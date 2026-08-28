import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.context_engine import (
    ContextError,
    build_entry,
    load_entries,
    record_entry,
    sanitize_text,
    validate_context,
)


def _initialize_git_repository(path: Path) -> None:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required for context engine tests")
    subprocess.run([git, "init", "--quiet"], cwd=path, check=True)  # noqa: S603
    subprocess.run(  # noqa: S603
        [
            git,
            "-c",
            "user.name=Context Test",
            "-c",
            "user.email=context@example.invalid",
            "commit",
            "--allow-empty",
            "--quiet",
            "-m",
            "initial",
        ],
        cwd=path,
        check=True,
    )


def test_record_is_append_only_and_current_view_is_valid(tmp_path: Path) -> None:
    _initialize_git_repository(tmp_path)
    context_dir = tmp_path / ".context"
    first = build_entry(
        objective="Build context engine",
        summaries=("Added validated append-only storage.",),
        verifications=("pytest tests/context::passed::Tests passed.",),
        root=tmp_path,
        now=datetime(2026, 8, 28, 10, 0, tzinfo=UTC),
    )
    second = build_entry(
        objective="Verify context engine",
        summaries=("Confirmed deterministic current context rendering.",),
        root=tmp_path,
        now=datetime(2026, 8, 28, 10, 1, tzinfo=UTC),
    )

    record_entry(first, context_dir)
    record_entry(second, context_dir)

    assert load_entries(context_dir) == [first, second]
    assert validate_context(context_dir) == 2
    assert second["session_id"] in (context_dir / "CURRENT.md").read_text(encoding="utf-8")


def test_secret_shapes_are_redacted() -> None:
    sanitized, redactions = sanitize_text("Used API_KEY=super-secret-value safely")

    assert "super-secret-value" not in sanitized
    assert "[REDACTED]" in sanitized
    assert redactions == 1


def test_invalid_existing_log_fails_closed(tmp_path: Path) -> None:
    context_dir = tmp_path / ".context"
    context_dir.mkdir()
    (context_dir / "sessions.jsonl").write_text('{"schema_version":"1.0"}\n', encoding="utf-8")

    with pytest.raises(ContextError, match="invalid context"):
        load_entries(context_dir)
