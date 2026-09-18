"""Cohort scoring, Mr Bands comparison, disagreement diagnosis, radar hook.

Does not optimize merely for matching Mr Bands' numerical score.
Live trading is forbidden.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .action_policy import recommend_action
from .guards import GuardEngine
from .journal import append_rows, default_journal_path
from .opportunity_score import score_opportunity
from .pool_features import derive_features
from .schemas import (
    AccountState,
    DISAGREEMENT_CAUSES,
    JournalRow,
    MrBandsObservation,
    PoolSnapshot,
    assert_research_only,
    load_config,
    mapping_to_dict,
)


def spearman_rank(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    n = len(xs)
    if n < 3:
        # Still defined for n=2.
        pass

    def ranks(vals: Sequence[float], reverse: bool = False) -> List[float]:
        indexed = sorted(range(len(vals)), key=lambda i: vals[i], reverse=reverse)
        out = [0.0] * len(vals)
        i = 0
        while i < len(vals):
            j = i
            while j + 1 < len(vals) and vals[indexed[j + 1]] == vals[indexed[i]]:
                j += 1
            avg = (i + 1 + j + 1) / 2.0
            for k in range(i, j + 1):
                out[indexed[k]] = avg
            i = j + 1
        return out

    rx = ranks(xs)
    ry = ranks(ys)
    d2 = sum((a - b) ** 2 for a, b in zip(rx, ry))
    denom = n * (n * n - 1)
    if denom == 0:
        return None
    return 1.0 - (6.0 * d2) / denom


def classify_disagreement(
    our_score: float,
    mr_score: Optional[float],
    our_action: str,
    mr_action: Optional[str],
    our_rank: Optional[int] = None,
    mr_rank: Optional[int] = None,
    fee_tvl_component: Optional[float] = None,
    guard_tripped: Optional[List[str]] = None,
    reason: str = "",
    stale: bool = False,
    our_top_feature: Optional[str] = None,
) -> List[str]:
    """Label *why* we disagree. Not a loss to minimize against their number."""
    causes: List[str] = []
    tripped = guard_tripped or []
    if tripped:
        causes.append("different_guard")
    if mr_score is None or mr_action is None:
        return [c for c in DISAGREEMENT_CAUSES if c in causes]

    score_delta = abs(float(our_score) - float(mr_score))
    rank_delta = abs((our_rank or 0) - (mr_rank or 0)) if our_rank and mr_rank else 0

    if our_action != mr_action:
        if score_delta < 0.08:
            causes.append("different_action_threshold")
        if "cost" in reason.lower():
            causes.append("different_cost_assumption")
        if our_action == "HOLD" and mr_action in {"OPEN", "MOVE"}:
            causes.append("different_objective")

    if rank_delta >= 1 or score_delta >= 0.10:
        if fee_tvl_component is not None and our_top_feature and our_top_feature != "fee_tvl_quality":
            causes.append("different_weight")
        if our_top_feature == "cost_adjusted_expected_return":
            causes.append("different_objective")
            causes.append("different_normalization")
        if stale:
            causes.append("different_feature")
        if fee_tvl_component is not None and abs(float(mr_score) - float(fee_tvl_component)) < abs(
            float(our_score) - float(fee_tvl_component)
        ):
            causes.append("different_weight")
            causes.append("different_normalization")

    # Deduplicate, preserve spec order.
    seen = set()
    ordered = []
    for c in DISAGREEMENT_CAUSES:
        if c in causes and c not in seen:
            seen.add(c)
            ordered.append(c)
    return ordered


def _obs_map(observations: Optional[Iterable[MrBandsObservation]]) -> Dict[str, MrBandsObservation]:
    out: Dict[str, MrBandsObservation] = {}
    if not observations:
        return out
    for obs in observations:
        out[f"{obs.timestamp}|{obs.pool}"] = obs
        out[obs.pool] = obs
    return out


def compare_cohort(
    snapshots: Sequence[PoolSnapshot],
    observations: Optional[Iterable[MrBandsObservation]] = None,
    cfg: Optional[Mapping[str, Any]] = None,
    account: Optional[AccountState] = None,
    now_unix: float = 1_000_000.0,
    day_stamp: str = "1970-01-01",
) -> List[JournalRow]:
    assert_research_only()
    cfg = mapping_to_dict(cfg or load_config())
    engine = GuardEngine(cfg)
    acct = account or AccountState(equity_usd=1000.0, cash_usd=1000.0, peak_equity=1000.0)
    obs = _obs_map(observations)

    scored = []
    for snap in snapshots:
        feat = derive_features(snap, cfg)
        breakdown = score_opportunity(feat, cfg)
        pos = acct.positions.get(snap.pool)
        proposal = recommend_action(feat, breakdown, pos, cfg)
        guarded = engine.apply(proposal, acct, feat, now_unix=now_unix, day_stamp=day_stamp)
        scored.append((snap, feat, breakdown, proposal, guarded))

    scored.sort(key=lambda item: item[2].score, reverse=True)
    rows: List[JournalRow] = []
    for rank, (snap, feat, breakdown, proposal, guarded) in enumerate(scored, start=1):
        key = f"{snap.timestamp}|{snap.pool}"
        observation = obs.get(key) or obs.get(snap.pool)
        top_feature = max(breakdown.weighted, key=breakdown.weighted.get) if breakdown.weighted else None
        mr_score = observation.mr_bands_score if observation else None
        mr_rank = observation.mr_bands_rank if observation else None
        mr_action = observation.mr_bands_action if observation else None
        causes = []
        if observation is not None:
            causes = classify_disagreement(
                our_score=breakdown.score,
                mr_score=mr_score,
                our_action=guarded.actual_action,
                mr_action=mr_action,
                our_rank=rank,
                mr_rank=mr_rank,
                fee_tvl_component=breakdown.components.get("fee_tvl_quality"),
                guard_tripped=guarded.tripped,
                reason=proposal.reason if guarded.passed else guarded.reason,
                stale=feat.stale,
                our_top_feature=top_feature,
            )
        reason = proposal.reason if guarded.passed else f"{proposal.reason} | {guarded.reason}"
        rows.append(
            JournalRow(
                timestamp=snap.timestamp,
                pool=snap.pool,
                our_opportunity_score=round(breakdown.score, 6),
                our_rank=rank,
                features_used=list(breakdown.features_used),
                recommended_action=proposal.action,
                guard_result=guarded.to_dict(),
                actual_action=guarded.actual_action,
                reason=reason,
                mr_bands_score=mr_score,
                mr_bands_rank=mr_rank,
                mr_bands_action=mr_action,
                disagreement_causes=causes,
                subsequent_fee_tvl=snap.next_fee_tvl,
                subsequent_inventory_drawdown=snap.next_inventory_drawdown,
                net_return_after_costs=None,
                features=feat.as_public_dict(),
            )
        )
    return rows


def compute_metrics(rows: Sequence[JournalRow]) -> Dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {
            "rank_correlation": None,
            "action_agreement": None,
            "hold_agreement": None,
            "false_action_churn_rate": None,
            "recommended_churn_rate": None,
            "pool_selection_overlap": None,
            "subsequent_fee_tvl_performance": None,
            "subsequent_inventory_drawdown": None,
            "net_return_after_estimated_execution_costs": None,
            "n": 0,
        }

    paired = [r for r in rows if r.mr_bands_score is not None and r.mr_bands_rank is not None]
    rank_corr = None
    if len(paired) >= 2:
        rank_corr = spearman_rank(
            [float(r.our_opportunity_score) for r in paired],
            [float(r.mr_bands_score) for r in paired],
        )

    action_pairs = [r for r in rows if r.mr_bands_action]
    if action_pairs:
        action_agreement = sum(1 for r in action_pairs if r.actual_action == r.mr_bands_action) / len(action_pairs)
        hold_pairs = [r for r in action_pairs if r.actual_action == "HOLD" or r.mr_bands_action == "HOLD"]
        if hold_pairs:
            hold_agreement = sum(1 for r in hold_pairs if r.actual_action == "HOLD" and r.mr_bands_action == "HOLD") / len(
                hold_pairs
            )
        else:
            hold_agreement = None
    else:
        action_agreement = None
        hold_agreement = None

    churn = sum(1 for r in rows if r.actual_action != "HOLD") / n
    recommended_churn = sum(1 for r in rows if r.recommended_action != "HOLD") / n

    our_open = {r.pool for r in rows if r.actual_action in {"OPEN", "MOVE", "HOLD"} and r.our_rank <= 3}
    mr_open = {r.pool for r in rows if r.mr_bands_action in {"OPEN", "MOVE"} or (r.mr_bands_rank is not None and r.mr_bands_rank <= 3)}
    if our_open or mr_open:
        overlap = len(our_open & mr_open) / max(len(our_open | mr_open), 1)
    else:
        overlap = None

    fee_vals = [r.subsequent_fee_tvl for r in rows if r.subsequent_fee_tvl is not None]
    dd_vals = [r.subsequent_inventory_drawdown for r in rows if r.subsequent_inventory_drawdown is not None]
    net_vals = [r.net_return_after_costs for r in rows if r.net_return_after_costs is not None]

    pred = None
    scored_net = [(r.our_opportunity_score, r.net_return_after_costs) for r in rows if r.net_return_after_costs is not None]
    if len(scored_net) >= 3:
        pred = spearman_rank([a for a, _ in scored_net], [b for _, b in scored_net])

    cause_counts: Dict[str, int] = {c: 0 for c in DISAGREEMENT_CAUSES}
    for r in rows:
        for c in r.disagreement_causes:
            if c in cause_counts:
                cause_counts[c] += 1

    return {
        "rank_correlation": rank_corr,
        "action_agreement": action_agreement,
        "hold_agreement": hold_agreement,
        "false_action_churn_rate": churn,
        "recommended_churn_rate": recommended_churn,
        "pool_selection_overlap": overlap,
        "subsequent_fee_tvl_performance": (sum(fee_vals) / len(fee_vals)) if fee_vals else None,
        "subsequent_inventory_drawdown": (sum(dd_vals) / len(dd_vals)) if dd_vals else None,
        "net_return_after_estimated_execution_costs": (sum(net_vals) / len(net_vals)) if net_vals else None,
        "score_predictive_of_net_return": pred,
        "disagreement_cause_counts": cause_counts,
        "n": n,
        "n_with_mr_bands": len(action_pairs),
    }


def check_dlmm_lane(
    snapshots: Optional[Sequence[PoolSnapshot]] = None,
    cfg: Optional[Mapping[str, Any]] = None,
    journal_path: Optional[str] = None,
) -> str:
    """Research-only radar hook. Never signs or deploys."""
    assert_research_only()
    enabled = os.environ.get("BANDS_COMPARE_ENABLED", "1").strip().lower()
    if enabled in {"0", "false", "no", "off"}:
        return "DLMM lane disabled (BANDS_COMPARE_ENABLED=0)"

    if snapshots is None:
        snapshots = _load_optional_snapshots()
    if not snapshots:
        return "DLMM lane idle (no pool snapshots; research-only, no live deployment)"

    # Score only the latest timestamp slice.
    latest = max(s.timestamp for s in snapshots)
    slice_ = [s for s in snapshots if s.timestamp == latest]
    rows = compare_cohort(slice_, cfg=cfg)
    path = journal_path or os.environ.get("BANDS_COMPARE_JOURNAL") or default_journal_path()
    append_rows(rows, path=path)
    top = rows[0] if rows else None
    if not top:
        return "DLMM lane scored 0 pools"
    return (
        f"scored {len(rows)} pools; top={top.pool} score={top.our_opportunity_score:.3f} "
        f"action={top.actual_action} (research-only, unsigned)"
    )


def _load_optional_snapshots() -> List[PoolSnapshot]:
    import json

    env_path = os.environ.get("BANDS_COMPARE_SNAPSHOTS")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [env_path, os.path.join(root, "fixtures", "dlmm_snapshots.json")]
    for path in candidates:
        if not path or not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        items = raw.get("snapshots", raw) if isinstance(raw, dict) else raw
        return [PoolSnapshot.from_dict(x) for x in items]
    return []
