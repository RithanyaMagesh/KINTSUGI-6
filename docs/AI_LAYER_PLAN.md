# AI Layer Plan — Early-Warning Failure Predictor

**Version:** 1.0
**Date:** 2026-09-29
**Status:** SUPERSEDED in priority order (2026-09-29, later the same day) by `docs/ENDGAME_PLAN.md` — measurement-first P0–P4; the predictor is now cut-first. The AI-layer constraints, design detail, and wire deltas here carry forward into ENDGAME_PLAN §7/§8 unchanged. Read ENDGAME_PLAN first; keep this doc as the predictor-design reference. Original status: approved plan for the predictor work — §1 decision record pre-agreed by the user 2026-09-29; two items remain OPEN user questions (§8): LightGBM dependency approval and sign-off for the one gated sim-core branch (§2.3)
**Clock:** feature freeze 2026-09-30 18:00 IST; P3 decision gate 2026-09-30 ~12:00 IST
**Amends:** `docs/BACKEND_SPEC.md` via the dated additive addendum in §3 (land BEFORE any predictor diff so the G5 implementer is never surprised mid-build)

Grounding: AGENTS.md invariants; GATES.md ledger (every number below cites it); the 2026-09-29 predictor design pass (generator/features/baseline/model recipe + risk register, which produced the LightGBM/NIST/PR-AUC source list in §4.7). Verified this session at HEAD `67189ab`: 43 tests collected (`uv run pytest --collect-only -q` → 43 across 10 files); golden pin green (`uv run pytest tests/test_cli.py::test_run_is_byte_deterministic -q` → `.` `[100%]`); `git ls-files data/logs` → only `.gitkeep`; `rg -n "predictor|PREDICT|lightgbm" docs cubesat GATES.md README.md pyproject.toml uv.lock` → no matches.

## 0. Reading order and scope

- **Scope:** everything the AI layer adds — telemetry generator, features, baseline detectors, model, policy, eval harness, wire deltas. NOT in scope: G5 backend build (docs/BACKEND_SPEC.md v1.0), G6 deploy, G7 README (this doc only fixes §7's honesty language).
- **Reading order for the G5 teammate:** §3 first (wire deltas, all additive), then §2.3 (the one sim-core branch — added by our side, never by G5), then §5 R9/R10.
- **Reading order for the predictor session:** §1 → §6 (time boxes) → §4 (specs) → §5 (risks).
- **Precedence:** AGENTS.md invariants > GATES.md decisions log > this plan > the design-pass recipe. Where this plan and BACKEND_SPEC v1.0 conflict, the §3 addendum resolves it — never fork silently (BACKEND_SPEC §0).

## 1. Decision record (user, 2026-09-29)

1.1 **The AI layer is an early-warning failure predictor.** It scores per-satellite failure risk from synthetic telemetry so the swarm reassigns BEFORE the heartbeat timeout fires. The reactive heartbeat → Hungarian path (G4, GATES.md row 9) stays the authoritative safety net; the predictor never replaces it, only acts earlier when confident.

1.2 **The LLM mission-ops copilot is demoted to optional stretch** — built only with slack after P2. Sketch if built at all: `POST /api/copilot` taking `{question, log_tail?}` and answering from the current run's log; demo uses **pre-cached responses** committed as fixtures (no live LLM call on stage); API key is backend-only (env var, never shipped to the browser); cut FIRST, before OPSSAT-AD, the moment anything slips. Nothing in G5's wire contract depends on it.

1.3 **Headline numbers.** Committed: recovery vs no-recovery = **+4.93 coverage points**, per-sat Δv up to **193.68 m/s** on two_failure (GATES.md rows 9/37; the 6.411 m/s figure is the G2 1-km reconfig, GATES.md row 7 — never budget against it). The predictor's number to produce: a **second delta — predictor+reactive vs reactive-only** — measured on ≥3 scenarios with committed logs and exact commands (invariant 1).

## 2. Architecture

### 2.1 New modules (sim core untouched except §2.3)

| Module | Role |
|---|---|
| `cubesat/telemetry.py` | Deterministic synthetic-telemetry generator: pure function of (JSONL log, scenario, telemetry seed, failure family). Consumes the byte-identical logs for ground truth (positions, `dv_used`, status, failure schedule) and synthesizes bus channels around them. |
| `cubesat/telemetry_features.py` | Strictly past-only feature extraction (§4.2). Kept its own module so the past-only rule is auditable in one file. |
| `cubesat/baseline_detectors.py` | EWMA + CUSUM control charts (~80 lines, numpy/scipy only) — the honest shipped fallback if P1 fails or LightGBM is declined. |
| `cubesat/predictor.py` | Model wrapper: loads hash-pinned artifact, scores per-sat risk from features. |
| `cubesat/policy.py` | Suspect policy (risk ≥ τ for k sustained steps), PREDICTOR_ALERT emission, risk-term plumbing, τ* gating. |
| `cubesat/eval_harness.py` | The P0 deliverable: splits, metrics, matched-FA calibration report, P2 sweep. Every number in README/pitch is reproducible by a harness command. |
| `models/predictor.txt` + `models/predictor_manifest.json` | Hash-pinned model artifact (plain-text `save_model`) + manifest `{model_sha256, lightgbm_version, params, feature_names, train-data hash, label horizon L, threshold τ*}`. |
| `data/scenarios_predictor/*.json`, `data/eval/test_manifest.json` | Predictor-family scenarios (own deterministic family, new pins) and the pre-registered test-split manifest written BEFORE any training. |

### 2.2 Data flow

Generator composes AROUND the frozen pipeline (`run_scenario` is pure, sim.py:80): log lines + scenario → telemetry channels → features → per-sat risk score → policy → (a) PREDICTOR_ALERT event, (b) optionally a pre-emptive replan via the existing `replan()` (allocate.py:233-246). The predictor consumes the same per-tick view the loop already serializes (sim.py:189-199: `states[i]`, `dv_used`, `missed`, `status`, roles, seats). Command history is NOT persisted — `dv_used` (pd.py:54, 76) is the only accumulated control signal; the generator reconstructs burn duty from its deltas.

Two data paths, kept strictly separate:

- **Offline path (P0/P1, zero sim diff):** committed logs → `telemetry.py` channels → `telemetry_features.py` → scores → `eval_harness.py` report. Pure functions of (log, scenario, seed); no log bytes change.
- **In-run path (P2 only):** `run_scenario` constructs the scorer at INIT from `scenario.predictor` (loading the hash-verified artifact from `models/`); with no block the scorer is `None` and the §2.3 branch is dead code. Scores feed `policy.py`, which raises events / arms the pre-emptive replan.

### 2.3 Hook mechanism — zero-diff preference, one unavoidable branch

- **P0/P1 are zero-diff by construction**: generator, features, baseline, model, and eval harness all live off the run path. No scenario file, log byte, or pin changes.
- **The unavoidable bit**: pre-emptive action needs an in-loop trigger. Today `mission=FAILURE_DETECTED` is set at exactly one place (sim.py:154, inside the missed-heartbeat block) and `replan_due` is set only at sim.py:227 and read only at sim.py:228 — there is no predictive trigger path.
- **The branch (added by our side, never by the G5 teammate)**: a minimal additive block (~15 lines) inside the same between-step orchestration region (sim.py:215ff), AFTER the existing reactive trigger, gated on `scenario.predictor is not None`. When the policy arms a suspect: emit a `PREDICTOR_ALERT` event (existing event field), set `mission=REPLANNING` + STATE event + `replan_due=True` — mirroring the existing trigger's exact state-transition pattern (sim.py:220-227) so the log/state machine stays consistent. The existing `replan()` runs unchanged. Sketch (shape only; exact code lands in P2):

  ```python
  # sim.py, between-step orchestration, AFTER the reactive trigger (sim.py:215-227).
  # PREDICTOR SESSION ONLY — gated, unreachable when scenario.predictor is None.
  if (
      scorer is not None                        # constructed at INIT iff predictor block present
      and scenario.predictor.preemptive_replan
      and mission == STATE_NOMINAL              # never overrides or interrupts the reactive path
      and policy.arms_preemptive_replan(scorer, sustain_ticks)   # risk >= tau sustained k ticks
  ):
      mission = STATE_REPLANNING
      events.append({"type": "PREDICTOR_ALERT",
                     "payload": {"sat_id": suspect, "risk": score, "t_alarm": t, "mode_hint": hint}})
      events.append({"type": "STATE",
                     "payload": {"from": STATE_NOMINAL, "to": STATE_REPLANNING}})
      replan_due = True
  ```

  Note on event order: the log pops at most ONE event per tick (sim.py:203-204), so if both events land on the same tick the STATE event appears one tick later — existing FIFO behavior (IMPLEMENTATION_NOTES.md), deterministic either way; P2 pins the exact order in the family fixture.
- **Inert when disabled**: with no predictor block the branch is unreachable and adds no dict keys. Proven by test: `test_predictor_disabled_bytes_identical` plus a re-run of `uv run pytest tests/test_cli.py::test_run_is_byte_deterministic -q` (green at HEAD `67189ab` this session, before the branch).
- **Own deterministic family**: predictor-enabled scenarios get their own committed sha256 pins (pattern: tests/test_cli.py:13, per-scenario table in IMPLEMENTATION_NOTES.md) — existing pins untouched.
- **Process guards**: defaulted nested `predictor` block on Scenario next to `detection`/`allocation` (scenario.py:110-111 — the G4 precedent of defaulted blocks keeping `nominal.json` byte-identical); dated approval line in the GATES.md decisions log; BACKEND_SPEC v1.1 addendum committed BEFORE the diff.
- **allocate.py touch (our side, additive)**: optional kwarg `risk_scores=None` on `replan()`/`build_cost_matrix()`; a strict `if risk_scores is not None` branch adds the §4.5 term. When None the function is bit-identical (no zero-addition) — same guard style as the G4 defaults.

**OFF-path checklist** (what "inert when disabled" means, concretely): no `risk` key in any per-sat object; no `PREDICTOR_ALERT` events; no extra INIT/SUMMARY keys; `mission` never leaves the G4 state machine's transitions; identical rng-free control flow (the scorer is never constructed); `replan()`/`build_cost_matrix()` called with the G4 signature and values. Every item is asserted by `test_predictor_disabled_bytes_identical` (P2), which runs a two_failure replay with and without the hook present in the tree and compares bytes to the committed log sha256 (`450d5371…`, GATES.md:9).

## 3. Wire/schema deltas — additive only, for the G5 teammate

No new WS message types. The message set stays `hello/sim_state/event/role_reassignment/ping/pong` (BACKEND_SPEC.md §6.2). Deltas, each tagged:

- **[must] Optional per-sat `risk` field** on the log's per-sat object (sim.py:189-199), present ONLY when the predictor is enabled; absent otherwise. G5's normalizer maps it into the `sim_state` per-sat shape verbatim (or drops it) — no enum/shape change elsewhere.
- **[must] `PREDICTOR_ALERT` event type** inside the existing `event` field (FIFO one-pop-per-tick semantics unchanged, sim.py:203-204). Payload `{sat_id, risk, t_alarm, mode_hint}`. The frontend already renders generic events (FRONTEND_SPEC warning-banner/event-message handling) — no frontend change required to display it.
- **[must] Optional `predictor` block in scenario JSON** (schema in §4.5). Defaulted nested pydantic model; old committed files parse unchanged (pydantic v2 `extra='ignore'` — verified by the design pass executing a minimal parse with an unknown top-level key). G5's `GET /scenarios` passes the block through opaquely.
- **[must] Old committed logs replay unchanged** — no new keys on the OFF path; INIT header and SUMMARY stay schema v1 (the predictor block is NOT echoed into INIT; replay clients read it from the scenario, which `POST /replay/load` already knows).
- **[must] One committed predictor-family log fixture** in the G5 series, plus `test_wire_predictor_event_additive` (tests/test_wire.py per BACKEND_SPEC §11) and `test_live_equals_replay_frames` (BACKEND_SPEC.md criterion 3) extended to that fixture.
- **[optional] `replanning_latency_ms`**: BACKEND_SPEC.md:246 ships it `null` "unless a future sim hook provides it out-of-band" — the predictor IS that hook: predicted lead time from the τ* sweep can populate it as out-of-band metadata. Else stays `null`/`unmeasured`.
- **[optional] Expose the predictor block fields** (armed, τ*, model hash) in the replay `/hello` metadata for dashboard display.

Wire shapes (additive keys only — the existing schema v1 envelope is untouched):

```json
{"id": 3, "role": "imager", "status": "NOMINAL", "r": [0.0, 8000.0, 0.0],
 "v": [0.0, 0.0, 0.0], "dv_used": 12.41, "risk": 0.83}
```
```json
"event": {"type": "PREDICTOR_ALERT",
          "payload": {"sat_id": 3, "risk": 0.83, "t_alarm": 902.0, "mode_hint": "eps_fade"}}
```

Old committed logs carry neither key; the normalizer treats absent `risk` as `null` → frontend renders "unmeasured" (BACKEND_SPEC.md:50 honesty rule). `mode_hint` is the argmax contributing channel family — informational only, never drives assignment.

**Coordination notes for G5** (verified this session): the spec is stale vs the tree in two places — `.github/workflows/ci.yml` IS committed (`git ls-files .github`) while BACKEND_SPEC.md:73 says no CI exists, and a Dockerfile build is verified in GATES.md:25 while BACKEND_SPEC.md:302 claims none exists. Tree wins (AGENTS.md). G5 amends the existing Dockerfile and must COPY `models/predictor.txt` + manifest if the predictor lands before the image rebuild. The v1.1 addendum for §3 lands as a dated GATES.md coordination note + spec addendum BEFORE the predictor diff.

## 4. Component specs (from the 2026-09-29 design pass)

### 4.1 Telemetry generator (`cubesat/telemetry.py`)

One sample per tick (dt=2 s); one orbit = 5677 s ≈ 2838.5 ticks at 500 km (n = 0.001107 rad/s, executed in the design pass). Channels: `bus_voltage_v` (7.4 V nominal, AR(1) σ≈0.02 V, deterministic eclipse dip keyed to orbit phase), `soc_frac` (integrator: discharge in eclipse, solar charge otherwise), `thrust_duty` (0 nominal; nonzero only during real PD burns, cross-checked against `dv_used` deltas — those are real log data), `hb_latency_ms` (40 ms + AR(1) σ=5 ms; finite until t_f — the sim's heartbeat is perfect until DEAD, sim.py:141-145), `hb_jitter_ms` (rolling std of latency), `temp_c` (20 °C + orbit-phase sine + noise). **Three failure families**, one per scheduled failure, overlaid on one satellite:

| Family | Overlay (parameterized, never fixed waveforms) | Precursor | Positive ticks |
|---|---|---|---|
| EPS fade (slow ramp) | over R ending at t_f: voltage drains 0.03–0.05 V/min to −1.5 V; SoC deficit vs the eclipse profile; temp +3–6 °C | visible ≥10 min early | ~L per event |
| Comms degradation | over R: hb_latency mean 40→120 ms, AR(1) σ 5→40 ms; silence at t_f | jitter growth is the discriminative signal | ~L per event |
| Sudden death | none — instant DEAD at t_f | none, by construction | 0 |

**Seeding (invariant 2)**: all sampling from `numpy.random.Generator(PCG64)` seeded via `SeedSequence(scenario.seed).spawn()` per (satellite, channel); iterate channels/sats by index, never over sets/dicts. This is the sim family's first RNG consumer (no `random` import exists anywhere in cubesat/ today; the seed is currently a pure label, sim.py:122).

**Anti-circularity**: every parameter (R, drift rates, noise σ, distractors) drawn per-run, never hardcoded waveforms. Train family = seed range A with R ∈ [1800, 3600] s; test family = DISJOINT seed range B with shifted parameters (R ∈ [3600, 5400] s, different drift magnitudes, compound modes like EPS fade + elevated jitter on one sat) so the model cannot win by memorizing shapes. Benign distractors as false-alarm bait: self-recovering voltage excursions, eclipse transients, burn pulses. **The test-split parameters + seed list are written to `data/eval/test_manifest.json` and committed BEFORE any model training** (pre-registration; see risk R1). Scale: ~90 runs × 3–6 sats (two_failure is 17028 s ≈ 3 orbits), scenarios in `data/scenarios_predictor/`.

### 4.2 Features (`cubesat/telemetry_features.py`)

**Strictly past-only**: at tick t every feature uses samples with timestamp ≤ t; shift one tick where a window endpoint could touch t. Windows tied to dt=2 s: W ∈ {15, 60, 300} ticks = {30 s, 2 min, 10 min}. Per channel and window: last, mean, std, trend (mean of latest W/2 − mean of previous W/2), min, max. Cross-window: `mean_15 − mean_300` (recent-drift), robust z-score against median + 1.4826·MAD — **the SAME baseline rule at train and inference: expanding per-sat history** (no train-serve skew). Comms-specific: near-miss beat count, rolling latency std at W=60/300, max latency, ticks-since-spike. Power-specific: eclipse-detrended voltage residual, SoC slope over W=300. Control-specific: thrust-duty sum W=60, real `dv_used` delta. EWMA z_t and CUSUM S_t are included AS features (§4.3). **Labels**: for a failure at t_f on sat i, y(t)=1 iff t ∈ [t_f − L, t_f) with L = 150 ticks = 300 s; ticks ≥ t_f are censored (post-onset belongs to the reactive path); warmup t < 300 dropped so every 300-tick window exists — no NaN plumbing. Sudden death contributes zero positives. Class balance ≈ 0.02% positives — all model choices are PR-focused.

### 4.3 Baseline detectors (`cubesat/baseline_detectors.py`) — the shipped fallback

Per (sat, channel): robust μ, s (median, 1.4826·MAD) from the first-orbit nominal window, then two NIST-quoted charts. **EWMA** (NIST/SEMATECH §3.2.4): z_t = λ·y_t + (1−λ)·z_{t−1}, z_0 = μ, σ_ewma = s·√(λ/(2−λ)); alarm outside μ ± k·σ_ewma; λ ∈ {0.1, 0.2} swept (small λ favors gradual-drift sensitivity). Primary for EPS fade. **CUSUM** (NIST §3.2.3): S_hi = max(0, S_prev + y − μ − k), S_lo mirrored, alarm above h; k ≈ 0.5σ, h ≈ 4–5σ; run on the rolling-std-of-latency series (two-stage: variance growth → CUSUM) — primary for the comms mode. **Alarm semantics**: an alarm EVENT needs M = 5 consecutive alarmed ticks (10 s debounce) so FA rate counts events, not ticks; family-wise inflation across channels handled by calibrating the max-statistic empirically, not per-channel. **Matched-FA calibration (the core protocol)**: sweep (k, h, λ) on train+val NOMINAL segments only; threshold = empirical quantile of the max-statistic for ~0.5 alarm events/satellite-orbit (no Gaussian assumption). The model's operating threshold is then chosen on the SAME validation set to produce the SAME FA rate. Deterministic, dependency-free, fully defensible — this ships if P1 fails.

### 4.4 Model (`cubesat/predictor.py`) — pending §8 user approval

LightGBM 4.7.0, NATIVE API (`lgb.train` on `lgb.Dataset` — never `LGBMClassifier`, so scikit-learn is never pulled; core deps are narwhals/numpy/scipy, sklearn only an extra in 4.7.0 per PyPI). Params (tiny/imbalanced tabular; LightGBM docs' overfitting checklist):

| Param | Value | Reason |
|---|---|---|
| objective | binary | — |
| learning_rate | 0.05 | small-data default |
| num_leaves / max_depth | 15 / 5 | keep num_leaves < 2^max_depth; anti-overfit |
| min_data_in_leaf | 200 | docs: "very important" against overfitting |
| max_bin | 63 | fewer bins, faster + anti-overfit |
| feature_fraction / bagging | 0.8 / 0.8 + freq 1 | docs checklist |
| lambda_l2 | 1.0 | regularization |
| rounds | ≤1000, early stopping | on a hand-rolled average-precision feval (no sklearn metric) |
| deterministic / force_row_wise | true / true | docs REQUIRE the pairing with deterministic=true |
| seed / num_threads | 42 / 4 (fixed) | docs: seed generates the sub-seed family; never change threads mid-training |

Model selection and thresholding are strictly PR-AUC-based (Saito & Rehmsmeier 2015: PR over ROC at ~0.02% positives); no accuracy metric anywhere. Determinism caveat, quoted from the docs: cross-machine or cross-version results "are expected to be different" — win32 dev vs linux CI — so **CI never retrains: it only verifies the artifact sha256 against the manifest and the OFF-path pins**. Artifact: `booster.save_model('models/predictor.txt')` (plain text) + manifest (§2.1). Build-time check: train twice → identical model-file hash → identical predictions on the validation set.

### 4.5 Policy (`cubesat/policy.py`)

Scenario block (defaulted, alongside detection/allocation at scenario.py:110-111): `predictor: {enabled: false, model: str|null, tau: float|null, sustain_ticks: int = 5, preemptive_replan: bool = false, w_risk: float = 0.0}`. Semantics: per-sat risk score each tick; **risk ≥ τ sustained for k = sustain_ticks steps marks the satellite SUSPECT** → `PREDICTOR_ALERT` event. If `preemptive_replan`: a sustained suspect arms a pre-emptive call of the existing `replan()` via the §2.3 branch. **Risk term in the Hungarian cost**: `build_cost_matrix` gains the optional `risk_scores` row-constant term, mirroring the fuel-term pattern (allocate.py:194-197): C[i,j] += w_risk · risk_i · crit_j, with crit_j = 1 for the leader seat, 0 for follower seats — a satellite predicted to fail is de-preferred for the role-critical seat. w_risk = 0 (default) reproduces the G4 cost exactly. **τ\* selection (P2)**: sweep τ on validation scenarios running the full sim with the predictor ON; record last-orbit coverage delta vs reactive-only, extra Δv spent on spurious replans, FA count. Choose τ* = argmax coverage delta subject to **Δv-per-false-alarm ≤ 10% of the scenario's MEASURED recovery Δv** (two_failure worst per-sat 193.68 m/s, GATES.md:37 — not the 6.411 m/s G2 figure, GATES.md:7). OFF by default; a negative delta means ship reactive-only and say so.

### 4.6 Evaluation protocol (`cubesat/eval_harness.py`)

Splits BY RUN: train 0–59, validation 60–74 (early stopping + threshold selection ONLY), test 75–89; never split at tick level (autocorrelation leaks). Satellite holdout: sats 4–5 excluded from training entirely. Metrics: (1) tick-level PR-AUC, overall and per mode; (2) lead time — median/min of (t_f − t_first_alarm) over detected events, in s and ticks, capped at L = 300 s; (3) false alarms per satellite-orbit = debounced alarm events on nominal sat-time ÷ (n_sats × 2838.5); (4) event recall per mode (detected = any alarm in [t_f−L, t_f)), sudden death reported separately and expected ≈ 0. Baseline comparison: EWMA/CUSUM vs model at the same FA/sat-orbit rate (P1 gate). **Generator ablation**: regenerate the test family with a fresh noise-realization seed; per-mode event recall must stay within the band stated in the harness report. OPSSAT-AD side-validation (real ESA OPS-SAT anomaly dataset, pipeline-only — NOT training data) is stretch, only after P2's delta is committed.

### 4.7 Sources

LightGBM Parameters + Parameters-Tuning (readthedocs, fetched 2026-09-29); PyPI JSON lightgbm 4.7.0; NIST/SEMATECH e-Handbook §3.2.3 (CUSUM) and §3.2.4 (EWMA); Saito & Rehmsmeier 2015 (PLOS ONE e0118432); OPSSAT-AD Zenodo DOI 10.5281/zenodo.12588359 (CC-BY-4.0). Full list in the design-pass record.

## 5. Risk register

Condensed from the 2026-09-29 risk-mapper output: no risk added or dropped, severities unchanged, wording tightened for table form.

| # | Risk | Sev | Mitigation | Detection (✓ = executed this session) |
|---|---|---|---|---|
| R1 | Training circularity — model tuned to its own generator | high | Pre-registered test manifest committed BEFORE training; sat holdout 4–5; EWMA/CUSUM fallback per P1 clause; generator-ablation recall band | `test_eval_report_from_pinned_test_manifest` — not run (harness P0) |
| R2 | Feature/label leakage, train-serve skew | med | Strictly past-only windows w/ one-tick guard; SAME expanding-baseline rule train+serve; split by run id | `test_features_past_only` (bit-identity under future-garbage), `test_eval_split_no_run_overlap` — not run |
| R3 | Determinism & golden pins on the predictor path | high | OFF-by-default inert hook; own family sha256 pins; artifact+manifest hash-verify; NEVER retrain in CI | ✓ `test_run_is_byte_deterministic` green at `67189ab`; then `test_predictor_disabled_bytes_identical`, `test_predictor_family_run_byte_identical` |
| R4 | Generator is the first RNG consumer (seed is a label today) | med | PCG64 via `SeedSequence(seed).spawn()` per (sat, channel); index iteration only; invariant-2 comment in module | `test_generator_seeded_reproducible` — not run; RNG sweep clean (design pass) |
| R5 | Sim-core no-modify rule vs the in-loop trigger | high | Minimal gated branch (§2.3), added by our side only; defaulted block (G4 precedent); dated GATES.md approval; spec addendum BEFORE the diff | ✓ golden test green pre-branch; re-run + `test_predictor_disabled_bytes_identical` after |
| R6 | False alarms burning Δv → negative headline | med | Matched-FA calibration (0.5 events/sat-orbit, M=5 debounce); τ* gated on ≤10% of measured 193.68 m/s (GATES.md:37); OFF-by-default contains worst case | P2 sweep + `test_dv_spent_on_false_alarms_bounded` — not run |
| R7 | LightGBM approval & uv.lock discipline | med | Ask now with PyPI facts; fallback = numpy/scipy baseline (P1 clause); if approved: `uv add lightgbm` + re-lock + `uv sync --locked` in one commit with the artifact | ✓ `rg` no-match today; at approval: `uv sync --locked` + full `uv run pytest -q` |
| R8 | Docker image weight AND content for G6 | high | COPY data/scenarios + canonical logs + models/* ; rebuild + record size next to GATES.md:25 (816 MB); exercise run+/health+/scenarios BEFORE freeze; G5 amends the existing Dockerfile (spec:302 stale) | `docker build` + `docker run` + curl — not run (daemon availability unknown) |
| R9 | Wire-contract drift while G5 builds from a predictor-blind spec | high | Additive-only wire (§3); dated v1.1 addendum + GATES.md note BEFORE landing; committed predictor fixture | `test_wire_predictor_event_additive` + extended `test_live_equals_replay_frames` — not run (G5 modules pending) |
| R10 | Live demo with no committed replay fallback | high | Land BACKEND_SPEC §7.3 whitelist commit (✓ `git ls-files data/logs` → only `.gitkeep` today); commit predictor-ON logs for the 3+ P2 scenarios; rehearse replay-first demo | post-commit `git ls-files`; `curl -X POST localhost:8000/replay/load` — not run (server is G5's) |
| R11 | Time-to-freeze (P0–P2 before P3) | high | Hard time-boxes (§6); P1 fork pre-agreed (ship baseline); cut copilot/OPSSAT unless P2 delta committed by 12:00; G6/G7 take priority after P3 | GATES.md P3 entry; per-commit `uv run pytest -m "not slow" -x -q` |
| R12 | Sudden-death overclaim in README/pitch | med | Per-mode recall table with sudden death marked "unpredictable by construction; reactive net (4 s detection, GATES.md:9)"; demo scenario includes ≥1 slow-family failure | P2 harness report; G7 README line-review against it |

## 6. Phased plan (time-boxed against the freeze)

Repo test style throughout (names per docs/MASTER_PROMPT.md §3.8 convention); tests first in every phase. Gate discipline: predictor sessions stay separate from the G5 session (one gate per session, AGENTS.md); G5 keeps building from the spec + §3 addendum in parallel.

**P0 — harness, generator, features, baseline (today 2026-09-29, box ends 22:00 IST).**
Deliverables: `cubesat/eval_harness.py`, `cubesat/telemetry.py`, `cubesat/telemetry_features.py`, `cubesat/baseline_detectors.py`; `data/eval/test_manifest.json` committed BEFORE any training (R1). Tests: `test_generator_seeded_reproducible`, `test_features_past_only`, `test_eval_split_no_run_overlap`, `test_baseline_calibration_matched_fa`. Verification per commit: `uv run pytest -m "not slow" -x -q` and `uv run ruff check .` green with the 43 existing tests untouched. Exit: zero changes to scenarios/pins/sim; the harness report command's exact invocation recorded in GATES.md (it becomes the command-of-record for every later number).

**P1 — train and compare at matched false alarms (tonight → 09-30 06:00 IST).**
If LightGBM approved (§8 Q1): `uv add lightgbm`, re-lock, artifact + manifest, matched-FA comparison on test runs. If declined or not answered: EWMA/CUSUM ships — pre-agreed honest outcome. Tests: `test_model_artifact_hash_matches_manifest`, `test_eval_report_from_pinned_test_manifest`, twice-train byte equality recorded in the manifest. Exit: P1 verdict (model vs baseline) written to GATES.md with the harness command; PR-AUC + per-mode recall table produced by that command.

**P2 — integrate and measure the second delta (09-30 morning, box ends 11:30 IST).**
Deliverables: the §2.3 gated branch + `risk_scores` kwarg; `data/scenarios_predictor/*.json` (≥3 scenarios, each with ≥1 slow-family failure so the alarm visibly fires on stage); τ* sweep; committed predictor-ON logs + family sha256 pins + wire fixture. Tests: `test_predictor_disabled_bytes_identical`, `test_predictor_family_run_byte_identical`, `test_dv_spent_on_false_alarms_bounded`, `test_wire_predictor_event_additive`; re-run `uv run pytest tests/test_cli.py::test_run_is_byte_deterministic -q` and `uv run pytest -q` full. Exit: second delta (predictor+reactive vs reactive-only) measured on ≥3 scenarios with committed logs and exact commands (invariant 1) — or an honest "no improvement" verdict.

**P3 — decision gate (2026-09-30 ~12:00 IST).**
Ship the predictor+reactive headline only if the delta is positive and Δv-gated (§4.5); else ship reactive-only and say so. Then G6 deploy and G7 README take priority until the 18:00 freeze. Copilot and OPSSAT-AD are cut unless P2 is already committed and slack remains.

**Session mapping (one gate per session, AGENTS.md):** P0+P1 = predictor session #1 (today); P2 = predictor session #2 (09-30 morning); G5 continues per BACKEND_SPEC in its own sessions; neither touches the other's files except the shared §3 addendum, which the predictor session commits BEFORE its P2 diff.

## 7. README honesty claim (G7 language, binding)

- The AI layer **explains and configures**; every seat assignment comes from the Hungarian algorithm (`linear_sum_assignment`, rows = survivors, cols = candidate slots, deterministic index-epsilon tie-break) — **deterministic and reproducible**, same scenario + seed ⇒ byte-identical log.
- The predictor is an early-warning layer over synthetic telemetry; it **never replaces the reactive path** — heartbeat timeout → Hungarian reallocation remains the authoritative safety net.
- **The predictor cannot catch sudden failures**: sudden death has no precursor by construction; per-mode recall is published from the eval harness with sudden death marked "unpredictable by construction; covered by the reactive path (4 s detection latency at K=3, GATES.md:9)".
- The model is **trained and tested on separate generator settings** (disjoint seed ranges, shifted ramp lengths, compound modes; satellite holdout); the test manifest is committed before training.
- Every number carries a committed log AND the exact command (invariant 1). Anything unmeasured is written "unmeasured".

## 8. What NOT to build, and open questions

**Not building:** the LLM copilot beyond the §1.2 sketch (cut FIRST); no model retraining in CI (hash-verify only); OPSSAT-AD as training data (side-validation only, stretch); no new WS message types; no changes to the reactive path's semantics (missed_ticks_k, Hungarian, mission states stay); no edits to existing golden pins, committed scenarios, or nominal.json; no unseeded RNG anywhere on the log path; no new dependency beyond an approved lightgbm; no sim-core edits beyond the single gated branch of §2.3; no number without a committed log and command.

**Open questions for the user:**

1. **LightGBM dependency approval** (blocks P1 model training): `uv add lightgbm` (4.7.0; core deps narwhals/numpy/scipy — sklearn stays out via the native API) + uv.lock re-lock. Cost: the wheel (~1.3 MB win) + narwhals. If declined or unanswered by P1, the EWMA/CUSUM baseline ships per the pre-agreed fork — no block.
2. **Sign-off for the §2.3 gated sim-core branch** (~15 lines, added by our side, inert when disabled, GATES.md approval line + BACKEND_SPEC v1.1 addendum first). Without it, P2 degenerates to detector-only measurement with no pre-emptive action — the delta would be 0.
3. **Committed-log ownership**: BACKEND_SPEC §7.3 (line 285) plans the canonical-log whitelist commit in the G5 series; the predictor additionally needs predictor-ON family logs committed for its headline. Confirm the split of ownership so neither session blocks the other.
4. **OPSSAT-AD side-validation**: confirm the cut unless P2's delta is committed before 12:00 and real slack remains.
5. **Copilot stretch**: confirm the cut unless everything through P3 is committed by 14:00 on 09-30 — the §1.2 sketch is the ceiling; no live-LLM demo.

## Appendix A — commands of record (this session, HEAD `67189ab`, 2026-09-29)

- `uv run pytest --collect-only -q` → 43 tests across 10 files (5+3+9+3+5+3+4+6+3+2); full suite NOT run this session.
- `uv run pytest tests/test_cli.py::test_run_is_byte_deterministic -q` → `.` `[100%]`, passed — golden pin `c95f31b8…` (tests/test_cli.py:13) holds on the current tree, pre-branch.
- `git ls-files data/logs` → `data/logs/.gitkeep` only; `git ls-files data/scenarios` → the 5 committed scenario JSONs.
- `git ls-files .github` → `.github/workflows/ci.yml` committed (BACKEND_SPEC.md:73 "no CI config exists" is stale — tree wins).
- `rg -n "predictor|PREDICT|lightgbm" docs cubesat GATES.md README.md pyproject.toml uv.lock` → no matches (clean slate for the predictor naming and the dependency).
- Reads grounding the cites above: graphify-out/GRAPH_REPORT.md (mandatory onboarding), GATES.md, cubesat/sim.py:120-239, cubesat/scenario.py, cubesat/allocate.py:180-249, tests/test_cli.py, pyproject.toml, docs/BACKEND_SPEC.md (§0-§8 targeted).
- NOT run this session: full `uv run pytest -q`, `uv run ruff check .`, any docker command, any harness/generator code (none exists yet).
