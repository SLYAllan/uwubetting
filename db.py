"""Couche SQLite : schéma + helpers de requête.

ponytail: sqlite3 stdlib en connexion-par-opération. Les écritures bloquent la
boucle async mais le volume (quelques dizaines de lignes) rend ça négligeable ;
passer à aiosqlite si le serveur grossit beaucoup.

Écarts assumés vs le schéma du cahier des charges (voir README) :
- matchs.journee  : nécessaire pour `/matchs [journee]`
- pronos.username : afficher les noms dans `/classement` sans l'intent privilégié
"""
import os
import sqlite3
import logging
from contextlib import contextmanager
from datetime import datetime, timezone

DB = os.environ.get("DB_PATH", "pronobot.db")  # /data/pronobot.db en prod (volume)
log = logging.getLogger("pronobot.db")


@contextmanager
def conn():
    c = sqlite3.connect(DB, timeout=10)  # évite "database is locked" sous contention
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS matchs(
          id INTEGER PRIMARY KEY,
          sportsdb_event_id TEXT UNIQUE,
          league TEXT,
          numero INTEGER,
          journee INTEGER,
          equipe_dom TEXT,
          equipe_ext TEXT,
          date_kickoff_utc TEXT,
          statut TEXT,
          score_dom INTEGER,
          score_ext INTEGER,
          saison TEXT,
          provider TEXT,
          comp_nom TEXT,
          comp_logo TEXT,
          dom_logo TEXT,
          ext_logo TEXT,
          bo TEXT,
          annonce INTEGER DEFAULT 0,
          resolu INTEGER DEFAULT 0);

        CREATE TABLE IF NOT EXISTS leagues(
          league_id TEXT PRIMARY KEY,
          provider TEXT,
          nom TEXT,
          saison TEXT,
          channel_id TEXT);

        CREATE TABLE IF NOT EXISTS pronos(
          id INTEGER PRIMARY KEY,
          user_id TEXT,
          username TEXT,
          match_id INTEGER REFERENCES matchs(id),
          resultat TEXT,
          score_dom INTEGER,
          score_ext INTEGER,
          points INTEGER DEFAULT 0,
          cree_le TEXT,
          modifie_le TEXT,
          UNIQUE(user_id, match_id));

        CREATE TABLE IF NOT EXISTS streaks(
          user_id TEXT PRIMARY KEY,
          serie_actuelle INTEGER DEFAULT 0,
          meilleure_serie INTEGER DEFAULT 0);
        """)


# ---------- temps ----------
def parse_dt(s):
    if not s:
        return None
    s = s.strip()
    # ISO 8601 large (microsecondes, offset, 'Z', séparateur espace) via stdlib
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            d = datetime.strptime(s.replace("Z", "+0000"), fmt)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def now_utc():
    return datetime.now(timezone.utc)


# ---------- matchs ----------
def upsert_match(c, *, event_id, league, provider, dom, ext, kickoff, statut,
                 saison, journee, comp_nom=None, comp_logo=None,
                 dom_logo=None, ext_logo=None, bo=None):
    """Insère/maj un match. Ne touche jamais aux scores/résolution (gérés par
    la résolution), et fige le statut une fois le match résolu."""
    c.execute("""
        INSERT INTO matchs(sportsdb_event_id, league, provider, equipe_dom, equipe_ext,
                           date_kickoff_utc, statut, saison, journee,
                           comp_nom, comp_logo, dom_logo, ext_logo, bo)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(sportsdb_event_id) DO UPDATE SET
          league=excluded.league,
          provider=excluded.provider,
          equipe_dom=excluded.equipe_dom,
          equipe_ext=excluded.equipe_ext,
          date_kickoff_utc=excluded.date_kickoff_utc,
          saison=excluded.saison,
          journee=excluded.journee,
          comp_nom=excluded.comp_nom,
          comp_logo=excluded.comp_logo,
          dom_logo=excluded.dom_logo,
          ext_logo=excluded.ext_logo,
          bo=excluded.bo,
          statut=CASE WHEN matchs.resolu=1 THEN matchs.statut ELSE excluded.statut END
    """, (event_id, league, provider, dom, ext, kickoff, statut, saison, journee,
          comp_nom, comp_logo, dom_logo, ext_logo, bo))


def renumber(c):
    """Attribue un # STABLE aux nouveaux matchs à venir, sans toucher aux
    numéros existants (sinon un # changerait entre /matchs et /prono → mauvais
    pari). Compteur global jamais réutilisé (gaps possibles, c'est voulu)."""
    maxi = c.execute("SELECT COALESCE(MAX(numero), 0) FROM matchs").fetchone()[0]
    rows = c.execute(
        "SELECT id FROM matchs WHERE statut='a_venir' AND numero IS NULL "
        "ORDER BY date_kickoff_utc").fetchall()
    for i, r in enumerate(rows, maxi + 1):
        c.execute("UPDATE matchs SET numero=? WHERE id=?", (i, r["id"]))


def matchs_a_venir(journee=None, league_ids=None):
    with conn() as c:
        q = "SELECT * FROM matchs WHERE statut='a_venir'"
        args = []
        if league_ids:
            q += " AND league IN (%s)" % ",".join("?" * len(league_ids))
            args += list(league_ids)
        if journee is not None:
            q += " AND journee=?"
            args.append(journee)
        q += " ORDER BY date_kickoff_utc"
        return c.execute(q, args).fetchall()


def matchs_non_annonces(league_id):
    """Matchs à venir d'une ligue pas encore annoncés dans son salon."""
    with conn() as c:
        return c.execute(
            "SELECT * FROM matchs WHERE league=? AND statut='a_venir' AND annonce=0 "
            "ORDER BY date_kickoff_utc", (league_id,)).fetchall()


def marquer_annonces(c, ids):
    if ids:
        c.executemany("UPDATE matchs SET annonce=1 WHERE id=?", [(i,) for i in ids])


# ---------- ligues / salons ----------
def list_leagues():
    with conn() as c:
        return c.execute("SELECT * FROM leagues ORDER BY nom").fetchall()


def add_league(league_id, provider, nom, saison, channel_id):
    with conn() as c:
        c.execute("""
            INSERT INTO leagues(league_id, provider, nom, saison, channel_id)
            VALUES(?,?,?,?,?)
            ON CONFLICT(league_id) DO UPDATE SET
              provider=excluded.provider, nom=excluded.nom,
              saison=excluded.saison, channel_id=excluded.channel_id
        """, (league_id, provider, nom, saison, channel_id))


def remove_league(league_id):
    with conn() as c:
        return c.execute("DELETE FROM leagues WHERE league_id=?",
                         (league_id,)).rowcount


def leagues_for_channel(channel_id):
    with conn() as c:
        return [r["league_id"] for r in c.execute(
            "SELECT league_id FROM leagues WHERE channel_id=?",
            (str(channel_id),)).fetchall()]


def match_by_numero(numero):
    with conn() as c:
        return c.execute(
            "SELECT * FROM matchs WHERE numero=? AND statut='a_venir'", (numero,)
        ).fetchone()


def matchs_a_resoudre():
    """Tous les matchs non résolus (sauf annulés), ordre chronologique pour
    que les séries se construisent dans le bon ordre."""
    with conn() as c:
        return c.execute(
            "SELECT * FROM matchs WHERE resolu=0 AND statut<>'annule' "
            "ORDER BY date_kickoff_utc"
        ).fetchall()


def set_statut(c, match_id, statut):
    c.execute("UPDATE matchs SET statut=? WHERE id=?", (statut, match_id))


def finalise_match(c, match_id, statut, sd, se):
    c.execute("UPDATE matchs SET statut=?, score_dom=?, score_ext=?, resolu=1 "
              "WHERE id=?", (statut, sd, se, match_id))


# ---------- pronos ----------
def upsert_prono(user_id, username, match_id, resultat, sd, se):
    now = now_utc().isoformat()
    with conn() as c:
        c.execute("""
            INSERT INTO pronos(user_id, username, match_id, resultat,
                               score_dom, score_ext, cree_le, modifie_le)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(user_id, match_id) DO UPDATE SET
              resultat=excluded.resultat,
              score_dom=excluded.score_dom,
              score_ext=excluded.score_ext,
              username=excluded.username,
              modifie_le=excluded.modifie_le
        """, (user_id, username, match_id, resultat, sd, se, now, now))


def mes_pronos(user_id):
    with conn() as c:
        return c.execute("""
            SELECT p.resultat, p.score_dom, p.score_ext,
                   m.equipe_dom, m.equipe_ext, m.statut, m.date_kickoff_utc
            FROM pronos p JOIN matchs m ON m.id=p.match_id
            WHERE p.user_id=? AND m.resolu=0
            ORDER BY m.date_kickoff_utc
        """, (user_id,)).fetchall()


def pronos_du_match(c, match_id):
    return c.execute("SELECT * FROM pronos WHERE match_id=?", (match_id,)).fetchall()


def set_prono_points(c, prono_id, pts):
    c.execute("UPDATE pronos SET points=? WHERE id=?", (pts, prono_id))


# ---------- streaks ----------
def get_streak(c, user_id):
    r = c.execute("SELECT serie_actuelle, meilleure_serie FROM streaks "
                  "WHERE user_id=?", (user_id,)).fetchone()
    return (r["serie_actuelle"], r["meilleure_serie"]) if r else (0, 0)


def streaks_actuelles():
    with conn() as c:
        return {r["user_id"]: r["serie_actuelle"]
                for r in c.execute(
                    "SELECT user_id, serie_actuelle FROM streaks").fetchall()}


def set_streak(c, user_id, serie, meilleure):
    c.execute("""
        INSERT INTO streaks(user_id, serie_actuelle, meilleure_serie)
        VALUES(?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET
          serie_actuelle=excluded.serie_actuelle,
          meilleure_serie=excluded.meilleure_serie
    """, (user_id, serie, meilleure))


# ---------- classement ----------
def classement(scope="saison", league_ids=None):
    """Agrège points + % réussite par joueur. % réussite calculé uniquement
    sur les matchs 'termine'. scope 'semaine' = matchs de la semaine ISO courante.
    league_ids = restreint à certaines ligues (classement par salon/sport)."""
    q = ("SELECT p.user_id, p.username, p.points, m.statut, m.date_kickoff_utc "
         "FROM pronos p JOIN matchs m ON m.id=p.match_id")
    args = []
    if league_ids:
        q += " WHERE m.league IN (%s)" % ",".join("?" * len(league_ids))
        args += list(league_ids)
    with conn() as c:
        rows = c.execute(q, args).fetchall()

    semaine_courante = now_utc().isocalendar()[:2]
    agg = {}
    for r in rows:
        if scope == "semaine":
            d = parse_dt(r["date_kickoff_utc"])
            if not d or d.isocalendar()[:2] != semaine_courante:
                continue
        a = agg.setdefault(r["user_id"], {
            "user_id": r["user_id"], "username": r["username"],
            "pts": 0, "bons": 0, "resolus": 0})
        a["username"] = r["username"] or a["username"]
        a["pts"] += r["points"] or 0
        if r["statut"] == "termine":
            a["resolus"] += 1
            if (r["points"] or 0) > 0:
                a["bons"] += 1

    table = list(agg.values())
    for a in table:
        a["pct"] = (a["bons"] / a["resolus"] * 100) if a["resolus"] else 0.0
    table.sort(key=lambda a: (-a["pts"], -a["pct"]))
    return table
