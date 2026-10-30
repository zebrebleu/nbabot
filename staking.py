"""Mise conseillée selon la confiance (commun NBA et tennis)."""
from __future__ import annotations

import config

ORDER = ["Prudente", "Moyenne", "Élevée"]


def lowest(confidences: list[str]) -> str:
    """Confiance la plus basse d'un combiné."""
    known = [c for c in confidences if c in ORDER]
    return min(known, key=ORDER.index) if known else "Prudente"


def stake_for(confidence: str) -> int:
    return round(config.BASE_STAKE * config.STAKE_SHARE.get(confidence, min(config.STAKE_SHARE.values())))


def bet_stake(confidences: list[str]) -> tuple[int, str]:
    """(mise conseillée en €, confiance retenue) pour un pari simple ou combiné."""
    conf = lowest(confidences)
    return stake_for(conf), conf


def stake_scale_text() -> str:
    return " · ".join(f"{c.lower()} {stake_for(c)} €" for c in reversed(ORDER))
