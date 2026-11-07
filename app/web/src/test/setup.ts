import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, vi } from "vitest";
import { fakeApi, server } from "./server";

/*
 * jsdom has no WebGL, no layout and no Web Animations. These stand-ins let the 3D figures, the
 * charts and the intro's animations run their real code paths in tests: three's renderer draws
 * nothing, a canvas reports a WebGL context, observed elements report a fixed size, and
 * animations hold still.
 */
const noop = () => undefined;

vi.mock("three", async (importOriginal) => {
  const three = await importOriginal<typeof import("three")>();
  class FakeWebGLRenderer {
    readonly domElement: HTMLCanvasElement;
    outputColorSpace = "";
    setPixelRatio = noop;
    setSize = noop;
    setClearColor = noop;
    render = noop;
    clear = noop;
    setViewport = noop;
    setScissor = noop;
    setScissorTest = noop;
    dispose = noop;
    forceContextLoss = noop;
    constructor(options: { canvas?: HTMLCanvasElement } = {}) {
      this.domElement = options.canvas ?? document.createElement("canvas");
    }
  }
  return { ...three, WebGLRenderer: FakeWebGLRenderer };
});

/**
 * 3Dmol.js stands in as a viewer that keeps its models and surfaces in lists and draws nothing.
 * Like the real 3Dmol 2.x, `addSurface` answers a promise of the surface's ID, and it puts one
 * canvas in its element, so the step's WebGL canvases can be counted.
 */
vi.mock("3dmol", () => {
  class FakeModel {
    setStyle = noop;
    selectedAtoms = () => [{ x: 0, y: 0, z: 0, chain: "A", resi: 1 }];
  }
  class FakeViewer {
    readonly models: FakeModel[] = [];
    readonly surfaces = new Set<number>();
    private readonly canvas: HTMLCanvasElement;
    private nextSurface = 1;
    constructor(element: HTMLElement) {
      this.canvas = document.createElement("canvas");
      element.append(this.canvas);
    }
    addModel = () => {
      const model = new FakeModel();
      this.models.push(model);
      return model;
    };
    removeModel = (model: FakeModel) => {
      this.models.splice(this.models.indexOf(model), 1);
    };
    addSurface = () => {
      const id = this.nextSurface++;
      this.surfaces.add(id);
      return Promise.resolve(id);
    };
    removeSurface = (id: number) => {
      this.surfaces.delete(id);
    };
    getCanvas = () => this.canvas;
    getRenderer = () => ({ getContext: () => this.canvas.getContext("webgl2") });
    getView = () => [0, 0, 0, 0, 0, 0, 0, 1];
    setStyle = noop;
    setViewStyle = noop;
    setView = noop;
    setCameraParameters = noop;
    setPerceivedDistance = noop;
    zoomTo = noop;
    spin = noop;
    render = noop;
    clear = noop;
  }
  return {
    createViewer: (element: HTMLElement) => new FakeViewer(element),
    Parsers: { sdf: () => [[{ x: 0, y: 0, z: 0 }]] },
    SurfaceType: { VDW: 1 },
  };
});

HTMLCanvasElement.prototype.getContext = function getContext(type: string) {
  return type.startsWith("webgl")
    ? ({ getExtension: () => null } as unknown as RenderingContext)
    : null;
} as typeof HTMLCanvasElement.prototype.getContext;

/** Reports a 800 × 600 box for every observed element, once, like a first layout. */
class FixedSizeResizeObserver {
  private readonly callback: ResizeObserverCallback;
  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
  }
  observe(target: Element) {
    queueMicrotask(() => {
      const contentRect = { width: 800, height: 600 } as DOMRectReadOnly;
      this.callback([{ target, contentRect } as ResizeObserverEntry], this);
    });
  }
  unobserve = noop;
  disconnect = noop;
}

class AlwaysVisibleIntersectionObserver {
  observe = noop;
  unobserve = noop;
  disconnect = noop;
  takeRecords = () => [];
}

/** An identity 2D matrix, enough for the lab's camera to compare one frame with the next. */
class IdentityDOMMatrix {
  a = 1;
  b = 0;
  c = 0;
  d = 1;
  e = 0;
  f = 0;
}

/** A Web Animation that never runs: it pauses, plays and cancels, and never finishes. */
function stillAnimation(): Animation {
  return {
    currentTime: 0,
    finished: new Promise<Animation>(noop),
    play: noop,
    pause: noop,
    cancel: noop,
  } as unknown as Animation;
}

/** SVG paths have no geometry in jsdom: every path is a single point at the origin. */
Object.assign(SVGElement.prototype, {
  getTotalLength: () => 0,
  getPointAtLength: () => ({ x: 0, y: 0 }) as DOMPoint,
});
Element.prototype.animate = stillAnimation;

vi.stubGlobal("DOMMatrix", IdentityDOMMatrix);
vi.stubGlobal("ResizeObserver", FixedSizeResizeObserver);
vi.stubGlobal("IntersectionObserver", AlwaysVisibleIntersectionObserver);
vi.stubGlobal(
  "matchMedia",
  (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: noop,
      removeEventListener: noop,
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList,
);

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
});

afterEach(() => {
  cleanup();
  server.resetHandlers();
  fakeApi.experiments.clear();
  fakeApi.followedUp.length = 0;
});

afterAll(() => {
  server.close();
});
