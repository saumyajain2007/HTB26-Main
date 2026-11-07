import { describe, expect, it } from "vitest";
import { placeLabels, type LabelRequest } from "./labels";

const request = (id: string, x: number, y: number, extra: Partial<LabelRequest> = {}) => ({
  id,
  anchor: { x, y, r: 6 },
  width: 40,
  height: 16,
  priority: 1,
  required: false,
  previous: null,
  ...extra,
});

const bounds = { width: 400, height: 300 };

describe("placeLabels", () => {
  it("puts a lone label to the right of its node", () => {
    const placed = placeLabels([request("A", 100, 100)], [{ x: 100, y: 100, r: 6 }], bounds);
    expect(placed.get("A")).toEqual({ x: 110, y: 92, spot: 0 });
  });

  it("never overlaps two labels: the lower priority one moves or hides", () => {
    const requests = [request("A", 100, 100, { priority: 2 }), request("B", 100, 104)];
    const placed = placeLabels(requests, [], bounds);
    const a = placed.get("A");
    const b = placed.get("B");
    expect(a).not.toBeNull();
    if (a && b) {
      const overlap = a.x < b.x + 40 && a.x + 40 > b.x && a.y < b.y + 16 && a.y + 16 > b.y;
      expect(overlap).toBe(false);
    }
  });

  it("hides a label that cannot fit unless it is required", () => {
    const crowded = { width: 30, height: 20 };
    expect(placeLabels([request("A", 15, 10)], [], crowded).get("A")).toBeNull();
    expect(
      placeLabels([request("A", 15, 10, { required: true })], [], crowded).get("A"),
    ).not.toBeNull();
  });

  it("keeps the spot used last time when it is still free", () => {
    const placed = placeLabels([request("A", 100, 100, { previous: 1 })], [], bounds);
    expect(placed.get("A")?.spot).toBe(1);
  });
});
