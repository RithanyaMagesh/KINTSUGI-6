// Router slot — the glob in pages/Router.tsx only scans src/pages/ and
// components/pages/, so the landing agent's component (components/landing/)
// gets a one-line re-export here under the documented slot name.
export { default } from "../components/landing/LandingPage";
