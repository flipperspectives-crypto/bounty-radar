"""Hard guards: code has final authority; runtime/LLM mutation is rejected."""

from __future__ import annotations

import unittest

from bands_compare.action_policy import recommend_action
from bands_compare.guards import GuardEngine
from bands_compare.opportunity_score import score_opportunity
from bands_compare.pool_features import derive_features
from bands_compare.schemas import (
    AccountState,
    ActionProposal,
    PositionState,
    PoolSnapshot,
    load_config,
    mapping_to_dict,
)


def _snap(**overrides) -> PoolSnapshot:
    base = dict(
        pool="SOL-USDC",
        timestamp="2026-09-18T00:00:00Z",
        volume_24h=6_000_000.0,
        tvl=2_000_000.0,
        fee_rate=0.01,
        fees_24h=150_000.0,
        price=100.0,
        current_active_bin=1000,
        prev_active_bin=1000,
        realized_volatility=0.02,
        recent_price_change=0.01,
        liquidity_depth_near_price=400_000.0,
        band_lower_price=97.0,
        band_upper_price=103.0,
        bin_step=10.0,
        out_of_range_hours=0.0,
        time_in_range_frac=0.9,
        inventory_exposure=0.4,
        current_open_exposure=0.0,
        estimated_slippage=0.001,
        observed_at_unix=1.0,
        now_unix=2.0,
        volume_avg_7d=5_500_000.0,
    )
    base.update(overrides)
    return PoolSnapshot.from_dict(base)


class TestGuards(unittest.TestCase):
    def setUp(self):
        self.cfg = mapping_to_dict(load_config())
        self.engine = GuardEngine(self.cfg)
        self.account = AccountState(equity_usd=1000.0, cash_usd=1000.0, peak_equity=1000.0)
        feat = derive_features(_snap(), self.cfg)
        self.feat = feat
        self.score = score_opportunity(feat, self.cfg)

    def test_open_passes_on_healthy_account(self):
        proposal = recommend_action(self.feat, self.score, None, self.cfg)
        self.assertEqual(proposal.action, "OPEN")
        result = self.engine.apply(proposal, self.account, self.feat, now_unix=10_000.0, day_stamp="2026-09-18")
        self.assertTrue(result.passed)
        self.assertEqual(result.actual_action, "OPEN")

    def test_kill_switch_blocks_open_and_move(self):
        cfg = mapping_to_dict(self.cfg)
        cfg["guards"]["kill_switch"] = True
        engine = GuardEngine(cfg)
        opened = engine.apply(
            ActionProposal("OPEN", "test"),
            self.account,
            self.feat,
            now_unix=10.0,
            day_stamp="d",
        )
        self.assertFalse(opened.passed)
        self.assertEqual(opened.actual_action, "HOLD")
        self.assertIn("kill_switch", opened.tripped)
        moved = engine.apply(
            ActionProposal("MOVE", "test"),
            self.account,
            self.feat,
            now_unix=10.0,
            day_stamp="d",
        )
        self.assertEqual(moved.actual_action, "HOLD")
        closed = engine.apply(
            ActionProposal("CLOSE", "test"),
            self.account,
            self.feat,
            now_unix=10.0,
            day_stamp="d",
        )
        self.assertEqual(closed.actual_action, "CLOSE")

    def test_max_allocation_and_reserve_and_aggregate(self):
        poor = AccountState(equity_usd=1000.0, cash_usd=50.0, peak_equity=1000.0)
        result = self.engine.apply(
            ActionProposal("OPEN", "test", expected_benefit_usd=10, estimated_cost_usd=0.3),
            poor,
            self.feat,
            now_unix=10.0,
            day_stamp="d",
            proposed_size_usd=150.0,
        )
        self.assertFalse(result.passed)
        self.assertEqual(result.actual_action, "HOLD")
        self.assertTrue(set(result.tripped) & {"minimum_reserve", "max_allocation_per_position", "max_aggregate_exposure"})

    def test_max_concurrent_pools(self):
        acct = AccountState(equity_usd=1000.0, cash_usd=800.0, peak_equity=1000.0)
        for i in range(4):
            acct.positions[f"P{i}"] = PositionState(
                pool=f"P{i}", size_usd=50.0, entry_price=1.0, band_lower_price=0.9, band_upper_price=1.1
            )
        result = self.engine.apply(
            ActionProposal("OPEN", "test"),
            acct,
            self.feat,
            now_unix=10.0,
            day_stamp="d",
            proposed_size_usd=50.0,
        )
        self.assertIn("max_concurrent_pools", result.tripped)
        self.assertEqual(result.actual_action, "HOLD")

    def test_max_band_width(self):
        wide = derive_features(
            _snap(band_lower_price=50.0, band_upper_price=200.0, price=100.0),
            self.cfg,
        )
        result = self.engine.apply(
            ActionProposal("OPEN", "test"),
            self.account,
            wide,
            now_unix=10.0,
            day_stamp="d",
        )
        self.assertIn("max_band_width", result.tripped)

    def test_max_actions_per_day_and_cooldown(self):
        acct = AccountState(
            equity_usd=1000.0,
            cash_usd=1000.0,
            peak_equity=1000.0,
            actions_today=8,
            day_stamp="2026-09-18",
            last_action_unix=9_000.0,
        )
        result = self.engine.apply(
            ActionProposal("OPEN", "test"),
            acct,
            self.feat,
            now_unix=9_100.0,
            day_stamp="2026-09-18",
        )
        self.assertIn("max_actions_per_day", result.tripped)

        acct2 = AccountState(
            equity_usd=1000.0,
            cash_usd=1000.0,
            peak_equity=1000.0,
            actions_today=1,
            day_stamp="2026-09-18",
            last_action_unix=9_000.0,
        )
        cool = self.engine.apply(
            ActionProposal("MOVE", "test"),
            acct2,
            self.feat,
            now_unix=9_100.0,
            day_stamp="2026-09-18",
        )
        self.assertIn("cooldown", cool.tripped)

    def test_slippage_and_abnormal_move_veto(self):
        slippery = derive_features(_snap(estimated_slippage=0.05), self.cfg)
        slip = self.engine.apply(
            ActionProposal("OPEN", "test"),
            self.account,
            slippery,
            now_unix=10.0,
            day_stamp="d",
        )
        self.assertIn("max_allowed_slippage", slip.tripped)

        moved = derive_features(_snap(recent_price_change=0.35), self.cfg)
        veto = self.engine.apply(
            ActionProposal("OPEN", "test"),
            self.account,
            moved,
            now_unix=10.0,
            day_stamp="d",
        )
        self.assertIn("abnormal_price_move_veto", veto.tripped)

    def test_stop_loss_forces_close(self):
        acct = AccountState(equity_usd=1000.0, cash_usd=850.0, peak_equity=1000.0)
        acct.positions["SOL-USDC"] = PositionState(
            pool="SOL-USDC",
            size_usd=150.0,
            entry_price=100.0,
            band_lower_price=97.0,
            band_upper_price=103.0,
            inventory_pnl=-40.0,
        )
        result = self.engine.apply(
            ActionProposal("HOLD", "still in range"),
            acct,
            self.feat,
            now_unix=10.0,
            day_stamp="d",
        )
        self.assertEqual(result.actual_action, "CLOSE")
        self.assertIn("stop_loss", result.tripped)
        self.assertTrue(result.forced)

    def test_runtime_mutation_is_rejected(self):
        with self.assertRaises(RuntimeError):
            self.engine.kill_switch = True
        with self.assertRaises(RuntimeError):
            self.engine._cfg = {"kill_switch": True}
        with self.assertRaises((TypeError, RuntimeError)):
            self.engine._cfg["kill_switch"] = True  # type: ignore[index]

    def test_hash_mismatch_detected_even_via_object_setattr(self):
        object.__setattr__(self.engine, "_cfg", {"kill_switch": True})
        with self.assertRaises(RuntimeError):
            self.engine.apply(
                ActionProposal("OPEN", "bypass"),
                self.account,
                self.feat,
                now_unix=10.0,
                day_stamp="d",
            )

    def test_policy_cannot_bypass_guards(self):
        """Model may propose OPEN; code still has final authority."""
        cfg = mapping_to_dict(self.cfg)
        cfg["guards"]["kill_switch"] = True
        engine = GuardEngine(cfg)
        proposal = recommend_action(self.feat, self.score, None, self.cfg)
        self.assertEqual(proposal.action, "OPEN")
        result = engine.apply(proposal, self.account, self.feat, now_unix=10.0, day_stamp="d")
        self.assertNotEqual(result.actual_action, "OPEN")
        self.assertEqual(result.actual_action, "HOLD")


if __name__ == "__main__":
    unittest.main()
