"""Derive an apples-to-apples DLMM pool feature vector from a snapshot."""

from __future__ import annotations

from typing import Any, Mapping

from .schemas import FEATURE_NAMES, PoolFeatures, PoolSnapshot


EPS = 1e-12


def required_feature_names():
    return FEATURE_NAMES


def safe_div(num: float, den: float) -> float:
    if abs(den) <= EPS:
        return 0.0
    return float(num) / float(den)


def _cfg_get(cfg: Mapping[str, Any], *keys, default=None):
    cur: Any = cfg
    for key in keys:
        if not isinstance(cur, Mapping) or key not in cur:
            return default
        cur = cur[key]
    return cur


def derive_features(snapshot: PoolSnapshot, cfg: Mapping[str, Any]) -> PoolFeatures:
    tvl = max(float(snapshot.tvl), 0.0)
    volume_24h = max(float(snapshot.volume_24h), 0.0)
    fee_rate = max(float(snapshot.fee_rate), 0.0)
    fees_24h = snapshot.fees_24h
    if fees_24h is None:
        fees_24h = volume_24h * fee_rate
    fees_24h = max(float(fees_24h), 0.0)

    fee_tvl = safe_div(fees_24h, tvl)
    volume_tvl = safe_div(volume_24h, tvl)

    if snapshot.active_tvl is not None and float(snapshot.active_tvl) > EPS:
        active_tvl = max(float(snapshot.active_tvl), 0.0)
    else:
        fallback_depth = float(_cfg_get(cfg, "features", "depth_fallback_frac", default=0.10) or 0.10)
        if snapshot.liquidity_depth_near_price is not None:
            active_tvl = max(float(snapshot.liquidity_depth_near_price), 0.0)
        else:
            active_tvl = tvl * fallback_depth
    fee_active_tvl = safe_div(fees_24h, active_tvl)

    lp_share = snapshot.lp_fee_share
    if lp_share is None:
        lp_share = float(_cfg_get(cfg, "features", "lp_fee_share", default=0.90) or 0.90)
    lp_share = max(0.0, min(1.0, float(lp_share)))

    current_bin = int(snapshot.current_active_bin)
    prev_bin = snapshot.prev_active_bin if snapshot.prev_active_bin is not None else current_bin
    bin_move = abs(float(current_bin) - float(prev_bin))

    bin_step = snapshot.bin_step
    if bin_step is None:
        bin_step = float(_cfg_get(cfg, "features", "default_bin_step", default=10.0) or 10.0)
    bin_step = float(bin_step)

    price = float(snapshot.price)
    lower = snapshot.band_lower_price
    upper = snapshot.band_upper_price
    if lower is None or upper is None:
        lower_bin = snapshot.band_lower_bin
        upper_bin = snapshot.band_upper_bin
        if lower_bin is not None and upper_bin is not None and price > 0:
            bins_in_band = max(int(upper_bin) - int(lower_bin), 0)
            width_frac = (1.0 + bin_step / 10000.0) ** bins_in_band - 1.0
            half = width_frac / 2.0
            lower = price / (1.0 + half) if half > -0.999 else price * 0.5
            upper = price * (1.0 + half)
        else:
            lower = price * 0.97
            upper = price * 1.03
    lower = float(lower)
    upper = float(upper)
    if upper < lower:
        lower, upper = upper, lower

    mid = (lower + upper) / 2.0 if (lower + upper) else price
    band_width = safe_div(upper - lower, price if price > EPS else mid)
    width_abs = max(upper - lower, EPS)

    in_range = lower <= price <= upper
    if in_range:
        dist_edge = min(price - lower, upper - price) / width_abs
        oor_hours = 0.0
    else:
        dist_edge = 0.0
        oor_hours = float(snapshot.out_of_range_hours or 0.0)

    lookback = float(_cfg_get(cfg, "features", "lookback_hours", default=24.0) or 24.0)
    if snapshot.time_in_range_frac is not None:
        time_in_range = max(0.0, min(1.0, float(snapshot.time_in_range_frac)))
    elif in_range:
        time_in_range = 1.0
    else:
        time_in_range = max(0.0, min(1.0, 1.0 - oor_hours / max(lookback, EPS)))

    rv = max(float(snapshot.realized_volatility or 0.0), 0.0)
    coverage = band_width  # percent of spot covered by the estimated band

    depth_fallback = float(_cfg_get(cfg, "features", "depth_fallback_frac", default=0.10) or 0.10)
    if snapshot.liquidity_depth_near_price is None:
        depth = tvl * depth_fallback
    else:
        depth = max(float(snapshot.liquidity_depth_near_price), 0.0)
    depth_frac = safe_div(depth, tvl)

    vol_avg = snapshot.volume_avg_7d
    if vol_avg is None or vol_avg <= EPS:
        persistence = 1.0 if volume_24h <= EPS else 0.5
    else:
        persistence = 1.0 - min(1.0, abs(volume_24h - float(vol_avg)) / max(float(vol_avg), EPS))

    if snapshot.inventory_exposure is None:
        inventory = (upper - price) / width_abs
        inventory = max(0.0, min(1.0, inventory))
    else:
        inventory = max(0.0, min(1.0, float(snapshot.inventory_exposure)))

    use_active = bool(_cfg_get(cfg, "features", "use_active_tvl", default=True))
    print_per_dollar = fee_active_tvl if use_active else fee_tvl
    expected_fees = fees_24h * time_in_range * lp_share
    expected_fees_per_dollar = print_per_dollar * time_in_range * lp_share
    wash = tuple(wash_reasons(volume_tvl=volume_tvl, tvl=tvl, fee_rate=fee_rate, cfg=cfg))

    rent = float(_cfg_get(cfg, "costs", "rent_usd_per_position_day", default=0.0) or 0.0)
    rebalance = float(_cfg_get(cfg, "costs", "rebalance_usd", default=0.0) or 0.0)
    tx_cost = rent + rebalance

    stale = False
    if snapshot.observed_at_unix is not None and snapshot.now_unix is not None:
        age = float(snapshot.now_unix) - float(snapshot.observed_at_unix)
        max_age = float(_cfg_get(cfg, "penalties", "stale_pool_information", "max_age_seconds", default=3600) or 3600)
        stale = age > max_age

    return PoolFeatures(
        volume_24h=volume_24h,
        tvl=tvl,
        fee_rate=fee_rate,
        fee_tvl=fee_tvl,
        volume_tvl=volume_tvl,
        current_active_bin=current_bin,
        recent_active_bin_movement=bin_move,
        recent_price_change=float(snapshot.recent_price_change or 0.0),
        realized_volatility=rv,
        liquidity_depth_around_price=depth,
        estimated_band_width=band_width,
        estimated_percent_price_coverage=coverage,
        estimated_time_in_range=time_in_range,
        expected_fees=expected_fees,
        transaction_rent_rebalance_cost=tx_cost,
        inventory_exposure=inventory,
        distance_from_band_edge=dist_edge,
        out_of_range_duration=oor_hours,
        current_open_exposure=float(snapshot.current_open_exposure or 0.0),
        in_range=in_range,
        stale=stale,
        volume_persistence=persistence,
        expected_fees_per_dollar=expected_fees_per_dollar,
        depth_frac=depth_frac,
        estimated_slippage=float(snapshot.estimated_slippage or 0.0),
        active_tvl=active_tvl,
        fee_active_tvl=fee_active_tvl,
        wash_reasons=wash,
        lp_fee_share=lp_share,
        pool=snapshot.pool,
        timestamp=snapshot.timestamp,
    )


def wash_reasons(*, volume_tvl: float, tvl: float, fee_rate: float, cfg: Mapping[str, Any]) -> list:
    """Public wash heuristics. Large-TVL stables are not flagged for low fee rate alone."""
    rules = cfg.get("wash_volume") if isinstance(cfg, Mapping) else None
    if not isinstance(rules, Mapping):
        rules = {}
    reasons = []
    max_vt = float(rules.get("max_volume_tvl", 10.0))
    min_tvl = float(rules.get("min_tvl_usd", 100000.0))
    min_tvl_vt = float(rules.get("min_tvl_volume_tvl", 5.0))
    max_fee = float(rules.get("max_fee_rate", 0.02))
    if volume_tvl > max_vt:
        reasons.append("volume_tvl")
    if tvl < min_tvl and volume_tvl > min_tvl_vt:
        reasons.append("tiny_tvl_outsized_volume")
    if tvl < min_tvl and fee_rate > max_fee:
        reasons.append("fee_rate_high")
    return reasons
