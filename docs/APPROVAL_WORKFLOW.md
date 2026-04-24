# Admin approval workflow for historical reports

This is the offline validation ritual. **Testers do not participate.** They
use the hosted app, see no approval UI, and can't mark anything as validated.

Approval is how a historical-mode report enters the trusted corpus that
Phase-2 retrieval will pull from (when we build it). Every approval is a
commitment — if you haven't read the whole report, don't approve it.

## Prereqs

- You're on `main` at `C:\DeepDive` (stay there, don't switch branches)
- `git` and `python` on PATH
- GitHub auth already configured (push access to `archives` branch)

## Workflow

### 1. Find what's pending review

```powershell
cd C:\DeepDive
python scripts/approve_run.py --list-pending
```

Lists every historical run in the archive that doesn't yet have an approval
entry. Output shows `run_id`, topic, mode, and the archive path.

### 2. Pull up the report content (we read together)

The script uses a scratch worktree internally, but for the read step we can
use `git show` directly without any checkout:

```powershell
# Replace <path> with run_path from --list-pending output:
git show origin/archives:archives/2026-04-27/<slug>_<time>/synthesis.md
git show origin/archives:archives/2026-04-27/<slug>_<time>/state.json
```

Or paste the path into the Claude Code chat; I'll read it and we can discuss.

### 3. Review end-to-end

Read the whole synthesis. Check that:

- Citations are real (pick 3, verify them out-of-band if uncertain)
- No fabrication-risk flags were smoothed over
- Causal chain links state real mechanisms (not just correlation)
- Primary sources are from the anchor era, not retrofitted
- No modern framing projected onto the historical period
- Scholarly consensus labels (consensus/contested/revisionist) match what
  you actually know about the field

**Ask yourself**: would you cite this report in a paper? In a lesson? If
either answer is "no with caveats," add those caveats as `--notes` on the
approval rather than rejecting outright. If the answer is "no, this needs
corrections," don't approve — let it stay pending or investigate the
corrections later.

### 4. Approve (if warranted)

```powershell
python scripts/approve_run.py <run_id> --notes "scope caveats here"
```

Examples:

```powershell
python scripts/approve_run.py 2026-04-27_143015_legacy_of_the_voting_rights_act `
  --notes "Scholarship through 2025; revisit if new declassified DOJ memos surface."

python scripts/approve_run.py 2026-04-27_091002_watergate_causal_chain_forward `
  --notes ""
```

The script:
1. Fetches latest `archives` branch
2. Creates a scratch worktree at `.approvals_worktree/` (gitignored)
3. Locates your run folder
4. Appends an entry to `archives/approvals.jsonl`
5. Commits + pushes to `origin/archives`
6. Removes the scratch worktree
7. Prints confirmation with the `approval_id`

**You stay on main the whole time.** No branch switching, no manual commits.

### 5. Verify the push

```powershell
git fetch origin archives
git log origin/archives --oneline -n 5
```

Your commit should appear at the top.

## Revoking an approval

If you later realize a report you approved has a real error, don't delete
the approval entry — that breaks the audit trail. Instead, append a new
entry with a `revoked_at` field referencing the original approval_id. (This
tool doesn't yet automate revocation; do it by hand in the worktree for now,
or we'll build it when needed.)

## Safety rails built in

- **Historical-mode only** by default. Attempts to approve current/recent/breaking
  runs fail with an explicit error. Override with `--allow-any-mode` if you
  really mean it (you almost never do).
- **Idempotent** — re-running against a run that's already approved is a no-op
  that just tells you the existing approval_id.
- **Self-contained entries** — each approval stores the topic, mode, path,
  and notes so the corpus is browsable without cross-referencing runs.jsonl.

## What this is NOT (yet)

- **No effect on hosted tool behavior.** The Fly container doesn't know
  about approvals yet. Approval state lives entirely in the `archives`
  branch. Phase 2 (retrieval) is when the hosted tool starts checking this
  corpus before running the pipeline.
- **No bulk approval.** One run at a time, deliberately. The whole point is
  that approval is a thoughtful act.
- **No multi-approver workflow.** Single approver (you) for the beta. If
  the tool ever needs peer-reviewer sign-off, extend `--approver` handling.
