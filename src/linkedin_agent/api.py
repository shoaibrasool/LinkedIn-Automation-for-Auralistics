from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from linkedin_agent.graph import build_graph

app = FastAPI(
    title="LinkedIn Content Agent",
    description="LangGraph pipeline that drafts LinkedIn posts from a topic",
    version="0.1.0",
)


class GenerateRequest(BaseModel):
    topic: str


class GenerateResponse(BaseModel):
    draft: str
    topic: str


@app.get("/")
def root():
    return {"status": "ok", "app": "LinkedIn Content Agent"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest):
    try:
        graph = build_graph()
        result = graph.invoke({"topic": req.topic})
        draft = result.get("draft")
        if not draft:
            raise HTTPException(status_code=500, detail="No draft generated")
        return GenerateResponse(draft=draft, topic=req.topic)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
