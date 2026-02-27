import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from rag_pipeline.chunker import Chunker

_chunker = Chunker()


def get_file_structure(file_path: str) -> list:
    """List all top-level functions and classes in a source file.

    Args:
        file_path: Path to the source file.

    Returns:
        List of dicts with name, type, start_line, end_line.
    """
    path = Path(file_path)
    config = _chunker.should_process_file(path)
    if not config:
        return [{"error": f"Unsupported or ignored file: {file_path}"}]
    try:
        chunks = _chunker.chunk_file(path, config)
        return [
            {"name": c.signature, "type": c.chunk_type, "start_line": c.start_line, "end_line": c.end_line}
            for c in chunks if c.chunk_type != "imports_and_globals"
        ]
    except Exception as e:
        return [{"error": str(e)}]


def get_function(file_path: str, function_name: str) -> dict:
    """Get the full source code of a named function or class.

    Args:
        file_path: Path to the source file.
        function_name: Name of the function or class to retrieve.

    Returns:
        Dict with signature, content, start_line, end_line.
    """
    path = Path(file_path)
    config = _chunker.should_process_file(path)
    if not config:
        return {"error": f"Unsupported or ignored file: {file_path}"}
    try:
        chunks = _chunker.chunk_file(path, config)
        for c in chunks:
            if function_name in c.signature:
                return {"signature": c.signature, "content": c.content,
                        "start_line": c.start_line, "end_line": c.end_line}
        return {"error": f"'{function_name}' not found in {file_path}"}
    except Exception as e:
        return {"error": str(e)}


def get_context(file_path: str, start_line: int, end_line: int) -> str:
    """Get raw source lines around a line range, with 10 lines of surrounding context.

    Args:
        file_path: Path to the source file.
        start_line: First line of the range (1-based).
        end_line: Last line of the range (1-based).

    Returns:
        Formatted source lines with line numbers.
    """
    try:
        with open(file_path) as f:
            lines = f.readlines()
        lo = max(0, start_line - 1 - 10)
        hi = min(len(lines), end_line + 10)
        return "".join(f"{lo + i + 1}: {line}" for i, line in enumerate(lines[lo:hi]))
    except Exception as e:
        return f"Error: {e}"
