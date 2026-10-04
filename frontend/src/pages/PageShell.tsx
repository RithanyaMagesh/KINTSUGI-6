// PageShell — shared page frame for the document-style pages (landing,
// tutorial, FAQ, docs): one max-width content column on the app background,
// tokens only (§13). Renders inside the Router's 1fr row and scrolls
// independently; the top bar stays persistent above it. Pages compose
// headings, paragraphs, lists and code blocks directly as children — the
// .body class in PageShell.module.css supplies the typographic rhythm.
import type { ReactNode } from "react";
import styles from "./PageShell.module.css";

interface PageShellProps {
  title: string;
  children: ReactNode;
}

export default function PageShell({ title, children }: PageShellProps) {
  return (
    <main className={styles.page}>
      <div className={styles.column}>
        <h1 className={styles.title}>{title}</h1>
        <div className={styles.body}>{children}</div>
      </div>
    </main>
  );
}
