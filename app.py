import os
import sys
import datetime
from typing import Optional
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

# Allow importing from scripts/
sys.path.insert(0, str(Path(__file__).parent / "scripts"))
from summarize import summarize

load_dotenv()

app = FastAPI()

# In-memory storage (replaced by Postgres later)
summaries: list[dict] = []

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", os.environ.get("GEMINI_KEY", ""))
PIVOTHIRE_TOKEN = os.environ.get("PIVOTHIRE_TOKEN", "test-token")


class WebhookPayload(BaseModel):
    diff: str
    repo: str
    commit_sha: str
    author: str
    branch: str


@app.post("/webhook")
async def webhook(payload: WebhookPayload, authorization: str = Header()):
    # Validate token
    token = authorization.replace("Bearer ", "")
    if token != PIVOTHIRE_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured")

    # Summarize the diff
    summary = summarize(payload.diff, api_key=GEMINI_API_KEY)

    # Store (in-memory for now)
    entry = {
        "repo": payload.repo,
        "commit_sha": payload.commit_sha,
        "author": payload.author,
        "branch": payload.branch,
        "summary": summary,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    summaries.append(entry)

    return {"status": "ok", "summary": summary}


@app.get("/summaries")
async def get_summaries(repo: Optional[str] = None):
    if repo:
        return [s for s in summaries if s["repo"] == repo]
    return summaries
