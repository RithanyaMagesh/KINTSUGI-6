// Plain labels for v2 satellites, from the real captured v2 frame.
import { expect, it } from "vitest";
import { deserializeMessage } from "../../api/deserializer";
import v2 from "../../test/fixtures/v2_live.json";
import { rolesLabel, satLabel } from "./hudFormat";

const last = (v2 as unknown[])
  .map((m) => deserializeMessage(m))
  .flatMap((d) => (d?.kind === "frame" ? [d.frame] : []))
  .at(-1)!;
const sat = (id: string) => last.satellites.find((s) => s.id === id)!;

it("names why each v2 satellite is degraded, and its roles", () => {
  expect(satLabel(sat("SAT-1"))).toBe("Lost");
  expect(satLabel(sat("SAT-2"))).toBe("Out of fuel");
  expect(satLabel(sat("SAT-3"))).toBe("Camera failed");
  expect(satLabel(sat("SAT-4"))).toBe("Radio silent");
  expect(satLabel(sat("SAT-5"))).toBe("50% thrust");
  expect(rolesLabel(sat("SAT-1"))).toBe("No role");
  expect(rolesLabel(sat("SAT-4"))).toBe("Spare");
});
