import {
  createViewer,
  Parsers,
  SurfaceType,
  type AtomSelectionSpec,
  type AtomSpec,
  type GLModel,
  type GLShape,
  type GLViewer,
  type Label,
} from "3dmol";
import { Box3, Matrix4, Quaternion, Vector3 } from "three";
import type { BindingVerdict } from "../lib/bindingVerdict";
import { DOCK_DURATION_MS, dockEndFrame, dockFrame, type DockFrame } from "./dockAnimation";
import { polarContacts, type Contact } from "./interactions";
import { tokenColor } from "./plate";

/**
 * A binding pose drawn with 3Dmol.js in the figure's print style (docs/engineering/design.md, "Binding
 * pose"): the protein as a thin backbone trace with ink outlines, the drug in sticks, the pocket's
 * residues as fine grey sticks. Optional: a translucent surface over the pocket and the drug's
 * crystal position, in the redock colour, to compare with the pose.
 */

/** Residues with an atom this close to the drug (Å) are drawn as sticks. */
const POCKET_ANGSTROM = 4.5;
/** Protein atoms this close to the drug (Å) carry the pocket surface. */
const SURFACE_ANGSTROM = 6;
/** Spin speed in degrees a second. */
const SPIN_DEGREES = 10;
/** The camera's vertical field of view in degrees: 3Dmol's default, set so framing can rely on it. */
const FIELD_OF_VIEW = 20;
/** How much of the view's width and height the framed atoms may take; the rest is margin. */
const FILL = 0.9;
/** Half the smallest height (Å) the view shows, so a lone fragment isn't blown up to fill it. */
const MIN_HALF_HEIGHT = 6;
/** Degrees the opening view tips the drug's top away from the reader, so it still reads as 3D. */
const TILT = 24;
/** How deep (Å) and how wide around the drug to look for protein in the way of the view. */
const FRONT_DEPTH = 16;
const FRONT_RADIUS = 7;

/** How far (Å) from its docked pose the drug starts its approach. */
const START_ANGSTROM = 16;
/** The starting tumble, as an axis and an angle in degrees. */
const TUMBLE_AXIS = new Vector3(0.6, 0.5, 0.62).normalize();
const TUMBLE_DEGREES = 110;

export interface PoseFiles {
  /** receptor.pdb: the protein chain the drug was docked into. */
  receptor: string;
  /** poses.sdf: the poses, best first. */
  poses: string;
  /** crystal_ligand.sdf: the co-crystal ligand in its crystal position. */
  crystal: string;
}

/** The first molecule of an SDF file: the best pose. */
export function firstMolecule(sdf: string): string {
  const end = sdf.indexOf("$$$$");
  return end === -1 ? sdf : `${sdf.slice(0, end + 4)}\n`;
}

/** Whether a point lies within `distance` of any of `atoms`. */
function near(atoms: readonly AtomSpec[], distance: number) {
  const limit = distance * distance;
  return (atom: AtomSpec) =>
    atoms.some((other) => {
      const dx = (atom.x ?? 0) - (other.x ?? 0);
      const dy = (atom.y ?? 0) - (other.y ?? 0);
      const dz = (atom.z ?? 0) - (other.z ?? 0);
      return dx * dx + dy * dy + dz * dz <= limit;
    });
}

/** The dominant direction of `points` around their centre (power iteration on the covariance). */
function principalAxis(points: readonly Vector3[], without?: Vector3): Vector3 {
  const centre = new Vector3();
  for (const point of points) centre.add(point);
  centre.divideScalar(Math.max(1, points.length));
  const spread = points.map((point) => {
    const offset = point.clone().sub(centre);
    // Leave out a direction already found, to get the next one.
    if (without) offset.addScaledVector(without, -offset.dot(without));
    return offset;
  });
  let axis = new Vector3(1, 0.7, 0.4).normalize();
  for (let step = 0; step < 32; step++) {
    const next = new Vector3();
    for (const offset of spread) next.addScaledVector(offset, offset.dot(axis));
    if (next.lengthSq() < 1e-12) break;
    axis = next.normalize();
  }
  return axis;
}

const toPoint = (atom: AtomSpec) => new Vector3(atom.x ?? 0, atom.y ?? 0, atom.z ?? 0);

/**
 * The rotation that shows a drug face-on: its longest extent across the screen, its second
 * across too, and its thinnest towards the reader, so a flat drug is seen flat and not edge-on.
 * Of the two face-on sides, it looks in from the one with less protein in the way.
 */
export function faceOn(drugAtoms: readonly AtomSpec[], proteinAtoms: readonly AtomSpec[]) {
  const points = drugAtoms.map(toPoint);
  if (points.length < 3) return new Quaternion();
  const centre = new Vector3();
  for (const point of points) centre.add(point);
  centre.divideScalar(points.length);
  const long = principalAxis(points);
  const wide = principalAxis(points, long);
  const thin = new Vector3().crossVectors(long, wide).normalize();
  // Protein atoms between the drug and the reader, within a column as wide as the pocket.
  let inFront = 0;
  for (const atom of proteinAtoms) {
    const offset = toPoint(atom).sub(centre);
    const depth = offset.dot(thin);
    if (Math.abs(depth) > FRONT_DEPTH) continue;
    const across = offset.addScaledVector(thin, -depth).length();
    if (across < FRONT_RADIUS) inFront += Math.sign(depth);
  }
  if (inFront > 0) {
    wide.negate();
    thin.negate();
  }
  // Rows long, wide and thin: the rotation that takes each onto the screen's x, y and z.
  const basis = new Matrix4().makeBasis(long, wide, thin).transpose();
  return new Quaternion().setFromRotationMatrix(basis);
}

/** A turn about the screen's own axis (x across, y up, z towards the reader), in degrees. */
export function screenTurn(axis: "x" | "y", degrees: number): Quaternion {
  const direction = axis === "x" ? new Vector3(1, 0, 0) : new Vector3(0, 1, 0);
  return new Quaternion().setFromAxisAngle(direction, (degrees * Math.PI) / 180);
}

export interface Framing {
  /** The point (in the structure's coordinates) at the middle of the view, and turned about. */
  centre: Vector3;
  /** The camera's distance from `centre`, in ångströms. */
  distance: number;
}

/**
 * Where the camera goes so that, turned by `turn`, the `subject` sits in the middle of a view of
 * this `aspect` (width over height) and it and its `surroundings` fill the view up to FILL on the
 * tighter side. `inset` is the share of the view's height covered at its top (by its controls);
 * as much is kept clear at the bottom, so the subject stays in the middle. Exact for a
 * perspective camera with a vertical field of view of `fov` degrees: a point nearer the reader
 * looks bigger, so each point is checked at its own depth.
 */
export function frame(
  subject: readonly Vector3[],
  surroundings: readonly Vector3[],
  turn: Quaternion,
  aspect: number,
  inset = 0,
  fov = FIELD_OF_VIEW,
): Framing {
  const turnPoint = (point: Vector3) => point.clone().applyQuaternion(turn);
  const middle = new Box3().setFromPoints(subject.map(turnPoint)).getCenter(new Vector3());
  const tanView = Math.tan((fov * Math.PI) / 360);
  const tanX = tanView * aspect;
  const tanY = tanView * Math.max(0.2, 1 - 2 * inset);
  let distance = MIN_HALF_HEIGHT / tanY;
  for (const point of [...subject, ...surroundings]) {
    const offset = turnPoint(point).sub(middle);
    const across = Math.max(Math.abs(offset.x) / tanX, Math.abs(offset.y) / tanY) / FILL;
    distance = Math.max(distance, offset.z + across);
  }
  return { centre: middle.applyQuaternion(turn.clone().invert()), distance };
}

/** 3Dmol keeps these observers private and never disconnects them; dispose does. */
interface ViewerInternals {
  divwatcher?: { disconnect(): void };
  intwatcher?: { disconnect(): void };
}

export class PoseScene {
  private readonly holder: HTMLElement;
  private readonly covered: () => number;
  private readonly viewer: GLViewer;
  private readonly receptor: GLModel;
  private readonly ligand: GLModel;
  private readonly crystal: string;
  private readonly pocket: AtomSelectionSpec;
  /** The opening view: its turn, the drug it centres on, and what else it fits in. */
  private readonly turn: Quaternion;
  private readonly drugPoints: Vector3[];
  private readonly surroundings: Vector3[];
  private surface: Promise<number> | null = null;
  private overlay: GLModel | null = null;
  /** What the interactions toggle drew: dashed lines and residue labels. */
  private contactShapes: GLShape[] = [];
  private contactLabels: Label[] = [];
  /** The drug's close polar contacts with the protein, closest first. */
  readonly contacts: Contact[];
  private spinFrame = 0;
  private disposed = false;
  /** The drug's docked atoms, to move it from and back to; its style, to redraw it as it moves. */
  private readonly ligandAtoms: AtomSpec[];
  private readonly ligandHome: Vector3[];
  private readonly ligandStyle: Parameters<GLModel["setStyle"]>[1];
  /** Which way the drug comes in from, away from the protein, as a unit vector. */
  private readonly approachDirection: Vector3;
  private dockRequest = 0;
  private dockTimer = 0;
  /** True while the drug is anywhere but its docked pose. */
  private ligandMoved = false;
  private wantInteractions = false;

  /**
   * Draws `files` into a new layer inside `host`, or returns null when 3Dmol can't start.
   * `covered` says how many pixels at the top of the view its controls cover.
   */
  static create(
    host: HTMLElement,
    layerClass: string,
    files: PoseFiles,
    covered: () => number,
  ): PoseScene | null {
    const holder = document.createElement("div");
    holder.className = layerClass;
    host.prepend(holder);
    let viewer: GLViewer | null;
    try {
      viewer = createViewer(holder, { backgroundColor: "white", antialias: true });
    } catch {
      viewer = null;
    }
    if (viewer === null) {
      holder.remove();
      return null;
    }
    return new PoseScene(holder, viewer, files, covered);
  }

  private constructor(
    holder: HTMLElement,
    viewer: GLViewer,
    files: PoseFiles,
    covered: () => number,
  ) {
    this.holder = holder;
    this.covered = covered;
    this.viewer = viewer;
    this.crystal = files.crystal;

    const ink = tokenColor("--color-ink");
    const halogen = tokenColor("--color-element-halogen");
    const elements = {
      C: ink,
      N: tokenColor("--color-element-n"),
      O: tokenColor("--color-element-o"),
      S: tokenColor("--color-element-s"),
      F: halogen,
      Cl: halogen,
      Br: halogen,
      I: halogen,
    };

    this.receptor = viewer.addModel(files.receptor, "pdb");
    this.ligand = viewer.addModel(firstMolecule(files.poses), "sdf");
    const drug = this.ligand.selectedAtoms({});
    const pocketAtoms = this.receptor.selectedAtoms({ predicate: near(drug, POCKET_ANGSTROM) });
    this.contacts = polarContacts(drug, pocketAtoms);
    const residue = (atom: AtomSpec) => `${atom.chain ?? ""}:${String(atom.resi)}`;
    const residues = new Set(pocketAtoms.map(residue));
    this.pocket = { model: this.receptor, predicate: (atom) => residues.has(residue(atom)) };

    // A thin trace, not a ribbon: omitting `style` would draw a full cartoon.
    const backbone = {
      cartoon: { style: "trace", color: tokenColor("--color-backbone"), thickness: 0.14 },
    };
    this.receptor.setStyle({}, backbone);
    viewer.setStyle(this.pocket, {
      ...backbone,
      stick: { radius: 0.07, color: tokenColor("--color-edge") },
    });
    this.ligandStyle = {
      stick: { radius: 0.24, colorscheme: { prop: "elem", map: elements } },
      sphere: { scale: 0.2, colorscheme: { prop: "elem", map: elements } },
    };
    this.ligand.setStyle({}, this.ligandStyle);
    this.ligandAtoms = drug;
    this.ligandHome = drug.map(toPoint);
    const proteinMiddle = new Box3()
      .setFromPoints(this.receptor.selectedAtoms({}).map(toPoint))
      .getCenter(new Vector3());
    const drugMiddle = new Box3().setFromPoints(this.ligandHome).getCenter(new Vector3());
    this.approachDirection = drugMiddle.sub(proteinMiddle);
    if (this.approachDirection.lengthSq() < 1e-6) this.approachDirection.set(1, 0, 0);
    this.approachDirection.normalize();
    viewer.setViewStyle({ style: "outline", color: ink, width: 0.02 });

    viewer.setCameraParameters({ fov: FIELD_OF_VIEW });
    // Only for the depth range kept in view and its fog, which it sets from the whole protein.
    viewer.zoomTo({ model: this.ligand });
    // The crystal position is framed too, so its overlay never falls outside the view.
    const parsed = Parsers.sdf?.(firstMolecule(files.crystal), {}) as AtomSpec[][] | undefined;
    const crystal = parsed?.[0] ?? [];
    this.drugPoints = drug.map(toPoint);
    this.surroundings = [...this.receptor.selectedAtoms(this.pocket), ...crystal].map(toPoint);
    this.turn = screenTurn("x", -TILT).multiply(faceOn(drug, this.receptor.selectedAtoms({})));
    this.reset();
  }

  /**
   * Shows or hides the translucent surface over the pocket. 3Dmol computes a surface in the
   * background and hands back a promise of its ID, so hiding waits for it before removing it.
   * Resolves once the change is drawn.
   */
  async setSurface(on: boolean): Promise<void> {
    if (on && this.surface === null) {
      const drug = this.ligand.selectedAtoms({});
      // 3Dmol 2.x returns a promise of the surface ID, typed as any.
      this.surface = Promise.resolve(
        this.viewer.addSurface(
          SurfaceType.VDW,
          { opacity: 0.3, color: tokenColor("--color-node") },
          { model: this.receptor, predicate: near(drug, SURFACE_ANGSTROM) },
          { model: this.receptor },
        ) as Promise<number> | number,
      );
      await this.surface;
    } else if (!on && this.surface !== null) {
      const pending = this.surface;
      this.surface = null;
      const id = await pending;
      if (this.disposed) return;
      this.viewer.removeSurface(id);
    } else {
      await this.surface;
    }
    if (!this.disposed) this.viewer.render();
  }

  /** Draws the crystal ligand over the pose, as fatter translucent sticks in the redock colour. */
  setOverlay(on: boolean): void {
    if (on && this.overlay === null) {
      this.overlay = this.viewer.addModel(firstMolecule(this.crystal), "sdf");
      this.overlay.setStyle(
        {},
        { stick: { radius: 0.62, color: tokenColor("--color-redock"), opacity: 0.45 } },
      );
    } else if (!on && this.overlay !== null) {
      this.viewer.removeModel(this.overlay);
      this.overlay = null;
    }
    this.viewer.render();
  }

  /**
   * Shows or hides the drug's close polar contacts: a dashed line from each drug atom to the
   * protein atom it nears, and a label with the residue and the distance. Each residue is named
   * once, at its closest contact, so a crowded pocket stays readable.
   */
  setInteractions(on: boolean): void {
    this.wantInteractions = on;
    // The lines belong to the docked pose; they stay off while the drug is elsewhere.
    this.drawInteractions(on && !this.ligandMoved);
  }

  private drawInteractions(on: boolean): void {
    if (this.disposed) return;
    if (on && this.contactShapes.length === 0 && this.contacts.length > 0) {
      const ink = tokenColor("--color-ink");
      const point = ([x, y, z]: [number, number, number]) => ({ x, y, z });
      for (const contact of this.contacts) {
        this.contactShapes.push(
          this.viewer.addCylinder({
            start: point(contact.ligandPoint),
            end: point(contact.proteinPoint),
            radius: 0.05,
            color: ink,
            dashed: true,
            dashLength: 0.2,
            gapLength: 0.15,
          }),
        );
      }
      const named = new Set<string>();
      for (const contact of this.contacts) {
        const key = `${contact.chain}:${contact.residue}`;
        if (named.has(key)) continue;
        named.add(key);
        this.contactLabels.push(
          this.viewer.addLabel(`${contact.residue} · ${contact.distance.toFixed(1)} Å`, {
            position: {
              x: contact.proteinPoint[0],
              y: contact.proteinPoint[1],
              z: contact.proteinPoint[2],
            },
            fontSize: 12,
            fontColor: ink,
            backgroundColor: "white",
            backgroundOpacity: 0.85,
            borderThickness: 0,
            inFront: true,
          }),
        );
      }
    } else if (!on) {
      for (const shape of this.contactShapes) this.viewer.removeShape(shape);
      for (const label of this.contactLabels) this.viewer.removeLabel(label);
      this.contactShapes = [];
      this.contactLabels = [];
    }
    this.viewer.render();
  }

  /** Puts the drug at `frame`: its docked pose moved back along the approach and turned. */
  private placeLigand({ approach, tumble }: DockFrame): void {
    const middle = new Box3().setFromPoints(this.ligandHome).getCenter(new Vector3());
    const turn = new Quaternion().slerp(
      new Quaternion().setFromAxisAngle(TUMBLE_AXIS, (TUMBLE_DEGREES * Math.PI) / 180),
      tumble,
    );
    const shift = this.approachDirection.clone().multiplyScalar(START_ANGSTROM * (1 - approach));
    this.ligandAtoms.forEach((atom, index) => {
      const home = this.ligandHome[index];
      if (home === undefined) return;
      const placed = home.clone().sub(middle).applyQuaternion(turn).add(middle).add(shift);
      atom.x = placed.x;
      atom.y = placed.y;
      atom.z = placed.z;
    });
    // 3Dmol redraws a model's geometry only after its style is set again.
    this.ligand.setStyle({}, this.ligandStyle);
    this.viewer.render();
  }

  /** Stops any animation and puts the drug back in its docked pose, with its contacts. */
  restoreLigand(): void {
    this.dockRequest++;
    cancelAnimationFrame(this.dockTimer);
    if (!this.ligandMoved || this.disposed) return;
    this.placeLigand({ approach: 1, tumble: 0 });
    this.ligandMoved = false;
    this.drawInteractions(this.wantInteractions);
  }

  /**
   * Plays the drug coming in to the pocket. For `binds` it settles in its docked pose and the
   * contacts appear; for `does_not_bind` it is turned away and stays out until reset. This
   * illustrates the verdict; it is not a simulated trajectory. `still` skips to the end for
   * readers who prefer no motion. `onDone` is told when it has finished.
   */
  playDock(verdict: BindingVerdict, options: { still?: boolean; onDone?: () => void } = {}): void {
    if (this.disposed) return;
    this.dockRequest++;
    const request = this.dockRequest;
    cancelAnimationFrame(this.dockTimer);
    this.drawInteractions(false);
    this.ligandMoved = true;

    const finish = () => {
      if (verdict === "binds") {
        this.ligandMoved = false;
        this.drawInteractions(this.wantInteractions);
      }
      options.onDone?.();
    };

    // Keep the whole approach in view, not only the pocket.
    const middle = new Box3().setFromPoints(this.ligandHome).getCenter(new Vector3());
    this.reset([middle.clone().addScaledVector(this.approachDirection, START_ANGSTROM)]);

    if (options.still === true) {
      this.placeLigand(dockEndFrame(verdict));
      finish();
      return;
    }
    const duration = DOCK_DURATION_MS[verdict];
    let start: number | null = null;
    const step = (now: number) => {
      if (request !== this.dockRequest || this.disposed) return;
      start ??= now;
      const elapsed = now - start;
      this.placeLigand(dockFrame(verdict, elapsed));
      if (elapsed >= duration) {
        finish();
        return;
      }
      this.dockTimer = requestAnimationFrame(step);
    };
    this.placeLigand(dockFrame(verdict, 0));
    this.dockTimer = requestAnimationFrame(step);
  }

  /**
   * Turns the slow spin on or off. It turns once per animation frame rather than on 3Dmol's own
   * 25 ms timer, so a slow device draws fewer frames instead of falling behind, and it rests
   * while the page is hidden or the view has no size.
   */
  setSpin(on: boolean): void {
    cancelAnimationFrame(this.spinFrame);
    this.spinFrame = 0;
    if (!on || this.disposed) return;
    let last = performance.now();
    const turn = (now: number) => {
      this.spinFrame = requestAnimationFrame(turn);
      const seconds = Math.min(0.1, (now - last) / 1000);
      last = now;
      if (document.hidden || this.holder.clientWidth === 0) return;
      // About the screen's upright axis, like a turntable; 3Dmol's own rotate turns about the
      // structure's axes.
      const view = this.viewer.getView() as number[];
      const [x, y, z, w] = view.slice(4);
      const turned = screenTurn("y", SPIN_DEGREES * seconds).multiply(new Quaternion(x, y, z, w));
      this.viewer.setView([...view.slice(0, 4), turned.x, turned.y, turned.z, turned.w]);
    };
    this.spinFrame = requestAnimationFrame(turn);
  }

  /**
   * Back to the opening view: the drug in the middle, its pocket around it clear of the controls,
   * framed anew for the view's current shape.
   */
  reset(extra: readonly Vector3[] = []): void {
    // A plain reset also brings the drug back to its docked pose; the animation's own call, which
    // passes extra points to keep in view, leaves it where it is.
    if (extra.length === 0) this.restoreLigand();
    const height = Math.max(1, this.holder.clientHeight);
    const aspect = this.holder.clientWidth / height || 1;
    const inset = this.covered() / height;
    const { centre, distance } = frame(
      this.drugPoints,
      [...this.surroundings, ...extra],
      this.turn,
      aspect,
      inset,
    );
    this.viewer.setPerceivedDistance(distance);
    const depth = (this.viewer.getView() as number[])[3];
    const { x, y, z, w } = this.turn;
    this.viewer.setView([-centre.x, -centre.y, -centre.z, depth, x, y, z, w]);
    this.viewer.render();
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.dockRequest++;
    cancelAnimationFrame(this.dockTimer);
    this.setSpin(false);
    const internals = this.viewer as unknown as ViewerInternals;
    internals.divwatcher?.disconnect();
    internals.intwatcher?.disconnect();
    // Detached, the viewer measures 0 × 0 and never tries to restore its lost context.
    this.holder.remove();
    // Free the WebGL context soon rather than whenever the browser gets round to it. 3Dmol 2.5
    // draws every viewer through one shared offscreen context (its canvas only shows the
    // result), and makes a fresh one for the next viewer once this one is lost. Losing it waits
    // for the GPU to finish the frames already queued, seconds on a software GPU, so it waits
    // until the next step has been drawn instead of holding up the navigation's commit.
    requestAnimationFrame(() => {
      setTimeout(() => {
        const gl = this.viewer.getRenderer().getContext() as WebGLRenderingContext | null;
        gl?.getExtension("WEBGL_lose_context")?.loseContext();
        // clear() draws the remaining protein while removing surfaces. Stop GPU work first.
        this.viewer.clear();
      });
    });
  }
}
