# Bands comparison baseline

Independent DLMM LP research lane. **Not** a clone of Mr Bands private coefficients.
Simulation only: no real funds, no signed transactions, no live deployment.
The harness 40/30/30 capital mix is **not** the pool opportunity score.

## Baseline metrics

- Rank correlation vs public Mr Bands stub: `0.7746`
- Action agreement: `0.2583`
- HOLD agreement: `0.2489`
- False-action / churn rate: `0.0958`
- Pool-selection overlap: `0.6250`
- Subsequent fee/TVL (mean): `0.2900`
- Subsequent inventory drawdown (mean): `0.0119`
- Mean net return after estimated execution costs: `0.3275`
- Terminal simulated equity: `861.05`
- Max drawdown: `0.1424`
- Score vs subsequent net return (Spearman): `0.4921`

## 1. Which inputs explain most disagreement with Mr Bands?

Disagreement is attributed, not minimized. Public stub is fee/TVL-heavy with a low OPEN threshold and almost no cost drag.

- `different_normalization`: 186 rows
- `different_weight`: 186 rows
- `different_objective`: 149 rows
- `different_guard`: 97 rows
- `different_cost_assumption`: 73 rows
- `different_feature`: 24 rows
- `different_action_threshold`: 11 rows

Most disagreement is expected from **different weight** (we spread 35/20/15/15/15 vs a ~70/30 fee-volume public stub),
**different cost assumption** (HOLD-first vs cost-blind OPEN), and **different guard** (band width, abnormal move, reserve).

## 2. Does changing weights actually improve economic results?

- Baseline terminal equity: `861.05`
- Best economic variant: `liquidity_depth_quality-0.10` at `991.94`
- Best rank-correlation variant: `liquidity_depth_quality-0.10`
- Public-observer-matching 70/30 equity: `865.11`
- Changing weights improved economics vs baseline: **True**

Matching the public stub's numerical mix is not the same as improving net return after inventory/rent/tx costs.

## 3. Does HOLD-first policy reduce churn?

- HOLD-first recommended (pre-guard) churn: `0.5250`
- Aggressive recommended (pre-guard) churn: `0.8500`
- HOLD-first actual (post-guard) churn: `0.0958` equity `861.05`
- Aggressive actual (post-guard) churn: `0.0958` equity `861.05`
- HOLD-first reduces churn: **True**

## 4. Which guard rules prevent the largest losses?

Ablation uses an eager policy (low OPEN threshold, no cost-advantage HOLD) so guards are the last line of authority.
Single-guard leave-one-out is often flat when remaining rules still block the same pool; a combo row tests that overlap.

Baseline guard hit counts (vetoes, not equity): `max_allocation_per_position`=92, `max_actions_per_day`=85, `max_band_width`=49, `max_allowed_slippage`=43, `wash_volume_veto`=39, `cooldown`=9, `stop_loss`=4

- `stop_loss`: equity lost when disabled `25.05`, extra drawdown `0.0259`
- `cooldown_seconds`: equity lost when disabled `3.21`, extra drawdown `0.0103`
- `max_allocation_per_position`: equity lost when disabled `0.00`, extra drawdown `0.0000`
- `max_aggregate_exposure`: equity lost when disabled `0.00`, extra drawdown `0.0000`
- `minimum_reserve`: equity lost when disabled `0.00`, extra drawdown `0.0000`
- `max_band_width`: equity lost when disabled `0.00`, extra drawdown `0.0000`
- `max_actions_per_day`: equity lost when disabled `0.00`, extra drawdown `0.0000`
- `max_concurrent_pools`: equity lost when disabled `0.00`, extra drawdown `0.0000`
- `max_allowed_slippage`: equity lost when disabled `0.00`, extra drawdown `0.0000`
- `abnormal_price_move_veto`: equity lost when disabled `0.00`, extra drawdown `0.0000`
- `kill_switch`: equity lost when disabled `0.00`, extra drawdown `0.0000`
- `wash_volume_veto`: equity lost when disabled `0.00`, extra drawdown `0.0000`
- `combo:band_width+slippage+abnormal_move`: equity lost when disabled `0.00`, extra drawdown `0.0000`
- `combo:caps+liquidity+abnormal (spray)`: equity lost when disabled `-95.39`, extra drawdown `-0.0239`

Largest economic backstop in this simulation: **`stop_loss`** (equity lost when disabled `25.05`).

## 5. Which weights are robust across multiple pools?

Spread is (max-min terminal equity of ± perturbations) / baseline equity. Lower is more robust.

- `fee_tvl_quality`: equity spread `0.000`, mean equity `861.05`
- `volume_tvl_persistence`: equity spread `0.000`, mean equity `861.05`
- `in_range_stability`: equity spread `0.000`, mean equity `861.05`
- `liquidity_depth_quality`: equity spread `0.152`, mean equity `893.77`
- `cost_adjusted_expected_return`: equity spread `0.152`, mean equity `893.77`

## 6. Is our score predictive of fee income AFTER inventory/rent/transaction costs?

- Spearman(score, subsequent net return after costs): `0.4921`

A positive rank correlation means higher opportunity scores lined up with better cost-adjusted outcomes on this simulated tape.
A near-zero or negative value means the score is not yet a reliable after-cost predictor and should not be traded.

## Next evidence-backed change

See `reports/experiment_active_tvl.md` for the latest held-out ship gate
(tight wash veto; active TVL remains off). Do not re-enable `use_active_tvl` on this tape.

