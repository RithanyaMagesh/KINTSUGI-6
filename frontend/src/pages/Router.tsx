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
// if a name exists in both). A route without a page renders "Page under construction".
import { useEffect } from "react";
import type { ComponentType } from "react";
import { useUiStore, routeFromHash } from "../stores/uiStore";
import type { Route } from "../stores/uiStore";
import PageShell from "./PageShell";

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

function PageUnderConstruction() {
  return (
    <PageShell title="Page under construction">
      <p>
        This page is not built yet. Open <a href="#/live">Live simulation</a> to run the swarm.
      </p>
    </PageShell>
  );
}

interface RouteEntry {
  route: Route;
  page: string;
}

const ROUTES: RouteEntry[] = [
  { route: "landing", page: "LandingPage" },
  { route: "live", page: "LivePage" },
  { route: "replay", page: "ReplayPage" },
  { route: "tutorial", page: "TutorialPage" },
  { route: "faq", page: "FaqPage" },
  { route: "docs", page: "DocsPage" },
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
  const Page = slot(entry.page) ?? PageUnderConstruction;
  return <Page />;
}
