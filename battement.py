"""Battement vers le Dashboard du serveur maison (annexe A.4, B3).

Chaque minute, POST <url> avec le jeton du projet. Le Dashboard alerte sur Discord quand
le battement manque depuis 3 minutes. Une erreur ici n'arrête jamais le bot.
"""

# Même code que bot/battement.py d'uwutcg-bot : dépôts séparés.

from __future__ import annotations

import asyncio
import logging
import urllib.request

log = logging.getLogger(__name__)


def envoyer(url: str, jeton: str, delai: float = 10) -> int:
    requete = urllib.request.Request(url, method="POST", headers={"Authorization": f"Bearer {jeton}"})
    with urllib.request.urlopen(requete, timeout=delai) as reponse:
        return reponse.status


async def boucle(url: str, jeton: str, periode: float = 60) -> None:
    if not url or not jeton:
        # Lancé en local, ou avant que les variables soient posées : le bot doit tourner
        # quand même ; l'absence de battement déclenche l'alerte du Dashboard.
        log.warning("Battement coupé : DASHBOARD_BATTEMENT_URL ou DASHBOARD_BATTEMENT_JETON absente")
        return
    while True:
        try:
            await asyncio.to_thread(envoyer, url, jeton)
        except Exception as e:  # noqa: BLE001 : réseau coupé, Dashboard arrêté, jeton refusé
            log.warning("Battement refusé : %s", e)
        await asyncio.sleep(periode)


def demo() -> None:
    import http.server
    import threading

    recus: list[tuple[str, str | None]] = []

    class Dashboard(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            recus.append((self.path, self.headers.get("Authorization")))
            self.send_response(204 if len(recus) == 1 else 401)
            self.end_headers()

        def log_message(self, *args):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Dashboard)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/api/battement/uwubetting"

    assert envoyer(url, "secret") == 204
    assert recus == [("/api/battement/uwubetting", "Bearer secret")]

    async def tours():
        tache = asyncio.create_task(boucle(url, "secret", periode=0.05))
        await asyncio.sleep(0.3)
        assert not tache.done()  # un 401 n'arrête pas la boucle
        tache.cancel()

    asyncio.run(tours())
    assert len(recus) >= 3
    asyncio.run(boucle("", "x"))  # sans variable : rend la main sans lever
    srv.shutdown()
    print("battement ok")


if __name__ == "__main__":
    demo()
