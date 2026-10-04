# Oracle value-of-warning sweep (Phase 2)
1. Scenarios: committed `nominal` and `two_failure`, plus 1-2 new scenarios where a failing sat holds the leader or downlink seat.
2. Add a gated default-off `oracle` block in the scenario JSON, byte-inert when absent.
3. At tick t_f - L the oracle knows each scheduled failure. Call standard `replan`, then one deterministic swap: any critical seat held by a soon-to-fail sat goes to the lowest-risk NOMINAL survivor (risk = 1 for sats failing within L, else 0; ties to lowest sat id).
4. Sweep L in {0, 30, 60, 300, 1800} s, capped at t_f - t_settle. Log Delta-v for every run.
5. Primary metric: critical-seat health fraction = share of sim time leader and downlink seats are held by NOMINAL sats. Also report coverage and total Delta-v.
6. Gate: if the gain at L=300 s is below my pre-declared threshold on every scenario, stop and recommend cutting the predictor.
