# UwuBetting — Bot Discord de pronos ⚽🎮🔥

Pronos entre potes sur **foot, NBA et esport**. Chaque compétition est liée à
son propre salon (1 salon = 1 sport, pas de mélange), les matchs y popent tout
seuls, le bot récupère les scores automatiquement et tient un classement par
salon. Foot/NBA via **TheSportsDB** (gratuit), esport via **PandaScore**.

## Arborescence
```
bot.py            # entrée : env, sync commandes, logging, lance le scheduler
db.py             # SQLite : schéma + helpers de requête
sportsdb.py       # client TheSportsDB (throttle 1 req/s + retry backoff)
pandascore.py     # client PandaScore (esport), même interface que sportsdb
scoring.py        # calcul des points (pur, testable: python scoring.py)
scheduler.py      # jobs APScheduler : refresh (00h00 Paris) + résolution (1h)
ui.py             # embeds + pagination à boutons
commands/         # slash commands
  matchs · prono · mes_pronos · classement · sports · aide
requirements.txt · .env.example · Dockerfile · docker-compose.yml · pronobot.service
```

## Commandes
**Joueurs**
- `/matchs [journee]` — matchs à venir **de ce salon** (boutons ◀️▶️ pour paginer)
- `/prono match:<#> resultat:<1|N|2> [score:2-1]` — modifiable jusqu'au coup d'envoi
- `/mes_pronos` — tes pronos en cours
- `/classement [saison|semaine]` — classement **de ce salon**, + ton rang
- `/sports` · `/aide`

**Admins** (permission *Gérer le serveur*)
- `/sport_ajouter provider:<> league_id:<> nom:<> salon:<#> [saison:<>]` — lier une compétition à un salon
- `/sport_retirer league_id:<>` · `/refresh` (forcer la MAJ)
- `/chercher_ligue provider:<> nom:<> [jeu:<>]` — trouver l'ID d'un tournoi

## Mise en place (ex : un salon CDM, un salon LEC)
```
/chercher_ligue provider:Esport nom:LEC jeu:League of Legends     → 4197
/sport_ajouter  provider:Esport league_id:4197 nom:"LEC 2026" salon:#lec-2026
/sport_ajouter  provider:Foot/NBA league_id:<id CDM> nom:"CDM 2026" salon:#cdm-2026 saison:2026
```
Chaque salon affiche/parie uniquement son sport ; les matchs y sont postés
automatiquement à chaque refresh (00h00 Paris) ou via `/refresh`.

## Points 🔥
- Bon résultat (1/N/2) : **3 pts**
- Score exact (en plus) : **+5 pts** → **8 pts** au total
- En feu (3 bons d'affilée ou +) : **+1 pt bonus** par bon prono tant que la série tient

Un mauvais prono casse la série ; la meilleure série ne redescend jamais. Le
% réussite = `bons / pronos_sur_matchs_terminés` (ignore les matchs non résolus
et les reportés/annulés).

## Écarts au schéma initial (assumés)
- `matchs.journee` ajouté — requis par `/matchs [journee]` (mappé sur `intRound`).
- `pronos.username` ajouté — afficher les noms dans `/classement` sans activer
  l'intent privilégié *Server Members* (les intents par défaut ne donnent pas
  le cache des membres).

## Config Discord
Crée l'appli sur https://discord.com/developers → scopes `applications.commands`
+ `bot`, permissions *Send Messages · Use Slash Commands · Embed Links*. Récupère
le **token**. `GUILD_ID` = clic droit sur le serveur → Copier l'identifiant (mode
dev activé) ; le sync guild-scoped est instantané.

`.env` : `DISCORD_TOKEN`, `GUILD_ID` (obligatoires) + `SPORTSDB_API_KEY`,
`PANDASCORE_TOKEN` selon les sports utilisés. `PROVIDER`/`LEAGUE_ID`/`SEASON`
ne servent qu'à amorcer une 1ʳᵉ ligue ; tout le reste se gère via `/sport_ajouter`.

## Déploiement Coolify (Docker, sur le VPS Hetzner)
Le bot est un *worker* (aucun port web). Déploiement via `docker-compose.yml`.

1. **New Resource → Docker Compose** (ou *Git Repo*, Coolify détecte le compose),
   pointe sur ce dépôt.
2. **Environment Variables** (onglet Coolify) — ne mets PAS de `.env` dans le repo :
   ```
   DISCORD_TOKEN=...        GUILD_ID=...
   PROVIDER=pandascore      PANDASCORE_TOKEN=...
   LEAGUE_ID=4197           SEASON=
   ```
   (Pour foot/NBA : `PROVIDER=sportsdb`, `SPORTSDB_API_KEY=3`, `LEAGUE_ID=4328`,
   `SEASON=2025-2026`.)
3. **Deploy.** Le volume `pronobot-data` (monté sur `/data`) persiste la base
   SQLite entre les redeploys — sinon le classement repartirait de zéro à chaque
   déploiement. `DB_PATH=/data/pronobot.db` est déjà câblé dans le compose.
4. **Logs** : visibles dans Coolify (le bot logge sur stdout).
   `restart: unless-stopped` le relance s'il plante.

> Worker sans port : pas de health check. Si Coolify en réclame un, désactive-le
> pour ce service. `pronobot.service` (systemd) reste fourni si tu veux du nu un jour.

## Changer de sport/ligue
Modifie `LEAGUE_ID` + `SEASON` dans `.env` (NBA = `4387`). Le scoring 1/N/2 +
score exact marche tel quel pour foot et basket ; seul le mapping de statut
(`sportsdb.mapper_statut`) gère les libellés API.

## Esport (PandaScore)
Couverture esport complète (LoL, CS2, Valorant, Dota) via PandaScore plutôt que
le tier gratuit TheSportsDB (pauvre en esport). Dans `.env` :
```env
PROVIDER=pandascore
PANDASCORE_TOKEN=<ta_clé>
LEAGUE_ID=4197      # LEC. SEASON est ignoré en mode pandascore
```
Le score = maps gagnées (Bo3/Bo5) → un prono `2-1` exact rapporte les 8 pts.
Pas de nul en esport : le choix `N` ne gagne jamais (1/N/2 reste correct).

Trouver un `LEAGUE_ID` PandaScore (token requis) :
```bash
curl -H "Authorization: Bearer $PANDASCORE_TOKEN" \
  "https://api.pandascore.co/lol/leagues?search[name]=LEC"
# IDs utiles : 4197 LEC · 293 LCK · 5347 LTA · /csgo/leagues, /valorant/leagues...
```
`pandascore.py` est un drop-in de `sportsdb.py` (mêmes fonctions), donc DB,
scoring et commandes sont inchangés.

## Tests
```bash
python scoring.py   # doit afficher "scoring ok"
```
