// The panel's copy of the backend's inject checks, on real captured frames.
import { expect, it } from "vitest";
import { deserializeMessage } from "../../api/deserializer";
import v2 from "../../test/fixtures/v2_live.json";
import v1 from "../../test/fixtures/v1_leader_failure.json";
import { injectBlock, isV2 } from "./injectRules";

const lastFrame = (msgs: unknown[]) =>
  msgs.map((m) => deserializeMessage(m)).flatMap((d) => (d?.kind === "frame" ? [d.frame] : [])).at(-1)!;

it("v2: dead satellites are refused, damaged ones can fail again", () => {
  const sats = lastFrame(v2).satellites;
  expect(isV2(sats)).toBe(true);
  const block = (id: string) => injectBlock(sats.find((s) => s.id === id)!, true);
  expect(block("SAT-1")).toBe("lost");
  expect(block("SAT-2")).toBeNull(); // out of fuel, still flying
  expect(block("SAT-3")).toBeNull(); // camera failed
});

it("v1: a satellite that already failed is refused", () => {
  const sats = lastFrame(v1).satellites;
  expect(isV2(sats)).toBe(false);
  expect(injectBlock(sats.find((s) => s.id === "SAT-1")!, false)).toBe("lost");
  expect(injectBlock(sats.find((s) => s.id === "SAT-2")!, false)).toBeNull();
});
