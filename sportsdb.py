"""Client TheSportsDB (tier gratuit) : throttle 1 req/s + retry backoff.

L'API gratuite est instable : on limite à 1 appel/seconde et on retente les
429/5xx avec un backoff exponentiel (1s, 2s, 4s).
"""
import os
import time
import asyncio
import logging

import httpx

log = logging.getLogger("pronobot.sportsdb")
_BASE = "https://www.thesportsdb.com/api/v1/json"
_MIN_INTERVAL = 1.0
_RETRYABLE = (429, 500, 502, 503, 504)

_lock = asyncio.Lock()
_last = 0.0


def _key():
    return os.environ.get("SPORTSDB_API_KEY", "3")


async def _throttle():
    global _last
    async with _lock:
        wait = _MIN_INTERVAL - (time.monotonic() - _last)
        if wait > 0:
            await asyncio.sleep(wait)
        _last = time.monotonic()


async def _get(path):
    url = f"{_BASE}/{_key()}/{path}"
    for attempt in range(4):
        await _throttle()
        try:
            async with httpx.AsyncClient(timeout=20) as cli:
                r = await cli.get(url)
        except httpx.HTTPError as e:                 # timeout / connexion
            if attempt == 3:
                log.error("API échec réseau %s: %s", path, e)
                raise
            await asyncio.sleep(2 ** attempt)
            continue
        if r.status_code in _RETRYABLE:               # 429/5xx : on retente
            if attempt == 3:
                r.raise_for_status()
            log.warning("API retry %d/3 (statut %d), dans %ss",
                        attempt + 1, r.status_code, 2 ** attempt)
            await asyncio.sleep(2 ** attempt)
            continue
        r.raise_for_status()                          # autres 4xx : on lève direct
        return r.json()


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _normalize(ev):
    """Event TheSportsDB -> dict canonique (mêmes clés que pandascore)."""
    return {
        "idEvent": ev.get("idEvent"),
        "strHomeTeam": ev.get("strHomeTeam"),
        "strAwayTeam": ev.get("strAwayTeam"),
        "intHomeScore": _int(ev.get("intHomeScore")),
        "intAwayScore": _int(ev.get("intAwayScore")),
        "strTimestamp": ev.get("strTimestamp"),
        "dateEvent": ev.get("dateEvent"),
        "strTime": ev.get("strTime"),
        "strStatus": ev.get("strStatus"),
        "intRound": _int(ev.get("intRound")),
        "comp_nom": ev.get("strLeague"),
        "comp_logo": ev.get("strLeagueBadge"),
        "dom_logo": ev.get("strHomeTeamBadge"),
        "ext_logo": ev.get("strAwayTeamBadge"),
        "bo": None,
    }


async def events_saison(league_id, season):
    data = await _get(f"eventsseason.php?id={league_id}&s={season}")
    return [_normalize(e) for e in (data.get("events") or [])]


async def lookup_event(event_id):
    data = await _get(f"lookupevent.php?id={event_id}")
    rows = data.get("events") or []
    return _normalize(rows[0]) if rows else None


async def search_leagues(query, jeu=None):
    """Cherche une ligue par nom dans tout TheSportsDB (jeu ignoré ici)."""
    data = await _get("all_leagues.php")
    q = query.lower()
    out = [{"id": l.get("idLeague"), "nom": l.get("strLeague"), "jeu": l.get("strSport")}
           for l in (data.get("leagues") or [])
           if q in (l.get("strLeague") or "").lower()]
    return out[:15]


# Codes de match en direct (mi-temps, 1re/2e période...) -> en_cours
_LIVE = ("1h", "2h", "ht", "half", "live", "in play", "inplay", "et ")


def mapper_statut(api_status, a_un_score, kickoff_passe):
    """Mappe le strStatus de l'API vers un statut interne.

    ponytail: heuristique, les libellés varient selon les ligues/sports —
    bouton de réglage si une nouvelle valeur apparaît dans les logs.
    """
    s = (api_status or "").strip().lower()

    if "postpon" in s or "report" in s:
        return "reporte"
    if "cancel" in s or "abandon" in s or "annul" in s:
        return "annule"
    if "finish" in s or "full time" in s or s in ("ft", "aet", "ap"):
        return "termine"
    if any(code in s for code in _LIVE):
        return "en_cours"
    # Pas de libellé explicite : on se fie au score + à l'heure de coup d'envoi
    if a_un_score and kickoff_passe:
        return "termine"
    if kickoff_passe:
        return "en_cours"
    return "a_venir"
