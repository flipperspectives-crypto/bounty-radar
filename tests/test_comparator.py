"""Comparator journal, metrics, disagreement causes, and research-only harness."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bands_compare.comparator import (
    classify_disagreement,
    compare_cohort,
    compute_metrics,
    spearman_rank,
)
from bands_compare.journal import JOURNAL_FIELDS, append_row, read_rows, validate_row
from bands_compare.schemas import JournalRow, MrBandsObservation, assert_research_only
from bands_compare.simulate import (
    capital_allocation_score,
    decide_ship,
    generate_snapshots,
    run_backtest,
)


class TestComparator(unittest.TestCase):
    def test_journal_row_schema(self):
        row = JournalRow(
            timestamp="2026-09-18T00:00:00Z",
            pool="SOL-USDC",
            our_opportunity_score=0.71,
            our_rank=1,
            features_used=["fee_tvl_quality"],
            recommended_action="OPEN",
            guard_result={"passed": True, "tripped": [], "actual_action": "OPEN"},
            actual_action="OPEN",
            reason="score passed",
            mr_bands_score=0.80,
            mr_bands_rank=1,
            mr_bands_action="OPEN",
        )
        payload = validate_row(row.to_dict())
        for field in JOURNAL_FIELDS:
            self.assertIn(field, payload)

    def test_journal_roundtrip(self):
        row = JournalRow(
            timestamp="t",
            pool="P",
            our_opportunity_score=0.2,
            our_rank=3,
            features_used=["x"],
            recommended_action="HOLD",
            guard_result={"passed": True, "tripped": []},
            actual_action="HOLD",
            reason="default",
        )
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "journal.jsonl")
            append_row(row, path)
            rows = read_rows(path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["pool"], "P")
            self.assertEqual(rows[0]["actual_action"], "HOLD")

    def test_spearman_perfect_and_inverse(self):
        self.assertAlmostEqual(spearman_rank([1, 2, 3], [10, 20, 30]), 1.0)
        self.assertAlmostEqual(spearman_rank([1, 2, 3], [30, 20, 10]), -1.0)

    def test_compare_cohort_produces_ranks_and_optional_mr_bands(self):
        snaps = [s for s in generate_snapshots() if s.timestamp.endswith("T00:00:00Z")]
        observations = [
            MrBandsObservation(pool=s.pool, timestamp=s.timestamp, mr_bands_score=0.1 * i, mr_bands_action="HOLD")
            for i, s in enumerate(snaps)
        ]
        rows = compare_cohort(snaps, observations=observations)
        self.assertGreaterEqual(len(rows), 2)
        ranks = sorted(r.our_rank for r in rows)
        self.assertEqual(ranks[0], 1)
        self.assertTrue(all(r.mr_bands_score is not None for r in rows))
        self.assertTrue(all(r.actual_action in {"HOLD", "OPEN", "MOVE", "CLAIM", "CLOSE"} for r in rows))

    def test_metrics_include_required_comparisons(self):
        snaps = generate_snapshots()
        result = run_backtest(snaps)
        metrics = result["metrics"]
        for key in (
            "rank_correlation",
            "action_agreement",
            "hold_agreement",
            "false_action_churn_rate",
            "pool_selection_overlap",
            "subsequent_fee_tvl_performance",
            "subsequent_inventory_drawdown",
            "net_return_after_estimated_execution_costs",
        ):
            self.assertIn(key, metrics)

    def test_disagreement_causes_are_labeled_not_score_matched(self):
        causes = classify_disagreement(
            our_score=0.70,
            mr_score=0.90,
            our_action="HOLD",
            mr_action="OPEN",
            our_rank=3,
            mr_rank=1,
            fee_tvl_component=0.4,
            guard_tripped=["max_band_width"],
            reason="HOLD: expected benefit does not exceed estimated cost",
            stale=False,
            our_top_feature="cost_adjusted_expected_return",
        )
        self.assertTrue(set(causes) <= {
            "different_objective",
            "different_normalization",
            "different_feature",
            "different_weight",
            "different_action_threshold",
            "different_guard",
            "different_cost_assumption",
        })
        self.assertIn("different_guard", causes)
        self.assertIn("different_cost_assumption", causes)

    def test_capital_score_is_not_pool_score(self):
        cap = capital_allocation_score(liquidity=100, volume=100, fees=100)
        self.assertAlmostEqual(cap, 100.0)
        snaps = [s for s in generate_snapshots() if s.timestamp.endswith("T00:00:00Z")]
        rows = compare_cohort(snaps)
        for row in rows:
            self.assertNotAlmostEqual(row.our_opportunity_score, cap)

    def test_live_trading_flag_is_rejected(self):
        with mock.patch.dict(os.environ, {"BANDS_COMPARE_LIVE": "1"}):
            with self.assertRaises(RuntimeError):
                assert_research_only()

    def test_package_does_not_import_market_sentinel(self):
        root = Path(__file__).resolve().parents[1] / "bands_compare"
        for path in root.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("import market_sentinel", text)
            self.assertNotIn("from market_sentinel", text)

    def test_sentinel_directional_logic_untouched(self):
        import market_sentinel

        self.assertEqual(market_sentinel.OVERSOLD_THRESHOLD, 99.20)
        self.assertEqual(market_sentinel.BREAKOUT_THRESHOLD, 101.10)
        zone, _ = market_sentinel.evaluate_market_condition(99.00)
        self.assertEqual(zone, "OVERSOLD_BOUNCE")

    def test_rug_and_wash_pools_exist_on_tape(self):
        snaps = generate_snapshots(seed=13)
        pools = {s.pool for s in snaps}
        self.assertIn("RUG-SOL", pools)
        self.assertIn("WASH-SOL", pools)
        rug = [s for s in snaps if s.pool == "RUG-SOL"]
        rug.sort(key=lambda s: s.timestamp)
        early = rug[0].price
        late = rug[-1].price
        self.assertLess(late / early, 0.4)

    def test_held_out_seed_differs_from_in_sample(self):
        a = generate_snapshots(seed=13)
        b = generate_snapshots(seed=97)
        self.assertNotEqual(
            [(s.pool, round(s.price, 8), round(s.volume_24h, 2)) for s in a[:10]],
            [(s.pool, round(s.price, 8), round(s.volume_24h, 2)) for s in b[:10]],
        )

    def test_ship_gate_requires_heldout_equity_spearman_and_churn_cap(self):
        self.assertTrue(
            decide_ship(
                control_equity=1000.0,
                treatment_equity=1010.0,
                control_spearman=0.40,
                treatment_spearman=0.50,
                treatment_recommended_churn=0.40,
                churn_cap=0.46,
            )
        )
        self.assertFalse(
            decide_ship(
                control_equity=1000.0,
                treatment_equity=990.0,
                control_spearman=0.40,
                treatment_spearman=0.50,
                treatment_recommended_churn=0.40,
                churn_cap=0.46,
            )
        )
        self.assertFalse(
            decide_ship(
                control_equity=1000.0,
                treatment_equity=1010.0,
                control_spearman=0.40,
                treatment_spearman=0.50,
                treatment_recommended_churn=0.80,
                churn_cap=0.46,
            )
        )

    def test_hold_first_reduces_churn_vs_always_act(self):
        snaps = generate_snapshots()
        baseline = run_backtest(snaps)
        aggressive = run_backtest(snaps, policy_overrides={"hold_cost_advantage_min": 0.0, "open_score_threshold": 0.20})
        self.assertLessEqual(
            baseline["metrics"]["false_action_churn_rate"],
            aggressive["metrics"]["false_action_churn_rate"] + 1e-12,
        )


if __name__ == "__main__":
    unittest.main()
