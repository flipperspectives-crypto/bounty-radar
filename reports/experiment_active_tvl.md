# Experiment: tight wash-volume veto

Wash fires only on tiny TVL **and** volume/TVL above 10. No fee-rate veto. No large-pool veto.
`use_active_tvl` stays off. Weights stayed **35/20/15/15/15**. Sentinel untouched. Simulation only.

**Decision: SHIP**

## Gate (held-out seed 97, rug + wash tape)

- Control equity: `1009.85`
- Treatment equity: `1009.85`
- Control Spearman(score, net after costs): `0.4753`
- Treatment Spearman: `0.4753`
- Treatment HOLD-first recommended churn: `0.5458` (cap `0.46`)
- Control max drawdown: `0.0155`
- Treatment max drawdown: `0.0155`
- Treatment wash veto hits: `40`

## In-sample seed 13 (same universe, different RNG path)

- Control equity `861.05` vs treatment `861.05`
- Control Spearman `0.4921` vs treatment `0.4921`

SHIP: held-out equity and Spearman both held or improved; HOLD-first recommended churn at or under cap.

