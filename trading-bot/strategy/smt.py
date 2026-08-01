"""Filtre SMT (Smart Money Technique) — divergence entre instruments correles.

Concept ICT : NQ et ES bougent ensemble. Quand l'un fait un nouveau plus-haut et
l'autre PAS (il fait un plus-haut inferieur), c'est une divergence = manque de
participation = signal de faiblesse. Ici on l'utilise en CONFIRMATION d'une cassure :
- LONG accepte seulement si l'instrument correle ne diverge pas a la baisse
  (il fait aussi un plus-haut, pas un plus-haut inferieur).
- SHORT accepte seulement si le correle ne diverge pas a la hausse.
"""
from __future__ import annotations

from collections import deque

from strategy.base import Action


class SMTFilter:
    def __init__(self, lookback: int = 20):
        self.lb = lookback
        self.highs: dict[str, deque] = {}
        self.lows: dict[str, deque] = {}

    def update(self, instr: str, bar) -> None:
        self.highs.setdefault(instr, deque(maxlen=self.lb + 1)).append(bar.high)
        self.lows.setdefault(instr, deque(maxlen=self.lb + 1)).append(bar.low)

    def _higher_high(self, instr: str) -> bool | None:
        h = self.highs.get(instr)
        if not h or len(h) < self.lb + 1:
            return None
        return h[-1] >= max(list(h)[:-1])

    def _lower_low(self, instr: str) -> bool | None:
        l = self.lows.get(instr)
        if not l or len(l) < self.lb + 1:
            return None
        return l[-1] <= min(list(l)[:-1])

    def allows(self, instr: str, action: Action, others: list[str]) -> bool:
        """Veto si un instrument correle diverge contre le sens du trade."""
        for o in others:
            if action == Action.LONG:
                self_hh = self._higher_high(instr)
                other_hh = self._higher_high(o)
                if self_hh and other_hh is False:   # ce n'est pas confirme -> divergence
                    return False
            else:  # SHORT
                self_ll = self._lower_low(instr)
                other_ll = self._lower_low(o)
                if self_ll and other_ll is False:
                    return False
        return True
