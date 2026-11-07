"""Separate functional STRING graph artifacts for diffusion, without distances."""

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import tempfile
from time import perf_counter

import numpy as np
from scipy.sparse import csr_matrix, load_npz, save_npz
from scipy.sparse.csgraph import connected_components

from .artifacts import file_record, write_json
from .network import GENE_ID, STRING_ID, load_mapping


@dataclass
class RWRGraph:
    graph: csr_matrix
    gene_ids: tuple[str, ...]
    scoring_indices: np.ndarray
    manifest: dict
    manifest_record: dict

    @property
    def kind(self):
        return self.manifest["network_kind"]


def load_rwr_graph(directory: Path | str) -> RWRGraph:
    """Read either original Stage 1 artifacts or a separate functional bundle."""
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    for name, record in manifest["files"].items():
        if file_record(directory / name) != record:
            raise ValueError(f"Graph artifact checksum mismatch: {name}")
    if manifest.get("network_kind") not in {"human_physical_gene_undirected_unweighted", "human_functional_association_gene_undirected_unweighted"}:
        raise ValueError("Unsupported or missing graph classification")
    index = json.loads((directory / "index.json").read_text(encoding="utf-8"))
    genes = tuple(index["graph_gene_ids"])
    if genes != tuple(sorted(set(genes))) or any(not GENE_ID.fullmatch(g) for g in genes):
        raise ValueError("Graph IDs must be unique sorted Ensembl IDs")
    graph = load_npz(directory / "graph.npz").tocsr()
    if (not genes or graph.shape != (len(genes), len(genes)) or (graph != graph.T).nnz
            or np.any(graph.diagonal()) or np.any(graph.data != 1)):
        raise ValueError("Graph must be undirected, unweighted and loop-free")
    graph.sort_indices()
    _, labels = connected_components(graph, directed=False)
    if not np.array_equal(labels, np.asarray(index["component_labels"])):
        raise ValueError("Component labels do not match the saved graph")
    largest = np.flatnonzero(labels == int(np.argmax(np.bincount(labels))))
    scoring = index.get("scoring_gene_ids", index.get("distance_gene_ids"))
    if scoring != [genes[i] for i in largest]:
        raise ValueError("Scoring identifiers do not match the largest component")
    return RWRGraph(graph, genes, largest, manifest, file_record(directory / "manifest.json"))


def build_functional_graph(mapping_path: Path | str, links_path: Path | str, output: Path | str, *, min_combined_score=700) -> dict:
    """Require the functional file; never reinterpret a physical-network file."""
    started = perf_counter()
    mapping_path, links_path, output = Path(mapping_path), Path(links_path), Path(output)
    if not links_path.is_file():
        raise FileNotFoundError(f"Required human functional STRING input is missing: {links_path}")
    if links_path.name != "9606.protein.links.v12.5.txt.gz":
        raise ValueError("Expected the inspected human functional file 9606.protein.links.v12.5.txt.gz; no substitution")
    if isinstance(min_combined_score, bool) or not isinstance(min_combined_score, int) or not 0 <= min_combined_score <= 1000:
        raise ValueError("Combined-score threshold must be an integer in 0..1000")
    if output.exists():
        raise FileExistsError(output)
    inputs = {"mapping": {"name": mapping_path.name, **file_record(mapping_path)},
              "functional_links": {"name": links_path.name, **file_record(links_path)}}
    mapping = load_mapping(mapping_path)
    if "string-12.5" not in mapping.releases:
        raise ValueError("Functional graph requires the STRING 12.5 mapping")
    counts, edges, proteins = Counter(), set(), set()
    with gzip.open(links_path, "rt", encoding="utf-8") as handle:
        columns = handle.readline().split()
        if columns != ["protein1", "protein2", "combined_score"]:
            raise ValueError(f"Unexpected functional STRING columns: {columns}")
        for number, line in enumerate(handle, 2):
            fields = line.split()
            if not fields:
                continue
            if len(fields) != 3 or not all(STRING_ID.fullmatch(v) for v in fields[:2]):
                raise ValueError(f"Invalid human STRING row {number}")
            try:
                score = int(fields[2])
            except ValueError as exc:
                raise ValueError(f"Non-integer combined score at row {number}") from exc
            if not 0 <= score <= 1000:
                raise ValueError(f"Invalid combined score at row {number}")
            counts["input_rows"] += 1
            proteins.update(fields[:2])
            if score < min_combined_score:
                counts["filtered_by_score_rows"] += 1
                continue
            counts["score_passing_rows"] += 1
            a, b = (mapping.protein_to_gene.get(p) for p in fields[:2])
            if a is None or b is None:
                counts["excluded_mapping_rows"] += 1
                continue
            if a == b:
                counts["self_loop_rows"] += 1
                continue
            edge = tuple(sorted((a, b)))
            counts["duplicate_edge_rows"] += int(edge in edges)
            edges.add(edge)
    genes = tuple(sorted(set(mapping.protein_to_gene.values())))
    indexes = {g: i for i, g in enumerate(genes)}
    pairs = np.asarray([(indexes[a], indexes[b]) for a, b in sorted(edges)], dtype=np.int32).reshape(-1, 2)
    if not len(pairs):
        raise ValueError("No functional edges survive mapping/filtering")
    rows, cols = np.concatenate((pairs[:, 0], pairs[:, 1])), np.concatenate((pairs[:, 1], pairs[:, 0]))
    graph = csr_matrix((np.ones(len(rows), dtype=np.uint8), (rows, cols)), shape=(len(genes), len(genes)))
    graph.sort_indices()
    n_components, labels = connected_components(graph, directed=False)
    sizes = np.bincount(labels)
    largest = np.flatnonzero(labels == int(np.argmax(sizes)))
    report = {**dict(sorted(counts.items())), "nodes": len(genes), "edges": len(edges), "components": int(n_components),
              "nodes_with_edges": int(np.count_nonzero(np.diff(graph.indptr))),
              "isolated_nodes": int(np.count_nonzero(np.diff(graph.indptr) == 0)),
              "largest_component_nodes": len(largest), "largest_component_edges": graph[largest][:, largest].nnz // 2,
              "component_sizes_descending": sorted(sizes.tolist(), reverse=True),
              "string_proteins_seen": len(proteins), "string_proteins_mapped": len(proteins & mapping.protein_to_gene.keys())}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".functional-", dir=output.parent) as temporary:
        staged = Path(temporary) / "bundle"
        staged.mkdir()
        save_npz(staged / "graph.npz", graph)
        write_json(staged / "index.json", {"graph_gene_ids": genes, "scoring_gene_ids": [genes[i] for i in largest], "component_labels": labels.tolist()})
        write_json(staged / "mapping_exclusions.json", mapping.excluded)
        source_path = links_path.with_suffix(".source.json")
        source = json.loads(source_path.read_text(encoding="utf-8")) if source_path.exists() else {"url": None, "note": "Original download metadata not supplied"}
        if "sha256" in source and {k: source[k] for k in ("bytes", "sha256")} != file_record(links_path):
            raise ValueError("Functional source download hash mismatch")
        manifest = {"format_version": 1, "artifact_type": "sparse_rwr_graph", "network_kind": "human_functional_association_gene_undirected_unweighted",
                    "releases": mapping.releases, "created_utc": datetime.now(timezone.utc).isoformat(), "inputs": inputs,
                    "source_metadata": source, "string_columns": columns, "mapping": mapping.report, "graph": report,
                    "filters": {"combined_score_min": min_combined_score, "experiments_min": None, "experimental_channel_required": False},
                    "scoring_scope": "largest_connected_component", "distance_precomputation": "not_required_for_rwr",
                    "files": {name: file_record(staged / name) for name in ("graph.npz", "index.json", "mapping_exclusions.json")},
                    "build_seconds": perf_counter() - started}
        for key, path in (("mapping", mapping_path), ("functional_links", links_path)):
            if file_record(path) != {k: inputs[key][k] for k in ("bytes", "sha256")}:
                raise ValueError("Functional graph source changed during build")
        write_json(staged / "manifest.json", manifest)
        staged.rename(output)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--links", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = build_functional_graph(args.mapping, args.links, args.output)
        summary = {k: manifest["graph"][k] for k in ("nodes", "edges", "components", "largest_component_nodes", "largest_component_edges")}
        print(json.dumps({"output": str(args.output), "graph": summary, "build_seconds": manifest["build_seconds"]}, indent=2))
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Error: {exc}\n")
