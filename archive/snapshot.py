import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from archive.chunker import Chunker

SNAPSHOT_FILE = "snapshots.json"

_chunker = None

def _get_chunker():
    global _chunker
    if _chunker is None:
        _chunker = Chunker()
    return _chunker


def build_snapshot(repo_path, changed_files):
    """Parse changed files and return structural summary."""
    chunker = _get_chunker()
    snapshot = {}
    for f in changed_files:
        path = Path(repo_path) / f
        if not path.is_file():
            continue
        config = chunker.should_process_file(path)
        if not config:
            continue
        chunks = chunker.chunk_file(path, config)
        snapshot[f] = [
            {"name": c.signature, "type": c.chunk_type,
             "lines": c.end_line - c.start_line + 1}
            for c in chunks if c.chunk_type != "imports_and_globals"
        ]
    return snapshot


def load_snapshots(path=SNAPSHOT_FILE):
    """Load snapshots.json, return {} if missing."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_snapshot(commit_sha, timestamp, snapshot, path=SNAPSHOT_FILE):
    """Append a snapshot entry keyed by commit SHA."""
    data = load_snapshots(path)
    data[commit_sha] = {"timestamp": timestamp, "files": snapshot}
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def get_latest_snapshot(path=SNAPSHOT_FILE):
    """Return the most recent snapshot's files dict, or {}."""
    data = load_snapshots(path)
    if not data:
        return {}
    latest_key = max(data, key=lambda k: data[k].get("timestamp", ""))
    return data[latest_key].get("files", {})


def diff_snapshots(old_files, new_files):
    """Compare two snapshots, return human-readable delta string."""
    lines = []
    all_files = sorted(set(list(old_files.keys()) + list(new_files.keys())))

    for f in all_files:
        old_funcs = {fn["name"]: fn for fn in old_files.get(f, [])}
        new_funcs = {fn["name"]: fn for fn in new_files.get(f, [])}

        if f not in old_files:
            lines.append(f"+ new file: {f} ({len(new_funcs)} functions)")
            continue
        if f not in new_files:
            lines.append(f"- deleted file: {f}")
            continue

        for name in sorted(set(new_funcs) - set(old_funcs)):
            lines.append(f"+ {f}: added {name}")
        for name in sorted(set(old_funcs) - set(new_funcs)):
            lines.append(f"- {f}: removed {name}")
        for name in sorted(set(old_funcs) & set(new_funcs)):
            old_lines = old_funcs[name]["lines"]
            new_lines = new_funcs[name]["lines"]
            if old_lines != new_lines:
                lines.append(f"~ {f}: {name} {old_lines}→{new_lines} lines")

    return "\n".join(lines)
