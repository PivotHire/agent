import os
import datetime
import requests
from google import genai

MAX_DIFF_CHARS = 30_000


def get_diff():
    diff = os.environ.get("DIFF", "")
    if not diff:
        return None
    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + "\n\n[truncated — diff exceeded 30k chars]"
    return diff


def summarize(diff):
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    prompt = f"""Summarize this git diff in 3-5 bullet points.
Focus on: what changed, why it likely changed, and anything risky.
Be concise.

<diff>
{diff}
</diff>"""
    response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
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
        summary = summarize(diff)
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
