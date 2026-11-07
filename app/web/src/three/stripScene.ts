import { PerspectiveCamera, Scene, Vector3, type WebGLRenderer } from "three";
import type { Conformer } from "../api/types";
import { Molecule, type MoleculeView } from "./moleculeScene";
import { createRenderer, dragToRotate, FOV, TAN_HALF_FOV, watchReducedMotion } from "./plate";

/** One place in the strip: the element it is drawn over, its letter layer and its molecule. */
export interface StripSlot {
  element: HTMLElement;
  labels: HTMLElement;
  conformer: Conformer;
}

interface LiveSlot {
  slot: StripSlot;
  scene: Scene;
  camera: PerspectiveCamera;
  molecule: Molecule;
  drag: ReturnType<typeof dragToRotate>;
  view: MoleculeView;
  width: number;
  height: number;
}

/**
 * Several molecules side by side on one shared canvas, so a comparison costs one WebGL context
 * instead of one per drug (browsers allow only a handful). The canvas lies under all the slots;
 * each frame, every molecule is drawn into its own slot's rectangle with a scissored viewport.
 * Each slot element takes its own drags, so every molecule turns on its own.
 */
export class StripScene {
  private readonly canvas: HTMLCanvasElement;
  private readonly renderer: WebGLRenderer;
  private readonly motion = watchReducedMotion();
  private readonly resizeObserver: ResizeObserver;
  private readonly intersectionObserver: IntersectionObserver;
  private slots: (LiveSlot | null)[] = [];
  private width = 0;
  private height = 0;
  private visible = true;
  private frameId = 0;
  private last = performance.now();
  private readonly projected = new Vector3();

  /** Starts a strip on a new canvas inside `host`, or returns null without WebGL. */
  static create(host: HTMLElement, canvasClass: string): StripScene | null {
    const canvas = document.createElement("canvas");
    canvas.className = canvasClass;
    const renderer = createRenderer(canvas);
    if (renderer === null) return null;
    host.prepend(canvas);
    return new StripScene(canvas, renderer);
  }

  private constructor(canvas: HTMLCanvasElement, renderer: WebGLRenderer) {
    this.canvas = canvas;
    this.renderer = renderer;
    this.resizeObserver = new ResizeObserver(() => {
      this.resize();
    });
    this.resizeObserver.observe(canvas);
    this.intersectionObserver = new IntersectionObserver(([entry]) => {
      this.visible = entry?.isIntersecting ?? true;
    });
    this.intersectionObserver.observe(canvas);
    this.frameId = requestAnimationFrame(this.loop);
  }

  /** Puts these molecules in these slots; a slot whose molecule is unchanged keeps its turn. */
  setSlots(slots: readonly (StripSlot | null)[]): void {
    const next = slots.map((slot, index) => {
      const live = this.slots[index] ?? null;
      if (
        live !== null &&
        slot !== null &&
        live.slot.conformer === slot.conformer &&
        live.slot.element === slot.element
      ) {
        return live;
      }
      if (live !== null) this.release(live);
      return slot === null ? null : this.build(slot);
    });
    for (const live of this.slots.slice(slots.length)) if (live !== null) this.release(live);
    this.slots = next;
  }

  dispose(): void {
    cancelAnimationFrame(this.frameId);
    this.resizeObserver.disconnect();
    this.intersectionObserver.disconnect();
    this.motion.dispose();
    for (const live of this.slots) if (live !== null) this.release(live);
    this.slots = [];
    this.renderer.dispose();
    this.renderer.forceContextLoss();
    this.canvas.remove();
  }

  private build(slot: StripSlot): LiveSlot {
    const scene = new Scene();
    const camera = new PerspectiveCamera(FOV, 1, 0.1, 200);
    const molecule = new Molecule(slot.conformer, slot.labels);
    scene.add(molecule.group);
    const drag = dragToRotate(slot.element, molecule.rotation, {
      reducedMotion: this.motion.reduced,
    });
    const live: LiveSlot = {
      slot,
      scene,
      camera,
      molecule,
      drag,
      width: 0,
      height: 0,
      view: {
        camera,
        size: () => ({ width: live.width, height: live.height }),
        reducedMotion: this.motion.reduced,
        pixelsPerUnit: () => live.height / 2 / (camera.position.z * TAN_HALF_FOV),
        project: (point) => {
          this.projected.copy(point).project(camera);
          return {
            x: (this.projected.x * 0.5 + 0.5) * live.width,
            y: (-this.projected.y * 0.5 + 0.5) * live.height,
          };
        },
      },
    };
    return live;
  }

  private release(live: LiveSlot): void {
    live.drag.dispose();
    live.scene.remove(live.molecule.group);
    live.molecule.dispose();
  }

  private resize(): void {
    const width = this.canvas.clientWidth;
    const height = this.canvas.clientHeight;
    if (width === this.width && height === this.height) return;
    this.width = width;
    this.height = height;
    if (width > 0 && height > 0) this.renderer.setSize(width, height, false);
  }

  private readonly loop = (now: number): void => {
    this.frameId = requestAnimationFrame(this.loop);
    const seconds = Math.min(0.05, (now - this.last) / 1000);
    this.last = now;
    if (!this.visible || document.hidden || this.width === 0 || this.height === 0) return;

    const { renderer } = this;
    const box = this.canvas.getBoundingClientRect();
    renderer.setScissorTest(false);
    renderer.clear();
    renderer.setScissorTest(true);
    for (const live of this.slots) {
      if (live === null) continue;
      const rect = live.slot.element.getBoundingClientRect();
      if (rect.width < 1 || rect.height < 1) continue;
      if (rect.width !== live.width || rect.height !== live.height) {
        live.width = rect.width;
        live.height = rect.height;
        live.camera.aspect = rect.width / rect.height;
        live.camera.updateProjectionMatrix();
      }
      live.molecule.frame(seconds, live.view, live.drag);
      // WebGL counts the viewport from the canvas's bottom-left corner.
      const x = rect.left - box.left;
      const y = this.height - (rect.top - box.top) - rect.height;
      renderer.setViewport(x, y, rect.width, rect.height);
      renderer.setScissor(x, y, rect.width, rect.height);
      renderer.render(live.scene, live.camera);
    }
  };
}
