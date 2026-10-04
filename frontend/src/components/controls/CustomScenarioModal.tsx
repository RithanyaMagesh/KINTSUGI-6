// Add-your-own-scenario dialog — POST /scenarios/upload (cubesat/api.py
// UploadRequest: {name: str | null, scenario: dict}). JSON is validated
// client-side with JSON.parse and an inline error; the server stays the
// schema authority (its 422 detail is shown verbatim). The reference shape
// below is the committed scenarios' schema: top-level keys from
// data/scenarios/nominal.json, one failure entry from
// data/scenarios/two_failure.json. Escape and overlay click cancel; focus
// starts on the name field.
import { useEffect, useRef, useState } from "react";
import { uploadScenario } from "../../api/scenarios";
import chrome from "../../styles/chrome.module.css";
import styles from "./CustomScenarioModal.module.css";

const EXAMPLE_SHAPE = `{
  "name": "my_scenario",
  "seed": 42,
  "duration_s": 5676.0,
  "dt_s": 2.0,
  "chief": {"altitude_km": 500.0},
  "formation": {"n_slots": 6, "radial_amp_km": 11.0, "phase_offset_deg": 0.0},
  "a_max_mps2": 0.01,
  "gains": {"wn": 0.01, "zeta": 1.0},
  "sensor": {"fov_half_angle_deg": 1.5, "grid_step_km": 2.0, "grid_extent_km": 30.0},
  "roles": ["leader", "imager", "imager", "imager", "imager", "downlink"],
  "failures": [{"t": 1200.0, "sat_id": 1, "mode": "DEAD"}]
}`;

interface Props {
  onClose: () => void;
  /** filename is null when the backend did not report the saved name;
   * listing is the refreshed GET /scenarios result (null when unavailable). */
  onUploaded: (filename: string | null, listing: string[] | null) => void;
}

export default function CustomScenarioModal({ onClose, onUploaded }: Props) {
  const [name, setName] = useState("");
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function submit(): Promise<void> {
    setError(null);
    let scenario: object;
    try {
      const parsed: unknown = JSON.parse(text);
      if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
        setError("Scenario must be a single JSON object.");
        return;
      }
      scenario = parsed as object;
    } catch (err) {
      setError(`Invalid JSON: ${err instanceof Error ? err.message : "could not parse"}`);
      return;
    }
    setBusy(true);
    try {
      const trimmed = name.trim();
      // Absent name -> the backend saves as "custom" (cubesat/api.py
      // _sanitize_scenario_name).
      const result = await uploadScenario(trimmed === "" ? null : trimmed, scenario);
      onUploaded(result.filename, result.scenarios);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Add your own scenario"
        aria-busy={busy}
        className={styles.modal}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className={chrome.panelTitle}>Add your own scenario</h3>
        <div className={styles.field}>
          <label className={chrome.fieldLabel} htmlFor="custom-scenario-name">
            Name (optional)
          </label>
          <input
            id="custom-scenario-name"
            ref={nameRef}
            className={chrome.input}
            type="text"
            value={name}
            disabled={busy}
            onChange={(e) => setName(e.target.value)}
          />
          <p className={chrome.hint}>Letters, digits, - and _ only. Defaults to custom.</p>
        </div>
        <div className={styles.field}>
          <label className={chrome.fieldLabel} htmlFor="custom-scenario-json">
            Scenario JSON
          </label>
          <textarea
            id="custom-scenario-json"
            className={styles.textarea}
            value={text}
            disabled={busy}
            rows={10}
            spellCheck={false}
            placeholder="Paste a scenario object"
            aria-invalid={error !== null}
            onChange={(e) => setText(e.target.value)}
          />
        </div>
        {error !== null && (
          <p className={chrome.errorText} role="alert">
            {error}
          </p>
        )}
        <div className={styles.reference}>
          <p className={chrome.fieldLabel}>
            Same schema as the committed scenarios (data/scenarios/*.json):
          </p>
          <pre className={styles.example}>{EXAMPLE_SHAPE}</pre>
        </div>
        <div className={chrome.btnRow}>
          <button className={chrome.btn} disabled={busy || text.trim() === ""} onClick={() => void submit()}>
            Save scenario
          </button>
          <button className={chrome.btn} disabled={busy} onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
