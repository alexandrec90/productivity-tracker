# Productivity Tracker

Track my productivity and idle time relative to claude.

Generated from [devkit](https://github.com/alexandrec90/devkit)'s project
template. The agent harness in `scripts/hooks/` is vendored from there — see
`CLAUDE.md`, "Vendored agent harness".

## How it works

```text
 every PC                          one PC (Docker)              the laptop
 ─────────                         ───────────────              ──────────
 pt-collector  ── POST /snapshots ─▶  API + Postgres  ◀─ GET /state ──  pt-overlay
 reads ~/.claude/sessions/*.json      (python -m productivity_tracker)  always-on-top rows
```

- **Collector** (`pt-collector`, every PC): every 3 s it reads the session files Claude
  Code keeps in `~/.claude/sessions/<pid>.json`, one per running agent, whose `status` is
  `busy`, `waiting` (a question, a permission prompt, a dialog) or `idle`. It checks each
  pid is still the process that wrote the file, folds worktrees into their project, and
  posts the PC's whole list. It needs no hook and no wrapper around `claude`.
- **Server** (`docker compose up -d`): keeps one row per **task** and each PC's latest
  sessions. A task is either a **project** (`roguelike`): every session in that repo or
  its worktrees, on any PC. Or it is a **whole PC** (`itopia`): every session on a PC
  whose collector has `TRACKER_TASK=itopia`; those sessions count toward that row only,
  never their project's. A PC that has not reported for 30 s stops counting.
- **Overlay** (`pt-overlay`, the laptop): one row per task.

| Row | Meaning |
| --- | --- |
| yellow | an agent is waiting for you (this wins over green) |
| green | at least one agent is working |
| red | no agent is working |
| grey, no bar | the task is inactive |

Left-click a row to focus a session: a yellow row cycles through the sessions asking,
any other row through all of its sessions, working ones first. A session on the
laptop raises its terminal window. A session on another PC opens its Remote Control page
(`claude.ai/code/session_…`). Right-click toggles the task active or inactive. Drag the
header to move it.

### Scoreboard

Each row shows the prompts you typed on that task today, and below the rows a scoreboard
sets today against your best day before it:

| Column | Today's figure |
| --- | --- |
| prompts | prompts you typed, on every PC |
| agent time | time agents spent working, summed over agents: two busy for an hour is 2h |
| parallel | the most agents working at once |
| streak | consecutive days with a prompt; today without one yet does not break it |

A figure that beats its record turns gold with a star (the first day has no record to
beat). The last line is how long agents sat waiting on you today: the number to keep low.

Prompts come from Claude Code's `~/.claude/history.jsonl`; the collector sends only each
prompt's time and project, never its text, and leaves out `/commands` and `!shell` lines.
On its first run it sends the whole file, so records and streaks start with your history.
Agent time and parallel count from the day the collector starts. Days end at midnight in
`TRACKER_TIMEZONE`.

## Setup

1. **Server**, on the PC that stays on: `cp .env.example .env`, set `TRACKER_TOKEN` and
   `TRACKER_TIMEZONE`, then `docker compose up -d`. The app migrates the database on
   start. It needs no screen: a minimized or disconnected Remote Desktop session keeps it
   running, as long as you do not sign out and the PC does not sleep.
2. **Every PC** (including the server's and the laptop): clone, `uv sync`, and put
   `TRACKER_URL` (the server's address as this PC sees it, e.g.
   `http://desktop-b9fc8vp:8003`) and the same `TRACKER_TOKEN` in `.env`. Run
   `uv run pt-collector`, or have it start at login.
3. **The laptop**: `uv run pt-overlay` (a GUI entry point, so no console window).

## Development

```bash
cp .env.example .env          # then fill in the placeholders
uv sync --all-extras          # creates .venv from the committed uv.lock
# no uv? pip install -e ".[dev]" works, but resolves fresh instead of from the lock
docker compose up -d db
alembic upgrade head
python scripts/run-tests.py
```

In VS Code, `Ctrl+Shift+B` runs the default build task and the task quick-pick
(`Ctrl+Shift+P` → "Run Task") lists everything else, each with a one-line `detail`
explaining what it costs and what it touches.

## Host ports

This checkout is **slot 3** in devkit's `ports.toml`. Every published port
is its conventional base plus the slot:

| Service | Host port |
| --- | --- |
| app | 8003 |
| postgres | 5435 |

Regenerate the `.env` block for any checkout with
`python <devkit>/scripts/devkit_ports.py <checkout-name>`.

## Layout

```text
productivity_tracker/                  application code
tests/                tests
scripts/                 project scripts (Python, each with tests)
scripts/hooks/           vendored agent harness — edit upstream in devkit
.devkit.toml      the per-project harness seam (NOT vendored)
docker-compose.yml       the local stack
```

## CI

`.github/workflows/pr-gate.yml` runs lint, tests, and the harness drift check on
every PR. The drift check is only meaningful when it can see devkit — if it prints
"nothing to do (skipping)", the gate is inert and the wiring needs fixing. Locally,
where `DEVKIT_DIR` is usually unset, `pre-commit run devkit-drift --all-files` is the
same check against the devkit rev pinned in `.pre-commit-config.yaml`.

`.github/dependabot.yml` opens weekly dependency PRs, and
`.github/workflows/dependabot-automerge.yml` merges them once the gate passes —
patch/minor bumps of anything, plus majors confined to dev tooling. A major that
touches a runtime dependency is labelled `needs-manual-merge` and waits for you.

That auto-merge workflow is **vendored** from devkit, so `sync-devkit.py --check`
compares it byte-for-byte and editing it here shows up as drift. Keep the gate's title
`PR Gate`: the auto-merge workflow waits on it by name, and a rename makes the merge job
inert without turning anything red.

`.github/actions/setup-python-env/` is **yours**, by contrast. devkit shipped it through
that same channel for one release and pulled it back out when two projects turned out to
install in ways `uv sync` cannot express, so it now arrives from `templates/` as a
one-shot copy: nothing compares it, and rewriting its steps to match how this project
installs is the supported move rather than drift. What owning it costs is the other
direction — later devkit fixes to that file never reach here.
