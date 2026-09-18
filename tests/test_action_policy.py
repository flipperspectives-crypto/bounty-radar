"""Tests for HOLD/OPEN/MOVE/CLAIM/CLOSE policy, independent of guards."""

from __future__ import annotations

import unittest

from bands_compare.action_policy import recommend_action
from bands_compare.opportunity_score import score_opportunity
from bands_compare.pool_features import derive_features
from bands_compare.schemas import PositionState, PoolSnapshot, mapping_to_dict, load_config


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
        realized_volatility=0.025,
        recent_price_change=0.005,
        liquidity_depth_near_price=500_000.0,
        band_lower_price=97.0,
        band_upper_price=103.0,
        bin_step=10.0,
        out_of_range_hours=0.0,
        time_in_range_frac=0.92,
        inventory_exposure=0.4,
        current_open_exposure=0.0,
        accumulated_fees=0.0,
        observed_at_unix=1.0,
        now_unix=2.0,
        volume_avg_7d=5_800_000.0,
    )
    base.update(overrides)
    return PoolSnapshot.from_dict(base)


def _pos(**overrides) -> PositionState:
    base = dict(
        pool="SOL-USDC",
        size_usd=150.0,
        entry_price=100.0,
        band_lower_price=97.0,
        band_upper_price=103.0,
        accumulated_fees=0.0,
    )
    base.update(overrides)
    return PositionState(**base)


class TestActionPolicy(unittest.TestCase):
    def setUp(self):
        self.cfg = mapping_to_dict(load_config())

    def _score(self, snap):
        feat = derive_features(snap, self.cfg)
        br = score_opportunity(feat, self.cfg)
        return feat, br

    def test_hold_is_default_when_flat_and_mediocre(self):
        feat, br = self._score(_snap(fees_24h=2_000.0, volume_24h=50_000.0, tvl=2_000_000.0))
        proposal = recommend_action(feat, br, None, self.cfg)
        self.assertEqual(proposal.action, "HOLD")
        self.assertIn("default", proposal.reason.lower())

    def test_open_requires_threshold_and_cost_advantage(self):
        feat, br = self._score(_snap())
        self.assertGreaterEqual(br.score, self.cfg["action_policy"]["open_score_threshold"])
        proposal = recommend_action(feat, br, None, self.cfg)
        self.assertEqual(proposal.action, "OPEN")

        costly = mapping_to_dict(self.cfg)
        costly["costs"]["open_usd"] = 1_000_000.0
        costly["action_policy"]["hold_cost_advantage_min"] = 1.25
        hold = recommend_action(feat, br, None, costly)
        self.assertEqual(hold.action, "HOLD")
        self.assertIn("cost", hold.reason.lower())

    def test_open_rejected_below_threshold(self):
        feat, br = self._score(_snap(fees_24h=500.0, volume_24h=20_000.0, realized_volatility=0.2))
        self.assertLess(br.score, self.cfg["action_policy"]["open_score_threshold"])
        proposal = recommend_action(feat, br, None, self.cfg)
        self.assertEqual(proposal.action, "HOLD")

    def test_move_only_when_materially_oor_and_still_attractive(self):
        in_range, br_in = self._score(_snap())
        pos = _pos()
        hold = recommend_action(in_range, br_in, pos, self.cfg)
        self.assertEqual(hold.action, "HOLD")

        oor_snap = _snap(
            price=80.0,
            band_lower_price=97.0,
            band_upper_price=103.0,
            out_of_range_hours=4.0,
            time_in_range_frac=0.2,
        )
        feat, br = self._score(oor_snap)
        move = recommend_action(feat, br, pos, self.cfg)
        self.assertIn(move.action, {"MOVE", "CLOSE"})

        ugly = mapping_to_dict(self.cfg)
        ugly["action_policy"]["move_min_score"] = 0.99
        ugly["action_policy"]["close_score_threshold"] = 0.0
        ugly["action_policy"]["close_oor_hours"] = 99.0
        not_move = recommend_action(feat, br, pos, ugly)
        self.assertEqual(not_move.action, "HOLD")

    def test_claim_only_when_fees_exceed_multiple_of_cost(self):
        feat, br = self._score(_snap())
        low = recommend_action(feat, br, _pos(accumulated_fees=0.01), self.cfg)
        self.assertEqual(low.action, "HOLD")
        high = recommend_action(feat, br, _pos(accumulated_fees=5.0), self.cfg)
        self.assertEqual(high.action, "CLAIM")

    def test_close_when_economics_deteriorate(self):
        feat, br = self._score(
            _snap(
                fees_24h=50.0,
                volume_24h=1_000.0,
                realized_volatility=0.2,
                recent_price_change=0.3,
                out_of_range_hours=20.0,
                price=70.0,
                band_lower_price=97.0,
                band_upper_price=103.0,
            )
        )
        proposal = recommend_action(feat, br, _pos(), self.cfg)
        self.assertEqual(proposal.action, "CLOSE")

    def test_hold_when_reposition_benefit_does_not_beat_cost(self):
        feat, br = self._score(
            _snap(
                price=96.5,
                band_lower_price=97.0,
                band_upper_price=103.0,
                out_of_range_hours=1.2,
                fees_24h=200.0,
                tvl=2_000_000.0,
            )
        )
        costly = mapping_to_dict(self.cfg)
        costly["costs"]["rebalance_usd"] = 50_000.0
        costly["action_policy"]["close_score_threshold"] = 0.0
        costly["action_policy"]["close_oor_hours"] = 99.0
        proposal = recommend_action(feat, br, _pos(), costly)
        self.assertEqual(proposal.action, "HOLD")


if __name__ == "__main__":
    unittest.main()
