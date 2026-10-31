# Claims after re-measure (2026-10-31)

Final deliverable of the evidence-repair pass (branch `v2-evidence`). Rows are the 150 claim rows of docs/audit/2026-10-31-c.md §5 (columns "status before" = that audit's `reproduces?`). Status after: **reproduces** (text unchanged, command re-run or artifact re-checked), **updated** (text changed to the regenerated number or reframed, command named), **unmeasured** (no committed command; text says so), **removed** (claim deleted), **listed** (frontend copy, not editable on this branch; see docs/audit/2026-10-31-frontend-claims.md). Machine: macOS arm64, Apple M3. Regenerated artifacts: GATES.md "2026-10-31 — v2 evidence re-measure".

| id | claim | file | status before | status after | command / note |
|---|---|---|---|---|---|
| R1 | CW-vs-Kepler 3.101 m, 1 km ellipse, 3 orbits | README.md:38 | yes | reproduces | `uv run python -m pytest tests/test_hcw.py -s -q` |
| R2 | 1 km PD: 746 s, 6.411 m/s, 4.99%, max abs u = a_max | README.md:40-41 | yes | reproduces | `uv run python -m pytest tests/test_pd.py -s -q` |
| R3 | quarter-phase: 20.176 m/s, 1966 s, bound 945.7 s | README.md:42-43 | yes | reproduces | `uv run python -m pytest tests/test_pd.py -s -q` |
| R4 | nominal mean tick coverage 0.4387, range 0.4266-0.4547 | README.md:44 | yes | reproduces | `uv run python -m cubesat.run --scenario data/scenarios/nominal.json --seed 42 --out data/logs/e_nominal.jsonl` (re-run: 0.4387, 0.4266-0.4547, 15556.3-17391.8 m, 1.56e-11) |
| R5 | nominal min sep 15.56-17.39 km | README.md:45 | yes | reproduces | `uv run python -m cubesat.run --scenario data/scenarios/nominal.json --seed 42 --out data/logs/e_nominal.jsonl` (re-run: 0.4387, 0.4266-0.4547, 15556.3-17391.8 m, 1.56e-11) |
| R6 | nominal per-sat dv ~1e-11 m/s | README.md:45 | yes | reproduces | `uv run python -m cubesat.run --scenario data/scenarios/nominal.json --seed 42 --out data/logs/e_nominal.jsonl` (re-run: 0.4387, 0.4266-0.4547, 15556.3-17391.8 m, 1.56e-11) |
| R7 | killing 2 of 4 imagers, no recovery: -16.65 to -19.99 pts | README.md:47-48 | yes | reproduces | `uv run python -m pytest tests/test_coverage.py -s -q` |
| R8 | recovery 0.2698 vs no recovery 0.2205 | README.md:50 | yes | reproduces | `uv run python -m pytest tests/test_fault.py -s -q` + `uv run python -m cubesat.run --scenario data/scenarios/two_failure.json --seed 42 --out data/logs/e_two_failure.jsonl` |
| R9 | +4.93 pts | README.md:50 | yes | updated | reframed as the best-case pair; mean over 15 pairs -2.13 added (README) |
| R10 | ~31% of destroyed coverage | README.md:50 | yes | reproduces | `uv run python -m pytest tests/test_fault.py -s -q` + `uv run python -m cubesat.run --scenario data/scenarios/two_failure.json --seed 42 --out data/logs/e_two_failure.jsonl` |
| R11 | no-recovery drop 15.91 pts from 0.3796 | README.md:51 | yes | reproduces | `uv run python -m pytest tests/test_fault.py -s -q` + `uv run python -m cubesat.run --scenario data/scenarios/two_failure.json --seed 42 --out data/logs/e_two_failure.jsonl` |
| R12 | worst min sep 3095.1 m (>2000) incl. transfers | README.md:52 | yes | updated | defined as all-pairs min_sep of pair (1,2); 15-pair worst survivor-dead 1852.5 m added |
| R13 | detection latency 4 s | README.md:53 | yes | updated | labelled (K-1)*dt by construction |
| R14 | per-sat dv up to 193.68 m/s | README.md:53 | yes | reproduces | `uv run python -m pytest tests/test_fault.py -s -q` + `uv run python -m cubesat.run --scenario data/scenarios/two_failure.json --seed 42 --out data/logs/e_two_failure.jsonl` |
| R15 | CW-vs-Kepler 2984.5 m at 22 km slot | README.md:65 | yes | reproduces | `--mode cw-curve` command (GATES.md P3 row); re-run: 3.101 / 2984.5 / 1578.543 m |
| R16 | a_max 1e-2 = "~8 kg, ~150 mN" | README.md:91 | no | updated | 0.01 m/s^2 = 80 mN at 8 kg (0.019 m/s^2 at 150 mN) |
| R17 | PD diverges at 1e-2 at every spacing swept 4-11 km | README.md:93-97 | unverified | unmeasured | no committed script/artifact for the 4-11 km a_max sweep; text says so |
| R18 | "G5/G6 in progress - not landed" | README.md:10-11 | no | updated | README status now G5 PASS untagged, G6/G7 todo |
| R19 | same scenario+seed => byte-identical log | README.md:7-8 | yes | updated | same-machine only; canonical_log_hash is the cross-platform pin |
| G1 | STM-vs-ODE 1.353e-12 / 5.599e-10; CW-Kepler 3.101 m | GATES.md:6 | yes | reproduces | `uv run python -m pytest tests/test_hcw.py -s -q` |
| G2 | 4.99% / 746 s / 6.411 / 20.176 / 1966 / 945.7 | GATES.md:7 | yes | reproduces | `uv run python -m pytest tests/test_pd.py -s -q` |
| G3 | passive slot 2.198e-11 m, 1.410e-12 m/s, 1.411e-15; forced prop 2.283e-13 | GATES.md:7 | yes | reproduces | `uv run python -m pytest tests/test_pd.py -s -q` |
| G4 | bang-bang dv 6.32 m/s at 1 km | GATES.md:7 | yes | reproduces | `uv run python -m pytest tests/test_pd.py -s -q` |
| G5 | G3: 0.4390; 0.1665/0.1999; r_f 13.09 km; 0.4387; 15.56-17.39 km; <=1.6e-11 | GATES.md:8 | yes | reproduces | `uv run python -m pytest tests/test_coverage.py -s -q` |
| G6 | golden sha 6169c266… (nominal), c95f31b8… | GATES.md:8 | no | updated | platform-bound sha: Windows value kept, macOS value added (GATES.md G3/G4/P0 rows) |
| G7 | G4: 3095.1, 0.3796/0.2205/15.91, 0.2698, 4.93, 31%, 4 s, t=3114, 193.68, 984.0/945.3 s, 8517 lines | GATES.md:9 | yes | reproduces | `uv run python -m pytest tests/test_fault.py -s -q` + `uv run python -m cubesat.run --scenario data/scenarios/two_failure.json --seed 42 --out data/logs/e_two_failure.jsonl` |
| G8 | two_failure sha 450d5371… | GATES.md:9 | no | updated | platform-bound sha: Windows value kept, macOS value added (GATES.md G3/G4/P0 rows) |
| G9 | G5: replay load 0.337 s, run 2.92-3.24 s, inject 2.87-3.21 s, 98 passed | GATES.md:10 | unverified | updated | replay load and run_scenario re-timed (macOS M3); injection stall unmeasured; 98-passed was a date-stamped count (current 224 collected) |
| G10 | P0: 60 rows, each with command + log sha | GATES.md:17 | yes | reproduces | P0 command (GATES.md P0 row); report+manifest regenerated byte-identical; G22 mean -1.5532 over 14 pairs re-computed |
| G11 | pair_1-2__hungarian sha 978367… | GATES.md:17 | no | updated | platform-bound sha: Windows value kept, macOS value added (GATES.md G3/G4/P0 rows) |
| G12 | hungarian coverage 0.26980 mean=worst, identical on 15 pairs | GATES.md:18 | yes | reproduces | P0 command (GATES.md P0 row); report+manifest regenerated byte-identical; G22 mean -1.5532 over 14 pairs re-computed |
| G13 | hungarian critical roles 15/15 | GATES.md:18 | unverified | reproduces | `policies_summary.*.pairs_critical_roles_held` in benchmark_results.json (15 / 6); metric now committed |
| G14 | hungarian total dv mean 444.30; worst per-sat 251.24 (pair (4,5) sat 2); min-sep mean 4154.9, worst 1852.5 | GATES.md:18 | yes | reproduces | P0 command (GATES.md P0 row); report+manifest regenerated byte-identical; G22 mean -1.5532 over 14 pairs re-computed |
| G15 | do_nothing 0.29106 / 0.22045 on (1,2),(1,4),(3,4); dv <=8.2e-11; sep 11313.7 | GATES.md:19 | yes | reproduces | P0 command (GATES.md P0 row); report+manifest regenerated byte-identical; G22 mean -1.5532 over 14 pairs re-computed |
| G16 | do_nothing critical roles 6/15 | GATES.md:19 | unverified | reproduces | `policies_summary.*.pairs_critical_roles_held` in benchmark_results.json (15 / 6); metric now committed |
| G17 | even_split 0.26982/0.26958; 1308.36; 2311.1/722.8 | GATES.md:20 | yes | reproduces | P0 command (GATES.md P0 row); report+manifest regenerated byte-identical; G22 mean -1.5532 over 14 pairs re-computed |
| G18 | greedy 0.26980; 283.65; worst sep 1852.5 | GATES.md:21 | yes | reproduces | P0 command (GATES.md P0 row); report+manifest regenerated byte-identical; G22 mean -1.5532 over 14 pairs re-computed |
| G19 | +4.93 on (1,2),(1,4),(3,4); +0.72/+0.73 (1,3)/(2,4); -0.00 (2,3) | GATES.md:22 | yes | reproduces | P0 command (GATES.md P0 row); report+manifest regenerated byte-identical; G22 mean -1.5532 over 14 pairs re-computed |
| G20 | negative on "8 pairs where <=1 imager dies" | GATES.md:22 | no | reproduces | GATES text already said 9 pairs (fixed in Phase 0); re-verified: 9 negative pairs |
| G21 | -10.14 pts on (0,5); do_nothing 0.3712 / 0.3796 | GATES.md:22 | yes | reproduces | P0 command (GATES.md P0 row); report+manifest regenerated byte-identical; G22 mean -1.5532 over 14 pairs re-computed |
| G22 | mean gain -2.13 (15), -1.55 (14) | GATES.md:22 | yes | reproduces | P0 command (GATES.md P0 row); report+manifest regenerated byte-identical; G22 mean -1.5532 over 14 pairs re-computed |
| G23 | Pareto: coverage flat 0.26980; front = 2 points; 4 of 12 partial | GATES.md:24 | yes | reproduces | `--mode pareto` command (GATES.md P1 row), regenerated: coverage flat, 2-point front, 4 of 12 partial |
| G24 | Pareto dv span 463.07-481.61 m/s | GATES.md:24 | no | updated | Pareto dv span 463.07-481.61 -> 425.76-469.34 m/s (regenerated) |
| G25 | keepout: 1322.6 = 1322.6, never fired, CUT | GATES.md:26 | no | updated | keep-out re-measured into keepout_report.json: CUT, 1852.5 m vs 1322.6 m, confound noted |
| G26 | 90 dead-sat entries; horizon ~2.79 orbits | GATES.md:26 | yes | updated | 60 dead-sat entries (2 policies x 30); horizon 2.74-2.79 orbits |
| G27 | CW curves 3.101 / 2984.5 / 1578.543 | GATES.md:28 | yes | reproduces | `--mode cw-curve` command (GATES.md P3 row); re-run: 3.101 / 2984.5 / 1578.543 m |
| G28 | headline 193.68; 155.09 vs 47.81 = 3.24x | GATES.md:31 | yes | reproduces | `python -m cubesat.dv_bound ...` regenerated: 3.24x, 47.81 / 149.37 m/s |
| G29 | mean completed ratio 2.58x; worst 5.64x pair (0,1) sat 2 | GATES.md:32 | no | updated | mean completed ratio 2.58x -> 2.95x; worst 5.64x -> 5.72x (pair (0,3) sat 4) |
| G30 | whole-run mean ratio 1.05x, 10/15 below 1.0 | GATES.md:33 | no | updated | whole-run mean ratio 1.05x -> 1.86x; 10/15 below 1.0 still holds |
| G31 | floors: whole-run per-sat 16-215 m/s, completed 0-61 m/s | GATES.md:34 | unverified | updated | recomputed from dv_lower_bounds.json: whole-run per-sat floor 9.19-214.51, completed 0-61.48 m/s |
| G32 | headline floor 47.8 completed / 149.4 both episodes | GATES.md:34 | yes | reproduces | `python -m cubesat.dv_bound ...` regenerated: 3.24x, 47.81 / 149.37 m/s |
| G33 | VACCO CuSP MiPS 69 N-s = 8.8 m/s at 8 kg; ~22x | GATES.md:35 | unverified | unmeasured | VACCO 8.8 m/s is a cited figure; source not re-fetched (69 N-s / 8 kg = 8.63 m/s); text says so |
| G34 | fast loop 129 / 142 passed | GATES.md:40,46 | unverified | updated | historical test counts kept as date-stamped; current 224 collected / 221 non-slow pass added |
| G35 | cascading_n8: 3 FD / 3 ASG / RECOVERED 4280.0 / worst 3410.6 m | GATES.md:40 | no | updated | RECOVERED 5152.0 s, worst min_sep 2327.3 m @2732 s, max dv 398.40 m/s (run_scenario via cubesat.run) |
| G36 | eps_leader: RECOVERED 4236.0, worst min_sep 3267.0 | GATES.md:40 | no | updated | RECOVERED 3664.0 s, worst min_sep 868.0 m @2746 s, 2 EVASIVE |
| G37 | proximity_stress seed 7: 35 EVASIVE | GATES.md:42 | no | updated | 30 EVASIVE_MANEUVER events at HEAD (first 848.5281 m at t=0 unchanged) |
| G38 | first evasion at 848.5 m, t=0 | GATES.md:42 | yes | reproduces | `cubesat.run --scenario data/scenarios/proximity_stress.json --seed 7`: first range 848.5281374 m at t=0 |
| G39 | oracle v2: CLEAR, +1.7968 pp L300, +10.6048 pp max, 3210.31 m/s L300 | GATES.md:44 | unverified | updated | `uv run python files/oracle_sweep_v2.py` re-run: CLEAR, 1.7968 / 10.6048 pp reproduce; family label and eps_leader row change (eps_leader_6sat.json now sets reassign_on_degrade); output kept as oracle_sweep_v2_regen_2026-10-31.json |
| G40 | Monte Carlo means/worst/std/gains/Δv/min sep | GATES.md:46 | yes | reproduces | monte-carlo command (GATES.md MC paragraph), regenerated: every headline identical |
| G41 | v3 trigger: pinned 10.6166 pp, functional 0.0470, coverage +0.1507, dv 562.80 vs 401.84, recommend true | GATES.md:53-59 | unverified | updated | `uv run python files/oracle_sweep_v3.py` re-run: trigger recommend flips true -> false at HEAD; committed record kept, regen in oracle_sweep_v3_regen_2026-10-31.json; user decision flagged |
| G42 | "no committed scenario sets reassign_on_degrade" | GATES.md:53 | no | updated | corrected: eps_leader_6sat.json sets reassign_on_degrade true since 5fb535c |
| G43 | allowed-numbers rows :111-118,122 (same values as G1-G7, G27) | GATES.md:111-122 | yes | reproduces | same values as G1-G7, G27 |
| G44 | allowed-numbers :119 "worst min survivor-dead separation 1322.6 m" (hungarian) | GATES.md:119 | no | updated | 1322.6 m belongs to hungarian_keepout; hungarian worst = 1852.5 m |
| G45 | allowed-numbers :120 Δv 463.07-481.61 | GATES.md:120 | no | updated | Pareto dv span 463.07-481.61 -> 425.76-469.34 m/s (regenerated) |
| G46 | allowed-numbers :121 keepout never fired | GATES.md:121 | no | updated | keep-out re-measured into keepout_report.json: CUT, 1852.5 m vs 1322.6 m, confound noted |
| G47 | allowed-numbers :123 2.58x / 5.64x | GATES.md:123 | no | updated | mean completed ratio 2.58x -> 2.95x; worst 5.64x -> 5.72x (pair (0,3) sat 4) |
| J1 | ruff clean, 185 tests pass | docs/JUDGE_PREP.md:21-24,228,358 | no | updated | 224 collected, 221 non-slow pass (3 slow not run) |
| J2 | two_failure sha 450d5371… byte-identical to committed log | docs/JUDGE_PREP.md:28-30 | no | updated | 450d5371 is the Windows pin; macOS cb7e2c2a, same-machine identical |
| J3 | 1578.5 m residual at 8 km; STM 1e-12 | docs/JUDGE_PREP.md:77-78 | yes | reproduces | see R15/G27, G3, `python3 -c 'import math;print(500e3*math.tan(math.radians(1.5)))'`, out2/results.json (PR-AUC 0.99161), eps_leader_6sat.json:6 |
| J4 | slot holding 1.41e-12 m/s per orbit | docs/JUDGE_PREP.md:82 | yes | reproduces | see R15/G27, G3, `python3 -c 'import math;print(500e3*math.tan(math.radians(1.5)))'`, out2/results.json (PR-AUC 0.99161), eps_leader_6sat.json:6 |
| J5 | 961 grid points; r_f 13.09 km | docs/JUDGE_PREP.md:90-91 | yes | reproduces | see R15/G27, G3, `python3 -c 'import math;print(500e3*math.tan(math.radians(1.5)))'`, out2/results.json (PR-AUC 0.99161), eps_leader_6sat.json:6 |
| J6 | DEAD detection 4 s | docs/JUDGE_PREP.md:98 | yes | updated | 4 s labelled (K-1)*dt by construction |
| J7 | LightGBM 132 features, PR-AUC 0.9916 | docs/JUDGE_PREP.md:156-157 | yes | reproduces | see R15/G27, G3, `python3 -c 'import math;print(500e3*math.tan(math.radians(1.5)))'`, out2/results.json (PR-AUC 0.99161), eps_leader_6sat.json:6 |
| J8 | 260 s median warning lead | docs/JUDGE_PREP.md:157,439 | no | updated | 260 s relabelled as gain over EWMA; LGB lead 3979-4860 s; false alarms 0.4806/sat-orbit added |
| J9 | oracle +0.0235 pp, fuel up to 2.9x, CUT | docs/JUDGE_PREP.md:158-160,440 | no | updated | Gate-2 CUT (+0.0235 pp) and v2 CLEAR (+1.7968 / +10.6048 pp) each quoted with own command; 2.9x attributed to Gate-2 sweep only |
| J10 | trigger "+1.80 pp on pinned metric" | docs/JUDGE_PREP.md:161-163 | no | updated | trigger arm quoted separately (pinned +10.617, functional +0.047, coverage +0.1507 committed; regen flips recommend) |
| J11 | demo: 4 s, t=3114, 0.2698/0.2205, +4.93, ~31%, 3095.1, 193.68, 8517 lines | docs/JUDGE_PREP.md:186-189 | yes | updated | wording corrected (best-case pair, all-pairs vs survivor-dead, by construction); numbers unchanged |
| J12 | hungarian 0.26980 mean=worst; worst per-sat 251.24 | docs/JUDGE_PREP.md:195-196 | yes | updated | wording corrected (best-case pair, all-pairs vs survivor-dead, by construction); numbers unchanged |
| J13 | hungarian mean total dv 481.61 m/s | docs/JUDGE_PREP.md:196 | no | updated | mean total dv 481.61 -> 444.30 m/s (policies_summary.hungarian.mean_total_dv_mps) |
| J14 | do_nothing 0.29106/0.22045 | docs/JUDGE_PREP.md:197 | yes | updated | wording corrected (best-case pair, all-pairs vs survivor-dead, by construction); numbers unchanged |
| J15 | +4.93 worst pairs, -2.13 mean | docs/JUDGE_PREP.md:198-199,387 | yes | updated | wording corrected (best-case pair, all-pairs vs survivor-dead, by construction); numbers unchanged |
| J16 | even_split seat 3.4e-9 m from a corpse | docs/JUDGE_PREP.md:200 | no | updated | even_split 3.4e-9 m -> 722.8 m worst survivor-dead clearance |
| J17 | MC +4.886 / +5.201 / +4.545, 20/20 positive, std .0025 vs .0045 | docs/JUDGE_PREP.md:201-203 | yes | updated | numbers reproduce; scope added (one pair, four scalars, seed 7 crashes) |
| J18 | keepout CUT, 1322.6 with = without | docs/JUDGE_PREP.md:204-205 | no | updated | keep-out re-measured; 1322.6 m is hungarian_keepout; hungarian 1852.5 m |
| J19 | 155.09 vs 47.81 = 3.24x | docs/JUDGE_PREP.md:206-207 | yes | updated | dv reference ratios regenerated (3.24x same; mean 2.95x, worst 5.72x); 'physics floor' -> fixed-time two-impulse reference |
| J20 | mean 2.58x, worst 5.64x | docs/JUDGE_PREP.md:207,489 | no | updated | dv reference ratios regenerated (3.24x same; mean 2.95x, worst 5.72x); 'physics floor' -> fixed-time two-impulse reference |
| J21 | FastAPI ~18 routes; ~13.5k lines TS/TSX | docs/JUDGE_PREP.md:211-212 | unverified | updated | 18 routes (grep count) and 11,785 TS/TSX lines in this tree, with commands |
| J22 | replay load 0.337 s; compute 2.92-3.24 s | docs/JUDGE_PREP.md:214 | unverified | updated | replay load 0.24 s, run_scenario 1.74 s on M3; Windows numbers labelled |
| J23 | "13 committed scenario files = 12 + 1 meta" | docs/JUDGE_PREP.md:220 | no | updated | 17 tracked scenario files (`git ls-files data/scenarios | wc -l`) |
| J24 | 35 EVASIVE, first at 848.53 m, 0.5 m/s per episode | docs/JUDGE_PREP.md:224-225 | no | updated | 30 EVASIVE_MANEUVER events at HEAD (first 848.5281 m at t=0 unchanged) |
| J25 | live_12sat/16sat untracked | docs/JUDGE_PREP.md:282-284 | no | updated | live_12sat/16sat tracked; no committed logs/ledger rows |
| J26 | eps_leader_6sat sets reassign_on_degrade true | docs/JUDGE_PREP.md:300 | yes | reproduces | see R15/G27, G3, `python3 -c 'import math;print(500e3*math.tan(math.radians(1.5)))'`, out2/results.json (PR-AUC 0.99161), eps_leader_6sat.json:6 |
| J27 | 30-second and 50-second pitch numbers (4 s, 15 pairs, -2/+5) | docs/JUDGE_PREP.md:320-346 | yes | updated | wording corrected (best-case pair, all-pairs vs survivor-dead, by construction); numbers unchanged |
| J28 | 0.2698 floor vs 0.22045 | docs/JUDGE_PREP.md:410 | yes | updated | wording corrected (best-case pair, all-pairs vs survivor-dead, by construction); numbers unchanged |
| J29 | 22x VACCO budget; 47.81; 3.24x | docs/JUDGE_PREP.md:418-421 | unverified | unmeasured | VACCO 8.8 m/s is a cited figure; source not re-fetched (69 N-s / 8 kg = 8.63 m/s); text says so |
| J30 | "+1.80 pp ... +0.15 pp on coverage" | docs/JUDGE_PREP.md:442 | no | updated | trigger arm quoted separately (pinned +10.617, functional +0.047, coverage +0.1507 committed; regen flips recommend) |
| J31 | two_failure separation never below 3095.1 m; 15-pair worst survivor-dead 1322.6 m | docs/JUDGE_PREP.md:447-450 | no | updated | keep-out re-measured; 1322.6 m is hungarian_keepout; hungarian 1852.5 m |
| J32 | cascading_n8: 3 detections, 3 replans, recovered t=4280 s | docs/JUDGE_PREP.md:482-484 | no | updated | cascading_n8 recovered 5152.0 s at HEAD |
| J33 | PD spends 2.6-5.6x the floor | docs/JUDGE_PREP.md:488-489 | no | updated | dv reference ratios regenerated (3.24x same; mean 2.95x, worst 5.72x); 'physics floor' -> fixed-time two-impulse reference |
| J34 | 1578.5 m curve in cw_error_curve.csv | docs/JUDGE_PREP.md:497-498 | yes | reproduces | see R15/G27, G3, `python3 -c 'import math;print(500e3*math.tan(math.radians(1.5)))'`, out2/results.json (PR-AUC 0.99161), eps_leader_6sat.json:6 |
| J35 | Pareto: coverage AND dv flat across weights | docs/JUDGE_PREP.md:501-505 | no | updated | coverage flat; dv spans 425.76-469.34 m/s (not flat) |
| P1 | n = 1.106783e-3, period 5677.0 s | docs/PHYSICS_ENGINE_EXPLAINED.md:89-90 | yes | reproduces | unchanged text; re-checked via tests/test_hcw.py/test_pd.py -s, derivation arithmetic, allocate.py:44, sim.py:218 |
| P2 | STM errors 1.358e-12 / 5.597e-10 | docs/PHYSICS_ENGINE_EXPLAINED.md:117 | yes | reproduces | unchanged text; re-checked via tests/test_hcw.py/test_pd.py -s, derivation arithmetic, allocate.py:44, sim.py:218 |
| P3 | forced propagator 2.281e-13 / 2.323e-13 | docs/PHYSICS_ENGINE_EXPLAINED.md:125 | yes | reproduces | unchanged text; re-checked via tests/test_hcw.py/test_pd.py -s, derivation arithmetic, allocate.py:44, sim.py:218 |
| P4 | slot hold 1.403e-12 m/s, 2.144e-11 m | docs/PHYSICS_ENGINE_EXPLAINED.md:147 | yes | reproduces | unchanged text; re-checked via tests/test_hcw.py/test_pd.py -s, derivation arithmetic, allocate.py:44, sim.py:218 |
| P5 | 1 m/s vy0 error => 3 m/s, ~17 km/orbit | docs/PHYSICS_ENGINE_EXPLAINED.md:145 | yes | reproduces | unchanged text; re-checked via tests/test_hcw.py/test_pd.py -s, derivation arithmetic, allocate.py:44, sim.py:218 |
| P6 | PD 1 km / 2236 m numbers | docs/PHYSICS_ENGINE_EXPLAINED.md:176-177 | yes | reproduces | unchanged text; re-checked via tests/test_hcw.py/test_pd.py -s, derivation arithmetic, allocate.py:44, sim.py:218 |
| P7 | 12 candidate formations; 72 = `_SWEEP_SAMPLES` | docs/PHYSICS_ENGINE_EXPLAINED.md:265,9.2 | yes | reproduces | unchanged text; re-checked via tests/test_hcw.py/test_pd.py -s, derivation arithmetic, allocate.py:44, sim.py:218 |
| P8 | r_f 13,093 m; 961 points | docs/PHYSICS_ENGINE_EXPLAINED.md:310-311 | yes | reproduces | unchanged text; re-checked via tests/test_hcw.py/test_pd.py -s, derivation arithmetic, allocate.py:44, sim.py:218 |
| P9 | RECOVERED tolerance ~1.1 km | docs/PHYSICS_ENGINE_EXPLAINED.md:300 | yes | reproduces | unchanged text; re-checked via tests/test_hcw.py/test_pd.py -s, derivation arithmetic, allocate.py:44, sim.py:218 |
| P10 | Hungarian worst survivor-dead clearance 1322.6 m, field `hungarian.worst_min_sep_survivor_dead_m` | docs/PHYSICS_ENGINE_EXPLAINED.md:323,9.2 | no | updated | keep-out re-measured; 1322.6 m is hungarian_keepout; hungarian 1852.5 m |
| P11 | eps_leader dips to 959.4 m, evasion at t=2740 | docs/PHYSICS_ENGINE_EXPLAINED.md:186,324,9.1c | no | updated | eps_leader: evasion at 959.4 m, worst min_sep 868.0 m @2746 s |
| P12 | two_failure worst min_sep 3095.1 m @1620 s | docs/PHYSICS_ENGINE_EXPLAINED.md:325,9.2 | yes | updated | 3095.1 m defined as all-pairs, one pair |
| P13 | MC jitter spec +-10% / +-30 deg / x[0.9,1.1] | docs/PHYSICS_ENGINE_EXPLAINED.md:334-336 | yes | reproduces | unchanged text; re-checked via tests/test_hcw.py/test_pd.py -s, derivation arithmetic, allocate.py:44, sim.py:218 |
| P14 | macOS sha cb7e2c2a… vs pin 450d5371… | docs/PHYSICS_ENGINE_EXPLAINED.md:339 | yes | reproduces | unchanged text; re-checked via tests/test_hcw.py/test_pd.py -s, derivation arithmetic, allocate.py:44, sim.py:218 |
| P15 | two_failure events 1204/1208/1504/1508/3114; final dv list; coverage 0.2674 | docs/PHYSICS_ENGINE_EXPLAINED.md 9.1b | yes | reproduces | unchanged text; re-checked via tests/test_hcw.py/test_pd.py -s, derivation arithmetic, allocate.py:44, sim.py:218 |
| P16 | eps_leader RECOVERED 3664, summary 0.349 | docs/PHYSICS_ENGINE_EXPLAINED.md 9.1c | yes | reproduces | `cubesat.run` on eps_leader_6sat.json (3664.0 s, 0.349) and thruster_leader_6sat.json (do_no_harm_hold, 2406.0 s, 0.36693, two leaders) |
| P16b | thruster_leader_6sat do_no_harm_hold, summary 0.3669, two leaders | docs/PHYSICS_ENGINE_EXPLAINED.md 9.1c | unverified | reproduces | `cubesat.run` on eps_leader_6sat.json (3664.0 s, 0.349) and thruster_leader_6sat.json (do_no_harm_hold, 2406.0 s, 0.36693, two leaders) |
| P17 | even_split worst survivor-dead 3.4e-9 m | docs/PHYSICS_ENGINE_EXPLAINED.md 9.2 | no | updated | even_split 3.4e-9 m -> 722.8 m worst survivor-dead clearance |
| P18 | hungarian mean gain -2.13; worst retained 0.2698 vs 0.2205 | docs/PHYSICS_ENGINE_EXPLAINED.md 9.2 | yes | reproduces | benchmark_results.json mean -2.13 / worst 0.2698 vs 0.2205; CW curve maxima |
| P19 | MC mean gain +4.886 | docs/PHYSICS_ENGINE_EXPLAINED.md 9.2 | yes | updated | MC +4.886 reproduces; one-pair scope added |
| P20 | dv 155.09 vs 47.81, 3.24x | docs/PHYSICS_ENGINE_EXPLAINED.md 9.2 | yes | updated | dv reference ratios regenerated (3.24x same; mean 2.95x, worst 5.72x); 'physics floor' -> fixed-time two-impulse reference |
| P21 | CW error 3.101 / 1578.5 / 2984.5 | docs/PHYSICS_ENGINE_EXPLAINED.md 9.2,:8 | yes | reproduces | benchmark_results.json mean -2.13 / worst 0.2698 vs 0.2205; CW curve maxima |
| P22 | predictor +0.0235 pp => CUT | docs/PHYSICS_ENGINE_EXPLAINED.md 9.2 | no | updated | oracle row: Gate-2 CUT and v2 CLEAR both quoted |
| P23 | no RNG; seed never read | docs/PHYSICS_ENGINE_EXPLAINED.md:7 | yes | reproduces | unchanged text; re-checked via tests/test_hcw.py/test_pd.py -s, derivation arithmetic, allocate.py:44, sim.py:218 |
| P24 | demo needs ~5x thrust (0.8 N) | docs/PHYSICS_ENGINE_EXPLAINED.md:196 | no | updated | a_max 0.1 is 10x the default (5.3x the 150 mN figure) |
| F1 | "Failure detected in 4 s" | landing/LandingPage.tsx:15,26,67 | yes | reproduces | unchanged; frontend frozen; claim re-checked against regenerated artifacts |
| F2 | "Coverage restored 27.0% vs 22.1%" | frontend/src (audit C §5 frontend table):16,68 | yes | reproduces | unchanged; frontend frozen; claim re-checked against regenerated artifacts |
| F3 | "75 recovery runs - 15 pairs x 5 policies" | frontend/src (audit C §5 frontend table):17,69 | no | listed | frontend frozen: listed in docs/audit/2026-10-31-frontend-claims.md |
| F4 | "heals itself", "No ground command" | frontend/src (audit C §5 frontend table):32,157 | unverified | listed | frontend frozen: listed in docs/audit/2026-10-31-frontend-claims.md |
| F5 | n = 1.107e-3, orbit 94.6 min | pages/DocsPage.tsx:100 | yes | reproduces | unchanged; frontend frozen; claim re-checked against regenerated artifacts |
| F6 | CW error 3.1 m (1 km), 2984.5 m (11 km) | frontend/src (audit C §5 frontend table):114-115 | yes | reproduces | unchanged; frontend frozen; claim re-checked against regenerated artifacts |
| F7 | up to 193.68 m/s | frontend/src (audit C §5 frontend table):119 | yes | reproduces | unchanged; frontend frozen; claim re-checked against regenerated artifacts |
| F8 | "Four benchmark policies" (five listed) | frontend/src (audit C §5 frontend table):173-177 | no | listed | frontend frozen: listed in docs/audit/2026-10-31-frontend-claims.md |
| F9 | 15.91 / +4.93 / 4 s / t=3114 / 3095.1 / 193.68 | frontend/src (audit C §5 frontend table):213-217 | yes | reproduces | unchanged; frontend frozen; claim re-checked against regenerated artifacts |
| F10 | paired lead gain 260.0 s, 31/31 earlier, p ~ 9.3e-10, sudden 1/16 | frontend/src (audit C §5 frontend table):237-243 | yes | reproduces | unchanged; frontend frozen; claim re-checked against regenerated artifacts |
| F11 | family holdout 0/15 | frontend/src (audit C §5 frontend table):240-241 | unverified | listed | frontend frozen: listed in docs/audit/2026-10-31-frontend-claims.md |
| F12 | oracle max gain 0.0235 pp, CUT | frontend/src (audit C §5 frontend table):249-250 | no | listed | frontend frozen: listed in docs/audit/2026-10-31-frontend-claims.md |
| F13 | FIREFLY-1 NORAD 62701, 589.309 km, e 3.72e-4 | pages/FaqPage.tsx:18-20 | yes | reproduces | unchanged; frontend frozen; claim re-checked against regenerated artifacts |
| F14 | 3 missed heartbeats, 2 s ticks, 4 s | frontend/src (audit C §5 frontend table):35-36 | yes | reproduces | unchanged; frontend frozen; claim re-checked against regenerated artifacts |
| F15 | THRUSTER_OUT "invisible to failure detection by design" | frontend/src (audit C §5 frontend table):45-47 | no | listed | frontend frozen: listed in docs/audit/2026-10-31-frontend-claims.md |
| F16 | up to 193.68 m/s | frontend/src (audit C §5 frontend table):87 | yes | reproduces | unchanged; frontend frozen; claim re-checked against regenerated artifacts |
| F17 | "about 260 s median lead across 31/31" | frontend/src (audit C §5 frontend table):101-102 | no | listed | frontend frozen: listed in docs/audit/2026-10-31-frontend-claims.md |
| F18 | oracle 0.0235 pp CUT | frontend/src (audit C §5 frontend table):108-110 | no | listed | frontend frozen: listed in docs/audit/2026-10-31-frontend-claims.md |
| F19 | two surviving imagers end up 180 deg apart | pages/TutorialPage.tsx:107 | yes | reproduces | unchanged; frontend frozen; claim re-checked against regenerated artifacts |
| F20 | 4.00 s, t~3114, +4.93 | frontend/src (audit C §5 frontend table):111-113 | yes | reproduces | unchanged; frontend frozen; claim re-checked against regenerated artifacts |
| F21 | 17028 s ~ 28 min at 10x | frontend/src (audit C §5 frontend table):113-114 | yes | reproduces | unchanged; frontend frozen; claim re-checked against regenerated artifacts |
| F22 | heaviest sat 193.68 m/s | frontend/src (audit C §5 frontend table):147-149 | yes | reproduces | unchanged; frontend frozen; claim re-checked against regenerated artifacts |
| F23 | health = 0.5 cov + 0.3 formation + 0.2 safety | frontend/src (audit C §5 frontend table):153 | yes | reproduces | unchanged; frontend frozen; claim re-checked against regenerated artifacts |
| F24 | FAILURE_DETECTED within 4 s (live) | frontend/src (audit C §5 frontend table):207-208 | yes | reproduces | unchanged; frontend frozen; claim re-checked against regenerated artifacts |

## Totals

| status after | n |
|---|---|
| reproduces | 76 |
| updated | 63 |
| unmeasured | 3 |
| removed | 0 |
| listed | 8 |
| **total** | **150** |

No whole claim row was deleted; 5 phrases inside updated rows were removed (below).

Status before (audit C): yes 89, no 46, unverified 15.

## Removed phrases (not table rows)
- "a guaranteed floor of 0.2698" (JUDGE_PREP Q2): an unsupported adjective; replaced by the measured 0.2698 vs 0.22045 on the three imager-pair pairs.
- "worst-case protection" / "+4.93 on the worst pairs" framing (GATES P0, JUDGE_PREP pitch, Q&A): +4.93 is the best per-pair gain, not a floor; replaced by the critical-roles-held metric.
- "the exclusion never fired ... byte-identical" (GATES P2, JUDGE_PREP): superseded by the regenerated keep-out report.
- "3.4e-9 m from a coasting corpse" (JUDGE_PREP, PHYSICS): replaced by 722.8 m.
- "all 20 pairs positive" as a robustness claim: kept as a number with its one-pair scope.

## Items from the lead's specific list
| item | where | outcome |
|---|---|---|
| "critical roles 15/15 vs 6/15" | GATES, JUDGE_PREP, frontend Landing | now cites `benchmark_results.json` `policies_summary.*.pairs_critical_roles_held` |
| "9 pairs negative"; "mean 30.84%"; "+4.93 on the worst pairs" | GATES P0 | 9 negative pairs verified; "30.84%" appears in no scoped file; +4.93 reframed as the best-case pairs, mean -2.13 (-1.55 over 14 coverage-bearing pairs, recomputed) |
| "185 tests" | JUDGE_PREP | 224 collected (`uv run python -m pytest --collect-only -q`), 221 non-slow pass |
| scenario-file counts | JUDGE_PREP | 17 tracked (`git ls-files data/scenarios | wc -l`) |
| oracle / predictor sentences (C-7) | JUDGE_PREP, PHYSICS, GATES | "260 s" = gain over EWMA; Gate-2 CUT (+0.0235 pp) and v2 CLEAR (+1.7968 / +10.6048 pp) each with its own command; v3 trigger committed vs HEAD flip stated, never mixed |
| "3095.1 m" (C-10) | README, JUDGE_PREP, PHYSICS, GATES | defined as all-pairs min_sep of pair (1,2); 1852.5 m = worst survivor-dead over 15 pairs |
| "72 formations" | not found in scoped files | PHYSICS already says 12 candidate formations; 72 = `_SWEEP_SAMPLES`; correction recorded in GATES |
| "8 seconds" | not in scoped docs | GATES decisions entries say "8-second lag"; correction recorded (4 s = (K-1)*dt) without rewriting history |
| "AI predicts and heals" | not found verbatim | no edit needed in scoped docs; JUDGE_PREP AI paragraph rewritten to the measured verdicts |
| "44% EPS" | only docs/HANDOFF.md:466 (not scoped) | exact wording and its unverified status recorded in GATES; not used in the scoped docs |
| coverage-hours headline | not in scoped docs | no committed command; recorded as unmeasured in GATES |
| "4 s detection" (C-11) | README, JUDGE_PREP, PHYSICS, GATES | labelled (K-1)*dt = 2 x 2 s by construction, DEAD mode, K=3, dt=2 s |
| thrust arithmetic (C-13) | README, PHYSICS, GATES | 0.01 m/s^2 = 80 mN at 8 kg; 150 mN = 0.019 m/s^2; 0.1 m/s^2 = 800 mN |
| timing claims 4.6 / 11.6 / 32.2 s | map §1 and v2 plan (not the four scoped docs) | re-measured with the script in GATES.md: live_6sat 2.07 s, live_12sat 5.33 s, live_24sat 16.12 s (min of 3, M3, idle); the map/plan text was left as is (not in scope) |
