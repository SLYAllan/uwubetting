"""/aide — mode d'emploi du bot."""
import discord
from discord import app_commands

import ui


@app_commands.command(name="aide", description="Comment utiliser le bot de pronos")
async def aide_cmd(itx: discord.Interaction):
    e = discord.Embed(
        title="🆘 Aide — Bot de pronos", color=ui.BLEU,
        description="Pronostique les matchs, gagne des points, grimpe au classement !"
                    "\nChaque salon a son sport : tu ne vois que ses matchs.")
    e.add_field(name="🎮 Joueurs", value=(
        "`/matchs [journee]` — les matchs à parier **dans ce salon**\n"
        "`/prono match:<#> resultat:<1|N|2> [score:2-1]` — ton prono "
        "(modifiable jusqu'au coup d'envoi)\n"
        "`/mes_pronos` — tes pronos en cours\n"
        "`/classement [saison|semaine]` — le classement **de ce salon**\n"
        "`/sports` — les compétitions suivies\n"
        "`/aide` — ce message"), inline=False)
    e.add_field(name="🏆 Points", value=(
        "Bon résultat **3 pts** · score exact **8 pts** · "
        "série de 3 bons pronos ou + 🔥 **+1 pt** par bon prono"), inline=False)
    e.add_field(name="🛠️ Admins", value=(
        "`/sport_ajouter provider:<> league_id:<> nom:<> salon:<#>` — "
        "lier une compétition à un salon (ex CDM 2026, LEC…)\n"
        "`/sport_retirer league_id:<>` — délier\n"
        "`/refresh` — forcer la mise à jour des matchs\n"
        "`/chercher_ligue provider:<> nom:<> [jeu:<>]` — **trouver l'ID** d'un "
        "tournoi sans quitter Discord"), inline=False)
    e.add_field(name="🔎 Trouver l'ID d'un tournoi", value=(
        "Le plus simple : **`/chercher_ligue`** (ex `nom:LEC jeu:League of Legends`, "
        "ou `provider:Foot/NBA nom:Premier`).\n\n"
        "Ou parcourir les listes complètes :\n"
        "• Foot/NBA : [toutes les ligues TheSportsDB]"
        "(https://www.thesportsdb.com/api/v1/json/3/all_leagues.php) "
        "(Ctrl+F le nom → `idLeague`)\n"
        "• Esport : [API PandaScore /leagues]"
        "(https://developers.pandascore.co/reference/get_leagues)\n"
        "• Foot gratuit complet (ESPN, sans clé, calendrier complet type CDM) : "
        "`/chercher_ligue provider:ESPN nom:<mot-clé>` (ex `Coupe du Monde`, "
        "`Premier League`)\n\n"
        "IDs courants : 4328 Premier League · 4334 Ligue 1 · 4387 NBA · "
        "4480 Champions League · 4197 LEC · 293 LCK · `fifa.world` CDM (ESPN)"),
        inline=False)
    await itx.response.send_message(embed=e, ephemeral=True)


def register(tree, guild):
    tree.add_command(aide_cmd, guild=guild)
