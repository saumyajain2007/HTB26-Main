import { useQueries } from "@tanstack/react-query";
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { dockFileQuery } from "../api/queries";
import type { PoseFiles } from "../api/types";
import { copy } from "../copy/en";
import type { BindingVerdict } from "../lib/bindingVerdict";
import styles from "./PoseViewer.module.css";
import type { Contact } from "./interactions";
import { PoseScene } from "./poseScene";
import { canUseWebGL } from "./webgl";

interface PoseViewerProps {
  files: PoseFiles;
  /** Accessible name of the 3D view: which drug in which protein. */
  label: string;
  /** Told the drug's close polar contacts once the scene is drawn, and `[]` when it is gone. */
  onContacts?: (contacts: Contact[]) => void;
  /**
   * When given, the drug is animated coming in to the pocket and a tick (binds) or cross (does
   * not) follows. `basis` is the plain-words reason shown beside it.
   */
  verdict?: { outcome: BindingVerdict; basis: string } | null;
}

interface ToggleProps {
  pressed: boolean;
  onToggle: () => void;
  /** The overlay's toggle carries its colour, so it is its own legend. */
  swatch?: "overlay";
  children: ReactNode;
}

function Toggle({ pressed, onToggle, swatch, children }: ToggleProps) {
  return (
    <button
      type="button"
      className={styles.toggle}
      aria-pressed={pressed}
      data-swatch={swatch}
      onClick={onToggle}
    >
      <span className={styles.box} aria-hidden="true" />
      {children}
    </button>
  );
}

/**
 * A docking result in 3D (3Dmol.js): the protein's backbone, the pocket and the drug's pose. Four
 * controls (the pocket surface, the drug's crystal position, spin and reset) and the key share a
 * quiet bar along the view's top edge, so the view takes the panel's whole height; the drug is
 * framed clear of the bar. On phones the bar sits above the view instead. The view starts
 * still; spin is the reader's choice. The viewer and its WebGL context are released on unmount.
 */
export function PoseViewer({ files, label, onContacts, verdict = null }: PoseViewerProps) {
  const [receptor, poses, crystal] = useQueries({
    queries: [
      dockFileQuery(files.receptor),
      dockFileQuery(files.poses),
      dockFileQuery(files.crystal_ligand),
    ],
  });
  const [surface, setSurface] = useState(true);
  const [overlay, setOverlay] = useState(false);
  const [interactions, setInteractions] = useState(true);
  // Still until the reader asks: a turning view makes labels hard to read.
  const [spinChoice, setSpinChoice] = useState<boolean | null>(null);
  const spin = spinChoice ?? false;

  const hostRef = useRef<HTMLDivElement>(null);
  const toolbarRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<PoseScene | null>(null);
  // The controls' latest values, for a scene that is built after they changed.
  const controlsRef = useRef({ surface, overlay, spin, interactions });
  const onContactsRef = useRef(onContacts);
  const verdictRef = useRef(verdict);
  // The verdict whose animation has finished: the tick or cross waits for the drug to arrive.
  const [arrived, setArrived] = useState<BindingVerdict | null>(null);
  const webgl = canUseWebGL();

  const texts =
    receptor.data !== undefined && poses.data !== undefined && crystal.data !== undefined
      ? { receptor: receptor.data, poses: poses.data, crystal: crystal.data }
      : null;
  const receptorText = texts?.receptor;
  const posesText = texts?.poses;
  const crystalText = texts?.crystal;

  // Release the GPU during the removal commit, before passive effects can be delayed by rendering.
  useLayoutEffect(() => {
    const host = hostRef.current;
    if (!webgl || !host || receptorText === undefined || posesText === undefined) return;
    if (crystalText === undefined) return;
    const scene = PoseScene.create(
      host,
      styles.layer ?? "",
      { receptor: receptorText, poses: posesText, crystal: crystalText },
      () => coveredBy(toolbarRef.current, host),
    );
    if (scene === null) return;
    sceneRef.current = scene;
    host.dataset.ready = "true";
    const controls = controlsRef.current;
    showSurface(host, scene, controls.surface);
    scene.setOverlay(controls.overlay);
    scene.setSpin(controls.spin);
    scene.setInteractions(controls.interactions);
    onContactsRef.current?.(scene.contacts);
    playDock(scene, verdictRef.current, setArrived);
    return () => {
      onContactsRef.current?.([]);
      scene.dispose();
      sceneRef.current = null;
      delete host.dataset.ready;
      delete host.dataset.surface;
    };
  }, [webgl, receptorText, posesText, crystalText]);

  useEffect(() => {
    controlsRef.current.surface = surface;
    const host = hostRef.current;
    const scene = sceneRef.current;
    if (host && scene) showSurface(host, scene, surface);
  }, [surface]);

  useEffect(() => {
    controlsRef.current.overlay = overlay;
    sceneRef.current?.setOverlay(overlay);
  }, [overlay]);

  useEffect(() => {
    onContactsRef.current = onContacts;
  }, [onContacts]);

  useEffect(() => {
    verdictRef.current = verdict;
  }, [verdict]);

  useEffect(() => {
    controlsRef.current.interactions = interactions;
    sceneRef.current?.setInteractions(interactions);
  }, [interactions]);

  useEffect(() => {
    controlsRef.current.spin = spin;
    sceneRef.current?.setSpin(spin);
  }, [spin]);

  const failed = [receptor, poses, crystal].filter((query) => query.isError);
  let note: ReactNode = null;
  if (!webgl) {
    note = copy.network.unavailable;
  } else if (failed.length > 0) {
    note = (
      <>
        <span>{copy.pose.filesFailed}</span>
        <button
          type="button"
          className={styles.retry}
          onClick={() => {
            for (const query of failed) void query.refetch();
          }}
        >
          {copy.retry}
        </button>
      </>
    );
  } else if (texts === null) {
    note = copy.pose.loading;
  }

  return (
    <div className={styles.viewer}>
      <div ref={toolbarRef} className={styles.toolbar}>
        <Toggle
          pressed={surface}
          onToggle={() => {
            setSurface(!surface);
          }}
        >
          {copy.pose.controls.surface}
        </Toggle>
        <Toggle
          pressed={overlay}
          swatch="overlay"
          onToggle={() => {
            setOverlay(!overlay);
          }}
        >
          {copy.pose.controls.overlay}
        </Toggle>
        <Toggle
          pressed={interactions}
          onToggle={() => {
            setInteractions(!interactions);
          }}
        >
          {copy.pose.controls.interactions}
        </Toggle>
        <Toggle
          pressed={spin}
          onToggle={() => {
            setSpinChoice(!spin);
          }}
        >
          {copy.pose.controls.spin}
        </Toggle>
        <button
          type="button"
          className={styles.reset}
          onClick={() => {
            sceneRef.current?.reset();
          }}
        >
          {copy.pose.controls.reset}
        </button>
        {verdict !== null && (
          <button
            type="button"
            className={styles.reset}
            onClick={() => {
              if (sceneRef.current) playDock(sceneRef.current, verdict, setArrived);
            }}
          >
            {copy.pose.controls.replay}
          </button>
        )}
        <ul className={styles.legend}>
          <li>
            <span className={styles.swatch} data-key="protein" aria-hidden="true" />
            {copy.pose.legend.protein}
          </li>
          <li>
            <span className={styles.swatch} data-key="drug" aria-hidden="true" />
            {copy.pose.legend.drug}
          </li>
        </ul>
      </div>
      <div className={styles.stage}>
        <div ref={hostRef} className={styles.plate} role="img" aria-label={label} />
        {note !== null && <p className={styles.note}>{note}</p>}
        {verdict !== null && arrived === verdict.outcome && (
          <div className={styles.verdict} data-outcome={verdict.outcome} role="status">
            <svg className={styles.verdictIcon} viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="12" cy="12" r="11" />
              {verdict.outcome === "binds" ? (
                <path d="M6.5 12.5l3.6 3.6 7.4-7.7" />
              ) : (
                <path d="M8 8l8 8M16 8l-8 8" />
              )}
            </svg>
            <span className={styles.verdictText}>
              <strong>{copy.pose.verdict[verdict.outcome]}</strong>
              <small>{verdict.basis}</small>
              <small>{copy.pose.verdict.illustration}</small>
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

/** How far `cover` reaches down over the top of `view`, in pixels: none when it sits above. */
function coveredBy(cover: HTMLElement | null, view: HTMLElement): number {
  if (cover === null) return 0;
  return Math.max(0, cover.getBoundingClientRect().bottom - view.getBoundingClientRect().top);
}

/** Applies the surface toggle and marks on the host when it is drawn or gone. */
function showSurface(host: HTMLElement, scene: PoseScene, on: boolean) {
  host.dataset.surface = on ? "computing" : "removing";
  void scene.setSurface(on).then(() => {
    // A later toggle may have changed it again; only the latest request marks the host.
    if (host.dataset.surface === (on ? "computing" : "removing")) {
      host.dataset.surface = on ? "on" : "off";
    }
  });
}

/** Plays the drug coming in, and reports the verdict once it has arrived. */
function playDock(
  scene: PoseScene,
  verdict: PoseViewerProps["verdict"],
  arrived: (outcome: BindingVerdict | null) => void,
) {
  arrived(null);
  if (verdict === null || verdict === undefined) return;
  const still =
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  scene.playDock(verdict.outcome, {
    still,
    onDone: () => {
      arrived(verdict.outcome);
    },
  });
}
