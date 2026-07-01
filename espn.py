"""Provider football GRATUIT via l'API publique ESPN (aucune clé requise).

Couvre la Coupe du Monde, les Euros, la C1/C3 et les grands championnats, avec
le calendrier complet (matchs à venir compris) — contrairement au tier gratuit
de TheSportsDB qui plafonne. Interface identique aux autres providers.

L'id ESPN seul ne suffit pas à requêter un match (il faut le slug de ligue), donc
on encode l'id sous la forme "slug:eventId" (ex "fifa.world:760490").
"""
import time
import asyncio
import logging
from datetime import timedelta

import httpx

import db

log = logging.getLogger("pronobot.espn")
_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
_HEADERS = {"User-Agent": "Mozilla/5.0"}
_MIN_INTERVAL = 0.4
_RETRYABLE = (429, 500, 502, 503, 504)

_lock = asyncio.Lock()
_last = 0.0

# Slugs ESPN des compétitions courantes (catalogue pour /chercher_ligue)
_LEAGUES = {
    "fifa.world": "Coupe du Monde",
    "fifa.cwc": "Coupe du Monde des Clubs",
    "uefa.euro": "Euro",
    "uefa.champions": "Ligue des Champions",
    "uefa.europa": "Ligue Europa",
    "eng.1": "Premier League",
    "esp.1": "LaLiga",
    "ita.1": "Serie A",
    "ger.1": "Bundesliga",
    "fra.1": "Ligue 1",
    "usa.1": "MLS",
}


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


async def _throttle():
    global _last
    async with _lock:
        wait = _MIN_INTERVAL - (time.monotonic() - _last)
        if wait > 0:
            await asyncio.sleep(wait)
        _last = time.monotonic()


async def _get(path):
    url = f"{_BASE}/{path}"
    for attempt in range(4):
        await _throttle()
        try:
            async with httpx.AsyncClient(timeout=20, headers=_HEADERS) as cli:
                r = await cli.get(url)
        except httpx.HTTPError as e:
            if attempt == 3:
                log.error("ESPN échec réseau %s: %s", path, e)
                raise
            await asyncio.sleep(2 ** attempt)
            continue
        if r.status_code in _RETRYABLE:
            if attempt == 3:
                r.raise_for_status()
            await asyncio.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        return r.json()


def _normalize(event, slug, comp_nom, comp_logo):
    comp = (event.get("competitions") or [{}])[0]
    cs = comp.get("competitors") or []
    home = next((c for c in cs if c.get("homeAway") == "home"), {})
    away = next((c for c in cs if c.get("homeAway") == "away"), {})
    status = (comp.get("status") or {}).get("type") or {}
    return {
        "idEvent": f"{slug}:{event.get('id')}",
        "strHomeTeam": (home.get("team") or {}).get("displayName") or "?",
        "strAwayTeam": (away.get("team") or {}).get("displayName") or "?",
        "intHomeScore": _int(home.get("score")),
        "intAwayScore": _int(away.get("score")),
        "strTimestamp": event.get("date"),
        "dateEvent": (event.get("date") or "")[:10],
        "strStatus": status.get("name"),
        "intRound": None,
        "comp_nom": comp_nom,
        "comp_logo": comp_logo,
        "dom_logo": (home.get("team") or {}).get("logo"),
        "ext_logo": (away.get("team") or {}).get("logo"),
        "bo": None,
    }


async def events_saison(league_id, season):
    """`league_id` = slug ESPN (ex 'fifa.world'). `season` ignoré : on récupère
    une fenêtre glissante (récents + ~1 mois à venir) pour avoir les matchs
    pariables et ceux à résoudre."""
    d1 = (db.now_utc() - timedelta(days=3)).strftime("%Y%m%d")
    d2 = (db.now_utc() + timedelta(days=30)).strftime("%Y%m%d")
    data = await _get(f"{league_id}/scoreboard?dates={d1}-{d2}")
    lg = (data.get("leagues") or [{}])[0]
    comp_nom = lg.get("name") or league_id
    comp_logo = (lg.get("logos") or [{}])[0].get("href")
    return [_normalize(e, league_id, comp_nom, comp_logo)
            for e in (data.get("events") or [])]


async def lookup_event(event_id):
    slug, _, eid = event_id.partition(":")
    data = await _get(f"{slug}/summary?event={eid}")
    hdr = data.get("header") or {}
    comp = (hdr.get("competitions") or [{}])[0]
    event = {"id": eid, "date": comp.get("date"), "competitions": [comp]}
    nom = (hdr.get("league") or {}).get("name") or _LEAGUES.get(slug, slug)
    return _normalize(event, slug, nom, None)


def mapper_statut(api_status, a_un_score, kickoff_passe):
    s = (api_status or "").upper()
    if "POSTPON" in s or "DELAY" in s:
        return "reporte"
    if "CANCEL" in s or "ABANDON" in s or "FORFEIT" in s:
        return "annule"
    if "FULL_TIME" in s or "FINAL" in s or s == "STATUS_FT":
        return "termine"
    if any(k in s for k in ("HALF", "IN_PROGRESS", "IN_PLAY", "FIRST",
                            "SECOND", "OVERTIME", "PENALT", "STATUS_RESCHED")):
        return "en_cours" if "RESCHED" not in s else "a_venir"
    return "a_venir"


async def search_leagues(query, jeu=None):
    q = query.lower()
    return [{"id": k, "nom": v, "jeu": "Foot"} for k, v in _LEAGUES.items()
            if q in v.lower() or q in k.lower()]
