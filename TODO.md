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

- [ ] Start `pt-collector` at login on every PC (Task Scheduler or the Startup folder)
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
