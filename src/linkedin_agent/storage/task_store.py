from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from linkedin_agent.storage.supabase_client import SupabaseClient

TASKS_TABLE = "tasks"
MAX_AGE_SECONDS = 600


class TaskStore:
    def __init__(self) -> None:
        self._client = SupabaseClient()

    def create_task(self, task_id: str, task_type: str) -> bool:
        doc = {
            "id": task_id,
            "task_type": task_type,
            "status": "running",
            "step": "",
            "message": "Starting...",
            "progress": 0,
            "result": None,
            "error": "",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self._client.insert_one(TASKS_TABLE, doc)
            return True
        except Exception:
            return False

    def update(self, task_id: str, **kwargs: Any) -> None:
        allowed = {"status", "step", "message", "progress", "result", "error"}
        update = {k: v for k, v in kwargs.items() if k in allowed}
        if not update:
            return
        update["updated_at"] = datetime.now(timezone.utc).isoformat()
        if update.get("result") is not None and not isinstance(update["result"], str):
            import json
            update["result"] = json.dumps(update["result"])
        try:
            self._client.update_one(TASKS_TABLE, {"id": task_id}, update)
        except Exception:
            pass

    def get(self, task_id: str) -> dict[str, Any] | None:
        try:
            return self._client.find_one(TASKS_TABLE, {"id": task_id})
        except Exception:
            return None

    def get_or_create(self, task_id: str, task_type: str) -> dict[str, Any]:
        existing = self.get(task_id)
        if existing:
            return existing
        self.create_task(task_id, task_type)
        return self.get(task_id) or {"id": task_id, "status": "running", "progress": 0,
                                      "message": "Starting...", "step": "", "result": None, "error": ""}

    def cleanup_old(self) -> None:
        try:
            all_tasks = self._client.find(TASKS_TABLE, limit=500)
            now = datetime.now(timezone.utc)
            for t in all_tasks:
                created = t.get("created_at")
                if created:
                    try:
                        dt = datetime.fromisoformat(created)
                        if (now - dt).total_seconds() > MAX_AGE_SECONDS:
                            self._client.update_one(TASKS_TABLE, {"id": t["id"]}, {"status": "expired"})
                    except (ValueError, TypeError):
                        pass
        except Exception:
            pass
