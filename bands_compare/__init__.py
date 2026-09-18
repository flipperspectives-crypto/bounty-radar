"""DLMM / Mr Bands comparator lane.

Independent of market_sentinel.py SOL/USD directional logic.
Research-only: never signs transactions, never deploys live positions.
Baseline weights are an explicit configurable model, not private coefficients.
"""

from .schemas import load_config, assert_research_only
from .comparator import check_dlmm_lane

__all__ = ["load_config", "assert_research_only", "check_dlmm_lane"]
