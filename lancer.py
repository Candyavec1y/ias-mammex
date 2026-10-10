#!/usr/bin/env python3
"""Lance MAMMEX : démarre le serveur local et ouvre le navigateur.

    python3 lancer.py            (port 8765 par défaut)
    python3 lancer.py --port 9000
    python3 lancer.py --sans-navigateur
"""
import argparse
import socket
import sys
import threading
import webbrowser

if sys.version_info < (3, 8):
    sys.exit("MAMMEX nécessite Python 3.8 ou plus récent (vous avez " + sys.version.split()[0] + ").")

from mammex import base  # noqa: E402
from mammex.serveur import creer_serveur  # noqa: E402


def port_libre(depart):
    for p in range(depart, depart + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    sys.exit("Aucun port libre trouvé entre %d et %d." % (depart, depart + 19))


def main():
    cfg = base.config()
    ap = argparse.ArgumentParser(description="MAMMEX — système expert d'aide au diagnostic du cancer du sein")
    ap.add_argument("--port", type=int, default=int(cfg.get("port", 8765)))
    ap.add_argument("--sans-navigateur", action="store_true")
    args = ap.parse_args()

    port = port_libre(args.port)
    serveur = creer_serveur(port)
    url = f"http://127.0.0.1:{port}/"
    print()
    print("  MAMMEX est lancé.")
    print(f"  Interface médecin : {url}")
    print(f"  Interface expert  : {url}expert   (code d'accès : {cfg.get('code_expert')})")
    print()
    print("  Laissez cette fenêtre ouverte pendant l'utilisation.")
    print("  Pour arrêter : Ctrl + C (ou fermez la fenêtre).")
    print()
    if not args.sans_navigateur:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        print("\n  MAMMEX arrêté.")
    finally:
        serveur.server_close()


if __name__ == "__main__":
    main()
