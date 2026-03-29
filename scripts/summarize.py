from google import genai

MAX_DIFF_CHARS = 30_000

PROMPT = """\
You are a code reviewer. Summarize this git diff in 3-5 bullet points.
Focus on: what changed, why it likely changed, and anything risky.
Be concise.

<diff>
{diff}
</diff>"""


def summarize(diff, api_key):
    """Send a diff to Gemini and return a summary string."""
    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + "\n\n[truncated — diff exceeded 30k chars]"

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=PROMPT.format(diff=diff),
        # --- Tool calling (commented out for now — needs source files on server) ---
        # config=types.GenerateContentConfig(
        #     tools=[get_file_structure, get_function, get_context],
        #     automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=False),
        # ),
    )
    return response.text.strip()


# --- Commented out: tool-calling and snapshot logic ---
# Requires source files on disk, which we don't have in the webhook-only workflow.
# May be re-enabled in a future version (e.g. with GitHub App repo access).
#
# import re, sys, datetime, requests
# from google.genai import types
# sys.path.insert(0, os.path.dirname(__file__))
# from snapshot import build_snapshot, get_latest_snapshot, save_snapshot, diff_snapshots
# from ast_tools import get_file_structure, get_function, get_context
#
# def parse_changed_files(diff):
#     return list(set(re.findall(r"diff --git a/.+ b/(.+)", diff)))
#
# def send_to_backend(summary, metadata):
#     url = os.environ["WEBHOOK_URL"]
#     r = requests.post(url, json={**metadata, "summary": summary}, timeout=10)
#     r.raise_for_status()
#
# def main():
#     ... (old GitHub Actions entry point — replaced by FastAPI server)
