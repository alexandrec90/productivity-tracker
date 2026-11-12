#!/usr/bin/env python3
"""The local end-to-end tier: every test that needs this workstation rather than a runner.

Contract: `.claude/rules/local-e2e.md`. It runs every test marked `local`, which
`pyproject.toml`'s `addopts` deselects from every other run, CI's included: the Docker
stack end to end (`tests/test_e2e_stack.py`) and what needs a Windows-only package.

- exit 0 green, anything else red;
- each failure is pytest's own `FAILED <id>` line, and the same lines open
  `logs/e2e-failures.log`, overwritten every run, with the whole output below them;
- a run that executed nothing is red: a green from zero tests is a skip reported as a
  pass;
- under the scheduler (`DEVKIT_E2E` set) a skip is a failure too, printed as a `FAILED`
  line naming its reason: the checkout is the one the tests were written for.

Stdlib only, so the machine's Python can run it; pytest runs in the checkout's `.venv`
where there is one. Test ids on the command line run those alone, still inside the tier.

    python scripts/e2e.py
    python scripts/e2e.py tests/test_e2e_stack.py::test_a_click_reaches_the_host_that_waits_for_it

Tested in `tests/test_e2e.py`.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ARTIFACT = REPO_ROOT / "logs" / "e2e-failures.log"
ENV_FLAG = "DEVKIT_E2E"
MARKER = "local"
# A windowless scheduled run would otherwise hand pytest a console of its own.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# `-v` names every test as it ends: `tests/x.py::name PASSED  [ 50%]`, or
# `tests/x.py::name SKIPPED (reason)  [ 50%]`. The id has no whitespace in it.
OUTCOME = re.compile(
    r"^(?P<id>\S+::\S+) (?P<outcome>PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)"
    r"(?: \((?P<reason>.*?)\))?(?:\s+\[\s*\d+%\])?\s*$"
)


def venv_python(root: Path, fallback: str) -> str:
    """The checkout's `.venv` interpreter, else `fallback`: the venv has pytest."""
    for candidate in (root / ".venv" / "Scripts" / "python.exe", root / ".venv" / "bin" / "python"):
        if candidate.is_file():
            return str(candidate)
    return fallback


def pytest_command(python: str, named: Sequence[str] = ()) -> list[str]:
    # `-m local` after `addopts`' `-m "not local"`: pytest takes the last one.
    return [
        python,
        "-m",
        "pytest",
        *(named or ["tests"]),
        "-m",
        MARKER,
        "-v",
        "-rfE",
        "--tb=short",
        "-p",
        "no:cacheprovider",
    ]


def outcomes(output: str) -> list[tuple[str, str, str]]:
    """`(id, outcome, reason)` for every test `-v` reported, in order."""
    found = []
    for line in output.splitlines():
        match = OUTCOME.match(line.strip())
        if match:
            found.append((match["id"], match["outcome"], match["reason"] or ""))
    return found


def failure_lines(output: str) -> list[str]:
    return [line for line in output.splitlines() if line.startswith(("FAILED ", "ERROR "))]


def verdict(code: int, output: str, strict: bool) -> tuple[int, list[str]]:
    """`(exit code, lines to print after pytest's own)` for a pytest run's code and output.

    pytest prints its `FAILED` lines itself; these add the skips and the empty run.
    """
    seen = outcomes(output)
    ran = [ident for ident, outcome, _ in seen if outcome != "SKIPPED"]
    skips = [(ident, reason) for ident, outcome, reason in seen if outcome == "SKIPPED"]
    lines = [
        f"{'FAILED' if strict else 'SKIPPED'} {ident} - skipped: {reason or 'no reason'}"
        for ident, reason in skips
    ]
    if not ran:
        lines.append(f"e2e: no {MARKER} test executed, which is not a pass")
        return (code or 1), lines
    if strict and skips:
        lines.append(f"e2e: {len(skips)} test(s) skipped under the scheduled run")
        return (code or 1), lines
    return code, lines


def scheduled(env: Mapping[str, str]) -> bool:
    return bool(env.get(ENV_FLAG))


def artifact_text(output: str, lines: Sequence[str]) -> str:
    failures = [*failure_lines(output), *(line for line in lines if line.startswith("FAILED "))]
    return "\n".join([*failures, "", output])


def main(argv: Sequence[str] | None = None) -> int:
    named = sys.argv[1:] if argv is None else list(argv)
    done = subprocess.run(
        pytest_command(venv_python(REPO_ROOT, sys.executable), named),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        creationflags=NO_WINDOW,
    )
    output = (done.stdout or "") + (done.stderr or "")
    print(output, end="", flush=True)
    code, lines = verdict(done.returncode, output, scheduled(os.environ))
    for line in lines:
        print(line, flush=True)
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(artifact_text(output, lines), encoding="utf-8")
    print(f"e2e: {'green' if code == 0 else 'red'} -- {ARTIFACT.relative_to(REPO_ROOT)}")
    return code


if __name__ == "__main__":
    sys.exit(main())
