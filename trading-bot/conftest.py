"""Ajoute le dossier trading-bot au sys.path pour que les imports absolus
(risk, strategy, backtest, ...) fonctionnent sous pytest depuis la racine."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
