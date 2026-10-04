// SideTabs — the tabbed-sidebar primitive (round 2 verdict: "make it a
// multiple-tab sidebar where each part can be seen as tabs"). Underline tab
// indicator (§13.3: never sliding-pill tabs), roving tabindex + arrow keys
// (same pattern as RightPanel's telemetry tabs), one panel visible at a time.
import { useId, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import styles from "./SideTabs.module.css";

export interface SideTab {
  id: string;
  label: string;
  content: ReactNode;
}

interface SideTabsProps {
  /** tablist aria-label, e.g. "Console sidebar" */
  label: string;
  tabs: SideTab[];
  /** Documented slot: an extra tab appended LAST when provided. The live page
   * mounts its scenario Builder here by rendering
   * <LeftPanel builder={<BuilderPanel />} /> (LeftPanel forwards the prop). */
  builder?: ReactNode;
  builderLabel?: string;
}

export default function SideTabs({ label, tabs, builder, builderLabel = "Builder" }: SideTabsProps) {
  const uid = useId();
  const allTabs: SideTab[] =
    builder !== undefined ? [...tabs, { id: "builder", label: builderLabel, content: builder }] : tabs;
  const [active, setActive] = useState(allTabs[0]?.id ?? "");
  const activeTab = allTabs.find((t) => t.id === active) ?? allTabs[0];

  function onTabKeyDown(e: KeyboardEvent<HTMLDivElement>): void {
    if (activeTab === undefined || allTabs.length === 0) return;
    const idx = allTabs.findIndex((t) => t.id === activeTab.id);
    let next: number;
    if (e.key === "ArrowRight") next = (idx + 1) % allTabs.length;
    else if (e.key === "ArrowLeft") next = (idx + allTabs.length - 1) % allTabs.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = allTabs.length - 1;
    else return;
    e.preventDefault();
    setActive(allTabs[next].id);
    document.getElementById(`${uid}-tab-${allTabs[next].id}`)?.focus();
  }

  return (
    <>
      <div role="tablist" aria-label={label} className={styles.tabs} onKeyDown={onTabKeyDown}>
        {allTabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`${uid}-tab-${t.id}`}
            aria-selected={activeTab?.id === t.id}
            aria-controls={`${uid}-panel`}
            tabIndex={activeTab?.id === t.id ? 0 : -1}
            className={styles.tab}
            data-active={activeTab?.id === t.id}
            onClick={() => setActive(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div
        role="tabpanel"
        id={`${uid}-panel`}
        aria-labelledby={activeTab === undefined ? undefined : `${uid}-tab-${activeTab.id}`}
        className={styles.panel}
      >
        {activeTab?.content}
      </div>
    </>
  );
}
