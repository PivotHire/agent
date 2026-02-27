#!/usr/bin/env python3
"""
treesitter_chunker_simple.py - Simplified version using tree-sitter-languages.

This version uses the pre-built parsers from tree-sitter-languages package,
eliminating the need to build grammars manually.

*** MODIFIED to include the 'signature' field in CodeChunk ***
"""

import json
from pathlib import Path
from typing import List, Dict, Set, Optional
from dataclasses import dataclass, asdict
from collections import defaultdict

import tree_sitter_languages as tsl

try:
    import orjson
    HAS_ORJSON = True
except ImportError:
    HAS_ORJSON = False

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False


# --- CHANGE 1: Added 'signature: str' ---
@dataclass
class CodeChunk:
    """Represents a single code chunk with metadata."""
    file_path: str
    language: str
    signature: str  # <-- ADDED
    content: str
    chunk_type: str
    start_line: int
    end_line: int
    node_types: List[str]


# Language configurations
LANGUAGE_MAP = {
    ".py": {
        "language": "python",
        "top_level_nodes": {
            "function_definition",
            "class_definition",
            "decorated_definition"
        }
    },
    ".js": {
        "language": "javascript",
        "top_level_nodes": {
            "function_declaration",
            "class_declaration",
            "function",
            "lexical_declaration",
            "export_statement"
        }
    },
    ".ts": {
        "language": "typescript",
        "top_level_nodes": {
            "function_declaration",
            "class_declaration",
            "interface_declaration",
            "type_alias_declaration",
            "enum_declaration"
        }
    },
    ".tsx": {
        "language": "tsx",
        "top_level_nodes": {
            "function_declaration",
            "class_declaration",
            "interface_declaration",
            "lexical_declaration"
        }
    },
    ".jsx": {
        "language": "jsx",
        "top_level_nodes": {
            "function_declaration",
            "class_declaration",
            "lexical_declaration"
        }
    },
    ".go": {
        "language": "go",
        "top_level_nodes": {
            "function_declaration",
            "method_declaration",
            "type_declaration"
        }
    },
    ".rs": {
        "language": "rust",
        "top_level_nodes": {
            "function_item",
            "impl_item",
            "struct_item",
            "enum_item",
            "trait_item"
        }
    },
    ".java": {
        "language": "java",
        "top_level_nodes": {
            "class_declaration",
            "interface_declaration",
            "method_declaration",
            "constructor_declaration"
        }
    },
    ".cpp": {
        "language": "cpp",
        "top_level_nodes": {
            "function_definition",
            "class_specifier",
            "struct_specifier",
            "namespace_definition"
        }
    },
    ".c": {
        "language": "c",
        "top_level_nodes": {
            "function_definition",
            "struct_specifier",
            "union_specifier"
        }
    },
    ".rb": {
        "language": "ruby",
        "top_level_nodes": {
            "method",
            "class",
            "module"
        }
    },
    ".php": {
        "language": "php",
        "top_level_nodes": {
            "function_definition",
            "class_declaration",
            "method_declaration"
        }
    }
}

# Add more extensions for the same languages
LANGUAGE_MAP[".pyw"] = LANGUAGE_MAP[".py"]
LANGUAGE_MAP[".pyi"] = LANGUAGE_MAP[".py"]
LANGUAGE_MAP[".mjs"] = LANGUAGE_MAP[".js"]
LANGUAGE_MAP[".cjs"] = LANGUAGE_MAP[".js"]
LANGUAGE_MAP[".cc"] = LANGUAGE_MAP[".cpp"]
LANGUAGE_MAP[".cxx"] = LANGUAGE_MAP[".cpp"]
LANGUAGE_MAP[".hpp"] = LANGUAGE_MAP[".cpp"]
LANGUAGE_MAP[".h"] = LANGUAGE_MAP[".c"]

IGNORED_DIRS = {
    ".git", ".svn", ".hg",
    "node_modules", "__pycache__", ".pytest_cache",
    "venv", "env", ".env", ".venv",
    "build", "dist", "out", "target",
    ".idea", ".vscode", ".vs",
    "vendor", "packages",
}

IGNORED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
    ".mp3", ".mp4", ".avi", ".mov",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".zip", ".tar", ".gz", ".rar",
    ".exe", ".dll", ".so", ".dylib",
    ".json", ".xml", ".yaml", ".yml", ".toml",
    ".lock", ".log", ".csv",
    ".md", ".rst", ".txt",
}


class Chunker:
    """Simplified chunker using tree-sitter-languages."""

    def __init__(self):
        """Initialize the chunker."""
        print("Initializing Tree-sitter chunker...")
        self.parsers = {}
        self._initialize_parsers()

    def _initialize_parsers(self):
        """Initialize parsers for supported languages."""
        for ext, config in LANGUAGE_MAP.items():
            lang_name = config["language"]
            if lang_name not in self.parsers:
                try:
                    parser = tsl.get_parser(lang_name)
                    self.parsers[lang_name] = parser
                    print(f"  Loaded parser for {lang_name}")
                except Exception as e:
                    print(f"  Warning: Could not load parser for {lang_name}: {e}")

    def should_process_file(self, file_path: Path) -> Optional[Dict]:
        """Check if file should be processed and return language config."""
        for parent in file_path.parents:
            if parent.name in IGNORED_DIRS:
                return None

        extension = file_path.suffix.lower()
        if extension in IGNORED_EXTENSIONS:
            return None

        return LANGUAGE_MAP.get(extension)

    def chunk_file(self, file_path: Path, config: Dict) -> List[CodeChunk]:
        """Chunk a single file."""
        lang_name = config["language"]
        if lang_name not in self.parsers:
            return []

        parser = self.parsers[lang_name]
        top_level_nodes = config["top_level_nodes"]

        try:
            with open(file_path, 'rb') as f:
                content_bytes = f.read()

            if not content_bytes:
                return []

            tree = parser.parse(content_bytes)
            root = tree.root_node

            try:
                content_str = content_bytes.decode('utf-8')
            except UnicodeDecodeError:
                return []

            content_lines = content_str.splitlines()
            chunks = []

            between_chunk_lines = []
            between_chunk_types = []
            between_chunk_start = None

            for child in root.named_children:
                start_line = child.start_point[0]
                end_line = child.end_point[0]

                if child.type in top_level_nodes:
                    # Save any accumulated "between" content
                    if between_chunk_lines:
                        chunk_content = '\n'.join(between_chunk_lines)
                        if chunk_content.strip():
                            
                            # --- CHANGE 2: Added signature for 'imports_and_globals' ---
                            chunk_signature = f"imports_and_globals:{between_chunk_start + 1}"
                            
                            chunks.append(CodeChunk(
                                file_path=str(file_path),
                                language=lang_name,
                                signature=chunk_signature,  # <-- ADDED
                                content=chunk_content,
                                chunk_type="imports_and_globals",
                                start_line=between_chunk_start + 1,
                                end_line=between_chunk_start + len(between_chunk_lines),
                                node_types=list(set(between_chunk_types))
                            ))
                        between_chunk_lines = []
                        between_chunk_types = []
                        between_chunk_start = None

                    # Extract this major block
                    chunk_lines = content_lines[start_line:end_line + 1]
                    chunk_content = '\n'.join(chunk_lines)

                    # --- CHANGE 3: Added signature for 'top_level_nodes' ---
                    chunk_signature = chunk_lines[0].strip() if chunk_lines else ""

                    if chunk_content.strip():
                        chunk_type = self._determine_chunk_type(child.type)
                        chunks.append(CodeChunk(
                            file_path=str(file_path),
                            language=lang_name,
                            signature=chunk_signature,  # <-- ADDED
                            content=chunk_content,
                            chunk_type=chunk_type,
                            start_line=start_line + 1,
                            end_line=end_line + 1,
                            node_types=[child.type]
                        ))
                else:
                    # Accumulate "between" content
                    if between_chunk_start is None:
                        between_chunk_start = start_line

                    chunk_lines = content_lines[start_line:end_line + 1]
                    between_chunk_lines.extend(chunk_lines)
                    between_chunk_types.append(child.type)

            # Save any remaining "between" content
            if between_chunk_lines:
                chunk_content = '\n'.join(between_chunk_lines)
                if chunk_content.strip():
                    
                    # --- CHANGE 4: Added signature for final 'imports_and_globals' ---
                    chunk_signature = f"imports_and_globals:{between_chunk_start + 1}"
                    
                    chunks.append(CodeChunk(
                        file_path=str(file_path),
                        language=lang_name,
                        signature=chunk_signature,  # <-- ADDED
                        content=chunk_content,
                        chunk_type="imports_and_globals",
                        start_line=between_chunk_start + 1,
                        end_line=between_chunk_start + len(between_chunk_lines),
                        node_types=list(set(between_chunk_types))
                    ))

            return chunks

        except Exception as e:
            print(f"Error chunking {file_path}: {e}")
            return []

    def _determine_chunk_type(self, node_type: str) -> str:
        """Determine chunk type from node type."""
        if "function" in node_type or "method" in node_type:
            return "function"
        elif "class" in node_type:
            return "class"
        elif "interface" in node_type:
            return "interface"
        elif "struct" in node_type:
            return "struct"
        elif "enum" in node_type:
            return "enum"
        elif "trait" in node_type:
            return "trait"
        elif "type" in node_type:
            return "type_definition"
        else:
            return "code_block"

    def chunk_repository(self, repo_path: Path) -> List[CodeChunk]:
        """Chunk all files in a repository."""
        if not repo_path.is_dir():
            raise ValueError(f"{repo_path} is not a directory")

        all_chunks = []
        files_to_process = []

        for file_path in repo_path.rglob("*"):
            if file_path.is_file():
                config = self.should_process_file(file_path)
                if config:
                    files_to_process.append((file_path, config))

        print(f"\nFound {len(files_to_process)} files to process")

        if HAS_TQDM and files_to_process:
            iterator = tqdm(files_to_process, desc="Chunking files")
        else:
            iterator = files_to_process

        stats = defaultdict(int)

        for file_path, config in iterator:
            chunks = self.chunk_file(file_path, config)
            all_chunks.extend(chunks)

            lang = config["language"]
            stats[lang] += len(chunks)
            stats['total_files'] += 1
            stats['total_chunks'] += len(chunks)

        print(f"\n{'='*60}")
        print("CHUNKING STATISTICS")
        print(f"{'='*60}")
        print(f"Total files: {stats['total_files']}")
        print(f"Total chunks: {stats['total_chunks']}")

        if stats['total_chunks'] > 0:
            print("\nChunks by language:")
            for lang in sorted(set(config["language"] for _, config in files_to_process)):
                if stats[lang] > 0:
                    print(f"  {lang:12s}: {stats[lang]:5d} chunks")

        return all_chunks

    def chunk_functions_from_lines(self, file_path: Path, line_numbers: List[int]) -> List[CodeChunk]:
        """
        Given line numbers, return unique function chunks containing those lines.

        Args:
            file_path: Path to the source file
            line_numbers: List of 1-based line numbers

        Returns:
            List of unique CodeChunk objects for functions containing the lines
        """
        if not file_path.is_file():
            raise ValueError(f"{file_path} is not a file")

        config = self.should_process_file(file_path)
        if not config:
            return []

        lang_name = config["language"]
        if lang_name not in self.parsers:
            return []

        parser = self.parsers[lang_name]
        top_level_nodes = config["top_level_nodes"]

        try:
            with open(file_path, 'rb') as f:
                content_bytes = f.read()

            if not content_bytes:
                return []

            tree = parser.parse(content_bytes)
            root = tree.root_node

            try:
                content_str = content_bytes.decode('utf-8')
            except UnicodeDecodeError:
                return []

            content_lines = content_str.splitlines()

            # Convert line numbers to 0-based for tree-sitter
            zero_based_lines = set(line - 1 for line in line_numbers if line > 0)

            # Find unique functions containing the given lines
            unique_functions = set()
            processed_chunks = []

            for line_num in zero_based_lines:
                function_node = self._find_function_at_line(root, line_num, top_level_nodes)
                if function_node:
                    # Use node's start and end points as unique identifier
                    node_id = (function_node.start_point[0], function_node.end_point[0])
                    if node_id not in unique_functions:
                        unique_functions.add(node_id)

                        # Create chunk for this function
                        start_line = function_node.start_point[0]
                        end_line = function_node.end_point[0]
                        chunk_lines = content_lines[start_line:end_line + 1]
                        chunk_content = '\n'.join(chunk_lines)

                        # Get function signature (first line)
                        chunk_signature = chunk_lines[0].strip() if chunk_lines else ""

                        if chunk_content.strip():
                            chunk_type = self._determine_chunk_type(function_node.type)
                            chunk = CodeChunk(
                                file_path=str(file_path),
                                language=lang_name,
                                signature=chunk_signature,
                                content=chunk_content,
                                chunk_type=chunk_type,
                                start_line=start_line + 1,  # Convert back to 1-based
                                end_line=end_line + 1,
                                node_types=[function_node.type]
                            )
                            processed_chunks.append(chunk)

            return processed_chunks

        except Exception as e:
            print(f"Error processing {file_path}: {e}")
            return []

    def _find_function_at_line(self, node, line_number: int, top_level_nodes: Set[str]) -> Optional[object]:
        """
        Recursively find the innermost function/class containing the given line.

        Args:
            node: Current tree-sitter node
            line_number: 0-based line number
            top_level_nodes: Set of node types to consider as functions/classes

        Returns:
            The innermost function/class node containing the line, or None
        """
        # Check if this node is a function/class and contains the line
        if (node.type in top_level_nodes and
            node.start_point[0] <= line_number <= node.end_point[0]):

            # Check if any child is a more specific function containing this line
            for child in node.named_children:
                inner_function = self._find_function_at_line(child, line_number, top_level_nodes)
                if inner_function:
                    return inner_function

            # No inner function found, this node is the innermost
            return node

        # Not a function or doesn't contain the line, check children
        for child in node.named_children:
            result = self._find_function_at_line(child, line_number, top_level_nodes)
            if result:
                return result

        return None

    def map_lines_to_functions(self, file_path: Path, line_numbers: List[int]) -> Dict[int, Optional[CodeChunk]]:
        """
        Map each line number to its containing function chunk.

        Args:
            file_path: Path to the source file
            line_numbers: List of 1-based line numbers

        Returns:
            Dictionary mapping line numbers to their containing function chunks
        """
        if not file_path.is_file():
            raise ValueError(f"{file_path} is not a file")

        config = self.should_process_file(file_path)
        if not config:
            return {line: None for line in line_numbers}

        lang_name = config["language"]
        if lang_name not in self.parsers:
            return {line: None for line in line_numbers}

        parser = self.parsers[lang_name]
        top_level_nodes = config["top_level_nodes"]

        line_to_chunk = {}

        try:
            with open(file_path, 'rb') as f:
                content_bytes = f.read()

            if not content_bytes:
                return {line: None for line in line_numbers}

            tree = parser.parse(content_bytes)
            root = tree.root_node

            try:
                content_str = content_bytes.decode('utf-8')
            except UnicodeDecodeError:
                return {line: None for line in line_numbers}

            content_lines = content_str.splitlines()

            # Cache for already created chunks
            node_to_chunk = {}

            for line_num in line_numbers:
                if line_num <= 0 or line_num > len(content_lines):
                    line_to_chunk[line_num] = None
                    continue

                zero_based_line = line_num - 1
                function_node = self._find_function_at_line(root, zero_based_line, top_level_nodes)

                if function_node:
                    # Use node's start and end as cache key
                    node_id = (function_node.start_point[0], function_node.end_point[0])

                    if node_id not in node_to_chunk:
                        # Create chunk for this function
                        start_line = function_node.start_point[0]
                        end_line = function_node.end_point[0]
                        chunk_lines = content_lines[start_line:end_line + 1]
                        chunk_content = '\n'.join(chunk_lines)

                        # Get function signature (first line)
                        chunk_signature = chunk_lines[0].strip() if chunk_lines else ""

                        if chunk_content.strip():
                            chunk_type = self._determine_chunk_type(function_node.type)
                            chunk = CodeChunk(
                                file_path=str(file_path),
                                language=lang_name,
                                signature=chunk_signature,
                                content=chunk_content,
                                chunk_type=chunk_type,
                                start_line=start_line + 1,  # Convert back to 1-based
                                end_line=end_line + 1,
                                node_types=[function_node.type]
                            )
                            node_to_chunk[node_id] = chunk
                        else:
                            node_to_chunk[node_id] = None

                    line_to_chunk[line_num] = node_to_chunk[node_id]
                else:
                    line_to_chunk[line_num] = None

            return line_to_chunk

        except Exception as e:
            print(f"Error processing {file_path}: {e}")
            return {line: None for line in line_numbers}


def save_chunks(chunks: List[CodeChunk], output_path: Path):
    """Save chunks to JSON file."""
    chunk_dicts = [asdict(chunk) for chunk in chunks]

    if HAS_ORJSON:
        with open(output_path, 'wb') as f:
            f.write(orjson.dumps(chunk_dicts, option=orjson.OPT_INDENT_2))
    else:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(chunk_dicts, f, indent=2, ensure_ascii=False)

    print(f"\nSaved {len(chunks)} chunks to {output_path}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Simple Tree-sitter code chunker"
    )
    parser.add_argument(
        "repo_path",
        type=str,
        help="Path to repository"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="chunks.json",
        help="Output JSON file (default: chunks.json)"
    )

    args = parser.parse_args()

    repo_path = Path(args.repo_path).resolve()
    output_path = Path(args.output)

    print(f"{'='*60}")
    print("SIMPLE TREE-SITTER CHUNKER")
    print(f"{'='*60}")
    print(f"Repository: {repo_path}")
    print(f"Output: {output_path}")
    print(f"{'='*60}")

    try:
        chunker = Chunker()
        chunks = chunker.chunk_repository(repo_path)

        if chunks:
            save_chunks(chunks, output_path)
            print(f"\nSuccess! {len(chunks)} chunks saved.")
        else:
            print("\nNo chunks created. Check if repository contains code files.")

        return 0

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())