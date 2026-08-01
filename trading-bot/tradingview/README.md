# Donchian M5 Breakout — version TradingView (Pine Script)

Portage de la stratégie validée par le bot Python (`config/settings.yaml` → `donchian`)
pour que tu puisses la **backtester et la trader depuis ton TradingView local**.

> Params par défaut = **validés sur vraies données CME** (Databento, MNQ, 2 ans) :
> walk-forward 4/4, holdout reproductible +432 / PF 1.19. Edge **réel mais modeste**.

## Installation
1. TradingView → **Pine Editor** (en bas) → colle le contenu de `donchian_m5.pine`.
2. Chart en **5 minutes**, symbole **MNQ1!** (Micro Nasdaq — ce que tu trades sur
   Tradeify) ou **NQ1!** (même prix, ×10). ⚠️ **Jamais** le « US Tech 100 Cash ».
3. **Add to chart**. Onglet **Strategy Tester** = backtest natif. Un label orange
   apparaît si le chart n'est pas en 5 min.

## Réglages importants (Propriétés de la stratégie)
- **Commission** : `0.75` cash par contrat (déjà dans le script).
- **Slippage** : `1` tick (déjà dans le script) — mets `2-3` pour un test pessimiste.
- Pour MES : passe `USD par point` à **5** (MNQ = 2).

## Exécuter les trades
Pine ne peut **pas** auto-trader ton courtier tout seul. Trois options :
1. **Manuel** : tu suis les flèches/alertes et tu cliques sur ton compte Tradeify.
2. **Auto via pont** : crée une **Alerte** sur la condition `LONG entry` / `SHORT entry`,
   pointe le webhook vers **TradersPost** ou **PickMyTrade**, connecté à ton compte
   Tradeify (via identifiants Tradovate). Adapte le message JSON à la doc du pont.
3. **Paper trading** TradingView pour t'entraîner sans risque.

## À savoir
- Les chiffres du Strategy Tester **ne seront pas identiques** au backtest Python :
  TradingView remplit à l'ouverture de la barre suivante et modélise les fills
  autrement. L'ordre de grandeur (edge modeste, PF ~1.2-1.5) doit se retrouver.
- **Les règles de compte Tradeify** (trailing drawdown 2000, daily loss, consistency)
  ne sont pas dans le script — respecte-les manuellement ou via le pont.
- Edge **modeste et réel**, pas une machine à cash : discipline, pas de sur-trading.
