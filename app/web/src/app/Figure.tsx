import { useId, type ReactNode } from "react";
import styles from "./Figure.module.css";

/**
 * A step's figure composition (docs/engineering/design.md, "One step, one figure"): at most three panels on
 * one grid. `layout` picks the grid; each panel names its own area in it.
 */
export type FigureLayout =
  "search" | "biology" | "candidates" | "evidence" | "jury" | "pose" | "evaluation" | "single";

interface FigureGridProps {
  layout: FigureLayout;
  /** False when the Experiment has no protein network: its cell goes to the step's panels. */
  network?: boolean;
  children: ReactNode;
}

export function FigureGrid({ layout, network = true, children }: FigureGridProps) {
  return (
    <div className={styles.grid} data-layout={layout} data-network={network ? undefined : "none"}>
      {children}
    </div>
  );
}

export type PanelArea =
  | "search"
  | "net"
  | "targets"
  | "slope"
  | "molecule"
  | "evidence"
  | "ballot"
  | "reading"
  | "pose"
  | "scores"
  | "results"
  | "tested"
  | "main";

interface PanelProps {
  area: PanelArea;
  /** Short and plain ("Ranking"); omitted when the panel speaks for itself. */
  title?: ReactNode;
  /** Accessible name when the panel has no visible title. */
  label?: string;
  /** Controls set on the title row's right. */
  actions?: ReactNode;
  hidden?: boolean;
  children: ReactNode;
}

export function Panel({ area, title, label, actions, hidden, children }: PanelProps) {
  const titleId = useId();
  const hasTitle = title !== undefined && title !== null;
  return (
    <section
      className={styles.panel}
      data-area={area}
      hidden={hidden}
      aria-labelledby={hasTitle ? titleId : undefined}
      aria-label={hasTitle ? undefined : label}
    >
      {(hasTitle || actions !== undefined) && (
        <header className={styles.head}>
          {hasTitle && (
            <h2 id={titleId} className={styles.title}>
              {title}
            </h2>
          )}
          {actions !== undefined && <div className={styles.actions}>{actions}</div>}
        </header>
      )}
      <div className={styles.body}>{children}</div>
    </section>
  );
}

/** A quiet line of status inside a figure: loading, empty or unavailable. */
export function FigureNote({ children }: { children: ReactNode }) {
  return <div className={styles.note}>{children}</div>;
}
