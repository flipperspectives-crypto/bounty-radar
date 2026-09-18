"""Tests for the independent opportunity score (not Mr Bands private weights)."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest

from bands_compare.opportunity_score import BASELINE_WEIGHTS, score_opportunity
from bands_compare.pool_features import derive_features
from bands_compare.schemas import PoolSnapshot, load_config, mapping_to_dict, validate_config


def _cfg_with(mutator):
    cfg = mapping_to_dict(load_config())
    mutator(cfg)
    validate_config(cfg)
    return cfg


def _snap(**overrides) -> PoolSnapshot:
    base = dict(
        pool="SOL-USDC",
        timestamp="2026-09-18T00:00:00Z",
        volume_24h=5_000_000.0,
        tvl=1_000_000.0,
        fee_rate=0.01,
        fees_24h=80_000.0,
        price=100.0,
        current_active_bin=1000,
        prev_active_bin=999,
        realized_volatility=0.03,
        recent_price_change=0.01,
        liquidity_depth_near_price=250_000.0,
        band_lower_price=96.0,
        band_upper_price=104.0,
        bin_step=10.0,
        out_of_range_hours=0.0,
        time_in_range_frac=0.9,
        inventory_exposure=0.4,
        current_open_exposure=0.0,
        observed_at_unix=1.0,
        now_unix=2.0,
        volume_avg_7d=4_800_000.0,
    )
    base.update(overrides)
    return PoolSnapshot.from_dict(base)


class TestOpportunityScore(unittest.TestCase):
    def setUp(self):
        self.cfg = mapping_to_dict(load_config())

    def test_baseline_weights_are_explicit_and_sum_to_one(self):
        self.assertEqual(BASELINE_WEIGHTS["fee_tvl_quality"], 0.35)
        self.assertEqual(BASELINE_WEIGHTS["volume_tvl_persistence"], 0.20)
        self.assertEqual(BASELINE_WEIGHTS["liquidity_depth_quality"], 0.15)
        self.assertEqual(BASELINE_WEIGHTS["in_range_stability"], 0.15)
        self.assertEqual(BASELINE_WEIGHTS["cost_adjusted_expected_return"], 0.15)
        self.assertAlmostEqual(sum(BASELINE_WEIGHTS.values()), 1.0)
        loaded = self.cfg["opportunity_weights"]
        for k, v in BASELINE_WEIGHTS.items():
            self.assertAlmostEqual(loaded[k], v)

    def test_note_does_not_claim_private_coefficients(self):
        feat = derive_features(_snap(), self.cfg)
        result = score_opportunity(feat, self.cfg)
        self.assertIn("not Mr Bands private", result.note)

    def test_score_is_unit_interval(self):
        feat = derive_features(_snap(), self.cfg)
        result = score_opportunity(feat, self.cfg)
        self.assertGreaterEqual(result.score, 0.0)
        self.assertLessEqual(result.score, 1.0)

    def test_fee_quality_uses_active_tvl_when_enabled(self):
        cfg = _cfg_with(lambda c: c.setdefault("features", {}).__setitem__("use_active_tvl", True))
        idle = derive_features(_snap(fees_24h=80_000.0, tvl=1_000_000.0, active_tvl=1_000_000.0), cfg)
        concentrated = derive_features(_snap(fees_24h=80_000.0, tvl=1_000_000.0, active_tvl=200_000.0), cfg)
        a = score_opportunity(idle, cfg)
        b = score_opportunity(concentrated, cfg)
        self.assertGreater(b.components["fee_tvl_quality"], a.components["fee_tvl_quality"])
        self.assertIn("fee_active_tvl", b.features_used)

    def test_baseline_weights_unchanged_by_active_tvl_experiment(self):
        self.assertEqual(self.cfg["opportunity_weights"]["fee_tvl_quality"], 0.35)
        self.assertEqual(self.cfg["opportunity_weights"]["volume_tvl_persistence"], 0.20)

    def test_higher_fee_tvl_scores_higher(self):
        low = score_opportunity(derive_features(_snap(fees_24h=5_000.0), self.cfg), self.cfg)
        high = score_opportunity(derive_features(_snap(fees_24h=120_000.0), self.cfg), self.cfg)
        self.assertGreater(high.score, low.score)
        self.assertGreater(high.components["fee_tvl_quality"], low.components["fee_tvl_quality"])

    def test_penalties_reduce_score(self):
        healthy = score_opportunity(derive_features(_snap(), self.cfg), self.cfg)
        volatile = score_opportunity(
            derive_features(_snap(realized_volatility=0.25, recent_price_change=0.30), self.cfg),
            self.cfg,
        )
        thin = score_opportunity(
            derive_features(_snap(liquidity_depth_near_price=1_000.0, tvl=1_000_000.0), self.cfg),
            self.cfg,
        )
        stale = score_opportunity(
            derive_features(_snap(observed_at_unix=1.0, now_unix=10_000.0), self.cfg),
            self.cfg,
        )
        self.assertGreater(healthy.score, volatile.score)
        self.assertGreater(healthy.score, thin.score)
        self.assertGreater(healthy.score, stale.score)
        self.assertIn("extreme_volatility", volatile.penalties)
        self.assertIn("poor_depth", thin.penalties)
        self.assertIn("stale_pool_information", stale.penalties)

    def test_fee_below_rebalance_cost_is_penalized(self):
        cheap_print = score_opportunity(
            derive_features(_snap(fees_24h=1.0, tvl=1_000_000.0, volume_24h=100.0), self.cfg),
            self.cfg,
        )
        self.assertIn("fee_below_cost", cheap_print.penalties)
        self.assertLess(cheap_print.score, 0.5)

    def test_weights_are_configurable_from_one_file(self):
        feat = derive_features(_snap(), self.cfg)
        baseline = score_opportunity(feat, self.cfg)
        shifted = _cfg_with(
            lambda c: c["opportunity_weights"].update(
                {
                    "fee_tvl_quality": 0.05,
                    "volume_tvl_persistence": 0.05,
                    "liquidity_depth_quality": 0.80,
                    "in_range_stability": 0.05,
                    "cost_adjusted_expected_return": 0.05,
                }
            )
        )
        thin = derive_features(_snap(liquidity_depth_near_price=5_000.0), shifted)
        a = score_opportunity(thin, self.cfg)
        b = score_opportunity(thin, shifted)
        self.assertNotAlmostEqual(a.score, b.score)
        self.assertLess(b.score, a.score)

    def test_does_not_use_403030_capital_mix_as_pool_score(self):
        feat = derive_features(_snap(), self.cfg)
        result = score_opportunity(feat, self.cfg)
        # 40/30/30 would be liquidity/volume/fee capital mix — forbidden as pool score.
        self.assertNotIn("capital", result.weights)
        self.assertEqual(set(result.weights), set(BASELINE_WEIGHTS))
        from bands_compare.simulate import capital_allocation_score

        cap = capital_allocation_score(feat.tvl, feat.volume_24h, feat.expected_fees)
        self.assertNotAlmostEqual(cap, result.score)

    def test_config_file_is_the_single_source(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["opportunity_weights"]["fee_tvl_quality"] = 0.55
        cfg["opportunity_weights"]["volume_tvl_persistence"] = 0.15
        cfg["opportunity_weights"]["liquidity_depth_quality"] = 0.10
        cfg["opportunity_weights"]["in_range_stability"] = 0.10
        cfg["opportunity_weights"]["cost_adjusted_expected_return"] = 0.10
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "config.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(cfg, fh)
            loaded = load_config(path)
            self.assertAlmostEqual(loaded["opportunity_weights"]["fee_tvl_quality"], 0.55)


if __name__ == "__main__":
    unittest.main()
