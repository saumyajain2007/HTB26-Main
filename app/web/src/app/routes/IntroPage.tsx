import { type CSSProperties, type ReactNode } from "react";
import { Link } from "react-router";
import { copy } from "../../copy/en";
import { crops } from "../../intro/content";
import { Backdrop, CropImage, LabPlate, Sticker } from "../../intro/Showpieces";
import { WorkflowMap } from "../../intro/WorkflowMap";
import { PageFrame } from "../PageFrame";
import { EXPLORE_PATH } from "../steps";
import styles from "./IntroPage.module.css";

/*
 * The introduction at `/`: a large serif headline beside Jessica's animated lab, the way into the
 * app, the four steps of the method over details of her story illustrations, and her Workflow
 * map. Asymmetric, with generous whitespace.
 */

/** One detail of Jessica's illustrations per method step, in the steps' order. */
const METHOD_CROPS = [crops.diseaseProtein, crops.network, crops.review, crops.shortlist];

export function IntroPage() {
  return (
    <PageFrame flow="document">
      <title>{copy.product}</title>
      <div className={styles.page}>
        <Backdrop />
        <Reveal order={0} className={styles.head}>
          <h1 className={styles.title}>{copy.intro.title}</h1>
          <Sticker className={styles.tag} tilt={-3} animate>
            {copy.intro.tagline}
          </Sticker>
        </Reveal>
        <Reveal order={2} className={styles.plate}>
          <LabPlate />
        </Reveal>
        <Reveal order={1} className={styles.solution}>
          <p className={styles.lede}>{copy.intro.solution}</p>
          <div className={styles.action}>
            <Start />
            <p className={styles.limit}>{copy.intro.limit}</p>
          </div>
        </Reveal>
        <Reveal order={3} className={styles.method}>
          <figure>
            <ol className={styles.steps}>
              {copy.intro.method.map((step, index) => (
                <li key={step.title} className={styles.step}>
                  <div className={styles.thumb}>
                    <CropImage crop={METHOD_CROPS[index] ?? crops.network} />
                    <span className={styles.glyphTab}>
                      <MethodGlyph index={index} />
                    </span>
                  </div>
                  <h2 className={styles.stepTitle}>
                    {/* The list already numbers the steps for assistive technology. */}
                    <span className={styles.stepNo} aria-hidden="true">
                      {index + 1}
                    </span>
                    {step.title}
                  </h2>
                  <p className={styles.stepText}>{step.text}</p>
                </li>
              ))}
            </ol>
          </figure>
        </Reveal>
        <Reveal order={4} className={styles.workflow}>
          <section aria-labelledby="intro-workflow">
            <h2 id="intro-workflow" className={styles.workflowTitle}>
              {copy.intro.workflow.title}
            </h2>
            <p className={styles.workflowLede}>{copy.intro.workflow.lede}</p>
            <WorkflowMap className={styles.workflowMap} />
          </section>
        </Reveal>
      </div>
    </PageFrame>
  );
}

/** The way into the app: an ink button with an arrow that leans in and a passing glint. */
function Start() {
  return (
    <Link to={EXPLORE_PATH} className={styles.start}>
      {copy.intro.start}
      <svg className={styles.startArrow} viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 12h15M13 5l7 7-7 7" />
      </svg>
    </Link>
  );
}

/** A block that settles in once as the page opens, `order` steps after the first. */
function Reveal({
  order,
  className,
  children,
}: {
  order: number;
  className: string | undefined;
  children: ReactNode;
}) {
  return (
    <div
      className={`${styles.reveal ?? ""} ${className ?? ""}`}
      style={{ "--order": order } as CSSProperties}
    >
      {children}
    </div>
  );
}

/** Glyphs for the four method steps: small, flat, drawn like the app's charts. */
function MethodGlyph({ index }: { index: number }) {
  const glyphs = [
    // Disease proteins: a small module.
    <g key="disease">
      <g className={styles.edges}>
        <line x1={34} y1={22} x2={52} y2={34} />
        <line x1={52} y1={34} x2={40} y2={50} />
        <line x1={34} y1={22} x2={40} y2={50} />
        <line x1={52} y1={34} x2={72} y2={26} />
      </g>
      <circle className={styles.node} data-role="disease" cx={34} cy={22} r={5} />
      <circle className={styles.node} data-role="disease" cx={52} cy={34} r={5} />
      <circle className={styles.node} data-role="disease" cx={40} cy={50} r={5} />
      <circle className={styles.node} data-role="disease" cx={72} cy={26} r={5} />
    </g>,
    // Network ranking: a target, a route, the module.
    <g key="network">
      <g className={styles.edges}>
        <line x1={12} y1={40} x2={32} y2={24} />
        <line x1={32} y1={24} x2={50} y2={44} />
        <line x1={32} y1={24} x2={28} y2={52} />
        <line x1={50} y1={44} x2={72} y2={30} />
        <line x1={72} y1={30} x2={86} y2={48} />
      </g>
      <path className={styles.route} d="M12 40L32 24L50 44L72 30" />
      <circle className={styles.node} data-role="target" cx={12} cy={40} r={5} />
      <circle className={styles.node} data-role="route" cx={32} cy={24} r={4} />
      <circle className={styles.node} data-role="protein" cx={28} cy={52} r={4} />
      <circle className={styles.node} data-role="route" cx={50} cy={44} r={4} />
      <circle className={styles.node} data-role="disease" cx={72} cy={30} r={5} />
      <circle className={styles.node} data-role="disease" cx={86} cy={48} r={5} />
    </g>,
    // Evidence review: three models, three calls.
    <g key="jury">
      {[0, 1, 2].map((model) => (
        <g key={model} transform={`translate(${String(14 + model * 26)} 14)`}>
          <g className={styles.glyphMarker} transform="translate(5 0)">
            {
              [
                <circle key="c" cx={6} cy={6} r={4.6} />,
                <rect key="s" x={1.6} y={1.6} width={8.8} height={8.8} />,
                <path key="t" d="M6 1.2L10.9 10.2H1.1Z" />,
              ][model]
            }
          </g>
          <rect
            className={styles.glyphTile}
            data-decision={(["investigate", "investigate", "watch"] as const)[model]}
            x={0}
            y={22}
            width={22}
            height={14}
            rx={2}
          />
          <rect
            className={styles.glyphTile}
            data-decision={(["watch", "deprioritise", "deprioritise"] as const)[model]}
            x={0}
            y={40}
            width={22}
            height={14}
            rx={2}
          />
        </g>
      ))}
    </g>,
    // Shortlist: ranked lines.
    <g key="shortlist" className={styles.glyphList}>
      {[0, 1, 2].map((row) => (
        <g key={row} transform={`translate(14 ${String(16 + row * 16)})`}>
          <text x={0} y={4}>
            {row + 1}
          </text>
          <line x1={14} y1={0} x2={78 - row * 14} y2={0} />
        </g>
      ))}
    </g>,
  ];
  return (
    <svg className={styles.glyph} viewBox="0 0 100 66" aria-hidden="true" focusable="false">
      {glyphs[index]}
    </svg>
  );
}
