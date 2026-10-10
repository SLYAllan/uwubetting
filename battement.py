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
    raise NotImplementedError


async def boucle(url: str, jeton: str, periode: float = 60) -> None:
    raise NotImplementedError


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
