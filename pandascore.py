"""Provider esport PandaScore (LoL, CS2, Valorant, Dota...).

Interface identique à espn.py (events_saison / lookup_event / mapper_statut)
pour être interchangeable. Les matchs PandaScore sont normalisés vers le même
format de dict qu'espn.py, donc scheduler.py n'a pas à connaître la source.

Le score = nombre de maps gagnées (Bo3/Bo5). Auth par token Bearer.
"""
import os
import time
import asyncio
import logging

import httpx

log = logging.getLogger("pronobot.pandascore")
_BASE = "https://api.pandascore.co"
_MIN_INTERVAL = 1.0          # tier gratuit ~1 req/s
_RETRYABLE = (429, 500, 502, 503, 504)

_lock = asyncio.Lock()
_last = 0.0


def _token():
    return os.environ["PANDASCORE_TOKEN"]


async def _throttle():
    global _last
    async with _lock:
        wait = _MIN_INTERVAL - (time.monotonic() - _last)
        if wait > 0:
            await asyncio.sleep(wait)
        _last = time.monotonic()


async def _get(path, params=None):
    url = f"{_BASE}/{path}"
    headers = {"Authorization": f"Bearer {_token()}"}
    for attempt in range(4):
        await _throttle()
        try:
            async with httpx.AsyncClient(timeout=20) as cli:
                r = await cli.get(url, params=params, headers=headers)
        except httpx.HTTPError as e:                 # timeout / connexion
            if attempt == 3:
                log.error("PandaScore échec réseau %s: %s", path, e)
                raise
            await asyncio.sleep(2 ** attempt)
            continue
        if r.status_code in _RETRYABLE:               # 429/5xx : on retente
            if attempt == 3:
                r.raise_for_status()
            log.warning("PandaScore retry %d/3 (statut %d), dans %ss",
                        attempt + 1, r.status_code, 2 ** attempt)
            await asyncio.sleep(2 ** attempt)
            continue
        r.raise_for_status()                          # autres 4xx : on lève direct
        return r.json()


def _normalize(m):
    """Match PandaScore -> dict au format TheSportsDB attendu par le scheduler."""
    opps = m.get("opponents") or []
    def _opp(i):
        return opps[i].get("opponent") or {} if len(opps) > i else {}

    scores = {r.get("team_id"): r.get("score") for r in (m.get("results") or [])}
    hs, as_ = scores.get(_opp(0).get("id")), scores.get(_opp(1).get("id"))
    begin = m.get("begin_at") or m.get("scheduled_at")
    league = m.get("league") or {}
    serie = m.get("serie") or {}
    ng = m.get("number_of_games")
    return {
        "idEvent": str(m["id"]),
        "strHomeTeam": _opp(0).get("name") or "?",
        "strAwayTeam": _opp(1).get("name") or "?",
        "intHomeScore": hs,
        "intAwayScore": as_,
        "strTimestamp": begin,
        "dateEvent": (begin or "")[:10],
        "strStatus": m.get("status"),
        "intRound": None,            # pas de "journée" simple en esport
        "comp_nom": league.get("name") or serie.get("full_name"),
        "comp_logo": league.get("image_url"),
        "dom_logo": _opp(0).get("image_url"),
        "ext_logo": _opp(1).get("image_url"),
        "bo": f"Bo{ng}" if ng else None,
    }


async def events_saison(league_id, season):
    """Matchs récents/en cours/à venir d'une ligue. `season` ignoré (PandaScore
    filtre par league_id)."""
    # upcoming + running suffisent : un match fini a déjà été inséré quand il
    # était à venir, et la résolution le relit par son id. Pas de backfill
    # historique (matches/past ramènerait des années de matchs inutiles).
    out = []
    for path in ("matches/running", "matches/upcoming"):
        rows = await _get(path, {"filter[league_id]": league_id,
                                 "sort": "begin_at", "per_page": 50})
        out += rows or []
    matchs = [_normalize(m) for m in out]
    # garde seulement les matchs avec deux adversaires connus
    return [m for m in matchs if "?" not in (m["strHomeTeam"], m["strAwayTeam"])]


async def lookup_event(event_id):
    m = await _get(f"matches/{event_id}")
    return _normalize(m) if m else None


_ALIAS = {
    "msi": "Mid-Season Invitational",
    "worlds": "World Championship",
}


async def search_leagues(query, jeu=None):
    """Cherche des ligues par nom. `jeu` (slug: lol, csgo, dota2, valorant...)
    rend la recherche fiable ; sans jeu, recherche générique (plus floue)."""
    query = _ALIAS.get(query.strip().lower(), query)
    path = f"{jeu}/leagues" if jeu else "leagues"
    rows = await _get(path, {"search[name]": query, "per_page": 15})
    return [{"id": str(l["id"]), "nom": l.get("name"),
             "jeu": (l.get("videogame") or {}).get("name") or jeu}
            for l in (rows or [])]


def mapper_statut(api_status, a_un_score, kickoff_passe):
    """Statut PandaScore (explicite) -> statut interne. has_score/kickoff non
    utilisés mais gardés pour une signature identique à espn.mapper_statut."""
    s = (api_status or "").lower()
    if s == "postponed":
        return "reporte"
    if s in ("canceled", "cancelled"):
        return "annule"
    if s == "finished":
        return "termine"
    if s == "running":
        return "en_cours"
    return "a_venir"      # not_started
