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
            CREATE TABLE IF NOT EXISTS summaries (
                id SERIAL PRIMARY KEY,
                repo TEXT NOT NULL,
                commit_sha TEXT NOT NULL,
                author TEXT NOT NULL,
                branch TEXT NOT NULL,
                diff_summary TEXT NOT NULL,
                goal_summary TEXT,
                timestamp TIMESTAMPTZ DEFAULT now()
            );
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


async def save_summary(pool, data):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO summaries (repo, commit_sha, author, branch, diff_summary, goal_summary)
            VALUES ($1, $2, $3, $4, $5, $6)
        """, data["repo"], data["commit_sha"], data["author"],
            data["branch"], data["diff_summary"], data.get("goal_summary"))


async def get_summaries(pool, repo=None, limit=50):
    async with pool.acquire() as conn:
        if repo:
            rows = await conn.fetch(
                "SELECT * FROM summaries WHERE repo = $1 ORDER BY timestamp DESC LIMIT $2",
                repo, limit)
        else:
            rows = await conn.fetch(
                "SELECT * FROM summaries ORDER BY timestamp DESC LIMIT $1",
                limit)
        return [dict(r) for r in rows]


async def get_recent_summaries(pool, repo, limit=5):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT diff_summary FROM summaries WHERE repo = $1 ORDER BY timestamp DESC LIMIT $2",
            repo, limit)
        return [r["diff_summary"] for r in rows]
