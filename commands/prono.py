"""/prono — enregistre ou modifie un pronostic (refusé après le coup d'envoi)."""
import re

import discord
from discord import app_commands

import db
import scoring
import ui

_SCORE_RE = re.compile(r"\s*(\d+)\s*-\s*(\d+)\s*")


@app_commands.command(name="prono", description="Enregistre ou modifie ton prono")
@app_commands.describe(match="Numéro affiché par /matchs",
                       score="Score exact, ex '2-1' (foot, nul possible), "
                             "'2-0' (Bo3) ou '3-1' (Bo5, pas de nul en esport)")
async def prono_cmd(itx: discord.Interaction, match: int, score: str):
    m = db.match_by_numero(match)
    if not m:
        return await itx.response.send_message(
            "Match introuvable (vérifie le # dans /matchs).", ephemeral=True)
    if (db.parse_dt(m["date_kickoff_utc"]) or db.now_utc()) <= db.now_utc():
        return await itx.response.send_message(
            "Trop tard, ce match a déjà commencé.", ephemeral=True)

    mm = _SCORE_RE.fullmatch(score)
    if not mm:
        return await itx.response.send_message(
            "Format de score invalide. Exemple attendu : `2-1`.", ephemeral=True)
    sd, se = int(mm.group(1)), int(mm.group(2))
    if not scoring.score_valide_pour_bo(m["bo"], sd, se):
        return await itx.response.send_message(
            f"Score `{sd}-{se}` impossible pour un match {m['bo']} "
            "(pas de nul, le vainqueur doit atteindre le seuil de victoire)."
            if m["bo"] else f"Score `{sd}-{se}` invalide.", ephemeral=True)
    resultat = scoring.resultat_depuis_score(sd, se)

    db.upsert_prono(str(itx.user.id), itx.user.display_name, m["id"],
                    resultat, sd, se)
    detail = f"{sd}-{se}"

    loc = ui.en_paris(m["date_kickoff_utc"])
    e = discord.Embed(
        title="✅ Prono enregistré", color=ui.couleur(m["bo"]),
        description=f"**{m['equipe_dom']}**  🆚  **{m['equipe_ext']}**\n\n"
                    f"Ton prono : **{detail}**"
                    + (f"   ·   🎮 {m['bo']}" if m["bo"] else ""))
    if m["dom_logo"]:
        e.set_thumbnail(url=m["dom_logo"])
    e.add_field(
        name="Coup d'envoi",
        value=f"🕐 {ui.jour_label(loc)} {ui.heure_label(loc)} (Paris) · "
              f"⏱️ {ui.countdown(m['date_kickoff_utc'])}")
    e.set_footer(text="Modifiable jusqu'au coup d'envoi · score exact = 8 pts")
    await itx.response.send_message(embed=e, ephemeral=True)


def register(tree, guild):
    tree.add_command(prono_cmd, guild=guild)
