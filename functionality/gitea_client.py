import hmac
import hashlib
import httpx


class GiteaClient:
    def __init__(self, base_url: str, admin_token: str):
        self.base_url = base_url.rstrip("/")
        self.admin_token = admin_token
        self.headers = {"Authorization": f"token {admin_token}"}

    async def get_commit_diff(self, owner: str, repo: str, sha: str) -> str:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/api/v1/repos/{owner}/{repo}/git/commits/{sha}.diff",
                headers=self.headers, timeout=30.0,
            )
            resp.raise_for_status()
            return resp.text

    async def get_compare_diff(self, owner: str, repo: str,
                               before: str, after: str) -> str:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/api/v1/repos/{owner}/{repo}/compare/{before}...{after}",
                headers={**self.headers, "Accept": "text/plain"},
                timeout=30.0,
            )
            resp.raise_for_status()
            return resp.text

    async def get_pr_diff(self, owner: str, repo: str, index: int) -> str:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/api/v1/repos/{owner}/{repo}/pulls/{index}.diff",
                headers=self.headers, timeout=30.0,
            )
            resp.raise_for_status()
            return resp.text

    @staticmethod
    def verify_signature(payload_body: bytes, secret: str,
                         signature: str) -> bool:
        expected = hmac.new(
            secret.encode(), payload_body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
