import styles from "./Marker.module.css";

const SIZE = 12;

// One outlined shape per jury model, in jury order: circle, square, triangle, diamond.
const SHAPES = [
  <circle key="circle" cx={6} cy={6} r={4.6} />,
  <rect key="square" x={1.6} y={1.6} width={8.8} height={8.8} />,
  <path key="triangle" d="M6 1.2L10.9 10.2H1.1Z" />,
  <path key="diamond" d="M6 0.9L11.1 6L6 11.1L0.9 6Z" />,
];

/**
 * A jury model's marker. `index` is the model's position in the jury, so each model keeps its
 * shape on every screen. Shapes, not colours, tell models apart: colour is reserved for roles.
 */
export function Marker({ index, className }: { index: number; className?: string }) {
  return (
    <svg
      className={className === undefined ? styles.marker : `${styles.marker ?? ""} ${className}`}
      width={SIZE}
      height={SIZE}
      viewBox={`0 0 ${String(SIZE)} ${String(SIZE)}`}
      aria-hidden="true"
      focusable="false"
    >
      {SHAPES[index % SHAPES.length]}
    </svg>
  );
}
