Real wire messages captured from `origin/backend` 2a4c57f over `/ws/state`, trimmed to the ticks the tests need (chief/station keys dropped).

- `v2_live.json`: `formation_cartwheel_6sat.json` (engine v2), seed 42, live; injected PAYLOAD_FAIL SAT-3, RADIO_FAIL SAT-4, PARTIAL_THRUST SAT-5, THRUSTER_STUCK_OPEN SAT-2, DEAD SAT-1.
- `v1_leader_failure.json`: `leader_failure_6sat.json` (engine v1), seed 42, live; first failure (kept-formation hold with leader and downlink handoffs).
