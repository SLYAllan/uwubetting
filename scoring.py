"""Calcul des points — logique pure, testable en standalone (`python scoring.py`).

Barème :
- Bon résultat (1/N/2)      : 3 pts
- Score exact (en plus)     : +5 pts  -> 8 pts au total
- En feu (3 bons d'affilée+): +1 pt bonus par bon prono tant que la série tient

Un mauvais prono casse la série (serie_actuelle -> 0). meilleure_serie ne baisse jamais.
"""
import re

POINTS_BON = 3
BONUS_EXACT = 5
SEUIL_FEU = 3      # à partir du 3e bon prono consécutif
BONUS_FEU = 1

_BO_RE = re.compile(r"Bo(\d+)", re.IGNORECASE)


def resultat_depuis_score(sd, se):
    """'1' (dom), '2' (ext) ou 'N' (nul) à partir d'un score."""
    if sd > se:
        return "1"
    if sd < se:
        return "2"
    return "N"


def score_valide_pour_bo(bo, sd, se):
    """Score cohérent avec le format du match. Foot (bo=None) : tout score

    valide, nul autorisé. Esport (Bo1/Bo3/Bo5) : pas de nul, le vainqueur
    doit atteindre exactement le seuil de victoire (1 en Bo1, 2 en Bo3, 3 en
    Bo5) et le perdant rester strictement en dessous.
    """
    if not bo:
        return True
    m = _BO_RE.match(bo)
    if not m:
        return True
    seuil = (int(m.group(1)) + 1) // 2
    if sd == se:
        return False
    gagnant, perdant = max(sd, se), min(sd, se)
    return gagnant == seuil and 0 <= perdant < seuil


def calcul_points(resultat_pred, sd_pred, se_pred, sd_reel, se_reel, serie_avant,
                   sd90=None, se90=None):
    """Retourne (points, bon, nouvelle_serie) pour un match TERMINÉ.

    Le résultat (1/N/2) se juge sur sd_reel/se_reel (score après prolongation
    éventuelle, hors tirs au but). Le bonus score exact se juge sur sd90/se90
    (score à 90 minutes) quand fournis -- sinon on retombe sur sd_reel/se_reel
    (esport, NBA : pas de notion de prolongation).
    serie_avant = streaks.serie_actuelle du joueur avant ce match (chronologique).
    """
    bon = resultat_pred == resultat_depuis_score(sd_reel, se_reel)
    if not bon:
        return 0, False, 0  # série cassée
    nouvelle_serie = serie_avant + 1
    pts = POINTS_BON
    sd_exact = sd_reel if sd90 is None else sd90
    se_exact = se_reel if se90 is None else se90
    if sd_pred is not None and se_pred is not None \
            and sd_pred == sd_exact and se_pred == se_exact:
        pts += BONUS_EXACT
    if nouvelle_serie >= SEUIL_FEU:
        pts += BONUS_FEU
    return pts, True, nouvelle_serie


def points_si_termine(statut, resultat_pred, sd_pred, se_pred, sd_reel, se_reel, serie_avant,
                       sd90=None, se90=None):
    """Reporté/annulé => 0 pt, série inchangée. Sinon délègue à calcul_points."""
    if statut != "termine":
        return 0, False, serie_avant
    return calcul_points(resultat_pred, sd_pred, se_pred, sd_reel, se_reel, serie_avant, sd90, se90)


def pourcentage_reussite(pronos):
    """% réussite = bons / résolus. Ignore les matchs non terminés.

    pronos: itérable de dicts avec 'termine' (bool) et 'bon' (bool).
    """
    resolus = [p for p in pronos if p["termine"]]
    if not resolus:
        return 0.0
    return sum(1 for p in resolus if p["bon"]) / len(resolus) * 100


def demo():
    assert resultat_depuis_score(2, 1) == "1"
    assert resultat_depuis_score(0, 0) == "N"
    assert resultat_depuis_score(1, 3) == "2"

    # bon résultat simple
    assert calcul_points("1", None, None, 2, 1, 0) == (3, True, 1)
    # score exact => 8
    assert calcul_points("1", 2, 1, 2, 1, 0) == (8, True, 1)
    # bon résultat mais score exact raté => 3
    assert calcul_points("1", 3, 0, 2, 1, 0) == (3, True, 1)
    # mauvais prono => 0 et série remise à 0
    assert calcul_points("2", None, None, 2, 1, 5) == (0, False, 0)
    # en feu : 3e bon d'affilée => +1 (3 -> 4)
    assert calcul_points("1", None, None, 2, 1, 2) == (4, True, 3)
    # score exact en feu => 8 + 1 = 9
    assert calcul_points("1", 2, 1, 2, 1, 2) == (9, True, 3)

    # série cassée par un mauvais prono (réel = victoire dom 2-1)
    serie = 0
    for pred in ("1", "1", "1", "2"):
        _, _, serie = calcul_points(pred, None, None, 2, 1, serie)
    assert serie == 0

    # match reporté => 0 pt, série inchangée
    assert points_si_termine("reporte", "1", None, None, 2, 1, 4) == (0, False, 4)

    # prolongation : nul à 90' (2-2), dom gagne après prolongation (3-2)
    # -> résultat jugé sur 3-2 (victoire dom), score exact jugé sur 2-2
    assert calcul_points("1", 2, 2, 3, 2, 0, sd90=2, se90=2) == (8, True, 1)
    assert calcul_points("N", 2, 2, 3, 2, 0, sd90=2, se90=2) == (0, False, 0)

    # cohérence score / format de match
    assert score_valide_pour_bo(None, 1, 1) is True        # nul autorisé au foot
    assert score_valide_pour_bo("Bo1", 1, 0) is True
    assert score_valide_pour_bo("Bo1", 1, 1) is False       # pas de nul en esport
    assert score_valide_pour_bo("Bo3", 2, 1) is True
    assert score_valide_pour_bo("Bo3", 2, 2) is False
    assert score_valide_pour_bo("Bo3", 3, 0) is False       # score impossible en Bo3
    assert score_valide_pour_bo("Bo5", 3, 2) is True
    assert score_valide_pour_bo("Bo5", 4, 0) is False

    # % réussite ignore les matchs non résolus
    pr = [{"termine": True, "bon": True},
          {"termine": True, "bon": False},
          {"termine": False, "bon": False}]
    assert pourcentage_reussite(pr) == 50.0

    print("scoring ok")


if __name__ == "__main__":
    demo()
