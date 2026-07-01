"""Tâches périodiques (APScheduler) : refresh multi-ligues + résolution.

Chaque ligue (table `leagues`) a son provider et son salon Discord. Les matchs
ne sont jamais mélangés : ils portent leur `league` + `provider`, et les
nouveaux matchs sont annoncés automatiquement dans le salon de leur ligue.
"""
import os
import logging

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import db
import pandascore
import espn
import scoring
import ui

log = logging.getLogger("pronobot.scheduler")
_sched = AsyncIOScheduler(timezone="UTC")
_client = None  # client Discord, pour annoncer dans les salons

PROVIDERS = {"pandascore": pandascore, "espn": espn}


def _prov(name):
    return PROVIDERS.get((name or "espn").lower(), espn)


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _score(ev):
    return _int(ev.get("intHomeScore")), _int(ev.get("intAwayScore"))


def _kickoff(ev):
    ts = ev.get("strTimestamp")
    if ts:
        return ts
    d = ev.get("dateEvent")
    return f"{d} {ev.get('strTime') or '00:00:00'}" if d else None


async def _annoncer(lg):
    """Poste les nouveaux matchs d'une ligue dans son salon, puis les marque.
    Tolérant aux pannes : une erreur d'envoi n'empêche pas les autres ligues."""
    if not (_client and lg["channel_id"]):
        return
    nouveaux = db.matchs_non_annonces(lg["league_id"])
    if not nouveaux:
        return
    ch = _client.get_channel(int(lg["channel_id"]))
    if not ch:
        log.warning("salon %s introuvable pour %s", lg["channel_id"], lg["nom"])
        return
    try:
        for emb in ui.matchs_pages(nouveaux, f"🆕 {lg['nom']} — nouveaux matchs"):
            await ch.send(embed=emb)
    except Exception:
        # ex: permissions manquantes dans le salon -> on log et on n'annonce
        # pas comme fait (réessai au prochain refresh), sans bloquer les autres
        log.exception("annonce impossible dans %s (%s)", lg["channel_id"], lg["nom"])
        return
    with db.conn() as c:
        db.marquer_annonces(c, [r["id"] for r in nouveaux])


async def refresh_matchs():
    """Tous les jours à 00h00 (Paris) : pour chaque ligue, récupère ses matchs
    via son provider, upsert, renumérote, puis annonce les nouveaux."""
    leagues = db.list_leagues()
    for lg in leagues:
        prov = _prov(lg["provider"])
        season = lg["saison"] or os.environ.get("SEASON", "")
        try:
            events = await prov.events_saison(lg["league_id"], season)
        except Exception:
            log.exception("events_saison %s (%s)", lg["league_id"], lg["provider"])
            continue
        with db.conn() as c:
            for ev in events:
                kickoff = _kickoff(ev)
                sd, se = _score(ev)
                passe = (db.parse_dt(kickoff) or db.now_utc()) <= db.now_utc()
                statut = prov.mapper_statut(
                    ev.get("strStatus"), sd is not None and se is not None, passe)
                db.upsert_match(
                    c, event_id=ev["idEvent"], league=lg["league_id"],
                    provider=lg["provider"], dom=ev["strHomeTeam"],
                    ext=ev["strAwayTeam"], kickoff=kickoff, statut=statut,
                    saison=season, journee=_int(ev.get("intRound")),
                    comp_nom=ev.get("comp_nom"), comp_logo=ev.get("comp_logo"),
                    dom_logo=ev.get("dom_logo"), ext_logo=ev.get("ext_logo"),
                    bo=ev.get("bo"))
            db.renumber(c)
        await _annoncer(lg)
        log.info("refresh %s: %d matchs", lg["nom"], len(events))


async def resoudre_matchs():
    """Toutes les heures : résout les matchs dont le coup d'envoi est passé.
    Idempotent (resolu=1 exclut du calcul). Chaque match utilise son provider."""
    a_traiter = sorted(
        (m for m in db.matchs_a_resoudre()
         if (db.parse_dt(m["date_kickoff_utc"]) or db.now_utc()) <= db.now_utc()),
        key=lambda m: db.parse_dt(m["date_kickoff_utc"]) or db.now_utc())

    for m in a_traiter:  # vrai ordre chronologique (multi-providers) -> séries OK
        prov = _prov(m["provider"])
        try:
            ev = await prov.lookup_event(m["sportsdb_event_id"])
        except Exception:
            log.exception("lookup_event %s", m["sportsdb_event_id"])
            continue
        if not ev:
            continue

        sd, se = _score(ev)
        has = sd is not None and se is not None
        statut = prov.mapper_statut(ev.get("strStatus"), has, True)

        with db.conn() as c:
            if statut == "termine" and has:
                pronos = db.pronos_du_match(c, m["id"])
                total = 0
                for p in pronos:
                    serie, best = db.get_streak(c, p["user_id"])
                    pts, _bon, nser = scoring.calcul_points(
                        p["resultat"], p["score_dom"], p["score_ext"], sd, se, serie)
                    db.set_prono_points(c, p["id"], pts)
                    db.set_streak(c, p["user_id"], nser, max(best, nser))
                    total += pts
                db.finalise_match(c, m["id"], "termine", sd, se)
                log.info("résolu %s (%s-%s): %d pts sur %d pronos",
                         m["sportsdb_event_id"], sd, se, total, len(pronos))
            elif statut == "annule":
                db.finalise_match(c, m["id"], "annule", None, None)
            elif statut == "reporte":
                db.set_statut(c, m["id"], "reporte")
            else:
                db.set_statut(c, m["id"], statut)


def _sport_bruyant(m):
    """Le basket marque trop souvent pour qu'une annonce par panier ait un
    sens (contrairement à un but au foot ou une map gagnée en esport)."""
    return not (m["league"] or "").startswith("basketball/")


async def _annoncer_score(m, sd, se, ancien_sd, ancien_se):
    if not _client:
        return
    lg = db.league_by_id(m["league"])
    if not (lg and lg["channel_id"]):
        return
    ch = _client.get_channel(int(lg["channel_id"]))
    if not ch:
        return
    qui = None
    if ancien_sd is not None:
        if sd > ancien_sd:
            qui = m["equipe_dom"]
        elif se > ancien_se:
            qui = m["equipe_ext"]
    if m["bo"]:
        titre = f"🎮 Map remportée par **{qui}** !" if qui else "🎮 Score mis à jour"
    else:
        titre = f"⚽ BUUUT de **{qui}** !" if qui else "⚽ Score mis à jour"
    e = discord.Embed(title=titre, color=ui.couleur(m["bo"]),
                      description=f"**{m['equipe_dom']}**  {sd} - {se}  **{m['equipe_ext']}**")
    try:
        await ch.send(embed=e)
    except Exception:
        log.exception("annonce score impossible dans %s", lg["channel_id"])


async def suivre_matchs():
    """Toutes les ~90s : traque les matchs en cours et annonce les buts (foot)
    ou changements de score (esport, = maps gagnées). Ne touche pas aux matchs
    déjà 'termine' (la résolution/le calcul des points reste géré par
    resoudre_matchs, une heure au plus tard)."""
    candidats = [m for m in db.matchs_a_resoudre()
                if _sport_bruyant(m)
                and (db.parse_dt(m["date_kickoff_utc"]) or db.now_utc()) <= db.now_utc()]
    for m in candidats:
        prov = _prov(m["provider"])
        try:
            ev = await prov.lookup_event(m["sportsdb_event_id"])
        except Exception:
            log.exception("suivi %s", m["sportsdb_event_id"])
            continue
        if not ev:
            continue
        sd, se = _score(ev)
        if sd is None or se is None:
            continue
        ancien_sd, ancien_se = m["score_dom"], m["score_ext"]
        statut = prov.mapper_statut(ev.get("strStatus"), True, True)
        if statut != "termine":
            with db.conn() as c:
                db.maj_score_live(c, m["id"], statut, sd, se)
        if ancien_sd is not None and (sd, se) != (ancien_sd, ancien_se):
            await _annoncer_score(m, sd, se, ancien_sd, ancien_se)


def start(client):
    global _client
    _client = client
    _sched.add_job(refresh_matchs, "cron", hour=0, minute=0,
                   timezone="Europe/Paris", id="refresh")
    _sched.add_job(resoudre_matchs, "interval", hours=1, id="resoudre")
    _sched.add_job(suivre_matchs, "interval", seconds=90, id="suivre")
    _sched.start()
    log.info("scheduler démarré (refresh 00h00 Paris, résolution 1h, suivi live 90s)")
