#!/usr/bin/env python3
"""
workflow.py - End-to-end workflow that connects chunking, embedding, and ChromaDB.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import json

import chromadb

from chunker import Chunker, CodeChunk
from embedder import embed_chunks
from chroma import insert_to_chroma


EmbeddedChunk = Dict[str, Any]  # {"chunk": CodeChunk, "embedding": List[float]}


@dataclass
class WorkflowConfig:
    collection_name: str = "code_chunks"
    db_path: str = "./my_chroma_db"
    k: int = 5
    distance_threshold: float = 0.5


def build_index(
    repo_path: Path,
    api_key: Optional[str] = None,
    config: WorkflowConfig = WorkflowConfig(),
    embed_documents: Optional[Callable[[List[CodeChunk]], List[EmbeddedChunk]]] = None,
) -> int:
    """
    Build a ChromaDB index for the repository.

    Args:
        repo_path: Repository root path
        api_key: Voyage API key if using default embedder
        config: Workflow configuration
        embed_documents: Optional custom embedding function

    Returns:
        Number of chunks inserted
    """
    chunker = Chunker()
    chunks = chunker.chunk_repository(repo_path)
    if not chunks:
        return 0

    if embed_documents is None:
        embed_documents = lambda items: embed_chunks(items, api_key=api_key)

    embedded = embed_documents(chunks)
    return insert_to_chroma(
        embedded,
        collection_name=config.collection_name,
        db_path=config.db_path,
    )


def _query_collection(
    embedding: List[float],
    config: WorkflowConfig,
    k: Optional[int] = None,
) -> Dict[str, List[Any]]:
    client = chromadb.PersistentClient(path=config.db_path)
    collection = client.get_collection(name=config.collection_name)
    return collection.query(
        query_embeddings=[embedding],
        n_results=k or config.k,
        include=["documents", "metadatas", "distances", "ids"],
    )


def _flatten_query_results(raw: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
    documents = (raw.get("documents") or [[]])[0]
    metadatas = (raw.get("metadatas") or [[]])[0]
    distances = (raw.get("distances") or [[]])[0]
    ids = (raw.get("ids") or [[]])[0]

    results = []
    for i, document in enumerate(documents):
        results.append({
            "id": ids[i] if i < len(ids) else None,
            "document": document,
            "metadata": metadatas[i] if i < len(metadatas) else None,
            "distance": distances[i] if i < len(distances) else None,
        })
    return results


def query_text(
    query: str,
    api_key: Optional[str] = None,
    config: WorkflowConfig = WorkflowConfig(),
    embed_query: Optional[Callable[[str], List[float]]] = None,
) -> List[Dict[str, Any]]:
    """
    Query ChromaDB using raw text.
    """
    if embed_query is None:
        query_chunk = CodeChunk(
            file_path="<query>",
            language="text",
            signature="",
            content=query,
            chunk_type="query",
            start_line=1,
            end_line=1,
            node_types=[],
        )
        embedded = embed_chunks([query_chunk], api_key=api_key)
        if not embedded:
            return []
        embedding = embedded[0]["embedding"]
    else:
        embedding = embed_query(query)

    raw = _query_collection(embedding, config)
    return _flatten_query_results(raw)


def _extract_conflict_chunks(
    conflict_data: List[Dict[str, Any]],
    chunker: Chunker,
) -> List[Dict[str, Any]]:
    extracted = []
    for conflict in conflict_data:
        file_path = Path(conflict.get("filefrom") or conflict.get("fileto") or "")
        lines = conflict.get("lns", [])
        if not file_path.exists():
            extracted.append({
                "file": str(file_path),
                "conflict_lines": lines,
                "error": f"File not found: {file_path}",
                "chunks": [],
            })
            continue
        chunks = chunker.chunk_functions_from_lines(file_path, lines)
        extracted.append({
            "file": str(file_path),
            "conflict_lines": lines,
            "chunks": chunks,
        })
    return extracted


def rag_for_conflicts(
    conflict_data: List[Dict[str, Any]],
    api_key: Optional[str] = None,
    config: WorkflowConfig = WorkflowConfig(),
    embed_documents: Optional[Callable[[List[CodeChunk]], List[EmbeddedChunk]]] = None,
) -> List[Dict[str, Any]]:
    """
    Use conflict line data to retrieve similar code from ChromaDB.
    """
    if embed_documents is None:
        embed_documents = lambda items: embed_chunks(items, api_key=api_key)

    chunker = Chunker()
    extracted = _extract_conflict_chunks(conflict_data, chunker)
    results = []

    for item in extracted:
        if item.get("error"):
            results.append(item)
            continue

        chunks = item["chunks"]
        embedded = embed_documents(chunks) if chunks else []
        per_chunk = []
        for embedded_item in embedded:
            embedding = embedded_item["embedding"]
            raw = _query_collection(embedding, config)
            similar = _flatten_query_results(raw)
            similar = [
                entry for entry in similar
                if entry["distance"] is None
                or entry["distance"] <= config.distance_threshold
            ]
            per_chunk.append({
                "chunk": embedded_item["chunk"],
                "similar": similar,
            })

        results.append({
            "file": item["file"],
            "conflict_lines": item["conflict_lines"],
            "chunks": per_chunk,
        })

    return results


def run_full_workflow(
    repo_path: Path,
    conflict_data: List[Dict[str, Any]],
    api_key: Optional[str] = None,
    config: WorkflowConfig = WorkflowConfig(),
    embed_documents: Optional[Callable[[List[CodeChunk]], List[EmbeddedChunk]]] = None,
) -> List[Dict[str, Any]]:
    """
    Build index then run conflict-based RAG retrieval.
    """
    build_index(
        repo_path=repo_path,
        api_key=api_key,
        config=config,
        embed_documents=embed_documents,
    )
    return rag_for_conflicts(
        conflict_data=conflict_data,
        api_key=api_key,
        config=config,
        embed_documents=embed_documents,
    )


def load_conflict_data(json_path: Path) -> List[Dict[str, Any]]:
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Chunk -> Embed -> Chroma -> RAG")
    parser.add_argument("--repo", type=str, help="Path to repository")
    parser.add_argument("--conflicts", type=str, help="Path to conflict JSON")
    parser.add_argument("--collection", type=str, default="code_chunks")
    parser.add_argument("--db-path", type=str, default="./my_chroma_db")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--threshold", type=float, default=0.5)
    args = parser.parse_args()

    if not args.repo:
        print("Error: --repo is required")
        return 2

    config = WorkflowConfig(
        collection_name=args.collection,
        db_path=args.db_path,
        k=args.k,
        distance_threshold=args.threshold,
    )

    api_key = os.environ.get("VOYAGE_API_KEY")
    repo_path = Path(args.repo).resolve()
    if args.conflicts:
        conflicts = load_conflict_data(Path(args.conflicts))
        results = run_full_workflow(
            repo_path=repo_path,
            conflict_data=conflicts,
            api_key=api_key,
            config=config,
        )
        print(json.dumps(results, indent=2))
        return 0

    inserted = build_index(
        repo_path=repo_path,
        api_key=api_key,
        config=config,
    )
    print(f"Inserted {inserted} chunks into '{config.collection_name}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
