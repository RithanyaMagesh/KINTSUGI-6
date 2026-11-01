Real wire messages captured from `origin/backend` 2a4c57f over `/ws/state`, trimmed to the ticks the tests need (chief/station keys dropped).

- `v2_live.json`: `formation_cartwheel_6sat.json` (engine v2), seed 42, live; injected PAYLOAD_FAIL SAT-3, RADIO_FAIL SAT-4, PARTIAL_THRUST SAT-5, THRUSTER_STUCK_OPEN SAT-2, DEAD SAT-1.
- `v1_leader_failure.json`: `leader_failure_6sat.json` (engine v1), seed 42, live; first failure (kept-formation hold with leader and downlink handoffs).

Track C (origin/backend d65c562, captured 2026-11-01, live at speed 1000, sim 1100–1600 s kept, chief/station/orbit_ring/ground_track dropped):
- `decentral_laser.json`: decentral_leader_kill_6sat (laser mesh, consensus auction). SAT-1 dies at 1200; sun splits the swarm 1352–1512 (split-brain).
- `central_laser.json`: central_star_leader_kill_6sat (laser star). The hub dies at 1200 and every sat is cut off until 1234; SAT-3 cut off by the sun 1352–1512.
