"""Drive Orchestrator.run_analysis() directly — no Streamlit.

Usage: python scripts/headline_smoke.py "<headline>"

Writes results to results/<YYYY-MM-DD>/<slug>_smoke.{json,md}
and mirrors the console log to logs/<YYYY-MM-DD>/<slug>_smoke.log.
"""
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Honor PERSIST_DIR env var so runs against production use the same path
# convention as the hosted dashboard. Locally defaults to project root.
_PERSIST_DIR = Path(os.getenv("PERSIST_DIR", Path(__file__).resolve().parent.parent))

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s | %(message)s"
_LOG_DATEFMT = "%H:%M:%S"

# Console handler (stdout) set up immediately so early errors are visible.
# The file handler is added once we know the headline/date for path naming.
logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT, datefmt=_LOG_DATEFMT)
log = logging.getLogger("smoke")

from agents.orchestrator import Orchestrator
from models.schemas import AgentType


def _slugify(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")
    return slug[:max_len] or "untitled"


def _attach_file_handler(headline: str, t0: float) -> Path:
    """Mirror this run's console output to logs/<date>/<slug>_smoke.log.
    Must be called after logging.basicConfig() so the root logger exists.
    Returns the log file path so the caller can log it as context."""
    run_date = datetime.fromtimestamp(t0).strftime("%Y-%m-%d")
    slug = _slugify(headline)
    log_path = _PERSIST_DIR / "logs" / run_date / f"{slug}_smoke.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATEFMT))
    handler.setLevel(logging.INFO)
    # Attach to ROOT logger so every module's logging.getLogger(__name__)
    # output lands in the file — not just the "smoke" logger.
    logging.getLogger().addHandler(handler)
    return log_path


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/headline_smoke.py '<headline>'")
        sys.exit(1)
    headline = sys.argv[1]
    t0 = time.time()

    log_path = _attach_file_handler(headline, t0)

    log.info("=" * 72)
    log.info("SMOKE TEST: %s", headline)
    log.info("Log mirrored to %s", log_path)
    log.info("=" * 72)

    orch = Orchestrator()

    def on_progress(agent_type, result):
        elapsed = int(time.time() - t0)
        log.info(
            "[+%03ds] %-18s conf=%.2f | %s",
            elapsed,
            agent_type.value if hasattr(agent_type, "value") else str(agent_type),
            getattr(result, "confidence", 0.0),
            (getattr(result, "sub_topic", "") or "")[:90],
        )

    # Match dashboard flow: engineer_prompt first (adds HISTORICAL_ANCHOR /
    # ANCHOR_EVENT / RECENCY_FLAG prefixes that route run_analysis), then
    # hand the engineered topic to run_analysis.
    try:
        engineered = orch.engineer_prompt(headline)
        log.info("Engineered topic header:\n%s",
                 "\n".join(engineered.splitlines()[:6]))
        pr = getattr(orch, "last_parse_result", None)
        if pr:
            log.info("ParseResult: mode=%s anchor_year=%s domain=%s subdomain=%s",
                     pr.mode, pr.anchor_year, pr.domain, pr.subdomain)
    except Exception as e:
        log.exception("engineer_prompt failed: %s", e)
        sys.exit(2)

    try:
        state = orch.run_analysis(engineered, progress_callback=on_progress)
    except Exception as e:
        log.exception("run_analysis failed: %s", e)
        sys.exit(2)

    total = int(time.time() - t0)
    log.info("=" * 72)
    log.info("Completed in %ds", total)

    # Resolution-chain diagnostics — the thing we actually care about
    try:
        diag = orch.resolution_chain.diagnostics
        log.info("Resolution chain diagnostics: %s", json.dumps(diag, indent=2))
    except Exception as e:
        log.warning("Could not pull diagnostics: %s", e)

    # Persist the state so we can inspect afterwards
    slug = (
        "".join(c if c.isalnum() else "_" for c in headline.lower())[:60].strip("_")
    )
    # Results organized by date (YYYY-MM-DD/) so the folder doesn't accumulate
    # into a flat mess over time. Use run-start date, not save date, so a run
    # that crosses midnight stays grouped under when it started.
    run_date = datetime.fromtimestamp(t0).strftime("%Y-%m-%d")
    out = _PERSIST_DIR / "results" / run_date / f"{slug}_smoke.json"
    out.parent.mkdir(parents=True, exist_ok=True)

    def _safe(obj):
        try:
            return json.loads(json.dumps(obj, default=lambda o: getattr(o, "__dict__", str(o))))
        except Exception:
            return str(obj)

    with open(out, "w", encoding="utf-8") as f:
        json.dump(
            {
                "headline": headline,
                "started_at": datetime.fromtimestamp(t0).isoformat(),
                "elapsed_s": total,
                "state_keys": list(state.keys()) if isinstance(state, dict) else None,
                "state": _safe(state),
            },
            f,
            indent=2,
            default=str,
        )
    log.info("State saved to %s", out)

    # Also write the synthesis as a standalone .md for easy viewing
    if isinstance(state, dict) and state.get("synthesis"):
        md_path = out.with_suffix(".md")
        md_path.write_text(state["synthesis"], encoding="utf-8")
        log.info("Report saved to %s", md_path)


if __name__ == "__main__":
    main()
