"""/classement — top 10 DU SALON courant (par sport), sinon classement général."""
from typing import Optional

import discord
from discord import app_commands

import db
import ui

MEDALS = ["🥇", "🥈", "🥉"]


def _ligne(a):
    return (f"**{a['pts']} pts**  ·  {ui.barre(a['pct'])} {round(a['pct'])}%  "
            f"({a['bons']}/{a['resolus']})")


@app_commands.command(name="classement", description="Classement de ce salon")
@app_commands.choices(periode=[
    app_commands.Choice(name="Saison", value="saison"),
    app_commands.Choice(name="Cette semaine", value="semaine"),
])
async def classement_cmd(itx: discord.Interaction,
                         periode: Optional[app_commands.Choice[str]] = None):
    scope = periode.value if periode else "saison"
    league_ids = db.leagues_for_channel(itx.channel_id)
    table = db.classement(scope, league_ids or None)
    if not table:
        return await itx.response.send_message("Pas encore de résultats ici.")

    streaks = db.streaks_actuelles()
    noms = {l["league_id"]: l["nom"] for l in db.list_leagues()}
    portee = (", ".join(noms.get(i, i) for i in league_ids)
              if league_ids else "tous sports")
    titre = "cette semaine" if scope == "semaine" else "saison"
    e = discord.Embed(title=f"📊 Classement {portee} — {titre}", color=ui.BLEU)
    for i, a in enumerate(table[:10]):
        rank = MEDALS[i] if i < 3 else f"`{i+1}.`"
        fire = " 🔥" if streaks.get(a["user_id"], 0) >= 3 else ""
        e.add_field(name=f"{rank} {a['username']}{fire}", value=_ligne(a), inline=False)

    me = str(itx.user.id)
    rank_me = next((i for i, a in enumerate(table) if a["user_id"] == me), None)
    if rank_me is not None and rank_me >= 10:
        a = table[rank_me]
        e.add_field(name=f"… `{rank_me+1}.` {a['username']} (toi)",
                    value=_ligne(a), inline=False)

    e.set_footer(text=f"{len(table)} joueurs · 🔥 = série de 3 bons pronos ou +")
    await itx.response.send_message(embed=e)


def register(tree, guild):
    tree.add_command(classement_cmd, guild=guild)
