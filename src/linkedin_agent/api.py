from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from linkedin_agent.graph import build_graph

app = FastAPI(title="LinkedIn Content Agent", version="0.1.0")
graph = build_graph()


class GenerateRequest(BaseModel):
    topic: str


class GenerateResponse(BaseModel):
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


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest):
    try:
        initial = {
            "topic": req.topic,
            "search_results": "",
            "draft": None,
            "authenticity_result": None,
            "retry_count": 0,
            "flagged_for_manual": False,
            "authenticity_feedback": "",
        }
        result = graph.invoke(initial)
        draft = result.get("draft")
        if not draft:
            raise HTTPException(500, "No draft generated")

        auth = result.get("authenticity_result") or {}
        return GenerateResponse(
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

    result = run_ideation()
    return IdeateResponse(
        generated=len(result.get("generated_ideas", [])),
        saved=len(result.get("saved_ids", [])),
    )


class BrainstormRequest(BaseModel):
    idea_id: str


@app.post("/brainstorm", response_model=BrainstormResponse)
async def brainstorm(req: BrainstormRequest):
    from linkedin_agent.brainstorm import brainstorm as run_brainstorm
    from linkedin_agent.storage.supabase_client import SupabaseClient

    client = SupabaseClient()
    idea = client.find_one("ideas", {"id": req.idea_id})
    if not idea:
        raise HTTPException(404, f"Idea {req.idea_id} not found")

    top_angles = run_brainstorm(idea)
    return BrainstormResponse(angles=top_angles, idea_id=req.idea_id)
