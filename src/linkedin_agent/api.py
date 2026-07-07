from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from linkedin_agent.graph import build_graph
from linkedin_agent.storage.supabase_client import SupabaseClient

app = FastAPI(title="LinkedIn Content Agent", version="0.1.0")
_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


class GenerateRequest(BaseModel):
    topic: str
    content_pillar: str = ""


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


DRAFTS_TABLE = "drafts"


def _drafts_client() -> SupabaseClient:
    return SupabaseClient()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/warmup")
async def warmup():
    get_graph().invoke({
        "topic": "warmup",
        "search_results": "",
        "draft": None,
        "authenticity_result": None,
        "retry_count": 0,
        "flagged_for_manual": False,
        "authenticity_feedback": "",
    })
    return {"status": "warmed"}


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
        result = get_graph().invoke(initial)
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

    client = _drafts_client()
    idea = client.find_one("ideas", {"id": req.idea_id})
    if not idea:
        raise HTTPException(404, f"Idea {req.idea_id} not found")

    top_angles = run_brainstorm(idea)
    return BrainstormResponse(angles=top_angles, idea_id=req.idea_id)


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


REVIEW_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Review Drafts — LinkedIn Content Agent</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Oxygen,Ubuntu,sans-serif;background:#f5f5f5;color:#1a1a1a;padding:24px;max-width:720px;margin:0 auto}
h1{font-size:1.5rem;font-weight:600;margin-bottom:24px;display:flex;align-items:center;gap:8px}
h1 span{font-size:.875rem;font-weight:400;color:#666;background:#eee;padding:2px 10px;border-radius:12px}
.empty{text-align:center;padding:64px 24px;color:#888;font-size:1.1rem}
.empty p{margin-top:8px;font-size:.9rem;color:#aaa}
.card{background:#fff;border-radius:12px;box-shadow:0 1px 4px rgba(0,0,0,.08);padding:20px;margin-bottom:16px;transition:opacity .2s,transform .2s}
.card.removing{opacity:0;transform:translateY(-8px)}
.card-header{display:flex;align-items:center;gap:8px;margin-bottom:12px;flex-wrap:wrap}
.badge{font-size:.75rem;font-weight:500;padding:2px 10px;border-radius:10px;background:#eee;color:#555}
.badge.pillar{background:#e8f0fe;color:#1a73e8}
.badge.auth-pass{background:#e6f4ea;color:#137333}
.badge.auth-fail{background:#fce8e6;color:#c5221f}
.badge.flagged{background:#fef7e0;color:#ea8600}
.badge.status{background:#e8f0fe;color:#1a73e8}
.card-body{font-size:.95rem;line-height:1.6;white-space:pre-wrap;color:#333;margin-bottom:16px;max-height:300px;overflow-y:auto;padding:12px;background:#fafafa;border-radius:8px;border:1px solid #eee}
.card-actions{display:flex;gap:8px;flex-wrap:wrap}
.btn{font-size:.875rem;font-weight:500;padding:8px 18px;border-radius:8px;border:none;cursor:pointer;transition:background .15s}
.btn:disabled{opacity:.5;cursor:not-allowed}
.btn-approve{background:#1a73e8;color:#fff}
.btn-approve:hover:not(:disabled){background:#1557b0}
.btn-approve:disabled{background:#8ab4f8}
.btn-edit{background:#5f6368;color:#fff}
.btn-edit:hover:not(:disabled){background:#3c4043}
.btn-reject{background:#d93025;color:#fff}
.btn-reject:hover:not(:disabled){background:#a50e0e}
.btn-save{background:#188038;color:#fff}
.btn-save:hover:not(:disabled){background:#137333}
.btn-cancel{background:#f1f3f4;color:#5f6368}
.btn-cancel:hover:not(:disabled){background:#e8eaed}
.edit-area{display:none;margin-top:12px}
.edit-area.open{display:block}
.edit-area textarea{width:100%;min-height:180px;padding:12px;font-family:inherit;font-size:.9rem;line-height:1.5;border:1px solid #ddd;border-radius:8px;resize:vertical;margin-bottom:8px}
.edit-actions{display:flex;gap:8px}
.toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#323232;color:#fff;padding:12px 24px;border-radius:8px;font-size:.875rem;z-index:100;animation:fadeIn .2s}
@keyframes fadeIn{from{opacity:0;transform:translateX(-50%) translateY(8px)}to{opacity:1;transform:translateX(-50%) translateY(0)}}
</style>
</head>
<body>
<h1>Draft Review <span id="count">0</span></h1>
<div id="container"><div class="empty">Loading drafts...</div></div>
<script>
const API="/api/drafts/ready";
const CONTAINER=document.getElementById("container");
const COUNT=document.getElementById("count");

async function load(){
  try{
    const r=await fetch(API);
    if(!r.ok)throw new Error(await r.text());
    const drafts=await r.json();
    render(drafts);
  }catch(e){
    CONTAINER.innerHTML=`<div class="empty">Failed to load drafts.<p>${e.message}</p></div>`;
  }
}

function render(drafts){
  if(!drafts||drafts.length===0){
    CONTAINER.innerHTML='<div class="empty">No drafts ready for review.</div>';
    COUNT.textContent="0";
    return;
  }
  COUNT.textContent=drafts.length;
  CONTAINER.innerHTML="";
  for(const d of drafts){
    const card=document.createElement("div");
    card.className="card";
    card.dataset.id=d.id;

    const pillar=d.content_pillar||"uncategorized";
    const authPassed=d.authenticity_passed;
    const flagged=d.flagged_for_manual;
    const badges=[`<span class="badge pillar">${pillar}</span>`];
    if(flagged){
      badges.push(`<span class="badge flagged">flagged</span>`);
    }else if(authPassed){
      badges.push(`<span class="badge auth-pass">authentic</span>`);
    }else{
      badges.push(`<span class="badge auth-fail">needs review</span>`);
    }

    card.innerHTML=`
      <div class="card-header">${badges.join("")}</div>
      <div class="card-body">${esc(d.draft_content)}</div>
      <div class="card-actions">
        <button class="btn btn-approve" onclick="approve(${d.id})">Approve</button>
        <button class="btn btn-edit" onclick="toggleEdit(this,${d.id})">Edit</button>
        <button class="btn btn-reject" onclick="reject(${d.id})">Reject</button>
      </div>
      <div class="edit-area" id="edit-${d.id}">
        <textarea>${esc(d.draft_content)}</textarea>
        <div class="edit-actions">
          <button class="btn btn-save" onclick="saveEdit(${d.id})">Save</button>
          <button class="btn btn-cancel" onclick="toggleEdit(null,${d.id})">Cancel</button>
        </div>
      </div>
    `;
    CONTAINER.appendChild(card);
  }
}

function esc(s){
  const d=document.createElement("div");
  d.textContent=s;
  return d.innerHTML;
}

function toggleEdit(btn,id){
  const area=document.getElementById("edit-"+id);
  area.classList.toggle("open");
}

function removeCard(id){
  const card=document.querySelector(`.card[data-id="${id}"]`);
  if(card){
    card.classList.add("removing");
    setTimeout(()=>{card.remove();updateCount();},200);
  }
}

function updateCount(){
  const cards=document.querySelectorAll(".card:not(.removing)").length;
  COUNT.textContent=cards;
  if(cards===0){
    CONTAINER.innerHTML='<div class="empty">No drafts ready for review.</div>';
  }
}

function toast(msg){
  const t=document.createElement("div");
  t.className="toast";
  t.textContent=msg;
  document.body.appendChild(t);
  setTimeout(()=>t.remove(),2000);
}

async function approve(id){
  const btn=document.querySelector(`.card[data-id="${id}"] .btn-approve`);
  if(btn)btn.disabled=true;
  try{
    const r=await fetch("/api/drafts/"+id+"/approve",{method:"POST"});
    if(!r.ok)throw new Error(await r.text());
    toast("Approved");
    removeCard(id);
  }catch(e){
    toast("Error: "+e.message);
    if(btn)btn.disabled=false;
  }
}

async function reject(id){
  const btn=document.querySelector(`.card[data-id="${id}"] .btn-reject`);
  if(btn)btn.disabled=true;
  try{
    const r=await fetch("/api/drafts/"+id+"/reject",{method:"POST"});
    if(!r.ok)throw new Error(await r.text());
    toast("Rejected");
    removeCard(id);
  }catch(e){
    toast("Error: "+e.message);
    if(btn)btn.disabled=false;
  }
}

async function saveEdit(id){
  const area=document.getElementById("edit-"+id);
  const textarea=area.querySelector("textarea");
  const content=textarea.value.trim();
  if(!content)return toast("Content cannot be empty");
  const btn=area.querySelector(".btn-save");
  if(btn)btn.disabled=true;
  try{
    const r=await fetch("/api/drafts/"+id+"/edit",{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({content}),
    });
    if(!r.ok)throw new Error(await r.text());
    toast("Saved");
    removeCard(id);
  }catch(e){
    toast("Error: "+e.message);
    if(btn)btn.disabled=false;
  }
}

load();
</script>
</body>
</html>"""


@app.get("/review", response_class=HTMLResponse)
async def review_page():
    return REVIEW_HTML
