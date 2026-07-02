"""Provider football + NBA GRATUIT via l'API publique ESPN (aucune clé requise).

Couvre la Coupe du Monde, les Euros, la C1/C3, les grands championnats et la
NBA, avec le calendrier complet (matchs à venir compris). Interface identique
aux autres providers.

`league_id` = chemin ESPN "sport/ligue" (ex "soccer/fifa.world", "basketball/nba").
L'id ESPN seul ne suffit pas à requêter un match (il faut ce chemin), donc on
encode l'id sous la forme "chemin:eventId" (ex "soccer/fifa.world:760490").
"""
import time
import asyncio
import logging
from datetime import timedelta

import httpx

import db

log = logging.getLogger("pronobot.espn")
_BASE = "https://site.api.espn.com/apis/site/v2/sports"
_HEADERS = {"User-Agent": "Mozilla/5.0"}
_MIN_INTERVAL = 0.4
_RETRYABLE = (429, 500, 502, 503, 504)

_lock = asyncio.Lock()
_last = 0.0

# Chemins ESPN des compétitions courantes (catalogue pour /chercher_ligue)
_LEAGUES = {
    "soccer/fifa.world": "Coupe du Monde",
    "soccer/fifa.cwc": "Coupe du Monde des Clubs",
    "soccer/uefa.euro": "Euro",
    "soccer/uefa.champions": "Ligue des Champions",
    "soccer/uefa.europa": "Ligue Europa",
    "soccer/eng.1": "Premier League",
    "soccer/esp.1": "LaLiga",
    "soccer/ita.1": "Serie A",
    "soccer/ger.1": "Bundesliga",
    "soccer/fra.1": "Ligue 1",
    "soccer/usa.1": "MLS",
    "basketball/nba": "NBA",
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


def _score_90(competitor, league_path):
    """Score à la fin du temps réglementaire (1re + 2e mi-temps), sans
    prolongation ni tirs au but. Seul le foot a ce concept (linescores =
    [mi-temps1, mi-temps2, prol1, prol2, tab] quand la prolongation a lieu) ;
    pour les autres sports (NBA...) on retombe sur le score final classique."""
    if not league_path.startswith("soccer/"):
        return None
    lignes = competitor.get("linescores") or []
    if len(lignes) < 2:
        return None
    try:
        return sum(int(float(l.get("displayValue"))) for l in lignes[:2])
    except (TypeError, ValueError):
        return None


def _buts(key_events):
    """Liste des buts marqués (hors tirs au but), ordre chronologique :
    équipe, buteur (None si non renseigné), minute affichée, CSC ou non."""
    buts = []
    for e in key_events or []:
        if not e.get("scoringPlay") or e.get("shootout"):
            continue
        participants = e.get("participants") or []
        buteur = (participants[0].get("athlete") or {}).get("displayName") if participants else None
        buts.append({
            "equipe": (e.get("team") or {}).get("displayName"),
            "buteur": buteur,
            "minute": (e.get("clock") or {}).get("displayValue") or "",
            "csc": "own goal" in ((e.get("type") or {}).get("text") or "").lower(),
        })
    return buts


def _normalize(event, league_path, comp_nom, comp_logo, key_events=None):
    comp = (event.get("competitions") or [{}])[0]
    cs = comp.get("competitors") or []
    home = next((c for c in cs if c.get("homeAway") == "home"), {})
    away = next((c for c in cs if c.get("homeAway") == "away"), {})
    status = (comp.get("status") or {}).get("type") or {}
    return {
        "idEvent": f"{league_path}:{event.get('id')}",
        "strHomeTeam": (home.get("team") or {}).get("displayName") or "?",
        "strAwayTeam": (away.get("team") or {}).get("displayName") or "?",
        "intHomeScore": _int(home.get("score")),
        "intAwayScore": _int(away.get("score")),
        "intHomeScore90": _score_90(home, league_path),
        "intAwayScore90": _score_90(away, league_path),
        "buts": _buts(key_events) if key_events is not None else None,
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
    """`league_id` = chemin ESPN "sport/ligue" (ex 'soccer/fifa.world',
    'basketball/nba'). `season` ignoré : on récupère une fenêtre glissante
    (récents + ~1 mois à venir) pour avoir les matchs pariables et ceux à
    résoudre."""
    d1 = (db.now_utc() - timedelta(days=3)).strftime("%Y%m%d")
    d2 = (db.now_utc() + timedelta(days=30)).strftime("%Y%m%d")
    data = await _get(f"{league_id}/scoreboard?dates={d1}-{d2}")
    lg = (data.get("leagues") or [{}])[0]
    comp_nom = lg.get("name") or _LEAGUES.get(league_id, league_id)
    comp_logo = (lg.get("logos") or [{}])[0].get("href")
    return [_normalize(e, league_id, comp_nom, comp_logo)
            for e in (data.get("events") or [])]


async def lookup_event(event_id):
    league_path, _, eid = event_id.partition(":")
    data = await _get(f"{league_path}/summary?event={eid}")
    hdr = data.get("header") or {}
    comp = (hdr.get("competitions") or [{}])[0]
    event = {"id": eid, "date": comp.get("date"), "competitions": [comp]}
    nom = (hdr.get("league") or {}).get("name") or _LEAGUES.get(league_path, league_path)
    return _normalize(event, league_path, nom, None, key_events=data.get("keyEvents"))


def mapper_statut(api_status, a_un_score, kickoff_passe):
    s = (api_status or "").upper()
    if "POSTPON" in s or "DELAY" in s:
        return "reporte"
    if "CANCEL" in s or "ABANDON" in s or "FORFEIT" in s:
        return "annule"
    if "FULL_TIME" in s or "FINAL" in s or s == "STATUS_FT":
        return "termine"
    if any(k in s for k in ("HALF", "IN_PROGRESS", "IN_PLAY", "FIRST",
                            "SECOND", "THIRD", "FOURTH", "QUARTER",
                            "OVERTIME", "PENALT")):
        return "en_cours"
    return "a_venir"


async def search_leagues(query, jeu=None):
    q = query.lower()
    return [{"id": k, "nom": v, "jeu": "Foot" if k.startswith("soccer/") else "NBA"}
            for k, v in _LEAGUES.items()
            if q in v.lower() or q in k.lower()]
