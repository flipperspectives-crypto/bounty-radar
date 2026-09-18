"""Action policy: HOLD / OPEN / MOVE / CLAIM / CLOSE.

Separate from opportunity score (attractiveness) and hard guards (authority).
HOLD is the default whenever expected benefit of changing a position does
not exceed estimated transaction / repositioning cost.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from .schemas import ActionProposal, PoolFeatures, PositionState, ScoreBreakdown, mapping_to_dict


def _pol(cfg: Mapping[str, Any], key: str, default: float) -> float:
    block = cfg.get("action_policy") if isinstance(cfg, Mapping) else None
    if isinstance(block, Mapping) and key in block:
        return float(block[key])
    return default


def _cost(cfg: Mapping[str, Any], key: str, default: float) -> float:
    block = cfg.get("costs") if isinstance(cfg, Mapping) else None
    if isinstance(block, Mapping) and key in block:
        return float(block[key])
    return default


def recommend_action(
    features: PoolFeatures,
    breakdown: ScoreBreakdown,
    position: Optional[PositionState],
    cfg: Mapping[str, Any],
) -> ActionProposal:
    cfg = mapping_to_dict(cfg)
    score = float(breakdown.score)
    assumed = _pol(cfg, "assumed_position_usd", 150.0)
    size = position.size_usd if position and position.size_usd > 0 else assumed
    hold_mult = _pol(cfg, "hold_cost_advantage_min", 1.25)
    open_thr = _pol(cfg, "open_score_threshold", 0.65)
    move_thr = _pol(cfg, "move_min_score", 0.55)
    move_oor = _pol(cfg, "move_min_oor_hours", 1.0)
    edge_eps = _pol(cfg, "move_edge_epsilon", 0.02)
    claim_mult = _pol(cfg, "claim_fee_multiple", 3.0)
    close_thr = _pol(cfg, "close_score_threshold", 0.35)
    close_oor = _pol(cfg, "close_oor_hours", 12.0)

    open_cost = _cost(cfg, "open_usd", 0.30)
    rebalance_cost = _cost(cfg, "rebalance_usd", 0.20)
    claim_cost = _cost(cfg, "claim_usd", 0.05)
    close_cost = _cost(cfg, "close_usd", 0.20)

    expected_fee_usd = features.expected_fees_per_dollar * size
    has_pos = position is not None and position.size_usd > 0

    if has_pos:
        materially_oor = (not features.in_range) and (
            features.out_of_range_duration >= move_oor or features.distance_from_band_edge <= edge_eps
        )
        fee_quality = float(breakdown.components.get("fee_tvl_quality", 0.0))
        # Brief OOR should MOVE, not CLOSE, if the pool still prints. CLOSE when
        # print quality is gone or the position has been out of range too long.
        deteriorated = features.out_of_range_duration >= close_oor or (
            score <= close_thr and fee_quality < 0.35 and not materially_oor
        )
        if deteriorated:
            return ActionProposal(
                action="CLOSE",
                reason="economics deteriorated or hard risk rule requires closure",
                expected_benefit_usd=max(0.0, -features.inventory_exposure * size * abs(features.recent_price_change)),
                estimated_cost_usd=close_cost,
            )

        # Restore in-range economics for the MOVE attractiveness check so a
        # temporary OOR does not look like a dead pool.
        restored = min(
            1.0,
            score
            + 0.5 * float(breakdown.penalties.get("fee_below_cost", 0.0))
            + 0.15 * (1.0 - float(breakdown.components.get("in_range_stability", 1.0))),
        )
        still_attractive = restored >= move_thr
        if materially_oor and still_attractive:
            # Benefit assumes a reposition restores in-range fee capture.
            benefit = features.fee_tvl * size * 0.50
            if benefit > rebalance_cost * hold_mult:
                return ActionProposal(
                    action="MOVE",
                    reason="materially out of range and pool remains economically attractive",
                    expected_benefit_usd=benefit,
                    estimated_cost_usd=rebalance_cost,
                )
            return ActionProposal(
                action="HOLD",
                reason="HOLD: expected benefit of repositioning does not exceed estimated cost",
                expected_benefit_usd=benefit,
                estimated_cost_usd=rebalance_cost,
            )

        accrued = position.accumulated_fees if position else 0.0
        if accrued >= claim_mult * claim_cost:
            return ActionProposal(
                action="CLAIM",
                reason="accumulated fees exceed configurable multiple of claim cost",
                expected_benefit_usd=accrued,
                estimated_cost_usd=claim_cost,
            )

        return ActionProposal(
            action="HOLD",
            reason="default: expected benefit of changing position does not exceed estimated transaction/repositioning cost",
            expected_benefit_usd=0.0,
            estimated_cost_usd=0.0,
        )

    # Flat: consider OPEN, else HOLD.
    if score >= open_thr:
        if expected_fee_usd > open_cost * hold_mult:
            return ActionProposal(
                action="OPEN",
                reason="opportunity score passed threshold and expected fees exceed open cost",
                expected_benefit_usd=expected_fee_usd,
                estimated_cost_usd=open_cost,
            )
        return ActionProposal(
            action="HOLD",
            reason="HOLD: score passed but expected benefit does not exceed estimated open cost",
            expected_benefit_usd=expected_fee_usd,
            estimated_cost_usd=open_cost,
        )

    return ActionProposal(
        action="HOLD",
        reason="default: score below open threshold; expected benefit of changing position does not exceed cost",
        expected_benefit_usd=expected_fee_usd,
        estimated_cost_usd=open_cost,
    )
