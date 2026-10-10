"""Serveur web local (bibliothèque standard uniquement, rien à installer)."""
from __future__ import annotations

import json
import mimetypes
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import base, verification
from .moteur import ErreurBase, Moteur

WEB = base.RACINE / "web"
PAGES = {"/": "index.html", "/index.html": "index.html", "/expert": "expert.html", "/expert.html": "expert.html"}


class ErreurRequete(Exception):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.code = code


class Gestionnaire(BaseHTTPRequestHandler):
    server_version = "SE-Sein/1.0"

    def log_message(self, fmt, *args):  # console plus calme
        pass

    # ------------------------------------------------------------------ envoi
    def _json(self, donnees, code=200):
        corps = json.dumps(donnees, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corps)

    def _fichier(self, chemin: Path):
        if not chemin.is_file():
            self.send_error(404, "Introuvable")
            return
        corps = chemin.read_bytes()
        type_mime = mimetypes.guess_type(str(chemin))[0] or "application/octet-stream"
        if type_mime.startswith("text/") or type_mime in ("application/javascript",):
            type_mime += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", type_mime)
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(corps)

    def _corps(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except ValueError:
            raise ErreurRequete("Requête JSON invalide")

    def _auteur(self):
        auteur = base.auteur_session(self.headers.get("X-Jeton"))
        if not auteur:
            raise ErreurRequete("Session expert expirée : reconnectez-vous.", 401)
        return auteur

    # ------------------------------------------------------------------ routage
    def do_GET(self):
        url = urlparse(self.path)
        try:
            if url.path in PAGES:
                return self._fichier(WEB / PAGES[url.path])
            if url.path.startswith("/static/"):
                rel = url.path[len("/static/"):]
                chemin = (WEB / rel).resolve()
                if WEB.resolve() not in chemin.parents:
                    return self.send_error(403)
                return self._fichier(chemin)
            if url.path == "/api/info":
                kb = base.charger_base()
                questions = [{k: q.get(k) for k in ("id", "libelle", "texte", "etape", "type", "unite", "options")}
                             for q in kb["questions"]]
                return self._json({"nom": kb["meta"].get("nom", "SE-Sein"), "version": kb["meta"].get("version"),
                                   "etapes": kb["etapes"], "questions": questions,
                                   "certitudes": kb["parametres"]["certitudes"]})
            if url.path == "/api/cas":
                return self._json([{"id": c["id"], "titre": c["titre"], "reponses": c["reponses"]} for c in base.charger_cas()])
            if url.path == "/api/expert/base":
                self._auteur()
                return self._json({"base": base.charger_base(), "versions": base.lister_versions()})
            if url.path == "/api/expert/versions":
                self._auteur()
                return self._json(base.lister_versions())
            if url.path == "/api/expert/version":
                self._auteur()
                n = int(parse_qs(url.query).get("n", ["0"])[0])
                v = base.lire_version(n)
                v["differences"] = base.differences(v["base"], base.charger_base())
                return self._json(v)
            self.send_error(404)
        except ErreurRequete as e:
            self._json({"erreur": str(e)}, e.code)
        except FileNotFoundError as e:
            self._json({"erreur": str(e)}, 404)
        except Exception as e:  # pragma: no cover
            traceback.print_exc()
            self._json({"erreur": f"Erreur interne : {e}"}, 500)

    def do_POST(self):
        url = urlparse(self.path)
        try:
            d = self._corps()
            if url.path == "/api/consultation":
                return self._json(Moteur(base.charger_base(), d.get("reponses") or {}).executer())
            if url.path == "/api/expert/connexion":
                jeton = base.ouvrir_session(d.get("nom", ""), d.get("code", ""))
                if not jeton:
                    raise ErreurRequete("Code d'accès incorrect.", 403)
                return self._json({"jeton": jeton, "auteur": base.auteur_session(jeton)})
            if url.path.startswith("/api/expert/"):
                auteur = self._auteur()
                action = url.path[len("/api/expert/"):]
                if action == "verifier":
                    return self._json(verification.verifier(d["base"]))
                if action == "analyser":
                    return self._json(verification.analyser_premisse(d["base"], d.get("premisse", ""), d.get("niveau")))
                if action == "essayer":
                    try:
                        return self._json(Moteur(d["base"], d.get("reponses") or {}, demander=False).executer())
                    except ErreurBase as e:
                        raise ErreurRequete(str(e))
                if action == "enregistrer":
                    motif = (d.get("motif") or "").strip()
                    if not motif:
                        raise ErreurRequete("Indiquez le motif de la modification.")
                    rapport = verification.verifier(d["base"])
                    if rapport["nb_erreurs"]:
                        return self._json({"erreur": "La base contient des erreurs : corrigez-les avant d'enregistrer.",
                                           "rapport": rapport}, 422)
                    meta = base.enregistrer(d["base"], auteur, motif)
                    return self._json({"meta": meta, "rapport": rapport})
                if action == "restaurer":
                    return self._json({"meta": base.restaurer(int(d["numero"]), auteur)})
            self.send_error(404)
        except ErreurRequete as e:
            self._json({"erreur": str(e)}, e.code)
        except ErreurBase as e:
            self._json({"erreur": f"Base de connaissances invalide : {e}"}, 500)
        except (KeyError, ValueError, TypeError) as e:
            traceback.print_exc()
            self._json({"erreur": f"Requête invalide : {e}"}, 400)
        except Exception as e:  # pragma: no cover
            traceback.print_exc()
            self._json({"erreur": f"Erreur interne : {e}"}, 500)


def creer_serveur(port):
    base.initialiser_versions()
    return ThreadingHTTPServer(("127.0.0.1", port), Gestionnaire)
