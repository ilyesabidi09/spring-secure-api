"""Stress-test de sensibilite au slippage : holdout Donchian M5 Nasdaq a plusieurs
niveaux de slippage. Un edge de breakout doit survivre a un slippage realiste/pessimiste."""
import json

from config import load_config
from data.loader import load_csv
from optimize.holdout import run_holdout
from strategy.gex import load_gex_levels

cfg = load_config()
gex = load_gex_levels(cfg["gex"]["levels_file"]) if cfg["gex"]["enabled"] else {}
bars = load_csv("data/nasdaq_5m.csv")

print("slippage_pts | holdout_net | holdout_PF | trades | MDD")
for slip in [0.25, 0.5, 0.75, 1.0]:
    cfg["costs"]["slippage_points"] = slip
    out = run_holdout(bars, cfg, gex, "MNQ", "donchian", split=0.75,
                      n_trials=40, out_path=f"ho_slip_{slip}.json")
    h = out["holdout"]
    net = h["net_pnl"]
    pf = h["profit_factor"]
    tr = h["trades"]
    mdd = h["max_drawdown"]
    print(f"   {slip:<9} | {net:>10} | {pf:>9} | {tr:>5} | {mdd}")
print("SLIP_DONE")
