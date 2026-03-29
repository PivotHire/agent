import os
import sys
from typing import Optional
from pathlib import Path
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent / "scripts"))
from summarize import summarize
from db import create_pool, init_db, set_goal, get_goal, save_summary, get_summaries, get_recent_summaries

load_dotenv()

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", os.environ.get("GPT_KEY", ""))
PIVOTHIRE_TOKEN = os.environ.get("PIVOTHIRE_TOKEN", "test-token")
DATABASE_URL = os.environ.get("DATABASE_URL", "")


@asynccontextmanager
async def lifespan(app):
    app.state.pool = await create_pool(DATABASE_URL)
    await init_db(app.state.pool)
    yield
    await app.state.pool.close()


app = FastAPI(lifespan=lifespan)


# --- Request models ---

class WebhookPayload(BaseModel):
    diff: str
    repo: str
    commit_sha: str
    author: str
    branch: str


class GoalPayload(BaseModel):
    repo: str
    goal: str


# --- Endpoints ---

@app.post("/webhook")
async def webhook(payload: WebhookPayload, authorization: str = Header()):
    token = authorization.replace("Bearer ", "")
    if token != PIVOTHIRE_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured")

    pool = app.state.pool

    # Fetch goal and recent summaries for context
    goal = await get_goal(pool, payload.repo)
    recent = await get_recent_summaries(pool, payload.repo, limit=5)

    # Summarize with context
    result = summarize(payload.diff, api_key=OPENAI_API_KEY, goal=goal, previous_summaries=recent)

    # Persist
    await save_summary(pool, {
        "repo": payload.repo,
        "commit_sha": payload.commit_sha,
        "author": payload.author,
        "branch": payload.branch,
        "diff_summary": result["diff_summary"],
        "goal_summary": result.get("goal_summary"),
    })

    return {"status": "ok", **result}


@app.get("/summaries")
async def list_summaries(repo: Optional[str] = None, limit: int = 50):
    rows = await get_summaries(app.state.pool, repo=repo, limit=limit)
    return rows


@app.post("/goals")
async def upsert_goal(payload: GoalPayload, authorization: str = Header()):
    token = authorization.replace("Bearer ", "")
    if token != PIVOTHIRE_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
    await set_goal(app.state.pool, payload.repo, payload.goal)
    return {"status": "ok", "repo": payload.repo, "goal": payload.goal}


@app.get("/goals/{repo:path}")
async def read_goal(repo: str):
    goal = await get_goal(app.state.pool, repo)
    if not goal:
        raise HTTPException(status_code=404, detail="No goal set for this repo")
    return {"repo": repo, "goal": goal}
