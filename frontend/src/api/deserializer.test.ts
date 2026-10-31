// Deserializer against real wire bytes captured from the backend (origin/backend
// 2a4c57f): a live engine-v2 run with every v2 fault injected, and a v1
// leader-failure run (fixtures in src/test/fixtures/, see their README).
import { describe, expect, it } from "vitest";
import { deserializeMessage } from "./deserializer";
import v2 from "../test/fixtures/v2_live.json";
import v1 from "../test/fixtures/v1_leader_failure.json";

const frames = (msgs: unknown[]) =>
  msgs.map((m) => deserializeMessage(m)).flatMap((d) => (d?.kind === "frame" ? [d.frame] : []));

describe("v2 sim_state satellites", () => {
  const last = frames(v2).at(-1)!;
  const sat = (id: string) => last.satellites.find((s) => s.id === id)!;

  it("keeps the raw v2 status for the label while the wire status drives colour", () => {
    expect(sat("SAT-2").status).toBe("degraded");
    expect(sat("SAT-2").failureType).toBe("FUEL_DEPLETED");
    expect(sat("SAT-4").failureType).toBe("RADIO_SILENT");
    expect(sat("SAT-3").failureType).toBe("PAYLOAD_FAILED");
    expect(sat("SAT-1").status).toBe("failed");
  });

  it("parses fuel, thrust health and subsystem flags", () => {
    const s2 = sat("SAT-2");
    expect(s2.fuelMpsLeft).toBe(0);
    expect(s2.fuelKg).toBe(0);
    expect(s2.thrust).toBe(0);
    expect(s2.stuck).toBe(true);
    expect(sat("SAT-3").payloadOk).toBe(false);
    expect(sat("SAT-4").radioOk).toBe(false);
    expect(sat("SAT-5").thrust).toBe(0.5);
    expect(sat("SAT-6").fuelMpsLeft).toBeGreaterThan(19);
  });

  it("parses roles, original_role and old_role", () => {
    expect(sat("SAT-3").roles).toEqual(["leader"]); // camera failed, so it no longer images
    expect(sat("SAT-3").role).toBe("leader");
    expect(sat("SAT-4").roles).toEqual(["spare"]);
    expect(sat("SAT-1").roles).toEqual([]);
    expect(sat("SAT-1").role).toBe("none");
    expect(sat("SAT-4").originalRole).toBe("imager");
    const handoffTick = frames(v2).find((f) => f.simTime === 1912)!;
    expect(handoffTick.satellites.find((s) => s.id === "SAT-3")!.oldRole).toBe("spare");
  });

  it("leaves v2 keys absent on v1 satellites", () => {
    const s = frames(v1)[0].satellites[0];
    expect(s.fuelMpsLeft).toBeUndefined();
    expect(s.roles).toBeUndefined();
    expect(s.payloadOk).toBeUndefined();
  });
});

describe("events", () => {
  it("keeps sat_id, and from/to/label on state events", () => {
    const evs = (v1 as unknown[]).map((m) => deserializeMessage(m)).flatMap((d) => (d?.kind === "event" ? [d.event] : []));
    expect(evs[0].satId).toBe("SAT-1");
    const st = evs.find((e) => e.label !== undefined)!;
    expect(st).toMatchObject({ from: "FAILURE_DETECTED", to: "REPLANNING", label: "Planning recovery" });
  });

  it("keeps every event on the same tick", () => {
    const at1912 = (v2 as unknown[])
      .map((m) => deserializeMessage(m))
      .flatMap((d) => (d?.kind === "event" && d.event.simTime === 1912 ? [d.event] : []));
    expect(at1912).toHaveLength(2);
  });
});

describe("role_reassignment and run_summary", () => {
  const ds = (v1 as unknown[]).map((m) => deserializeMessage(m));

  it("parses method, kept_formation and role_handoffs", () => {
    const r = ds.find((d) => d?.kind === "reassignment");
    expect(r?.kind).toBe("reassignment");
    if (r?.kind !== "reassignment") return;
    expect(r.reassignment.method).toBe("do_no_harm_hold");
    expect(r.reassignment.kept_formation).toBe(true);
    expect(r.reassignment.role_handoffs).toEqual([
      { role: "leader", from_sat: "SAT-1", to_sat: "SAT-3" },
      { role: "downlink", from_sat: "SAT-6", to_sat: "SAT-5" },
    ]);
  });

  it("parses run_summary instead of dropping it", () => {
    const s = (v2 as unknown[]).map((m) => deserializeMessage(m)).find((d) => d?.kind === "summary");
    expect(s).toMatchObject({
      kind: "summary",
      summary: { coverageMeanLastOrbit: expect.closeTo(0.252, 3), simTime: 5676 },
    });
  });
});
