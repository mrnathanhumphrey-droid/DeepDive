"""Drive Orchestrator.run_analysis() directly — no Streamlit.

Usage: python scripts/headline_smoke.py "<headline>"
Logs every agent callback. Writes final state JSON to results/<slug>_smoke.json.
"""
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("smoke")

from agents.orchestrator import Orchestrator
from models.schemas import AgentType


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/headline_smoke.py '<headline>'")
        sys.exit(1)
    headline = sys.argv[1]

    log.info("=" * 72)
    log.info("SMOKE TEST: %s", headline)
    log.info("=" * 72)

    orch = Orchestrator()
    t0 = time.time()

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
    out = Path(__file__).resolve().parent.parent / "results" / f"{slug}_smoke.json"
    out.parent.mkdir(exist_ok=True)

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
