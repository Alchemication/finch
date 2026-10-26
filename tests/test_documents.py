"""Documents kept in the archive beside the statements."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from models import Document
from sources import archive_source, archived_file
from store import (
    add_document,
    find_document,
    get_document,
    load_documents,
    load_imports,
)


def _document(sha256: str = "a" * 64, **overrides: object) -> Document:
    fields: dict[str, object] = {
        "sha256": sha256,
        "original_name": "Example_Agreement.pdf",
        "title": "Example agreement",
    }
    fields.update(overrides)
    return Document(**fields)  # type: ignore[arg-type]


class TestDocumentModel:
    def test_blank_title_is_refused(self) -> None:
        with pytest.raises(ValueError, match="--title"):
            _document(title="  ")


class TestDocumentStore:
    def test_round_trip(self, conn: sqlite3.Connection) -> None:
        with conn:
            stored = add_document(
                conn, _document(dated_on=date(2025, 4, 1), note="Example note")
            )
        assert stored.id is not None
        assert get_document(conn, stored.id) == stored
        assert find_document(conn, "a" * 64) == stored

    def test_unknown_hash_finds_nothing(self, conn: sqlite3.Connection) -> None:
        assert find_document(conn, "b" * 64) is None

    def test_unknown_id_says_how_to_list(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError, match="doc list"):
            get_document(conn, 99)

    def test_same_content_twice_is_refused(self, conn: sqlite3.Connection) -> None:
        add_document(conn, _document())
        with pytest.raises(ValueError, match="already kept"):
            add_document(conn, _document(title="Another title"))

    def test_newest_first_undated_by_when_added(self, conn: sqlite3.Connection) -> None:
        add_document(conn, _document("1" * 64, title="Old", dated_on=date(2024, 7, 27)))
        add_document(conn, _document("2" * 64, title="New", dated_on=date(2026, 8, 12)))
        add_document(conn, _document("3" * 64, title="Undated"))
        titles = [document.title for document in load_documents(conn)]
        # Undated documents sort by when they were added, which is today.
        assert titles == ["Undated", "New", "Old"]

    def test_no_imports_listed_on_an_empty_ledger(
        self, conn: sqlite3.Connection
    ) -> None:
        assert load_imports(conn) == []


class TestArchivedFile:
    def test_finds_what_was_archived(self, tmp_path: Path) -> None:
        digest, path = archive_source(tmp_path / "sources", b"%PDF-1.4", suffix=".PDF")
        assert archived_file(tmp_path / "sources", digest) == path
        assert path.name == "source.pdf"

    def test_unknown_hash_is_none(self, tmp_path: Path) -> None:
        assert archived_file(tmp_path / "sources", "c" * 64) is None
