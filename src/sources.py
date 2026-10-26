"""Write-once private archive of every file imported into a profile.

The archive is what makes the ledger rebuildable. A parser bug found in March
is fixed by bumping the parser version and re-reading January's file, not by
patching January's rows, so the file itself must still exist and be exactly
what was imported.

Public API:
    private_path    -- resolve a path, refusing anywhere inside the repository
    archive_source  -- store file bytes under their SHA-256, once
    archived_file   -- the archived file for a hash, if it is there

Example:
    from sources import archive_source

    digest, path = archive_source(profile.sources, content, suffix=".csv")
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from config import PRIVATE_DIR_MODE, PRIVATE_FILE_MODE, REPOSITORY_ROOT

_SUFFIX_RE = re.compile(r"^\.[a-z0-9]{1,8}$")


def private_path(path: Path) -> Path:
    """Resolve *path*, following symlinks, and refuse the repository.

    Raises:
        ValueError: If the resolved path is inside the checkout.
    """
    resolved = path.expanduser().resolve()
    if resolved.is_relative_to(REPOSITORY_ROOT):
        raise ValueError(
            f"Refusing to write financial data inside the repository ({resolved}). "
            f"It belongs under FINCH_HOME."
        )
    return resolved


def _write_once(path: Path, content: bytes) -> None:
    """Create a private immutable file, or verify an existing one matches."""
    try:
        descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_FILE_MODE
        )
    except FileExistsError:
        if path.read_bytes() != content:
            raise ValueError(
                f"Archived file {path} no longer matches its content hash. "
                f"Something modified the archive; inspect it before importing."
            ) from None
        return
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)


def archive_source(root: Path, content: bytes, *, suffix: str) -> tuple[str, Path]:
    """Archive file bytes under ``root/<sha256>/source<suffix>``.

    Idempotent: archiving identical bytes again returns the existing path. The
    original filename is deliberately not reused, since bank filenames often
    embed an account number; the import row records it instead.

    Args:
        root: The profile's sources directory.
        content: The file's bytes.
        suffix: Original file extension; dropped unless short and alphanumeric.

    Returns:
        ``(sha256 hex digest, archived path)``.

    Raises:
        ValueError: If *root* is inside the repository, or an archived file at
            the target path has different content.
    """
    digest = hashlib.sha256(content).hexdigest()
    root = private_path(root)
    # parents=True creates missing parents with the umask's mode, not ours,
    # so the archive root is made owner-only explicitly.
    root.mkdir(parents=True, exist_ok=True, mode=PRIVATE_DIR_MODE)
    os.chmod(root, PRIVATE_DIR_MODE)
    directory = root / digest
    directory.mkdir(exist_ok=True, mode=PRIVATE_DIR_MODE)
    clean_suffix = suffix.lower() if _SUFFIX_RE.fullmatch(suffix.lower()) else ""
    target = directory / f"source{clean_suffix}"
    _write_once(target, content)
    return digest, target


def archived_file(root: Path, digest: str) -> Path | None:
    """Return the file archived under *digest*, or None if it is not there.

    The extension is not recorded anywhere but on disk, so the one file in
    the hash's directory is the answer.
    """
    directory = root / digest
    if not directory.is_dir():
        return None
    return next(iter(sorted(directory.glob("source*"))), None)
