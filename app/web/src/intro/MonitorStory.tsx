import type { CSSProperties } from "react";
import styles from "./laboratory.module.css";

/*
 * The lab monitor's own story (Jessica's): the 10-15 year journey, thousands of compounds
 * narrowing to a few, then the question of an existing medicine. Hidden on the bench (chapter 0).
 */

function Compound({ form }: { form: number }) {
  return (
    <g fill="none" stroke="currentColor" strokeWidth="1.2">
      {form % 3 === 0 ? (
        <path d="m-7-4 7-4 7 4v8L0 8l-7-4Zm0 0 14 8" />
      ) : form % 3 === 1 ? (
        <path d="m-9 5 6-10 6 10 6-10" />
      ) : (
        <path d="m-8-6 8 12 8-12M0 6v5" />
      )}
      <circle cx="-7" cy="-4" r="2" fill="currentColor" />
      <circle cx="7" cy="4" r="2" fill="currentColor" />
    </g>
  );
}

const COMPOUND_COLOURS = [styles.compound0, styles.compound1, styles.compound2];

export function MonitorStory({ chapter }: { chapter: number }) {
  return (
    <g className={styles.monitor} data-chapter={chapter} aria-hidden="true">
      <rect
        x="1128"
        y="117"
        width="508"
        height="386"
        rx="3"
        fill="#0a213d"
        stroke="#27749b"
        strokeWidth="2"
      />
      <text x="1150" y="150" className={styles.monitorTitle}>
        A long path to a new medicine
      </text>
      <text x="1150" y="191" className={styles.monitorYears}>
        10–15 years
      </text>
      <text x="1150" y="213" className={styles.monitorNote}>
        Discovery to market · Timelines vary
      </text>
      <path d="M1160 245h438" stroke="#486586" strokeWidth="2" />
      {[0, 5, 10, 15].map((year, index) => (
        <g key={year}>
          <circle cx={1160 + index * 146} cy="245" r="4" fill="#d5ecf6" />
          <text x={1160 + index * 146} y="265" textAnchor="middle" className={styles.yearLabel}>
            {year}
          </text>
        </g>
      ))}
      <circle
        className={styles.traveller}
        data-motion-target
        cx="1160"
        cy="245"
        r="5"
        fill="#ffd08b"
      />
      {["Discovery", "Lab studies", "Clinical trials", "Review"].map((stage, index) => (
        <text
          key={stage}
          x={1160 + index * 146}
          y="287"
          textAnchor="middle"
          className={styles.stageLabel}
        >
          {stage}
        </text>
      ))}
      <path d="M1149 309h463" stroke="#294c70" />
      <text
        x="1150"
        y="335"
        className={`${styles.sectionLabel ?? ""} ${styles.compoundsLabel ?? ""}`}
      >
        Thousands of potential compounds
      </text>
      {Array.from({ length: 28 }, (_, index) => {
        const x = 1160 + (index % 7) * 20;
        const y = 357 + Math.floor(index / 7) * 23;
        return (
          <g
            key={index}
            transform={`translate(${String(x)} ${String(y)})`}
            className={COMPOUND_COLOURS[index % 3]}
          >
            <g
              className={`${styles.flight ?? ""} ${(index % 7 === 0 ? styles.pass : styles.setAside) ?? ""}`}
              data-motion-target
              style={
                {
                  "--compound-delay": `${String(index * 120)}ms`,
                  "--compound-x": `${String(1460 - x)}px`,
                  "--compound-y": `${String(390 - y)}px`,
                } as CSSProperties
              }
            >
              <Compound form={index} />
            </g>
          </g>
        );
      })}
      <path d="M1335 351v83m0-42h68m-8-6 8 6-8 6" stroke="#60879e" strokeWidth="1.3" fill="none" />
      <g className={styles.focus}>
        <circle cx="1460" cy="391" r="24" fill="#183e52" stroke="#8edace" />
        <g transform="translate(1460 391) scale(1.6)" className={styles.compound0}>
          <Compound form={0} />
        </g>
      </g>
      <text x="1510" y="385" className={styles.stageLabel}>
        Further
      </text>
      <text x="1510" y="403" className={styles.stageLabel}>
        study
      </text>
      <text x="1150" y="459" className={styles.monitorNote}>
        Screening identifies compounds for further study
      </text>
      <g className={styles.question} data-current={chapter === 3}>
        <rect x="1146" y="316" width="472" height="161" fill="#0a213d" />
        <text x="1150" y="339" className={styles.sectionLabel}>
          Could an existing medicine help?
        </text>
        <path
          d="M1230 383h83m-7-6 7 6-7 6m98-6h83m-7-6 7 6-7 6"
          stroke="#9de2cf"
          strokeWidth="2"
          fill="none"
        />
        <g transform="translate(1192 383) rotate(-38)" stroke="#9de2cf" strokeWidth="2">
          <rect x="-22" y="-11" width="44" height="22" rx="11" fill="#1b4053" />
          <path d="M0-11v22" />
        </g>
        <g stroke="#9de2cf" strokeWidth="2" fill="#1b4053">
          <path d="m1340 371 21 12 20-15m-20 15 13 19m-13-19-23 18" fill="none" />
          <circle cx="1340" cy="371" r="5" />
          <circle cx="1361" cy="383" r="7" />
          <circle cx="1381" cy="368" r="5" />
          <circle cx="1374" cy="402" r="5" />
          <circle cx="1338" cy="401" r="5" />
          <path d="M1515 361h21l12 12v32h-33Zm21 0v12h12m-25 10h17m-17 10h12" />
        </g>
        <text x="1192" y="430" textAnchor="middle" className={styles.stageLabel}>
          Existing medicine
        </text>
        <text x="1361" y="430" textAnchor="middle" className={styles.stageLabel}>
          Disease biology
        </text>
        <text x="1531" y="430" textAnchor="middle" className={styles.stageLabel}>
          Candidate new use
        </text>
        <text x="1150" y="459" className={styles.monitorNote}>
          Connect known drug targets with disease-linked proteins
        </text>
      </g>
    </g>
  );
}
