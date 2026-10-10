"""Tests : les 5 cas de la présentation (et leurs variantes) doivent donner exactement
les conclusions et les CF des slides 11-12.

Lancer :  python3 -m unittest discover -s tests -v
"""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from se_sein import base, dsl, moteur, verification  # noqa: E402


def resultat(reponses):
    r = moteur.consulter(base.charger_base(), reponses)
    assert r["etat"] == "resultat", f"question inattendue : {r.get('question', {}).get('id')}"
    return r["resultat"]


class TestCasReference(unittest.TestCase):
    def test_tous_les_cas(self):
        kb = base.charger_base()
        for cas in base.charger_cas():
            with self.subTest(cas=cas["id"]):
                res = resultat(cas["reponses"])
                att = cas["attendu"]
                self.assertEqual(res["hypothese"]["id"], att["diagnostic"])
                if att["cf"] is None:
                    self.assertIsNone(res["hypothese"]["cf"])
                else:
                    self.assertEqual(dsl.fmt(res["hypothese"]["cf"]), dsl.fmt(att["cf"]))
                sources = [r["source"] for r in res["recommandations"]]
                self.assertEqual(sorted(sources), sorted(att["recommandations"]))
                for fid, v in att.get("faits", {}).items():
                    fi = next(f for f in res["faits_intermediaires"] if f["id"] == fid)
                    self.assertEqual(fi["cf_texte"], dsl.fmt(v), fid)
        self.assertTrue(verification.verifier_cas(kb)["ok"])

    def test_couleurs(self):
        couleurs = {c["id"]: resultat(c["reponses"])["hypothese"]["gravite"] for c in base.charger_cas()}
        self.assertEqual(couleurs["cas1"], "rouge")
        self.assertEqual(couleurs["cas2"], "rouge")
        self.assertEqual(couleurs["cas3"], "vert")
        self.assertEqual(couleurs["cas4"], "orange")
        self.assertEqual(couleurs["cas5"], "gris")


class TestCalculs(unittest.TestCase):
    def test_flou(self):
        self.assertEqual(dsl.mu_rampe(58, 50, 60), 0.8)
        self.assertEqual(dsl.mu_rampe(45, 50, 60), 0.0)
        self.assertEqual(dsl.mu_rampe(70, 50, 60), 1.0)

    def test_combinaison_slide6(self):
        res = resultat(next(c for c in base.charger_cas() if c["id"] == "cas1")["reponses"])
        r1 = [e for e in res["trace_niveau1"] if e["conclusion"] == "risque_eleve"]
        self.assertEqual([dsl.fmt(e["cf"]) for e in r1], ["0,32", "0,70"])
        self.assertEqual(r1[-1]["combinaison"], "0,32 + 0,70 × (1 − 0,32) = 0,80")

    def test_r10_sans_mr4_cas4(self):
        res = resultat(next(c for c in base.charger_cas() if c["id"] == "cas4")["reponses"])
        r10 = next(t for t in res["trace_niveau2"] if t["regle"] == "R10")
        self.assertEqual(r10["statut"], "desactivee")
        # calcul exact (la slide arrondit 1 − 0,65 à 0,35 avant de multiplier : 0,30)
        self.assertEqual(dsl.fmt(r10["cf_sans_mr4"]), "0,29")

    def test_r11_variante_cas4(self):
        res = resultat(next(c for c in base.charger_cas() if c["id"] == "cas4b")["reponses"])
        r11 = next(t for t in res["trace_niveau2"] if t["regle"] == "R11")
        self.assertEqual(dsl.fmt(r11["cf"]), "0,31")


class TestDialogue(unittest.TestCase):
    """Consultation question par question, comme dans l'interface."""

    def repondre_jusqu_au_bout(self, reponses_prevues, max_tours=40):
        reponses, posees = {}, []
        kb = base.charger_base()
        for _ in range(max_tours):
            r = moteur.consulter(kb, reponses)
            if r["etat"] == "resultat":
                return r["resultat"], posees
            q = r["question"]
            posees.append(q)
            rep = copy.deepcopy(reponses_prevues.get(q["id"], {"valeur": "non"}))
            if q["redemandee"]:
                rep["fois"] = reponses[q["id"]].get("fois", 1) + 1
            reponses[q["id"]] = rep
        self.fail("trop de questions")

    def test_cas1_pose_la_biopsie_avec_pourquoi(self):
        cas = next(c for c in base.charger_cas() if c["id"] == "cas1")
        res, posees = self.repondre_jusqu_au_bout(cas["reponses"])
        self.assertEqual(res["hypothese"]["id"], "cancer_tres_probable")
        bio = next(q for q in posees if q["id"] == "biopsie_faite")
        self.assertIn("si une biopsie a été faite", bio["pourquoi"])
        self.assertIn("Cancer confirmé", bio["pourquoi"])
        self.assertIn("R7", bio["pourquoi"])
        self.assertNotIn("aucune_anomalie", [q["id"] for q in posees])

    def test_cas3_ne_pose_pas_la_biopsie(self):
        cas = next(c for c in base.charger_cas() if c["id"] == "cas3")
        res, posees = self.repondre_jusqu_au_bout(cas["reponses"])
        self.assertNotIn("biopsie_faite", [q["id"] for q in posees])
        self.assertNotIn("nodule_fixe", [q["id"] for q in posees])
        self.assertEqual(res["hypothese"]["id"], "probablement_benin")

    def test_mr3_redemande_la_clinique(self):
        prevues = {"age": {"valeur": 40}, "mutation_brca": {"valeur": "oui", "certitude": "certain"},
                   "aucune_anomalie": {"valeur": "oui", "certitude": "certain"}}
        for q in ("nodule_dur", "nodule_fixe", "retraction", "peau_orange", "ecoulement_sanglant"):
            prevues[q] = {"valeur": "jnsp"}
        res, posees = self.repondre_jusqu_au_bout(prevues)
        redemandees = [q["id"] for q in posees if q["redemandee"]]
        self.assertIn("nodule_dur", redemandees)
        self.assertEqual(res["hypothese"]["id"], "indetermine")
        self.assertTrue(res["donnees_manquantes"])


class TestVerification(unittest.TestCase):
    def test_base_initiale_sans_erreur(self):
        rapport = verification.verifier(base.charger_base())
        self.assertEqual(rapport["nb_erreurs"], 0, rapport)

    def test_detecte_redondance_et_contradiction(self):
        kb = base.charger_base()
        kb["regles"].append({"id": "R12", "niveau": 1, "actif": True, "premisse": "mutation_brca OU antecedent_familial",
                             "conclusion": "risque_eleve", "cf": 0.5})
        kb["regles"].append({"id": "R13", "niveau": 1, "actif": True, "premisse": "masse_spiculee OU microcalcifications",
                             "conclusion": "imagerie_rassurante", "cf": 0.5})
        rapport = verification.verifier(kb)
        ids = {c["id"]: c for c in rapport["controles"]}
        self.assertEqual(ids["redondance"]["statut"], "alerte")
        self.assertEqual(ids["contradiction"]["statut"], "erreur")

    def test_detecte_erreur_syntaxe(self):
        kb = base.charger_base()
        kb["regles"][0]["premisse"] = "age EST"
        self.assertGreater(verification.verifier(kb)["nb_erreurs"], 0)


if __name__ == "__main__":
    unittest.main()
