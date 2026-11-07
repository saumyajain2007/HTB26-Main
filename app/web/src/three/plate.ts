import {
  BackSide,
  FrontSide,
  Mesh,
  PerspectiveCamera,
  Scene,
  ShaderMaterial,
  SRGBColorSpace,
  Vector3,
  WebGLRenderer,
} from "three";

/**
 * Shared machinery for the print-style WebGL plates (the protein network and the molecule):
 * a renderer that sizes itself to its canvas and pauses when off screen, drag-to-rotate, and a
 * flat two-tone material with ink outlines, so the 3D reads like the charts beside it.
 */

/** A narrow field of view keeps perspective mild, like an engraving rather than a photo. */
export const FOV = 12;
export const TAN_HALF_FOV = Math.tan(((FOV / 2) * Math.PI) / 180);

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

export function clamp(value: number, low: number, high: number): number {
  return Math.max(low, Math.min(high, value));
}

/** A design-token colour from tokens.css, e.g. `--color-disease`, as `#rrggbb`. */
export function tokenColor(name: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return /^#[0-9a-f]{6}$/i.test(value) ? value : "#000000";
}

/** `#rrggbb` as a linear-free RGB triple in 0..1; the plates write sRGB straight out. */
export function rgb(hex: string): Vector3 {
  const channel = (start: number) => parseInt(hex.slice(start, start + 2), 16) / 255;
  return new Vector3(channel(1), channel(3), channel(5));
}

const VERTEX = `
varying vec3 vNormal;
varying vec3 vPosition;
void main() {
  vPosition = position;
  vNormal = normalize(normalMatrix * normal);
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`;

// Two tones only: lit and shaded. uSplit draws the top half in uA and the bottom in uB with a
// thin ink band between them (a protein that is both a disease protein and a drug target).
// uMix fades the colour toward paper for de-emphasised objects.
const FRAGMENT = `
uniform vec3 uA;
uniform vec3 uB;
uniform float uSplit;
uniform float uMix;
uniform float uShade;
varying vec3 vNormal;
varying vec3 vPosition;
void main() {
  vec3 base = uA;
  if (uSplit > 0.5) {
    base = vPosition.y >= 0.0 ? uA : uB;
    if (abs(vPosition.y) < 0.075) base = vec3(0.0);
  }
  float light = dot(normalize(vNormal), normalize(vec3(-0.45, 0.6, 0.66)));
  vec3 colour = base * (light > -0.12 ? 1.0 : uShade);
  gl_FragColor = vec4(mix(vec3(1.0), colour, uMix), 1.0);
}`;

export interface FlatUniforms {
  [uniform: string]: { value: unknown };
  uA: { value: Vector3 };
  uB: { value: Vector3 };
  uSplit: { value: number };
  uMix: { value: number };
  uShade: { value: number };
}

export type FlatMaterial = ShaderMaterial & { uniforms: FlatUniforms };

interface FlatOptions {
  /** Draw back faces only: an inverted hull, slightly larger than its mesh, is its outline. */
  outline?: boolean;
  /** How dark the shaded side is, as a fraction of the lit colour. */
  shade?: number;
}

export function flatMaterial(hex: string, options: FlatOptions = {}): FlatMaterial {
  const uniforms: FlatUniforms = {
    uA: { value: rgb(hex) },
    uB: { value: rgb(hex) },
    uSplit: { value: 0 },
    uMix: { value: 1 },
    uShade: { value: options.shade ?? 0.82 },
  };
  return new ShaderMaterial({
    vertexShader: VERTEX,
    fragmentShader: FRAGMENT,
    side: options.outline === true ? BackSide : FrontSide,
    uniforms,
  }) as FlatMaterial;
}

const UP = new Vector3(0, 1, 0);

/** Stretches a unit cylinder mesh so it runs from `a` to `b`. Keeps its x/z scale. */
export function placeCylinder(mesh: Mesh, a: Vector3, b: Vector3): void {
  const direction = new Vector3().subVectors(b, a);
  const length = direction.length();
  mesh.position.copy(a).add(b).multiplyScalar(0.5);
  mesh.quaternion.setFromUnitVectors(UP, direction.normalize());
  mesh.scale.y = length;
}

export interface Plate {
  /** The plate's own canvas: a fresh one per plate, so a remount never reuses a lost context. */
  readonly canvas: HTMLCanvasElement;
  readonly scene: Scene;
  readonly camera: PerspectiveCamera;
  /** Canvas size in CSS pixels; 0 while hidden. */
  size(): { width: number; height: number };
  /** True while the user asks for reduced motion: no ambient rotation, no easing. */
  reducedMotion(): boolean;
  /** Called before each rendered frame with the seconds since the last one. */
  onFrame(callback: (seconds: number) => void): void;
  /**
   * Draws a frame now rather than on the next animation frame, so a new plate is never blank
   * on screen: a view transition, say, captures the page before that frame.
   */
  draw(): void;
  /** CSS pixels per world unit at the origin's depth. */
  pixelsPerUnit(): number;
  /** Projects a world point to canvas pixels. */
  project(point: Vector3): { x: number; y: number };
  dispose(): void;
}

/** A transparent, antialiased WebGL renderer on `canvas`, or null when the browser has no WebGL. */
export function createRenderer(canvas: HTMLCanvasElement): WebGLRenderer | null {
  let renderer: WebGLRenderer;
  try {
    renderer = new WebGLRenderer({ canvas, antialias: true, alpha: true });
  } catch {
    return null;
  }
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.outputColorSpace = SRGBColorSpace;
  renderer.setClearColor(0xffffff, 0);
  return renderer;
}

/** Follows `prefers-reduced-motion` as it changes. */
export function watchReducedMotion(): { reduced: () => boolean; dispose: () => void } {
  const query = window.matchMedia(REDUCED_MOTION);
  let reduced = query.matches;
  const onChange = (event: MediaQueryListEvent) => {
    reduced = event.matches;
  };
  query.addEventListener("change", onChange);
  return {
    reduced: () => reduced,
    dispose: () => {
      query.removeEventListener("change", onChange);
    },
  };
}

/** Releases every mesh's geometry and material in `scene`. */
export function disposeScene(scene: Scene): void {
  scene.traverse((object) => {
    if (object instanceof Mesh) {
      (object.geometry as { dispose(): void }).dispose();
      const materials: unknown[] = Array.isArray(object.material)
        ? object.material
        : [object.material];
      for (const material of materials) (material as { dispose(): void }).dispose();
    }
  });
}

/**
 * Starts a plate on a new canvas inside `host`, or returns null when the browser has no WebGL.
 * The canvas is removed again on dispose.
 */
export function createPlate(host: HTMLElement, canvasClass: string): Plate | null {
  const canvas = document.createElement("canvas");
  canvas.className = canvasClass;
  const renderer = createRenderer(canvas);
  if (renderer === null) return null;
  host.prepend(canvas);

  const scene = new Scene();
  const camera = new PerspectiveCamera(FOV, 1, 0.1, 200);
  const callbacks: ((seconds: number) => void)[] = [];
  let width = 0;
  let height = 0;
  let visible = true;
  let frame = 0;
  let last = performance.now();

  const motion = watchReducedMotion();

  const resize = () => {
    const nextWidth = canvas.clientWidth;
    const nextHeight = canvas.clientHeight;
    if (nextWidth === width && nextHeight === height) return;
    width = nextWidth;
    height = nextHeight;
    if (width === 0 || height === 0) return;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  };
  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(canvas);
  const intersectionObserver = new IntersectionObserver(([entry]) => {
    visible = entry?.isIntersecting ?? true;
  });
  intersectionObserver.observe(canvas);

  const render = (seconds: number) => {
    if (width === 0 || height === 0) return;
    for (const callback of callbacks) callback(seconds);
    renderer.render(scene, camera);
  };
  const loop = (now: number) => {
    frame = requestAnimationFrame(loop);
    const seconds = Math.min(0.05, (now - last) / 1000);
    last = now;
    if (!visible || document.hidden) return;
    render(seconds);
  };
  frame = requestAnimationFrame(loop);

  const projected = new Vector3();
  return {
    canvas,
    scene,
    camera,
    size: () => ({ width, height }),
    reducedMotion: motion.reduced,
    onFrame: (callback) => {
      callbacks.push(callback);
    },
    draw: () => {
      resize();
      render(0);
    },
    pixelsPerUnit: () => height / 2 / (camera.position.z * TAN_HALF_FOV),
    project: (point) => {
      projected.copy(point).project(camera);
      return { x: (projected.x * 0.5 + 0.5) * width, y: (-projected.y * 0.5 + 0.5) * height };
    },
    dispose: () => {
      cancelAnimationFrame(frame);
      resizeObserver.disconnect();
      intersectionObserver.disconnect();
      motion.dispose();
      disposeScene(scene);
      renderer.dispose();
      renderer.forceContextLoss();
      canvas.remove();
    },
  };
}

/** The camera distance that fits a sphere of `radius` into the canvas, whatever its shape. */
export function fitDistance(radius: number, aspect: number): number {
  return radius / TAN_HALF_FOV / Math.min(1, aspect);
}

export interface Rotation {
  x: number;
  y: number;
}

/**
 * Drag `canvas` (or any element) to rotate `rotation`. Vertical page scrolling still works on
 * touch screens: only sideways drags are captured there. Released drags coast to a stop unless
 * motion is reduced.
 */
export function dragToRotate(
  canvas: HTMLElement,
  rotation: Rotation,
  plate: { reducedMotion(): boolean },
) {
  let pointer: { id: number; x: number; y: number } | null = null;
  const velocity = { x: 0, y: 0 };

  const down = (event: PointerEvent) => {
    pointer = { id: event.pointerId, x: event.clientX, y: event.clientY };
    velocity.x = 0;
    velocity.y = 0;
    canvas.setPointerCapture(event.pointerId);
    canvas.dataset.dragging = "true";
  };
  const move = (event: PointerEvent) => {
    if (pointer?.id !== event.pointerId) return;
    const dx = event.clientX - pointer.x;
    const dy = event.clientY - pointer.y;
    pointer = { id: event.pointerId, x: event.clientX, y: event.clientY };
    velocity.y = dx * 0.008;
    velocity.x = dy * 0.008;
    rotation.y += velocity.y;
    rotation.x = clamp(rotation.x + velocity.x, -1.3, 1.3);
  };
  const up = (event: PointerEvent) => {
    if (pointer?.id !== event.pointerId) return;
    pointer = null;
    delete canvas.dataset.dragging;
    if (plate.reducedMotion()) {
      velocity.x = 0;
      velocity.y = 0;
    }
  };
  canvas.addEventListener("pointerdown", down);
  canvas.addEventListener("pointermove", move);
  canvas.addEventListener("pointerup", up);
  canvas.addEventListener("pointercancel", up);

  return {
    dragging: () => pointer !== null,
    /** Applies the coasting after a release. Call once per frame. */
    coast: () => {
      if (pointer !== null) return;
      rotation.y += velocity.y;
      rotation.x = clamp(rotation.x + velocity.x, -1.3, 1.3);
      velocity.x *= 0.92;
      velocity.y *= 0.92;
    },
    dispose: () => {
      canvas.removeEventListener("pointerdown", down);
      canvas.removeEventListener("pointermove", move);
      canvas.removeEventListener("pointerup", up);
      canvas.removeEventListener("pointercancel", up);
    },
  };
}

/** Easing factor for one frame: instant under reduced motion. */
export function easeFactor(seconds: number, plate: Plate): number {
  return plate.reducedMotion() ? 1 : 1 - Math.pow(0.0008, seconds);
}
