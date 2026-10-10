"""Chargement, enregistrement et versions de la base de connaissances."""
from __future__ import annotations

import copy
import datetime as _dt
import json
import os
import secrets
import threading
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DONNEES = RACINE / "data"
FICHIER_BASE = DONNEES / "base_connaissances.json"
FICHIER_CAS = DONNEES / "cas_reference.json"
FICHIER_CONFIG = DONNEES / "config.json"
DOSSIER_VERSIONS = DONNEES / "versions"

_verrou = threading.Lock()


def _ecrire_json(chemin: Path, donnees):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_suffix(chemin.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(donnees, f, ensure_ascii=False, indent=2)
    os.replace(tmp, chemin)


def _lire_json(chemin: Path):
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


def charger_base():
    return _lire_json(FICHIER_BASE)


def charger_cas():
    return _lire_json(FICHIER_CAS)


def config():
    if not FICHIER_CONFIG.exists():
        _ecrire_json(FICHIER_CONFIG, {"code_expert": "expert-sein", "port": 8765})
    return _lire_json(FICHIER_CONFIG)


# ------------------------------------------------------------------ versions

def _fichiers_versions():
    DOSSIER_VERSIONS.mkdir(parents=True, exist_ok=True)
    return sorted(DOSSIER_VERSIONS.glob("v*.json"))


def initialiser_versions():
    """Crée la version 1 (base de la présentation) au premier lancement."""
    with _verrou:
        if not _fichiers_versions():
            base = charger_base()
            _enregistrer_sans_verrou(base, "Équipe projet (Mouradian, Pasquier, Mollier)",
                                     "Base initiale : version de la présentation", ecrire_base=False)


def lister_versions():
    out = []
    for f in _fichiers_versions():
        try:
            out.append(_lire_json(f)["meta"])
        except (OSError, ValueError, KeyError):
            continue
    return list(reversed(out))


def lire_version(numero: int):
    f = DOSSIER_VERSIONS / f"v{int(numero):04d}.json"
    if not f.exists():
        raise FileNotFoundError(f"Version {numero} introuvable")
    return _lire_json(f)


def _enregistrer_sans_verrou(base, auteur, motif, ecrire_base=True):
    fichiers = _fichiers_versions()
    numero = (int(fichiers[-1].stem[1:]) + 1) if fichiers else 1
    base = copy.deepcopy(base)
    meta = {
        "numero": numero,
        "date": _dt.datetime.now().isoformat(timespec="seconds"),
        "auteur": auteur.strip() or "anonyme",
        "motif": motif.strip(),
        "nb_regles": len(base.get("regles", [])),
    }
    base.setdefault("meta", {})["version"] = numero
    _ecrire_json(DOSSIER_VERSIONS / f"v{numero:04d}.json", {"meta": meta, "base": base})
    if ecrire_base:
        _ecrire_json(FICHIER_BASE, base)
    else:
        courante = charger_base()
        courante.setdefault("meta", {})["version"] = numero
        _ecrire_json(FICHIER_BASE, courante)
    return meta


def enregistrer(base, auteur, motif):
    with _verrou:
        return _enregistrer_sans_verrou(base, auteur, motif)


def restaurer(numero, auteur):
    v = lire_version(numero)
    return enregistrer(v["base"], auteur, f"Restauration de la version {numero}")


def differences(ancienne, nouvelle):
    """Résumé lisible des différences entre deux bases."""
    diffs = []
    ra = {r["id"]: r for r in ancienne.get("regles", [])}
    rn = {r["id"]: r for r in nouvelle.get("regles", [])}
    for rid in rn:
        if rid not in ra:
            diffs.append(f"Règle {rid} ajoutée : SI {rn[rid]['premisse']} ALORS {rn[rid]['conclusion']} (CF {rn[rid]['cf']})")
    for rid in ra:
        if rid not in rn:
            diffs.append(f"Règle {rid} supprimée")
    for rid in rn:
        if rid in ra and ra[rid] != rn[rid]:
            for cle in sorted(set(ra[rid]) | set(rn[rid])):
                if ra[rid].get(cle) != rn[rid].get(cle):
                    diffs.append(f"Règle {rid} — {cle} : {ra[rid].get(cle)!r} → {rn[rid].get(cle)!r}")
    for section, cle_id in (("meta_regles", "id"), ("heuristiques", "id"), ("questions", "id"),
                            ("faits_intermediaires", "id"), ("diagnostics", "id"), ("variables_floues", "id")):
        a = {x[cle_id]: x for x in ancienne.get(section, [])}
        n = {x[cle_id]: x for x in nouvelle.get(section, [])}
        for k in n:
            if k not in a:
                diffs.append(f"{section} : {k} ajouté")
            elif a[k] != n[k]:
                diffs.append(f"{section} : {k} modifié")
        for k in a:
            if k not in n:
                diffs.append(f"{section} : {k} supprimé")
    if ancienne.get("parametres") != nouvelle.get("parametres"):
        diffs.append("Paramètres généraux modifiés (seuil d'activation, certitudes ou lecture des CF)")
    return diffs


# ------------------------------------------------------------------ jetons de session expert
_jetons = {}


def ouvrir_session(nom, code):
    if code != config().get("code_expert"):
        return None
    jeton = secrets.token_hex(16)
    _jetons[jeton] = nom.strip() or "expert"
    return jeton


def auteur_session(jeton):
    return _jetons.get(jeton or "")
