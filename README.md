# DeepDive

Multi-agent news and policy analysis tool. Runs a topic through up to 27 specialist Claude agents — fact-checking, perspective mapping, primary-source lookup, causal-chain analysis, counterfactuals — then synthesizes a structured research brief.

## What it does

- **Breaking / current / recent / general**: 19-agent pipeline with live news fetch, fact-check, multi-perspective synthesis
- **Historical**: 8 additional agents (anchor verification, era context, causal chain, scholarly consensus, counterfactuals, ripple timeline, modern impact, primary sources) produce a 4-section retrospective brief
- **Headline resolution chain**: paste a headline; the app escalates through failure cache → RSS wire feeds → Twitter → Gemini grounded search → GDELT → Claude web search until it resolves
- **Correction learning**: your feedback is stored in a local ChromaDB and fed back to MetaAgent on similar future topics

## Local development

```bash
git clone <repo>
cd DeepDive
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # Mac/Linux
pip install -r requirements.txt
cp .env.example .env
# edit .env — at minimum set ANTHROPIC_API_KEY
python main.py                    # opens Streamlit at http://localhost:8501
```

Only `ANTHROPIC_API_KEY` is strictly required. Optional keys enable additional tiers:

| Key | Enables | Get it at |
|---|---|---|
| `ANTHROPIC_API_KEY` | everything | [console.anthropic.com](https://console.anthropic.com/settings/keys) |
| `GOOGLE_AI_API_KEY` | Gemini grounded search tier + fact-checker second opinion | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| `TWITTER_BEARER_TOKEN` | Twitter reverse-anchor tier for breaking news | [developer.x.com](https://developer.x.com/en/portal/dashboard) |

## Hosted deployment (Fly.io)

Scaffolding is committed: [Dockerfile](Dockerfile), [fly.toml](fly.toml), [.dockerignore](.dockerignore). Full walkthrough lives in [docs/DEPLOY.md](docs/DEPLOY.md).

Quick version:

```bash
fly launch --no-deploy              # accepts fly.toml as-is, picks a unique app name
fly secrets set ANTHROPIC_API_KEY=sk-ant-... \
                GOOGLE_AI_API_KEY=... \
                TWITTER_BEARER_TOKEN=...
fly deploy
fly certs add deepdive.yourdomain.com
```

Then point a CNAME at the Fly app in your DNS provider. For non-technical testers, front it with Cloudflare Access email-OTP so they just type an email and get a code — no passwords to share.

## Architecture

Three-phase pipeline:

1. `run_analysis()` — input parsing (pure Python, no LLM) → prompt engineering (1 Haiku call) → topic split → parallel agent dispatch (4 workers) → fact-check → synthesis
2. `run_meta_review()` — MetaAgent reads ChromaDB past corrections, critiques outputs, returns `agents_to_rerun`
3. `apply_user_corrections()` — your feedback → optimized adjustments → re-run flagged agents → store pattern in ChromaDB

## Key files

- [agents/orchestrator.py](agents/orchestrator.py) — main pipeline
- [dashboard.py](dashboard.py) — Streamlit UI
- [input_parser.py](input_parser.py) — pure-Python classifier for breaking/current/recent/historical mode
- [models/schemas.py](models/schemas.py) — Pydantic types
- [prompts/](prompts/) — agent system prompts + analysis instructions + shared directives
- [data/](data/) — JSON marker files for classification
- [services/](services/) — resolution chain (RSS, Gemini, GDELT, failure cache)

## Status

Friends-and-family beta. Not open for issues yet.
