# Bands comparison baseline

Independent DLMM LP research lane. **Not** a clone of Mr Bands private coefficients.
Simulation only: no real funds, no signed transactions, no live deployment.
The harness 40/30/30 capital mix is **not** the pool opportunity score.

## Baseline metrics

- Rank correlation vs public Mr Bands stub: `0.7914`
- Action agreement: `0.2604`
- HOLD agreement: `0.2526`
- False-action / churn rate: `0.1979`
- Pool-selection overlap: `0.6667`
- Subsequent fee/TVL (mean): `0.3702`
- Subsequent inventory drawdown (mean): `0.0086`
- Mean net return after estimated execution costs: `0.3532`
- Terminal simulated equity: `1060.98`
- Max drawdown: `0.0003`
- Score vs subsequent net return (Spearman): `0.5525`

## 1. Which inputs explain most disagreement with Mr Bands?

Disagreement is attributed, not minimized. Public stub is fee/TVL-heavy with a low OPEN threshold and almost no cost drag.

- `different_normalization`: 121 rows
- `different_weight`: 121 rows
- `different_objective`: 97 rows
- `different_cost_assumption`: 92 rows
- `different_guard`: 41 rows
- `different_feature`: 24 rows
- `different_action_threshold`: 12 rows

Most disagreement is expected from **different weight** (we spread 35/20/15/15/15 vs a ~70/30 fee-volume public stub),
**different cost assumption** (HOLD-first vs cost-blind OPEN), and **different guard** (band width, abnormal move, reserve).

## 2. Does changing weights actually improve economic results?

- Baseline terminal equity: `1060.98`
- Best economic variant: `baseline` at `1060.98`
- Best rank-correlation variant: `match_public_fee_tvl_70_30`
- Public-observer-matching 70/30 equity: `1060.98`
- Changing weights improved economics vs baseline: **False**

Matching the public stub's numerical mix is not the same as improving net return after inventory/rent/tx costs.

## 3. Does HOLD-first policy reduce churn?

- HOLD-first recommended (pre-guard) churn: `0.4583`
- Aggressive recommended (pre-guard) churn: `0.8750`
- HOLD-first actual (post-guard) churn: `0.1979` equity `1060.98`
- Aggressive actual (post-guard) churn: `0.1979` equity `1060.98`
- HOLD-first reduces churn: **True**

## 4. Which guard rules prevent the largest losses?

Ablation uses an eager policy (low OPEN threshold, no cost-advantage HOLD) so guards are the last line of authority.
Single-guard leave-one-out is often flat when remaining rules still block the same pool; a combo row tests that overlap.

Baseline guard hit counts (vetoes, not equity): `max_actions_per_day`=31, `max_band_width`=20, `max_allowed_slippage`=16, `cooldown`=9, `max_allocation_per_position`=6, `abnormal_price_move_veto`=1

- `max_allocation_per_position`: equity lost when disabled `0.00`, extra drawdown `0.0000`
- `max_aggregate_exposure`: equity lost when disabled `0.00`, extra drawdown `0.0000`
- `minimum_reserve`: equity lost when disabled `0.00`, extra drawdown `0.0000`
- `max_band_width`: equity lost when disabled `0.00`, extra drawdown `0.0000`
- `max_actions_per_day`: equity lost when disabled `0.00`, extra drawdown `0.0000`
- `max_concurrent_pools`: equity lost when disabled `0.00`, extra drawdown `0.0000`
- `max_allowed_slippage`: equity lost when disabled `0.00`, extra drawdown `0.0000`
- `abnormal_price_move_veto`: equity lost when disabled `0.00`, extra drawdown `0.0000`
- `stop_loss`: equity lost when disabled `0.00`, extra drawdown `0.0000`
- `kill_switch`: equity lost when disabled `0.00`, extra drawdown `0.0000`
- `combo:band_width+slippage+abnormal_move`: equity lost when disabled `0.00`, extra drawdown `0.0000`
- `cooldown_seconds`: equity lost when disabled `-16.01`, extra drawdown `0.0003`
- `combo:caps+liquidity+abnormal (spray)`: equity lost when disabled `-373.64`, extra drawdown `0.0015`

No leave-one-out guard increased losses on this tape: score ranking plus overlapping caps kept capital out of toxic pools.
Read the combo/spray rows and hit counts rather than treating a $0.00 leave-one-out as a winner.

## 5. Which weights are robust across multiple pools?

Spread is (max-min terminal equity of ± perturbations) / baseline equity. Lower is more robust.

- `fee_tvl_quality`: equity spread `0.000`, mean equity `1060.98`
- `in_range_stability`: equity spread `0.000`, mean equity `1060.98`
- `cost_adjusted_expected_return`: equity spread `0.000`, mean equity `1060.98`
- `volume_tvl_persistence`: equity spread `0.020`, mean equity `1055.70`
- `liquidity_depth_quality`: equity spread `0.020`, mean equity `1055.70`

## 6. Is our score predictive of fee income AFTER inventory/rent/transaction costs?

- Spearman(score, subsequent net return after costs): `0.5525`

A positive rank correlation means higher opportunity scores lined up with better cost-adjusted outcomes on this simulated tape.
A near-zero or negative value means the score is not yet a reliable after-cost predictor and should not be traded.

## Next evidence-backed change

Do **not** climb rank correlation with the public stub. Next change should be the weight or guard that improves
`score_predictive_of_net_return` and terminal equity on a held-out snapshot seed, while keeping HOLD-first churn at or below baseline.

