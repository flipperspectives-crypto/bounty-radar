"""Opportunity score: is this pool economically attractive for LP deployment?

Separate from action policy and hard guards.
Weights come from the single config file and are NOT claimed to be
Mr Bands private coefficients.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping

from .schemas import PoolFeatures, ScoreBreakdown, clip01, mapping_to_dict, unit_interval


BASELINE_WEIGHTS = {
    "fee_tvl_quality": 0.35,
    "volume_tvl_persistence": 0.20,
    "liquidity_depth_quality": 0.15,
    "in_range_stability": 0.15,
    "cost_adjusted_expected_return": 0.15,
}

NOTE = (
    "Baseline weights are an independent configurable model, "
    "not Mr Bands private coefficients."
)


def _n(cfg: Mapping[str, Any], key: str, default: float) -> float:
    norm = cfg.get("normalization") if isinstance(cfg, Mapping) else None
    if isinstance(norm, Mapping) and key in norm:
        return float(norm[key])
    return default


def _penalty_cfg(cfg: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    penalties = cfg.get("penalties") if isinstance(cfg, Mapping) else None
    if isinstance(penalties, Mapping):
        block = penalties.get(name)
        if isinstance(block, Mapping):
            return block
    return {}


def score_opportunity(features: PoolFeatures, cfg: Mapping[str, Any]) -> ScoreBreakdown:
    cfg = mapping_to_dict(cfg)
    weights_raw = cfg.get("opportunity_weights") or BASELINE_WEIGHTS
    weights = {k: float(weights_raw[k]) for k in BASELINE_WEIGHTS}

    fee_full = _n(cfg, "fee_tvl_full_score", 0.10)
    vol_full = _n(cfg, "volume_tvl_full_score", 8.0)
    depth_full = _n(cfg, "depth_frac_full_score", 0.30)
    bin_pen = _n(cfg, "bin_move_full_penalty", 25.0)
    cov_full = _n(cfg, "coverage_full_score", 1.0)
    net_lo = _n(cfg, "net_return_lo", -0.02)
    net_hi = _n(cfg, "net_return_hi", 0.12)
    persist_mix = _n(cfg, "persistence_mix", 0.40)

    fee_q = unit_interval(features.fee_tvl, 0.0, fee_full)
    vol_q = (1.0 - persist_mix) * unit_interval(features.volume_tvl, 0.0, vol_full) + persist_mix * clip01(
        features.volume_persistence
    )
    depth_q = unit_interval(features.depth_frac, 0.0, depth_full)
    bin_stability = 1.0 - unit_interval(features.recent_active_bin_movement, 0.0, bin_pen)
    coverage_q = unit_interval(features.estimated_percent_price_coverage / max(features.realized_volatility, 1e-6), 0.0, cov_full)
    # Prefer explicit band vs vol coverage; fall back to time-in-range heavy mix.
    coverage_term = clip01(
        features.estimated_band_width / max(features.realized_volatility, 1e-6) / max(cov_full, 1e-6)
        if features.realized_volatility > 1e-6
        else features.estimated_time_in_range
    )
    stability = clip01(
        0.50 * features.estimated_time_in_range + 0.30 * bin_stability + 0.20 * coverage_term
    )

    assumed = float(cfg.get("action_policy", {}).get("assumed_position_usd", 150.0) or 150.0)
    cost = float(features.transaction_rent_rebalance_cost or 0.0)
    net_per_dollar = features.expected_fees_per_dollar - (cost / max(assumed, 1e-9))
    cost_adj = unit_interval(net_per_dollar, net_lo, net_hi)

    components = {
        "fee_tvl_quality": fee_q,
        "volume_tvl_persistence": clip01(vol_q),
        "liquidity_depth_quality": depth_q,
        "in_range_stability": stability,
        "cost_adjusted_expected_return": cost_adj,
    }
    weighted = {k: components[k] * weights[k] for k in weights}
    raw = sum(weighted.values())

    penalties: Dict[str, float] = {}

    vol_p = _penalty_cfg(cfg, "extreme_volatility")
    vol_thr = float(vol_p.get("threshold", 0.08))
    if features.realized_volatility > vol_thr:
        penalties["extreme_volatility"] = float(vol_p.get("weight", 0.22)) * min(
            1.0, (features.realized_volatility - vol_thr) / max(vol_thr, 1e-9)
        )

    depth_p = _penalty_cfg(cfg, "poor_depth")
    depth_thr = float(depth_p.get("threshold", 0.06))
    if features.depth_frac < depth_thr:
        penalties["poor_depth"] = float(depth_p.get("weight", 0.18)) * min(
            1.0, (depth_thr - features.depth_frac) / max(depth_thr, 1e-9)
        )

    inv_p = _penalty_cfg(cfg, "excessive_inventory_risk")
    inv_thr = float(inv_p.get("threshold", 0.045))
    inv_risk = features.inventory_exposure * features.realized_volatility
    if inv_risk > inv_thr:
        penalties["excessive_inventory_risk"] = float(inv_p.get("weight", 0.16)) * min(
            1.0, (inv_risk - inv_thr) / max(inv_thr, 1e-9)
        )

    fee_p = _penalty_cfg(cfg, "fee_below_cost")
    expected_fee_usd = features.expected_fees_per_dollar * assumed
    if expected_fee_usd < cost:
        gap = (cost - expected_fee_usd) / max(cost, 1e-9)
        penalties["fee_below_cost"] = float(fee_p.get("weight", 0.28)) * clip01(gap)

    move_p = _penalty_cfg(cfg, "abnormal_single_cycle_move")
    move_thr = float(move_p.get("threshold", 0.18))
    abs_move = abs(features.recent_price_change)
    if abs_move > move_thr:
        penalties["abnormal_single_cycle_move"] = float(move_p.get("weight", 0.20)) * min(
            1.0, (abs_move - move_thr) / max(move_thr, 1e-9)
        )

    stale_p = _penalty_cfg(cfg, "stale_pool_information")
    if features.stale:
        penalties["stale_pool_information"] = float(stale_p.get("weight", 0.15))

    penalized = raw - sum(penalties.values())
    score = clip01(penalized)

    features_used = list(components.keys()) + [f"penalty:{k}" for k in penalties]
    return ScoreBreakdown(
        score=score,
        components=components,
        weighted=weighted,
        penalties=penalties,
        features_used=features_used,
        weights=weights,
        note=NOTE,
    )
