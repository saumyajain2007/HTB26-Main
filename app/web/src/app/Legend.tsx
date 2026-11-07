import { copy } from "../copy/en";
import styles from "./Legend.module.css";

export type LegendKey = "disease" | "drug" | "both" | "link" | "path";

/** The network's key: one swatch per role colour that the current view uses. */
export function Legend({ keys }: { keys: readonly LegendKey[] }) {
  if (keys.length === 0) return null;
  return (
    <ul className={styles.legend}>
      {keys.map((key) => (
        <li key={key}>
          <span className={styles.swatch} data-key={key} aria-hidden="true" />
          {copy.legend[key]}
        </li>
      ))}
    </ul>
  );
}
