"""Enregistre toutes les slash commands sur l'arbre, scope guild."""
from . import matchs, prono, mes_pronos, classement, sports, aide


def setup_commands(tree, guild):
    for module in (matchs, prono, mes_pronos, classement, sports, aide):
        module.register(tree, guild)
