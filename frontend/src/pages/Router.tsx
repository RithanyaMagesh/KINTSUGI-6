// Hash router (round 2), hand-rolled: no new deps (the stack is locked; no
// react-router). Routes: #/ landing, #/live, #/replay, #/tutorial, #/faq,
// #/docs; unknown or missing hashes resolve to landing (uiStore.routeFromHash).
//
// PAGE SLOTS: pages plug in WITHOUT editing this file. Drop a file named
//   frontend/src/pages/LandingPage.tsx | LivePage.tsx | ReplayPage.tsx |
//   TutorialPage.tsx | FaqPage.tsx | DocsPage.tsx
// with a default export and the Vite glob below picks it up on the next
// build. ../components/pages/*Page.tsx is scanned too (the docs/FAQ/tutorial
// agents landed there first; src/pages/ stays the documented home and wins
// if a name exists in both). Until a page lands, its route renders the
// fallback below:
//   #/live and #/replay -> today's working console layout (never ship a
//   broken build — the demo must run even if the page agents are late),
//   the document pages -> a minimal "Page under construction" panel.
import { useEffect } from "react";
import type { ComponentType } from "react";
import { useUiStore, routeFromHash } from "../stores/uiStore";
import type { Route } from "../stores/uiStore";
import PageShell from "./PageShell";
import LeftPanel from "../components/layout/LeftPanel";
import CenterPanel from "../components/layout/CenterPanel";
import RightPanel from "../components/layout/RightPanel";
import BottomPanel from "../components/layout/BottomPanel";
import appStyles from "../App.module.css";

const pageModules = import.meta.glob(["./*Page.tsx", "../components/pages/*Page.tsx"], {
  eager: true,
}) as Record<string, { default?: ComponentType }>;

function slot(name: string): ComponentType | null {
  const suffix = `/${name}.tsx`;
  const paths = Object.keys(pageModules).filter((p) => p.endsWith(suffix));
  // Deterministic: the documented src/pages/ slot wins over components/pages/.
  paths.sort((a, b) =>
    a.startsWith("./") === b.startsWith("./") ? a.localeCompare(b) : a.startsWith("./") ? -1 : 1,
  );
  for (const path of paths) {
    const mod = pageModules[path];
    if (typeof mod?.default === "function") {
      return mod.default;
    }
  }
  return null;
}

// Bridge: #/live and #/replay keep today's console until the live/replay page
// components land (this is also what makes the router run standalone).
function ConsoleFallback() {
  return (
    <div className={appStyles.console}>
      <div className={appStyles.main}>
        <LeftPanel />
        <CenterPanel />
        <RightPanel />
      </div>
      <BottomPanel />
    </div>
  );
}

function PageUnderConstruction() {
  return (
    <PageShell title="Page under construction">
      <p>
        This page is not built yet. Open <a href="#/live">Live simulation</a> for the swarm
        console.
      </p>
    </PageShell>
  );
}

interface RouteEntry {
  route: Route;
  page: string;
  fallback: ComponentType;
}

const ROUTES: RouteEntry[] = [
  { route: "landing", page: "LandingPage", fallback: PageUnderConstruction },
  { route: "live", page: "LivePage", fallback: ConsoleFallback },
  { route: "replay", page: "ReplayPage", fallback: ConsoleFallback },
  { route: "tutorial", page: "TutorialPage", fallback: PageUnderConstruction },
  { route: "faq", page: "FaqPage", fallback: PageUnderConstruction },
  { route: "docs", page: "DocsPage", fallback: PageUnderConstruction },
];

export default function Router() {
  const route = useUiStore((s) => s.route);
  const setRoute = useUiStore((s) => s.setRoute);

  // One hashchange listener per app; the parsed route lives in uiStore so the
  // top-bar nav can underline the active page without a second subscription.
  useEffect(() => {
    const onHashChange = () => setRoute(routeFromHash(window.location.hash));
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, [setRoute]);

  const entry = ROUTES.find((r) => r.route === route) ?? ROUTES[0];
  const Page = slot(entry.page) ?? entry.fallback;
  return <Page />;
}
