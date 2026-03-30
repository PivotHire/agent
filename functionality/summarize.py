import json
from openai import OpenAI

MAX_DIFF_CHARS = 30_000

PROMPT = """\
You are a code reviewer tracking progress on a project.

<goal>
{goal}
</goal>

<previous_summaries>
{previous_summaries}
</previous_summaries>

<diff>
{diff}
</diff>

Respond in JSON with two keys:
- "diff_summary": 3-5 bullet points on what changed, why it likely changed, and anything risky.
- "goal_summary": 1-2 sentences on how this commit moves toward (or away from) the overarching goal, referencing previous work where relevant. If no goal is set, set this to null."""


def summarize(diff, api_key, goal=None, previous_summaries=None):
    """Send a diff to GPT with goal context and return a structured summary."""
    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + "\n\n[truncated — diff exceeded 30k chars]"

    goal_text = goal or "No goal set."
    if previous_summaries:
        prev_text = "\n---\n".join(previous_summaries)
    else:
        prev_text = "No previous summaries."

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4.1-nano",
        messages=[{"role": "user", "content": PROMPT.format(
            diff=diff, goal=goal_text, previous_summaries=prev_text
        )}],
        response_format={"type": "json_object"},
    )

    result = json.loads(response.choices[0].message.content)

    diff_summary = result.get("diff_summary", "")
    if isinstance(diff_summary, list):
        diff_summary = "\n".join(f"- {item}" if not item.startswith("-") else item for item in diff_summary)

    goal_summary = result.get("goal_summary")
    if isinstance(goal_summary, list):
        goal_summary = " ".join(goal_summary)

    return {
        "diff_summary": diff_summary,
        "goal_summary": goal_summary,
    }


# --- Commented out: tool-calling and snapshot logic ---
# Requires source files on disk, which we don't have in the webhook-only workflow.
# May be re-enabled in a future version (e.g. with GitHub App repo access).
