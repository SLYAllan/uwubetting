"""Helpers d'affichage partagés (commandes + annonces auto du scheduler)."""
from zoneinfo import ZoneInfo

import discord

import db
import pronos

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
    """Timestamp Discord natif : live, localisé dans la langue du client de
    chacun ("in 3 hours" / "dans 3 heures"...). '🔴 en cours' si déjà passé."""
    d = db.parse_dt(iso)
    if not d:
        return ""
    if d <= db.now_utc():
        return "🔴 en cours"
    return f"<t:{int(d.timestamp())}:R>"


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


class ProsRapidesModal(discord.ui.Modal, title="Pronos rapides"):
    """Un prono par ligne (numero:score), pour parier sur toute une page
    d'un coup au lieu d'enchaîner les /prono un par un."""

    def __init__(self, rows):
        super().__init__()
        self.rows = {r["numero"]: r for r in rows}
        exemple = "\n".join(f"{r['numero']}:2-1" for r in rows[:4])
        self.saisie = discord.ui.TextInput(
            label="Format : numero:score (1 par ligne)",
            style=discord.TextStyle.paragraph,
            placeholder=exemple or "1:2-1")
        self.add_item(self.saisie)

    async def on_submit(self, itx: discord.Interaction):
        oks, erreurs = [], []
        for ligne in (l.strip() for l in self.saisie.value.splitlines()):
            if not ligne:
                continue
            num_str, sep, score = ligne.partition(":")
            if not sep:
                erreurs.append(f"`{ligne}` : format attendu `numero:score`")
                continue
            try:
                num = int(num_str.strip())
            except ValueError:
                erreurs.append(f"`{ligne}` : numéro invalide")
                continue
            m = self.rows.get(num)
            if not m:
                erreurs.append(f"#{num} : pas sur cette page")
                continue
            err = pronos.match_ouvert(m)
            if err:
                erreurs.append(f"#{num} : {err}")
                continue
            ok, err, detail = pronos.enregistrer(
                str(itx.user.id), itx.user.display_name, m, score.strip())
            if ok:
                oks.append(f"#{num} · {m['equipe_dom']} 🆚 {m['equipe_ext']} → **{detail}**")
            else:
                erreurs.append(f"#{num} : {err}")

        desc = ""
        if oks:
            desc += "✅ **Enregistrés**\n" + "\n".join(oks)
        if erreurs:
            desc += ("\n\n" if desc else "") + "⚠️ **Erreurs**\n" + "\n".join(erreurs)
        e = discord.Embed(title="🎯 Pronos rapides", color=BLEU,
                          description=desc or "Rien à traiter.")
        await itx.response.send_message(embed=e)


class MatchsView(discord.ui.View):
    """Boutons de pagination (actifs en permanence, pas de timeout) + prono
    rapide sur la page actuellement affichée."""

    def __init__(self, pages, embeds):
        super().__init__(timeout=None)
        self.pages = pages
        self.embeds = embeds
        self.i = 0
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

    @discord.ui.button(label="🎯 Prono rapide", style=discord.ButtonStyle.success)
    async def prono_rapide(self, itx: discord.Interaction, _btn):
        rows = self.pages[self.i]
        if not rows:
            return await itx.response.send_message(
                "Aucun match sur cette page.", ephemeral=True)
        await itx.response.send_modal(ProsRapidesModal(rows))
