# Claude Code prompt: integrate the failure predictor (paste everything below)

You are integrating a trained early-warning failure predictor into the CubeSat swarm sim. Work in phase gates. After each gate, STOP and show me the diff plus the command output. Do not start the next phase until I say go. Prefer diffs over prose. Verify claims by running code, not by assuming.

## Inputs (already produced, treat as frozen)
- `predictor_pipeline.py`: synthetic telemetry generator, features, EWMA/CUSUM baselines, LightGBM training and eval. **DO NOT EDIT IT.** `out2/test_manifest.json` stores its sha256 and `run` refuses if the file changes.
- `predictor_holdout.py`: family-holdout test; imports the pipeline unchanged.
- `out2/predictor.txt`, `out2/predictor_manifest.json` (tau_lgb, feature names, K_ALARM=3, STRIDE=10, model sha256), `out2/results.json`, `out2/test_manifest.json`.

## Known facts you must respect
- The model beats EWMA/CUSUM by about 260 s median lead on failure families it was trained on (EPS-fade, comms), at matched false-alarm rate. It does NOT generalize to unseen families (comms-holdout: 0/15). Sudden death is about 0 recall. Never write README text that implies otherwise.
- The score is an uncalibrated LightGBM probability (is_unbalance=True; tau is about 0.026). A risk margin of 0.1 or 0.2 in probability space will probably never fire.
- The pipeline generates its OWN failure schedules (`gen_run`). The sim has its own scheduled failures, so telemetry must be re-synthesized from the sim's schedule.
- Features are past-only; I verified that corrupting the future leaves earlier rows identical. Reproduce that check on whatever path you build.
- Constants in the pipeline: DT=2 s, T_TICKS=5400, STRIDE=10, WARM=300, 6 sats, 6 channels (volt, soc, duty, lat, jit, temp), eclipse nominal model removed before features.

## Phase 0: placement (no sim changes)
1. `uv add lightgbm numpy scipy`. Copy the frozen files into the repo (suggested: `predictor/` for the .py files, `models/` for predictor.txt and manifests). Do not modify them.
2. Add a test that the sha256 of `predictor.txt` equals `model_sha256` in `predictor_manifest.json`. CI verifies the hash and never retrains.
3. Run `python predictor/predictor_pipeline.py run --out out2` and confirm the numbers match `out2/results.json`. This checks reproducibility on this machine; if they differ, report it, don't fix it.
**Gate 0:** show test output and the reproducibility diff.

## Phase 1: runtime scoring module (new file `predictor/runtime.py`; offline, zero sim diff)
1. `telemetry_from_schedule(scenario, seed)`: synthesize the 6 channels per sat for the sim's actual failure schedule. Reuse the pipeline's channel logic (copy it; do not edit the original) and overlay EPS-fade / comms ramps on scheduled failures using the profile-A parameters. Sudden failures get no precursor. Add a parity test comparing channel statistics against `gen_run` (means and stds within tolerance).
2. `score_run(telemetry)`: call `features()` and the saved model, return risk per sat per scored tick (every STRIDE ticks, from WARM). Only use a score at tick t if its tick <= current sim tick. Add the future-corruption test.
3. SUSPECT rule: score >= tau_lgb for K_ALARM consecutive scored rows. Emit a `PREDICTOR_ALERT` event.
4. If the sim's tick length or run length differs from DT=2 s / 5400 ticks, report it. Do not silently resample.
**Gate 1:** show a script that scores `two_failure` offline, with SUSPECT times next to the true t_f for each failing sat.

## Phase 2: oracle sweep first (the kill switch; offline or gated)
Run the oracle value-of-warning sweep described in `ORACLE_SWEEP.md`, or ask me for it. Metric is critical-seat health fraction; L in {0, 30, 60, 300, 1800} s capped at t_f - t_settle. If the gain at L=300 s is under my pre-declared threshold on every scenario, STOP and recommend cutting the predictor. Do not proceed to Phase 3.
**Gate 2:** show the gain-vs-L table.

## Phase 3: in-loop hook (only if Gate 2 passes)
1. ONE gated branch (~15 lines) in `sim.py` between steps, behind a defaulted `predictor` block in the scenario JSON. Unreachable and byte-inert when absent; prove it with `test_predictor_disabled_bytes_identical` against the committed canonical logs.
2. Behavior: call the standard `replan`, then ONE deterministic post-assignment swap: if a critical seat's holder is SUSPECT and a NOMINAL, non-suspect survivor exists, swap to the lowest-risk such survivor (ties: lowest sat id). Log the swap as its own event.
3. **This changes a locked decision.** ENDGAME_PLAN section 7 pins the swap on a risk MARGIN swept from {0.0, 0.1, 0.2}, but the scores are uncalibrated probabilities, so a margin may never fire. I am proposing the binary SUSPECT trigger instead. Do not swap silently: show me a dev-scenario sweep of both rules and let me choose.
4. Report Delta-v per false alarm, and keep total false-alarm Delta-v at or below 10% of measured recovery Delta-v. If it breaks the budget, raise tau (re-calibrate on the cal set), do not weaken the budget.
**Gate 3:** byte-identity test green, then the second delta (predictor+reactive vs reactive-only) on at least 3 new predictor-family scenarios with committed logs and exact commands. A negative or zero delta means ship reactive-only and say so.

## Phase 4: honesty pass (README)
State plainly: synthetic telemetry written by our own generator; lead gain about 4 min on trained families only; no generalization to unseen families (cite predictor_holdout.py output); sudden death not predictable; in-sim delta as measured. If Gate 2 or 3 failed, the line is "predictor was not built / not shipped."

## Rules
- Never edit the frozen pipeline file. Never retrain in CI. Never tune thresholds on test seeds (9500-9559).
- No new dependencies beyond lightgbm, numpy, scipy.
- If anything here conflicts with ENDGAME_PLAN, say so explicitly and ask before choosing.
