"""The command tree and first runs end to end, in a throwaway home."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from config import REPOSITORY_ROOT
from main import build_parser

FIXTURE = REPOSITORY_ROOT / "tests" / "fixtures" / "aib" / "export.csv"


def _run(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "FINCH_HOME": str(home), "COLUMNS": "200"}
    return subprocess.run(
        [sys.executable, str(REPOSITORY_ROOT / "main.py"), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPOSITORY_ROOT,
        check=False,
    )


def _ready(home: Path, *, last4: str = "1234") -> None:
    assert _run(home, "profile", "add", "me", "--operator").returncode == 0
    assert _run(home, "init").returncode == 0
    added = _run(
        home,
        "account",
        "add",
        "aib-current",
        "--institution",
        "AIB",
        "--kind",
        "current",
        "--last4",
        last4,
    )
    assert added.returncode == 0, added.stderr


class TestCommandTree:
    def test_subcommands(self) -> None:
        action = build_parser()._subparsers._group_actions[0]  # type: ignore[union-attr]
        assert set(action.choices) == {
            "profile",
            "init",
            "account",
            "import",
            "recurring",
            "status",
            "db",
        }


class TestFirstRun:
    def test_no_roster_explains_what_to_do(self, tmp_path: Path) -> None:
        result = _run(tmp_path / "home", "status")
        assert result.returncode == 1
        assert "profile add" in result.stderr

    def test_status_before_init_says_to_init(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        assert _run(home, "profile", "add", "me", "--operator").returncode == 0
        result = _run(home, "status")
        assert result.returncode == 1
        assert "init" in result.stderr

    def test_profile_init_account_status(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        _ready(home)
        status = _run(home, "status")
        assert status.returncode == 0, status.stderr
        assert "aib-current" in status.stdout
        assert _run(home, "db", "status").returncode == 0


class TestImport:
    def test_dry_run_then_import_then_reimport(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        _ready(home)

        dry = _run(home, "import", str(FIXTURE), "--dry-run")
        assert dry.returncode == 0, dry.stderr
        assert "Would add 10 new rows" in dry.stdout
        assert "nothing written" in dry.stdout
        assert not (home / "profiles" / "me" / "sources").exists()

        first = _run(home, "import", str(FIXTURE))
        assert first.returncode == 0, first.stderr
        assert "Added 10 new rows" in first.stdout
        assert "€5,412.72" in first.stdout

        again = _run(home, "import", str(FIXTURE))
        assert again.returncode == 0, again.stderr
        assert "already imported" in again.stdout

        status = _run(home, "status")
        assert "€5,412.72" in status.stdout

    def test_file_for_another_account_is_refused(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        _ready(home, last4="9999")
        result = _run(home, "import", str(FIXTURE))
        assert result.returncode == 1
        assert "ends in 9999" in result.stderr

    def test_unrecognised_file_is_refused(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        _ready(home)
        other = tmp_path / "other.csv"
        other.write_text("Date,Amount\n2026-08-01,1.00")
        result = _run(home, "import", str(other))
        assert result.returncode == 1
        assert "No parser recognises" in result.stderr


class TestRecurring:
    def test_reports_on_an_imported_account(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        _ready(home)
        assert _run(home, "import", str(FIXTURE)).returncode == 0
        result = _run(home, "recurring")
        assert result.returncode == 0, result.stderr
        assert "No recurring payments found yet" in result.stdout

    def test_account_without_transactions_is_refused(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        _ready(home)
        result = _run(home, "recurring")
        assert result.returncode == 1
        assert "import" in result.stderr
