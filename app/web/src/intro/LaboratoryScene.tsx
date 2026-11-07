import { useEffect, useId, useLayoutEffect, useRef } from "react";
import background from "./assets/laboratory.webp";
import microscope from "./assets/microscope.webp";
import researcher from "./assets/researcher.webp";
import styles from "./laboratory.module.css";
import { MonitorStory } from "./MonitorStory";
import type { CameraMode } from "./playback";

/*
 * Jessica's animated laboratory (Jessica-mak/half-life-ui, round three), ported to CSS Modules.
 * One HTML plane holds the illustration in fixed 1672x941 coordinates; a resize projection fills
 * the viewport and a camera transform travels between chapters with the Web Animations API.
 */

const WIDTH = 1672;
const HEIGHT = 941;

// The raised forearm, cut at the cuff in the character's own coordinates so it can articulate.
const ARM_OUTLINE =
  "410,274 496,255 549,363 578,447 615,521 730,746 675,766 604,655 514,592 458,623 397,593 392,533 419,448 414,359";

/** Where the camera rests for each problem chapter: the bench, then into the monitor. */
const CAMERA = [
  "translate3d(0px, 0px, 0) scale(1)",
  "translate3d(-1360px, -82px, 0) scale(1.75)",
  "translate3d(-1570px, -150px, 0) scale(1.9)",
  "translate3d(-750px, -40px, 0) scale(1.4)",
] as const;

export function LaboratoryScene({
  chapter,
  playing,
  reduced,
  camera: mode,
  revision,
}: {
  /** 0 to 3; anything else rests on the bench. */
  chapter: number;
  playing: boolean;
  reduced: boolean;
  camera: CameraMode;
  revision: number;
}) {
  const camera = useRef<HTMLDivElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const projection = useRef<HTMLDivElement>(null);
  const transition = useRef<Animation | null>(null);

  useLayoutEffect(() => {
    const host = viewport.current;
    const plane = projection.current;
    if (!host || !plane) return;
    const resize = () => {
      const scale = Math.max(host.clientWidth / WIDTH, host.clientHeight / HEIGHT);
      const x = (host.clientWidth - WIDTH * scale) / 2;
      const y = (host.clientHeight - HEIGHT * scale) / 2;
      plane.style.transform = `translate3d(${String(x)}px, ${String(y)}px, 0) scale(${String(scale)})`;
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(host);
    return () => {
      observer.disconnect();
    };
  }, []);

  useLayoutEffect(() => {
    const node = camera.current;
    const host = viewport.current;
    if (!node) return;
    const destination = (CAMERA as readonly string[])[chapter] ?? CAMERA[0];
    const from = getComputedStyle(node).transform;
    node.style.transform = destination;
    const current = new DOMMatrix(from);
    const target = new DOMMatrix(destination);
    const sameFrame = (["a", "b", "c", "d", "e", "f"] as const).every(
      (key) => Math.abs(current[key] - target[key]) < 0.0001,
    );
    if (reduced || mode === "instant" || sameFrame) return;
    const animation = node.animate([{ transform: from }, { transform: destination }], {
      duration: mode === "pointer" ? 900 : 1600,
      easing:
        mode === "pointer" ? "cubic-bezier(0.23, 1, 0.32, 1)" : "cubic-bezier(0.77, 0, 0.175, 1)",
    });
    transition.current = animation;
    // Hold the illustration's own loops while the camera travels; resume them on arrival.
    host?.setAttribute("data-camera-moving", "true");
    const settle = () => {
      if (transition.current !== animation) return;
      transition.current = null;
      host?.removeAttribute("data-camera-moving");
    };
    void animation.finished.then(settle, settle);
    return () => {
      // Another chapter interrupted this move: retarget from the frame on screen.
      node.style.transform = getComputedStyle(node).transform;
      animation.cancel();
      host?.removeAttribute("data-camera-moving");
      if (transition.current === animation) transition.current = null;
    };
  }, [chapter, reduced, mode, revision]);

  useEffect(() => {
    if (playing) transition.current?.play();
    else transition.current?.pause();
  }, [playing, chapter, revision]);

  const id = useId().replaceAll(":", "");
  const bodyMask = `${id}-body`;
  const armClip = `${id}-arm`;

  return (
    <div className={styles.lab} ref={viewport} data-playing={playing}>
      <div className={styles.projection} ref={projection}>
        <div className={styles.camera} ref={camera}>
          <svg
            className={styles.scene}
            viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT)}`}
            preserveAspectRatio="xMidYMid slice"
            role="img"
            aria-label="A scientist pipettes a sample beside a microscope while a protein network display lights up."
          >
            <defs>
              <mask id={bodyMask} maskUnits="userSpaceOnUse" x="0" y="0" width="1637" height="961">
                <rect width="1637" height="961" fill="white" />
                <polygon points={ARM_OUTLINE} fill="black" />
              </mask>
              <clipPath id={armClip}>
                <polygon points={ARM_OUTLINE} />
              </clipPath>
            </defs>
            <image href={background} width={WIDTH} height={HEIGHT} />
            <g aria-hidden="true">
              <path
                d="M1180 470h130l42-27 25 12 40-53 32 26 45-8 45 17"
                fill="none"
                stroke="#69dfeb"
                strokeWidth="3"
                opacity=".65"
              />
              <circle
                className={styles.monitorSignal}
                data-motion-target
                cx="1308"
                cy="470"
                r="7"
                fill="#9cf4ff"
              />
              <circle
                className={styles.proteinSignal}
                data-motion-target
                cx="1495"
                cy="150"
                r="12"
                fill="#9cf4ff"
              />
            </g>
            <svg x="42" y="34" width="1473" height="865" viewBox="0 0 1637 961" overflow="visible">
              {/* A coat underlap so no gap opens as the separate pipetting arm moves. */}
              <path d="M500 525h110l140 255H590L470 620Z" fill="#98aaea" />
              <path d="m550 550 142 150-102 80-75-160Z" fill="#879de4" />
              <image href={researcher} width="1637" height="961" mask={`url(#${bodyMask})`} />
              <g className={styles.arm} data-motion-target>
                <image href={researcher} width="1637" height="961" clipPath={`url(#${armClip})`} />
              </g>
            </svg>
            <g aria-hidden="true">
              <ellipse cx="688" cy="851" rx="62" ry="17" fill="#73bed5" opacity=".7" />
              <path d="M626 845v12c0 22 124 22 124 0v-12" fill="#b4dded" opacity=".8" />
              <ellipse cx="688" cy="844" rx="62" ry="16" fill="#d4f3fb" opacity=".8" />
              <ellipse
                className={styles.ripple}
                data-motion-target
                cx="688"
                cy="844"
                rx="25"
                ry="7"
                fill="none"
                stroke="#389bbe"
                strokeWidth="3"
              />
              <g className={styles.drop} data-motion-target>
                <path
                  d="M680 701c-14 20-17 25-17 32a17 17 0 0 0 34 0c0-7-3-12-17-32Z"
                  fill="#9cecf5"
                />
              </g>
            </g>
            <image href={microscope} x="823" y="399" width="350" height="525" />
            <g className={styles.focusLight} data-motion-target aria-hidden="true">
              <ellipse cx="997" cy="683" rx="38" ry="7" fill="#b0f4ff" opacity=".7" />
            </g>
            <MonitorStory chapter={chapter} />
          </svg>
        </div>
      </div>
    </div>
  );
}
