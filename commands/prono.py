"""/prono — enregistre, modifie ou supprime un pronostic (refusé après le
coup d'envoi)."""
import discord
from discord import app_commands

import db
import pronos
import ui


@app_commands.command(name="prono", description="Enregistre ou modifie ton prono")
@app_commands.describe(match="Numéro affiché par /matchs",
                       score="Score exact, ex '2-1' (foot, nul possible), "
                             "'2-0' (Bo3) ou '3-1' (Bo5, pas de nul en esport)")
async def prono_cmd(itx: discord.Interaction, match: int, score: str):
    m = db.match_by_numero(match)
    err = pronos.match_ouvert(m)
    if err:
        return await itx.response.send_message(err.capitalize() + ".", ephemeral=True)

    ok, err, detail = pronos.enregistrer(
        str(itx.user.id), itx.user.display_name, m, score)
    if not ok:
        return await itx.response.send_message(err.capitalize() + ".", ephemeral=True)

    loc = ui.en_paris(m["date_kickoff_utc"])
    e = discord.Embed(
        title="✅ Prono enregistré", color=ui.couleur(m["bo"]),
        description=f"**{m['equipe_dom']}**  🆚  **{m['equipe_ext']}**\n\n"
                    f"Prono : **{detail}**"
                    + (f"   ·   🎮 {m['bo']}" if m["bo"] else ""))
    e.set_author(name=itx.user.display_name, icon_url=itx.user.display_avatar.url)
    if m["dom_logo"]:
        e.set_thumbnail(url=m["dom_logo"])
    e.add_field(
        name="Début du match" if m["bo"] else "Coup d'envoi",
        value=f"🕐 {ui.jour_label(loc)} {ui.heure_label(loc)} (Paris) · "
              f"⏱️ {ui.countdown(m['date_kickoff_utc'])}")
    e.set_footer(text="Modifiable jusqu'au coup d'envoi · résultat + score exact = 8 pts")
    await itx.response.send_message(embed=e)


@app_commands.command(name="prono_supprimer", description="Supprime ton prono sur un match")
@app_commands.describe(match="Numéro affiché par /matchs")
async def prono_supprimer_cmd(itx: discord.Interaction, match: int):
    m = db.match_by_numero(match)
    err = pronos.match_ouvert(m)
    if err:
        return await itx.response.send_message(err.capitalize() + ".", ephemeral=True)

    if not db.supprimer_prono(str(itx.user.id), m["id"]):
        return await itx.response.send_message(
            "Tu n'as pas de prono sur ce match.", ephemeral=True)

    e = discord.Embed(
        title="🗑️ Prono supprimé", color=ui.couleur(m["bo"]),
        description=f"**{m['equipe_dom']}**  🆚  **{m['equipe_ext']}**")
    e.set_author(name=itx.user.display_name, icon_url=itx.user.display_avatar.url)
    await itx.response.send_message(embed=e)


def register(tree, guild):
    tree.add_command(prono_cmd, guild=guild)
    tree.add_command(prono_supprimer_cmd, guild=guild)
