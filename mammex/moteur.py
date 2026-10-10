"""Moteur d'inférence de MAMMEX.

Chaînage mixte :
  - niveau 1 en chaînage avant, jusqu'à saturation (MR1) ;
  - niveau 2 en chaînage arrière (comme MYCIN) : chaque hypothèse est prise dans
    l'ordre H1 (ou MR2) et le moteur cherche à la prouver ; s'il lui manque une
    donnée utile (biopsie) et que H4 la juge utile, il pose la question.

Le moteur est « rejoué » à chaque réponse : on lui donne toutes les réponses déjà
connues et il renvoie soit la prochaine question, soit le résultat complet avec
sa trace. La base de faits n'existe donc que le temps d'une consultation.
"""
from __future__ import annotations

from . import dsl
from .dsl import fmt, fmt_nombre, ge

GRAVITE_LIBELLE = {
    "rouge": "Gravité élevée",
    "orange": "À explorer",
    "vert": "Rassurant",
    "gris": "Indéterminé",
}


def calcul_regle(cf_regle, ev, resultat):
    """« 0,40 × μâgée(58) = 0,40 × 0,80 = 0,32 » (étape intermédiaire si le calcul n'est pas un simple nombre)."""
    if ev.calcul == fmt(ev.cf):
        return f"{fmt(cf_regle)} × {ev.calcul} = {fmt(resultat)}"
    return f"{fmt(cf_regle)} × {ev.calcul} = {fmt(cf_regle)} × {fmt(ev.cf)} = {fmt(resultat)}"


class QuestionRequise(Exception):
    def __init__(self, question_id, pourquoi, redemandee=False, regle=None):
        super().__init__(question_id)
        self.question_id = question_id
        self.pourquoi = pourquoi
        self.redemandee = redemandee
        self.regle = regle


class ErreurBase(Exception):
    pass


class Moteur:
    def __init__(self, kb, reponses=None, faits_injectes=None, demander=True):
        self.kb = kb
        self.reponses = dict(reponses or {})
        self.injectes = faits_injectes  # pour la vérification : faits intermédiaires imposés
        self.demander_autorise = demander
        p = kb["parametres"]
        self.seuil = float(p["seuil_activation"])
        self.certitudes = p["certitudes"]
        self.q = {q["id"]: q for q in kb["questions"]}
        self.inter = {f["id"]: f for f in kb["faits_intermediaires"]}
        self.diag = {d["id"]: d for d in kb["diagnostics"]}
        self.etapes = {e["id"]: e for e in kb["etapes"]}
        self.floues = {v["id"]: v for v in kb["variables_floues"]}
        self.regles = [r for r in kb["regles"] if r.get("actif", True)]
        self.regle = {r["id"]: r for r in kb["regles"]}
        self.mr = {m["id"]: m for m in kb["meta_regles"]}
        self.h = {h["id"]: h for h in kb["heuristiques"]}
        self.arbres = {}
        for r in self.regles:
            try:
                self.arbres[r["id"]] = dsl.analyser(r["premisse"])
            except dsl.ErreurSyntaxe as e:
                raise ErreurBase(f"Règle {r['id']} : {e}")
        self.faits_inter = {}
        self.complet_inter = {}
        self.trace1 = []
        self.rejets1 = []

    # ------------------------------------------------------------------ utilitaires
    def mr_actif(self, mid):
        m = self.mr.get(mid)
        return m is not None and m.get("actif", True)

    def mr_param(self, mid, cle, defaut=None):
        return (self.mr.get(mid) or {}).get("parametres", {}).get(cle, defaut)

    def h_param(self, hid, cle, defaut=None):
        return (self.h.get(hid) or {}).get("parametres", {}).get(cle, defaut)

    def lecture(self, cf):
        if cf is None:
            return "non renseigné"
        for palier in sorted(self.kb["parametres"]["lecture_cf"], key=lambda x: -x["min"]):
            if ge(cf, palier["min"]):
                return palier["texte"]
        return "non retenu"

    def libelle_fait(self, fid):
        if fid in self.inter:
            return self.inter[fid]["libelle"]
        q = self.q.get(fid)
        if q:
            return q.get("libelle") or q["texte"]
        return fid

    def libelle_feuille(self, arbre):
        if arbre[0] == "fait":
            return self.libelle_fait(arbre[1])
        if arbre[0] == "floue":
            var = self.floues.get(arbre[1], {})
            ens = next((e for e in var.get("ensembles", []) if e["id"] == arbre[2]), {})
            return f"{var.get('libelle', arbre[1])} EST {ens.get('libelle', arbre[2])}"
        q = self.q.get(arbre[1], {})
        opt = next((o for o in q.get("options", []) if o["id"] == arbre[2]), None)
        return f"{q.get('libelle', arbre[1])} = {opt['libelle'] if opt else arbre[2]}"

    def texte_premisse(self, r):
        """Prémisse en langage médical."""
        def rendu(a, parent=None):
            t = a[0]
            if t in ("fait", "floue", "egal"):
                return self.libelle_feuille(a)
            if t == "non":
                return "NON " + rendu(a[1], "non")
            s = (" ET " if t == "et" else " OU ").join(rendu(x, t) for x in a[1])
            return f"({s})" if parent in ("et", "non") and t == "ou" or parent == "non" else s
        return rendu(self.arbres.get(r["id"]) or dsl.analyser(r["premisse"]))

    # ------------------------------------------------------------------ réponses brutes
    def _val(self, qid):
        r = self.reponses.get(qid)
        return None if r is None else r.get("valeur")

    def visible(self, q):
        ms = q.get("masquer_si") or {}
        for qid in ms.get("non", []):
            if self._val(qid) == "non":
                return False
        for qid in ms.get("oui", []):
            if self._val(qid) == "oui":
                return False
        aff = q.get("afficher_si") or {}
        for qid in aff.get("oui", []):
            if self._val(qid) != "oui":
                return False
        return True

    def valeur_brute(self, qid):
        q = self.q[qid]
        if q["type"] == "choix":
            for parent in (q.get("afficher_si") or {}).get("oui", []):
                if self._val(parent) == "non":
                    return q.get("valeur_si_parent_non")
                if self._val(parent) != "oui":
                    return None
            v = self._val(qid)
            return None if v in (None, "jnsp") else v
        if not self.visible(q):
            # question sans objet (ex. « nodule fixé » sans nodule dur, « aucune anomalie »
            # alors qu'une masse est décrite) : le fait est logiquement faux
            return 0.0 if q["type"] == "oui_non" and q.get("masquer_si") else None
        r = self.reponses.get(qid)
        if r is None:
            return None
        v = r.get("valeur")
        if q["type"] == "nombre":
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
        if v == "oui":
            if q.get("certitude", True):
                return float(self.certitudes.get(r.get("certitude") or "certain", 1.0))
            return 1.0
        if v == "non":
            return 0.0
        return None

    def est_repondue(self, qid):
        return qid in self.reponses

    # ------------------------------------------------------------------ contexte d'évaluation
    class _Ctx:
        def __init__(self, moteur, niveau, regle=None):
            self.m = moteur
            self.niveau = niveau
            self.regle = regle
            self.utilises = []

        def noter(self, arbre, cf):
            self.utilises.append({"fait": dsl.texte(arbre), "libelle": self.m.libelle_feuille(arbre), "cf": cf})

        def fait(self, fid):
            m = self.m
            if fid in m.inter:
                if fid in m.faits_inter:
                    return m.faits_inter[fid], m.complet_inter.get(fid, True)
                if m.complet_inter.get(fid):
                    return 0.0, True
                return None, False
            if fid in m.q:
                self.demander_si_utile(fid)
                return m.valeur_brute(fid), True
            raise ErreurBase(f"Fait inconnu « {fid} »")

        def libelle_ensemble(self, var, ens):
            v = self.m.floues.get(var, {})
            e = next((x for x in v.get("ensembles", []) if x["id"] == ens), {})
            return e.get("libelle", ens)

        def floue(self, var, ens):
            m = self.m
            v = m.floues.get(var)
            if v is None:
                raise ErreurBase(f"Variable floue inconnue « {var} »")
            e = next((x for x in v["ensembles"] if x["id"] == ens), None)
            if e is None:
                raise ErreurBase(f"Ensemble flou inconnu « {var} EST {ens} »")
            x = m.valeur_brute(var) if var in m.q else None
            return dsl.mu_rampe(x, float(e["debut"]), float(e["fin"])), x

        def choix(self, qid):
            if qid not in self.m.q:
                raise ErreurBase(f"Fait inconnu « {qid} »")
            self.demander_si_utile(qid)
            return self.m.valeur_brute(qid)

        def demander_si_utile(self, qid):
            """Chaînage arrière : si la donnée manque et que H4 la juge utile, poser la question."""
            m = self.m
            if self.niveau != 2 or not m.demander_autorise:
                return
            q = m.q[qid]
            if q.get("phase") != "chainage_arriere":
                return
            # question parente d'abord (ex. « biopsie faite ? » avant « résultat »)
            for parent in (q.get("afficher_si") or {}).get("oui", []):
                if not m.est_repondue(parent):
                    if m.h4_autorise(parent):
                        raise QuestionRequise(parent, m.pourquoi_chainage(parent, self.regle), regle=self.regle["id"])
                    return
                if m._val(parent) != "oui":
                    return
            if not m.est_repondue(qid) and m.h4_autorise(qid):
                raise QuestionRequise(qid, m.pourquoi_chainage(qid, self.regle), regle=self.regle["id"])

    def h4_autorise(self, qid):
        if qid not in (self.h_param("H4", "questions_conditionnees", []) or []):
            return True
        for c in self.h_param("H4", "conditions", []) or []:
            if ge(self.faits_inter.get(c["fait"]), float(c["seuil"])):
                return True
        return False

    def pourquoi_chainage(self, qid, regle):
        q = self.q[qid]
        d = self.diag.get(regle["conclusion"], {})
        verbe = {"biopsie_faite": "si une biopsie a été faite"}.get(qid, f"« {q.get('libelle', q['texte'])} »")
        return (f"Je vous demande {verbe} car je cherche à prouver « {d.get('libelle', regle['conclusion'])} » "
                f"({regle['id']} : SI {self.texte_premisse(regle)}).")

    def pourquoi_recueil(self, qid):
        q = self.q[qid]
        morceaux = []
        for r in self.regles:
            arbre = self.arbres[r["id"]]
            if any(f[1] == qid for f in dsl.feuilles(arbre)):
                concl = self.inter.get(r["conclusion"]) or self.diag.get(r["conclusion"]) or {}
                morceaux.append(f"« {concl.get('libelle', r['conclusion'])} » ({r['id']} : SI {self.texte_premisse(r)}, CF {fmt(r['cf'], 2)})")
        if not morceaux:
            return "Cette donnée n'est utilisée par aucune règle active ; elle figure dans le rapport."
        return "Je vous pose cette question car je cherche à établir " + " ; et ".join(morceaux) + "."

    # ------------------------------------------------------------------ phase de recueil (H4)
    def question_recueil(self):
        ordre = self.h_param("H4", "ordre_etapes", [e["id"] for e in self.kb["etapes"]])
        for etape in ordre:
            for q in self.kb["questions"]:
                if q["etape"] != etape or q.get("phase", "recueil") != "recueil":
                    continue
                if not self.visible(q):
                    continue
                if q["id"] not in self.reponses:
                    return QuestionRequise(q["id"], self.pourquoi_recueil(q["id"]))
        return None

    # ------------------------------------------------------------------ niveau 1 : chaînage avant
    def niveau1(self):
        regles1 = [r for r in self.regles if r["niveau"] == 1]
        if self.injectes is not None:
            for fid in self.inter:
                v = self.injectes.get(fid)
                if v is not None:
                    self.faits_inter[fid] = v
                self.complet_inter[fid] = v is not None
            return
        # un fait intermédiaire est « complet » si toutes les règles qui le concluent sont évaluables
        executees = set()
        cycle = 0
        while True:
            self._maj_completude(regles1)
            cycle += 1
            conflits = []
            for r in regles1:
                if r["id"] in executees:
                    continue
                ctx = self._Ctx(self, 1, r)
                ev = dsl.evaluer(self.arbres[r["id"]], ctx)
                if ge(ev.cf, self.seuil):
                    conflits.append((r, ev, ctx.utilises))
            if not conflits:
                break
            r, ev, utilises = conflits[0]  # sélection : ordre de la base
            executees.add(r["id"])
            cf = float(r["cf"]) * ev.cf
            avant = self.faits_inter.get(r["conclusion"])
            if avant is None:
                nouveau, combinaison = cf, None
            else:
                nouveau = avant + cf * (1 - avant)
                combinaison = f"{fmt(avant)} + {fmt(cf)} × (1 − {fmt(avant)}) = {fmt(nouveau)}"
            self.faits_inter[r["conclusion"]] = nouveau
            self.trace1.append({
                "cycle": cycle,
                "regle": r["id"],
                "premisse": self.texte_premisse(r),
                "conclusion": r["conclusion"],
                "conclusion_libelle": self.libelle_fait(r["conclusion"]),
                "conflits": [c[0]["id"] for c in conflits],
                "cf_premisses": ev.cf,
                "calcul": calcul_regle(r["cf"], ev, cf),
                "cf": cf,
                "combinaison": combinaison,
                "cf_fait": nouveau,
                "faits": utilises,
            })
        self._maj_completude(regles1)
        for r in regles1:
            if r["id"] in executees:
                continue
            ctx = self._Ctx(self, 1, r)
            ev = dsl.evaluer(self.arbres[r["id"]], ctx)
            if ev.cf is None:
                raison = "non évaluable : données manquantes"
            else:
                raison = f"non déclenchée : prémisses {fmt(ev.cf)} < {fmt(self.seuil)}"
            self.rejets1.append({"regle": r["id"], "premisse": self.texte_premisse(r), "calcul": ev.calcul,
                                 "cf_premisses": ev.cf, "raison": raison,
                                 "conclusion_libelle": self.libelle_fait(r["conclusion"]), "faits": ctx.utilises})

    def _maj_completude(self, regles1):
        for fid in self.inter:
            prod = [r for r in regles1 if r["conclusion"] == fid]
            ok = bool(prod)
            for r in prod:
                ev = dsl.evaluer(self.arbres[r["id"]], self._Ctx(self, 1, r))
                if ev.cf is None or not ev.complet:
                    ok = False
            self.complet_inter[fid] = ok

    # ------------------------------------------------------------------ MR3
    def question_mr3(self):
        if not self.mr_actif("MR3") or self.injectes is not None:
            return None
        groupes = self.mr_param("MR3", "groupes", ["terrain", "clinique"])
        nmax = int(self.mr_param("MR3", "nombre_max_demandes", 2))
        for f in self.kb["faits_intermediaires"]:
            if f.get("groupe") not in groupes or self.complet_inter.get(f["id"]):
                continue
            for q in self.kb["questions"]:
                if q["etape"] != f["groupe"] or q.get("phase", "recueil") != "recueil" or not self.visible(q):
                    continue
                r = self.reponses.get(q["id"])
                if r and r.get("valeur") == "jnsp" and int(r.get("fois", 1)) < nmax:
                    return QuestionRequise(
                        q["id"],
                        f"MR3 : « {f['libelle']} » n'est pas établi car cette donnée manque. "
                        "Aucune conclusion n'est produite sur un dossier incomplet : pouvez-vous la préciser ?",
                        redemandee=True)
        return None

    # ------------------------------------------------------------------ niveau 2 : chaînage arrière
    def biopsie_connue(self):
        fid = self.mr_param("MR2", "fait_biopsie", "biopsie_resultat")
        if fid not in self.q:
            return False
        v = self.valeur_brute(fid)
        return v is not None and v not in (self.mr_param("MR2", "valeurs_sans_resultat", []) or [])

    def mr4(self):
        if not self.mr_actif("MR4"):
            return False, []
        raisons = []
        for c in self.mr_param("MR4", "conditions", []) or []:
            v = self.faits_inter.get(c["fait"])
            if ge(v, float(c["seuil"])):
                raisons.append(f"{self.libelle_fait(c['fait'])} {fmt(v)} ≥ {fmt(c['seuil'], 1)}")
        return bool(raisons), raisons

    def niveau2(self):
        regles2 = [r for r in self.regles if r["niveau"] == 2]
        ids2 = [r["id"] for r in regles2]
        ordre = [rid for rid in self.h_param("H1", "ordre", []) if rid in ids2]
        ordre += [rid for rid in ids2 if rid not in ordre]
        mr2 = self.mr_actif("MR2") and self.biopsie_connue()
        histo = [rid for rid in (self.mr_param("MR2", "regles_histologie", []) or []) if rid in ids2]
        if mr2:
            ordre = histo + [rid for rid in ordre if rid not in histo]
        mr4_actif, mr4_raisons = self.mr4()
        desactivees = set(self.mr_param("MR4", "regles_desactivees", []) or []) if mr4_actif else set()
        seuil_h2 = float(self.h_param("H2", "seuil", 0.9))
        seuil_mr2 = float(self.mr_param("MR2", "seuil", 0.9))

        cf_diag, ordre_diag, regle_diag = {}, [], {}
        tests = []
        arret = None
        for i, rid in enumerate(ordre):
            r = self.regle[rid]
            entree = {"regle": rid, "premisse": self.texte_premisse(r), "conclusion": r["conclusion"],
                      "conclusion_libelle": self.diag.get(r["conclusion"], {}).get("libelle", r["conclusion"]),
                      "cf_regle": r["cf"]}
            if r["conclusion"] not in ordre_diag:
                ordre_diag.append(r["conclusion"])
            if arret:
                entree.update(statut="non_testee", raison=arret)
                tests.append(entree)
                continue
            if rid in desactivees:
                # on calcule ce qu'elle aurait donné, sans poser de question
                sauv = self.demander_autorise
                self.demander_autorise = False
                ctx = self._Ctx(self, 2, r)
                ev = dsl.evaluer(self.arbres[rid], ctx)
                self.demander_autorise = sauv
                sans = float(r["cf"]) * ev.cf if ge(ev.cf, self.seuil) else None
                txt = f" Sans cette méta-règle : {calcul_regle(r['cf'], ev, sans)}." if sans is not None else ""
                entree.update(statut="desactivee", raison="MR4 : " + " ; ".join(mr4_raisons) + "." + txt,
                              calcul=ev.calcul, faits=ctx.utilises, cf_sans_mr4=sans)
                tests.append(entree)
                continue
            ctx = self._Ctx(self, 2, r)
            ev = dsl.evaluer(self.arbres[rid], ctx)  # peut lever QuestionRequise
            entree.update(calcul=ev.calcul, faits=ctx.utilises, cf_premisses=ev.cf)
            if ev.cf is None:
                manquants = [u["libelle"] for u in ctx.utilises if u["cf"] is None]
                non_demandee = [u for u in ctx.utilises if u["cf"] is None and self._feuille_conditionnee(u["fait"])]
                if non_demandee and not any(self.est_repondue(q) for q in self.h_param("H4", "questions_conditionnees", []) or []):
                    entree.update(statut="non_testable", raison="Biopsie non demandée (H4 : elle ne changerait pas la décision).")
                else:
                    entree.update(statut="bloquee", raison="Données manquantes : " + ", ".join(dict.fromkeys(manquants)) + ".",
                                  manquants=list(dict.fromkeys(manquants)))
            elif not ge(ev.cf, self.seuil):
                entree.update(statut="echec" if ev.cf <= dsl.EPS else "non_declenchee",
                              raison=f"Prémisses {fmt(ev.cf)} < {fmt(self.seuil)} : règle non déclenchée.")
            else:
                cf = float(r["cf"]) * ev.cf
                d = r["conclusion"]
                avant = cf_diag.get(d)
                cf_diag[d] = cf if avant is None else avant + cf * (1 - avant)
                regle_diag.setdefault(d, rid)
                entree.update(statut="declenchee", cf=cf, calcul_complet=calcul_regle(r["cf"], ev, cf))
                if avant is not None:
                    entree["combinaison"] = f"{fmt(avant)} + {fmt(cf)} × (1 − {fmt(avant)}) = {fmt(cf_diag[d])}"
            tests.append(entree)
            # contrôle de l'arrêt
            if mr2 and rid in histo:
                if rid == histo[-1]:
                    if any(ge(cf_diag.get(self.regle[h]["conclusion"]), seuil_mr2) for h in histo):
                        arret = "MR2 : l'histologie tranche (CF ≥ " + fmt(seuil_mr2, 1) + "), R8 à R10 ne sont pas testées."
                continue
            if any(ge(v, seuil_h2) for v in cf_diag.values()):
                arret = f"H2 : arrêt sur certitude (une hypothèse atteint CF ≥ {fmt(seuil_h2, 1)})."
        return {"tests": tests, "cf_diag": cf_diag, "ordre_diag": ordre_diag, "regle_diag": regle_diag,
                "mr2": mr2, "mr4": (mr4_actif, mr4_raisons), "arret": arret, "ordre": ordre}

    def _feuille_conditionnee(self, texte_feuille):
        cond = set(self.h_param("H4", "questions_conditionnees", []) or [])
        nom = texte_feuille.split(" ")[0]
        return nom in cond

    # ------------------------------------------------------------------ exécution complète
    def executer(self):
        """Renvoie {"etat": "question", ...} ou {"etat": "resultat", ...}."""
        if self.injectes is None:
            q = self.question_recueil()
            if q:
                return self._paquet_question(q)
        self.niveau1()  # MR1 : saturer le niveau 1 avant d'ouvrir le niveau 2
        q = self.question_mr3()
        if q:
            return self._paquet_question(q)
        try:
            n2 = self.niveau2()
        except QuestionRequise as qr:
            return self._paquet_question(qr)
        return {"etat": "resultat", "resultat": self._conclure(n2)}

    def _paquet_question(self, qr):
        q = self.q[qr.question_id]
        ordre = self.h_param("H4", "ordre_etapes", [e["id"] for e in self.kb["etapes"]])
        etapes = [{"id": e, "libelle": self.etapes.get(e, {}).get("libelle", e)} for e in ordre]
        paquet = {k: q.get(k) for k in ("id", "etape", "type", "texte", "aide", "unite", "min", "max", "options", "libelle")}
        paquet["certitude"] = bool(q.get("certitude", True)) if q["type"] == "oui_non" else False
        paquet["etape_libelle"] = self.etapes.get(q["etape"], {}).get("libelle", q["etape"])
        paquet["etape_index"] = ordre.index(q["etape"]) if q["etape"] in ordre else 0
        paquet["pourquoi"] = qr.pourquoi
        paquet["redemandee"] = qr.redemandee
        paquet["deja"] = self.reponses.get(q["id"])
        if q["type"] == "nombre" and q["id"] in self.floues:
            paquet["floue"] = self.floues[q["id"]]
        return {"etat": "question", "question": paquet, "etapes": etapes}

    # ------------------------------------------------------------------ conclusion
    def _conclure(self, n2):
        seuil_ret = float(self.h_param("H1", "seuil_retenue", 0.4))
        cf_diag = n2["cf_diag"]
        retenu = next((d for d in n2["ordre_diag"] if ge(cf_diag.get(d), seuil_ret)), None)
        recommandations, alertes = [], []
        meta = [{"id": "MR1", "texte": "Niveau 1 saturé (chaînage avant) avant d'ouvrir le niveau 2."}]

        manquantes = self.donnees_manquantes(n2)
        bloquees = [t for t in n2["tests"] if t["statut"] == "bloquee"]

        if retenu:
            d = self.diag[retenu]
            rid = n2["regle_diag"][retenu]
            r = self.regle[rid]
            rec = r.get("recommandation_si_biopsie") if (r.get("recommandation_si_biopsie") and self.biopsie_connue()) else r.get("recommandation")
            if rec:
                recommandations.append({"texte": rec, "source": rid})
            hypothese = {"id": retenu, "libelle": d["libelle"], "gravite": d.get("gravite", "gris"),
                         "cf": cf_diag[retenu], "cf_texte": fmt(cf_diag[retenu]), "lecture": self.lecture(cf_diag[retenu]),
                         "regle": rid}
            heur = [{"id": "H1", "texte": f"« {d['libelle']} » est la première hypothèse (ordre du plus grave au plus rassurant) avec CF ≥ {fmt(seuil_ret, 1)}."}]
        else:
            hypothese = {"id": "indetermine", "libelle": "Indéterminé", "gravite": "gris", "cf": None, "cf_texte": "—",
                         "lecture": f"aucune hypothèse ≥ {fmt(seuil_ret, 1)}", "regle": None}
            raison = f"aucune hypothèse n'atteint CF {fmt(seuil_ret, 1)}"
            if bloquees:
                raison += " ; " + ", ".join(t["regle"] for t in bloquees) + " bloquée(s) par des données manquantes"
            heur = [{"id": "H5", "texte": f"Aucune conclusion fiable : {raison}."}]
            rec5 = self.h_param("H5", "recommandation")
            if rec5:
                recommandations.append({"texte": rec5, "source": "H5"})

        secondaires = []
        for dd in n2["ordre_diag"]:
            if dd == retenu or cf_diag.get(dd) is None:
                continue
            secondaires.append({"id": dd, "libelle": self.diag[dd]["libelle"], "gravite": self.diag[dd].get("gravite"),
                                "cf": cf_diag[dd], "cf_texte": fmt(cf_diag[dd]), "lecture": self.lecture(cf_diag[dd]),
                                "regle": n2["regle_diag"][dd]})

        if n2["mr2"]:
            meta.append({"id": "MR2", "texte": "Un résultat de biopsie est connu : règles d'histologie évaluées en premier."
                         + (" " + n2["arret"] if n2["arret"] and n2["arret"].startswith("MR2") else "")})
        mr3_rep = [qid for qid, r in self.reponses.items() if int(r.get("fois", 1)) > 1]
        if mr3_rep:
            meta.append({"id": "MR3", "texte": "Données de terrain ou de clinique redemandées avant d'ouvrir le niveau 2 : "
                         + ", ".join(self.libelle_fait(q) for q in mr3_rep) + "."})
        mr4_actif, mr4_raisons = n2["mr4"]
        if mr4_actif:
            regs = ", ".join(self.mr_param("MR4", "regles_desactivees", []))
            meta.append({"id": "MR4", "texte": f"{' ; '.join(mr4_raisons)} → {regs} désactivée : aucune conclusion rassurante n'est permise."})
            if hypothese["gravite"] not in ("rouge",):
                alertes.append({"niveau": "info", "texte": "Conclusion rassurante interdite (MR4) : " + " ; ".join(mr4_raisons) + "."})
        if self.mr_actif("MR5"):
            fid = self.mr_param("MR5", "fait", "risque_eleve")
            v = self.faits_inter.get(fid)
            if ge(v, float(self.mr_param("MR5", "seuil", 0.7))):
                recommandations.append({"texte": self.mr_param("MR5", "recommandation"), "source": "MR5"})
                meta.append({"id": "MR5", "texte": f"{self.libelle_fait(fid)} {fmt(v)} ≥ {fmt(self.mr_param('MR5', 'seuil'), 1)} → oncogénétique et surveillance renforcée ajoutées."})
        if n2["arret"] and n2["arret"].startswith("H2"):
            heur.append({"id": "H2", "texte": n2["arret"]})

        # H3 : prudence en cas de discordance clinique / imagerie
        s3 = float(self.h_param("H3", "seuil", 0.4))
        susp = self.faits_inter.get("suspicion_forte")
        rass = self.faits_inter.get("imagerie_rassurante")
        imsusp = self.faits_inter.get("imagerie_suspecte")
        if ge(susp, s3) and ge(rass, s3):
            alertes.append({"niveau": "attention", "texte": "Discordance radio-clinique : la clinique est inquiétante malgré une imagerie rassurante. "
                            "La conclusion la plus grave l'emporte (H3)."})
            heur.append({"id": "H3", "texte": "Clinique et imagerie se contredisent : la conclusion la plus grave est retenue."})
        elif ge(imsusp, s3) and self.complet_inter.get("suspicion_forte") and not ge(susp, self.seuil):
            alertes.append({"niveau": "attention", "texte": "Discordance radio-clinique : imagerie suspecte sans signe clinique. "
                            "La conclusion la plus grave l'emporte (H3)."})
            heur.append({"id": "H3", "texte": "Clinique et imagerie se contredisent : la conclusion la plus grave est retenue."})
        if "biopsie_resultat" in self.q and self.valeur_brute("biopsie_resultat") == "benigne":
            if retenu and self.diag[retenu].get("gravite") in ("rouge", "orange"):
                alertes.append({"niveau": "attention", "texte": "Biopsie bénigne discordante avec l'imagerie ou la clinique : "
                                "l'échantillon n'est peut-être pas représentatif."})
        for t in bloquees:
            alertes.append({"niveau": "attention", "texte": f"{t['regle']} bloquée : {t['raison']}"})
        q4 = [t for t in n2["tests"] if t["statut"] == "non_testable"]
        if q4:
            heur.append({"id": "H4", "texte": "Biopsie non demandée : elle ne pourrait pas changer la décision (ni imagerie suspecte, ni suspicion clinique ≥ 0,4)."})
        elif any(self.est_repondue(q) for q in self.h_param("H4", "questions_conditionnees", []) or []):
            heur.append({"id": "H4", "texte": "Biopsie demandée en dernier, car elle peut changer la décision."})

        return {
            "hypothese": hypothese,
            "gravite_libelle": GRAVITE_LIBELLE.get(hypothese["gravite"], ""),
            "recommandations": recommandations,
            "alertes": alertes,
            "donnees_manquantes": manquantes,
            "secondaires": secondaires,
            "faits_intermediaires": [
                {"id": f["id"], "libelle": f["libelle"], "cf": self.faits_inter.get(f["id"]),
                 "cf_texte": fmt(self.faits_inter.get(f["id"], 0.0 if self.complet_inter.get(f["id"]) else None)),
                 "lecture": self.lecture(self.faits_inter.get(f["id"], 0.0 if self.complet_inter.get(f["id"]) else None)),
                 "complet": self.complet_inter.get(f["id"], False)}
                for f in self.kb["faits_intermediaires"]],
            "trace_niveau1": self.trace1,
            "rejets_niveau1": self.rejets1,
            "trace_niveau2": n2["tests"],
            "ordre_niveau2": n2["ordre"],
            "meta_regles": meta,
            "heuristiques": heur,
            "donnees": self.resume_donnees(),
            "comment": self.comment(hypothese, n2),
        }

    def donnees_manquantes(self, n2=None):
        bloquants = set()
        if n2:
            for t in n2["tests"]:
                if t["statut"] == "bloquee":
                    for u in t.get("faits", []):
                        bloquants.add(u["fait"].split(" ")[0])
        out = []
        for q in self.kb["questions"]:
            r = self.reponses.get(q["id"])
            if r and r.get("valeur") == "jnsp" and self.visible(q):
                lie = any(self._question_alimente(q["id"], b) for b in bloquants)
                out.append({"id": q["id"], "libelle": q.get("libelle") or q["texte"], "etape": q["etape"], "bloquante": lie})
        return out

    def _question_alimente(self, qid, fid):
        if qid == fid:
            return True
        for r in self.regles:
            if r["conclusion"] == fid and any(f[1] == qid for f in dsl.feuilles(self.arbres[r["id"]])):
                return True
        return False

    def resume_donnees(self):
        out = []
        for q in self.kb["questions"]:
            r = self.reponses.get(q["id"])
            if r is None:
                continue
            if q["type"] != "choix" and not self.visible(q):
                continue
            v = r.get("valeur")
            if q["type"] == "nombre":
                txt = f"{fmt_nombre(self.valeur_brute(q['id']))} {q.get('unite', '')}".strip()
                var = self.floues.get(q["id"])
                if var:
                    x = self.valeur_brute(q["id"])
                    for e in var["ensembles"]:
                        mu = dsl.mu_rampe(x, float(e["debut"]), float(e["fin"]))
                        txt += f" → {e['libelle']} à {round(mu * 100)} %"
            elif q["type"] == "choix":
                opt = next((o for o in q.get("options", []) if o["id"] == v), None)
                txt = opt["libelle"] if opt else ("Je ne sais pas" if v == "jnsp" else str(v))
            else:
                txt = {"oui": "Oui", "non": "Non", "jnsp": "Je ne sais pas"}.get(v, str(v))
                if v == "oui" and q.get("certitude", True):
                    c = r.get("certitude") or "certain"
                    txt += f" ({c}, CF {fmt(self.certitudes.get(c, 1.0), 1)})"
            if int(r.get("fois", 1)) > 1:
                txt += " — redemandée (MR3)"
            out.append({"id": q["id"], "etape": q["etape"],
                        "etape_libelle": self.etapes.get(q["etape"], {}).get("libelle", q["etape"]),
                        "libelle": q.get("libelle") or q["texte"].rstrip(" ?"), "valeur": txt, "brute": v})
        return out

    def comment(self, hypothese, n2):
        """Explication « Comment ? » : on redescend la trace du niveau 2 au niveau 1."""
        phrases = []
        if hypothese["regle"]:
            t = next(x for x in n2["tests"] if x["regle"] == hypothese["regle"])
            phrases.append({"niveau": 2, "texte": f"« {hypothese['libelle']} » (CF {hypothese['cf_texte']}, {hypothese['lecture']}) "
                            f"car {t['premisse']} — règle {t['regle']}.", "calcul": t.get("calcul_complet")})
            utilises = {u["fait"] for u in t.get("faits", [])}
        else:
            phrases.append({"niveau": 2, "texte": "Aucune hypothèse n'atteint le seuil de 0,4 : le système refuse de conclure (H5).", "calcul": None})
            utilises = set(self.inter)
        for f in self.kb["faits_intermediaires"]:
            if f["id"] not in utilises:
                continue
            etapes = [e for e in self.trace1 if e["conclusion"] == f["id"]]
            if not etapes:
                if self.complet_inter.get(f["id"]):
                    phrases.append({"niveau": 1, "texte": f"« {f['libelle']} » = 0 : aucune règle ne s'est déclenchée.", "calcul": None})
                else:
                    phrases.append({"niveau": 1, "texte": f"« {f['libelle']} » non établi : données manquantes.", "calcul": None})
                continue
            for e in etapes:
                faits = ", ".join(f"{u['libelle']} ({fmt(u['cf'])})" for u in e["faits"])
                phrases.append({"niveau": 1, "texte": f"« {f['libelle']} » par {e['regle']} : {faits}.",
                                "calcul": e["calcul"] + (f" ; combinaison : {e['combinaison']}" if e["combinaison"] else "")})
        return phrases


def consulter(kb, reponses):
    return Moteur(kb, reponses).executer()
