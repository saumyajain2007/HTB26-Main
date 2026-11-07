import { useEffect, useLayoutEffect, useRef } from "react";
import type { NetworkGraph } from "../api/types";
import { copy } from "../copy/en";
import { NetworkScene, type NetworkView } from "./networkScene";
import styles from "./Plate.module.css";
import { canUseWebGL } from "./webgl";

export type { NetworkMode, NetworkView } from "./networkScene";

interface NetworkFigureProps {
  graph: NetworkGraph;
  view: NetworkView;
}

/**
 * The persistent 3D protein network. It is laid out once per graph and kept alive across steps;
 * each step only changes the `view` (what is coloured, emphasised and labelled). Drag to rotate.
 * Ambient rotation and easing stop under `prefers-reduced-motion`.
 */
export function NetworkFigure({ graph, view }: NetworkFigureProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const labelsRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<NetworkScene | null>(null);
  const viewRef = useRef(view);
  const webgl = canUseWebGL();

  // Laid out and drawn as the graph is committed, not after: when another Disease's network
  // replaces this one, the new one is on screen in the same frame as the rest of the page.
  useLayoutEffect(() => {
    const host = hostRef.current;
    const labels = labelsRef.current;
    if (!webgl || !host || !labels) return;
    const scene = NetworkScene.create(host, styles.canvas ?? "", labels, graph);
    if (scene === null) return;
    scene.setView(viewRef.current);
    scene.draw();
    sceneRef.current = scene;
    return () => {
      scene.dispose();
      sceneRef.current = null;
    };
  }, [graph, webgl]);

  useEffect(() => {
    viewRef.current = view;
    sceneRef.current?.setView(view);
  }, [view]);

  if (!webgl) return <p className={styles.message}>{copy.network.unavailable}</p>;
  if (graph.nodes.length === 0) return <p className={styles.message}>{copy.network.empty}</p>;
  return (
    <div ref={hostRef} className={styles.plate} role="img" aria-label={copy.network.label}>
      <div ref={labelsRef} className={styles.labels} aria-hidden="true" />
    </div>
  );
}
