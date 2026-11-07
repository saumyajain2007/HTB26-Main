import { Vector3 } from "three";
import type { NetworkGraph } from "../api/types";

/** A small deterministic PRNG (mulberry32), so the same graph always lands in the same shape. */
function random(seed: number): () => number {
  let state = seed | 0;
  return () => {
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const ITERATIONS = 900;
/** Ideal edge length. Larger than 1 spreads densely linked hubs so their labels have room. */
const K = 1.6;
/** Pull toward the centre, so disconnected proteins stay in frame. */
const GRAVITY = 0.12;

interface Body {
  position: Vector3;
  force: Vector3;
}

/**
 * Lays the network out in 3D with Fruchterman-Reingold: linked proteins pull together, all
 * proteins push apart, and a weak pull to the centre keeps stray components close. The spacing
 * comes out even, so labels rarely collide. Positions are centred and scaled into the unit
 * sphere. Deterministic for a given graph and seed.
 */
export function layoutNetwork(graph: NetworkGraph, seed = 29): Map<string, Vector3> {
  const next = random(seed);
  const bodies = new Map<string, Body>(
    graph.nodes.map((node) => [
      node.id,
      {
        position: new Vector3(next() - 0.5, next() - 0.5, next() - 0.5).multiplyScalar(4),
        force: new Vector3(),
      },
    ]),
  );
  const list = [...bodies.values()];
  const links = graph.edges.flatMap((edge) => {
    const a = bodies.get(edge.source);
    const b = bodies.get(edge.target);
    return a && b ? [[a, b] as const] : [];
  });

  const delta = new Vector3();
  for (let iteration = 0; iteration < ITERATIONS; iteration++) {
    const temperature = 0.35 * (1 - iteration / ITERATIONS) + 0.005;
    for (const body of list) body.force.set(0, 0, 0);
    list.forEach((a, i) => {
      for (const b of list.slice(i + 1)) {
        delta.subVectors(a.position, b.position);
        const length = Math.max(0.05, delta.length());
        delta.multiplyScalar((K * K) / (length * length));
        a.force.add(delta);
        b.force.sub(delta);
      }
    });
    for (const [a, b] of links) {
      delta.subVectors(b.position, a.position);
      delta.multiplyScalar(Math.max(0.05, delta.length()) / K);
      a.force.add(delta);
      b.force.sub(delta);
    }
    for (const body of list) {
      body.force.addScaledVector(body.position, -GRAVITY * body.position.length());
      const length = body.force.length();
      if (length > 0)
        body.position.addScaledVector(body.force, Math.min(length, temperature) / length);
    }
  }

  // Scale so most proteins fill the unit sphere; a few far-flung ones are drawn in toward its
  // edge rather than shrinking everything else to make room for them.
  const centre = new Vector3();
  for (const body of list) centre.add(body.position);
  centre.divideScalar(Math.max(1, list.length));
  const distances = list.map((body) => body.position.distanceTo(centre)).sort((a, b) => a - b);
  const scale = distances[Math.floor(0.85 * (distances.length - 1))] ?? 1;
  return new Map(
    [...bodies].map(([id, body]) => {
      const point = body.position
        .clone()
        .sub(centre)
        .divideScalar(scale || 1);
      const r = point.length();
      if (r > 1) point.multiplyScalar((1 + 0.3 * Math.tanh((r - 1) / 0.3)) / r);
      return [id, point];
    }),
  );
}
