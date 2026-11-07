import { useEffect, useRef } from "react";
import type { Conformer } from "../api/types";
import { copy } from "../copy/en";
import { MoleculeScene } from "./moleculeScene";
import styles from "./Plate.module.css";
import { canUseWebGL } from "./webgl";

interface MoleculeFigureProps {
  conformer: Conformer;
  /** The drug's display name, for the canvas's accessible name. */
  name: string;
}

/** One small molecule in 3D, in the same flat, outlined style as the network. Drag to rotate. */
export function MoleculeFigure({ conformer, name }: MoleculeFigureProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const labelsRef = useRef<HTMLDivElement>(null);
  const webgl = canUseWebGL();

  useEffect(() => {
    const host = hostRef.current;
    const labels = labelsRef.current;
    if (!webgl || !host || !labels) return;
    const scene = MoleculeScene.create(host, styles.canvas ?? "", labels, conformer);
    return () => {
      scene?.dispose();
    };
  }, [conformer, webgl]);

  if (!webgl) return <p className={styles.message}>{copy.network.unavailable}</p>;
  return (
    <div
      ref={hostRef}
      className={styles.plate}
      role="img"
      aria-label={copy.evidence.moleculeLabel(name)}
    >
      <div
        ref={labelsRef}
        className={`${styles.labels ?? ""} ${styles.atoms ?? ""}`}
        aria-hidden="true"
      />
    </div>
  );
}
