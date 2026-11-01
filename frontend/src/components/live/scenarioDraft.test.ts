import { describe, expect, it } from "vitest";
import {
  FORMATION_SHAPES,
  FORMATION_SHAPE_LABEL,
  buildScenario,
  defaultRoles,
  type BuilderNumbers,
  type FailureRow,
} from "./scenarioDraft";

const NUMS: BuilderNumbers = {
  name: "live_6sat",
  seed: 42,
  durationS: 17028,
  dtS: 2,
  altitudeKm: 500,
  radialAmpKm: 8,
  phaseOffsetDeg: 0,
  aMax: 0.1,
  wn: 0.01,
  zeta: 1,
  fovHalfAngleDeg: 1.5,
  gridStepKm: 2,
  gridExtentKm: 30,
};

const FAILS: FailureRow[] = [
  { key: 1, satId: 2, t: 1200, mode: "DEAD" },
  { key: 2, satId: 4, t: 300, mode: "EPS_DEGRADE" },
];

// Output of buildScenario before the formation picker existed (frozen literal):
// the cartwheel default must stay byte-identical so every saved scenario and
// the v1 engine path are untouched.
const CARTWHEEL_BEFORE =
  '{"name":"live_6sat","seed":42,"duration_s":17028,"dt_s":2,' +
  '"chief":{"altitude_km":500},' +
  '"formation":{"n_slots":6,"radial_amp_km":8,"phase_offset_deg":0},' +
  '"a_max_mps2":0.1,"gains":{"wn":0.01,"zeta":1},' +
  '"sensor":{"fov_half_angle_deg":1.5,"grid_step_km":2,"grid_extent_km":30},' +
  '"roles":["leader","imager","imager","imager","imager","downlink"],' +
  '"failures":[{"t":1200,"sat_id":2,"mode":"DEAD"},' +
  '{"t":300,"sat_id":4,"mode":"EPS_DEGRADE","degrade_s":600}]}';

describe("buildScenario formation shape", () => {
  it("lists the five backend shapes with plain labels", () => {
    expect(FORMATION_SHAPES).toEqual(["cartwheel", "pco", "gco", "helix", "string"]);
    expect(FORMATION_SHAPE_LABEL.cartwheel).toBe("Cartwheel");
    expect(FORMATION_SHAPE_LABEL.pco).toBe("Projected circular");
    expect(FORMATION_SHAPE_LABEL.gco).toBe("General circular");
    expect(FORMATION_SHAPE_LABEL.helix).toBe("Helix");
    expect(FORMATION_SHAPE_LABEL.string).toBe("String");
  });

  it("keeps the cartwheel output byte-identical (no shape, no engine key)", () => {
    const roles = defaultRoles(6);
    expect(JSON.stringify(buildScenario(NUMS, roles, FAILS))).toBe(CARTWHEEL_BEFORE);
    expect(JSON.stringify(buildScenario(NUMS, roles, FAILS, "cartwheel"))).toBe(
      CARTWHEEL_BEFORE,
    );
  });

  it("helix writes formation.shape and engine v2", () => {
    const out = buildScenario(NUMS, defaultRoles(6), FAILS, "helix");
    expect(out.engine).toBe("v2");
    expect(out.formation).toEqual({
      n_slots: 6,
      radial_amp_km: 8,
      phase_offset_deg: 0,
      shape: "helix",
    });
    // Everything else is the same as the cartwheel draft.
    const { engine: _e, formation: _f, ...rest } = out;
    const base = JSON.parse(CARTWHEEL_BEFORE) as Record<string, unknown>;
    delete base.formation;
    expect(rest).toEqual(base);
  });

  it("every non-cartwheel shape asks for engine v2", () => {
    for (const s of FORMATION_SHAPES.filter((x) => x !== "cartwheel")) {
      const out = buildScenario(NUMS, defaultRoles(6), [], s);
      expect(out.engine).toBe("v2");
      expect((out.formation as Record<string, unknown>).shape).toBe(s);
    }
  });
});
