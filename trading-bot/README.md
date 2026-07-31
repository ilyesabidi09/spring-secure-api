# Bot de scalping MES/MNQ — Tradeify 50k Select

Framework de scalping futures (micro S&P / Nasdaq) pour un compte prop **Tradeify 50k Select**,
exécution via **Tradovate** (+ option alertes TradingView), avec **backtest** et **optimisation
walk-forward**.

> ⚠️ **À lire avant tout.** Aucun code ne rend un bot rentable — l'edge vient de la stratégie et
> des données, pas de l'outil. Ce projet fournit une base *propre et sûre* : signal, gestion du
> risque alignée sur les règles Tradeify, exécution conforme, et une boucle d'amélioration par
> optimisation offline. **Développe et valide en compte DEMO** avant tout passage en réel.

## Conformité Tradeify / CME (important)
- Bots autorisés par Tradeify **si tu es seul propriétaire**, **pas de HFT**, pas le même bot sur
  plusieurs firms. Vérifie leurs *terms* à jour avant de déployer.
- Chaque ordre porte **`isAutomated: true`** (CME Rule 575) — géré dans `execution/tradovate.py`.
- Le `RiskManager` applique des garde-fous durs : *trailing drawdown*, *daily loss limit*,
  *consistency rule*, taille max, fenêtre RTH. C'est ce qui évite la violation de compte.

## Installation
```bash
cd trading-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # renseigne tes identifiants Tradovate (DEMO d'abord)
```

## Structure
| Dossier | Rôle |
|---|---|
| `config/` | `settings.yaml` (symbole, risque, seuils Tradeify) + chargement `.env` |
| `strategy/` | signal : EMA/VWAP/RSI + filtre GEX + (option) orderflow |
| `risk/` | `RiskManager` — garde-fous prop-firm |
| `execution/` | client Tradovate (auth REST, ordres bracket `isAutomated`) |
| `backtest/` | moteur barre-par-barre + métriques (PF, winrate, MDD, expectancy) |
| `optimize/` | walk-forward Optuna → `best_params.json` |
| `live/` | orchestrateur temps réel (data → strategy → risk → execution) |
| `webhook/` | serveur FastAPI pour alertes TradingView |
| `tests/` | tests déterministes (risk + strategy) |

## Utilisation
```bash
# Tests
pytest -q

# Backtest de démonstration (données synthétiques — valide le pipeline, pas la rentabilité)
python run_backtest.py

# Backtest sur données réelles (CSV: time,open,high,low,close,volume)
python run_backtest.py --csv mes_1min.csv

# Optimisation walk-forward → best_params.json
python run_backtest.py --walkforward

# Runner live (reste en mode=demo dans settings.yaml)
python -m live.runner

# Webhook TradingView
uvicorn webhook.server:app --port 8000
```

## La boucle « qui s'améliore »
`optimize/walkforward.py` optimise les paramètres sur une fenêtre *in-sample*, les valide
*out-of-sample*, et n'enregistre que ce qui tient hors échantillon dans `best_params.json`
(rechargé par le live). Rejoue-la périodiquement (ex. cron hebdomadaire) sur des données récentes.
C'est une amélioration **offline et reproductible** — pas d'apprentissage en direct sur le compte
(source d'overfitting et de risque).

## Prochaines étapes
1. Brancher un vrai flux de barres Tradovate WebSocket sur `LiveRunner.on_bar`.
2. Fournir des données MES/MNQ réelles pour des backtests significatifs.
3. Alimenter `data/gex_levels.json` chaque matin depuis ton abonnement GEX.
4. Activer/brancher le module orderflow (DOM/footprint) quand le flux est disponible.
5. Valider en démo sur plusieurs semaines **avant** d'envisager `mode: live`.

## Avertissement
Le trading de futures comporte un risque de perte substantielle. Ce logiciel est fourni à titre
éducatif/technique, sans garantie de résultat. Tu es seul responsable du respect des règles de
Tradeify, de Tradovate et du CME.
