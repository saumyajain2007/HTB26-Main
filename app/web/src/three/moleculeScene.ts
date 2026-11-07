import {
  CylinderGeometry,
  Group,
  Mesh,
  type PerspectiveCamera,
  SphereGeometry,
  Vector3,
} from "three";
import type { Conformer } from "../api/types";
import {
  clamp,
  createPlate,
  dragToRotate,
  fitDistance,
  flatMaterial,
  placeCylinder,
  tokenColor,
  type FlatMaterial,
  type Plate,
} from "./plate";

const AUTO_TURN = 0.2; // radians per second
const DOUBLE_BOND_OFFSET = 0.026; // of the molecule's radius

interface Atom {
  position: Vector3;
  hetero: boolean;
  mesh: Mesh;
  hull: Mesh;
  label: HTMLSpanElement | null;
}

/** What a molecule needs from the surface it is drawn on: a whole plate, or one slot of a strip. */
export interface MoleculeView {
  readonly camera: PerspectiveCamera;
  /** Drawing size in CSS pixels; 0 while hidden. */
  size(): { width: number; height: number };
  reducedMotion(): boolean;
  pixelsPerUnit(): number;
  /** Projects a world point to pixels in the view, for the element letters. */
  project(point: Vector3): { x: number; y: number };
}

interface Drag {
  coast(): void;
  dragging(): boolean;
}

/**
 * A small molecule as a turning skeletal formula: carbons are small white atoms with ink
 * outlines, other elements larger and lettered, bonds are ink rods (double and triple bonds drawn
 * as parallel rods). Hydrogens are left out, as in a skeletal formula. It draws into any view, so
 * one canvas can hold one molecule (MoleculeScene) or several side by side (MoleculeStrip).
 */
export class Molecule {
  readonly group = new Group();
  readonly rotation = { x: 0.35, y: 0.5 };
  private readonly atoms: Atom[] = [];
  private readonly bonds: { mesh: Mesh; thin: boolean }[] = [];
  private readonly geometries: { dispose(): void }[];
  private readonly materials: FlatMaterial[];
  private lastSize = { width: 0, height: 0 };
  private readonly world = new Vector3();

  /** Builds `conformer`; its element letters go into `labelLayer`. */
  constructor(conformer: Conformer, labelLayer: HTMLElement) {
    const ink = tokenColor("--color-ink");
    const sphere = new SphereGeometry(1, 28, 18);
    const cylinder = new CylinderGeometry(1, 1, 1, 10, 1, true);
    const atomMaterial = flatMaterial("#ffffff", { shade: 0.87 });
    const hullMaterial = flatMaterial(ink, { outline: true, shade: 1 });
    const bondMaterial = flatMaterial(ink, { shade: 1 });
    this.geometries = [sphere, cylinder];
    this.materials = [atomMaterial, hullMaterial, bondMaterial];

    // Heavy atoms only, centred and scaled into the unit sphere.
    const kept = new Map<number, number>();
    const heavy = conformer.atoms.flatMap((atom, index) => {
      if (atom.element === "H") return [];
      kept.set(index, kept.size);
      return [{ element: atom.element, position: new Vector3(atom.x, atom.y, atom.z) }];
    });
    const centre = new Vector3();
    for (const atom of heavy) centre.add(atom.position);
    centre.divideScalar(Math.max(1, heavy.length));
    const radius = Math.max(1e-6, ...heavy.map((atom) => atom.position.distanceTo(centre)));
    for (const atom of heavy) atom.position.sub(centre).divideScalar(radius);

    for (const atom of heavy) {
      const mesh = new Mesh(sphere, atomMaterial);
      const hull = new Mesh(sphere, hullMaterial);
      mesh.position.copy(atom.position);
      hull.position.copy(atom.position);
      this.group.add(mesh, hull);
      const hetero = atom.element !== "C";
      let label: HTMLSpanElement | null = null;
      if (hetero) {
        label = document.createElement("span");
        label.textContent = atom.element;
        labelLayer.append(label);
      }
      this.atoms.push({ position: atom.position, hetero, mesh, hull, label });
    }

    const neighbours = heavy.map((): number[] => []);
    const bonds = conformer.bonds.flatMap((bond) => {
      const a = kept.get(bond.a);
      const b = kept.get(bond.b);
      if (a === undefined || b === undefined) return [];
      neighbours[a]?.push(b);
      neighbours[b]?.push(a);
      return [{ a, b, order: bond.order }];
    });
    for (const { a, b, order } of bonds) {
      const start = this.atoms[a]?.position;
      const end = this.atoms[b]?.position;
      if (!start || !end) continue;
      if (order === 1) {
        const mesh = new Mesh(cylinder, bondMaterial);
        placeCylinder(mesh, start, end);
        this.group.add(mesh);
        this.bonds.push({ mesh, thin: false });
        continue;
      }
      // Parallel rods in the plane of a neighbouring atom, so rings keep their double bonds flat.
      const axis = new Vector3().subVectors(end, start);
      const other =
        neighbours[a]?.find((n) => n !== b) ?? neighbours[b]?.find((n) => n !== a) ?? null;
      const side =
        other === null
          ? new Vector3(0, 0, 1)
          : new Vector3().subVectors(this.atoms[other]?.position ?? start, start);
      let normal = new Vector3().crossVectors(axis, side);
      if (normal.lengthSq() < 1e-6) normal = new Vector3().crossVectors(axis, new Vector3(0, 1, 0));
      const offset = new Vector3()
        .crossVectors(normal, axis)
        .normalize()
        .multiplyScalar(DOUBLE_BOND_OFFSET * (order === 3 ? 1.6 : 1));
      const shifts = order === 3 ? [-1, 0, 1] : [-1, 1];
      for (const shift of shifts) {
        const mesh = new Mesh(cylinder, bondMaterial);
        placeCylinder(
          mesh,
          start.clone().addScaledVector(offset, shift),
          end.clone().addScaledVector(offset, shift),
        );
        this.group.add(mesh);
        this.bonds.push({ mesh, thin: true });
      }
    }
  }

  /** Removes the element letters and frees the GPU resources. */
  dispose(): void {
    for (const atom of this.atoms) atom.label?.remove();
    for (const geometry of this.geometries) geometry.dispose();
    for (const material of this.materials) material.dispose();
  }

  /** One frame: turn, fit the camera to the view, and keep atoms and bonds a steady pixel size. */
  frame(seconds: number, view: MoleculeView, drag: Drag): void {
    const { rotation } = this;
    const size = view.size();
    if (size.width !== this.lastSize.width || size.height !== this.lastSize.height) {
      this.lastSize = size;
      view.camera.position.set(0, 0, fitDistance(1.12, size.width / size.height));
    }
    drag.coast();
    if (!view.reducedMotion() && !drag.dragging()) rotation.y += seconds * AUTO_TURN;
    this.group.rotation.set(rotation.x, rotation.y, 0);
    this.group.updateMatrixWorld();

    const unit = view.pixelsPerUnit();
    const showLetters = clamp(0.072 * unit, 3.6, 8.5) >= 5.6;
    for (const atom of this.atoms) {
      const pixels = atom.hetero ? clamp(0.072 * unit, 3.6, 8.5) : clamp(0.036 * unit, 2.2, 4.4);
      atom.mesh.scale.setScalar(pixels / unit);
      atom.hull.scale.setScalar((pixels + 1.05) / unit);
      if (!atom.label) continue;
      if (!showLetters) {
        atom.label.style.opacity = "0";
        continue;
      }
      this.world.copy(atom.position).applyMatrix4(this.group.matrixWorld);
      const { x, y } = view.project(this.world);
      const depth = clamp((this.world.z + 1) / 2, 0, 1); // 1 nearest
      atom.label.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px) translate(-50%, -50%)`;
      atom.label.style.opacity = (0.3 + 0.7 * depth).toFixed(2);
    }
    for (const bond of this.bonds) {
      const pixels = bond.thin ? clamp(0.008 * unit, 0.55, 1) : clamp(0.012 * unit, 0.75, 1.5);
      bond.mesh.scale.x = pixels / unit;
      bond.mesh.scale.z = pixels / unit;
    }
  }
}

/** One molecule on its own canvas. Drag to rotate. */
export class MoleculeScene {
  private readonly plate: Plate;
  private readonly molecule: Molecule;
  private readonly drag: ReturnType<typeof dragToRotate>;

  /** Draws `conformer` on a new canvas in `host`; element letters go into `labelLayer`. */
  static create(
    host: HTMLElement,
    canvasClass: string,
    labelLayer: HTMLElement,
    conformer: Conformer,
  ): MoleculeScene | null {
    const plate = createPlate(host, canvasClass);
    return plate === null ? null : new MoleculeScene(plate, labelLayer, conformer);
  }

  private constructor(plate: Plate, labelLayer: HTMLElement, conformer: Conformer) {
    this.plate = plate;
    this.molecule = new Molecule(conformer, labelLayer);
    this.drag = dragToRotate(plate.canvas, this.molecule.rotation, plate);
    plate.scene.add(this.molecule.group);
    plate.onFrame((seconds) => {
      this.molecule.frame(seconds, plate, this.drag);
    });
  }

  dispose(): void {
    this.drag.dispose();
    this.plate.dispose();
    this.molecule.dispose();
  }
}
