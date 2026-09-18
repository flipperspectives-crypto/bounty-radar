# Bands comparison held-out (seed 97, rug + wash)

Independent DLMM LP research lane. **Not** a clone of Mr Bands private coefficients.
Simulation only: no real funds, no signed transactions, no live deployment.
The harness 40/30/30 capital mix is **not** the pool opportunity score.

## Baseline metrics

- Rank correlation vs public Mr Bands stub: `0.7560`
- Action agreement: `0.2583`
- HOLD agreement: `0.2521`
- False-action / churn rate: `0.1500`
- Pool-selection overlap: `0.6250`
- Subsequent fee/TVL (mean): `0.3101`
- Subsequent inventory drawdown (mean): `0.0120`
- Mean net return after estimated execution costs: `0.3501`
- Terminal simulated equity: `1009.85`
- Max drawdown: `0.0155`
- Score vs subsequent net return (Spearman): `0.4753`

## 1. Which inputs explain most disagreement with Mr Bands?

Disagreement is attributed, not minimized. Public stub is fee/TVL-heavy with a low OPEN threshold and almost no cost drag.

- `different_weight`: 182 rows
- `different_normalization`: 181 rows
- `different_objective`: 136 rows
- `different_guard`: 89 rows
- `different_cost_assumption`: 81 rows
- `different_feature`: 24 rows
- `different_action_threshold`: 13 rows

Most disagreement is expected from **different weight** (we spread 35/20/15/15/15 vs a ~70/30 fee-volume public stub),
**different cost assumption** (HOLD-first vs cost-blind OPEN), and **different guard** (band width, abnormal move, reserve).

## 2. Does changing weights actually improve economic results?

- Baseline terminal equity: `1009.85`
- Best economic variant: `baseline` at `1009.85`
- Best rank-correlation variant: `liquidity_depth_quality-0.10`
- Public-observer-matching 70/30 equity: `1009.85`
- Changing weights improved economics vs baseline: **False**

Matching the public stub's numerical mix is not the same as improving net return after inventory/rent/tx costs.

## 3. Does HOLD-first policy reduce churn?

- HOLD-first recommended (pre-guard) churn: `0.5458`
- Aggressive recommended (pre-guard) churn: `0.8500`
- HOLD-first actual (post-guard) churn: `0.1500` equity `1009.85`
- Aggressive actual (post-guard) churn: `0.1500` equity `1009.85`
- HOLD-first reduces churn: **True**

## 4. Which guard rules prevent the largest losses?

Ablation uses an eager policy (low OPEN threshold, no cost-advantage HOLD) so guards are the last line of authority.
Single-guard leave-one-out is often flat when remaining rules still block the same pool; a combo row tests that overlap.

Baseline guard hit counts (vetoes, not equity): `max_actions_per_day`=67, `max_band_width`=55, `max_allowed_slippage`=47, `wash_volume_veto`=40, `max_allocation_per_position`=15, `cooldown`=8, `stop_loss`=4, `abnormal_price_move_veto`=1

- `cooldown_seconds`: equity lost when disabled `153.90`, extra drawdown `0.1345`
- `combo:caps+liquidity+abnormal (spray)`: equity lost when disabled `130.90`, extra drawdown `0.1587`
- `max_allocation_per_position`: equity lost when disabled `16.77`, extra drawdown `0.0142`
- `stop_loss`: equity lost when disabled `6.05`, extra drawdown `0.0181`
- `max_actions_per_day`: equity lost when disabled `1.14`, extra drawdown `0.0000`
- `max_aggregate_exposure`: equity lost when disabled `0.00`, extra drawdown `0.0000`
- `minimum_reserve`: equity lost when disabled `0.00`, extra drawdown `0.0000`
- `max_band_width`: equity lost when disabled `0.00`, extra drawdown `0.0000`
- `max_concurrent_pools`: equity lost when disabled `0.00`, extra drawdown `0.0000`
- `max_allowed_slippage`: equity lost when disabled `0.00`, extra drawdown `0.0000`
- `abnormal_price_move_veto`: equity lost when disabled `0.00`, extra drawdown `0.0000`
- `kill_switch`: equity lost when disabled `0.00`, extra drawdown `0.0000`
- `wash_volume_veto`: equity lost when disabled `0.00`, extra drawdown `0.0000`
- `combo:band_width+slippage+abnormal_move`: equity lost when disabled `0.00`, extra drawdown `0.0000`

Largest economic backstop in this simulation: **`cooldown_seconds`** (equity lost when disabled `153.90`).

## 5. Which weights are robust across multiple pools?

Spread is (max-min terminal equity of ± perturbations) / baseline equity. Lower is more robust.

- `fee_tvl_quality`: equity spread `0.000`, mean equity `1009.85`
- `in_range_stability`: equity spread `0.000`, mean equity `1009.85`
- `volume_tvl_persistence`: equity spread `0.025`, mean equity `997.25`
- `cost_adjusted_expected_return`: equity spread `0.026`, mean equity `997.35`
- `liquidity_depth_quality`: equity spread `0.125`, mean equity `961.48`

## 6. Is our score predictive of fee income AFTER inventory/rent/transaction costs?

- Spearman(score, subsequent net return after costs): `0.4753`

A positive rank correlation means higher opportunity scores lined up with better cost-adjusted outcomes on this simulated tape.
A near-zero or negative value means the score is not yet a reliable after-cost predictor and should not be traded.

## Next evidence-backed change

See `reports/experiment_active_tvl.md` for the latest held-out ship gate
(tight wash veto; active TVL remains off). Do not re-enable `use_active_tvl` on this tape.

