"""Build and reload a checksummed, disease-independent network artifact bundle."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import tempfile
from time import perf_counter
from typing import Callable

import numpy as np
import scipy
from scipy.sparse import csr_matrix, load_npz, save_npz

from . import __version__
from .network import GENE_ID, build_network, load_mapping, precompute_distances


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def file_record(path: Path) -> dict:
    return {"bytes": path.stat().st_size, "sha256": sha256(path)}


def build_artifacts(
    mapping_path: Path | str,
    links_path: Path | str,
    output: Path | str,
    *,
    min_combined_score: int = 700,
    min_experiments: int = 400,
    chunk_size: int = 128,
    dtype: str = "uint8",
    progress: Callable[[int, int], None] | None = None,
) -> dict:
    started = perf_counter()
    mapping_path, links_path, output = Path(mapping_path).resolve(), Path(links_path).resolve(), Path(output).resolve()
    for path in (mapping_path, links_path):
        if not path.is_file():
            raise FileNotFoundError(f"Required Stage 1 input is missing: {path}")
    if output.exists():
        raise FileExistsError(f"Output already exists; choose a new directory: {output}")
    input_records = {name: {"path": str(path), **file_record(path)} for name, path in (
        ("mapping", mapping_path), ("physical_links", links_path),
    )}
    mapping = load_mapping(mapping_path)
    if "string-12.5" not in mapping.releases:
        raise ValueError("Stage 1 requires a mapping release declaring 'string-12.5'")
    network = build_network(links_path, mapping, min_combined_score=min_combined_score, min_experiments=min_experiments)
    if network.report["edges"] == 0:
        raise ValueError("No mapped gene edges survive the filters; no distance artifacts were published")
    graph_seconds = perf_counter() - started
    output.parent.mkdir(parents=True, exist_ok=True)
    # Publish the directory only once every artifact is complete. Failed builds
    # cannot be mistaken for a usable cache because no manifest is published.
    with tempfile.TemporaryDirectory(prefix=".stage1-", dir=output.parent) as temporary:
        staged = Path(temporary) / "bundle"
        staged.mkdir()
        save_npz(staged / "graph.npz", network.graph)
        distance_genes = [network.gene_ids[i] for i in network.largest_indices]
        write_json(staged / "index.json", {
            "graph_gene_ids": network.gene_ids,
            "distance_gene_ids": distance_genes,
            "component_labels": network.component_labels.tolist(),
        })
        write_json(staged / "mapping_exclusions.json", mapping.excluded)
        distance_info = precompute_distances(
            network.graph[network.largest_indices][:, network.largest_indices],
            staged / "distances.npy", chunk_size=chunk_size, dtype=dtype, progress=progress,
        )
        files = {name: file_record(staged / name) for name in (
            "graph.npz", "index.json", "mapping_exclusions.json", "distances.npy",
        )}
        manifest = {
            "format_version": 1,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "software": {"ranking": __version__, "python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__},
            "inputs": input_records,
            "releases": mapping.releases,
            "source_metadata": {"urls": None, "licences": None, "note": "Download URLs, extraction dates and licence notices were not supplied with the local input files; input hashes identify the exact files used."},
            "network_kind": "human_physical_gene_undirected_unweighted",
            "string_columns": network.columns,
            "filters": {"combined_score_min": min_combined_score, "experiments_min": min_experiments, "direct_experiments_column": "experiments", "transferred_experiments_used_as_direct": False},
            "mapping": mapping.report,
            "graph": network.report,
            "distance_scope": "largest_connected_component",
            "distances": distance_info,
            "files": files,
            "timing_seconds": {"load_and_graph": graph_seconds, "total": perf_counter() - started},
        }
        # Detect inputs changed during a long precomputation.
        for name, path in (("mapping", mapping_path), ("physical_links", links_path)):
            if file_record(path) != {k: input_records[name][k] for k in ("bytes", "sha256")}:
                raise ValueError(f"Input changed during build: {path}")
        write_json(staged / "manifest.json", manifest)
        if output.exists():
            raise FileExistsError(f"Output appeared during build: {output}")
        staged.rename(output)
    return manifest


@dataclass
class Artifacts:
    graph: csr_matrix
    graph_gene_ids: tuple[str, ...]
    distance_gene_ids: tuple[str, ...]
    component_labels: np.ndarray
    distances: np.memmap
    manifest: dict

    def close(self) -> None:
        self.distances._mmap.close()

    def __enter__(self) -> "Artifacts":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def load_artifacts(directory: Path | str, *, verify: bool = True) -> Artifacts:
    """Reload without source files or recomputing paths; distances stay memory-mapped."""
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format_version") != 1:
        raise ValueError("Unsupported Stage 1 artifact format")
    names = ("graph.npz", "index.json", "mapping_exclusions.json", "distances.npy")
    if verify:
        for name in names:
            if file_record(directory / name) != manifest["files"][name]:
                raise ValueError(f"Artifact checksum/size mismatch: {name}")
    index = json.loads((directory / "index.json").read_text(encoding="utf-8"))
    graph_genes, distance_genes = tuple(index["graph_gene_ids"]), tuple(index["distance_gene_ids"])
    for genes in (graph_genes, distance_genes):
        if not genes or genes != tuple(sorted(set(genes))) or any(not GENE_ID.fullmatch(g) for g in genes):
            raise ValueError("Artifact identifiers must be unique sorted Ensembl gene IDs")
    if not set(distance_genes).issubset(graph_genes):
        raise ValueError("Distance identifiers are absent from graph index")
    graph = load_npz(directory / "graph.npz").tocsr()
    labels = np.array(index["component_labels"], dtype=np.int32)
    if graph.shape != (len(graph_genes), len(graph_genes)) or len(labels) != len(graph_genes):
        raise ValueError("Graph/index shape mismatch")
    if (graph != graph.T).nnz or np.any(graph.diagonal()) or np.any(graph.data != 1):
        raise ValueError("Stored graph must be undirected, unweighted and loop-free")
    distances = np.load(directory / "distances.npy", mmap_mode="r", allow_pickle=False)
    info = manifest["distances"]
    if (distances.shape != (len(distance_genes), len(distance_genes))
            or list(distances.shape) != info["shape"] or str(distances.dtype) != info["dtype"]
            or str(distances.dtype) not in ("uint8", "uint16")
            or info["unreachable_sentinel"] != int(np.iinfo(distances.dtype).max)):
        distances._mmap.close()
        raise ValueError("Distance matrix/index/encoding mismatch")
    return Artifacts(graph, graph_genes, distance_genes, labels, distances, manifest)
