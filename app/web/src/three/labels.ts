/**
 * Places text labels beside projected 3D nodes without overlapping each other or any node.
 * Each label tries eight spots around its node; the spot it used last frame goes first, so
 * labels don't flicker as the figure turns. A label with no free spot is hidden, unless it must
 * show (a focused protein), in which case it takes the least-bad spot.
 */

export interface Disc {
  x: number;
  y: number;
  r: number;
}

export interface LabelRequest {
  id: string;
  /** The node the label belongs to, in canvas pixels. */
  anchor: Disc;
  width: number;
  height: number;
  /** Higher places first. */
  priority: number;
  /** Shown even without a free spot. */
  required: boolean;
  /** Index of the spot used last time, if any. */
  previous: number | null;
}

export interface Placement {
  x: number;
  y: number;
  spot: number;
}

interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

const GAP = 4;
const EDGE = 2;
/** Clear space kept between two labels, so neighbouring words never read as one. */
const SPACING = 4;

function spots(anchor: Disc, w: number, h: number): [number, number][] {
  const { x, y, r } = anchor;
  return [
    [x + r + GAP, y - h / 2],
    [x - r - GAP - w, y - h / 2],
    [x + r * 0.6, y - r - h],
    [x + r * 0.6, y + r],
    [x - w / 2, y - r - GAP - h],
    [x - w / 2, y + r + GAP],
    [x - r * 0.6 - w, y - r - h],
    [x - r * 0.6 - w, y + r],
  ];
}

function overlapsDisc(rect: Rect, disc: Disc): boolean {
  const cx = Math.max(rect.x, Math.min(disc.x, rect.x + rect.w));
  const cy = Math.max(rect.y, Math.min(disc.y, rect.y + rect.h));
  return (cx - disc.x) ** 2 + (cy - disc.y) ** 2 < disc.r * disc.r;
}

function overlapsRect(a: Rect, b: Rect): boolean {
  return (
    a.x < b.x + b.w + SPACING && a.x + a.w + SPACING > b.x && a.y < b.y + b.h && a.y + a.h > b.y
  );
}

export function placeLabels(
  requests: readonly LabelRequest[],
  discs: readonly Disc[],
  bounds: { width: number; height: number },
): Map<string, Placement | null> {
  const placed: Rect[] = [];
  const result = new Map<string, Placement | null>();
  const ordered = [...requests].sort((a, b) => b.priority - a.priority);
  for (const request of ordered) {
    const options = spots(request.anchor, request.width, request.height);
    const order = options.map((_, i) => i);
    if (request.previous !== null) order.unshift(request.previous);
    let best: Placement | null = null;
    let bestScore = Infinity;
    for (const index of order) {
      const spot = options[index];
      if (spot === undefined) continue;
      const rect = { x: spot[0], y: spot[1], w: request.width, h: request.height };
      const outside =
        rect.x < EDGE ||
        rect.y < EDGE ||
        rect.x + rect.w > bounds.width - EDGE ||
        rect.y + rect.h > bounds.height - EDGE;
      const score =
        (outside ? 4 : 0) +
        (discs.some((disc) => overlapsDisc(rect, disc)) ? 2 : 0) +
        (placed.some((other) => overlapsRect(rect, other)) ? 1 : 0);
      if (score < bestScore) {
        bestScore = score;
        best = { x: rect.x, y: rect.y, spot: index };
        if (score === 0) break;
      }
    }
    if (best === null || (bestScore > 0 && !request.required)) {
      result.set(request.id, null);
      continue;
    }
    placed.push({ x: best.x, y: best.y, w: request.width, h: request.height });
    result.set(request.id, best);
  }
  return result;
}
