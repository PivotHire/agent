import uuid
import asyncpg


async def create_pool(database_url):
    return await asyncpg.create_pool(database_url)

async def init_db(pool):
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS goals (
                id SERIAL PRIMARY KEY,
                repo TEXT NOT NULL UNIQUE,
                goal TEXT NOT NULL,
                updated_at TIMESTAMPTZ DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS checkpoints (
                id SERIAL PRIMARY KEY,
                repo TEXT NOT NULL,
                type TEXT NOT NULL CHECK (type IN ('pr', 'push')),
                pr_number INTEGER,
                pr_title TEXT,
                commit_sha TEXT NOT NULL,
                author TEXT NOT NULL,
                branch TEXT NOT NULL,
                diff_summary TEXT,
                goal_summary TEXT,
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now(),
                UNIQUE (repo, type, pr_number)
            );
            CREATE TABLE IF NOT EXISTS repo_tokens (
                id SERIAL PRIMARY KEY,
                token TEXT NOT NULL UNIQUE,
                repo TEXT NOT NULL,
                label TEXT,
                created_at TIMESTAMPTZ DEFAULT now(),
                expires_at TIMESTAMPTZ
            );
            CREATE INDEX IF NOT EXISTS idx_repo_tokens_token
                ON repo_tokens (token);
        """)


async def set_goal(pool, repo, goal):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO goals (repo, goal, updated_at)
            VALUES ($1, $2, now())
            ON CONFLICT (repo) DO UPDATE SET goal = $2, updated_at = now()
        """, repo, goal)


async def get_goal(pool, repo):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT goal FROM goals WHERE repo = $1", repo)
        return row["goal"] if row else None


async def upsert_checkpoint(pool, data):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO checkpoints (repo, type, pr_number, pr_title, commit_sha, author, branch, diff_summary, goal_summary)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (repo, type, pr_number) DO UPDATE
                SET diff_summary = EXCLUDED.diff_summary,
                    goal_summary = EXCLUDED.goal_summary,
                    pr_title = EXCLUDED.pr_title,
                    commit_sha = EXCLUDED.commit_sha,
                    author = EXCLUDED.author,
                    branch = EXCLUDED.branch,
                    updated_at = now()
            RETURNING id
        """, data["repo"], data["type"], data.get("pr_number"),
            data.get("pr_title"), data["commit_sha"], data["author"],
            data["branch"], data.get("diff_summary"), data.get("goal_summary"))
        return row["id"]


async def get_checkpoints(pool, repo=None, limit=50):
    async with pool.acquire() as conn:
        if repo:
            rows = await conn.fetch(
                "SELECT * FROM checkpoints WHERE repo = $1 ORDER BY updated_at DESC LIMIT $2",
                repo, limit)
        else:
            rows = await conn.fetch(
                "SELECT * FROM checkpoints ORDER BY updated_at DESC LIMIT $1",
                limit)
        return [dict(r) for r in rows]


async def get_recent_summaries(pool, repo, limit=5):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT diff_summary FROM checkpoints WHERE repo = $1 ORDER BY updated_at DESC LIMIT $2",
            repo, limit)
        return [r["diff_summary"] for r in rows]


async def get_checkpoints_by_ids(pool, checkpoint_ids):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM checkpoints WHERE id = ANY($1) ORDER BY updated_at DESC",
            checkpoint_ids)
        return [dict(r) for r in rows]


# --- Repo token management ---

async def create_repo_token(pool, repo, label=None, expires_at=None):
    token = uuid.uuid4().hex
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO repo_tokens (token, repo, label, expires_at)
               VALUES ($1, $2, $3, $4)""",
            token, repo, label, expires_at,
        )
    return {"token": token, "repo": repo, "label": label}


async def validate_repo_token(pool, token):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT repo FROM repo_tokens
               WHERE token = $1
                 AND (expires_at IS NULL OR expires_at > now())""",
            token,
        )
        return row["repo"] if row else None


async def list_repo_tokens(pool, repo=None):
    async with pool.acquire() as conn:
        if repo:
            rows = await conn.fetch(
                "SELECT id, token, repo, label, created_at, expires_at FROM repo_tokens WHERE repo = $1 ORDER BY created_at DESC",
                repo)
        else:
            rows = await conn.fetch(
                "SELECT id, token, repo, label, created_at, expires_at FROM repo_tokens ORDER BY created_at DESC")
        return [dict(r) for r in rows]


async def revoke_repo_token(pool, token):
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM repo_tokens WHERE token = $1", token)
        return result == "DELETE 1"
