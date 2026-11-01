# KINTSUGI-6 — Earth view: true-to-physics constellation visualisation (spec)

(Verbatim from the user, 2026-10-31 evening. Supplements master map V1/V2 and §11; order: backend item 1 → frontend 1–3 (formation) → backend 2 → frontend 4.)

**Goal:** an Earth view like a constellation visualization (globe, orbit rings, satellite dots) that is TRUE to the physics engine. Delete the fake mapping in sceneSatellites.ts `lvlhToScene()` "global" mode (it stretches formation phase around the whole orbit).

## BACKEND (backend session)
1. Each sim_state carries `chief: {r_eci:[x,y,z] m, lat_deg, lon_deg, alt_m}` and hello carries `epoch_utc`, `inclination_deg`, `raan_deg`, plus `orbit_ring`: 256 ECI points of one chief period (from truth model / J2 propagation) and `ground_track`: lat/lon samples for ±1 orbit. Per-sat positions stay LVLH (unchanged).
2. Constellation mode (engine v2, scenario `layout: "formation" | "constellation"`): Walker 6/3/1 at 500 km (i 97.4° default, labelled illustrative), each sat propagated in ECI by the truth model; per-sat `r_eci` in the wire. Recovery in this mode = in-plane re-phasing: survivors re-space to equal angles. Phasing Δv (two burns) = (2/3)·v·Δθ/(2π·k) for k revolutions; choose k from the fuel budget; certificate checks fuel. Benchmark Δv and time-to-even-spacing; commit artifacts.

## FRONTEND (frontend session; load frontend-design skill)
1. Globe: Earth at true scale, orbit ring(s) from `orbit_ring`, satellites as glowing dots at true ECI→scene positions, ground track faint on the surface, the ground station (Bengaluru) as a marker with its visibility cone when a pass is active. Earth rotates at the real rate × time-warp. Sun lighting from the sim's sun vector (day/night terminator).
2. Formation mode: the swarm is ONE cluster dot on the ring; a "Formation lens" inset is anchored to it with a leader line, showing true LVLH geometry (ellipses, 2 km keep-out rings, scale bar, "↓ Earth" and "→ direction of flight" arrows).
3. Director: on failure → camera flies from globe into the lens; shows old slots (dashed), planned paths, role batons; on RECOVERED → seams turn gold → camera pulls back to the globe.
4. Constellation mode: each sat is its own dot on its own plane's ring (colour per plane); a dead sat greys out and drifts; survivors slide to even spacing; a coverage-gap arc on the ring shrinks as they re-space; a time-warp badge always visible ("×600").
5. Colours: failed red, in-transit amber, healthy green, repaired = gold only. Hex only in tokens.css. Reduced motion respected. 60 fps at 1920×1080; check 1280×720.
6. Visual QA: screenshot globe, lens, mid-repair, recovered, constellation-mode before/after; a judge must see what broke and that it healed within 10 s, no narration.
