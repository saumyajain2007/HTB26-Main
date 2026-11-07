import { useCallback, useEffect, useRef, type ReactNode } from "react";
import { Link, useNavigate } from "react-router";
import { copy, stepCopy, type StepSlug } from "../copy/en";
import { PageBody, PageFrame } from "./PageFrame";
import styles from "./Shell.module.css";
import { neighbourStep, stepPath } from "./steps";
import { useStepKeys } from "./useStepKeys";

interface ShellProps {
  step: StepSlug;
  /** Absent on the landing page, before a Disease has been chosen. */
  experimentId?: string | undefined;
  /** The Experiment's Disease, shown once in the header. */
  disease?: string | undefined;
  /** The step's figure. */
  children: ReactNode;
}

/**
 * The app shell: product, Disease and step navigation in the header; then the step title, its
 * intro and the figure; then Back and Next at the bottom right, where a reader finishes the step.
 * The step's name is said once, as the page title; the navigation marks the current step by
 * state (underline and aria-current) and the buttons never repeat a step name.
 */
export function Shell({ step, experimentId, disease, children }: ShellProps) {
  const navigate = useNavigate();
  const { title, intro } = stepCopy(step);

  const previousStep = neighbourStep(step, -1);
  const nextStep = neighbourStep(step, 1);
  const previousPath = previousStep && stepPath(experimentId, previousStep);
  const nextPath = nextStep && stepPath(experimentId, nextStep);

  const goPrevious = useCallback(() => {
    if (previousPath !== undefined) void navigate(previousPath);
  }, [navigate, previousPath]);
  const goNext = useCallback(() => {
    if (nextPath !== undefined) void navigate(nextPath);
  }, [navigate, nextPath]);
  useStepKeys(goPrevious, goNext);

  // On narrow screens the steps scroll sideways; keep the current one in view.
  const currentLink = useRef<HTMLAnchorElement>(null);
  useEffect(() => {
    const link = currentLink.current;
    const nav = link?.closest("nav");
    if (!link || !nav || nav.scrollWidth <= nav.clientWidth) return;
    const linkBox = link.getBoundingClientRect();
    const navBox = nav.getBoundingClientRect();
    nav.scrollLeft += linkBox.left + linkBox.width / 2 - (navBox.left + navBox.width / 2);
  }, [step]);

  return (
    <PageFrame
      header={
        <>
          {disease !== undefined && (
            <span className={styles.disease} title={disease}>
              <span className={styles.diseaseMark} aria-hidden="true" />
              <span className={styles.diseaseName}>{disease}</span>
            </span>
          )}
          <nav className={styles.nav} aria-label={copy.stepsLabel}>
            <ol className={styles.navList}>
              {copy.steps.map((item) => {
                const path = stepPath(experimentId, item.slug);
                return (
                  <li key={item.slug} className={styles.navItem}>
                    {path === undefined ? (
                      <span className={styles.navLink} aria-disabled="true">
                        {item.title}
                      </span>
                    ) : (
                      <Link
                        to={path}
                        className={styles.navLink}
                        ref={item.slug === step ? currentLink : undefined}
                        aria-current={item.slug === step ? "step" : undefined}
                      >
                        {item.title}
                      </Link>
                    )}
                  </li>
                );
              })}
            </ol>
          </nav>
        </>
      }
      footer={
        <div className={styles.actions}>
          <button
            type="button"
            className={styles.button}
            onClick={goPrevious}
            disabled={previousPath === undefined}
          >
            {copy.back}
          </button>
          <button
            type="button"
            className={`${styles.button ?? ""} ${styles.primary ?? ""}`}
            onClick={goNext}
            disabled={nextPath === undefined}
          >
            {copy.next}
          </button>
        </div>
      }
    >
      <PageBody title={title} intro={intro}>
        {children}
      </PageBody>
    </PageFrame>
  );
}
