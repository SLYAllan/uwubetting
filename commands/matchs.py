"""/matchs — matchs à venir DU SALON courant (pas de mélange entre sports)."""
from typing import Optional

import discord
from discord import app_commands

import db
import ui


@app_commands.command(name="matchs", description="Matchs à venir dans ce salon")
@app_commands.describe(journee="Numéro de journée à filtrer (optionnel)")
async def matchs_cmd(itx: discord.Interaction, journee: Optional[int] = None):
    league_ids = db.leagues_for_channel(itx.channel_id)
    if not league_ids:
        return await itx.response.send_message(
            "Aucun sport n'est lié à ce salon. Un admin peut le faire avec "
            "`/sport_ajouter`.", ephemeral=True)
    rows = db.matchs_a_venir(journee, league_ids)
    # on n'affiche que les matchs dont le coup d'envoi n'est pas passé : pas de
    # match impariable dans la liste (la garde de /prono le bloque de toute façon)
    rows = [r for r in rows
            if (db.parse_dt(r["date_kickoff_utc"]) or db.now_utc()) > db.now_utc()]
    if not rows:
        return await itx.response.send_message(
            "Aucun match à venir ici pour l'instant.")
    titre = f"🎯 {rows[0]['comp_nom'] or 'Matchs'} — à pronostiquer"
    embeds = ui.matchs_pages(rows, titre)
    view = ui.MatchsView(embeds) if len(embeds) > 1 else None
    await itx.response.send_message(embed=embeds[0], view=view)
    if view:
        view.message = await itx.original_response()


def register(tree, guild):
    tree.add_command(matchs_cmd, guild=guild)
