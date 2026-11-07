"""Read release mappings and STRING physical links, then compute graph distances."""

from collections import Counter, defaultdict
from dataclasses import dataclass
import gzip
import json
from pathlib import Path
import re
from time import perf_counter
from typing import Callable

import numpy as np
from numpy.typing import NDArray
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components, shortest_path


GENE_ID = re.compile(r"ENSG[0-9]{11}\Z")
STRING_ID = re.compile(r"9606\.ENSP[0-9]{11}\Z")


@dataclass
class MappingData:
    protein_to_gene: dict[str, str]
    excluded: dict[str, str]
    releases: list[str]
    report: dict


@dataclass
class NetworkData:
    graph: csr_matrix
    gene_ids: tuple[str, ...]
    component_labels: NDArray[np.int32]
    largest_indices: NDArray[np.int64]
    report: dict
    columns: list[str]


def load_mapping(path: Path | str) -> MappingData:
    """Jessica's release: {releases, coverage, mappings: [{string_id, target_id, status, reason}]}.

    Identical rows are harmless. Conflicting genes or statuses quarantine the
    entire STRING ID; multiple STRING proteins mapping to one gene are valid.
    """
    with Path(path).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or not isinstance(payload.get("mappings"), list):
        raise ValueError("Mapping release must contain a 'mappings' array")
    releases = payload.get("releases")
    if not isinstance(releases, list) or not releases or not all(isinstance(r, str) for r in releases):
        raise ValueError("Mapping release must contain nonempty 'releases' strings")
    grouped: dict[str, list[dict]] = defaultdict(list)
    invalid_source_rows = 0
    for number, row in enumerate(payload["mappings"], 1):
        if not isinstance(row, dict):
            raise ValueError(f"Mapping row {number} must be an object")
        protein = row.get("string_id")
        if not isinstance(protein, str) or not STRING_ID.fullmatch(protein):
            invalid_source_rows += 1
            continue
        grouped[protein].append(row)

    accepted: dict[str, str] = {}
    excluded: dict[str, str] = {}
    for protein, rows in sorted(grouped.items()):
        statuses = {row.get("status") if isinstance(row.get("status"), str) else "invalid_status" for row in rows}
        genes = {row.get("target_id") for row in rows if isinstance(row.get("target_id"), str)}
        if "ambiguous" in statuses or len(genes) > 1:
            excluded[protein] = "ambiguous"
        elif len(statuses) > 1:
            excluded[protein] = "conflicting_status"
        elif statuses == {"unmapped"}:
            excluded[protein] = "unmapped"
        elif statuses != {"mapped"}:
            excluded[protein] = "invalid_status"
        elif any(not isinstance(row.get("target_id"), str) or not GENE_ID.fullmatch(row["target_id"]) for row in rows):
            excluded[protein] = "invalid_target_id"
        else:
            accepted[protein] = next(iter(genes))

    if not accepted:
        raise ValueError("Mapping release contains no valid unambiguous human mappings")
    gene_counts = Counter(accepted.values())
    report = {
        "input_rows": len(payload["mappings"]),
        "unique_valid_string_ids": len(grouped),
        "invalid_string_id_rows": invalid_source_rows,
        "duplicate_source_rows": sum(len(rows) - 1 for rows in grouped.values()),
        "mapped_proteins": len(accepted),
        "excluded_proteins": len(excluded),
        "excluded_by_reason": dict(sorted(Counter(excluded.values()).items())),
        "mapping_fraction": len(accepted) / len(grouped),
        "mapped_genes": len(gene_counts),
        "genes_with_multiple_string_proteins": sum(count > 1 for count in gene_counts.values()),
        "source_reported_coverage": payload.get("coverage"),
    }
    return MappingData(accepted, excluded, releases, report)


def build_network(
    links_path: Path | str,
    mapping: MappingData,
    *,
    min_combined_score: int = 700,
    min_experiments: int = 400,
) -> NetworkData:
    """Keep direct experiments, collapse proteins to genes, deduplicate unordered edges.

    All mapped genes are retained in the full graph, including isolates after
    filtering, so coverage loss remains measurable.
    """
    for name, value in (("combined_score", min_combined_score), ("experiments", min_experiments)):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1000:
            raise ValueError(f"Minimum {name} must be an integer in 0..1000")
    path = Path(links_path)
    opener = gzip.open if path.suffix == ".gz" else open
    counts: Counter = Counter()
    proteins_seen: set[str] = set()
    retained_proteins: set[str] = set()
    edges: set[tuple[str, str]] = set()
    with opener(path, "rt", encoding="utf-8") as handle:
        columns = handle.readline().split()
        required = {"protein1", "protein2", "combined_score", "experiments"}
        if len(columns) != len(set(columns)) or not required.issubset(columns):
            raise ValueError(f"STRING header must contain unique columns {sorted(required)}; got {columns}")
        positions = {name: columns.index(name) for name in required}
        for number, line in enumerate(handle, 2):
            if not line.strip():
                continue
            fields = line.split()
            if len(fields) != len(columns):
                raise ValueError(f"STRING row {number}: expected {len(columns)} columns, got {len(fields)}")
            counts["input_rows"] += 1
            a, b = fields[positions["protein1"]], fields[positions["protein2"]]
            proteins_seen.update((a, b))
            try:
                combined = int(fields[positions["combined_score"]])
                direct = int(fields[positions["experiments"]])
            except ValueError as error:
                raise ValueError(f"STRING row {number}: scores must be integers") from error
            if not 0 <= combined <= 1000 or not 0 <= direct <= 1000:
                raise ValueError(f"STRING row {number}: scores must be in 0..1000")
            if combined < min_combined_score or direct < min_experiments:
                counts["filtered_by_score_rows"] += 1
                continue
            counts["score_passing_rows"] += 1
            retained_proteins.update((a, b))
            gene_a, gene_b = mapping.protein_to_gene.get(a), mapping.protein_to_gene.get(b)
            if gene_a is None or gene_b is None:
                counts["excluded_mapping_rows"] += 1
                continue
            if gene_a == gene_b:
                counts["self_loop_rows"] += 1
                continue
            edge = tuple(sorted((gene_a, gene_b)))
            if edge in edges:
                counts["duplicate_edge_rows"] += 1
            edges.add(edge)

    genes = tuple(sorted(set(mapping.protein_to_gene.values())))
    index = {gene: i for i, gene in enumerate(genes)}
    pairs = np.array([(index[a], index[b]) for a, b in sorted(edges)], dtype=np.int32).reshape(-1, 2)
    rows = np.concatenate((pairs[:, 0], pairs[:, 1]))
    cols = np.concatenate((pairs[:, 1], pairs[:, 0]))
    graph = csr_matrix((np.ones(len(rows), dtype=np.uint8), (rows, cols)), shape=(len(genes), len(genes)))
    graph.sort_indices()
    n_components, labels = connected_components(graph, directed=False)
    sizes = np.bincount(labels, minlength=n_components)
    # Lexicographically first gene resolves equal-size component ties.
    largest = np.flatnonzero(labels == int(np.argmax(sizes)))
    lcc_edges = graph[largest][:, largest].nnz // 2
    stats = {name: counts[name] for name in (
        "input_rows", "filtered_by_score_rows", "score_passing_rows",
        "excluded_mapping_rows", "self_loop_rows", "duplicate_edge_rows",
    )}
    stats.update({
        "string_proteins_seen": len(proteins_seen),
        "string_proteins_mapped": len(proteins_seen & mapping.protein_to_gene.keys()),
        "string_proteins_excluded_by_reason": dict(sorted(Counter(
            mapping.excluded.get(p, "absent_from_mapping")
            for p in proteins_seen if p not in mapping.protein_to_gene
        ).items())),
        "score_passing_proteins": len(retained_proteins),
        "score_passing_proteins_mapped": len(retained_proteins & mapping.protein_to_gene.keys()),
        "nodes": len(genes),
        "nodes_with_edges": int(np.count_nonzero(np.diff(graph.indptr))),
        "isolated_nodes": int(np.count_nonzero(np.diff(graph.indptr) == 0)),
        "edges": len(edges),
        "components": int(n_components),
        "component_sizes_descending": sorted(sizes.tolist(), reverse=True),
        "largest_component_nodes": len(largest),
        "largest_component_edges": lcc_edges,
        "genes_outside_largest_component": len(genes) - len(largest),
    })
    return NetworkData(graph, genes, labels, largest, stats, columns)


def encode_distances(values: NDArray, dtype: str = "uint8") -> NDArray:
    """Encode +infinity as the dtype maximum; reject overflow before casting."""
    if dtype not in ("uint8", "uint16"):
        raise ValueError("Distance dtype must be uint8 or uint16")
    sentinel = int(np.iinfo(dtype).max)
    if np.any(np.isnan(values)) or np.any(values < 0):
        raise ValueError("Distances must be nonnegative or positive infinity")
    finite = np.isfinite(values)
    if np.any(values[finite] != np.floor(values[finite])):
        raise ValueError("Unweighted distances must be whole numbers")
    if np.any(values[finite] >= sentinel):
        raise OverflowError(f"Finite distance does not fit {dtype} with sentinel {sentinel}; use a wider dtype")
    encoded = np.full(values.shape, sentinel, dtype=dtype)
    encoded[finite] = values[finite].astype(dtype)
    return encoded


def precompute_distances(
    graph: csr_matrix,
    output: Path | str,
    *,
    chunk_size: int = 128,
    dtype: str = "uint8",
    progress: Callable[[int, int], None] | None = None,
) -> dict:
    """Chunked SciPy shortest paths to a .npy memmap; also supports disconnected graphs."""
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    if graph.shape[0] != graph.shape[1] or graph.shape[0] == 0:
        raise ValueError("Graph must be nonempty and square")
    if (graph != graph.T).nnz or np.any(graph.diagonal()) or np.any(graph.data != 1):
        raise ValueError("Graph must be undirected, unweighted and have no self-loops")
    encode_distances(np.array([0.0]), dtype)
    path = Path(output)
    if path.exists():
        raise FileExistsError(f"Distance output already exists: {path}")
    n = graph.shape[0]
    started = perf_counter()
    distances = np.lib.format.open_memmap(path, mode="w+", dtype=dtype, shape=(n, n))
    maximum, unreachable = 0, 0
    try:
        for start in range(0, n, chunk_size):
            stop = min(start + chunk_size, n)
            block = shortest_path(graph, method="D", directed=False, unweighted=True, indices=np.arange(start, stop))
            encoded = encode_distances(block, dtype)
            finite = np.isfinite(block)
            maximum = max(maximum, int(block[finite].max(initial=0)))
            unreachable += int(np.count_nonzero(~finite))
            distances[start:stop] = encoded
            if progress:
                progress(stop, n)
        distances.flush()
    finally:
        # Close before moving artifacts on Windows, including after failed builds.
        distances._mmap.close()
    return {
        "shape": [n, n], "dtype": dtype, "unreachable_sentinel": int(np.iinfo(dtype).max),
        "unreachable_pairs": unreachable, "max_finite_distance": maximum,
        "chunk_size": chunk_size, "seconds": perf_counter() - started,
    }
