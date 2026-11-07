import { useEffect, useRef } from "react";
import type { Conformer } from "../api/types";
import { copy } from "../copy/en";
import { StripScene as Strip } from "./stripScene";
import styles from "./MoleculeStrip.module.css";
import plate from "./Plate.module.css";
import { canUseWebGL } from "./webgl";

/** One place in the strip: a molecule to draw, or a plain line where there is none. */
export type StripItem =
  | { key: string; name: string; conformer: Conformer; message?: undefined }
  | { key: string; name: string; conformer?: undefined; message: string | null };

/**
 * Small molecules side by side, one per item, drawn on one shared canvas (one WebGL context for
 * the whole row). The strip lays its items out on its parent's grid columns, so each molecule
 * sits under its own column. Drag a molecule to rotate it.
 */
export function MoleculeStrip({ items }: { items: readonly StripItem[] }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const slotRefs = useRef<(HTMLDivElement | null)[]>([]);
  const labelRefs = useRef<(HTMLDivElement | null)[]>([]);
  const stripRef = useRef<Strip | null>(null);
  const webgl = canUseWebGL();

  useEffect(() => {
    const host = hostRef.current;
    if (!webgl || !host) return;
    const strip = Strip.create(host, styles.canvas ?? "");
    stripRef.current = strip;
    return () => {
      strip?.dispose();
      stripRef.current = null;
    };
  }, [webgl]);

  // Cheap on every render: the strip keeps a slot as it is unless its molecule or element changed.
  useEffect(() => {
    stripRef.current?.setSlots(
      items.map((item, index) => {
        const element = slotRefs.current[index];
        const labels = labelRefs.current[index];
        return item.conformer && element && labels
          ? { element, labels, conformer: item.conformer }
          : null;
      }),
    );
  }, [items]);

  return (
    <div ref={hostRef} className={styles.strip}>
      {items.map((item, index) =>
        item.conformer && webgl ? (
          <div
            key={item.key}
            ref={(element) => {
              slotRefs.current[index] = element;
            }}
            className={styles.slot}
            role="img"
            aria-label={copy.evidence.moleculeLabel(item.name)}
          >
            <div
              ref={(element) => {
                labelRefs.current[index] = element;
              }}
              className={`${plate.labels ?? ""} ${plate.atoms ?? ""}`}
              aria-hidden="true"
            />
          </div>
        ) : (
          <p key={item.key} className={styles.message}>
            {item.conformer ? copy.network.unavailable : item.message}
          </p>
        ),
      )}
    </div>
  );
}
