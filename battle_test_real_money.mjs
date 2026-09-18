#!/usr/bin/env node
"use strict";

/**
 * Simulation harness adapter for the DLMM / Mr Bands comparator.
 *
 * SIMULATION ONLY — does not sign transactions, does not use real funds,
 * does not deploy live positions.
 *
 * The historical 40/30/30 capital mix is a harness-only allocation helper.
 * It is NOT the DLMM pool opportunity score (see bands_compare/opportunity_score.py).
 *
 * battle_test_real_money.mjs was not present in this repo; this file is the
 * adapted simulation entrypoint requested by the comparator directive.
 */

const { spawnSync } = require("child_process");
const path = require("path");

const repoRoot = path.resolve(__dirname);

if (process.env.BANDS_COMPARE_LIVE === "1") {
  console.error("Live trading is forbidden. This harness is simulation-only.");
  process.exit(2);
}

const result = spawnSync(
  "python3",
  ["-m", "bands_compare", "--baseline", "--sensitivity"],
  {
    cwd: repoRoot,
    stdio: "inherit",
    env: { ...process.env, BANDS_COMPARE_LIVE: "0" },
  }
);

process.exit(result.status === null ? 1 : result.status);
