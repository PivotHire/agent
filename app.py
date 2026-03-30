import os
import sys
import time
import uuid
from typing import Optional
from pathlib import Path
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header
from openai import OpenAI
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent / "scripts"))
from functionality.summarize import summarize
from functionality.db import create_pool, init_db, set_goal, get_goal, upsert_checkpoint, get_checkpoints, get_recent_summaries, get_checkpoints_by_ids

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
    event_type: Optional[str] = None
    pr_number: Optional[int] = None
    pr_title: Optional[str] = None


class GoalPayload(BaseModel):
    repo: str
    goal: str


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = "gpt-4.1-nano"
    messages: list[ChatMessage]
    repo: Optional[str] = None
    checkpoint_ids: Optional[list[int]] = None


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

    # Create or update checkpoint
    event_type = payload.event_type or "push"
    checkpoint_id = await upsert_checkpoint(pool, {
        "repo": payload.repo,
        "type": event_type,
        "pr_number": payload.pr_number,
        "pr_title": payload.pr_title,
        "commit_sha": payload.commit_sha,
        "author": payload.author,
        "branch": payload.branch,
        "diff_summary": result["diff_summary"],
        "goal_summary": result.get("goal_summary"),
    })

    return {"status": "ok", "checkpoint_id": checkpoint_id, **result}


@app.post("/goals")
async def upsert_goal(payload: GoalPayload, authorization: str = Header()):
    token = authorization.replace("Bearer ", "")
    if token != PIVOTHIRE_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
    await set_goal(app.state.pool, payload.repo, payload.goal)
    return {"status": "ok", "repo": payload.repo, "goal": payload.goal}


@app.get("/checkpoints")
async def list_checkpoints(repo: Optional[str] = None, limit: int = 50):
    rows = await get_checkpoints(app.state.pool, repo=repo, limit=limit)
    return rows


@app.get("/goals/{repo:path}")
async def read_goal(repo: str):
    goal = await get_goal(app.state.pool, repo)
    if not goal:
        raise HTTPException(status_code=404, detail="No goal set for this repo")
    return {"repo": repo, "goal": goal}


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest, authorization: str = Header()):
    token = authorization.replace("Bearer ", "")
    if token != PIVOTHIRE_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured")

    pool = app.state.pool
    context_parts = []

    # Inject project goal if repo provided
    if req.repo:
        goal = await get_goal(pool, req.repo)
        if goal:
            context_parts.append(f"Project goal: {goal}")

    # Inject selected checkpoint summaries
    if req.checkpoint_ids:
        checkpoints = await get_checkpoints_by_ids(pool, req.checkpoint_ids)
        for cp in checkpoints:
            label = f"PR #{cp['pr_number']}: {cp['pr_title']}" if cp["type"] == "pr" else f"Push to {cp['branch']}"
            context_parts.append(f"[{label} by {cp['author']}]\n{cp['diff_summary']}")

    # Build system message
    if context_parts:
        system_content = (
            "You are a helpful assistant that answers questions about a software project. "
            "Use the following context to inform your answers.\n\n"
            + "\n\n---\n\n".join(context_parts)
        )
    else:
        system_content = "You are a helpful assistant that answers questions about a software project."

    # Forward to OpenAI
    openai_messages = [{"role": "system", "content": system_content}]
    for msg in req.messages:
        openai_messages.append({"role": msg.role, "content": msg.content})

    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=req.model,
        messages=openai_messages,
    )

    choice = response.choices[0]
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": choice.message.content,
                },
                "finish_reason": choice.finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        },
    }
