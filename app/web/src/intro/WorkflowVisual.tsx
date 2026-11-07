import type { ReactNode } from "react";
import styles from "./workflowVisual.module.css";

/*
 * The small schematic drawn inside each step of the Workflow technical map, ported from
 * Jessica's round-three prototype and redrawn in the app's ink-on-paper style. Its pulses
 * run only while an ancestor carries `data-active="true"` and pause under `data-playing="false"`.
 */

function cx(...names: (string | false | undefined)[]): string {
  return names.filter(Boolean).join(" ");
}

const pulses = [styles.pulse0, styles.pulse1, styles.pulse2, styles.pulse3];

function pulse(i: number): string {
  return cx(styles.microPulse, pulses[i % pulses.length]);
}

function Frame({ kind, label, children }: { kind: string; label: string; children: ReactNode }) {
  return (
    <svg
      className={styles.visual}
      data-kind={kind}
      data-motion-target=""
      viewBox="0 0 180 108"
      role="img"
      aria-label={label}
    >
      {children}
    </svg>
  );
}

export function WorkflowVisual({ kind }: { kind: string }) {
  if (kind === "connect") {
    return (
      <Frame
        kind={kind}
        label="Schematic shortest protein-network path between a drug target and a disease-linked protein"
      >
        <g className={styles.edges}>
          <path d="M17 52 53 27 94 48 132 25 163 53M17 52 51 82 94 48 127 84 163 53M53 27 51 82M132 25 127 84" />
        </g>
        <path className={styles.path} d="M17 52 53 27 94 48 163 53" />
        {[
          [51, 82],
          [132, 25],
          [127, 84],
        ].map(([x, y], i) => (
          <circle key={i} cx={x} cy={y} r="5" className={styles.proteinMuted} />
        ))}
        {[
          [17, 52],
          [53, 27],
          [94, 48],
          [163, 53],
        ].map(([x, y], i) => (
          <circle
            key={i}
            cx={x}
            cy={y}
            r={i === 0 || i === 3 ? 8 : 5}
            className={cx(
              i === 0 ? styles.target : i === 3 ? styles.disease : styles.protein,
              pulse(i),
            )}
          />
        ))}
        <text x="0" y="13">
          Drug target
        </text>
        <text x="180" y="13" textAnchor="end">
          Disease
        </text>
        <text x="90" y="106" textAnchor="middle" className={styles.caption}>
          Shared targets + network links
        </text>
      </Frame>
    );
  }
  if (kind === "rank") {
    return (
      <Frame
        kind={kind}
        label="Ten network selections and five direct-evidence selections form a deduplicated shortlist of up to fifteen candidates"
      >
        <text x="2" y="15">
          10 network
        </text>
        <text x="2" y="60">
          5 direct
        </text>
        {Array.from({ length: 10 }, (_, i) => (
          <rect
            key={`n${String(i)}`}
            x={2 + i * 16}
            y="24"
            width="11"
            height="18"
            rx="2"
            className={cx(styles.slot, pulse(i))}
          />
        ))}
        {Array.from({ length: 5 }, (_, i) => (
          <rect
            key={`d${String(i)}`}
            x={2 + i * 16}
            y="69"
            width="11"
            height="18"
            rx="2"
            className={cx(styles.slot, styles.slotDirect, pulse(i))}
          />
        ))}
        <path className={styles.edges} d="M169 24v67h-69m0 0 6-4m-6 4 6 4" />
        <text x="139" y="106" textAnchor="middle" className={styles.caption}>
          dedupe + refill
        </text>
      </Frame>
    );
  }
  if (kind === "packet") {
    return (
      <Frame
        kind={kind}
        label="Archived ChEMBL evidence E2 includes the exact phrase JAK1 inhibitor. The saved AI review cites E2, linking its claim to the source."
      >
        <path className={styles.paper} d="M3 8h65l13 13v70H3Z" />
        <path className={styles.edges} d="M68 8v14h13" />
        <text x="13" y="31" className={styles.accent}>
          ChEMBL
        </text>
        <text x="13" y="52">
          “JAK1
        </text>
        <text x="13" y="69">
          inhibitor.”
        </text>
        <path className={styles.path} d="M88 51h20m-5-4 5 4-5 4" />
        <circle cx="96" cy="51" r="3" className={cx(styles.protein, pulse(0))} />
        <path className={styles.paper} d="M116 18h60v73h-60Z" />
        <text x="146" y="41" textAnchor="middle">
          Review
        </text>
        <text x="146" y="64" textAnchor="middle" className={styles.eid}>
          [E2]
        </text>
        <text x="90" y="106" textAnchor="middle" className={styles.caption}>
          Archived source → citation
        </text>
      </Frame>
    );
  }
  if (kind === "cortex") {
    return (
      <Frame
        kind={kind}
        label="The same candidate evidence is sent independently to GPT-5.4, GLM-5.3 and Kimi K3, producing three separate reviews"
      >
        <path
          className={styles.edges}
          d="M13 54h14V20h15M27 54h15M27 54v34h15M140 20h22M140 54h22M140 88h22"
        />
        <path className={styles.paper} d="M2 43h16v23H2Z" />
        {[
          { y: 6, name: "GPT-5.4" },
          { y: 40, name: "GLM-5.3" },
          { y: 74, name: "Kimi K3" },
        ].map(({ y, name }, i) => (
          <g key={name}>
            <rect className={styles.model} x="43" y={y} width="96" height="28" rx="3" />
            <text x="91" y={y + 18} textAnchor="middle">
              {name}
            </text>
            <path className={styles.paper} d={`M163 ${String(y + 4)}h14v21h-14Z`} />
            <circle cx="150" cy={y + 14} r="3" className={cx(styles.protein, pulse(i))} />
          </g>
        ))}
      </Frame>
    );
  }
  if (kind === "compare") {
    return (
      <Frame
        kind={kind}
        label="Schematic rank comparison: computational and AI orderings can differ. This illustration is not an experiment result."
      >
        <text x="5" y="14">
          Network
        </text>
        <text x="179" y="14" textAnchor="end">
          AI jury
        </text>
        <g className={styles.edges}>
          <path d="M53 34 124 57M53 57 124 34M53 80h71" />
        </g>
        {[34, 57, 80].map((y, i) => (
          <g key={y}>
            <rect className={styles.rank} x="5" y={y - 12} width="47" height="21" rx="2" />
            <rect className={styles.rank} x="125" y={y - 12} width="50" height="21" rx="2" />
            <text x="28" y={y + 3} textAnchor="middle">
              #{i + 1}
            </text>
            <text x="150" y={y + 3} textAnchor="middle">
              #{i + 1}
            </text>
          </g>
        ))}
        <circle cx="89" cy="80" r="3" className={cx(styles.protein, pulse(0))} />
        <text x="90" y="106" textAnchor="middle" className={styles.caption}>
          Ranks can differ
        </text>
      </Frame>
    );
  }
  if (kind === "tiger") {
    return (
      <Frame
        kind={kind}
        label="TigerData PostgreSQL stores experiments, exact evidence and AI reviews"
      >
        <path className={styles.database} d="M47 29h86v47c0 22-86 22-86 0Z" />
        <ellipse cx="90" cy="29" rx="43" ry="14" className={styles.databaseTop} />
        <path className={styles.databaseBand} d="M47 50c0 20 86 20 86 0M47 68c0 20 86 20 86 0" />
      </Frame>
    );
  }
  return (
    <Frame
      kind={kind}
      label="Optional AutoDock Vina predicts a possible ligand pose inside a protein, rather than proving treatment benefit"
    >
      <path
        className={styles.pocket}
        d="m32 13 33 11 19-12 29 22 36-2 8 34-29 23-29-10-27 14-40-22 12-29Z"
      />
      <path
        className={styles.edges}
        d="m32 13 27 39-27 19m27-19 25-40m-25 40 40 27 14-45m-54 18 54-18 15 55"
      />
      <path className={styles.ligand} d="m70 45 20-6 13 17-12 18-23-7Z" />
      {[
        [70, 45],
        [90, 39],
        [103, 56],
        [91, 74],
        [68, 67],
      ].map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r="4" className={styles.ligandNode} />
      ))}
    </Frame>
  );
}
