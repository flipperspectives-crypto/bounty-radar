"""Tests for DLMM pool feature derivation."""

from __future__ import annotations

import unittest

from bands_compare.pool_features import derive_features, required_feature_names
from bands_compare.schemas import FEATURE_NAMES, PoolSnapshot, load_config


def _snap(**overrides) -> PoolSnapshot:
    base = dict(
        pool="SOL-USDC",
        timestamp="2026-09-18T00:00:00Z",
        volume_24h=4_000_000.0,
        tvl=1_000_000.0,
        fee_rate=0.0025,
        fees_24h=10_000.0,
        price=100.0,
        current_active_bin=1000,
        prev_active_bin=996,
        realized_volatility=0.04,
        recent_price_change=0.02,
        liquidity_depth_near_price=200_000.0,
        band_lower_bin=980,
        band_upper_bin=1020,
        band_lower_price=95.0,
        band_upper_price=105.0,
        bin_step=10.0,
        out_of_range_hours=0.0,
        time_in_range_frac=0.85,
        inventory_exposure=0.45,
        current_open_exposure=150.0,
        observed_at_unix=1_000_000.0,
        now_unix=1_000_100.0,
    )
    base.update(overrides)
    return PoolSnapshot.from_dict(base)


class TestPoolFeatures(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config()

    def test_required_feature_vector_matches_spec(self):
        self.assertEqual(required_feature_names(), FEATURE_NAMES)
        self.assertEqual(len(FEATURE_NAMES), 19)

    def test_derived_ratios(self):
        feat = derive_features(_snap(), self.cfg)
        self.assertAlmostEqual(feat.fee_tvl, 0.01)
        self.assertAlmostEqual(feat.volume_tvl, 4.0)
        self.assertEqual(feat.volume_24h, 4_000_000.0)
        self.assertEqual(feat.tvl, 1_000_000.0)
        self.assertEqual(feat.fee_rate, 0.0025)
        self.assertEqual(feat.current_active_bin, 1000)
        self.assertEqual(feat.recent_active_bin_movement, 4)
        self.assertAlmostEqual(feat.recent_price_change, 0.02)
        self.assertAlmostEqual(feat.realized_volatility, 0.04)
        self.assertAlmostEqual(feat.liquidity_depth_around_price, 200_000.0)
        self.assertGreater(feat.estimated_band_width, 0.0)
        self.assertGreater(feat.estimated_percent_price_coverage, 0.0)
        self.assertGreater(feat.estimated_time_in_range, 0.0)
        self.assertGreater(feat.expected_fees, 0.0)
        self.assertGreater(feat.transaction_rent_rebalance_cost, 0.0)
        self.assertAlmostEqual(feat.inventory_exposure, 0.45)
        self.assertGreater(feat.distance_from_band_edge, 0.0)
        self.assertEqual(feat.out_of_range_duration, 0.0)
        self.assertEqual(feat.current_open_exposure, 150.0)
        public = feat.as_public_dict()
        for name in FEATURE_NAMES:
            self.assertIn(name, public)

    def test_fees_inferred_from_volume_and_fee_rate(self):
        feat = derive_features(_snap(fees_24h=None, volume_24h=2_000_000.0, fee_rate=0.01), self.cfg)
        self.assertAlmostEqual(feat.fee_tvl, 0.02)

    def test_zero_tvl_does_not_raise(self):
        feat = derive_features(_snap(tvl=0.0, fees_24h=10.0, volume_24h=100.0), self.cfg)
        self.assertEqual(feat.fee_tvl, 0.0)
        self.assertEqual(feat.volume_tvl, 0.0)
        self.assertFalse(feat.in_range is None)

    def test_out_of_range_duration_and_edge_distance(self):
        feat = derive_features(
            _snap(
                price=90.0,
                band_lower_price=95.0,
                band_upper_price=105.0,
                out_of_range_hours=6.0,
                time_in_range_frac=None,
            ),
            self.cfg,
        )
        self.assertFalse(feat.in_range)
        self.assertEqual(feat.out_of_range_duration, 6.0)
        self.assertLess(feat.estimated_time_in_range, 1.0)
        self.assertEqual(feat.distance_from_band_edge, 0.0)

    def test_stale_pool_information(self):
        fresh = derive_features(_snap(observed_at_unix=100.0, now_unix=200.0), self.cfg)
        stale = derive_features(_snap(observed_at_unix=100.0, now_unix=100.0 + 7200.0), self.cfg)
        self.assertFalse(fresh.stale)
        self.assertTrue(stale.stale)

    def test_band_width_from_bin_range(self):
        feat = derive_features(
            _snap(
                band_lower_price=None,
                band_upper_price=None,
                band_lower_bin=0,
                band_upper_bin=100,
                bin_step=10.0,
                price=100.0,
            ),
            self.cfg,
        )
        self.assertGreater(feat.estimated_band_width, 0.05)

    def test_volume_persistence_between_zero_and_one(self):
        feat = derive_features(_snap(volume_24h=4_000_000.0, volume_avg_7d=4_000_000.0), self.cfg)
        self.assertAlmostEqual(feat.volume_persistence, 1.0)
        feat2 = derive_features(_snap(volume_24h=4_000_000.0, volume_avg_7d=1_000_000.0), self.cfg)
        self.assertLess(feat2.volume_persistence, feat.volume_persistence)

    def test_fee_active_tvl_uses_in_range_liquidity(self):
        feat = derive_features(
            _snap(fees_24h=10_000.0, tvl=1_000_000.0, active_tvl=200_000.0),
            self.cfg,
        )
        self.assertAlmostEqual(feat.fee_tvl, 0.01)
        self.assertAlmostEqual(feat.active_tvl, 200_000.0)
        self.assertAlmostEqual(feat.fee_active_tvl, 0.05)
        self.assertGreater(feat.fee_active_tvl, feat.fee_tvl)

    def test_wash_volume_flags_tiny_tvl_and_turnover(self):
        clean = derive_features(_snap(), self.cfg)
        self.assertEqual(clean.wash_reasons, ())
        wash = derive_features(
            _snap(tvl=40_000.0, volume_24h=800_000.0, fee_rate=0.04, fees_24h=32_000.0, active_tvl=5_000.0),
            self.cfg,
        )
        self.assertTrue(wash.wash_reasons)
        self.assertGreater(wash.volume_tvl, 10.0)


if __name__ == "__main__":
    unittest.main()
