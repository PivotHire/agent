import os
import time
import uuid
import logging
from typing import Optional
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header, Request
from openai import OpenAI
from pydantic import BaseModel

from functionality.summarize import summarize
from functionality.gitea_client import GiteaClient
from functionality.db import (
    create_pool, init_db,
    set_goal, get_goal,
    upsert_checkpoint, get_checkpoints, get_recent_summaries, get_checkpoints_by_ids,
    create_repo_token, validate_repo_token, list_repo_tokens, revoke_repo_token,
)

load_dotenv()

logger = logging.getLogger("ph-agent")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", os.environ.get("GPT_KEY", ""))
ADMIN_TOKEN = os.environ.get("PIVOTHIRE_TOKEN", "test-token")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
GITEA_URL = os.environ.get("GITEA_URL", "")
GITEA_TOKEN = os.environ.get("GITEA_TOKEN", "")
GITEA_WEBHOOK_SECRET = os.environ.get("GITEA_WEBHOOK_SECRET", "")


def _verify_admin(authorization: str):
    token = authorization.replace("Bearer ", "")
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid admin token")


@asynccontextmanager
async def lifespan(app):
    app.state.pool = await create_pool(DATABASE_URL)
    await init_db(app.state.pool)
    app.state.gitea = GiteaClient(GITEA_URL, GITEA_TOKEN)
    yield
    await app.state.pool.close()


app = FastAPI(lifespan=lifespan)

ZERO_SHA = "0" * 40


# --- Request models ---

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


class RepoTokenRequest(BaseModel):
    repo: str
    label: Optional[str] = None
    expires_at: Optional[str] = None


# --- Gitea webhook ---

@app.post("/webhook/gitea")
async def gitea_webhook(request: Request):
    body = await request.body()

    # Verify HMAC signature if secret is configured
    if GITEA_WEBHOOK_SECRET:
        signature = request.headers.get("X-Gitea-Signature", "")
        if not GiteaClient.verify_signature(body, GITEA_WEBHOOK_SECRET, signature):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    if not OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured")

    event = request.headers.get("X-Gitea-Event", "")
    payload = await request.json()
    pool = app.state.pool
    gitea: GiteaClient = app.state.gitea

    repo_full = payload["repository"]["full_name"]  # "owner/repo"
    owner, repo_name = repo_full.split("/", 1)

    if event == "push":
        before = payload.get("before", ZERO_SHA)
        after = payload.get("after", ZERO_SHA)
        ref = payload.get("ref", "")
        branch = ref.removeprefix("refs/heads/")
        author = payload.get("pusher", {}).get("login", "unknown")

        # Fetch diff from Gitea API
        if before == ZERO_SHA:
            # New branch / initial push — fetch individual commit diffs
            parts = []
            for c in payload.get("commits", []):
                try:
                    parts.append(await gitea.get_commit_diff(owner, repo_name, c["id"]))
                except Exception:
                    logger.warning("Failed to fetch diff for commit %s", c["id"])
            diff = "\n".join(parts)
        else:
            diff = await gitea.get_compare_diff(owner, repo_name, before, after)

        event_type = "push"
        pr_number = None
        pr_title = None
        commit_sha = after

    elif event == "pull_request":
        action = payload.get("action", "")
        if action not in ("opened", "synchronize", "reopened"):
            return {"status": "ignored", "reason": f"PR action '{action}' skipped"}

        pr = payload["pull_request"]
        pr_number = pr["number"]
        pr_title = pr.get("title", "")
        commit_sha = pr["head"]["sha"]
        branch = pr["head"]["ref"]
        author = pr.get("user", {}).get("login", "unknown")

        diff = await gitea.get_pr_diff(owner, repo_name, pr_number)
        event_type = "pr"

    else:
        return {"status": "ignored", "reason": f"Event '{event}' not handled"}

    # Summarize with context
    goal = await get_goal(pool, repo_full)
    recent = await get_recent_summaries(pool, repo_full, limit=5)
    result = summarize(diff, api_key=OPENAI_API_KEY, goal=goal, previous_summaries=recent)

    checkpoint_id = await upsert_checkpoint(pool, {
        "repo": repo_full,
        "type": event_type,
        "pr_number": pr_number,
        "pr_title": pr_title,
        "commit_sha": commit_sha,
        "author": author,
        "branch": branch,
        "diff_summary": result["diff_summary"],
        "goal_summary": result.get("goal_summary"),
    })

    return {"status": "ok", "checkpoint_id": checkpoint_id, **result}


# --- Goals (admin) ---

@app.post("/goals")
async def upsert_goal(payload: GoalPayload, authorization: str = Header()):
    _verify_admin(authorization)
    await set_goal(app.state.pool, payload.repo, payload.goal)
    return {"status": "ok", "repo": payload.repo, "goal": payload.goal}


@app.get("/goals/{repo:path}")
async def read_goal(repo: str):
    goal = await get_goal(app.state.pool, repo)
    if not goal:
        raise HTTPException(status_code=404, detail="No goal set for this repo")
    return {"repo": repo, "goal": goal}


# --- Checkpoints (admin) ---

@app.get("/checkpoints")
async def list_checkpoints(
    repo: Optional[str] = None, limit: int = 50,
    authorization: str = Header(),
):
    _verify_admin(authorization)
    rows = await get_checkpoints(app.state.pool, repo=repo, limit=limit)
    return rows


# --- Repo tokens (admin) ---

@app.post("/repo-tokens")
async def create_token(payload: RepoTokenRequest, authorization: str = Header()):
    _verify_admin(authorization)
    token_info = await create_repo_token(
        app.state.pool, payload.repo, payload.label,
    )
    return token_info


@app.get("/repo-tokens")
async def list_tokens(repo: Optional[str] = None, authorization: str = Header()):
    _verify_admin(authorization)
    return await list_repo_tokens(app.state.pool, repo=repo)


@app.delete("/repo-tokens/{token}")
async def delete_token(token: str, authorization: str = Header()):
    _verify_admin(authorization)
    ok = await revoke_repo_token(app.state.pool, token)
    if not ok:
        raise HTTPException(status_code=404, detail="Token not found")
    return {"status": "ok"}


# --- Chat completions (repo-scoped) ---

@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest, authorization: str = Header()):
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured")

    pool = app.state.pool
    token = authorization.replace("Bearer ", "")

    # Validate repo-scoped token
    allowed_repo = await validate_repo_token(pool, token)
    if not allowed_repo:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Enforce repo isolation
    effective_repo = req.repo or allowed_repo
    if effective_repo != allowed_repo:
        raise HTTPException(status_code=403, detail="Token not authorized for this repo")

    context_parts = []

    # Inject project goal
    goal = await get_goal(pool, effective_repo)
    if goal:
        context_parts.append(f"Project goal: {goal}")

    # Inject selected checkpoint summaries (must belong to same repo)
    if req.checkpoint_ids:
        checkpoints = await get_checkpoints_by_ids(pool, req.checkpoint_ids)
        for cp in checkpoints:
            if cp["repo"] != allowed_repo:
                raise HTTPException(
                    status_code=403,
                    detail=f"Checkpoint {cp['id']} does not belong to your repo",
                )
            label = (
                f"PR #{cp['pr_number']}: {cp['pr_title']}"
                if cp["type"] == "pr"
                else f"Push to {cp['branch']}"
            )
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
