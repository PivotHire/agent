#!/usr/bin/env python3
"""
chroma.py - ChromaDB integration for code chunks and embeddings.
"""

import chromadb


def insert_to_chroma(results, collection_name="code_chunks", db_path="./my_chroma_db"):
    """
    Insert code chunks and embeddings into ChromaDB.

    Args:
        results: Output from embed_chunks() - list of {"chunk": chunk, "embedding": vector}
        collection_name: Name of ChromaDB collection (default: "code_chunks")
        db_path: Path to persistent ChromaDB (default: "./my_chroma_db")

    Returns:
        Number of items inserted
    """
    # Initialize persistent client
    client = chromadb.PersistentClient(path=db_path)

    # Get or create collection
    collection = client.get_or_create_collection(name=collection_name)

    # Prepare data for batch insertion
    documents = []
    embeddings = []
    ids = []
    metadatas = []

    for i, item in enumerate(results):
        chunk = item["chunk"]
        embedding = item["embedding"]

        # Document: the actual code
        documents.append(chunk.content)

        # Embedding: the vector
        embeddings.append(embedding)

        # ID: unique identifier
        ids.append(f"{chunk.file_path}:{chunk.start_line}-{chunk.end_line}")

        # Metadata: for filtering
        metadatas.append({
            "file_path": chunk.file_path,
            "language": chunk.language,
            "chunk_type": chunk.chunk_type,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line
        })

    # Insert everything
    collection.add(
        documents=documents,
        embeddings=embeddings,
        ids=ids,
        metadatas=metadatas
    )

    print(f"✓ Inserted {len(results)} chunks into '{collection_name}'")
    return len(results)


# Example usage
if __name__ == "__main__":
    # Test the connection
    client = chromadb.PersistentClient(path="./my_chroma_db")
    client.heartbeat()
    print("✅ ChromaDB ready")

    # Show how to use the function
    print("\nUsage:")
    print("  from chunker import Chunker")
    print("  from embedder import embed_chunks")
    print("  from chroma import insert_to_chroma")
    print("")
    print("  chunker = Chunker()")
    print("  chunks = chunker.chunk_repository(Path('my_project'))")
    print("  results = embed_chunks(chunks, api_key='...')")
    print("  insert_to_chroma(results)")