"""Append a validated-reference approval entry to archives/approvals.jsonl.

Admin-only, backend validation workflow. Testers DO NOT run this. Approvals
happen offline, after a full read of the report by the admin + Claude Code
together, against the archives branch.

Usage (from C:\\DeepDive, on main branch):
    python scripts/approve_run.py <run_id> --notes "scope caveat"
    python scripts/approve_run.py <run_id> --list-pending

The script:
  1. Fetches the latest archives branch
  2. Creates a scratch git worktree (gitignored) — you stay on main
  3. Locates the run folder matching <run_id>
  4. Reads the run's metadata for the approval entry
  5. Appends to archives/approvals.jsonl
  6. Commits + pushes the archives branch
  7. Removes the scratch worktree

Run ONLY after reading synthesis.md end-to-end. Low approval rates are a
feature — the corpus is only as trustworthy as the minimum review standard
that created it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKTREE_NAME = ".approvals_worktree"  # gitignored; cleaned up after each use


def _git(*args: str, cwd: Path | None = None, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        check=check,
        capture_output=capture,
        text=True,
    )


def _ensure_worktree() -> Path:
    """Create (or refresh) a scratch worktree for the archives branch.
    Returns the absolute path to the worktree root."""
    worktree_path = PROJECT_ROOT / WORKTREE_NAME
    worktree_path_str = str(worktree_path)

    # Fetch latest archives branch ref from remote
    _git("fetch", "origin", "archives", cwd=PROJECT_ROOT)

    # If an old worktree exists, nuke it to guarantee clean state
    if worktree_path.exists():
        try:
            _git("worktree", "remove", worktree_path_str, "--force", cwd=PROJECT_ROOT, check=False)
        except Exception:
            pass

    # Create a fresh worktree at the current archives branch tip
    _git("worktree", "add", worktree_path_str, "origin/archives", cwd=PROJECT_ROOT)
    # Detach and switch to a branch tracking origin/archives so we can push
    _git("checkout", "-B", "archives", "origin/archives", cwd=worktree_path)

    return worktree_path


def _cleanup_worktree() -> None:
    worktree_path = PROJECT_ROOT / WORKTREE_NAME
    if not worktree_path.exists():
        return
    _git("worktree", "remove", str(worktree_path), "--force", cwd=PROJECT_ROOT, check=False)


def _find_run_folder(worktree: Path, run_id: str) -> Path | None:
    archives_root = worktree / "archives"
    if not archives_root.exists():
        return None

    m = re.match(r"(\d{4}-\d{2}-\d{2})_(\d{6})_(.+)", run_id)
    if m:
        date, time_str, slug = m.group(1), m.group(2), m.group(3)
        candidate = archives_root / date / f"{slug}_{time_str}"
        if candidate.exists():
            return candidate
        # Slug truncated — find by time suffix under matching date dir
        date_dir = archives_root / date
        if date_dir.exists():
            for d in date_dir.iterdir():
                if d.is_dir() and d.name.endswith(f"_{time_str}"):
                    return d

    # Generic fallback
    for p in archives_root.rglob("*"):
        if p.is_dir() and run_id.split("_")[-1] in p.name:
            return p
    return None


def _read_run_metadata(run_folder: Path) -> dict:
    meta: dict = {}

    state_path = run_folder / "state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            meta["topic"] = state.get("raw_topic") or state.get("topic")
            meta["anchor_event"] = state.get("anchor_event")
        except Exception as exc:
            meta["state_read_error"] = str(exc)

    qc_path = run_folder / "parser_qc.json"
    if qc_path.exists():
        try:
            qc = json.loads(qc_path.read_text(encoding="utf-8"))
            pr = qc.get("parse_result", {})
            meta["mode"] = pr.get("mode")
            meta["domain"] = pr.get("domain")
            meta["subdomain"] = pr.get("subdomain")
            meta["anchor_year"] = pr.get("anchor_year")
            if not meta.get("topic"):
                meta["topic"] = qc.get("raw_topic")
        except Exception as exc:
            meta["qc_read_error"] = str(exc)

    return meta


def _already_approved(worktree: Path, run_id: str) -> dict | None:
    approvals_path = worktree / "archives" / "approvals.jsonl"
    if not approvals_path.exists():
        return None
    for line in approvals_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("run_id") == run_id and not entry.get("revoked_at"):
            return entry
    return None


def _list_pending(worktree: Path) -> None:
    """Print all runs in the archive that don't yet have an approval entry."""
    archives_root = worktree / "archives"
    approvals_path = archives_root / "approvals.jsonl"

    approved_ids = set()
    if approvals_path.exists():
        for line in approvals_path.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
                if not e.get("revoked_at"):
                    approved_ids.add(e["run_id"])
            except Exception:
                continue

    # Walk archives/<date>/<run-folder>/
    pending: list[tuple[str, str, str, str]] = []  # (run_id, topic, mode, run_path)
    for date_dir in sorted(archives_root.iterdir(), reverse=True):
        if not date_dir.is_dir() or not re.match(r"\d{4}-\d{2}-\d{2}", date_dir.name):
            continue
        for run_dir in sorted(date_dir.iterdir()):
            if not run_dir.is_dir():
                continue
            # Reconstruct run_id from folder name: slug_HHMMSS → date_HHMMSS_slug[:40]
            m = re.match(r"(.+)_(\d{6})$", run_dir.name)
            if not m:
                continue
            slug, time_str = m.group(1), m.group(2)
            # The saved run_id in runs.jsonl is exactly this form:
            run_id = f"{date_dir.name}_{time_str}_{slug[:40]}"
            if run_id in approved_ids:
                continue
            meta = _read_run_metadata(run_dir)
            pending.append((run_id, meta.get("topic") or "(no topic)", meta.get("mode") or "?", str(run_dir.relative_to(worktree))))

    if not pending:
        print("No pending reviews. Either nothing archived, or everything's approved.")
        return

    print(f"Pending review ({len(pending)} runs):\n")
    for run_id, topic, mode, path in pending:
        print(f"  [{mode:10}] {run_id}")
        print(f"              topic: {topic}")
        print(f"              path:  {path}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("run_id", nargs="?", help="Run ID from runs.jsonl (date_time_slug form)")
    parser.add_argument("--notes", default="", help="Scope caveats for this approval")
    parser.add_argument("--approver", default=os.getenv("USER") or os.getenv("USERNAME") or "admin",
                        help="Approver name (defaults to $USER / $USERNAME)")
    parser.add_argument("--list-pending", action="store_true",
                        help="List runs that haven't been reviewed yet, then exit")
    parser.add_argument("--allow-any-mode", action="store_true",
                        help="Override the historical-only restriction (use with care)")
    parser.add_argument("--keep-worktree", action="store_true",
                        help="Don't clean up the scratch worktree (for debugging)")
    args = parser.parse_args()

    if not args.list_pending and not args.run_id:
        parser.error("Provide a run_id, or use --list-pending")

    try:
        worktree = _ensure_worktree()
    except subprocess.CalledProcessError as exc:
        print(f"ERROR: failed to set up worktree. {exc}", file=sys.stderr)
        sys.exit(2)

    try:
        if args.list_pending:
            _list_pending(worktree)
            return

        run_folder = _find_run_folder(worktree, args.run_id)
        if run_folder is None:
            print(f"ERROR: could not locate a run matching run_id={args.run_id!r}", file=sys.stderr)
            print(f"Looked under {worktree / 'archives'}", file=sys.stderr)
            print("Tip: run with --list-pending to see what's in the archive.", file=sys.stderr)
            sys.exit(1)

        meta = _read_run_metadata(run_folder)
        mode = meta.get("mode")

        if not args.allow_any_mode and mode != "historical":
            print(
                f"ERROR: run is mode={mode!r}. Approval is restricted to historical-mode "
                "runs — current/recent/breaking aren't stable enough to cache as validated "
                "references. Override with --allow-any-mode if you really mean it.",
                file=sys.stderr,
            )
            sys.exit(1)

        existing = _already_approved(worktree, args.run_id)
        if existing:
            print(
                f"Already approved at {existing.get('approved_at')}. "
                f"Approval ID: {existing.get('approval_id')}. Skipping."
            )
            return

        approved_at = datetime.now(timezone.utc).isoformat()
        approval_id = hashlib.sha256(
            f"{args.run_id}|{approved_at}|{args.approver}".encode()
        ).hexdigest()[:16]

        entry = {
            "approval_id": approval_id,
            "run_id": args.run_id,
            "approved_at": approved_at,
            "approver": args.approver,
            "topic": meta.get("topic"),
            "mode": mode,
            "domain": meta.get("domain"),
            "subdomain": meta.get("subdomain"),
            "anchor_event": meta.get("anchor_event"),
            "anchor_year": meta.get("anchor_year"),
            "run_path": str(run_folder.relative_to(worktree)).replace("\\", "/"),
            "notes": args.notes,
        }

        approvals_path = worktree / "archives" / "approvals.jsonl"
        approvals_path.parent.mkdir(parents=True, exist_ok=True)
        with open(approvals_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

        # Commit + push
        _git("add", "archives/approvals.jsonl", cwd=worktree)
        _git("-c", "user.name=approver",
             "-c", f"user.email={args.approver}@deepdive.local",
             "commit", "-m", f"Approve run {args.run_id}", cwd=worktree)
        _git("push", "origin", "archives", cwd=worktree)

        print(f"✓ Approval recorded and pushed to origin/archives")
        print(f"  approval_id : {approval_id}")
        print(f"  run_id      : {args.run_id}")
        print(f"  topic       : {meta.get('topic')}")
        print(f"  mode        : {mode}")
        print(f"  notes       : {args.notes or '(none)'}")
    finally:
        if not args.keep_worktree:
            _cleanup_worktree()


if __name__ == "__main__":
    main()
