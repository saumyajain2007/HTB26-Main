import { BoxGeometry, CylinderGeometry, Group, Mesh, SphereGeometry, Vector3 } from "three";
import type { NetworkGraph, NetworkRole } from "../api/types";
import { placeLabels, type Disc, type LabelRequest } from "./labels";
import { layoutNetwork } from "./networkLayout";
import {
  clamp,
  createPlate,
  dragToRotate,
  easeFactor,
  fitDistance,
  flatMaterial,
  placeCylinder,
  rgb,
  tokenColor,
  type FlatMaterial,
  type Plate,
} from "./plate";

/**
 * What the network shows on a step (docs/engineering/design.md, "Protein network"):
 * - `disease`: disease proteins in vermilion, everything else neutral;
 * - `roles`: disease proteins, drug targets (blue) and proteins that are both (split);
 * - `path`: roles, plus the route from one drug to a disease protein in green.
 */
export type NetworkMode = "disease" | "roles" | "path";

export interface NetworkView {
  mode: NetworkMode;
  /** Proteins drawn at full strength; the rest fade back. Null: all at full strength. */
  highlight: readonly string[] | null;
  /** Proteins drawn larger with bold labels. */
  focus: readonly string[] | null;
  /** Protein IDs of the route, from the drug's closest target to a disease protein. */
  route: readonly string[] | null;
  /** The drug as an extra node joined to its targets, shown in `path` mode. */
  drug: { label: string; targets: readonly string[] } | null;
}

interface Palette<T> {
  ink: T;
  node: T;
  edge: T;
  disease: T;
  drug: T;
  route: T;
}

interface NodeState {
  id: string;
  role: NetworkRole;
  position: Vector3;
  material: FlatMaterial;
  hullMaterial: FlatMaterial;
  mesh: Mesh;
  hull: Mesh;
  colourA: Vector3;
  colourB: Vector3;
  mix: number;
  grow: number;
  label: HTMLSpanElement;
  labelWidths: Map<string, number>;
  spot: number | null;
  screen: Disc;
}

interface EdgeState {
  a: string;
  b: string;
  mesh: Mesh;
  material: FlatMaterial;
  colour: Vector3;
  mix: number;
  width: number;
}

const LABEL_HEIGHT = 16;
const AUTO_TURN = 0.085; // radians per second
const isDiseaseRole = (role: NetworkRole) => role === "disease" || role === "both";

/**
 * The persistent 3D protein network: laid out once, then re-coloured, re-weighted and
 * re-labelled for each step's view. Framework-free; `NetworkFigure` owns its lifetime.
 */
export class NetworkScene {
  private readonly plate: Plate;
  private readonly drag: ReturnType<typeof dragToRotate>;
  private readonly pivot = new Group();
  private readonly rotation = { x: 0.4, y: -1.6 };
  private readonly nodes: NodeState[] = [];
  private readonly byId = new Map<string, NodeState>();
  private readonly edges: EdgeState[] = [];
  private readonly palette: Palette<string>;
  private readonly colours: Palette<Vector3>;
  private readonly sphere = new SphereGeometry(1, 36, 24);
  private readonly cylinder = new CylinderGeometry(1, 1, 1, 10, 1, true);
  private readonly drug: {
    mesh: Mesh;
    hull: Mesh;
    label: HTMLSpanElement;
    show: number;
    position: Vector3;
    links: { target: string; mesh: Mesh; material: FlatMaterial }[];
    labelWidth: number;
    spot: number | null;
  };
  private view: NetworkView = {
    mode: "disease",
    highlight: null,
    focus: null,
    route: null,
    drug: null,
  };
  private highlight: Set<string> | null = null;
  private focus = new Set<string>();
  private routePairs = new Set<string>();
  private lastSize = { width: 0, height: 0 };
  private readonly world = new Vector3();

  /** Draws `graph` on a new canvas in `host`; labels go into `labelLayer`. */
  static create(
    host: HTMLElement,
    canvasClass: string,
    labelLayer: HTMLElement,
    graph: NetworkGraph,
  ): NetworkScene | null {
    const plate = createPlate(host, canvasClass);
    return plate === null ? null : new NetworkScene(plate, labelLayer, graph);
  }

  private constructor(plate: Plate, labelLayer: HTMLElement, graph: NetworkGraph) {
    this.plate = plate;
    this.palette = {
      ink: tokenColor("--color-ink"),
      node: tokenColor("--color-node"),
      edge: tokenColor("--color-edge"),
      disease: tokenColor("--color-disease"),
      drug: tokenColor("--color-drug"),
      route: tokenColor("--color-route"),
    };
    this.colours = {
      ink: rgb(this.palette.ink),
      node: rgb(this.palette.node),
      edge: rgb(this.palette.edge),
      disease: rgb(this.palette.disease),
      drug: rgb(this.palette.drug),
      route: rgb(this.palette.route),
    };
    this.drag = dragToRotate(plate.canvas, this.rotation, plate);
    plate.scene.add(this.pivot);

    const layout = layoutNetwork(graph);
    for (const node of graph.nodes) {
      const position = layout.get(node.id) ?? new Vector3();
      const material = flatMaterial(this.palette.node);
      const hullMaterial = flatMaterial(this.palette.ink, { outline: true, shade: 1 });
      const mesh = new Mesh(this.sphere, material);
      const hull = new Mesh(this.sphere, hullMaterial);
      mesh.position.copy(position);
      hull.position.copy(position);
      this.pivot.add(mesh, hull);
      const label = document.createElement("span");
      label.textContent = node.symbol;
      labelLayer.append(label);
      const state: NodeState = {
        id: node.id,
        role: node.role,
        position,
        material,
        hullMaterial,
        mesh,
        hull,
        colourA: rgb(this.palette.node),
        colourB: rgb(this.palette.node),
        mix: 1,
        grow: 1,
        label,
        labelWidths: new Map(),
        spot: null,
        screen: { x: 0, y: 0, r: 0 },
      };
      this.nodes.push(state);
      this.byId.set(node.id, state);
    }
    for (const edge of graph.edges) {
      const a = this.byId.get(edge.source);
      const b = this.byId.get(edge.target);
      if (!a || !b) continue;
      const material = flatMaterial(this.palette.edge, { shade: 1 });
      const mesh = new Mesh(this.cylinder, material);
      placeCylinder(mesh, a.position, b.position);
      this.pivot.add(mesh);
      this.edges.push({
        a: a.id,
        b: b.id,
        mesh,
        material,
        colour: rgb(this.palette.edge),
        mix: 1,
        width: 1.15,
      });
    }

    const box = new BoxGeometry(1.6, 1.6, 1.6);
    const drugMesh = new Mesh(box, flatMaterial("#ffffff"));
    const drugHull = new Mesh(box, flatMaterial(this.palette.ink, { outline: true, shade: 1 }));
    drugMesh.scale.setScalar(1e-6);
    drugHull.scale.setScalar(1e-6);
    this.pivot.add(drugMesh, drugHull);
    const drugLabel = document.createElement("span");
    drugLabel.dataset.state = "focus";
    labelLayer.append(drugLabel);
    this.drug = {
      mesh: drugMesh,
      hull: drugHull,
      label: drugLabel,
      show: 0,
      position: new Vector3(1, 0, 0),
      links: [],
      labelWidth: 0,
      spot: null,
    };

    plate.onFrame((seconds) => {
      this.frame(seconds);
    });
  }

  setView(view: NetworkView): void {
    this.view = view;
    this.highlight = view.highlight === null ? null : new Set(view.highlight);
    this.focus = new Set(view.focus ?? []);
    const route = view.mode === "path" ? (view.route ?? []) : [];
    this.routePairs = new Set(
      route.slice(1).flatMap((id, i) => {
        const previous = route[i] ?? "";
        return [`${previous}|${id}`, `${id}|${previous}`];
      }),
    );
    this.setDrug(view.mode === "path" ? view.drug : null);
  }

  /** Draws the current view now; see `Plate.draw`. */
  draw(): void {
    this.plate.draw();
  }

  dispose(): void {
    this.drag.dispose();
    this.plate.dispose();
    for (const node of this.nodes) node.label.remove();
    this.drug.label.remove();
  }

  private setDrug(drug: NetworkView["drug"]): void {
    for (const link of this.drug.links) {
      this.pivot.remove(link.mesh);
      link.material.dispose();
    }
    this.drug.links = [];
    if (drug === null) return;
    const targets = drug.targets.flatMap((id) => {
      const node = this.byId.get(id);
      return node ? [node] : [];
    });
    const centre = new Vector3();
    for (const node of targets) centre.add(node.position);
    if (centre.lengthSq() < 1e-4) centre.set(1, 0, 0);
    this.drug.position.copy(centre.normalize().multiplyScalar(1.12));
    this.drug.mesh.position.copy(this.drug.position);
    this.drug.hull.position.copy(this.drug.position);
    this.drug.label.textContent = drug.label;
    this.drug.labelWidth = 0;
    this.drug.links = targets.map((node) => {
      const material = flatMaterial(this.palette.edge, { shade: 1 });
      const mesh = new Mesh(this.cylinder, material);
      placeCylinder(mesh, this.drug.position, node.position);
      mesh.scale.x = 1e-6;
      mesh.scale.z = 1e-6;
      this.pivot.add(mesh);
      return { target: node.id, mesh, material };
    });
  }

  private nodeColours(node: NodeState): [Vector3, Vector3] {
    const { disease, drug, node: neutral } = this.colours;
    if (this.view.mode === "disease") {
      return isDiseaseRole(node.role) ? [disease, disease] : [neutral, neutral];
    }
    switch (node.role) {
      case "disease":
        return [disease, disease];
      case "drug":
        return [drug, drug];
      case "both":
        return [disease, drug];
      case "link":
        return [neutral, neutral];
    }
  }

  private frame(seconds: number): void {
    const { plate, rotation } = this;
    const size = plate.size();
    if (size.width !== this.lastSize.width || size.height !== this.lastSize.height) {
      this.lastSize = size;
      plate.camera.position.set(0, 0, fitDistance(1.2, size.width / size.height));
    }
    this.drag.coast();
    if (!plate.reducedMotion() && !this.drag.dragging()) rotation.y += seconds * AUTO_TURN;
    this.pivot.rotation.set(rotation.x, rotation.y, 0);
    this.pivot.updateMatrixWorld();

    const k = easeFactor(seconds, plate);
    const unit = plate.pixelsPerUnit();
    const world = this.world;
    const discs: Disc[] = [];

    for (const node of this.nodes) {
      const [a, b] = this.nodeColours(node);
      node.colourA.lerp(a, k);
      node.colourB.lerp(b, k);
      node.material.uniforms.uA.value.copy(node.colourA);
      node.material.uniforms.uB.value.copy(node.colourB);
      node.material.uniforms.uSplit.value =
        this.view.mode !== "disease" && node.role === "both" ? 1 : 0;
      const on = this.highlight === null || this.highlight.has(node.id);
      node.mix += ((on ? 1 : 0.2) - node.mix) * k;
      node.grow += ((this.focus.has(node.id) ? 1.45 : 1) - node.grow) * k;
      world.copy(node.position).applyMatrix4(this.pivot.matrixWorld);
      const depth = clamp((1 - world.z) / 2, 0, 1); // 0 nearest, 1 farthest
      const mix = node.mix * (1 - 0.32 * depth);
      node.material.uniforms.uMix.value = mix;
      node.hullMaterial.uniforms.uMix.value = mix;
      const front = node.mix > 0.6;
      node.material.depthWrite = front;
      node.hullMaterial.depthWrite = front;
      node.mesh.renderOrder = front ? 2 : 1;
      node.hull.renderOrder = front ? 2 : 1;
      const base =
        node.role === "link" ? clamp(0.03 * unit, 3.6, 6.5) : clamp(0.05 * unit, 5.6, 10);
      const radius = base * node.grow * (1.08 - 0.16 * depth);
      node.mesh.scale.setScalar(radius / unit);
      node.hull.scale.setScalar((radius + 1.1) / unit);
      const screen = plate.project(world);
      node.screen = { x: screen.x, y: screen.y, r: radius + 1.1 };
      discs.push({ x: screen.x, y: screen.y, r: radius + 2.5 });
    }

    for (const edge of this.edges) {
      const onRoute = this.routePairs.has(`${edge.a}|${edge.b}`);
      edge.colour.lerp(onRoute ? this.colours.route : this.colours.edge, k);
      const on =
        onRoute ||
        this.highlight === null ||
        (this.highlight.has(edge.a) && this.highlight.has(edge.b));
      edge.mix += ((on ? 1 : 0.25) - edge.mix) * k;
      edge.width += ((onRoute ? 3 : 1.15) - edge.width) * k;
      edge.material.uniforms.uA.value.copy(edge.colour);
      edge.material.uniforms.uMix.value = edge.mix;
      const radius = edge.width / 2 / unit;
      edge.mesh.scale.x = radius;
      edge.mesh.scale.z = radius;
    }

    const drug = this.drug;
    const showDrug = this.view.mode === "path" && this.view.drug !== null;
    drug.show += ((showDrug ? 1 : 0) - drug.show) * k;
    const drugPixels = 10 * drug.show;
    drug.mesh.scale.setScalar(drugPixels / unit / 1.6 + 1e-6);
    drug.hull.scale.setScalar(drug.show > 0.01 ? (drugPixels + 1.2) / unit / 1.6 : 1e-6);
    const firstStop = this.view.route?.[0];
    for (const link of drug.links) {
      const onRoute = link.target === firstStop;
      link.material.uniforms.uA.value.copy(onRoute ? this.colours.route : this.colours.edge);
      const radius = ((onRoute ? 3 : 1.15) / 2 / unit) * drug.show;
      link.mesh.scale.x = radius + 1e-6;
      link.mesh.scale.z = radius + 1e-6;
    }
    world.copy(drug.position).applyMatrix4(this.pivot.matrixWorld);
    const drugScreen = plate.project(world);
    if (drug.show > 0.3)
      discs.push({ x: drugScreen.x, y: drugScreen.y, r: drugPixels * 0.75 + 2.5 });

    this.placeAllLabels(discs, drugScreen, drugPixels * 0.75 + 1.2);
  }

  private labelState(node: NodeState): "focus" | "plain" | "muted" | null {
    const { mode } = this.view;
    if (this.focus.has(node.id)) return "focus";
    if (node.role === "link") return null;
    const on = this.highlight === null || this.highlight.has(node.id);
    if (!on) return null;
    if (mode === "disease") return isDiseaseRole(node.role) ? "plain" : "muted";
    return "plain";
  }

  private placeAllLabels(discs: Disc[], drugScreen: { x: number; y: number }, drugRadius: number) {
    const requests: LabelRequest[] = [];
    for (const node of this.nodes) {
      const state = this.labelState(node);
      if (state === null) continue;
      node.label.dataset.state = state;
      let width = node.labelWidths.get(state);
      if (width === undefined || width === 0) {
        width = node.label.offsetWidth;
        node.labelWidths.set(state, width);
      }
      requests.push({
        id: node.id,
        anchor: node.screen,
        width: width || 40,
        height: LABEL_HEIGHT,
        priority: state === "focus" ? 3 : state === "plain" ? 2 : 1,
        required: state === "focus",
        previous: node.spot,
      });
    }
    const drug = this.drug;
    if (drug.show > 0.3) {
      if (drug.labelWidth === 0) drug.labelWidth = drug.label.offsetWidth;
      requests.push({
        id: "",
        anchor: { x: drugScreen.x, y: drugScreen.y, r: drugRadius },
        width: drug.labelWidth || 80,
        height: LABEL_HEIGHT,
        priority: 4,
        required: true,
        previous: drug.spot,
      });
    }
    const placements = placeLabels(requests, discs, this.plate.size());
    for (const node of this.nodes) {
      const placement = placements.get(node.id) ?? null;
      show(node.label, placement);
      if (placement) node.spot = placement.spot;
    }
    const drugPlacement = placements.get("") ?? null;
    show(drug.label, drugPlacement);
    if (drugPlacement) drug.spot = drugPlacement.spot;
  }
}

function show(label: HTMLElement, placement: { x: number; y: number } | null): void {
  if (placement === null) {
    label.style.opacity = "0";
    return;
  }
  label.style.opacity = "1";
  label.style.transform = `translate(${placement.x.toFixed(1)}px, ${placement.y.toFixed(1)}px)`;
}
