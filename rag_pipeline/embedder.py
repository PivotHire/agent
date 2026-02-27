#!/usr/bin/env python3
"""
embedder.py - Simple code embedding using Voyager AI Code-3.
"""

import os
from typing import List, Dict
import voyageai


def embed_chunk(chunk, api_key: str = None) -> List[float]:
    """
    Embed a single code chunk.

    Args:
        chunk: A CodeChunk object with 'content' attribute
        api_key: Voyager AI API key (or set VOYAGE_API_KEY env var)

    Returns:
        List of floats representing the embedding vector (1024 dimensions)
    """
    # Get API key
    key = api_key or os.environ.get("VOYAGE_API_KEY")
    if not key:
        raise ValueError("No API key provided. Pass api_key or set VOYAGE_API_KEY")

    # Initialize client
    client = voyageai.Client(api_key=key)

    # Embed the chunk content
    result = client.embed(
        [chunk.content],  # API expects a list
        model="voyage-code-3",
        input_type="document"
    )

    # Return the embedding vector
    return result.embeddings[0] if result.embeddings else []


def embed_chunks(chunks: List, api_key: str = None) -> List[Dict]:
    """
    Embed all chunks.

    Args:
        chunks: List of CodeChunk objects
        api_key: Voyager AI API key (or set VOYAGE_API_KEY env var)

    Returns:
        List of dictionaries with 'chunk' and 'embedding' keys
    """
    # Get API key
    key = api_key or os.environ.get("VOYAGE_API_KEY")
    if not key:
        raise ValueError("No API key provided. Pass api_key or set VOYAGE_API_KEY")

    # Initialize client
    client = voyageai.Client(api_key=key)

    # Collect all content
    texts = [chunk.content for chunk in chunks]

    # Embed all at once (more efficient than one by one)
    result = client.embed(
        texts,
        model="voyage-code-3",
        input_type="document"
    )

    # Combine chunks with their embeddings
    embedded = []
    for chunk, embedding in zip(chunks, result.embeddings):
        embedded.append({
            "chunk": chunk,
            "embedding": embedding
        })

    return embedded


# Simple usage example
if __name__ == "__main__":
    print("Simple embedder for code chunks")
    print("Usage:")
    print("  from embedder import embed_chunk, embed_chunks")
    print("  vector = embed_chunk(chunk, api_key='...')")
    print("  results = embed_chunks(chunks, api_key='...')")