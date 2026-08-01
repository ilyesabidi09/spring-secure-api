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

## Données de marché réelles (Dukascopy, gratuit)
`data/download_dukascopy.py` télécharge des **ticks réels** S&P 500 (`USA500IDXUSD`) ou Nasdaq 100
(`USATECHIDXUSD`) et les agrège en barres OHLCV CSV (horodatées en US/Eastern, alignées RTH).
```bash
python -m data.download_dukascopy --instrument USA500IDXUSD \
    --start 2026-01-01 --end 2026-06-01 --interval 5min --out data/sp500_5m.csv
```
> ⚠️ C'est le **CFD indice** de Dukascopy (proxy du S&P), pas le contrat CME MES : prix quasi
> identiques (bon pour tester le *signal*), mais le volume n'est pas le volume CME. Les CSV ne sont
> pas commités (voir `.gitignore`) — régénère-les. Pour utiliser TES propres données MES, mets un
> CSV `time,open,high,low,close,volume` dans `data/`.

## Utilisation
```bash
# Tests
pytest -q

# Backtest de démonstration (données synthétiques — valide le pipeline, pas la rentabilité)
python run_backtest.py

# Backtest sur données réelles (CSV: time,open,high,low,close,volume)
python run_backtest.py --csv data/sp500_5m.csv

# Optimisation walk-forward → best_params.json
python run_backtest.py --walkforward

# Runner live (reste en mode=demo dans settings.yaml)
python -m live.runner

# Webhook TradingView
uvicorn webhook.server:app --port 8000
```

## ✅ Stratégie validée : Donchian breakout M5 (le résultat de la recherche)

Après avoir testé 8 stratégies + un sélecteur de régime + SMT sur 2 ans de vraies
données (frais inclus, walk-forward, holdout verrouillé, validation croisée), **une
seule survit à tous les tests** : le **Donchian channel breakout en M5** (momentum).

| Test | Donchian M5 |
|---|---|
| Walk-forward Nasdaq (4 folds OOS) | ✅ 4/4 positifs (+4335) |
| Holdout verrouillé (6 mois jamais vus) | ✅ positif, PF 1.26 |
| Validation croisée S&P | ✅ +1709 |
| **Pool MNQ+MES holdout (136 trades)** | ✅ **+3658 net, PF 1.25** |
| MDD mono-instrument | ✅ 400-600 (< limite 2000) |
| Filtre SMT (divergence NQ/ES) | ❌ testé, dégrade → rejeté |

Params validés (dans `config/settings.yaml`) : `channel_period 13, adx_min 20,
atr_stop_mult 2.36, rr_ratio 3.27`. Edge **modeste mais réel** (PF ~1.25), pas une
machine à cash. **Aucun abonnement GEX/orderflow requis** — l'edge a été trouvé sans.

### Forward-test (paper) — le juge avant le réel
`forward_test.py` rejoue un flux 1-min **exactement comme le live** (agrégateur M5 →
stratégie → RiskManager → fills bracket simulés, frais inclus) :
```bash
python forward_test.py --csv data/nasdaq_1m.csv            # tout l'historique
python forward_test.py --csv data/nasdaq_1m.csv --tail 40000  # fenêtre récente
```
> ⚠️ Prochaine étape obligatoire : **forward-test en compte DEMO Tradovate** (vrais
> fills, temps réel, plusieurs semaines) avant tout capital réel. C'est là que le
> slippage réel du breakout se mesure. `live/runner.py::feed_1m` utilise le même
> agrégateur — brancher le flux WS 1-min Tradovate dessus suffit.

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
