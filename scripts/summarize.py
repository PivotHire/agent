import os
import sys
import datetime
import requests
from google import genai
from google.genai import types

sys.path.insert(0, os.path.dirname(__file__))

MAX_DIFF_CHARS = 30_000

PROMPT = """\
You are a code reviewer. Summarize this git diff in 3-5 bullet points.
Focus on: what changed, why it likely changed, and anything risky.
You have tools to look up function bodies and file structure if the diff alone is unclear.
Use them when you need more context. Be concise.

<diff>
{diff}
</diff>"""


def get_diff():
    diff = os.environ.get("DIFF", "")
    if not diff:
        return None
    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + "\n\n[truncated — diff exceeded 30k chars]"
    return diff


def summarize(diff, repo_root="."):
    from ast_tools import get_file_structure as _get_file_structure
    from ast_tools import get_function as _get_function
    from ast_tools import get_context as _get_context

    def get_file_structure(file_path: str) -> list:
        """List all top-level functions and classes in a source file.

        Args:
            file_path: File path relative to the repo root (e.g. 'src/app.py').
        """
        print(f"  [tool] get_file_structure({file_path})")
        return _get_file_structure(os.path.join(repo_root, file_path))

    def get_function(file_path: str, function_name: str) -> dict:
        """Get the full source code of a named function or class.

        Args:
            file_path: File path relative to the repo root.
            function_name: Name of the function or class to retrieve.
        """
        print(f"  [tool] get_function({file_path}, {function_name})")
        return _get_function(os.path.join(repo_root, file_path), function_name)

    def get_context(file_path: str, start_line: int, end_line: int) -> str:
        """Get raw source lines around a line range, with surrounding context.

        Args:
            file_path: File path relative to the repo root.
            start_line: First line of the range (1-based).
            end_line: Last line of the range (1-based).
        """
        print(f"  [tool] get_context({file_path}, {start_line}, {end_line})")
        return _get_context(os.path.join(repo_root, file_path), start_line, end_line)

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=PROMPT.format(diff=diff),
        config=types.GenerateContentConfig(
            tools=[get_file_structure, get_function, get_context],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=False),
        ),
    )
    return response.text.strip()


def send_to_backend(summary, metadata):
    url = os.environ["WEBHOOK_URL"]
    r = requests.post(url, json={**metadata, "summary": summary}, timeout=10)
    r.raise_for_status()


def main():
    diff = get_diff()
    if not diff:
        print("No diff — skipping.")
        summary = "No changes detected."
    else:
        print("Summarizing...")
        repo_root = os.environ.get("GITHUB_WORKSPACE", ".")
        summary = summarize(diff, repo_root)
        print(f"Summary:\n{summary}")

    metadata = {
        "repo": os.environ.get("GITHUB_REPOSITORY", "local/test"),
        "commit_sha": os.environ.get("GITHUB_SHA", "unknown"),
        "author": os.environ.get("GITHUB_ACTOR", "unknown"),
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
    }

    print("Sending to backend...")
    send_to_backend(summary, metadata)
    print("Done.")


if __name__ == "__main__":
    main()
