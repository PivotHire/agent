#!/usr/bin/env python3
"""
conflict_processor.py - Process merge conflicts across multiple files.

This module chunks and embeds functions that contain merge conflicts,
supporting multi-file conflict resolution scenarios.
"""

from pathlib import Path
from typing import List, Dict, Optional, Any
from dataclasses import asdict
import json

from chunker import Chunker
from embedder import embed_chunks


def chunk_and_embed_conflicts(
    conflict_data: List[Dict[str, Any]],
    api_key: str,
    verbose: bool = True
) -> List[Dict[str, Any]]:
    """
    Process conflict data from multiple files, chunk relevant functions, and embed them.

    Args:
        conflict_data: List of dicts with structure:
            [
                {
                    "filefrom": "src/app.js",
                    "fileto": "src/app.js",
                    "lns": [11, 12, 30, 31]
                },
                ...
            ]
        api_key: Voyage AI API key for embeddings
        verbose: Whether to print progress information

    Returns:
        List of dicts with structure:
            [
                {
                    "file": "src/app.js",
                    "conflict_lines": [11, 12, 30, 31],
                    "chunks": [CodeChunk objects...],
                    "embedded_chunks": [
                        {
                            "chunk": CodeChunk,
                            "embedding": vector
                        },
                        ...
                    ]
                },
                ...
            ]
    """
    if verbose:
        print("=" * 60)
        print("PROCESSING MULTI-FILE CONFLICTS")
        print("=" * 60)
        print(f"Processing {len(conflict_data)} files with conflicts...")

    # Initialize chunker once
    chunker = Chunker()
    results = []

    # Process each file's conflicts
    for i, conflict in enumerate(conflict_data, 1):
        # Extract file path and lines
        file_path = Path(conflict.get("filefrom", conflict.get("fileto", "")))
        lines = conflict.get("lns", [])

        if verbose:
            print(f"\n[{i}/{len(conflict_data)}] Processing: {file_path}")
            print(f"  Conflict lines: {lines}")

        # Handle file not found
        if not file_path.exists():
            if verbose:
                print(f"  ⚠️  File not found: {file_path}")
            results.append({
                "file": str(file_path),
                "conflict_lines": lines,
                "error": f"File not found: {file_path}",
                "chunks": [],
                "embedded_chunks": []
            })
            continue

        # Handle unsupported file types
        config = chunker.should_process_file(file_path)
        if not config:
            if verbose:
                print(f"  ⚠️  Unsupported file type: {file_path.suffix}")
            results.append({
                "file": str(file_path),
                "conflict_lines": lines,
                "error": f"Unsupported file type: {file_path.suffix}",
                "chunks": [],
                "embedded_chunks": []
            })
            continue

        try:
            # Get unique chunks for the conflict lines
            chunks = chunker.chunk_functions_from_lines(file_path, lines)

            if verbose:
                print(f"  ✓ Found {len(chunks)} unique function(s) containing conflicts")
                for chunk in chunks:
                    print(f"    - {chunk.chunk_type}: {chunk.signature[:50]}...")

            # Embed the chunks if we have any
            embedded_chunks = []
            if chunks:
                if verbose:
                    print(f"  → Embedding {len(chunks)} chunks...")

                embedded_chunks = embed_chunks(chunks, api_key=api_key)

                if verbose:
                    print(f"  ✓ Embedded {len(embedded_chunks)} chunks")

            # Add to results
            results.append({
                "file": str(file_path),
                "conflict_lines": lines,
                "chunks": chunks,  # Raw CodeChunk objects
                "embedded_chunks": embedded_chunks  # List of {"chunk": CodeChunk, "embedding": vector}
            })

        except Exception as e:
            if verbose:
                print(f"  ❌ Error processing file: {e}")
            results.append({
                "file": str(file_path),
                "conflict_lines": lines,
                "error": str(e),
                "chunks": [],
                "embedded_chunks": []
            })

    if verbose:
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        total_chunks = sum(len(r["chunks"]) for r in results)
        total_embedded = sum(len(r["embedded_chunks"]) for r in results)
        successful = sum(1 for r in results if "error" not in r)

        print(f"Files processed: {len(results)}")
        print(f"Successful: {successful}/{len(results)}")
        print(f"Total chunks found: {total_chunks}")
        print(f"Total chunks embedded: {total_embedded}")

    return results


def save_conflict_results(results: List[Dict], output_path: Path):
    """
    Save the conflict processing results to a JSON file.

    Args:
        results: Output from chunk_and_embed_conflicts
        output_path: Path to save the JSON file
    """
    # Convert results to JSON-serializable format
    serializable_results = []

    for result in results:
        serializable_result = {
            "file": result["file"],
            "conflict_lines": result["conflict_lines"],
        }

        # Add error if present
        if "error" in result:
            serializable_result["error"] = result["error"]

        # Convert chunks to dicts
        serializable_result["chunks"] = [
            asdict(chunk) for chunk in result.get("chunks", [])
        ]

        # Convert embedded chunks (keeping only chunk metadata, not full embeddings)
        serializable_result["embedded_chunks_summary"] = [
            {
                "chunk_signature": item["chunk"].signature,
                "chunk_type": item["chunk"].chunk_type,
                "lines": f"{item['chunk'].start_line}-{item['chunk'].end_line}",
                "embedding_dimensions": len(item["embedding"])
            }
            for item in result.get("embedded_chunks", [])
        ]

        serializable_results.append(serializable_result)

    # Save to file
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(serializable_results, f, indent=2, ensure_ascii=False)

    print(f"\n✓ Results saved to: {output_path}")


def load_conflict_data(json_path: Path) -> List[Dict]:
    """
    Load conflict data from a JSON file.

    Args:
        json_path: Path to the JSON file containing conflict data

    Returns:
        List of conflict dictionaries
    """
    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def main():
    """Example usage of the conflict processor."""
    import os

    # Example conflict data (as provided by user)
    sample_conflicts = [
        {
            "filefrom": "demo_code/sample.py",
            "fileto": "demo_code/sample.py",
            "lns": [19, 20, 21, 25, 26]  # Lines in Calculator methods
        },
        {
            "filefrom": "chunker.py",
            "fileto": "chunker.py",
            "lns": [220, 225, 330, 335]  # Lines in different functions
        }
    ]

    # Get API key
    api_key = os.environ.get("VOYAGE_API_KEY") or "pa-XpJmKf_6HucjcZRGDueQzIVsHq3LHMsEU4E1UStG5wB"

    # Process conflicts
    results = chunk_and_embed_conflicts(sample_conflicts, api_key)

    # Save results
    save_conflict_results(results, Path("conflict_results.json"))

    print("\n" + "=" * 60)
    print("DETAILED RESULTS")
    print("=" * 60)

    for result in results:
        print(f"\nFile: {result['file']}")
        print(f"Conflict lines: {result['conflict_lines']}")

        if "error" in result:
            print(f"  Error: {result['error']}")
        else:
            print(f"  Chunks found: {len(result['chunks'])}")
            for chunk in result['chunks']:
                print(f"    - {chunk.chunk_type}: {chunk.signature[:60]}...")
                print(f"      Lines {chunk.start_line}-{chunk.end_line}")

            print(f"  Embeddings created: {len(result['embedded_chunks'])}")


if __name__ == "__main__":
    main()