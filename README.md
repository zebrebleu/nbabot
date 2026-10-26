# Assistant d'analyse de paris NBA

Récupère les matchs NBA du jour, applique des filtres stricts anti-pièges et propose
un combiné de 2 matchs autour de 1.80, avec l'argumentaire de chaque sélection.
Aucun scraping de bookmaker : les cotes Unibet FR viennent de The Odds API.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # puis colle ta clé The Odds API
```

Python 3.10 ou plus récent.

## Utilisation

```bash
python main.py --demo              # tester sans clé ni réseau (données fictives)
python main.py                     # analyse réelle
python main.py --show-rejected     # toutes les causes de rejet, pas seulement la 1re
python main.py -v                  # logs (dont crédits API restants)
```

Le rapport s'affiche dans le terminal et est enregistré dans `reports/`.

**Lance-le au moins deux fois par jour de match** (ex. 18 h puis 23 h, heure de Paris) :
le filtre « hausse anormale de cote » compare la cote actuelle à la première cote
mémorisée dans `data/odds_history.json`. Au premier passage, il ne peut pas encore
juger et le signale dans « À vérifier ».

## Architecture

| Fichier | Rôle |
|---|---|
| `main.py` | Point d'entrée, arguments, orchestration |
| `config.py` | Clés, seuils de tous les filtres, listes manuelles |
| `models.py` | Structures de données (match, équipe, résultat de filtre…) |
| `data_fetcher.py` | The Odds API (cotes) + API publique ESPN (calendrier, classement, blessures), cache disque, historique des cotes |
| `filters.py` | Les 9 filtres stricts |
| `analyzer.py` | Score, choix du combiné, rapport texte |
| `demo_data.py` | Jeu de données fictif couvrant chaque cas de rejet |

## Filtres (tous obligatoires)

| Filtre | Rejet si… | Réglage (`config.py`) |
|---|---|---|
| Cote | cote Unibet du favori hors 1.25–1.45 | `ODDS_MIN`, `ODDS_MAX` |
| Mouvement de cote | hausse ≥ 0.06 ou ≥ 4 % depuis la 1re observation, ou favori inversé | `LINE_RISE_MAX_*` |
| Back-to-back | 2e match en ~24 h **et** à l'extérieur | `B2B_MAX_GAP_HOURS` |
| Trap game | match vs contender dans les 48 h, adversaire du jour abordable | `TRAP_GAME_WINDOW_HOURS`, `CONTENDERS_*` |
| Road trip | 3e match consécutif (ou plus) à l'extérieur | `ROAD_TRIP_MAX_CONSECUTIVE` |
| Forme dom./ext. | moins de 3 victoires sur les 5 derniers au même lieu | `VENUE_FORM_*` |
| Dynamique croisée | outsider ≥ 7/10 et favori ≤ 5/10, ou outsider en meilleure forme, ou outsider sur 4+ victoires et favori 2 défaites sur 3 | `DOG_HOT_*`, `FAV_DOUBT_MAX_WINS` |
| Infirmerie | franchise player absent/incertain, ou 2+ titulaires majeurs | `KEY_PLAYERS`, `BLOCKING_STATUSES` |
| Anti-tanking | mars/avril avec une équipe parmi les 8 pires bilans | `TANKING_*` |

Toute donnée manquante ou insuffisante entraîne un **rejet**, jamais une validation.

## À savoir

- **Début de saison (1er octobre → 30 novembre)** : le script bascule automatiquement sur
  `EARLY_SEASON` : dynamique croisée dès 5 matchs joués, forme dom./ext. sur 3 matchs
  (2 victoires requises). Ensuite, retour à `NORMAL_SEASON` (10 matchs, 3/5).
  Réglages : `EARLY_SEASON_MODE` (`"auto"`, `"on"`, `"off"`), `EARLY_SEASON_END`.
  Avec `INSUFFICIENT_DATA="warn"` dans `EARLY_SEASON`, une équipe sous ces minimums
  passe le filtre avec une alerte, sauf si le peu de matchs joués est déjà négatif.
- **Joueurs clés** : complète `KEY_PLAYERS` dans `config.py` (1er nom = franchise player).
  Équipe absente, liste vide ou mal formée : la règle de secours s'applique
  (3 absents/incertains = rejet) et le rapport l'indique. Les fautes de frappe dans les
  noms d'équipe sont signalées au démarrage.
- **Contenders** : top 6 du classement dès que les équipes ont 15 matchs, sinon la liste
  statique `CONTENDERS_FALLBACK` (8 cadors, à ajuster).
- **Quota The Odds API** : chaque exécution coûte 1 crédit (5 bookmakers, marché h2h),
  avec un cache de 15 min.
- L'API ESPN est publique mais non officielle : sa structure peut changer. Les parseurs
  sont tolérants et un match dont les données manquent est rejeté.

Outil d'aide à la décision, sans garantie de résultat. Joue une mise fixe et raisonnable.
Joueurs Info Service : 09 74 75 13 13.
