// Mission-brief copy as structured data, so the brief and any other surface
// (help modal, presentation notes) reuse the exact same words. Every claim
// traces to a spec: FRONTEND_SPEC §4 (narrative), §6.1/§6.2 (modes), §7.5
// (metric sources), §8.7 (health score), Appendix C (scenario wording),
// Appendix D (suspect), AGENTS.md invariants 4-6 (frame, assignment). No
// invented mission facts, no numbers the specs do not state (repo invariant 1).
import { STATE_SPINE } from "../../types/satellite";

export const briefIntro = {
  productName: "Swarm console",
  title: "Mission brief",
  paragraphs: [
    "Swarm console is the mission-control view for a hypothetical 6-satellite formation-flying swarm on the real orbit of FIREFLY-1 (Pixxel). The swarm is hypothetical — it does not exist; only the chief's orbit is real (spec Appendix C).",
    "Physics: Clohessy-Wiltshire relative dynamics in the LVLH frame — x radial, y along-track, z cross-track. Everything on screen is computed by the same engine that writes the committed logs; no number appears unless the stream carries it, otherwise you will see the word unmeasured.",
  ],
} as const;

export const briefModes = [
  {
    name: "Live",
    text: "Live runs the physics engine now. The console connects to the backend over a WebSocket: start the simulation, inject failures, and watch the swarm detect, replan, and recover in real time (spec §6.1).",
  },
  {
    name: "Replay",
    text: "Replay scrubs a recorded run deterministically through the same console — same physics, frozen evidence. Replay reads the same JSONL logs the simulator writes, so the live demo always has a scripted fallback (spec §6.2).",
  },
] as const;

export const recoveryIntro =
  "A failure is not the end of the demo — it is the story. When a satellite stops reporting heartbeats, the survivors heal the formation:";

export const recoverySteps = [
  "Detect — the swarm notices the missing heartbeat: FAILURE_DETECTED.",
  "Replan — a Hungarian assignment (rows = survivors, columns = candidate slots) gives every survivor a new formation slot.",
  "Reconfigure — PD-controlled burns fly each satellite to its new slot.",
  "Recover — coverage and formation error come back: RECOVERED.",
] as const;

/** The story spine — the same literals the timeline spine (§13.5) tracks,
 * imported from the shared state list so copy and UI cannot drift. */
export const stateChain: readonly string[] = STATE_SPINE;

export interface GlossaryEntry {
  term: string;
  definition: string;
}

export const glossary: GlossaryEntry[] = [
  {
    term: "Ground coverage",
    definition:
      "The fraction of ground covered by the imagers' footprints over time — the primary mission metric, read from the coverage value in the log. The story is the change: steady, then a drop at failure, then recovery after replanning (spec §7.5).",
  },
  {
    term: "Minimum separation",
    definition:
      "The smallest distance between any two satellites in the swarm, in metres — the safety and collision-avoidance metric (spec §7.5, min_sep).",
  },
  {
    term: "Mission health score",
    definition:
      "One judge-friendly number derived only from measured inputs: 0.5 × ground coverage + 0.3 × formation quality + 0.2 × safety (spec §8.7).",
  },
  {
    term: "Delta-v (Δv)",
    definition:
      "The velocity change the thrusters have spent, in m/s — the thrust budget consumed flying to new formation slots (spec §7.5, dv_used).",
  },
  {
    term: "Detection latency",
    definition:
      "How long the swarm took to notice a failure: the time from the failure to its detection, t_detect − t_fail, shown at the failure tick on the timeline (spec §7.5).",
  },
  {
    term: "Suspect",
    definition:
      "A failure-risk annotation for a satellite that still reports heartbeats but shows rule-based signs of degradation. It is an annotation, not a satellite status. The learned predictor is a sealed LightGBM pipeline (trained on synthetic degradation — strong on trained families, it does not generalize to unseen fault families, and sudden death is unpredictable by construction); when its risk rides the wire the suspect label arms early. A suspect alert arrives as an ordinary warning event (spec Appendix D).",
  },
];

/** Verbatim fallback copy when the backend lists no replay logs — same
 * sentence SwarmScene's §20.1 fallback shows (§13.6: one voice). */
export const replayEmptyHint =
  "No replay logs available. Generate one with: uv run python -m cubesat.run";

export const reopenHint = "Reopen this brief anytime with the ? button in the top bar.";
