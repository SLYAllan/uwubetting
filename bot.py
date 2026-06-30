"""Point d'entrée du bot de pronos. Charge le .env, sync les commandes, lance
le scheduler. Logs vers pronobot.log (rotation) + stdout (journalctl/Coolify)."""
import os
import sys
import logging
from logging.handlers import RotatingFileHandler

import discord
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()

import db          # noqa: E402  (après load_dotenv)
import scheduler   # noqa: E402
from commands import setup_commands  # noqa: E402

log = logging.getLogger("pronobot")


def setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    fichier = RotatingFileHandler("pronobot.log", maxBytes=5_000_000,
                                  backupCount=3, encoding="utf-8")
    fichier.setFormatter(fmt)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(fichier)
    root.addHandler(console)


def seed_league():
    """Amorce une ligue depuis le .env si la table est vide (sans salon ; à lier
    ensuite avec /sport_ajouter). Optionnel : tout peut se gérer par commande."""
    lid = os.environ.get("LEAGUE_ID")
    if lid and not db.list_leagues():
        db.add_league(lid, os.environ.get("PROVIDER", "sportsdb"),
                      os.environ.get("LEAGUE_NOM", "Ligue"),
                      os.environ.get("SEASON", ""), None)


TOKEN = os.environ["DISCORD_TOKEN"]
GUILD = discord.Object(id=int(os.environ["GUILD_ID"]))


async def on_tree_error(itx: discord.Interaction, err):
    if isinstance(err, app_commands.MissingPermissions):
        msg = "⛔ Réservé aux admins (permission « Gérer le serveur »)."
    else:
        log.exception("erreur commande: %s", err)
        msg = "Une erreur est survenue."
    send = itx.followup.send if itx.response.is_done() else itx.response.send_message
    await send(msg, ephemeral=True)


class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        db.init()
        seed_league()
        setup_commands(self.tree, GUILD)
        self.tree.on_error = on_tree_error
        await self.tree.sync(guild=GUILD)
        scheduler.start(self)              # mémorise le client + planifie les jobs
        log.info("commandes synchronisées sur la guild %s", GUILD.id)

    async def on_ready(self):
        # 1er remplissage ici (pas dans setup_hook) : le cache des salons est
        # peuplé, donc l'auto-annonce fonctionne dès le 1er démarrage.
        if getattr(self, "_did_initial_refresh", False):
            return
        self._did_initial_refresh = True
        try:
            await scheduler.refresh_matchs()
        except Exception:
            log.exception("refresh initial échoué")
        log.info("bot prêt (%s)", self.user)


if __name__ == "__main__":
    setup_logging()
    Bot().run(TOKEN, log_handler=None)
