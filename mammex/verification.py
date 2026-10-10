"""Vérification automatique de la base de connaissances (interface expert).

Contrôles :
  1. structure et syntaxe (références, CF entre 0 et 1, niveaux cohérents) ;
  2. contradictions (même prémisse → conclusions opposées) ;
  3. redondances (même prémisse ou prémisse incluse → même conclusion : CF comptés deux fois) ;
  4. trous de couverture (profils pour lesquels le système ne conclut rien) ;
  5. règles jamais déclenchées ;
  6. non-régression sur les cas de référence.
"""
from __future__ import annotations

import copy
import itertools
import random

from . import base as base_mod
from . import dsl
from .dsl import fmt, ge
from .moteur import ErreurBase, Moteur

ATOMES_TYPES = ("fait", "floue", "egal")


def _references(kb):
    oui_non = {q["id"] for q in kb.get("questions", []) if q.get("type") == "oui_non"}
    inter = {f["id"] for f in kb.get("faits_intermediaires", [])}
    choix = {}
    for q in kb.get("questions", []):
        if q.get("type") == "choix":
            vals = {o["id"] for o in q.get("options", [])}
            if q.get("valeur_si_parent_non"):
                vals.add(q["valeur_si_parent_non"])
            choix[q["id"]] = vals
    floues = {v["id"]: {e["id"] for e in v.get("ensembles", [])} for v in kb.get("variables_floues", [])}
    arriere = {q["id"] for q in kb.get("questions", []) if q.get("phase") == "chainage_arriere"}
    return oui_non, inter, choix, floues, arriere


def analyser_premisse(kb, texte, niveau=None):
    """Analyse d'une prémisse pour l'éditeur : syntaxe + références."""
    try:
        arbre = dsl.analyser(texte)
    except dsl.ErreurSyntaxe as e:
        return {"ok": False, "erreurs": [str(e)], "avertissements": []}
    erreurs, avert = _verifier_feuilles(kb, arbre, niveau)
    m = None
    try:
        m = Moteur(kb)
    except Exception:  # base en cours d'édition : pas grave pour l'affichage
        pass
    lisible = None
    if m:
        lisible = m.texte_premisse({"id": "_", "premisse": texte})
    return {"ok": not erreurs, "erreurs": erreurs, "avertissements": avert,
            "normalisee": dsl.texte(arbre), "lisible": lisible}


def _verifier_feuilles(kb, arbre, niveau):
    oui_non, inter, choix, floues, arriere = _references(kb)
    erreurs, avert = [], []
    for f in dsl.feuilles(arbre):
        if f[0] == "fait":
            if f[1] not in oui_non and f[1] not in inter:
                if f[1] in choix:
                    erreurs.append(f"« {f[1]} » est une question à choix : écrire « {f[1]} = valeur »")
                else:
                    erreurs.append(f"Fait inconnu « {f[1]} »")
            elif niveau == 2 and f[1] not in inter and f[1] not in arriere:
                avert.append(f"Le niveau 2 ne devrait lire que les faits intermédiaires et la biopsie (« {f[1]} »)")
            elif niveau == 1 and f[1] in inter:
                avert.append(f"Règle de niveau 1 qui lit un fait intermédiaire (« {f[1]} ») : chaînage interne au niveau 1")
        elif f[0] == "floue":
            if f[1] not in floues:
                erreurs.append(f"Variable floue inconnue « {f[1]} »")
            elif f[2] not in floues[f[1]]:
                erreurs.append(f"Ensemble flou inconnu « {f[2]} » pour « {f[1]} »")
            elif niveau == 2:
                avert.append("Le niveau 2 ne devrait pas lire de donnée brute (variable floue)")
        elif f[0] == "egal":
            if f[1] not in choix:
                erreurs.append(f"« {f[1]} » n'est pas une question à choix")
            elif f[2] not in choix[f[1]]:
                erreurs.append(f"Valeur « {f[2]} » impossible pour « {f[1]} » (valeurs : {', '.join(sorted(choix[f[1]]))})")
    return erreurs, avert


def _controle(cid, titre, ok_texte, erreurs=None, alertes=None, infos=None):
    erreurs, alertes, infos = erreurs or [], alertes or [], infos or []
    statut = "erreur" if erreurs else ("alerte" if alertes else "ok")
    return {"id": cid, "titre": titre, "statut": statut, "resume": ok_texte if statut == "ok" else None,
            "erreurs": erreurs, "alertes": alertes, "infos": infos}


# ---------------------------------------------------------------------------- 1. structure

def controle_structure(kb):
    err, al = [], []
    for section in ("regles", "questions", "faits_intermediaires", "diagnostics", "meta_regles", "heuristiques"):
        ids = [x.get("id") for x in kb.get(section, [])]
        doublons = sorted({i for i in ids if ids.count(i) > 1})
        if doublons:
            err.append(f"{section} : identifiants en double {', '.join(map(str, doublons))}")
        if any(not i for i in ids):
            err.append(f"{section} : un élément n'a pas d'identifiant")
    inter = {f["id"] for f in kb.get("faits_intermediaires", [])}
    diags = {d["id"] for d in kb.get("diagnostics", [])}
    etapes = {e["id"] for e in kb.get("etapes", [])}
    for q in kb.get("questions", []):
        if q.get("etape") not in etapes:
            err.append(f"Question {q.get('id')} : étape « {q.get('etape')} » inconnue")
        if q.get("type") not in ("oui_non", "nombre", "choix"):
            err.append(f"Question {q.get('id')} : type « {q.get('type')} » inconnu")
        if q.get("type") == "choix" and not q.get("options"):
            err.append(f"Question {q.get('id')} : aucune option de réponse")
        if not (q.get("texte") or "").strip():
            err.append(f"Question {q.get('id')} : texte vide")
    for r in kb.get("regles", []):
        rid = r.get("id", "?")
        try:
            cf = float(r.get("cf"))
            if not 0 <= cf <= 1:
                err.append(f"{rid} : CF {cf} hors de [0 ; 1]")
        except (TypeError, ValueError):
            err.append(f"{rid} : CF manquant ou non numérique")
        niveau = r.get("niveau")
        if niveau not in (1, 2):
            err.append(f"{rid} : niveau doit valoir 1 ou 2")
        if niveau == 1 and r.get("conclusion") not in inter:
            err.append(f"{rid} : une règle de niveau 1 doit conclure un fait intermédiaire (« {r.get('conclusion')} »)")
        if niveau == 2 and r.get("conclusion") not in diags:
            err.append(f"{rid} : une règle de niveau 2 doit conclure un diagnostic (« {r.get('conclusion')} »)")
        if niveau == 2 and r.get("actif", True) and not (r.get("recommandation") or "").strip():
            al.append(f"{rid} : aucune recommandation associée")
        try:
            arbre = dsl.analyser(r.get("premisse", ""))
            e, a = _verifier_feuilles(kb, arbre, niveau)
            err += [f"{rid} : {x}" for x in e]
            al += [f"{rid} : {x}" for x in a]
        except dsl.ErreurSyntaxe as e:
            err.append(f"{rid} : prémisse invalide — {e}")
    ids2 = {r["id"] for r in kb.get("regles", []) if r.get("niveau") == 2 and r.get("actif", True)}
    ids_toutes = {r.get("id") for r in kb.get("regles", [])}
    h = {x["id"]: x for x in kb.get("heuristiques", [])}
    ordre = h.get("H1", {}).get("parametres", {}).get("ordre", [])
    for rid in ordre:
        if rid not in ids_toutes:
            err.append(f"H1 : la règle {rid} de l'ordre de test n'existe pas")
    for rid in sorted(ids2 - set(ordre)):
        al.append(f"H1 : la règle {rid} n'est pas placée dans l'ordre de test (elle sera testée en dernier)")
    mr = {x["id"]: x for x in kb.get("meta_regles", [])}
    for rid in mr.get("MR2", {}).get("parametres", {}).get("regles_histologie", []):
        if rid not in ids_toutes:
            err.append(f"MR2 : la règle {rid} n'existe pas")
    for rid in mr.get("MR4", {}).get("parametres", {}).get("regles_desactivees", []):
        if rid not in ids_toutes:
            err.append(f"MR4 : la règle {rid} n'existe pas")
    for c in mr.get("MR4", {}).get("parametres", {}).get("conditions", []):
        if c.get("fait") not in inter:
            err.append(f"MR4 : fait « {c.get('fait')} » inconnu")
    if mr.get("MR5") and mr["MR5"].get("parametres", {}).get("fait") not in inter:
        err.append("MR5 : fait surveillé inconnu")
    for c in h.get("H4", {}).get("parametres", {}).get("conditions", []):
        if c.get("fait") not in inter:
            err.append(f"H4 : fait « {c.get('fait')} » inconnu")
    for e in h.get("H4", {}).get("parametres", {}).get("ordre_etapes", []):
        if e not in etapes:
            err.append(f"H4 : étape « {e} » inconnue")
    for v in kb.get("variables_floues", []):
        if not v.get("ensembles"):
            err.append(f"Variable floue {v.get('id')} : aucun ensemble défini")
        for e in v.get("ensembles", []):
            nom = f"Variable floue {v.get('id')} / {e.get('id')}"
            try:
                if e.get("points"):
                    xs = [float(x) for x, _ in e["points"]]
                    mus = [float(m) for _, m in e["points"]]
                    if len(xs) < 2:
                        err.append(f"{nom} : au moins deux points sont nécessaires")
                    elif any(b <= a for a, b in zip(xs, xs[1:])):
                        err.append(f"{nom} : les abscisses des points doivent être strictement croissantes")
                    if any(not 0 <= m <= 1 for m in mus):
                        err.append(f"{nom} : les degrés d'appartenance μ doivent être compris entre 0 et 1")
                    elif max(mus) < 1:
                        al.append(f"{nom} : la fonction n'atteint jamais μ = 1 (ensemble non normalisé)")
                elif float(e["debut"]) >= float(e["fin"]):
                    err.append(f"{nom} : le début doit être inférieur à la fin")
            except (KeyError, TypeError, ValueError):
                err.append(f"{nom} : définition de la fonction d'appartenance invalide")
    p = kb.get("parametres", {})
    try:
        if not 0 <= float(p.get("seuil_activation")) <= 1:
            err.append("Seuil d'activation hors de [0 ; 1]")
        for k, v in p.get("certitudes", {}).items():
            if not 0 <= float(v) <= 1:
                err.append(f"Certitude « {k} » hors de [0 ; 1]")
    except (TypeError, ValueError):
        err.append("Paramètres généraux non numériques")
    return _controle("structure", "Structure et syntaxe", "Toutes les règles sont bien formées et leurs références existent.", err, al)


# ---------------------------------------------------------------------------- 2-3. contradiction / redondance

def _opposes(kb, c1, c2):
    inter = {f["id"]: f for f in kb.get("faits_intermediaires", [])}
    diag = {d["id"]: d for d in kb.get("diagnostics", [])}
    if c1 in inter and inter[c1].get("oppose") == c2:
        return True
    if c2 in inter and inter[c2].get("oppose") == c1:
        return True
    g = {diag.get(c1, {}).get("gravite"), diag.get(c2, {}).get("gravite")}
    return g == {"rouge", "vert"}


def _termes(arbre, op):
    n = dsl.normaliser(arbre)
    return set(n[1]) if n[0] == op else {n}


def controles_logiques(kb):
    regles = []
    for r in kb.get("regles", []):
        if not r.get("actif", True):
            continue
        try:
            regles.append((r, dsl.analyser(r["premisse"])))
        except (dsl.ErreurSyntaxe, KeyError):
            continue
    contra, redon, internes = [], [], []
    for (r1, a1), (r2, a2) in itertools.combinations(regles, 2):
        n1, n2 = dsl.normaliser(a1), dsl.normaliser(a2)
        if n1 == n2:
            if r1["conclusion"] == r2["conclusion"]:
                redon.append(f"{r1['id']} et {r2['id']} ont la même prémisse et la même conclusion : leurs CF seraient comptés deux fois.")
            elif _opposes(kb, r1["conclusion"], r2["conclusion"]):
                contra.append(f"{r1['id']} et {r2['id']} : même prémisse « {dsl.texte(a1)} » mais conclusions opposées "
                              f"({r1['conclusion']} / {r2['conclusion']}).")
            continue
        if r1["conclusion"] == r2["conclusion"]:
            for (ra, aa), (rb, ab) in (((r1, a1), (r2, a2)), ((r2, a2), (r1, a1))):
                ta, tb = _termes(aa, "et"), _termes(ab, "et")
                if tb < ta and len(tb) >= 1 and dsl.normaliser(ab)[0] != "ou":
                    redon.append(f"{ra['id']} est incluse dans {rb['id']} (mêmes conditions + d'autres) pour la même conclusion : "
                                 "les CF se cumuleront sur les mêmes indices.")
                oa, ob = _termes(aa, "ou"), _termes(ab, "ou")
                if dsl.normaliser(aa)[0] == "ou" and dsl.normaliser(ab)[0] == "ou" and oa < ob:
                    redon.append(f"Les signes de {ra['id']} sont tous déjà dans {rb['id']} (même conclusion) : double comptage possible.")
        elif _opposes(kb, r1["conclusion"], r2["conclusion"]):
            ta, tb = _termes(a1, "et"), _termes(a2, "et")
            if ta <= tb or tb <= ta:
                plus = r1 if len(ta) < len(tb) else r2
                contra.append(f"{r1['id']} et {r2['id']} peuvent se déclencher ensemble sur les mêmes indices avec des conclusions "
                              f"opposées ({r1['conclusion']} / {r2['conclusion']}) ; vérifier l'ordre H1 ou ajouter un NON dans {plus['id']}.")
    for r, a in regles:
        termes = _termes(a, "et")
        for t in termes:
            if ("non", t) in termes:
                internes.append(f"{r['id']} contient « X ET NON X » ({dsl.texte(t)}) : elle ne peut jamais être pleinement vraie.")
    c = _controle("contradiction", "Contradictions", "Pas de contradiction.", contra, internes)
    rd = _controle("redondance", "Redondances", "Pas de redondance.", None, redon)
    return c, rd


# ---------------------------------------------------------------------------- 4-5. couverture et règles mortes

def _bande(v):
    return {0.0: "absent", 0.3: "faible", 0.6: "modéré", 0.9: "fort"}.get(v, fmt(v))


def controle_couverture(kb):
    inter = kb.get("faits_intermediaires", [])
    mr = {x["id"]: x for x in kb.get("meta_regles", [])}
    fait_bio = mr.get("MR2", {}).get("parametres", {}).get("fait_biopsie", "biopsie_resultat")
    qbio = next((q for q in kb.get("questions", []) if q["id"] == fait_bio), None)
    biopsies = [("non réalisée", {})]
    if qbio:
        parents = (qbio.get("afficher_si") or {}).get("oui", [])
        biopsies = [("non réalisée", {p: {"valeur": "non"} for p in parents})]
        for o in qbio.get("options", []):
            rep = {p: {"valeur": "oui"} for p in parents}
            rep[fait_bio] = {"valeur": o["id"]}
            biopsies.append((o["libelle"].lower(), rep))
    valeurs = [0.0, 0.3, 0.6, 0.9]
    trous, declenchees = [], set()
    nb_profils = 0
    for combo in itertools.product(valeurs, repeat=len(inter)):
        faits = {f["id"]: v for f, v in zip(inter, combo)}
        if any(f.get("oppose") and ge(faits[f["id"]], 0.4) and ge(faits.get(f["oppose"]), 0.4) for f in inter):
            continue  # deux faits opposés tous deux établis : profil incohérent
        for nom_bio, rep in biopsies:
            nb_profils += 1
            m = Moteur(kb, reponses=rep, faits_injectes=faits, demander=False)
            res = m.executer()["resultat"]
            for t in res["trace_niveau2"]:
                if t["statut"] == "declenchee":
                    declenchees.add(t["regle"])
            if res["hypothese"]["id"] == "indetermine":
                desc = [f"{f['libelle']} {fmt(faits[f['id']], 1)}" for f in inter if faits[f["id"]] > 0]
                profil = ", ".join(desc) or "aucun fait établi (pas d'imagerie concluante)"
                couvert = any(r["source"] == "MR5" for r in res["recommandations"])
                trous.append({"profil": profil, "bio": nom_bio, "couvert_mr5": couvert, "poids": sum(combo)})
    groupes = {}
    for t in trous:
        if t["couvert_mr5"]:
            continue
        g = groupes.setdefault(t["profil"], {"bios": [], "poids": t["poids"]})
        g["bios"].append(t["bio"])
    tries = sorted(groupes.items(), key=lambda kv: -kv[1]["poids"])
    alertes = [f"Trou de couverture : {p} — biopsie {' / '.join(g['bios'])}" for p, g in tries[:10]]
    if len(tries) > 10:
        alertes.append(f"… et {len(tries) - 10} autres profils sans conclusion (signes plus faibles).")
    non_couverts = [t for t in trous if not t["couvert_mr5"]]
    infos = [f"{nb_profils} profils testés (faits intermédiaires à 0 / 0,3 / 0,6 / 0,9 × résultats de biopsie)."]
    nb_mr5 = len(trous) - len(non_couverts)
    if nb_mr5:
        infos.append(f"{nb_mr5} profils « indéterminé » à terrain à risque sont pris en charge par MR5 (oncogénétique + surveillance) : comportement voulu (cas 5).")
    return _controle("couverture", "Couverture", "Tous les profils testés aboutissent à une conclusion.", None, alertes, infos), declenchees


def _reponses_aleatoires(kb, rnd):
    rep = {}
    for q in kb["questions"]:
        if q["type"] == "nombre":
            rep[q["id"]] = {"valeur": rnd.randint(int(q.get("min", 20)) + 15, int(q.get("max", 90)) - 25)}
        elif q["type"] == "choix":
            rep[q["id"]] = {"valeur": rnd.choice([o["id"] for o in q["options"]] + ["jnsp"]), "fois": 2}
        else:
            v = rnd.choices(["non", "oui", "jnsp"], weights=[5, 4, 1])[0]
            rep[q["id"]] = {"valeur": v, "certitude": rnd.choice(["certain", "probable", "possible"]), "fois": 2}
    return rep


def controle_regles_mortes(kb, declenchees_n2):
    rnd = random.Random(42)
    declenchees = set(declenchees_n2)
    for _ in range(600):
        m = Moteur(kb, reponses=_reponses_aleatoires(kb, rnd), demander=False)
        m.niveau1()
        declenchees |= {e["regle"] for e in m.trace1}
    mortes = [r["id"] for r in kb["regles"] if r.get("actif", True) and r["id"] not in declenchees]
    al = [f"{rid} ne s'est déclenchée sur aucun des profils simulés : prémisse impossible ou toujours bloquée par une méta-règle."
          for rid in mortes]
    inactives = [r["id"] for r in kb["regles"] if not r.get("actif", True)]
    infos = [f"Règles désactivées par l'expert : {', '.join(inactives)}"] if inactives else []
    return _controle("mortes", "Règles jamais déclenchées", "Chaque règle se déclenche au moins sur un profil simulé.", None, al, infos)


# ---------------------------------------------------------------------------- 6. cas de référence

def verifier_cas(kb):
    lignes = []
    for cas in base_mod.charger_cas():
        att = cas["attendu"]
        try:
            r = Moteur(kb, cas["reponses"], demander=False).executer()
            if r["etat"] != "resultat":
                obtenu, cf = f"question « {r['question']['id']} »", None
            else:
                obtenu, cf = r["resultat"]["hypothese"]["id"], r["resultat"]["hypothese"]["cf"]
        except (ErreurBase, KeyError, ValueError, TypeError) as e:
            obtenu, cf = f"erreur : {e}", None
        ok = obtenu == att["diagnostic"] and fmt(cf) == fmt(att["cf"]) if att["cf"] is not None else obtenu == att["diagnostic"] and cf is None
        lignes.append({"id": cas["id"], "titre": cas["titre"], "attendu": att["diagnostic"], "cf_attendu": fmt(att["cf"]) if att["cf"] is not None else "—",
                       "obtenu": obtenu, "cf_obtenu": fmt(cf) if cf is not None else "—", "ok": ok})
    return {"ok": all(x["ok"] for x in lignes), "lignes": lignes}


# ---------------------------------------------------------------------------- tout

def verifier(kb):
    kb = copy.deepcopy(kb)
    controles = [controle_structure(kb)]
    c, r = controles_logiques(kb)
    controles += [c, r]
    cas = None
    if controles[0]["statut"] != "erreur":
        try:
            couv, declenchees = controle_couverture(kb)
            controles.append(couv)
            controles.append(controle_regles_mortes(kb, declenchees))
            cas = verifier_cas(kb)
            ko = [x for x in cas["lignes"] if not x["ok"]]
            controles.append(_controle(
                "cas", "Cas de référence", f"Les {len(cas['lignes'])} cas de référence donnent le résultat attendu.",
                None,
                [f"{x['titre']} : attendu {x['attendu']} ({x['cf_attendu']}), obtenu {x['obtenu']} ({x['cf_obtenu']})" for x in ko]))
        except (ErreurBase, KeyError, ValueError, TypeError, ZeroDivisionError) as e:
            controles.append(_controle("execution", "Exécution du moteur", "", [f"Le moteur ne peut pas tourner sur cette base : {e}"]))
    return {
        "controles": controles,
        "cas": cas,
        "nb_erreurs": sum(len(c["erreurs"]) for c in controles),
        "nb_alertes": sum(len(c["alertes"]) for c in controles),
    }
