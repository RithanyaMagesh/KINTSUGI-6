// Mission brief — the first-load landing page / FAQ / docs in one modal
// (FRONTEND_SPEC §3 users, §4 narrative, §6 modes, Appendix C/D wording).
// Shown once per browser session (sessionStorage flag lives in uiStore);
// the top-bar "?" button reopens it. Solid panel over a solid page-ground
// scrim (§13.3: modal shadow is the one allowed shadow — not needed here, the
// full-screen scrim carries separation). "Open replay mode" sets
// uiStore.replayModeRequested AND loads the latest replay log directly — the
// same path as SwarmScene's §20.1 fallback button — so the button works even
// though no component consumes the flag yet.
import { Fragment, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { backend } from "../../api/backend";
import { useSimStore } from "../../stores/simStore";
import { useReplayStore } from "../../stores/replayStore";
import { useUiStore } from "../../stores/uiStore";
import { missionStateColor } from "../../utils/colors";
import { isMissionState } from "../../types/satellite";
import {
  briefIntro,
  briefModes,
  glossary,
  recoveryIntro,
  recoverySteps,
  reopenHint,
  replayEmptyHint,
  stateChain,
} from "./helpContent";
import chrome from "../../styles/chrome.module.css";
import styles from "./MissionBrief.module.css";

export default function MissionBrief() {
  const setReplayModeRequested = useUiStore((s) => s.setReplayModeRequested);
  const exploreRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const close = (): void => setOpen(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    exploreRef.current?.focus(); // keyboard entry point = the primary action
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (!open) return null;

  // Same loader as ReplayControls.loadSelected / SwarmScene.openReplay:
  // backend drives replay, frames arrive over the shared /ws/state socket.
  // The log duration is NOT fetched here — ReplayControls measures it itself
  // whenever a replay session is active with an unread duration, so the scrub
  // slider appears without a manual reload (measured values only, none
  // guessed — repo invariant 1).
  async function openReplayMode(): Promise<void> {
    setReplayModeRequested(true);
    setBusy(true);
    setError(null);
    try {
      const { files } = await backend.replayFiles();
      if (files.length === 0) {
        setError(replayEmptyHint);
        return;
      }
      const latest = files[files.length - 1];
      await backend.replayLoad(latest);
      useSimStore.getState().reset();
      useReplayStore.getState().setActiveFile(latest);
      useReplayStore.getState().setIsPlaying(true);
      useSimStore.getState().setMode("replay");
      close();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Replay could not be loaded");
    } finally {
      setBusy(false);
    }
  }

  return createPortal(
    <div className={styles.scrim}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="mission-brief-title"
        className={styles.panel}
      >
        <header className={styles.header}>
          <span className={styles.product}>{briefIntro.productName}</span>
          <h2 id="mission-brief-title" className={styles.title}>
            {briefIntro.title}
          </h2>
        </header>

        <div className={styles.body}>
          <section className={styles.section}>
            <h3 className={styles.heading}>What this is</h3>
            {briefIntro.paragraphs.map((p) => (
              <p key={p.slice(0, 24)} className={styles.p}>
                {p}
              </p>
            ))}
          </section>

          <section className={styles.section}>
            <h3 className={styles.heading}>Live and replay</h3>
            {briefModes.map((m) => (
              <p key={m.name} className={styles.p}>
                <strong className={styles.modeName}>{m.name}. </strong>
                {m.text}
              </p>
            ))}
          </section>

          <section className={styles.section}>
            <h3 className={styles.heading}>How recovery works</h3>
            <p className={styles.p}>{recoveryIntro}</p>
            <ol className={styles.steps}>
              {recoverySteps.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ol>
            <p className={styles.chain} aria-label="Mission state machine">
              {stateChain.map((s, i) => (
                <Fragment key={s}>
                  {i > 0 && (
                    <span className={styles.chainArrow} aria-hidden="true">
                      →
                    </span>
                  )}
                  <span style={{ color: missionStateColor(isMissionState(s) ? s : null) }}>{s}</span>
                </Fragment>
              ))}
            </p>
          </section>

          <section className={styles.section}>
            <h3 className={styles.heading}>Glossary</h3>
            <dl className={styles.glossary}>
              {glossary.map((g) => (
                <Fragment key={g.term}>
                  <dt className={styles.dt}>{g.term}</dt>
                  <dd className={styles.dd}>{g.definition}</dd>
                </Fragment>
              ))}
            </dl>
          </section>
        </div>

        <footer className={styles.footer}>
          {/* min-height 1.4em always reserved: the error line never shifts layout (§13.3) */}
          <p className={chrome.errorText} role="alert">
            {error ?? ""}
          </p>
          <div className={styles.footerRow}>
            <button ref={exploreRef} className={chrome.btn} onClick={close} disabled={busy}>
              Explore the console
            </button>
            <button
              className={chrome.btn}
              onClick={() => void openReplayMode()}
              disabled={busy}
            >
              Open replay mode
            </button>
            <span className={styles.reopenHint}>{reopenHint}</span>
          </div>
        </footer>
      </div>
    </div>,
    document.body,
  );
}
