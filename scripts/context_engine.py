"""Validated, append-only repository context for cross-session continuity."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTEXT_DIR = ROOT / ".context"
SCHEMA_VERSION = "1.0"
VALID_SOURCES = frozenset({"bootstrap", "session"})
VALID_VERIFICATION_STATUSES = frozenset({"passed", "failed", "skipped", "not_run"})
ENTRY_KEYS = frozenset(
    {
        "schema_version",
        "session_id",
        "recorded_at",
        "source",
        "actor",
        "objective",
        "work_summary",
        "decisions",
        "files_changed",
        "verification",
        "blockers",
        "next_steps",
        "git",
        "redactions_applied",
    }
)

_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+"),
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|secret|password)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
)


class ContextError(RuntimeError):
    """Raised when context cannot be safely recorded or validated."""


def sanitize_text(value: str, *, max_length: int = 2000) -> tuple[str, int]:
    """Normalize context text and redact common credential shapes."""

    sanitized = " ".join(value.strip().split())
    redactions = 0
    for pattern in _SECRET_PATTERNS:
        sanitized, count = pattern.subn("[REDACTED]", sanitized)
        redactions += count
    if not sanitized:
        raise ContextError("context text cannot be empty")
    if len(sanitized) > max_length:
        raise ContextError(f"context text exceeds the {max_length}-character limit")
    return sanitized, redactions


def _sanitize_many(values: Sequence[str]) -> tuple[list[str], int]:
    sanitized: list[str] = []
    redactions = 0
    for value in values:
        item, count = sanitize_text(value)
        sanitized.append(item)
        redactions += count
    return sanitized, redactions


def parse_verification(value: str) -> dict[str, str]:
    """Parse COMMAND::STATUS::DETAILS into a validated verification record."""

    parts = value.split("::", maxsplit=2)
    if len(parts) != 3:
        raise ContextError("verification must use COMMAND::STATUS::DETAILS")
    command, command_redactions = sanitize_text(parts[0], max_length=500)
    status = parts[1].strip()
    details, details_redactions = sanitize_text(parts[2], max_length=1000)
    if status not in VALID_VERIFICATION_STATUSES:
        allowed = ", ".join(sorted(VALID_VERIFICATION_STATUSES))
        raise ContextError(f"verification status must be one of: {allowed}")
    return {
        "command": command,
        "status": status,
        "details": details,
        "_redactions": str(command_redactions + details_redactions),
    }


def _git_output(args: Sequence[str], *, root: Path) -> str:
    executable = shutil.which("git")
    if executable is None:
        raise ContextError("git is required to record repository context")
    completed = subprocess.run(  # noqa: S603
        [executable, *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def git_snapshot(root: Path) -> dict[str, Any]:
    """Capture only stable Git metadata, never diff contents."""

    try:
        branch = _git_output(("branch", "--show-current"), root=root) or "detached"
        head = _git_output(("rev-parse", "HEAD"), root=root)
        status_lines = _git_output(("status", "--short"), root=root).splitlines()
    except (OSError, subprocess.CalledProcessError) as error:
        raise ContextError("unable to capture repository Git state") from error
    return {
        "branch": branch,
        "head": head,
        "dirty": bool(status_lines),
        "changed_path_count": len(status_lines),
    }


def build_entry(
    *,
    objective: str,
    summaries: Sequence[str],
    decisions: Sequence[str] = (),
    files_changed: Sequence[str] = (),
    verifications: Sequence[str] = (),
    blockers: Sequence[str] = (),
    next_steps: Sequence[str] = (),
    source: str = "session",
    actor: str = "codex",
    root: Path = ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a context entry from explicit, evidence-backed session facts."""

    if source not in VALID_SOURCES:
        raise ContextError(f"unsupported context source: {source}")
    if not summaries:
        raise ContextError("at least one work summary is required")

    redactions = 0
    safe_objective, count = sanitize_text(objective)
    redactions += count
    safe_actor, count = sanitize_text(actor, max_length=128)
    redactions += count
    safe_summaries, count = _sanitize_many(summaries)
    redactions += count
    safe_decisions, count = _sanitize_many(decisions)
    redactions += count
    safe_files, count = _sanitize_many(files_changed)
    redactions += count
    safe_blockers, count = _sanitize_many(blockers)
    redactions += count
    safe_next_steps, count = _sanitize_many(next_steps)
    redactions += count

    safe_verifications: list[dict[str, str]] = []
    for verification in verifications:
        parsed = parse_verification(verification)
        redactions += int(parsed.pop("_redactions"))
        safe_verifications.append(parsed)

    recorded_at = now or datetime.now(UTC)
    timestamp = recorded_at.strftime("%Y%m%dT%H%M%SZ")
    return {
        "schema_version": SCHEMA_VERSION,
        "session_id": f"run_{timestamp}_{uuid4().hex[:8]}",
        "recorded_at": recorded_at.isoformat().replace("+00:00", "Z"),
        "source": source,
        "actor": safe_actor,
        "objective": safe_objective,
        "work_summary": safe_summaries,
        "decisions": safe_decisions,
        "files_changed": safe_files,
        "verification": safe_verifications,
        "blockers": safe_blockers,
        "next_steps": safe_next_steps,
        "git": git_snapshot(root),
        "redactions_applied": redactions,
    }


def validate_entry(entry: Any) -> list[str]:
    """Return every schema error instead of accepting partial context."""

    if not isinstance(entry, dict):
        return ["entry must be a JSON object"]
    errors: list[str] = []
    keys = set(entry)
    if keys != ENTRY_KEYS:
        missing = sorted(ENTRY_KEYS - keys)
        extra = sorted(keys - ENTRY_KEYS)
        if missing:
            errors.append(f"missing keys: {', '.join(missing)}")
        if extra:
            errors.append(f"unexpected keys: {', '.join(extra)}")
    if entry.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    for field in ("session_id", "recorded_at", "actor", "objective"):
        if not isinstance(entry.get(field), str) or not entry[field].strip():
            errors.append(f"{field} must be a non-empty string")
    if entry.get("source") not in VALID_SOURCES:
        errors.append("source is invalid")
    try:
        datetime.fromisoformat(str(entry.get("recorded_at", "")).replace("Z", "+00:00"))
    except ValueError:
        errors.append("recorded_at must be an ISO-8601 timestamp")
    for field in (
        "work_summary",
        "decisions",
        "files_changed",
        "blockers",
        "next_steps",
    ):
        value = entry.get(field)
        if not isinstance(value, list) or not all(
            isinstance(item, str) and bool(item.strip()) for item in value
        ):
            errors.append(f"{field} must be a list of non-empty strings")
    if isinstance(entry.get("work_summary"), list) and not entry["work_summary"]:
        errors.append("work_summary cannot be empty")
    verification = entry.get("verification")
    if not isinstance(verification, list):
        errors.append("verification must be a list")
    else:
        for index, item in enumerate(verification):
            if not isinstance(item, dict) or set(item) != {"command", "status", "details"}:
                errors.append(f"verification[{index}] has an invalid shape")
                continue
            if item["status"] not in VALID_VERIFICATION_STATUSES:
                errors.append(f"verification[{index}].status is invalid")
            if not all(isinstance(item[field], str) and item[field] for field in item):
                errors.append(f"verification[{index}] values must be non-empty strings")
    git = entry.get("git")
    expected_git_keys = {"branch", "head", "dirty", "changed_path_count"}
    if not isinstance(git, dict) or set(git) != expected_git_keys:
        errors.append("git has an invalid shape")
    elif (
        not isinstance(git["branch"], str)
        or not isinstance(git["head"], str)
        or not isinstance(git["dirty"], bool)
        or not isinstance(git["changed_path_count"], int)
        or git["changed_path_count"] < 0
    ):
        errors.append("git values have invalid types")
    if not isinstance(entry.get("redactions_applied"), int) or entry["redactions_applied"] < 0:
        errors.append("redactions_applied must be a non-negative integer")
    return errors


def load_entries(context_dir: Path = DEFAULT_CONTEXT_DIR) -> list[dict[str, Any]]:
    log_path = context_dir / "sessions.jsonl"
    if not log_path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line_number, line in enumerate(log_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            raise ContextError(f"blank JSONL record at line {line_number}")
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as error:
            raise ContextError(f"invalid JSON at line {line_number}: {error.msg}") from error
        errors = validate_entry(entry)
        if errors:
            raise ContextError(f"invalid context at line {line_number}: {'; '.join(errors)}")
        entries.append(entry)
    return entries


def render_current(entries: Sequence[dict[str, Any]]) -> str:
    """Render a compact startup view while the JSONL remains authoritative."""

    if not entries:
        return "# Current Project Context\n\nNo session context has been recorded.\n"
    latest = entries[-1]
    lines = [
        "# Current Project Context",
        "",
        "> Generated by `scripts/context_engine.py`; do not edit manually.",
        "",
        f"- Session: `{latest['session_id']}`",
        f"- Recorded: `{latest['recorded_at']}`",
        f"- Objective: {latest['objective']}",
        f"- Git: `{latest['git']['branch']}` at `{latest['git']['head'][:12]}`",
        "",
        "## Work completed",
        "",
        *(f"- {item}" for item in latest["work_summary"]),
        "",
        "## Decisions",
        "",
        *(f"- {item}" for item in latest["decisions"] or ["None recorded."]),
        "",
        "## Verification",
        "",
        *(
            f"- `{item['status']}` - `{item['command']}`: {item['details']}"
            for item in latest["verification"]
        ),
    ]
    if not latest["verification"]:
        lines.append("- No verification recorded.")
    lines.extend(
        [
            "",
            "## Blockers",
            "",
            *(f"- {item}" for item in latest["blockers"] or ["None."]),
            "",
            "## Next steps",
            "",
            *(f"- {item}" for item in latest["next_steps"] or ["None recorded."]),
            "",
            "## Recent sessions",
            "",
            *(
                f"- `{item['recorded_at']}` - {item['objective']} (`{item['session_id']}`)"
                for item in reversed(entries[-5:])
            ),
            "",
            "Full append-only history: `.context/sessions.jsonl`.",
            "",
        ]
    )
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def record_entry(entry: dict[str, Any], context_dir: Path = DEFAULT_CONTEXT_DIR) -> None:
    """Validate and append a record under a cross-process lock."""

    errors = validate_entry(entry)
    if errors:
        raise ContextError("refusing invalid context: " + "; ".join(errors))
    context_dir.mkdir(parents=True, exist_ok=True)
    lock_path = context_dir / ".write.lock"
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise ContextError(
            "another context writer is active; remove a stale .write.lock manually"
        ) from error
    try:
        os.close(lock_fd)
        entries = load_entries(context_dir)
        if any(existing["session_id"] == entry["session_id"] for existing in entries):
            raise ContextError("session_id already exists")
        entries.append(entry)
        log_content = "".join(
            json.dumps(item, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
            for item in entries
        )
        _atomic_write(context_dir / "sessions.jsonl", log_content)
        _atomic_write(context_dir / "CURRENT.md", render_current(entries))
    finally:
        lock_path.unlink(missing_ok=True)


def validate_context(context_dir: Path = DEFAULT_CONTEXT_DIR) -> int:
    entries = load_entries(context_dir)
    current_path = context_dir / "CURRENT.md"
    if entries and (
        not current_path.exists()
        or current_path.read_text(encoding="utf-8") != render_current(entries)
    ):
        raise ContextError("CURRENT.md is missing or does not match the append-only log")
    return len(entries)


def refresh_current(context_dir: Path = DEFAULT_CONTEXT_DIR) -> int:
    """Regenerate the derived current view without mutating session history."""

    entries = load_entries(context_dir)
    context_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(context_dir / "CURRENT.md", render_current(entries))
    return len(entries)


def _context_dir(value: str | None) -> Path:
    return Path(value).resolve() if value else DEFAULT_CONTEXT_DIR


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context-dir", help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command", required=True)

    record = subparsers.add_parser("record", help="append one verified session record")
    record.add_argument("--objective", required=True)
    record.add_argument("--summary", action="append", required=True)
    record.add_argument("--decision", action="append", default=[])
    record.add_argument("--file", action="append", default=[])
    record.add_argument("--verification", action="append", default=[])
    record.add_argument("--blocker", action="append", default=[])
    record.add_argument("--next-step", action="append", default=[])
    record.add_argument("--source", choices=sorted(VALID_SOURCES), default="session")
    record.add_argument("--actor", default="codex")

    show = subparsers.add_parser("show", help="show the generated current context")
    show.add_argument("--limit", type=int, default=5)
    subparsers.add_parser("validate", help="validate the full log and current view")
    subparsers.add_parser("refresh", help="regenerate CURRENT.md from the append-only log")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    context_dir = _context_dir(args.context_dir)
    try:
        if args.command == "record":
            entry = build_entry(
                objective=args.objective,
                summaries=args.summary,
                decisions=args.decision,
                files_changed=args.file,
                verifications=args.verification,
                blockers=args.blocker,
                next_steps=args.next_step,
                source=args.source,
                actor=args.actor,
            )
            record_entry(entry, context_dir)
            print(f"Recorded context session {entry['session_id']}.", flush=True)
            return 0
        if args.command == "show":
            entries = load_entries(context_dir)
            if not entries:
                print("No session context has been recorded.")
                return 0
            limit = max(1, args.limit)
            print(render_current(entries[-limit:]), end="")
            return 0
        if args.command == "refresh":
            count = refresh_current(context_dir)
            print(f"Refreshed current context from {count} session record(s).", flush=True)
            return 0
        count = validate_context(context_dir)
        print(f"Context is valid: {count} session record(s).", flush=True)
        return 0
    except ContextError as error:
        print(f"CONTEXT ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
