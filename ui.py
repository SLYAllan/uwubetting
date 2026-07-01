"""Helpers d'affichage partagés (commandes + annonces auto du scheduler)."""
from zoneinfo import ZoneInfo

import discord

import db

PARIS = ZoneInfo("Europe/Paris")
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

VERT = 0x2ecc71      # foot/NBA
VIOLET = 0x9b59b6    # esport
BLEU = 0x3498db      # classement


def couleur(bo):
    return VIOLET if bo else VERT


def en_paris(iso):
    d = db.parse_dt(iso)
    return d.astimezone(PARIS) if d else None


def jour_label(loc):
    return f"{JOURS[loc.weekday()]} {loc:%d/%m}" if loc else "Date inconnue"


def heure_label(loc):
    return f"{loc:%H:%M}" if loc else "--:--"


def countdown(iso):
    """'dans 2j 3h' / 'dans 4h05' / 'dans 12min' / '🔴 en cours'."""
    d = db.parse_dt(iso)
    if not d:
        return ""
    secs = int((d - db.now_utc()).total_seconds())
    if secs <= 0:
        return "🔴 en cours"
    jours, reste = divmod(secs, 86400)
    heures, reste = divmod(reste, 3600)
    minutes = reste // 60
    if jours:
        return f"dans {jours}j {heures}h"
    if heures:
        return f"dans {heures}h{minutes:02d}"
    return f"dans {minutes}min"


def barre(pct):
    """Petite jauge sur 5 blocs : ▰▰▰▱▱."""
    plein = round(pct / 20)
    return "▰" * plein + "▱" * (5 - plein)


PAR_PAGE = 8  # matchs/page max PAR JOUR -> au pire 16 champs, sous la limite Discord (25)


def paginer(rows, par_page=PAR_PAGE):
    """Une page par jour (jamais deux jours mélangés sur une page). Un jour
    avec plus de `par_page` matchs se scinde quand même en plusieurs pages."""
    pages = []
    jour_courant, bloc = None, []
    for r in rows:
        jour = jour_label(en_paris(r["date_kickoff_utc"]))
        if jour != jour_courant:
            pages += [bloc[i:i + par_page] for i in range(0, len(bloc), par_page)]
            jour_courant, bloc = jour, []
        bloc.append(r)
    pages += [bloc[i:i + par_page] for i in range(0, len(bloc), par_page)]
    return pages or [[]]


def matchs_embed(rows, titre, page=1, total=1):
    """Embed listant une page de matchs groupés par date (réutilisé par /matchs
    et l'annonce auto). `rows` est déjà une page (<= PAR_PAGE matchs)."""
    esport = any(r["bo"] for r in rows)
    e = discord.Embed(title=titre, color=couleur(esport))
    if rows and rows[0]["comp_logo"]:
        e.set_thumbnail(url=rows[0]["comp_logo"])

    jour_courant = None
    for r in rows:
        loc = en_paris(r["date_kickoff_utc"])
        jour = jour_label(loc)
        if jour != jour_courant:
            jour_courant = jour
            e.add_field(name=f"📅 {jour}", value="​", inline=False)
        infos = [f"🕐 {heure_label(loc)} (Paris)"]
        cd = countdown(r["date_kickoff_utc"])
        if cd:
            infos.append(f"⏱️ {cd}")
        if r["bo"]:
            infos.append(f"🎮 {r['bo']}")
        if r["journee"]:
            infos.append(f"J{r['journee']}")
        e.add_field(name=f"#{r['numero']} · {r['equipe_dom']} 🆚 {r['equipe_ext']}",
                    value=" · ".join(infos), inline=False)

    pied = "/prono match:<#> score:<2-1>"
    if total > 1:
        pied = f"Page {page}/{total}  ·  " + pied
    e.set_footer(text=pied)
    return e


def matchs_pages(rows, titre):
    """Liste d'embeds, un par page de matchs."""
    pages = paginer(rows)
    return [matchs_embed(p, titre, i + 1, len(pages)) for i, p in enumerate(pages)]


class MatchsView(discord.ui.View):
    """Boutons de pagination pour parcourir les autres matchs."""

    def __init__(self, embeds, timeout=300):
        super().__init__(timeout=timeout)
        self.embeds = embeds
        self.i = 0
        self.message = None
        self._sync()

    def _sync(self):
        self.prev.disabled = self.i == 0
        self.suiv.disabled = self.i == len(self.embeds) - 1

    @discord.ui.button(label="◀️ Précédent", style=discord.ButtonStyle.secondary)
    async def prev(self, itx: discord.Interaction, _btn):
        self.i = max(0, self.i - 1)
        self._sync()
        await itx.response.edit_message(embed=self.embeds[self.i], view=self)

    @discord.ui.button(label="Autres matchs ▶️", style=discord.ButtonStyle.primary)
    async def suiv(self, itx: discord.Interaction, _btn):
        self.i = min(len(self.embeds) - 1, self.i + 1)
        self._sync()
        await itx.response.edit_message(embed=self.embeds[self.i], view=self)

    async def on_timeout(self):
        for b in self.children:
            b.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPError:
                pass
