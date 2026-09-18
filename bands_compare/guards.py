"""Deterministic hard guards. The model can propose; code has final authority.

Runtime mutation (including LLM-attempted bypass) is rejected. Guard values
are loaded from the single config file and hashed; apply() refuses a hash
mismatch.
"""

from __future__ import annotations

from typing import Any, List, Mapping, Optional

from .schemas import (
    AccountState,
    ActionProposal,
    GuardResult,
    PoolFeatures,
    config_hash,
    freeze_mapping,
    mapping_to_dict,
)


class GuardEngine:
    """Frozen guard evaluator. Attributes cannot be assigned after init."""

    def __init__(self, cfg: Mapping[str, Any]):
        cfg_dict = mapping_to_dict(cfg)
        guards = cfg_dict.get("guards")
        if not isinstance(guards, dict):
            raise ValueError("config.guards is required")
        object.__setattr__(self, "_cfg", freeze_mapping(guards))
        object.__setattr__(self, "_policy", freeze_mapping(cfg_dict.get("action_policy") or {}))
        object.__setattr__(self, "_origin_hash", config_hash(guards))
        object.__setattr__(self, "_frozen", True)

    def __setattr__(self, name: str, value: Any) -> None:
        raise RuntimeError("Guards cannot be modified at runtime (LLM bypass forbidden)")

    def __delattr__(self, name: str) -> None:
        raise RuntimeError("Guards cannot be modified at runtime (LLM bypass forbidden)")

    def _guards(self) -> Mapping[str, Any]:
        current = config_hash(self._cfg)
        if current != self._origin_hash:
            raise RuntimeError("Guard config hash mismatch; mutation detected")
        return self._cfg

    def apply(
        self,
        proposal: ActionProposal,
        account: AccountState,
        features: PoolFeatures,
        now_unix: float,
        day_stamp: str,
        proposed_size_usd: Optional[float] = None,
    ) -> GuardResult:
        g = self._guards()
        tripped: List[str] = []
        action = proposal.action
        assumed = float(self._policy.get("assumed_position_usd", 150.0) or 150.0)  # type: ignore[arg-type]
        size = float(proposed_size_usd if proposed_size_usd is not None else assumed)
        equity = max(float(account.equity_usd), 1e-9)

        # Stop-loss can force CLOSE even if the model wants HOLD.
        pos = account.positions.get(features.pool)
        if pos and pos.size_usd > 0:
            loss_frac = -float(pos.inventory_pnl) / max(pos.size_usd, 1e-9)
            if loss_frac >= float(g["stop_loss"]):
                tripped.append("stop_loss")
                return GuardResult(
                    passed=False,
                    actual_action="CLOSE",
                    tripped=tripped,
                    forced=True,
                    reason="stop_loss forced CLOSE",
                    config_hash=self._origin_hash,
                )

        if bool(g["kill_switch"]) and action in {"OPEN", "MOVE"}:
            tripped.append("kill_switch")
            return GuardResult(
                passed=False,
                actual_action="HOLD",
                tripped=tripped,
                forced=True,
                reason="kill_switch blocked OPEN/MOVE",
                config_hash=self._origin_hash,
            )

        if action in {"OPEN", "MOVE"}:
            if abs(features.recent_price_change) >= float(g["abnormal_price_move_veto"]):
                tripped.append("abnormal_price_move_veto")
            slippage = float(getattr(features, "estimated_slippage", 0.0) or 0.0)
            if slippage > float(g["max_allowed_slippage"]):
                tripped.append("max_allowed_slippage")

            if features.estimated_band_width > float(g["max_band_width"]):
                tripped.append("max_band_width")

            if day_stamp == account.day_stamp and account.actions_today >= int(g["max_actions_per_day"]):
                tripped.append("max_actions_per_day")

            if account.last_action_unix and (now_unix - account.last_action_unix) < float(g["cooldown_seconds"]):
                if action != "HOLD":
                    tripped.append("cooldown")

            if action == "OPEN":
                concurrent = len(account.positions)
                if features.pool not in account.positions and concurrent >= int(g["max_concurrent_pools"]):
                    tripped.append("max_concurrent_pools")
                alloc_frac = size / equity
                if alloc_frac > float(g["max_allocation_per_position"]) + 1e-12:
                    tripped.append("max_allocation_per_position")
                new_exposure = account.exposure_usd() + size
                if new_exposure / equity > float(g["max_aggregate_exposure"]) + 1e-12:
                    tripped.append("max_aggregate_exposure")
                cash_after = account.cash_usd - size
                if cash_after < float(g["minimum_reserve"]) * equity - 1e-9:
                    tripped.append("minimum_reserve")

        if tripped:
            fallback = "HOLD" if action in {"OPEN", "MOVE", "CLAIM"} else action
            return GuardResult(
                passed=False,
                actual_action=fallback,
                tripped=tripped,
                forced=True,
                reason="guard veto: " + ",".join(tripped),
                config_hash=self._origin_hash,
            )

        return GuardResult(
            passed=True,
            actual_action=action,
            tripped=[],
            forced=False,
            reason="guards passed",
            config_hash=self._origin_hash,
        )
