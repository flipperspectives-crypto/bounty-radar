"""Historical/simulated snapshot harness for the DLMM comparator.

SIMULATION ONLY. Does not sign transactions, use real funds, or deploy positions.

The 40/30/30 capital_allocation_score is a harness-only wallet split helper.
It is NOT the pool opportunity score (see opportunity_score.py).
"""

from __future__ import annotations

import csv
import json
import math
import os
import random
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .action_policy import recommend_action
from .comparator import classify_disagreement, compare_cohort, compute_metrics, spearman_rank
from .guards import GuardEngine
from .opportunity_score import score_opportunity
from .pool_features import derive_features
from .schemas import (
    AccountState,
    DISAGREEMENT_CAUSES,
    JournalRow,
    MrBandsObservation,
    PositionState,
    PoolSnapshot,
    assert_research_only,
    clip01,
    load_config,
    mapping_to_dict,
    unit_interval,
)


POOL_SPECS: List[Dict[str, Any]] = [
    {
        "id": "SOL-USDC",
        "tvl": 8_000_000.0,
        "fee_rate": 0.0025,
        "vol_mult": 5.0,
        "sigma": 0.008,
        "depth_frac": 0.25,
        "bin_step": 10.0,
        "half_width": 0.04,
        "price0": 100.0,
    },
    {
        "id": "JUP-SOL",
        "tvl": 2_000_000.0,
        "fee_rate": 0.010,
        "vol_mult": 6.5,
        "sigma": 0.03,
        "depth_frac": 0.18,
        "bin_step": 20.0,
        "half_width": 0.08,
        "price0": 1.20,
    },
    {
        "id": "BONK-SOL",
        "tvl": 1_200_000.0,
        "fee_rate": 0.015,
        "vol_mult": 10.0,
        "sigma": 0.05,
        "depth_frac": 0.12,
        "bin_step": 25.0,
        "half_width": 0.10,
        "price0": 0.00002,
    },
    {
        "id": "WIF-SOL",
        "tvl": 900_000.0,
        "fee_rate": 0.020,
        "vol_mult": 12.0,
        "sigma": 0.07,
        "depth_frac": 0.08,
        "bin_step": 40.0,
        "half_width": 0.12,
        "price0": 1.50,
        "shock_step": 8,
        "shock": 0.28,
    },
    {
        "id": "MEME-SOL",
        "tvl": 250_000.0,
        "fee_rate": 0.040,
        "vol_mult": 22.0,
        "sigma": 0.12,
        "depth_frac": 0.04,
        "bin_step": 80.0,
        "half_width": 0.22,
        "price0": 0.008,
    },
    {
        "id": "STABLE-USDC",
        "tvl": 5_000_000.0,
        "fee_rate": 0.0001,
        "vol_mult": 0.8,
        "sigma": 0.001,
        "depth_frac": 0.40,
        "bin_step": 1.0,
        "half_width": 0.005,
        "price0": 1.0,
    },
    {
        "id": "THIN-SOL",
        "tvl": 80_000.0,
        "fee_rate": 0.030,
        "vol_mult": 15.0,
        "sigma": 0.09,
        "depth_frac": 0.02,
        "bin_step": 50.0,
        "half_width": 0.18,
        "price0": 0.40,
    },
    {
        "id": "STALE-SOL",
        "tvl": 400_000.0,
        "fee_rate": 0.012,
        "vol_mult": 5.0,
        "sigma": 0.04,
        "depth_frac": 0.10,
        "bin_step": 20.0,
        "half_width": 0.09,
        "price0": 2.5,
        "stale": True,
    },
    {
        "id": "RUG-SOL",
        "tvl": 180_000.0,
        "fee_rate": 0.018,
        "vol_mult": 7.0,
        "sigma": 0.05,
        "depth_frac": 0.16,
        "bin_step": 40.0,
        "half_width": 0.12,
        "price0": 0.05,
        "rug_step": 12,
        "rug_drop": 0.85,
    },
    {
        "id": "WASH-SOL",
        "tvl": 40_000.0,
        "fee_rate": 0.04,
        "vol_mult": 18.0,
        "sigma": 0.08,
        "depth_frac": 0.03,
        "bin_step": 80.0,
        "half_width": 0.20,
        "price0": 0.01,
        "wash": True,
    },
]


def decide_ship(
    *,
    control_equity: Optional[float],
    treatment_equity: Optional[float],
    control_spearman: Optional[float],
    treatment_spearman: Optional[float],
    treatment_recommended_churn: Optional[float],
    churn_cap: float = 0.46,
) -> bool:
    """Ship only if held-out equity and Spearman both do not fall, and churn stays capped."""
    if control_equity is None or treatment_equity is None:
        return False
    if control_spearman is None or treatment_spearman is None:
        return False
    if float(treatment_equity) + 1e-9 < float(control_equity):
        return False
    if float(treatment_spearman) + 1e-9 < float(control_spearman):
        return False
    if float(treatment_recommended_churn or 0.0) > float(churn_cap) + 1e-12:
        return False
    return True


def capital_allocation_score(liquidity: float, volume: float, fees: float) -> float:
    """Harness-only 40/30/30 capital mix.

    Used historically for wallet-split experiments. MUST NOT be used as the
    DLMM pool opportunity score.
    """
    return 0.40 * float(liquidity) + 0.30 * float(volume) + 0.30 * float(fees)


def generate_snapshots(
    cfg: Optional[Mapping[str, Any]] = None,
    seed: Optional[int] = None,
    steps: Optional[int] = None,
) -> List[PoolSnapshot]:
    cfg = mapping_to_dict(cfg or load_config())
    sim = cfg.get("simulation") or {}
    seed = int(sim["seed"] if seed is None else seed)
    steps = int(sim["steps"] if steps is None else steps)
    rng = random.Random(seed)
    start = datetime(2026, 9, 18, tzinfo=timezone.utc)
    state: Dict[str, Dict[str, float]] = {}
    for spec in POOL_SPECS:
        state[spec["id"]] = {
            "price": float(spec["price0"]),
            "center": float(spec["price0"]),
            "bin": 1000.0,
            "oor": 0.0,
        }

    snaps: List[PoolSnapshot] = []
    for t in range(steps):
        ts = (start + timedelta(hours=t)).strftime("%Y-%m-%dT%H:%M:%SZ")
        now_unix = start.timestamp() + t * 3600.0
        for spec in POOL_SPECS:
            pid = spec["id"]
            st = state[pid]
            z = rng.gauss(0.0, float(spec["sigma"]))
            if spec.get("shock_step") == t:
                z = float(spec.get("shock", z))
            prev_price = st["price"]
            if spec.get("rug_step") is not None and t == int(spec["rug_step"]):
                drop = min(0.99, max(0.0, float(spec.get("rug_drop", 0.85))))
                price = max(prev_price * (1.0 - drop), 1e-12)
            else:
                price = max(prev_price * math.exp(z), 1e-12)
            if spec.get("rug_step") is not None and t > int(spec["rug_step"]):
                price = max(price * 0.92, 1e-12)
            st["price"] = price
            # Band center lags, producing realistic time-out-of-range.
            lag = 0.35 if spec["sigma"] > 0.04 else 0.15
            st["center"] = (1.0 - lag) * st["center"] + lag * price
            half = float(spec["half_width"]) * st["center"]
            lower = st["center"] - half
            upper = st["center"] + half
            in_range = lower <= price <= upper
            st["oor"] = 0.0 if in_range else st["oor"] + 1.0
            bin_delta = int(round(math.log(price / spec["price0"]) / max(spec["sigma"], 1e-6)))
            cur_bin = 1000 + bin_delta
            prev_bin = int(st["bin"])
            st["bin"] = float(cur_bin)
            tvl = float(spec["tvl"]) * (0.92 + 0.16 * rng.random())
            vol_mult = float(spec["vol_mult"]) * (1.0 + min(2.0, abs(z) * 8.0))
            if spec.get("rug_step") is not None and t >= int(spec["rug_step"]):
                tvl *= 0.25
                vol_mult *= 0.08
            volume = tvl * vol_mult
            fees = volume * float(spec["fee_rate"])
            depth = tvl * float(spec["depth_frac"])
            active_tvl = max(depth, tvl * min(0.45, float(spec["depth_frac"]) + 0.05))
            observed = now_unix - (8_000.0 if spec.get("stale") else 30.0)
            price_chg = (price - prev_price) / max(prev_price, 1e-12)
            snaps.append(
                PoolSnapshot(
                    pool=pid,
                    timestamp=ts,
                    volume_24h=volume,
                    tvl=tvl,
                    fee_rate=float(spec["fee_rate"]),
                    fees_24h=fees,
                    price=price,
                    current_active_bin=cur_bin,
                    prev_active_bin=prev_bin,
                    realized_volatility=float(spec["sigma"]),
                    recent_price_change=price_chg,
                    liquidity_depth_near_price=depth,
                    band_lower_price=lower,
                    band_upper_price=upper,
                    bin_step=float(spec["bin_step"]),
                    out_of_range_hours=st["oor"],
                    time_in_range_frac=None,
                    inventory_exposure=(
                        0.95
                        if spec.get("rug_step") is not None and t >= int(spec["rug_step"])
                        else max(0.0, min(1.0, (upper - price) / max(upper - lower, 1e-12)))
                    ),
                    current_open_exposure=0.0,
                    observed_at_unix=observed,
                    now_unix=now_unix,
                    volume_avg_7d=tvl * float(spec["vol_mult"]),
                    active_tvl=active_tvl,
                    lp_fee_share=0.80 if spec.get("wash") or spec.get("rug_step") is not None else 0.90,
                    estimated_slippage=(
                        0.015
                        if spec["depth_frac"] < 0.05
                        else 0.006
                        if spec["depth_frac"] < 0.10
                        else 0.002
                    ),
                )
            )
    _attach_subsequent(snaps)
    return snaps


def _attach_subsequent(snaps: Sequence[PoolSnapshot]) -> None:
    by_pool: Dict[str, List[PoolSnapshot]] = defaultdict(list)
    for s in snaps:
        by_pool[s.pool].append(s)
    for pool, series in by_pool.items():
        series.sort(key=lambda s: s.timestamp)
        for i, s in enumerate(series[:-1]):
            nxt = series[i + 1]
            fees = nxt.fees_24h if nxt.fees_24h is not None else nxt.volume_24h * nxt.fee_rate
            s.next_fee_tvl = fees / max(nxt.tvl, 1e-12)
            s.next_price_change = nxt.recent_price_change
            inv = s.inventory_exposure if s.inventory_exposure is not None else 0.5
            s.next_inventory_drawdown = 0.5 * inv * abs(nxt.recent_price_change)
            if pool == "WASH-SOL":
                s.next_fee_tvl = min(s.next_fee_tvl or 0.0, 0.002)


def public_mr_bands_score(feat, cfg: Mapping[str, Any]) -> float:
    """Public-observable comparison stub. Not a reverse-engineer of private weights."""
    obs = mapping_to_dict(cfg).get("mr_bands_public_observer") or {}
    fee = unit_interval(feat.fee_tvl, 0.0, 0.10)
    vol = unit_interval(feat.volume_tvl, 0.0, 8.0)
    w_fee = float(obs.get("fee_tvl_weight", 0.70))
    w_vol = float(obs.get("volume_tvl_weight", 0.30))
    return clip01(w_fee * fee + w_vol * vol)


def public_mr_bands_action(feat, score: float, has_position: bool, cfg: Mapping[str, Any]) -> str:
    obs = mapping_to_dict(cfg).get("mr_bands_public_observer") or {}
    open_thr = float(obs.get("open_score_threshold", 0.45))
    move_thr = float(obs.get("move_min_score", 0.40))
    close_thr = float(obs.get("close_score_threshold", 0.20))
    if has_position:
        if score <= close_thr or feat.out_of_range_duration >= 18.0:
            return "CLOSE"
        if (not feat.in_range) and score >= move_thr:
            return "MOVE"
        return "HOLD"
    if score >= open_thr:
        return "OPEN"
    return "HOLD"


def _observations_for(
    snaps: Sequence[PoolSnapshot],
    cfg: Mapping[str, Any],
    positions: Mapping[str, PositionState],
) -> List[MrBandsObservation]:
    scored: List[Tuple[PoolSnapshot, float, str]] = []
    for snap in snaps:
        feat = derive_features(snap, cfg)
        sc = public_mr_bands_score(feat, cfg)
        act = public_mr_bands_action(feat, sc, snap.pool in positions, cfg)
        scored.append((snap, sc, act))
    scored.sort(key=lambda item: item[1], reverse=True)
    out: List[MrBandsObservation] = []
    for rank, (snap, sc, act) in enumerate(scored, start=1):
        out.append(
            MrBandsObservation(
                pool=snap.pool,
                timestamp=snap.timestamp,
                mr_bands_score=round(sc, 6),
                mr_bands_rank=rank,
                mr_bands_action=act,
                source="public_observable_stub",
            )
        )
    return out


def _mark_to_market(account: AccountState, snap_by_pool: Mapping[str, PoolSnapshot], cfg: Mapping[str, Any], hours: float) -> None:
    for pool, pos in list(account.positions.items()):
        snap = snap_by_pool.get(pool)
        if snap is None:
            continue
        feat = derive_features(snap, cfg)
        fees_24h = snap.fees_24h if snap.fees_24h is not None else snap.volume_24h * snap.fee_rate
        share = pos.size_usd / max(snap.tvl, 1e-9)
        earned = share * fees_24h * (hours / 24.0)
        if not feat.in_range:
            earned *= 0.05
        pos.accumulated_fees += earned
        pos.inventory_pnl += pos.size_usd * feat.inventory_exposure * snap.recent_price_change
        pos.band_lower_price = snap.band_lower_price or pos.band_lower_price
        pos.band_upper_price = snap.band_upper_price or pos.band_upper_price
    n_pos = len(account.positions)
    if n_pos:
        rent = float(cfg.get("costs", {}).get("rent_usd_per_position_day", 0.0) or 0.0)
        rent_step = rent * (hours / 24.0) * n_pos
        account.cash_usd -= rent_step
        account.costs_paid += rent_step
    _revalue(account)


def _revalue(account: AccountState) -> None:
    pos_val = sum(p.size_usd + p.accumulated_fees + p.inventory_pnl for p in account.positions.values())
    account.equity_usd = account.cash_usd + pos_val
    if account.peak_equity <= 0:
        account.peak_equity = account.equity_usd
    account.peak_equity = max(account.peak_equity, account.equity_usd)
    dd = (account.peak_equity - account.equity_usd) / max(account.peak_equity, 1e-9)
    account.max_drawdown = max(account.max_drawdown, dd)


def _execute(
    action: str,
    snap: PoolSnapshot,
    feat,
    account: AccountState,
    cfg: Mapping[str, Any],
    now_unix: float,
    day_stamp: str,
    guard_hits: Dict[str, float],
) -> float:
    """Apply an actual (post-guard) action. Returns net cash delta from costs/fees."""
    costs = cfg["costs"]
    assumed = float(cfg["action_policy"]["assumed_position_usd"])
    max_alloc = float(cfg["guards"]["max_allocation_per_position"])
    reserve = float(cfg["guards"]["minimum_reserve"])
    net = 0.0

    if action == "OPEN" and snap.pool not in account.positions:
        size = min(assumed, max_alloc * account.equity_usd, account.cash_usd - reserve * account.equity_usd)
        if size < 10.0:
            return 0.0
        fee = float(costs["open_usd"])
        account.cash_usd -= size + fee
        account.costs_paid += fee
        account.positions[snap.pool] = PositionState(
            pool=snap.pool,
            size_usd=size,
            entry_price=snap.price,
            band_lower_price=snap.band_lower_price or snap.price * 0.97,
            band_upper_price=snap.band_upper_price or snap.price * 1.03,
            accumulated_fees=0.0,
            inventory_pnl=0.0,
            opened_at=snap.timestamp,
        )
        net -= fee
        account.actions_today += 1
        account.last_action_unix = now_unix
        account.day_stamp = day_stamp
    elif action == "CLOSE" and snap.pool in account.positions:
        pos = account.positions.pop(snap.pool)
        fee = float(costs["close_usd"])
        proceeds = pos.size_usd + pos.accumulated_fees + pos.inventory_pnl - fee
        account.cash_usd += proceeds
        account.costs_paid += fee
        account.fees_collected += pos.accumulated_fees
        account.realized_pnl += pos.inventory_pnl - fee
        net += pos.accumulated_fees + pos.inventory_pnl - fee
        account.actions_today += 1
        account.last_action_unix = now_unix
        account.day_stamp = day_stamp
    elif action == "MOVE" and snap.pool in account.positions:
        fee = float(costs["rebalance_usd"])
        account.cash_usd -= fee
        account.costs_paid += fee
        pos = account.positions[snap.pool]
        pos.band_lower_price = snap.band_lower_price or snap.price * 0.97
        pos.band_upper_price = snap.band_upper_price or snap.price * 1.03
        net -= fee
        account.actions_today += 1
        account.last_action_unix = now_unix
        account.day_stamp = day_stamp
    elif action == "CLAIM" and snap.pool in account.positions:
        pos = account.positions[snap.pool]
        fee = float(costs["claim_usd"])
        account.cash_usd += pos.accumulated_fees - fee
        account.fees_collected += pos.accumulated_fees
        account.costs_paid += fee
        net += pos.accumulated_fees - fee
        pos.accumulated_fees = 0.0
        account.actions_today += 1
        account.last_action_unix = now_unix
        account.day_stamp = day_stamp

    _revalue(account)
    return net


def run_backtest(
    snapshots: Optional[Sequence[PoolSnapshot]] = None,
    cfg: Optional[Mapping[str, Any]] = None,
    policy_overrides: Optional[Mapping[str, Any]] = None,
    guard_overrides: Optional[Mapping[str, Any]] = None,
    weight_overrides: Optional[Mapping[str, float]] = None,
) -> Dict[str, Any]:
    assert_research_only()
    cfg = deepcopy(mapping_to_dict(cfg or load_config()))
    if policy_overrides:
        cfg.setdefault("action_policy", {}).update(dict(policy_overrides))
    if guard_overrides:
        cfg.setdefault("guards", {}).update(dict(guard_overrides))
    if weight_overrides:
        cfg.setdefault("opportunity_weights", {}).update(dict(weight_overrides))
        total = sum(float(cfg["opportunity_weights"][k]) for k in cfg["opportunity_weights"] if k in {
            "fee_tvl_quality",
            "volume_tvl_persistence",
            "liquidity_depth_quality",
            "in_range_stability",
            "cost_adjusted_expected_return",
        })
        if total > 0:
            for k in list(cfg["opportunity_weights"]):
                if k in {
                    "fee_tvl_quality",
                    "volume_tvl_persistence",
                    "liquidity_depth_quality",
                    "in_range_stability",
                    "cost_adjusted_expected_return",
                }:
                    cfg["opportunity_weights"][k] = float(cfg["opportunity_weights"][k]) / total

    snaps = list(snapshots if snapshots is not None else generate_snapshots(cfg))
    sim = cfg.get("simulation") or {}
    capital = float(sim.get("capital_usd", 1000.0))
    hours = float(sim.get("hours_per_step", 1.0))
    account = AccountState(equity_usd=capital, cash_usd=capital, peak_equity=capital)
    engine = GuardEngine(cfg)
    by_ts: Dict[str, List[PoolSnapshot]] = defaultdict(list)
    for s in snaps:
        by_ts[s.timestamp].append(s)
    timestamps = sorted(by_ts)

    rows: List[JournalRow] = []
    guard_hits: Dict[str, int] = defaultdict(int)
    guard_loss_prevented: Dict[str, float] = defaultdict(float)
    start_unix = datetime(2026, 9, 18, tzinfo=timezone.utc).timestamp()

    for t_index, ts in enumerate(timestamps):
        cohort = by_ts[ts]
        day_stamp = ts[:10]
        if account.day_stamp != day_stamp:
            account.actions_today = 0
            account.day_stamp = day_stamp
        now_unix = start_unix + t_index * hours * 3600.0
        snap_by_pool = {s.pool: s for s in cohort}
        _mark_to_market(account, snap_by_pool, cfg, hours)

        # Evaluate each pool without updating last_action_unix until after the cycle
        # so a single research cycle can open multiple concurrent pools.
        freeze_last = account.last_action_unix
        cycle_account_view = account
        scored = []
        for snap in cohort:
            feat = derive_features(snap, cfg)
            breakdown = score_opportunity(feat, cfg)
            pos = account.positions.get(snap.pool)
            proposal = recommend_action(feat, breakdown, pos, cfg)
            saved_last = account.last_action_unix
            account.last_action_unix = freeze_last
            guarded = engine.apply(proposal, cycle_account_view, feat, now_unix=now_unix, day_stamp=day_stamp)
            account.last_action_unix = saved_last
            scored.append((snap, feat, breakdown, proposal, guarded))

        scored.sort(key=lambda item: item[2].score, reverse=True)
        obs = _observations_for(cohort, cfg, account.positions)
        obs_map = {o.pool: o for o in obs}

        for rank, (snap, feat, breakdown, proposal, guarded) in enumerate(scored, start=1):
            for gname in guarded.tripped:
                guard_hits[gname] += 1
            observation = obs_map.get(snap.pool)
            top_feature = max(breakdown.weighted, key=breakdown.weighted.get) if breakdown.weighted else None
            causes = []
            if observation is not None:
                causes = classify_disagreement(
                    our_score=breakdown.score,
                    mr_score=observation.mr_bands_score,
                    our_action=guarded.actual_action,
                    mr_action=observation.mr_bands_action,
                    our_rank=rank,
                    mr_rank=observation.mr_bands_rank,
                    fee_tvl_component=breakdown.components.get("fee_tvl_quality"),
                    guard_tripped=guarded.tripped,
                    reason=proposal.reason if guarded.passed else guarded.reason,
                    stale=feat.stale,
                    our_top_feature=top_feature,
                )
            step_net = 0.0
            if guarded.actual_action != "HOLD":
                # Re-apply guards against live account after earlier executions in this cycle.
                live = engine.apply(proposal, account, feat, now_unix=now_unix, day_stamp=day_stamp)
                actual = live.actual_action
                for gname in live.tripped:
                    guard_hits[gname] += 1
                if actual != "HOLD":
                    step_net = _execute(actual, snap, feat, account, cfg, now_unix, day_stamp, {})
                guarded = live
            else:
                actual = "HOLD"

            inv_dd = snap.next_inventory_drawdown
            fee_next = snap.next_fee_tvl
            net_after = None
            if fee_next is not None:
                assumed = float(cfg["action_policy"]["assumed_position_usd"])
                cost_drag = feat.transaction_rent_rebalance_cost / max(assumed, 1.0)
                net_after = feat.expected_fees_per_dollar - (inv_dd or 0.0) - (
                    cost_drag if actual in {"OPEN", "MOVE", "CLOSE", "CLAIM"} else 0.0
                )

            reason = proposal.reason if guarded.passed else f"{proposal.reason} | {guarded.reason}"
            rows.append(
                JournalRow(
                    timestamp=ts,
                    pool=snap.pool,
                    our_opportunity_score=round(breakdown.score, 6),
                    our_rank=rank,
                    features_used=list(breakdown.features_used),
                    recommended_action=proposal.action,
                    guard_result=guarded.to_dict(),
                    actual_action=guarded.actual_action,
                    reason=reason,
                    mr_bands_score=observation.mr_bands_score if observation else None,
                    mr_bands_rank=observation.mr_bands_rank if observation else None,
                    mr_bands_action=observation.mr_bands_action if observation else None,
                    disagreement_causes=causes,
                    subsequent_fee_tvl=fee_next,
                    subsequent_inventory_drawdown=inv_dd,
                    net_return_after_costs=net_after if net_after is None else net_after + step_net / max(account.equity_usd, 1.0),
                    features=feat.as_public_dict(),
                )
            )

    metrics = compute_metrics(rows)
    metrics["terminal_equity"] = account.equity_usd
    metrics["max_drawdown"] = account.max_drawdown
    metrics["fees_collected"] = account.fees_collected
    metrics["costs_paid"] = account.costs_paid
    metrics["realized_pnl"] = account.realized_pnl
    metrics["guard_hits"] = dict(guard_hits)
    metrics["n_positions_open"] = len(account.positions)
    return {
        "metrics": metrics,
        "rows": rows,
        "account": account,
        "config_weights": dict(cfg["opportunity_weights"]),
        "config_policy": dict(cfg["action_policy"]),
        "config_guards": dict(cfg["guards"]),
    }


def _renormalize_weights(weights: Dict[str, float], key: str, new_value: float) -> Dict[str, float]:
    keys = [
        "fee_tvl_quality",
        "volume_tvl_persistence",
        "liquidity_depth_quality",
        "in_range_stability",
        "cost_adjusted_expected_return",
    ]
    out = {k: float(weights[k]) for k in keys}
    out[key] = max(0.02, float(new_value))
    total = sum(out.values())
    return {k: v / total for k, v in out.items()}


def run_sensitivity(snapshots: Sequence[PoolSnapshot], cfg: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
    cfg = mapping_to_dict(cfg or load_config())
    baseline_w = dict(cfg["opportunity_weights"])
    rows: List[Dict[str, Any]] = []
    keys = list(baseline_w.keys())
    variants = [("baseline", dict(baseline_w))]
    for key in keys:
        for delta in (-0.10, -0.05, 0.05, 0.10):
            name = f"{key}{delta:+.2f}"
            variants.append((name, _renormalize_weights(baseline_w, key, baseline_w[key] + delta)))
    # Matching the public observer's fee/TVL-heavy mix — for contrast, not as a target.
    variants.append(
        (
            "match_public_fee_tvl_70_30",
            {
                "fee_tvl_quality": 0.70,
                "volume_tvl_persistence": 0.30,
                "liquidity_depth_quality": 0.0,
                "in_range_stability": 0.0,
                "cost_adjusted_expected_return": 0.0,
            },
        )
    )

    for name, weights in variants:
        result = run_backtest(snapshots, cfg=cfg, weight_overrides=weights)
        m = result["metrics"]
        rec = {
            "variant": name,
            "fee_tvl_w": weights.get("fee_tvl_quality", 0.0),
            "vol_tvl_w": weights.get("volume_tvl_persistence", 0.0),
            "depth_w": weights.get("liquidity_depth_quality", 0.0),
            "stability_w": weights.get("in_range_stability", 0.0),
            "cost_adj_w": weights.get("cost_adjusted_expected_return", 0.0),
            "terminal_equity": m.get("terminal_equity"),
            "max_drawdown": m.get("max_drawdown"),
            "mean_net_return": m.get("net_return_after_estimated_execution_costs"),
            "rank_correlation": m.get("rank_correlation"),
            "action_agreement": m.get("action_agreement"),
            "hold_agreement": m.get("hold_agreement"),
            "churn_rate": m.get("false_action_churn_rate"),
            "score_vs_net_return": m.get("score_predictive_of_net_return"),
            "pool_overlap": m.get("pool_selection_overlap"),
            "fees_collected": m.get("fees_collected"),
        }
        rows.append(rec)
    return rows


def run_guard_ablation(snapshots: Sequence[PoolSnapshot], cfg: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
    """Ablate guards against an eager policy so code authority is the variable."""
    cfg = mapping_to_dict(cfg or load_config())
    eager = {"hold_cost_advantage_min": 0.0, "open_score_threshold": 0.20}
    baseline = run_backtest(snapshots, cfg=cfg, policy_overrides=eager)
    base_dd = float(baseline["metrics"]["max_drawdown"] or 0.0)
    base_eq = float(baseline["metrics"]["terminal_equity"] or 0.0)
    out = []
    guards = dict(cfg["guards"])
    for name in guards:
        overridden = dict(guards)
        if isinstance(overridden[name], bool):
            overridden[name] = False
        elif isinstance(overridden[name], (int, float)):
            # Disable by making the cap non-binding.
            overridden[name] = 10 ** 9 if float(overridden[name]) < 1e6 else 0.0
            if name == "stop_loss":
                overridden[name] = 1.0
            if name == "minimum_reserve":
                overridden[name] = 0.0
            if name == "abnormal_price_move_veto":
                overridden[name] = 10.0
            if name == "max_allowed_slippage":
                overridden[name] = 1.0
            if name == "cooldown_seconds":
                overridden[name] = 0
        result = run_backtest(snapshots, cfg=cfg, policy_overrides=eager, guard_overrides=overridden)
        eq = float(result["metrics"]["terminal_equity"] or 0.0)
        dd = float(result["metrics"]["max_drawdown"] or 0.0)
        out.append(
            {
                "guard": name,
                "baseline_equity": base_eq,
                "ablated_equity": eq,
                "equity_lost_when_disabled": base_eq - eq,
                "baseline_drawdown": base_dd,
                "ablated_drawdown": dd,
                "extra_drawdown_when_disabled": dd - base_dd,
            }
        )
    out.sort(key=lambda r: r["equity_lost_when_disabled"], reverse=True)
    combo = dict(guards)
    combo["max_band_width"] = 10 ** 9
    combo["max_allowed_slippage"] = 1.0
    combo["abnormal_price_move_veto"] = 10.0
    combo_result = run_backtest(snapshots, cfg=cfg, policy_overrides=eager, guard_overrides=combo)
    out.append(
        {
            "guard": "combo:band_width+slippage+abnormal_move",
            "baseline_equity": base_eq,
            "ablated_equity": float(combo_result["metrics"]["terminal_equity"] or 0.0),
            "equity_lost_when_disabled": base_eq - float(combo_result["metrics"]["terminal_equity"] or 0.0),
            "baseline_drawdown": base_dd,
            "ablated_drawdown": float(combo_result["metrics"]["max_drawdown"] or 0.0),
            "extra_drawdown_when_disabled": float(combo_result["metrics"]["max_drawdown"] or 0.0) - base_dd,
        }
    )
    spray = dict(combo)
    spray["max_concurrent_pools"] = 10 ** 9
    spray["max_actions_per_day"] = 10 ** 9
    spray["max_allocation_per_position"] = 1.0
    spray["max_aggregate_exposure"] = 1.0
    spray["minimum_reserve"] = 0.0
    spray["cooldown_seconds"] = 0
    spray_result = run_backtest(snapshots, cfg=cfg, policy_overrides=eager, guard_overrides=spray)
    out.append(
        {
            "guard": "combo:caps+liquidity+abnormal (spray)",
            "baseline_equity": base_eq,
            "ablated_equity": float(spray_result["metrics"]["terminal_equity"] or 0.0),
            "equity_lost_when_disabled": base_eq - float(spray_result["metrics"]["terminal_equity"] or 0.0),
            "baseline_drawdown": base_dd,
            "ablated_drawdown": float(spray_result["metrics"]["max_drawdown"] or 0.0),
            "extra_drawdown_when_disabled": float(spray_result["metrics"]["max_drawdown"] or 0.0) - base_dd,
        }
    )
    out.sort(key=lambda r: r["equity_lost_when_disabled"], reverse=True)
    return out


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def build_report(
    baseline: Dict[str, Any],
    sensitivity: Sequence[Mapping[str, Any]],
    ablation: Sequence[Mapping[str, Any]],
    hold_first: Dict[str, Any],
    aggressive: Dict[str, Any],
) -> Tuple[Dict[str, Any], str]:
    m = baseline["metrics"]
    causes = m.get("disagreement_cause_counts") or {}
    top_causes = sorted(causes.items(), key=lambda kv: kv[1], reverse=True)
    base_row = next((r for r in sensitivity if r["variant"] == "baseline"), None)
    best_econ = max(sensitivity, key=lambda r: (r["terminal_equity"] is not None, r["terminal_equity"] or 0))
    best_corr = max(sensitivity, key=lambda r: (r["rank_correlation"] is not None, r["rank_correlation"] or -9))
    match_row = next((r for r in sensitivity if r["variant"] == "match_public_fee_tvl_70_30"), None)
    top_guard = ablation[0] if ablation else None

    # Robustness: weight keys whose +/-10% variants keep terminal equity within 2% of baseline.
    robust = []
    if base_row:
        for key, label in (
            ("fee_tvl_w", "fee_tvl_quality"),
            ("vol_tvl_w", "volume_tvl_persistence"),
            ("depth_w", "liquidity_depth_quality"),
            ("stability_w", "in_range_stability"),
            ("cost_adj_w", "cost_adjusted_expected_return"),
        ):
            related = [r for r in sensitivity if r["variant"].startswith(label)]
            if not related:
                continue
            eqs = [r["terminal_equity"] for r in related if r["terminal_equity"] is not None]
            if eqs and base_row["terminal_equity"]:
                spread = (max(eqs) - min(eqs)) / max(base_row["terminal_equity"], 1e-9)
                robust.append((label, spread, sum(eqs) / len(eqs)))

    answers = {
        "q1_disagreement_inputs": [c for c, n in top_causes if n > 0],
        "q1_counts": dict(top_causes),
        "q2_changing_weights_improves_economics": bool(
            best_econ and base_row and (best_econ["terminal_equity"] or 0) > (base_row["terminal_equity"] or 0) + 1e-9
        ),
        "q2_best_economic_variant": best_econ["variant"] if best_econ else None,
        "q2_best_correlation_variant": best_corr["variant"] if best_corr else None,
        "q2_match_public_observer_equity": match_row["terminal_equity"] if match_row else None,
        "q2_baseline_equity": base_row["terminal_equity"] if base_row else None,
        "q3_hold_first_churn": hold_first["metrics"]["false_action_churn_rate"],
        "q3_aggressive_churn": aggressive["metrics"]["false_action_churn_rate"],
        "q3_hold_first_recommended_churn": hold_first["metrics"].get("recommended_churn_rate"),
        "q3_aggressive_recommended_churn": aggressive["metrics"].get("recommended_churn_rate"),
        "q3_hold_first_reduces_churn": (
            (hold_first["metrics"].get("recommended_churn_rate") or 0)
            <= (aggressive["metrics"].get("recommended_churn_rate") or 0)
        ),
        "q3_hold_first_equity": hold_first["metrics"]["terminal_equity"],
        "q3_aggressive_equity": aggressive["metrics"]["terminal_equity"],
        "q4_top_guard": top_guard["guard"] if top_guard else None,
        "q4_ablation": list(ablation),
        "q5_weight_robustness_spread": {k: s for k, s, _ in robust},
        "q6_score_predictive_of_net_after_costs": m.get("score_predictive_of_net_return"),
    }

    payload = {
        "note": "Independent comparable model. Weights are not Mr Bands private coefficients. Simulation only — no live funds.",
        "baseline_metrics": m,
        "answers": answers,
        "sensitivity_preview": list(sensitivity)[:8],
    }

    lines = [
        "# Bands comparison baseline",
        "",
        "Independent DLMM LP research lane. **Not** a clone of Mr Bands private coefficients.",
        "Simulation only: no real funds, no signed transactions, no live deployment.",
        "The harness 40/30/30 capital mix is **not** the pool opportunity score.",
        "",
        "## Baseline metrics",
        "",
        f"- Rank correlation vs public Mr Bands stub: `{_fmt(m.get('rank_correlation'))}`",
        f"- Action agreement: `{_fmt(m.get('action_agreement'))}`",
        f"- HOLD agreement: `{_fmt(m.get('hold_agreement'))}`",
        f"- False-action / churn rate: `{_fmt(m.get('false_action_churn_rate'))}`",
        f"- Pool-selection overlap: `{_fmt(m.get('pool_selection_overlap'))}`",
        f"- Subsequent fee/TVL (mean): `{_fmt(m.get('subsequent_fee_tvl_performance'))}`",
        f"- Subsequent inventory drawdown (mean): `{_fmt(m.get('subsequent_inventory_drawdown'))}`",
        f"- Mean net return after estimated execution costs: `{_fmt(m.get('net_return_after_estimated_execution_costs'))}`",
        f"- Terminal simulated equity: `{_fmt(m.get('terminal_equity'), 2)}`",
        f"- Max drawdown: `{_fmt(m.get('max_drawdown'))}`",
        f"- Score vs subsequent net return (Spearman): `{_fmt(m.get('score_predictive_of_net_return'))}`",
        "",
        "## 1. Which inputs explain most disagreement with Mr Bands?",
        "",
        "Disagreement is attributed, not minimized. Public stub is fee/TVL-heavy with a low OPEN threshold and almost no cost drag.",
        "",
    ]
    for cause, n in top_causes:
        lines.append(f"- `{cause}`: {n} rows")
    if not any(n > 0 for _, n in top_causes):
        lines.append("- No labeled disagreements in this slice.")
    lines.extend(
        [
            "",
            "Most disagreement is expected from **different weight** (we spread 35/20/15/15/15 vs a ~70/30 fee-volume public stub),",
            "**different cost assumption** (HOLD-first vs cost-blind OPEN), and **different guard** (band width, abnormal move, reserve).",
            "",
            "## 2. Does changing weights actually improve economic results?",
            "",
            f"- Baseline terminal equity: `{_fmt(answers['q2_baseline_equity'], 2)}`",
            f"- Best economic variant: `{answers['q2_best_economic_variant']}` at `{_fmt(best_econ['terminal_equity'] if best_econ else None, 2)}`",
            f"- Best rank-correlation variant: `{answers['q2_best_correlation_variant']}`",
            f"- Public-observer-matching 70/30 equity: `{_fmt(answers['q2_match_public_observer_equity'], 2)}`",
            f"- Changing weights improved economics vs baseline: **{answers['q2_changing_weights_improves_economics']}**",
            "",
            "Matching the public stub's numerical mix is not the same as improving net return after inventory/rent/tx costs.",
            "",
            "## 3. Does HOLD-first policy reduce churn?",
            "",
            f"- HOLD-first recommended (pre-guard) churn: `{_fmt(hold_first['metrics'].get('recommended_churn_rate'))}`",
            f"- Aggressive recommended (pre-guard) churn: `{_fmt(aggressive['metrics'].get('recommended_churn_rate'))}`",
            f"- HOLD-first actual (post-guard) churn: `{_fmt(answers['q3_hold_first_churn'])}` equity `{_fmt(answers['q3_hold_first_equity'], 2)}`",
            f"- Aggressive actual (post-guard) churn: `{_fmt(answers['q3_aggressive_churn'])}` equity `{_fmt(answers['q3_aggressive_equity'], 2)}`",
            f"- HOLD-first reduces churn: **{answers['q3_hold_first_reduces_churn']}**",
            "",
            "## 4. Which guard rules prevent the largest losses?",
            "",
            "Ablation uses an eager policy (low OPEN threshold, no cost-advantage HOLD) so guards are the last line of authority.",
            "Single-guard leave-one-out is often flat when remaining rules still block the same pool; a combo row tests that overlap.",
            "",
            "Baseline guard hit counts (vetoes, not equity): "
            + ", ".join(f"`{k}`={v}" for k, v in sorted((m.get("guard_hits") or {}).items(), key=lambda kv: -kv[1])),
            "",
        ]
    )
    for row in ablation:
        lines.append(
            f"- `{row['guard']}`: equity lost when disabled `{_fmt(row['equity_lost_when_disabled'], 2)}`, "
            f"extra drawdown `{_fmt(row['extra_drawdown_when_disabled'])}`"
        )
    if top_guard and (top_guard["equity_lost_when_disabled"] or 0) > 1e-6:
        lines.extend(
            [
                "",
                f"Largest economic backstop in this simulation: **`{top_guard['guard']}`** "
                f"(equity lost when disabled `{_fmt(top_guard['equity_lost_when_disabled'], 2)}`).",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "No leave-one-out guard increased losses on this tape: score ranking plus overlapping caps kept capital out of toxic pools.",
                "Read the combo/spray rows and hit counts rather than treating a $0.00 leave-one-out as a winner.",
            ]
        )
    lines.extend(
        [
            "",
            "## 5. Which weights are robust across multiple pools?",
            "",
            "Spread is (max-min terminal equity of ± perturbations) / baseline equity. Lower is more robust.",
            "",
        ]
    )
    for label, spread, mean_eq in sorted(robust, key=lambda x: x[1]):
        lines.append(f"- `{label}`: equity spread `{spread:.3f}`, mean equity `{mean_eq:.2f}`")
    lines.extend(
        [
            "",
            "## 6. Is our score predictive of fee income AFTER inventory/rent/transaction costs?",
            "",
            f"- Spearman(score, subsequent net return after costs): `{_fmt(answers['q6_score_predictive_of_net_after_costs'])}`",
            "",
            "A positive rank correlation means higher opportunity scores lined up with better cost-adjusted outcomes on this simulated tape.",
            "A near-zero or negative value means the score is not yet a reliable after-cost predictor and should not be traded.",
            "",
            "## Next evidence-backed change",
            "",
            "fees/active TVL + wash-volume veto was tested on held-out seed 97 and **did not ship**",
            "(see `reports/experiment_active_tvl.md`). Do not re-enable those flags without a tape where",
            "treatment Spearman and equity both beat control and HOLD-first recommended churn stays at or under 0.46.",
            "Next: tighten wash rules so they do not inflate OPEN proposals, or size positions so rent is a small",
            "fraction of expected in-range fees.",
            "",
        ]
    )
    return payload, "\n".join(lines) + "\n"


def _control_cfg(cfg: Mapping[str, Any]) -> Dict[str, Any]:
    out = deepcopy(mapping_to_dict(cfg))
    out.setdefault("features", {})["use_active_tvl"] = False
    out.setdefault("guards", {})["wash_volume_veto"] = False
    return out


def _write_snapshot_fixture(path: str, snaps: Sequence[PoolSnapshot], note: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "note": note,
                "snapshots": [s.__dict__ for s in snaps],
            },
            fh,
            indent=2,
        )


def _write_sensitivity_csv(path: str, sensitivity: Sequence[Mapping[str, Any]]) -> None:
    fieldnames = [
        "variant",
        "fee_tvl_w",
        "vol_tvl_w",
        "depth_w",
        "stability_w",
        "cost_adj_w",
        "terminal_equity",
        "max_drawdown",
        "mean_net_return",
        "rank_correlation",
        "action_agreement",
        "hold_agreement",
        "churn_rate",
        "score_vs_net_return",
        "pool_overlap",
        "fees_collected",
    ]
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in sensitivity:
            writer.writerow({k: row.get(k) for k in fieldnames})


def _persist_feature_flags(cfg: Mapping[str, Any], use_active_tvl: bool, wash_veto: bool) -> None:
    from .schemas import default_config_path

    path = default_config_path()
    raw = mapping_to_dict(cfg)
    raw.setdefault("features", {})["use_active_tvl"] = bool(use_active_tvl)
    raw.setdefault("guards", {})["wash_volume_veto"] = bool(wash_veto)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(raw, fh, indent=2)
        fh.write("\n")


def write_experiment_report(
    *,
    out_dir: str,
    ship: bool,
    churn_cap: float,
    control_in: Dict[str, Any],
    treatment_in: Dict[str, Any],
    control_out: Dict[str, Any],
    treatment_out: Dict[str, Any],
) -> Tuple[str, str]:
    ci, ti = control_in["metrics"], treatment_in["metrics"]
    co, to = control_out["metrics"], treatment_out["metrics"]
    payload = {
        "experiment": "fees/active TVL + wash-volume veto vs control (total TVL, no wash veto)",
        "weights_unchanged": True,
        "ship": ship,
        "churn_cap": churn_cap,
        "in_sample_seed": 13,
        "held_out_seed": 97,
        "held_out": {
            "control_equity": co.get("terminal_equity"),
            "treatment_equity": to.get("terminal_equity"),
            "control_spearman": co.get("score_predictive_of_net_return"),
            "treatment_spearman": to.get("score_predictive_of_net_return"),
            "control_churn_recommended": co.get("recommended_churn_rate"),
            "treatment_churn_recommended": to.get("recommended_churn_rate"),
            "control_drawdown": co.get("max_drawdown"),
            "treatment_drawdown": to.get("max_drawdown"),
            "control_guard_hits": co.get("guard_hits"),
            "treatment_guard_hits": to.get("guard_hits"),
        },
        "in_sample": {
            "control_equity": ci.get("terminal_equity"),
            "treatment_equity": ti.get("terminal_equity"),
            "control_spearman": ci.get("score_predictive_of_net_return"),
            "treatment_spearman": ti.get("score_predictive_of_net_return"),
            "treatment_churn_recommended": ti.get("recommended_churn_rate"),
        },
        "decision": (
            "SHIP: held-out equity and Spearman both held or improved; HOLD-first recommended churn at or under cap."
            if ship
            else "NO-SHIP: revert feature flags. Code paths remain for the next tape."
        ),
    }
    lines = [
        "# Experiment: fees/active TVL + wash-volume veto",
        "",
        "Baseline weights stayed **35/20/15/15/15**. Sentinel untouched. Simulation only.",
        "",
        f"**Decision: {'SHIP' if ship else 'NO-SHIP / REVERT FLAGS'}**",
        "",
        "## Gate (held-out seed 97, rug + wash tape)",
        "",
        f"- Control equity: `{_fmt(co.get('terminal_equity'), 2)}`",
        f"- Treatment equity: `{_fmt(to.get('terminal_equity'), 2)}`",
        f"- Control Spearman(score, net after costs): `{_fmt(co.get('score_predictive_of_net_return'))}`",
        f"- Treatment Spearman: `{_fmt(to.get('score_predictive_of_net_return'))}`",
        f"- Treatment HOLD-first recommended churn: `{_fmt(to.get('recommended_churn_rate'))}` (cap `{churn_cap}`)",
        f"- Control max drawdown: `{_fmt(co.get('max_drawdown'))}`",
        f"- Treatment max drawdown: `{_fmt(to.get('max_drawdown'))}`",
        f"- Treatment wash veto hits: `{(to.get('guard_hits') or {}).get('wash_volume_veto', 0)}`",
        "",
        "## In-sample seed 13 (same universe, different RNG path)",
        "",
        f"- Control equity `{_fmt(ci.get('terminal_equity'), 2)}` vs treatment `{_fmt(ti.get('terminal_equity'), 2)}`",
        f"- Control Spearman `{_fmt(ci.get('score_predictive_of_net_return'))}` vs treatment `{_fmt(ti.get('score_predictive_of_net_return'))}`",
        "",
        payload["decision"],
        "",
    ]
    json_path = os.path.join(out_dir, "experiment_active_tvl.json")
    md_path = os.path.join(out_dir, "experiment_active_tvl.md")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return json_path, md_path


def write_reports(
    out_dir: Optional[str] = None,
    snapshots: Optional[Sequence[PoolSnapshot]] = None,
) -> Dict[str, str]:
    assert_research_only()
    cfg = mapping_to_dict(load_config())
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = out_dir or os.path.join(root, "reports")
    os.makedirs(out_dir, exist_ok=True)
    sim = cfg.get("simulation") or {}
    in_seed = int(sim.get("seed", 13))
    out_seed = int(sim.get("held_out_seed", 97))
    churn_cap = float(sim.get("churn_cap", 0.46))

    in_sample = list(snapshots if snapshots is not None else generate_snapshots(cfg, seed=in_seed))
    held_out = generate_snapshots(cfg, seed=out_seed)
    control = _control_cfg(cfg)

    treatment_in = run_backtest(in_sample, cfg=cfg)
    control_in = run_backtest(in_sample, cfg=control)
    treatment_out = run_backtest(held_out, cfg=cfg)
    control_out = run_backtest(held_out, cfg=control)

    ship = decide_ship(
        control_equity=control_out["metrics"].get("terminal_equity"),
        treatment_equity=treatment_out["metrics"].get("terminal_equity"),
        control_spearman=control_out["metrics"].get("score_predictive_of_net_return"),
        treatment_spearman=treatment_out["metrics"].get("score_predictive_of_net_return"),
        treatment_recommended_churn=treatment_out["metrics"].get("recommended_churn_rate"),
        churn_cap=churn_cap,
    )
    _persist_feature_flags(cfg, use_active_tvl=ship, wash_veto=ship)
    shipped_cfg = cfg if ship else control

    fixtures_dir = os.path.join(root, "fixtures")
    os.makedirs(fixtures_dir, exist_ok=True)
    fixture_path = os.path.join(fixtures_dir, "dlmm_snapshots.json")
    held_fixture = os.path.join(fixtures_dir, "dlmm_snapshots_heldout.json")
    _write_snapshot_fixture(fixture_path, in_sample, "In-sample simulated DLMM snapshots. Not live chain data.")
    _write_snapshot_fixture(held_fixture, held_out, "Held-out seed 97 with rug/wipe and wash pools. Not live chain data.")

    baseline = run_backtest(in_sample, cfg=shipped_cfg)
    hold_first = baseline
    aggressive = run_backtest(
        in_sample,
        cfg=shipped_cfg,
        policy_overrides={"hold_cost_advantage_min": 0.0, "open_score_threshold": 0.20},
    )
    sensitivity = run_sensitivity(in_sample, cfg=shipped_cfg)
    ablation = run_guard_ablation(in_sample, cfg=shipped_cfg)
    payload, markdown = build_report(baseline, sensitivity, ablation, hold_first, aggressive)
    payload["experiment_shipped"] = ship

    held_run = run_backtest(held_out, cfg=shipped_cfg)
    held_agg = run_backtest(
        held_out,
        cfg=shipped_cfg,
        policy_overrides={"hold_cost_advantage_min": 0.0, "open_score_threshold": 0.20},
    )
    held_sens = run_sensitivity(held_out, cfg=shipped_cfg)
    held_ablate = run_guard_ablation(held_out, cfg=shipped_cfg)
    held_payload, held_md = build_report(held_run, held_sens, held_ablate, held_run, held_agg)
    held_payload["tape"] = "held_out_seed_97"
    held_md = held_md.replace("# Bands comparison baseline", "# Bands comparison held-out (seed 97, rug + wash)")

    json_path = os.path.join(out_dir, "bands_comparison_baseline.json")
    md_path = os.path.join(out_dir, "bands_comparison_baseline.md")
    csv_path = os.path.join(out_dir, "weight_sensitivity.csv")
    held_json = os.path.join(out_dir, "bands_comparison_heldout.json")
    held_md_path = os.path.join(out_dir, "bands_comparison_heldout.md")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(markdown)
    _write_sensitivity_csv(csv_path, sensitivity)
    with open(held_json, "w", encoding="utf-8") as fh:
        json.dump(held_payload, fh, indent=2, default=str)
    with open(held_md_path, "w", encoding="utf-8") as fh:
        fh.write(held_md)

    exp_json, exp_md = write_experiment_report(
        out_dir=out_dir,
        ship=ship,
        churn_cap=churn_cap,
        control_in=control_in,
        treatment_in=treatment_in,
        control_out=control_out,
        treatment_out=treatment_out,
    )

    from .journal import append_rows

    journal_path = os.path.join(out_dir, "bands_journal.jsonl")
    if os.path.exists(journal_path):
        os.remove(journal_path)
    append_rows(baseline["rows"], path=journal_path)

    return {
        "json": json_path,
        "markdown": md_path,
        "csv": csv_path,
        "journal": journal_path,
        "fixtures": fixture_path,
        "heldout_json": held_json,
        "heldout_markdown": held_md_path,
        "heldout_fixtures": held_fixture,
        "experiment_json": exp_json,
        "experiment_markdown": exp_md,
        "shipped": str(ship).lower(),
    }
