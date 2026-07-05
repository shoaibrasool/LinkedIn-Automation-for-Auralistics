from __future__ import annotations

from urllib.parse import urlencode

import requests

from linkedin_agent.config import get_supabase_service_key, get_supabase_url


class SupabaseClient:
    def __init__(self) -> None:
        self._base_url = get_supabase_url().rstrip("/") + "/rest/v1"
        self._session = requests.Session()
        self._session.headers.update({
            "apikey": get_supabase_service_key(),
        })

    def ping(self) -> bool:
        try:
            r = self._session.get(f"{self._base_url}/", timeout=5)
            return r.status_code < 500
        except requests.RequestException:
            return False

    def find_one(self, table: str, filter: dict | None = None) -> dict | None:
        params: dict = {"select": "*", "limit": 1}
        if filter:
            for k, v in filter.items():
                params[k] = f"eq.{v}"
        r = self._session.get(
            f"{self._base_url}/{table}", params=params, timeout=10
        )
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else None

    def find(
        self,
        table: str,
        filter: dict | None = None,
        sort: list | None = None,
        limit: int = 100,
    ) -> list[dict]:
        params: dict = {"select": "*", "limit": limit}
        if filter:
            for k, v in filter.items():
                params[k] = f"eq.{v}"
        if sort:
            order = ",".join(
                f"{col}.{'desc' if direction < 0 else 'asc'}"
                for col, direction in sort
            )
            params["order"] = order
        r = self._session.get(
            f"{self._base_url}/{table}", params=params, timeout=10
        )
        r.raise_for_status()
        return r.json()

    def insert_one(self, table: str, document: dict) -> str:
        r = self._session.post(
            f"{self._base_url}/{table}",
            json=document,
            headers={"Prefer": "return=representation"},
            timeout=10,
        )
        r.raise_for_status()
        rows = r.json()
        return str(rows[0]["id"]) if rows else ""

    def insert_many(self, table: str, documents: list[dict]) -> list[str]:
        if not documents:
            return []
        r = self._session.post(
            f"{self._base_url}/{table}",
            json=documents,
            headers={"Prefer": "return=representation"},
            timeout=10,
        )
        r.raise_for_status()
        return [str(row["id"]) for row in r.json()]

    def update_one(self, table: str, filter: dict, update: dict) -> int:
        qs = urlencode({k: f"eq.{v}" for k, v in filter.items()})
        r = self._session.patch(
            f"{self._base_url}/{table}?{qs}", json=update, timeout=10
        )
        r.raise_for_status()
        result = r.json()
        return len(result) if isinstance(result, list) else 0

    def close(self) -> None:
        self._session.close()
