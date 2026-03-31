# MyVastu — Project Brief

> Committed to source control. Contains shared project context for anyone working on this codebase.
> Personal learning preferences and teaching instructions live in CLAUDE.local.md (git-ignored).
> Global coding philosophy lives in ~/.claude/CLAUDE.md.

---

## What This App Does
MyVastu is a public-facing web app that helps people buying or renting an apartment evaluate its Vastu Shastra compliance. The user uploads a floor plan image, marks the north direction on it, and receives a Vastu score out of 100 with detailed per-rule feedback and improvement suggestions.

## Primary User
Someone buying or renting an apartment — not a Vastu expert. Language and feedback must be simple, warm, and easy to understand for a layperson.

---

## Core User Flow
1. User lands on home page
2. User uploads a floor plan image (JPG or PNG)
3. User marks north direction using a compass selector (N / NE / E / SE / S / SW / W / NW)
4. User clicks "Analyze"
5. Streamlit sends the image + north direction to the FastAPI backend
6. FastAPI passes image + north direction + rules to the analyzer service
7. Analyzer calls Claude vision API (raw SDK in Phase 1, LangChain in Phase 2)
8. Results returned: overall score out of 100, per-rule breakdown, improvement suggestions
9. Results displayed in Streamlit UI

---

## North Direction
**MVP:** User manually selects from a compass UI (N / NE / E / SE / S / SW / W / NW). Passed as a string to the backend.
**Post-MVP:** Auto-detect from property address using a maps API.

---

## Vastu Rules
Defined in `/vastu-rules.json` at the project root. All rules must be editable without touching application code.

Rule object structure:
```json
{
  "id": "entrance_direction",
  "name": "Entrance Direction",
  "description": "The main door should ideally face North, East, or North-East.",
  "weightage": 25,
  "what_to_look_for": "Identify the main entrance and its direction relative to the marked north.",
  "ideal": "North, East, or North-East facing entrance",
  "avoid": "South or South-West facing entrance"
}
```

Starting rules and weightages:
- Entrance direction — 25 points
- Kitchen placement — 20 points
- Master bedroom direction — 20 points
- Bathroom placement — 15 points
- Brahmasthan (center of home open) — 20 points

---

## Tech Stack

### Backend
- **FastAPI** — async Python web framework, typed, auto-generates API docs at `/docs`
- **Anthropic SDK** — used directly in Phase 1; raw prompt construction so the team understands what's happening
- **LangChain** — introduced in Phase 2 refactor for chain orchestration; chosen for natural LangGraph extension later
- **Pydantic** — data validation and schema definition; `BaseSettings` for config validation on startup
- **Python-dotenv** — environment variable management
- **Python logging** — structured logging throughout; no print statements anywhere

### Frontend (MVP)
- **Streamlit** — Python-only UI; intentionally simple so focus stays on backend quality

### Future (Post-MVP — Do Not Build Now)
- LangGraph multi-agent system
- React frontend
- PostgreSQL for persisting results
- User authentication

---

## Project Structure
```
myvastu/
├── CLAUDE.md                      ← this file (committed, shared)
├── CLAUDE.local.md                ← personal instructions (git-ignored)
├── vastu-rules.json               ← Vastu rules config, never hardcode in Python
├── .env                           ← secrets, never commit
├── .env.example                   ← committed, shows required keys without values
├── requirements.txt
├── streamlit_app.py               ← Streamlit frontend, calls FastAPI
├── app/
│   ├── main.py                    ← FastAPI app entry point, startup validation here
│   ├── api/
│   │   └── analyze.py             ← /analyze endpoint, no business logic here
│   ├── services/
│   │   └── vastu_analyzer.py      ← all AI and scoring logic lives here
│   ├── models/
│   │   └── schemas.py             ← Pydantic request/response models
│   └── core/
│       ├── config.py              ← Pydantic BaseSettings, validates env vars on startup
│       └── rules_loader.py        ← loads and validates vastu-rules.json
└── tests/
    └── test_analyze.py
```

---

## Architectural Principles

- **Separation of concerns** — API layer handles HTTP only; service layer handles AI logic; never mix them
- **Dependency injection** — use FastAPI's `Depends()` for shared resources like config and loaded rules
- **Config over code** — Vastu rules live in JSON, not Python; behavior changes without code changes
- **Typed everything** — all function signatures have type hints; all API contracts use Pydantic models
- **Fail loudly** — raise meaningful exceptions with clear messages; never silently return empty results
- **Async done right** — use `async def` for all I/O-bound operations; understand why it matters for API calls
- **Startup validation** — if `ANTHROPIC_API_KEY` or any required config is missing, fail on startup not mid-request

---

## Build Philosophy

### Build order for AI integration
1. **Phase 1 — Raw Anthropic SDK:** Construct prompts manually, parse responses manually, handle errors manually
2. **Phase 2 — LangChain refactor:** Introduce abstraction once the raw layer is understood and working

### Production signals to include
- Rate limiting per IP — public app hitting a paid API
- Input validation at the API boundary — file type, file size, north direction value
- Meaningful error messages to users — never expose stack traces
- Structured logging with appropriate levels

---

## Hard Rules — Never Do These
- Never hardcode Vastu rules in Python — always read from `vastu-rules.json`
- Never put business logic in the API route — it belongs in the service layer
- Never make Anthropic API calls in Phase 1 through LangChain — use raw SDK first
- Never add a database without being explicitly asked
- Never add authentication without being explicitly asked
- Never commit `.env` or any file containing secrets
- Never use `print()` — use `logging`

---

## Future Enhancements (Do Not Build Now)
- LangGraph multi-agent system: separate agents for room identification, rule application, and suggestion generation
- Auto north detection via maps API
- Save and share results via unique URL
- PDF report export
- User accounts and history
- React frontend with Indian aesthetic (earthy tones, warm design)