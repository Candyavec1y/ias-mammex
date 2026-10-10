"""Petit langage des prémisses de règles.

Syntaxe (mots-clés en MAJUSCULES) :
    fait                      fait booléen (réponse Oui/Non ou fait intermédiaire)
    variable EST ensemble     prémisse floue, ex. « age EST agee »
    fait = valeur             égalité sur une réponse à choix, ex. « biopsie_resultat = carcinome »
    NON x                     1 − CF
    a ET b                    minimum
    a OU b                    maximum
    ( ... )                   parenthèses ; ET est prioritaire sur OU

Arbre produit (tuples) :
    ("fait", id) · ("floue", variable, ensemble) · ("egal", id, valeur)
    ("non", x) · ("et", [x, y, ...]) · ("ou", [x, y, ...])
"""
from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP

EPS = 1e-9
MOTS_CLES = {"ET", "OU", "NON", "EST"}
_TOKEN = re.compile(r"\s*(?:(\()|(\))|(=)|([A-Za-zÀ-ÿ_][A-Za-z0-9À-ÿ_]*)|(\S))")


class ErreurSyntaxe(ValueError):
    pass


# --------------------------------------------------------------------------- format

def fmt(x, n: int = 2) -> str:
    """Nombre au format français, arrondi « au plus proche » (0,765 → 0,77)."""
    if x is None:
        return "?"
    d = Decimal(repr(round(float(x), 9))).quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP)
    return str(d).replace(".", ",")


def fmt_nombre(x) -> str:
    if x is None:
        return "?"
    if float(x).is_integer():
        return str(int(x))
    return fmt(x, 1)


def ge(a, b) -> bool:
    return a is not None and a >= b - EPS


# --------------------------------------------------------------------------- analyse

def _tokeniser(texte: str):
    jetons = []
    pos = 0
    texte = texte.strip()
    while pos < len(texte):
        m = _TOKEN.match(texte, pos)
        if not m or m.end() == pos:
            break
        if m.group(5):
            raise ErreurSyntaxe(f"Caractère inattendu « {m.group(5)} »")
        jetons.append(m.group(1) or m.group(2) or m.group(3) or m.group(4))
        pos = m.end()
    return jetons


class _Analyseur:
    def __init__(self, jetons):
        self.j = jetons
        self.i = 0

    def voir(self):
        return self.j[self.i] if self.i < len(self.j) else None

    def prendre(self, attendu=None):
        t = self.voir()
        if t is None:
            raise ErreurSyntaxe("Prémisse incomplète" + (f" : « {attendu} » attendu" if attendu else ""))
        if attendu and t != attendu:
            raise ErreurSyntaxe(f"« {attendu} » attendu, « {t} » trouvé")
        self.i += 1
        return t

    def expr(self):
        enfants = [self.et()]
        while self.voir() == "OU":
            self.prendre()
            enfants.append(self.et())
        return enfants[0] if len(enfants) == 1 else ("ou", enfants)

    def et(self):
        enfants = [self.unaire()]
        while self.voir() == "ET":
            self.prendre()
            enfants.append(self.unaire())
        return enfants[0] if len(enfants) == 1 else ("et", enfants)

    def unaire(self):
        t = self.voir()
        if t == "NON":
            self.prendre()
            return ("non", self.unaire())
        if t == "(":
            self.prendre()
            e = self.expr()
            self.prendre(")")
            return e
        return self.atome()

    def atome(self):
        t = self.prendre()
        if t in MOTS_CLES or t in ("(", ")", "="):
            raise ErreurSyntaxe(f"Nom de fait attendu, « {t} » trouvé")
        if self.voir() == "EST":
            self.prendre()
            ens = self.prendre()
            if ens in MOTS_CLES or ens in ("(", ")", "="):
                raise ErreurSyntaxe("Ensemble flou attendu après EST")
            return ("floue", t, ens)
        if self.voir() == "=":
            self.prendre()
            val = self.prendre()
            if val in MOTS_CLES or val in ("(", ")", "="):
                raise ErreurSyntaxe("Valeur attendue après =")
            return ("egal", t, val)
        return ("fait", t)


def analyser(texte: str):
    if not texte or not texte.strip():
        raise ErreurSyntaxe("Prémisse vide")
    a = _Analyseur(_tokeniser(texte))
    arbre = a.expr()
    if a.voir() is not None:
        raise ErreurSyntaxe(f"Élément en trop : « {a.voir()} »")
    return arbre


def feuilles(arbre):
    """Liste des atomes (fait / floue / egal) d'un arbre."""
    t = arbre[0]
    if t in ("fait", "floue", "egal"):
        return [arbre]
    if t == "non":
        return feuilles(arbre[1])
    out = []
    for e in arbre[1]:
        out.extend(feuilles(e))
    return out


def texte(arbre, parent=None) -> str:
    t = arbre[0]
    if t == "fait":
        return arbre[1]
    if t == "floue":
        return f"{arbre[1]} EST {arbre[2]}"
    if t == "egal":
        return f"{arbre[1]} = {arbre[2]}"
    if t == "non":
        return "NON " + texte(arbre[1], "non")
    op = " ET " if t == "et" else " OU "
    s = op.join(texte(e, t) for e in arbre[1])
    if parent in ("et", "non") and t == "ou" or parent == "non" and t == "et":
        s = f"({s})"
    return s


def normaliser(arbre):
    """Forme canonique (ET/OU aplatis et triés) pour comparer deux prémisses."""
    t = arbre[0]
    if t in ("fait", "floue", "egal"):
        return arbre
    if t == "non":
        return ("non", normaliser(arbre[1]))
    enfants = []
    for e in arbre[1]:
        n = normaliser(e)
        if n[0] == t:
            enfants.extend(n[1])
        else:
            enfants.append(n)
    uniques = sorted(set(enfants), key=repr)
    return (t, tuple(uniques)) if len(uniques) > 1 else uniques[0]


# --------------------------------------------------------------------------- évaluation

class Evaluation:
    __slots__ = ("cf", "calcul", "complet")

    def __init__(self, cf, calcul, complet=True):
        self.cf = cf
        self.calcul = calcul
        self.complet = complet


def evaluer(arbre, ctx) -> Evaluation:
    """Évalue une prémisse.

    ctx doit fournir :
      ctx.fait(id)            -> (cf | None, complet: bool)
      ctx.floue(var, ens)     -> (mu | None, valeur | None)
      ctx.choix(id)           -> valeur | None
      ctx.noter(arbre, cf)    (mémorise les faits utilisés)

    Règles sur les faits absents (None) :
      ET : 0 si un terme connu vaut 0, sinon absent dès qu'un terme manque ;
      OU : maximum des termes connus (absent si aucun n'est connu) ;
      NON : absent si le fait est absent ou incomplet (on ne peut pas affirmer une absence).
    """
    t = arbre[0]
    if t == "fait":
        cf, complet = ctx.fait(arbre[1])
        ctx.noter(arbre, cf)
        return Evaluation(cf, fmt(cf), complet)
    if t == "floue":
        mu, x = ctx.floue(arbre[1], arbre[2])
        ctx.noter(arbre, mu)
        lib = getattr(ctx, "libelle_ensemble", lambda v, e: e)(arbre[1], arbre[2])
        return Evaluation(mu, f"μ{lib}({fmt_nombre(x)})")
    if t == "egal":
        val = ctx.choix(arbre[1])
        cf = None if val is None else (1.0 if val == arbre[2] else 0.0)
        ctx.noter(arbre, cf)
        return Evaluation(cf, fmt(cf))
    if t == "non":
        e = evaluer(arbre[1], ctx)
        if e.cf is None or not e.complet:
            return Evaluation(None, f"1 − {e.calcul}", False)
        return Evaluation(1.0 - e.cf, f"1 − {e.calcul}")
    evals = [evaluer(x, ctx) for x in arbre[1]]
    connus = [e.cf for e in evals if e.cf is not None]
    complet = all(e.complet for e in evals)
    if t == "et":
        calc = "min(" + " ; ".join(e.calcul for e in evals) + ")"
        if any(c <= EPS for c in connus):
            return Evaluation(0.0, calc, True)
        if len(connus) < len(evals):
            return Evaluation(None, calc, False)
        return Evaluation(min(connus), calc, complet)
    calc = "max(" + " ; ".join(e.calcul for e in evals) + ")"
    if not connus:
        return Evaluation(None, calc, False)
    return Evaluation(max(connus), calc, complet and len(connus) == len(evals))


def mu_rampe(x, debut, fin):
    if x is None:
        return None
    if x <= debut:
        return 0.0
    if x >= fin:
        return 1.0
    return (x - debut) / (fin - debut)
