import type { ReactNode } from "react";
import { Link } from "react-router";
import { copy } from "../copy/en";
import { BrandMark } from "./BrandMark";
import styles from "./PageFrame.module.css";

interface PageFrameProps {
  /** What the header shows after the product name, in reading order. */
  header?: ReactNode;
  /** What the footer shows at its right, e.g. a step's Back and Next; no footer without it. */
  footer?: ReactNode;
  /** A reading page grows with its content and the window scrolls; steps fit the window. */
  flow?: "fit" | "document";
  children: ReactNode;
}

/**
 * The frame of every screen: a header that starts with the product name, the main area, and an
 * optional footer. Rendering them here is what keeps each to exactly once.
 */
export function PageFrame({ header, footer, flow = "fit", children }: PageFrameProps) {
  return (
    <div className={styles.page} data-flow={flow}>
      <header className={styles.header}>
        <Link to="/" className={styles.product}>
          <BrandMark className={styles.productMark} />
          {copy.product}
        </Link>
        {header}
      </header>
      <main className={styles.main}>{children}</main>
      {footer !== undefined && <footer className={styles.footer}>{footer}</footer>}
    </div>
  );
}

interface PageBodyProps {
  title: string;
  intro: string;
  /** The screen's figure. */
  children: ReactNode;
}

/** A screen's title, said once and also as the document title; its intro; then its figure. */
export function PageBody({ title, intro, children }: PageBodyProps) {
  return (
    <>
      <title>{`${title} - ${copy.product}`}</title>
      <div className={styles.head}>
        <h1 className={styles.title}>{title}</h1>
        <p className={styles.intro}>{intro}</p>
      </div>
      <div className={styles.figure}>{children}</div>
    </>
  );
}
