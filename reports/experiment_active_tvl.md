# Experiment: fees/active TVL + wash-volume veto

Baseline weights stayed **35/20/15/15/15**. Sentinel untouched. Simulation only.

**Decision: NO-SHIP / REVERT FLAGS**

## Gate (held-out seed 97, rug + wash tape)

- Control equity: `1009.85`
- Treatment equity: `982.72`
- Control Spearman(score, net after costs): `0.4753`
- Treatment Spearman: `0.1716`
- Treatment HOLD-first recommended churn: `0.6417` (cap `0.46`)
- Control max drawdown: `0.0155`
- Treatment max drawdown: `0.0199`
- Treatment wash veto hits: `96`

## In-sample seed 13 (same universe, different RNG path)

- Control equity `861.05` vs treatment `983.68`
- Control Spearman `0.4921` vs treatment `0.2122`

NO-SHIP: revert feature flags. Code paths remain for the next tape.

