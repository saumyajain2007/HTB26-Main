import { useCallback, useEffect, useRef, type ReactNode } from "react";
import { Link, useNavigate } from "react-router";
import {
  copy,
  resistanceStepCopy,
  stepCopy,
  type ResistanceStepSlug,
  type StepSlug,
} from "../copy/en";
import { PageBody, PageFrame } from "./PageFrame";
import styles from "./Shell.module.css";
import { neighbourResistanceStep, neighbourStep, resistanceStepPath, stepPath } from "./steps";
import { useStepKeys } from "./useStepKeys";

/** One step in the navigation: `path` is undefined while the step has no page to go to. */
interface StepLink {
  slug: string;
  title: string;
  path: string | undefined;
  current: boolean;
}

interface StepShellProps {
  /** The current step's slug. Only the sideways scroll reads it; the links carry the rest. */
  step: string;
  title: string;
  intro: string;
  links: readonly StepLink[];
  previousPath: string | undefined;
  nextPath: string | undefined;
  /** What the flow is about (a Disease, a pathogen), shown once in the header. */
  subject?: string | undefined;
  /** `document`: the page grows with its content and the window scrolls. Default: fit the window. */
  flow?: "fit" | "document";
  children: ReactNode;
}

/**
 * The app shell: product, subject and step navigation in the header; then the step title, its
 * intro and the figure; then Back and Next at the bottom right, where a reader finishes the step.
 * The step's name is said once, as the page title; the navigation marks the current step by
 * state (underline and aria-current) and the buttons never repeat a step name.
 *
 * It knows nothing about which flow it is drawing: `Shell` and `ResistanceShell` below work out
 * the steps and their addresses, so both flows get one piece of chrome and one set of keys.
 */
function StepShell({
  step,
  title,
  intro,
  links,
  previousPath,
  nextPath,
  subject,
  flow,
  children,
}: StepShellProps) {
  const navigate = useNavigate();

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
      flow={flow}
      header={
        <>
          {subject !== undefined && (
            <span className={styles.subject} title={subject}>
              <span className={styles.subjectMark} aria-hidden="true" />
              <span className={styles.subjectName}>{subject}</span>
            </span>
          )}
          <nav className={styles.nav} aria-label={copy.stepsLabel}>
            <ol className={styles.navList}>
              {links.map((item) => (
                <li key={item.slug} className={styles.navItem}>
                  {item.path === undefined ? (
                    <span className={styles.navLink} aria-disabled="true">
                      {item.title}
                    </span>
                  ) : (
                    <Link
                      to={item.path}
                      className={styles.navLink}
                      ref={item.current ? currentLink : undefined}
                      aria-current={item.current ? "step" : undefined}
                    >
                      {item.title}
                    </Link>
                  )}
                </li>
              ))}
            </ol>
          </nav>
        </>
      }
      footer={
        <div className={styles.actions}>
          <span className={styles.keysHint}>{copy.stepKeysHint}</span>
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

interface ShellProps {
  step: StepSlug;
  /** Absent on the landing page, before a Disease has been chosen. */
  experimentId?: string | undefined;
  /** The Experiment's Disease, shown once in the header. */
  disease?: string | undefined;
  /** The step's figure. */
  children: ReactNode;
}

/** The shell of the gated disease flow (`src/app/flags.ts`): the eight Experiment steps. */
export function Shell({ step, experimentId, disease, children }: ShellProps) {
  const { title, intro } = stepCopy(step);
  const previous = neighbourStep(step, -1);
  const next = neighbourStep(step, 1);
  return (
    <StepShell
      step={step}
      title={title}
      intro={intro}
      links={copy.steps.map((item) => ({
        slug: item.slug,
        title: item.title,
        path: stepPath(experimentId, item.slug),
        current: item.slug === step,
      }))}
      previousPath={previous && stepPath(experimentId, previous)}
      nextPath={next && stepPath(experimentId, next)}
      subject={disease}
    >
      {children}
    </StepShell>
  );
}

interface ResistanceShellProps {
  step: ResistanceStepSlug;
  /** Absent on `/resistance`, before a resistance profile has been built. */
  profileId?: string | undefined;
  /** The profile's pathogen, shown once in the header. */
  pathogen?: string | undefined;
  /** The step's figure. */
  children: ReactNode;
}

/** The shell of the antibiotic resistance flow: the pathogen input, then the resistance map. */
export function ResistanceShell({ step, profileId, pathogen, children }: ResistanceShellProps) {
  const { title, intro } = resistanceStepCopy(step);
  const previous = neighbourResistanceStep(step, -1);
  const next = neighbourResistanceStep(step, 1);
  return (
    <StepShell
      step={step}
      title={title}
      intro={intro}
      links={copy.resistanceSteps.map((item) => ({
        slug: item.slug,
        title: item.title,
        path: resistanceStepPath(profileId, item.slug),
        current: item.slug === step,
      }))}
      previousPath={previous && resistanceStepPath(profileId, previous)}
      nextPath={next && resistanceStepPath(profileId, next)}
      subject={pathogen}
      // These steps are read down the page, so the window scrolls and nothing is boxed in a
      // scroll area; Back and Next follow the content.
      flow="document"
    >
      {children}
    </StepShell>
  );
}
