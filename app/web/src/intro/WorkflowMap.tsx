import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { usePlayback } from "./playback";
import workflowMap from "./workflow-map.json";
import styles from "./workflowMap.module.css";
import { WorkflowVisual } from "./WorkflowVisual";

/*
 * The workflow at a glance (after Jessica's TechnicalOverview): seven nodes on a 1280 x 520 map,
 * with three signals that travel each route in turn and light the node they leave or reach.
 */

const { nodes, routes } = workflowMap;

const WIDTH = 1280;
const HEIGHT = 520;
const PHASES = routes.length;
const PHASE_DURATION = 4600;
const DURATION = PHASES * PHASE_DURATION;
/** When, within a phase, the signal leaves and reaches its node. */
const DEPART = 2400;
const TRAVEL = 1500;
const ARRIVE = 3900;
const SAMPLES = 40;

const cx = (...names: (string | false | undefined)[]) => names.filter(Boolean).join(" ");

function Glyph({ name }: { name: "play" | "pause" | "replay" }) {
  return (
    <svg className={styles.glyph} viewBox="0 0 16 16" aria-hidden="true">
      {name === "play" && <path d="M5 3.5v9l7-4.5Z" />}
      {name === "pause" && <path d="M5.5 3.5v9M10.5 3.5v9" />}
      {name === "replay" && <path d="M3.5 8a4.5 4.5 0 1 0 1.3-3.2M3.5 2.5v2.8h2.8" />}
    </svg>
  );
}

/** Keyframes that carry a signal along every route in turn, resting between phases. */
function signalFrames(paths: readonly (SVGPathElement | null)[]): Keyframe[] {
  const frames: Keyframe[] = [];
  paths.forEach((path, index) => {
    if (!path) return;
    const length = path.getTotalLength();
    const start = index * PHASE_DURATION;
    const frame = (fraction: number, time: number, opacity: number) => {
      const point = path.getPointAtLength(length * fraction);
      frames.push({
        offset: time / DURATION,
        transform: `translate3d(${String(point.x)}px, ${String(point.y)}px, 0)`,
        opacity,
      });
    };
    frame(0, start, 0);
    frame(0, start + DEPART - 200, 0);
    frame(0, start + DEPART, 1);
    for (let sample = 1; sample <= SAMPLES; sample++) {
      frame(sample / SAMPLES, start + DEPART + (sample / SAMPLES) * TRAVEL, 1);
    }
    frame(1, start + ARRIVE + 350, 0);
    frame(1, start + PHASE_DURATION, 0);
  });
  return frames;
}

export function WorkflowMap({ className }: { className?: string | undefined }) {
  const playback = usePlayback();
  const [revision, setRevision] = useState(0);
  const [phase, setPhase] = useState(0);
  const [arrived, setArrived] = useState(false);
  const canvas = useRef<HTMLDivElement>(null);
  const plane = useRef<HTMLDivElement>(null);
  const paths = useRef<(SVGPathElement | null)[]>([]);
  const signals = useRef<(HTMLSpanElement | null)[]>([]);
  const animations = useRef<Animation[]>([]);
  const id = useId().replaceAll(":", "");
  const arrow = `workflow-arrow-${id}`;
  const route = routes[phase];
  const active = arrived ? route?.to : route?.from;

  // The signals move in map coordinates; scale their plane to the drawn map.
  useLayoutEffect(() => {
    const host = canvas.current;
    const world = plane.current;
    if (!host || !world) return;
    const resize = () => {
      world.style.transform = `scale(${String(host.clientWidth / WIDTH)})`;
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(host);
    return () => {
      observer.disconnect();
    };
  }, [playback.reduced]);

  useEffect(() => {
    if (playback.reduced) return;
    const frames = signalFrames(paths.current);
    animations.current = signals.current.flatMap((signal, index) => {
      if (!signal) return [];
      const animation = signal.animate(frames, {
        duration: DURATION,
        iterations: Infinity,
        delay: index * 180,
        fill: "both",
      });
      animation.pause();
      return [animation];
    });
    const timer = window.setInterval(() => {
      const time = Number(animations.current[0]?.currentTime ?? 0) % DURATION;
      setPhase(Math.floor(time / PHASE_DURATION));
      setArrived(time % PHASE_DURATION >= ARRIVE);
    }, 160);
    return () => {
      window.clearInterval(timer);
      animations.current.forEach((animation) => {
        animation.cancel();
      });
      animations.current = [];
    };
  }, [revision, playback.reduced]);

  useEffect(() => {
    animations.current.forEach((animation) => {
      if (playback.playing) {
        animation.play();
      } else {
        animation.pause();
      }
    });
  }, [playback.playing, playback.reduced, revision]);

  const replay = () => {
    setPhase(0);
    setArrived(false);
    setRevision((value) => value + 1);
    if (!playback.playing) playback.toggle();
  };

  return (
    <section
      className={cx(styles.root, className)}
      aria-label="Half Life workflow"
      data-playing={playback.playing}
      data-reduced={playback.reduced}
    >
      <div className={styles.scroller}>
        <div
          className={styles.canvas}
          ref={canvas}
          role="group"
          aria-label="Half Life technical workflow"
        >
          <svg
            className={styles.routes}
            viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT)}`}
            aria-hidden="true"
          >
            <defs>
              <marker
                id={arrow}
                viewBox="0 0 10 10"
                refX="9"
                refY="5"
                markerWidth="6"
                markerHeight="6"
                orient="auto"
              >
                <path className={styles.arrowhead} d="m1 1 8 4-8 4" />
              </marker>
            </defs>
            {routes.map((edge, index) => (
              <path
                key={`${edge.from}-${edge.to}`}
                d={edge.d}
                className={styles.route}
                data-dashed={edge.dashed === true}
                markerEnd={`url(#${arrow})`}
                ref={(node) => {
                  paths.current[index] = node;
                }}
              />
            ))}
          </svg>
          <div className={styles.nodes}>
            {nodes.map((node) => (
              <article
                key={node.id}
                className={styles.node}
                data-node={node.id}
                data-active={!playback.reduced && active === node.id}
                style={{
                  left: `${String((node.x / WIDTH) * 100)}%`,
                  top: `${String((node.y / HEIGHT) * 100)}%`,
                  width: `${String((node.w / WIDTH) * 100)}%`,
                  height: `${String((node.h / HEIGHT) * 100)}%`,
                }}
              >
                <h3 className={styles.title}>{node.title}</h3>
                <p className={styles.keyPoint}>{node.keyPoint}</p>
                <WorkflowVisual key={`${node.id}-${String(revision)}`} kind={node.id} />
                <p className={styles.copy}>
                  {node.lines.map((line) => (
                    <span key={line}>{line}</span>
                  ))}
                </p>
              </article>
            ))}
          </div>
          {!playback.reduced && (
            <div className={styles.plane} ref={plane} aria-hidden="true">
              {[0, 1, 2].map((index) => (
                <span
                  className={styles.signal}
                  key={index}
                  ref={(node) => {
                    signals.current[index] = node;
                  }}
                />
              ))}
            </div>
          )}
        </div>
      </div>
      <div className={styles.controls} role="group" aria-label="Workflow animation">
        <button type="button" disabled={playback.reduced} onClick={playback.toggle}>
          <Glyph name={playback.playing ? "pause" : "play"} />
          {playback.reduced ? "Reduced motion" : playback.playing ? "Pause" : "Play"}
        </button>
        <button type="button" disabled={playback.reduced} onClick={replay}>
          <Glyph name="replay" />
          Replay
        </button>
      </div>
    </section>
  );
}
