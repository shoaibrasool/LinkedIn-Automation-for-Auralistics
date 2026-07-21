import asyncio
import json
import logging
import os
import pathlib
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from linkedin_agent.graph import build_graph
from linkedin_agent.storage.supabase_client import SupabaseClient
from linkedin_agent.storage.task_store import TaskStore, TASKS_TABLE

logger = logging.getLogger(__name__)

REQUIRED_ENV_VARS = [
    "GEMINI_API_KEY",
    "TAVILY_API_KEY",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_KEY",
    "GROQ_API_KEY",
    "PINECONE_API_KEY",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    missing = [key for key in REQUIRED_ENV_VARS if not os.getenv(key)]
    if missing:
        msg = f"Missing required env vars at startup: {', '.join(missing)}"
        logger.critical(msg)
        raise RuntimeError(msg)
    yield


app = FastAPI(title="LinkedIn Content Agent", version="0.1.0", lifespan=lifespan)
_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


class GenerateRequest(BaseModel):
    topic: str
    content_pillar: str = ""
    hook: str = ""
    premise: str = ""


class GenerateResponse(BaseModel):
    draft_id: str
    draft: str
    authenticity_passed: bool
    flagged_for_manual: bool
    authenticity_feedback: str


class IdeateResponse(BaseModel):
    task_id: str


class BrainstormRequest(BaseModel):
    idea_id: str


class BrainstormResponse(BaseModel):
    task_id: str


class LogOutcomeRequest(BaseModel):
    draft_id: int | None = None
    topic: str = ""
    content_pillar: str = ""
    posted_at: str | None = None
    impressions: int = 0
    comments: int = 0
    profile_visits: int = 0
    dms_received: int = 0
    notes: str = ""


class OutcomeSummaryItem(BaseModel):
    pillar: str
    post_count: int
    avg_impressions: float
    avg_profile_visits: float
    avg_dms: float
    total_impressions: int
    total_profile_visits: int
    total_dms: int


class OutcomeSummaryResponse(BaseModel):
    pillars: list[OutcomeSummaryItem]
    total: int
    rows: list[dict]


DRAFTS_TABLE = "drafts"
OUTCOMES_TABLE = "post_outcomes"
IDEAS_TABLE = "ideas"
THEMES_TABLE = "weekly_themes"

TEMPLATES_DIR = pathlib.Path(__file__).parent / "templates"


def _drafts_client() -> SupabaseClient:
    return SupabaseClient()


def _outcomes_client() -> SupabaseClient:
    return SupabaseClient()


# ---------------------------------------------------------------------------
# Task tracking — SSE streaming + polling
# ---------------------------------------------------------------------------


def _make_progress_callback(task_id: str):
    """Create a progress callback that writes to the TaskStore."""
    store = TaskStore()

    def cb(step: str, message: str, progress: int):
        store.update(task_id, step=step, message=message, progress=progress)

    return cb


async def _stream_task_events(task_id: str):
    """Async generator that yields SSE events for a task until completion."""
    store = TaskStore()
    while True:
        task = store.get(task_id)
        if task is None:
            yield f"event: error\ndata: {json.dumps({'error': 'Task not found'})}\n\n"
            return

        status = task.get("status", "running")
        event = {
            "status": status,
            "step": task.get("step", ""),
            "message": task.get("message", ""),
            "progress": task.get("progress", 0),
        }
        if status == "complete" and task.get("result"):
            try:
                event["result"] = json.loads(task["result"]) if isinstance(task["result"], str) else task["result"]
            except (json.JSONDecodeError, TypeError):
                event["result"] = task.get("result")
        if status == "error":
            event["error"] = task.get("error", "")

        yield f"data: {json.dumps(event)}\n\n"

        if status in ("complete", "error", "expired"):
            return

        await asyncio.sleep(0.5)


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    store = TaskStore()
    task = store.get(task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    result = task.get("result")
    if isinstance(result, str):
        try:
            task["result"] = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            pass
    return task


@app.get("/api/tasks/{task_id}/stream")
async def task_stream(task_id: str):
    store = TaskStore()
    task = store.get(task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    return StreamingResponse(
        _stream_task_events(task_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# Health / Warmup
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/warmup")
async def warmup():
    await asyncio.to_thread(
        get_graph().invoke,
        {
            "topic": "warmup",
            "hook": "",
            "premise": "",
            "search_results": "",
            "draft": None,
            "authenticity_result": None,
            "retry_count": 0,
            "flagged_for_manual": False,
            "authenticity_feedback": "",
        },
    )
    return {"status": "warmed"}


# ---------------------------------------------------------------------------
# Generate — now task-based with progress streaming
# ---------------------------------------------------------------------------


@app.post("/generate")
async def generate(req: GenerateRequest):
    task_id = str(uuid.uuid4())
    store = TaskStore()
    store.create_task(task_id, "generate")

    async def run():
        try:
            cb = _make_progress_callback(task_id)

            cb("starting", "Starting draft generation...", 0)

            initial = {
                "topic": req.topic,
                "hook": req.hook or "",
                "premise": req.premise or "",
                "search_results": "",
                "draft": None,
                "authenticity_result": None,
                "retry_count": 0,
                "flagged_for_manual": False,
                "authenticity_feedback": "",
            }

            graph = build_graph(progress_callback=cb)
            result = await asyncio.to_thread(graph.invoke, initial)
            draft = result.get("draft")
            if not draft:
                store.update(task_id, status="error", error="No draft generated", step="error", message="No draft generated", progress=100)
                return

            auth = result.get("authenticity_result") or {}
            now = datetime.now(timezone.utc).isoformat()
            draft_doc = {
                "topic": req.topic,
                "content_pillar": req.content_pillar,
                "draft_content": draft,
                "authenticity_passed": auth.get("passed", False),
                "authenticity_feedback": auth.get("feedback", ""),
                "flagged_for_manual": result.get("flagged_for_manual", False),
                "status": "ready_for_review",
                "created_at": now,
                "reviewed_at": None,
            }
            client = _drafts_client()
            draft_id = client.insert_one(DRAFTS_TABLE, draft_doc)

            cb("saving", "Draft saved to database", 95)

            output = {
                "draft_id": draft_id,
                "draft": draft,
                "authenticity_passed": auth.get("passed", False),
                "flagged_for_manual": result.get("flagged_for_manual", False),
                "authenticity_feedback": auth.get("feedback", ""),
            }
            store.update(task_id, status="complete", result=output, step="done", message="Draft ready for review", progress=100)
        except Exception as e:
            logger.exception("Generate task failed")
            store.update(task_id, status="error", error=str(e), step="error", message=str(e), progress=100)

    asyncio.create_task(run())
    return {"task_id": task_id}


# ---------------------------------------------------------------------------
# Ideate — now task-based with progress streaming
# ---------------------------------------------------------------------------


@app.post("/ideate")
async def ideate():
    task_id = str(uuid.uuid4())
    store = TaskStore()
    store.create_task(task_id, "ideate")

    async def run():
        try:
            cb = _make_progress_callback(task_id)

            from linkedin_agent.ideation.pipeline import run_ideation

            cb("queued", "Queued ideation pipeline...", 0)

            result = await asyncio.to_thread(run_ideation, progress_callback=cb)

            saved = result.get("saved_ids", [])
            scored = result.get("scored_ids", [])

            output = {
                "generated": len(result.get("generated_ideas", [])),
                "saved": len(saved),
                "scored": len(scored),
            }
            store.update(task_id, status="complete", result=output, step="done", message=f"Done — {len(saved)} new ideas", progress=100)
        except Exception as e:
            logger.exception("Ideate task failed")
            store.update(task_id, status="error", error=str(e), step="error", message=str(e), progress=100)

    asyncio.create_task(run())
    return {"task_id": task_id}


# ---------------------------------------------------------------------------
# Brainstorm — now task-based with progress streaming
# ---------------------------------------------------------------------------


@app.post("/brainstorm")
async def brainstorm(req: BrainstormRequest):
    task_id = str(uuid.uuid4())
    store = TaskStore()
    store.create_task(task_id, "brainstorm")

    client = _drafts_client()
    idea = client.find_one("ideas", {"id": req.idea_id})
    if not idea:
        raise HTTPException(404, f"Idea {req.idea_id} not found")

    async def run():
        try:
            cb = _make_progress_callback(task_id)

            cb("starting", "Loading idea and preparing...", 0)

            from linkedin_agent.brainstorm import brainstorm as run_brainstorm

            top_angles = await asyncio.to_thread(run_brainstorm, idea, progress_callback=cb)

            output = {
                "angles": top_angles,
                "idea_id": req.idea_id,
            }
            store.update(task_id, status="complete", result=output, step="done", message=f"Done — {len(top_angles)} angles ready", progress=100)
        except Exception as e:
            logger.exception("Brainstorm task failed")
            store.update(task_id, status="error", error=str(e), step="error", message=str(e), progress=100)

    asyncio.create_task(run())
    return {"task_id": task_id}


# ---------------------------------------------------------------------------
# Outcome Tracking  (Phase 9)
# ---------------------------------------------------------------------------


@app.post("/api/outcomes")
async def log_outcome(req: LogOutcomeRequest):
    try:
        client = _outcomes_client()
        outcome_id = client.insert_one(OUTCOMES_TABLE, req.model_dump())
        return {"id": outcome_id}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/outcomes/summary", response_model=OutcomeSummaryResponse)
async def outcomes_summary():
    try:
        client = _outcomes_client()
        rows = client.find(OUTCOMES_TABLE, sort=[("created_at", -1)])
    except Exception as e:
        raise HTTPException(500, str(e))

    pillars: dict[str, dict] = {}
    for row in rows:
        pillar = row.get("content_pillar") or "Uncategorized"
        if pillar not in pillars:
            pillars[pillar] = {
                "count": 0,
                "sum_imp": 0,
                "sum_pv": 0,
                "sum_dms": 0,
            }
        pillars[pillar]["count"] += 1
        pillars[pillar]["sum_imp"] += (row.get("impressions") or 0)
        pillars[pillar]["sum_pv"] += (row.get("profile_visits") or 0)
        pillars[pillar]["sum_dms"] += (row.get("dms_received") or 0)

    items = [
        OutcomeSummaryItem(
            pillar=p,
            post_count=d["count"],
            avg_impressions=round(d["sum_imp"] / d["count"], 1),
            avg_profile_visits=round(d["sum_pv"] / d["count"], 1),
            avg_dms=round(d["sum_dms"] / d["count"], 1),
            total_impressions=d["sum_imp"],
            total_profile_visits=d["sum_pv"],
            total_dms=d["sum_dms"],
        )
        for p, d in sorted(pillars.items())
    ]
    return OutcomeSummaryResponse(pillars=items, total=len(rows), rows=rows)


class OverviewResponse(BaseModel):
    drafts_total: int
    drafts_ready: int
    ideas_total: int
    outcomes_total: int


# ---------------------------------------------------------------------------
# Human Review Queue  (Phase 8)
# ---------------------------------------------------------------------------


@app.get("/api/drafts/ready")
async def get_ready_drafts():
    client = _drafts_client()
    drafts = client.find(
        DRAFTS_TABLE,
        filter={"status": "ready_for_review"},
        sort=[("created_at", -1)],
        limit=50,
    )
    return drafts


class EditDraftRequest(BaseModel):
    content: str


@app.post("/api/drafts/{draft_id}/approve")
async def approve_draft(draft_id: int):
    client = _drafts_client()
    now = datetime.now(timezone.utc).isoformat()
    updated = client.update_one(
        DRAFTS_TABLE,
        {"id": draft_id},
        {"status": "approved", "reviewed_at": now},
    )
    if updated == 0:
        raise HTTPException(404, f"Draft {draft_id} not found")
    return {"status": "approved"}


@app.post("/api/drafts/{draft_id}/edit")
async def edit_draft(draft_id: int, req: EditDraftRequest):
    client = _drafts_client()
    now = datetime.now(timezone.utc).isoformat()
    updated = client.update_one(
        DRAFTS_TABLE,
        {"id": draft_id},
        {
            "status": "edited",
            "draft_content": req.content,
            "reviewed_at": now,
        },
    )
    if updated == 0:
        raise HTTPException(404, f"Draft {draft_id} not found")
    return {"status": "edited"}


@app.post("/api/drafts/{draft_id}/reject")
async def reject_draft(draft_id: int):
    client = _drafts_client()
    now = datetime.now(timezone.utc).isoformat()
    updated = client.update_one(
        DRAFTS_TABLE,
        {"id": draft_id},
        {"status": "rejected", "reviewed_at": now},
    )
    if updated == 0:
        raise HTTPException(404, f"Draft {draft_id} not found")
    return {"status": "rejected"}


# ---------------------------------------------------------------------------
# Listing Endpoints  (Phase 9 UI)
# ---------------------------------------------------------------------------


@app.get("/api/ideas")
async def list_ideas(status: str | None = None, sort_by: str = "created_at"):
    client = _drafts_client()
    filter_dict = {}
    if status:
        filter_dict["status"] = status
    sort = [(sort_by, -1)]
    ideas = client.find(IDEAS_TABLE, filter=filter_dict, sort=sort, limit=100)
    return ideas


@app.get("/api/ideas/{idea_id}")
async def get_idea(idea_id: int):
    client = _drafts_client()
    idea = client.find_one(IDEAS_TABLE, {"id": idea_id})
    if not idea:
        raise HTTPException(404, f"Idea {idea_id} not found")
    return idea


@app.get("/api/themes")
async def list_themes():
    client = _drafts_client()
    themes = client.find(THEMES_TABLE, sort=[("week_date", -1)], limit=50)
    return themes


@app.get("/api/drafts")
async def list_drafts(status: str | None = None, limit: int = 100):
    client = _drafts_client()
    filter_dict = {}
    if status:
        filter_dict["status"] = status
    drafts = client.find(DRAFTS_TABLE, filter=filter_dict, sort=[("created_at", -1)], limit=limit)
    return drafts


@app.get("/api/drafts/{draft_id}")
async def get_draft(draft_id: int):
    client = _drafts_client()
    draft = client.find_one(DRAFTS_TABLE, {"id": draft_id})
    if not draft:
        raise HTTPException(404, f"Draft {draft_id} not found")
    return draft


@app.get("/api/stats/overview", response_model=OverviewResponse)
async def stats_overview():
    client = _drafts_client()
    oc = _outcomes_client()
    drafts_all = client.find(DRAFTS_TABLE, limit=9999)
    drafts_ready_list = [d for d in drafts_all if d.get("status") == "ready_for_review"]
    ideas_all = client.find(IDEAS_TABLE, limit=9999)
    outcomes_all = oc.find(OUTCOMES_TABLE, limit=9999)
    return OverviewResponse(
        drafts_total=len(drafts_all),
        drafts_ready=len(drafts_ready_list),
        ideas_total=len(ideas_all),
        outcomes_total=len(outcomes_all),
    )


REDIRECT_TPL = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="0;url=/{}"></head><body><p><a href="/{}">Redirect to app</a></p></body></html>"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return (TEMPLATES_DIR / "index.html").read_text()


@app.get("/review", response_class=HTMLResponse)
async def review_redirect():
    return REDIRECT_TPL.format("#review", "#review")


@app.get("/stats", response_class=HTMLResponse)
async def stats_redirect():
    return REDIRECT_TPL.format("#stats", "#stats")
