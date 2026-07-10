# Auralistic AI — LinkedIn Content Agent

An end-to-end AI pipeline that researches trending topics, scores ideas, brainstorms creative angles, and drafts authentic LinkedIn posts in your founder's voice — all surfaced through a web dashboard for human review.

No posting API. No auto-publishing. The pipeline ends at "draft ready for your eyes." You review, you edit, you post.

---

## Architecture

```
                    ┌──────────────────────────────────────┐
                    │        FastAPI (api.py)               │
                    │   Serves SPA dashboard + REST API     │
                    └──────────┬───────────────────────┬────┘
                               │                       │
                    ┌──────────▼──────────┐   ┌────────▼────────┐
                    │   LangGraph Pipelines │   │  SPA Dashboard  │
                    │  (4 orchestrators)    │   │  (index.html)   │
                    └──────────┬──────────┘   └─────────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        ▼                      ▼                      ▼
   ┌──────────┐         ┌──────────┐          ┌──────────┐
   │  Gemini  │         │  Groq    │          │  Tavily  │
   │ 2.5 Flash│         │ LLaMA 3.3│          │  Search  │
   │ (draft,  │         │ 70B      │          │  API     │
   │  check,  │         │ (scoring │          │ (research)│
   │  ideate) │         │  themes) │          └──────────┘
   └──────────┘         └──────────┘
        │                    │
        └────────┬──────────-┘
                 ▼
        ┌────────────────┐    ┌────────────────┐
        │   Supabase     │    │   Pinecone     │
        │  (PostgreSQL)  │    │  (Vector DB)   │
        │  via PostgREST │    │  (angle dedup) │
        └────────────────┘    └────────────────┘
```

---

## Features

- **Idea Generation Engine** — Scrapes Reddit, Hacker News, and GitHub alongside Tavily web search to surface trending signals, then uses Gemini to synthesize 5–8 scored ideas with hooks and frameworks.
- **5-Dimension Scoring** — Every idea is scored on originality, value to reader, authority fit, ICP relevance, and sales potential via Groq LLaMA 3.3 70B.
- **Angle Brainstorming** — Given a scored idea, Gemini generates 15–20 creative angles across 10 categories (contrarian, tutorial, vulnerable, data-driven, etc.), scored and deduplicated via Pinecone vector similarity.
- **Authentic Draft Generation** — Gemini 2.5 Flash writes drafts using a voice DNA system prompt distilled from Justin Welsh, Andrej Karpathy, and Rishabh Sethia patterns, paired with your own few-shot examples.
- **Adversarial Authenticity Checker** — Two-layer defense: regex scan against 110+ banned corporate phrases, then an adversarial Gemini pass that checks concrete detail, sentence rhythm, and generic tone. Max 2 retries, then flagged for manual rewrite.
- **Weekly Theme Clustering** — Automatically clusters high-scored angles into 2–3 weekly themes across four content pillars (build in public, technical teardown, trend commentary, ICP problem-solution).
- **Human Review Queue** — Approve, edit, or reject drafts in the SPA dashboard before posting.
- **Post-Performance Tracking** — Log impressions, profile visits, and DMs per post; view per-pillar analytics to see what actually drives business outcomes.
- **SPA Dashboard** — Full single-page application at `https://saas-posts-automation.containers.snapdeploy.app/` with zero external dependencies (inline CSS/JS).

---

## Tech Stack

| Layer | Tool | Purpose |
|---|---|---|
| Orchestration | LangGraph | State-machine pipeline for multi-stage workflows |
| LLM (Primary) | Google Gemini 2.5 Flash | Drafting, authenticity checks, idea generation, brainstorming |
| LLM (Scoring) | Groq LLaMA 3.3 70B | Idea/angle scoring, theme clustering |
| Search | Tavily API | LLM-optimized web research |
| Database | Supabase (PostgreSQL via PostgREST) | Ideas, drafts, themes, outcomes |
| Vector DB | Pinecone | Angle dedup via cosine similarity |
| Web Framework | FastAPI | REST API + SPA server |
| Signal Sources | Reddit, HN Algolia, GitHub Search | Trend discovery |

---

## Quick Start

```bash
# Clone and set up
git clone https://github.com/shoaibrasol/auralistic-linkedin-agent
cd auralistic-linkedin-agent
python -m venv venv && source venv/bin/activate
pip install -e .

# Configure API keys
cp .env.example .env
# Edit .env with your keys (Gemini, Tavily, Supabase, Groq, Pinecone)

# Run the server
uvicorn src.linkedin_agent.api:app --reload
```

Open `http://localhost:8000` for the dashboard.

---

## Required Environment Variables

| Variable | Description |
|---|---|
| `GEMINI_API_KEY` | Google Gemini API key |
| `TAVILY_API_KEY` | Tavily web search API key |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Supabase service role key (bypasses RLS) |
| `GROQ_API_KEY` | Groq API key for LLaMA inference |
| `PINECONE_API_KEY` | Pinecone vector database API key |
| `NICHE_KEYWORDS` | Comma-separated keywords for signal scraping |
| `REDDIT_SUBREDDITS` | Comma-separated subreddit names to monitor |
| `GITHUB_TOPICS` | Comma-separated GitHub topics to track |
| `GITHUB_TOKEN` | (Optional) GitHub token for higher API rate limits |

---

## Usage

### CLI

```bash
# Generate a single draft from a topic
python -m linkedin_agent draft "Building AI tools for SMBs"

# Run the full ideation pipeline (research → ideas → score)
python -m linkedin_agent ideate

# Schedule via cron (Mon/Wed/Fri)
python scripts/run_ideation.py
```

### API

| Method | Path | What it does |
|---|---|---|
| `POST` | `/generate` | Generate a draft from a topic |
| `POST` | `/ideate` | Run full ideation pipeline |
| `POST` | `/brainstorm` | Brainstorm angles for a scored idea |
| `POST` | `/api/outcomes` | Log post performance data |
| `GET` | `/api/outcomes/summary` | Per-pillar performance averages |
| `GET` | `/api/drafts/ready` | List drafts awaiting review |
| `POST` | `/api/drafts/{id}/approve` | Approve a draft |
| `POST` | `/api/drafts/{id}/edit` | Edit a draft |
| `POST` | `/api/drafts/{id}/reject` | Reject a draft |
| `GET` | `/api/stats/overview` | Dashboard counts |

### Dashboard

Navigate to `http://localhost:8000` for the full SPA — review drafts, explore ideas, log outcomes, and view per-pillar analytics.

---

## Pipeline Data Flow

### Draft Generation
```
Topic → Tavily Search → Gemini Draft (with voice DNA + few-shots)
     → Authenticity Check (banned phrases + adversarial LLM)
     → Retry (max 2) or Flag for Manual → Save to Supabase
```

### Ideation
```
Trigger → Parallel: Web Search + Reddit/HN/GitHub Signals
     → Aggregate Context → Gemini: 5-8 ideas with scores
     → Save to Supabase → Groq: 5-dimension scoring
```

### Brainstorm + Weekly Themes
```
Scored Idea → Gemini: 15-20 angles → Groq: score each
     → Pinecone: dedup → Select top 2-4
     → Cluster into weekly themes across content pillars
```

---

## Project Structure

```
src/linkedin_agent/
├── api.py              # FastAPI app — all 20 endpoints + SPA serving
├── graph.py            # LangGraph state definition + graph builder
├── config.py           # Typed env var accessors
├── banned_phrases.py   # 110+ banned corporate phrases
├── nodes/
│   ├── search_node.py      # Tavily web search
│   ├── draft_node.py       # Gemini draft generation
│   └── authenticity_node.py # Adversarial LLM check + retry loop
├── prompts/
│   ├── system_prompt.py        # Voice DNA + formatting rules
│   ├── few_shot_examples.py    # 4 example posts in founder voice
│   ├── authenticity_prompt.py  # Adversarial editor prompt
│   └── ideation_prompt.py      # Idea generation prompt
├── storage/
│   └── supabase_client.py  # REST-only Supabase CRUD client
├── ideation/
│   ├── pipeline.py  # LangGraph for idea generation
│   └── signals.py   # Reddit/HN/GitHub scrapers
├── scoring/
│   ├── rubric.py        # 5-dimension ScoreCard model
│   └── scoring_node.py  # Groq LLaMA scoring node
├── brainstorm/
│   ├── pipeline.py       # LangGraph for angle brainstorming
│   ├── brainstorm_node.py # Gemini angle generation
│   ├── angle_scorer.py   # Groq angle scoring
│   └── dedup.py          # Pinecone vector dedup
├── themes/
│   ├── pipeline.py  # LangGraph for weekly theme clustering
│   └── prompts.py   # Theme clustering prompts
└── templates/
    └── index.html   # SPA dashboard (~800 lines, zero deps)
```

---

## Docker

```bash
docker build -t linkedin-agent .
docker run -p 8000:8000 --env-file .env linkedin-agent
```

---

## Testing

```bash
pytest tests/ -v
```

47 tests across 4 test files covering graph execution, authenticity checking, review queue endpoints, and config validation.

---

## Design Philosophy

- **No posting API** — LinkedIn doesn't grant posting access to personal profiles outside their Marketing Developer Platform, and automating posts on a new account risks flagging. The human always posts manually.
- **REST-only Supabase** — No SDKs, no drivers. Supabase accessed exclusively via its PostgREST HTTP API.
- **Adversarial authenticity** — Generic LinkedIn-guru tone is the biggest risk. Two-layer defense (banned phrase regex + LLM critique) with capped retries.
- **Profile visits and DMs are the signal** — Not likes. Outcome tracking focuses on business-relevant metrics.
- **Manual feedback loop** — Score weights are adjusted manually every 2–3 weeks based on real outcome data. Automation kicks in only after 50+ posts.

---

## License

MIT
