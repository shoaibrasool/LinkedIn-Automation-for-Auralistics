import asyncio
import logging
import os
import pathlib
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from linkedin_agent.graph import build_graph
from linkedin_agent.storage.supabase_client import SupabaseClient

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
GRAPH_INVOKE_TIMEOUT = 180


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
    generated: int
    saved: int


class BrainstormResponse(BaseModel):
    angles: list[dict]
    idea_id: str


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


@app.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest):
    try:
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
        result = await asyncio.wait_for(
            asyncio.to_thread(get_graph().invoke, initial),
            timeout=GRAPH_INVOKE_TIMEOUT,
        )
        draft = result.get("draft")
        if not draft:
            raise HTTPException(500, "No draft generated")

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

        return GenerateResponse(
            draft_id=draft_id,
            draft=draft,
            authenticity_passed=auth.get("passed", False),
            flagged_for_manual=result.get("flagged_for_manual", False),
            authenticity_feedback=auth.get("feedback", ""),
        )
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/ideate", response_model=IdeateResponse)
async def ideate():
    from linkedin_agent.ideation.pipeline import run_ideation

    asyncio.create_task(asyncio.to_thread(run_ideation))
    return IdeateResponse(generated=0, saved=0)


class BrainstormRequest(BaseModel):
    idea_id: str


@app.post("/brainstorm", response_model=BrainstormResponse)
async def brainstorm(req: BrainstormRequest):
    from linkedin_agent.brainstorm import brainstorm as run_brainstorm

    client = _drafts_client()
    idea = client.find_one("ideas", {"id": req.idea_id})
    if not idea:
        raise HTTPException(404, f"Idea {req.idea_id} not found")

    top_angles = await asyncio.to_thread(run_brainstorm, idea)
    return BrainstormResponse(angles=top_angles, idea_id=req.idea_id)


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
