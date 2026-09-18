"""Typed contracts and the single frozen config loader for the DLMM lane."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field, fields
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Tuple


ACTIONS = ("HOLD", "OPEN", "MOVE", "CLAIM", "CLOSE")

FEATURE_NAMES = (
    "volume_24h",
    "tvl",
    "fee_rate",
    "fee_tvl",
    "volume_tvl",
    "current_active_bin",
    "recent_active_bin_movement",
    "recent_price_change",
    "realized_volatility",
    "liquidity_depth_around_price",
    "estimated_band_width",
    "estimated_percent_price_coverage",
    "estimated_time_in_range",
    "expected_fees",
    "transaction_rent_rebalance_cost",
    "inventory_exposure",
    "distance_from_band_edge",
    "out_of_range_duration",
    "current_open_exposure",
)

JOURNAL_FIELDS = (
    "timestamp",
    "pool",
    "our_opportunity_score",
    "our_rank",
    "features_used",
    "recommended_action",
    "guard_result",
    "actual_action",
    "reason",
    "mr_bands_score",
    "mr_bands_rank",
    "mr_bands_action",
)

DISAGREEMENT_CAUSES = (
    "different_objective",
    "different_normalization",
    "different_feature",
    "different_weight",
    "different_action_threshold",
    "different_guard",
    "different_cost_assumption",
)

REQUIRED_WEIGHTS = (
    "fee_tvl_quality",
    "volume_tvl_persistence",
    "liquidity_depth_quality",
    "in_range_stability",
    "cost_adjusted_expected_return",
)

REQUIRED_GUARDS = (
    "max_allocation_per_position",
    "max_aggregate_exposure",
    "minimum_reserve",
    "max_band_width",
    "max_actions_per_day",
    "cooldown_seconds",
    "max_concurrent_pools",
    "max_allowed_slippage",
    "abnormal_price_move_veto",
    "stop_loss",
    "kill_switch",
    "wash_volume_veto",
)

CONFIG_FILENAME = "config.json"


def _package_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def default_config_path() -> str:
    return os.path.join(_package_dir(), CONFIG_FILENAME)


def freeze_mapping(value: Any) -> Any:
    """Deep-freeze dicts/lists so runtime (including LLM) mutation fails."""
    if isinstance(value, dict):
        return MappingProxyType({k: freeze_mapping(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(freeze_mapping(v) for v in value)
    return value


def mapping_to_dict(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: mapping_to_dict(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [mapping_to_dict(v) for v in value]
    return value


def config_hash(cfg: Mapping[str, Any]) -> str:
    payload = json.dumps(mapping_to_dict(cfg), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def assert_research_only() -> None:
    """Hard stop if anything tries to flip this lane into live trading."""
    flag = os.environ.get("BANDS_COMPARE_LIVE", "0").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        raise RuntimeError(
            "Live trading is forbidden. The DLMM comparator is research-only "
            "and will not sign transactions or deploy positions."
        )


def validate_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("config must be a JSON object")
    weights = raw.get("opportunity_weights")
    if not isinstance(weights, dict):
        raise ValueError("opportunity_weights missing")
    for key in REQUIRED_WEIGHTS:
        if key not in weights:
            raise ValueError(f"missing opportunity weight: {key}")
    total = sum(float(weights[k]) for k in REQUIRED_WEIGHTS)
    if abs(total - 1.0) > 1e-9:
        raise ValueError(f"opportunity_weights must sum to 1.0, got {total}")
    guards = raw.get("guards")
    if not isinstance(guards, dict):
        raise ValueError("guards missing")
    for key in REQUIRED_GUARDS:
        if key not in guards:
            raise ValueError(f"missing guard: {key}")
    for section in ("normalization", "penalties", "action_policy", "costs", "features"):
        if section not in raw or not isinstance(raw[section], dict):
            raise ValueError(f"missing config section: {section}")
    return raw


def load_config(path: Optional[str] = None) -> Mapping[str, Any]:
    """Load and freeze the single config file. Runtime mutation is rejected."""
    cfg_path = path or os.environ.get("BANDS_COMPARE_CONFIG") or default_config_path()
    with open(cfg_path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    validate_config(raw)
    frozen = freeze_mapping(raw)
    return frozen


@dataclass
class PoolSnapshot:
    pool: str
    timestamp: str
    volume_24h: float
    tvl: float
    fee_rate: float
    price: float
    current_active_bin: int
    prev_active_bin: Optional[int] = None
    fees_24h: Optional[float] = None
    volume_avg_7d: Optional[float] = None
    realized_volatility: float = 0.0
    recent_price_change: float = 0.0
    liquidity_depth_near_price: Optional[float] = None
    band_lower_bin: Optional[int] = None
    band_upper_bin: Optional[int] = None
    band_lower_price: Optional[float] = None
    band_upper_price: Optional[float] = None
    bin_step: Optional[float] = None
    out_of_range_hours: float = 0.0
    time_in_range_frac: Optional[float] = None
    inventory_exposure: Optional[float] = None
    current_open_exposure: float = 0.0
    accumulated_fees: float = 0.0
    observed_at_unix: Optional[float] = None
    now_unix: Optional[float] = None
    estimated_slippage: float = 0.0
    next_fee_tvl: Optional[float] = None
    next_price_change: Optional[float] = None
    next_inventory_drawdown: Optional[float] = None
    active_tvl: Optional[float] = None
    lp_fee_share: Optional[float] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PoolSnapshot":
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in allowed})


@dataclass
class PoolFeatures:
    volume_24h: float
    tvl: float
    fee_rate: float
    fee_tvl: float
    volume_tvl: float
    current_active_bin: int
    recent_active_bin_movement: float
    recent_price_change: float
    realized_volatility: float
    liquidity_depth_around_price: float
    estimated_band_width: float
    estimated_percent_price_coverage: float
    estimated_time_in_range: float
    expected_fees: float
    transaction_rent_rebalance_cost: float
    inventory_exposure: float
    distance_from_band_edge: float
    out_of_range_duration: float
    current_open_exposure: float
    in_range: bool
    stale: bool
    volume_persistence: float
    expected_fees_per_dollar: float
    depth_frac: float
    estimated_slippage: float = 0.0
    active_tvl: float = 0.0
    fee_active_tvl: float = 0.0
    wash_reasons: tuple = ()
    lp_fee_share: float = 0.90
    pool: str = ""
    timestamp: str = ""

    def as_public_dict(self) -> Dict[str, Any]:
        return {name: getattr(self, name) for name in FEATURE_NAMES}


@dataclass
class ScoreBreakdown:
    score: float
    components: Dict[str, float]
    weighted: Dict[str, float]
    penalties: Dict[str, float]
    features_used: List[str]
    weights: Dict[str, float]
    note: str = (
        "Baseline weights are an independent configurable model, "
        "not Mr Bands private coefficients."
    )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ActionProposal:
    action: str
    reason: str
    expected_benefit_usd: float = 0.0
    estimated_cost_usd: float = 0.0
    source: str = "action_policy"

    def __post_init__(self) -> None:
        if self.action not in ACTIONS:
            raise ValueError(f"invalid action: {self.action}")


@dataclass
class GuardResult:
    passed: bool
    actual_action: str
    tripped: List[str] = field(default_factory=list)
    forced: bool = False
    reason: str = ""
    config_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PositionState:
    pool: str
    size_usd: float
    entry_price: float
    band_lower_price: float
    band_upper_price: float
    accumulated_fees: float = 0.0
    inventory_pnl: float = 0.0
    opened_at: str = ""


@dataclass
class AccountState:
    equity_usd: float
    cash_usd: float
    positions: Dict[str, PositionState] = field(default_factory=dict)
    actions_today: int = 0
    last_action_unix: float = 0.0
    day_stamp: str = ""
    realized_pnl: float = 0.0
    fees_collected: float = 0.0
    costs_paid: float = 0.0
    peak_equity: float = 0.0
    max_drawdown: float = 0.0

    def exposure_usd(self) -> float:
        return sum(p.size_usd for p in self.positions.values())


@dataclass
class JournalRow:
    timestamp: str
    pool: str
    our_opportunity_score: float
    our_rank: int
    features_used: List[str]
    recommended_action: str
    guard_result: Dict[str, Any]
    actual_action: str
    reason: str
    mr_bands_score: Optional[float] = None
    mr_bands_rank: Optional[int] = None
    mr_bands_action: Optional[str] = None
    disagreement_causes: List[str] = field(default_factory=list)
    subsequent_fee_tvl: Optional[float] = None
    subsequent_inventory_drawdown: Optional[float] = None
    net_return_after_costs: Optional[float] = None
    features: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MrBandsObservation:
    pool: str
    timestamp: str
    mr_bands_score: Optional[float] = None
    mr_bands_rank: Optional[int] = None
    mr_bands_action: Optional[str] = None
    source: str = "manual_or_public"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MrBandsObservation":
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in allowed})


def clip01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return float(value)


def unit_interval(value: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    return clip01((float(value) - lo) / (hi - lo))
