"""Pool MNQ (Nasdaq) + MES (S&P) en M5, Donchian breakout, holdout verrouille.
Compare sans filtre SMT vs avec filtre SMT (divergence des instruments correles)."""
from config import load_config
from data.loader import load_csv
from optimize.portfolio_holdout import pooled_holdout

cfg = load_config()
streams = {
    "MNQ": {"bars": load_csv("data/nasdaq_5m.csv"), "tick_size": 0.25, "tick_value": 0.50},
    "MES": {"bars": load_csv("data/sp500_5m.csv"), "tick_size": 0.25, "tick_value": 1.25},
}
print("Trades dispo:", {i: len(s["bars"]) for i, s in streams.items()})

for use_smt in (False, True):
    tag = "AVEC SMT" if use_smt else "SANS SMT"
    out = pooled_holdout(streams, cfg, strat_name="donchian", split=0.75,
                         n_trials=40, use_smt=use_smt,
                         out_path=f"pooled_{'smt' if use_smt else 'nosmt'}.json")
    i, h = out["in_sample"], out["holdout"]
    print(f"\n=== POOL MNQ+MES M5 Donchian — {tag} ===")
    print(f"  IN-SAMPLE : net={i['net_pnl']:>9} PF={i['profit_factor']:>5} "
          f"trades={i['trades']:>4} MDD={i['max_drawdown']}")
    print(f"  HOLDOUT   : net={h['net_pnl']:>9} PF={h['profit_factor']:>5} "
          f"trades={h['trades']:>4} MDD={h['max_drawdown']}")
print("\nPOOL_DONE")
