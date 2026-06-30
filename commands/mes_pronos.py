"""/mes_pronos — pronos de l'utilisateur sur les matchs non encore résolus."""
import discord
from discord import app_commands

import db
import ui

TAG = {"a_venir": "⏳", "en_cours": "▶️", "reporte": "⏸️"}


@app_commands.command(name="mes_pronos", description="Tes pronos en cours")
async def mes_pronos_cmd(itx: discord.Interaction):
    rows = db.mes_pronos(str(itx.user.id))
    if not rows:
        return await itx.response.send_message(
            "Tu n'as aucun prono en cours.", ephemeral=True)

    e = discord.Embed(title="📋 Tes pronos en cours", color=ui.BLEU)
    for r in rows[:25]:
        pick = r["resultat"]
        if r["score_dom"] is not None:
            pick += f" {r['score_dom']}-{r['score_ext']}"
        tag = TAG.get(r["statut"], "⏳")
        loc = ui.en_paris(r["date_kickoff_utc"])
        when = ("⏸️ Reporté" if r["statut"] == "reporte"
                else f"{ui.heure_label(loc)} · {ui.countdown(r['date_kickoff_utc'])}")
        e.add_field(name=f"{tag} {r['equipe_dom']} 🆚 {r['equipe_ext']}",
                    value=f"Prono **{pick}**  ·  {when}", inline=False)
    await itx.response.send_message(embed=e, ephemeral=True)


def register(tree, guild):
    tree.add_command(mes_pronos_cmd, guild=guild)
