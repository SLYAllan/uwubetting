"""Correction ponctuelle : le match Belgium-Senegal (2-2 a 90', 3-2 AET) a ete
resolu avec l'ancien bareme bugge (score exact non credite si le resultat
implique par le score a 90' differait du resultat final). On recalcule les
points de ce match precis avec la logique a jour, sans toucher aux series.

A executer une seule fois la ou vit pronobot.db (meme process/volume que le
bot en prod), puis a supprimer.
"""
import db
import scoring

SD_REEL, SE_REEL = 3, 2   # score final (AET)
SD90, SE90 = 2, 2         # score a 90 minutes

with db.conn() as c:
    m = c.execute(
        "SELECT id, equipe_dom, equipe_ext FROM matchs "
        "WHERE equipe_dom LIKE '%elgium%' AND equipe_ext LIKE '%enegal%' "
        "AND resolu=1 ORDER BY date_kickoff_utc DESC LIMIT 1").fetchone()
    if not m:
        print("Match introuvable (deja corrige ou pas encore resolu ?)")
    else:
        print(f"Match #{m['id']}: {m['equipe_dom']} vs {m['equipe_ext']}")
        pronos = db.pronos_du_match(c, m["id"])
        for p in pronos:
            pts, bon, _ = scoring.calcul_points(
                p["resultat"], p["score_dom"], p["score_ext"],
                SD_REEL, SE_REEL, 0, sd90=SD90, se90=SE90)
            if pts != p["points"]:
                print(f"  user {p['user_id']}: {p['score_dom']}-{p['score_ext']} "
                      f"-> {p['points']} pts => {pts} pts")
                c.execute("UPDATE pronos SET points=? WHERE id=?", (pts, p["id"]))
            else:
                print(f"  user {p['user_id']}: {p['score_dom']}-{p['score_ext']} "
                      f"-> deja correct ({pts} pts)")
print("Termine.")
