"""Commandes admin : lier/délier une compétition à un salon, lister, forcer refresh."""
import discord
from discord import app_commands

import db
import scheduler
import sportsdb
import pandascore

ADMIN = app_commands.checks.has_permissions(manage_guild=True)
_MODS = {"sportsdb": sportsdb, "pandascore": pandascore}


@app_commands.command(name="sport_ajouter",
                      description="[Admin] Lier une compétition à un salon")
@app_commands.describe(provider="Source de données",
                       league_id="ID de la ligue (voir /aide)",
                       nom="Nom affiché, ex « CDM 2026 »",
                       salon="Salon où les matchs vont apparaître",
                       saison="Saison foot/NBA (ex 2025-2026) ; vide en esport")
@app_commands.choices(provider=[
    app_commands.Choice(name="Foot / NBA (TheSportsDB)", value="sportsdb"),
    app_commands.Choice(name="Esport (PandaScore)", value="pandascore"),
])
@ADMIN
async def sport_ajouter(itx: discord.Interaction,
                        provider: app_commands.Choice[str], league_id: str,
                        nom: str, salon: discord.TextChannel, saison: str = None):
    await itx.response.defer(ephemeral=True)
    db.add_league(league_id, provider.value, nom, saison or "", str(salon.id))
    await scheduler.refresh_matchs()
    await itx.followup.send(
        f"✅ **{nom}** ({provider.value}) lié à {salon.mention}. "
        "Les matchs vont y apparaître automatiquement.", ephemeral=True)


@app_commands.command(name="sport_retirer", description="[Admin] Délier une compétition")
@app_commands.describe(league_id="ID de la ligue (voir /sports)")
@ADMIN
async def sport_retirer(itx: discord.Interaction, league_id: str):
    n = db.remove_league(league_id)
    await itx.response.send_message(
        "🗑️ Compétition retirée." if n else "Aucune compétition avec cet ID.",
        ephemeral=True)


@app_commands.command(name="sports", description="Compétitions suivies et leurs salons")
async def sports_cmd(itx: discord.Interaction):
    lgs = db.list_leagues()
    if not lgs:
        return await itx.response.send_message(
            "Aucune compétition. Un admin : `/sport_ajouter`.", ephemeral=True)
    lines = []
    for l in lgs:
        salon = f"<#{l['channel_id']}>" if l["channel_id"] else "_(aucun salon)_"
        lines.append(f"`{l['league_id']}` · **{l['nom']}** "
                     f"({l['provider']}) → {salon}")
    e = discord.Embed(title="🏆 Compétitions suivies",
                      description="\n".join(lines), color=0x9b59b6)
    await itx.response.send_message(embed=e)


@app_commands.command(name="refresh",
                      description="[Admin] Forcer la mise à jour des matchs")
@ADMIN
async def refresh_cmd(itx: discord.Interaction):
    await itx.response.defer(ephemeral=True)
    await scheduler.refresh_matchs()
    await itx.followup.send("🔄 Matchs mis à jour.", ephemeral=True)


@app_commands.command(name="chercher_ligue",
                      description="[Admin] Trouver l'ID d'une compétition/tournoi")
@app_commands.describe(provider="Source de données",
                       nom="Mot-clé, ex « World Cup », « LEC », « NBA »",
                       jeu="Esport : précise le jeu pour un résultat fiable")
@app_commands.choices(
    provider=[
        app_commands.Choice(name="Foot / NBA (TheSportsDB)", value="sportsdb"),
        app_commands.Choice(name="Esport (PandaScore)", value="pandascore"),
    ],
    jeu=[
        app_commands.Choice(name="League of Legends", value="lol"),
        app_commands.Choice(name="Counter-Strike", value="csgo"),
        app_commands.Choice(name="Valorant", value="valorant"),
        app_commands.Choice(name="Dota 2", value="dota2"),
        app_commands.Choice(name="Overwatch", value="ow"),
        app_commands.Choice(name="Rainbow 6", value="r6siege"),
        app_commands.Choice(name="Rocket League", value="rl"),
    ])
@ADMIN
async def chercher_ligue(itx: discord.Interaction,
                         provider: app_commands.Choice[str], nom: str,
                         jeu: app_commands.Choice[str] = None):
    await itx.response.defer(ephemeral=True)
    try:
        res = await _MODS[provider.value].search_leagues(
            nom, jeu.value if jeu else None)
    except Exception:
        return await itx.followup.send(
            "Recherche impossible (jeu inconnu ou API indispo).", ephemeral=True)
    if not res:
        return await itx.followup.send(
            f"Rien trouvé pour « {nom} ».", ephemeral=True)
    lines = [f"`{r['id']}` · **{r['nom']}**"
             + (f"  _({r['jeu']})_" if r.get("jeu") else "") for r in res[:15]]
    e = discord.Embed(title=f"🔎 Résultats « {nom} »",
                      description="\n".join(lines), color=0x9b59b6)
    e.set_footer(text=f"Copie l'ID dans /sport_ajouter (provider : {provider.value})")
    await itx.followup.send(embed=e, ephemeral=True)


def register(tree, guild):
    for cmd in (sport_ajouter, sport_retirer, sports_cmd, refresh_cmd, chercher_ligue):
        tree.add_command(cmd, guild=guild)
