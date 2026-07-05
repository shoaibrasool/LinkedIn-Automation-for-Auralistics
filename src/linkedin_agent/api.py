from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from linkedin_agent.graph import build_graph

app = FastAPI(title="LinkedIn Content Agent", version="0.1.0")
graph = build_graph()


class GenerateRequest(BaseModel):
    topic: str


class GenerateResponse(BaseModel):
    draft: str


class IdeateResponse(BaseModel):
    generated: int
    saved: int


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest):
    try:
        result = graph.invoke({"topic": req.topic})
        draft = result.get("draft")
        if not draft:
            raise HTTPException(500, "No draft generated")
        return GenerateResponse(draft=draft)
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
