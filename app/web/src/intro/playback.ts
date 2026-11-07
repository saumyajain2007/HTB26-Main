import { useEffect, useRef, useState, useSyncExternalStore } from "react";

/*
 * Playback for the homepage story: chapters that advance on their own, pause and resume where
 * they stopped, stop in hidden tabs, and never move by themselves under reduced motion.
 */

const MOTION_QUERY = "(prefers-reduced-motion: reduce)";

function subscribeToMotion(callback: () => void) {
  const media = window.matchMedia(MOTION_QUERY);
  media.addEventListener("change", callback);
  return () => {
    media.removeEventListener("change", callback);
  };
}

function subscribeToVisibility(callback: () => void) {
  document.addEventListener("visibilitychange", callback);
  return () => {
    document.removeEventListener("visibilitychange", callback);
  };
}

export function useReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribeToMotion,
    () => window.matchMedia(MOTION_QUERY).matches,
    () => true,
  );
}

/** How the camera reaches a chapter: at once, on its own (slow), or because the reader chose it. */
export type CameraMode = "instant" | "automatic" | "pointer";

export interface Chapters {
  index: number;
  camera: CameraMode;
  playing: boolean;
  reduced: boolean;
  /** Bumped by Replay, so scenes can restart their own loops. */
  revision: number;
  /** Choose a chapter; keyboard choices (`immediate`) skip the camera move. */
  select: (next: number, immediate?: boolean) => void;
  toggle: () => void;
  replay: () => void;
}

/**
 * Chapters with the given durations in ms. The last chapter holds unless `loop` is set. Time
 * already spent in a chapter survives Pause, so Play resumes rather than restarts it.
 */
export function useChapters(durations: readonly number[], { loop = false } = {}): Chapters {
  const reduced = useReducedMotion();
  const visible = useSyncExternalStore(
    subscribeToVisibility,
    () => !document.hidden,
    () => true,
  );
  const [enabled, setEnabled] = useState(true);
  const [index, setIndex] = useState(0);
  const [camera, setCamera] = useState<CameraMode>("instant");
  const [revision, setRevision] = useState(0);
  const elapsed = useRef(0);
  const generation = useRef(0);

  const playing = enabled && visible && !reduced;
  const last = durations.length - 1;
  const holds = !loop && index >= last;

  useEffect(() => {
    if (!playing || holds) return;
    const started = performance.now();
    const version = generation.current;
    let advanced = false;
    const timer = window.setTimeout(
      () => {
        advanced = true;
        elapsed.current = 0;
        setCamera("automatic");
        setIndex((value) => (value + 1) % durations.length);
      },
      Math.max(0, (durations[index] ?? 0) - elapsed.current),
    );
    return () => {
      window.clearTimeout(timer);
      if (!advanced && generation.current === version) {
        elapsed.current += performance.now() - started;
      }
    };
  }, [index, playing, holds, revision, durations]);

  return {
    index,
    camera,
    playing,
    reduced,
    revision,
    select: (next, immediate = false) => {
      generation.current += 1;
      elapsed.current = 0;
      setCamera(immediate ? "instant" : "pointer");
      setIndex(next);
    },
    toggle: () => {
      setEnabled((value) => !value);
    },
    replay: () => {
      generation.current += 1;
      elapsed.current = 0;
      setCamera("instant");
      setIndex(0);
      setEnabled(true);
      setRevision((value) => value + 1);
    },
  };
}

export interface Playback {
  playing: boolean;
  reduced: boolean;
  toggle: () => void;
}

/** A free-running loop's playback: on until paused, off in hidden tabs and under reduced motion. */
export function usePlayback(): Playback {
  const reduced = useReducedMotion();
  const visible = useSyncExternalStore(
    subscribeToVisibility,
    () => !document.hidden,
    () => true,
  );
  const [enabled, setEnabled] = useState(true);
  return {
    playing: enabled && visible && !reduced,
    reduced,
    toggle: () => {
      setEnabled((value) => !value);
    },
  };
}
