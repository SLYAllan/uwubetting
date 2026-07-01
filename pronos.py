"""Logique partagée d'enregistrement d'un prono, utilisée par /prono et par
le bouton "Prono rapide" (modal) de /matchs — pour ne pas dupliquer la
validation entre les deux points d'entrée."""
import re

import db
import scoring

_SCORE_RE = re.compile(r"\s*(\d+)\s*-\s*(\d+)\s*")


def match_ouvert(m):
    """Message d'erreur si le match n'existe pas ou a déjà commencé, sinon None."""
    if not m:
        return "match introuvable"
    if (db.parse_dt(m["date_kickoff_utc"]) or db.now_utc()) <= db.now_utc():
        return "match déjà commencé"
    return None


def enregistrer(user_id, username, m, score_str):
    """Valide puis enregistre un prono sur le match `m` (row db).

    Retourne (ok, message_erreur, detail) — `detail` = "sd-se" si ok.
    """
    mm = _SCORE_RE.fullmatch(score_str)
    if not mm:
        return False, f"format de score invalide (`{score_str}`), attendu `2-1`", None
    sd, se = int(mm.group(1)), int(mm.group(2))
    if not scoring.score_valide_pour_bo(m["bo"], sd, se):
        return False, (f"score `{sd}-{se}` impossible pour un match {m['bo']} "
                       "(pas de nul, le vainqueur doit atteindre le seuil de victoire)"), None
    resultat = scoring.resultat_depuis_score(sd, se)
    db.upsert_prono(user_id, username, m["id"], resultat, sd, se)
    return True, "", f"{sd}-{se}"
