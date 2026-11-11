# TODO — Productivity Tracker

Freshly generated. These are the things the template deliberately left for you,
because guessing them wrong is worse than leaving them blank.

## Setup

- [ ] Fill in `.env` from `.env.example` (it is gitignored; nothing works without it)
- [ ] Confirm `python scripts/sync-devkit.py --list` shows a stamped `DEVKIT_VERSION`
- [ ] Set `DEVKIT_DIR` in CI so the drift check actually gates — a
      `--check` that prints "nothing to do (skipping)" is checking nothing
      (once `DEVKIT_VERSION` is stamped it fails instead of skipping; to check
      drift on a machine with no devkit clone, `pre-commit run devkit-drift`)
- [ ] Replace the placeholder DB password in `.env` (the committed one is a
      local-dev placeholder and is fine to keep local, but never reuse it remotely)

## Next

- [ ] Enable the collector at login on every PC:
      `python -m productivity_tracker.autostart enable collector`
- [ ] itopia: its row exists but stays grey until a collector reports. itopia is off the
      tailnet, so it needs a route to the server first; then `TRACKER_TASK=itopia` there
- [ ] Codex sessions: the collector reads Claude Code's files only. Codex keeps no live
      status file, so this means a process scan plus its rollout log, on a real Codex CLI
- [ ] A click through two Remote Desktop hops (the laptop, this PC, itopia): the overlay
      raises one window only, and itopia's sits inside this PC's
- [ ] Idle time per project: busy and waiting time are now recorded per day across all
      tasks (`daily_activity`); split them by task to report where agents sat idle
- [ ] Gamification ideas not built yet: a daily prompt goal with a progress bar;
      response time (how fast a yellow row is answered) with its own record;
      achievements (first 100-prompt day, 5 agents at once); a weekly summary

## Archive

<!-- Completed items move here. -->

- [x] Scoreboard: prompts per task and per day, agent time, parallel peak, streaks and
      records, and time agents waited on you

- [x] Replace the placeholder in `productivity_tracker/`: collector, API, overlay
- [x] Delete `tests/test_smoke.py` once real tests exist
