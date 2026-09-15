"""Profile roster and per-profile paths.

A profile is one person's ledger: their database and the archive of every
statement imported into it. The roster lives at ``$FINCH_HOME/profiles.toml``;
everything a profile owns lives under ``$FINCH_HOME/profiles/<name>/``.

Profiles never share a database. A household view, if one is ever built, reads
several profiles; it does not merge them.

Public API:
    Profile              -- one person's configuration and paths
    ProfileConfigError   -- roster missing, malformed, or inconsistent
    load_profiles        -- read and validate the whole roster
    operator_profile     -- the default profile for bare commands
    resolve_profile      -- the profile a command acts on
    add_profile          -- create a profile and its private directory

Example:
    from profiles import resolve_profile

    profile = resolve_profile(args.profile)
"""

from __future__ import annotations

import logging
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from config import APP_HOME, PRIVATE_DIR_MODE, PRIVATE_FILE_MODE, REPOSITORY_ROOT

logger = logging.getLogger(__name__)

PROFILE_NAME_RE = re.compile(r"^[a-z0-9_-]+$")
ROSTER_FILENAME = "profiles.toml"


class ProfileConfigError(ValueError):
    """Raised when the profile roster is missing or invalid."""


@dataclass(frozen=True)
class Profile:
    """One person's ledger and where it lives."""

    name: str
    root: Path
    operator: bool = False
    enabled: bool = True

    @property
    def db(self) -> Path:
        """This profile's ledger database."""
        return self.root / "ledger.db"

    @property
    def sources(self) -> Path:
        """Write-once archive of every file imported into this profile."""
        return self.root / "sources"


def validate_profile_name(name: str) -> str:
    """Return *name* if it is filesystem-safe.

    Raises:
        ProfileConfigError: If the name is not filesystem-safe.
    """
    if not PROFILE_NAME_RE.fullmatch(name):
        raise ProfileConfigError(
            f"Invalid profile name {name!r}; use lowercase letters, digits, "
            f"'_' or '-'. It becomes a directory name."
        )
    return name


def load_profiles(home: Path = APP_HOME) -> dict[str, Profile]:
    """Load and validate the complete profile roster.

    Args:
        home: App home containing ``profiles.toml``.

    Returns:
        Profiles keyed by name.

    Raises:
        ProfileConfigError: If the roster is missing, unreadable, or invalid.
    """
    path = home / ROSTER_FILENAME
    if not path.exists():
        raise ProfileConfigError(
            f"No profile roster at {path}. Create the first profile with "
            f"'uv run python main.py profile add NAME --operator'."
        )
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ProfileConfigError(
            f"Could not read profile roster {path}: {exc}"
        ) from exc

    raw_profiles = raw.get("profiles")
    if not isinstance(raw_profiles, dict) or not raw_profiles:
        raise ProfileConfigError(
            f"{path} must contain at least one [profiles.NAME] table."
        )

    profiles: dict[str, Profile] = {}
    for raw_name, values in raw_profiles.items():
        name = validate_profile_name(str(raw_name))
        if not isinstance(values, dict):
            raise ProfileConfigError(f"profiles.{name} must be a TOML table.")
        operator = values.get("operator", False)
        enabled = values.get("enabled", True)
        if not isinstance(operator, bool) or not isinstance(enabled, bool):
            raise ProfileConfigError(
                f"profiles.{name}.operator and enabled must be booleans."
            )
        profiles[name] = Profile(
            name=name,
            root=home / "profiles" / name,
            operator=operator,
            enabled=enabled,
        )

    operators = [profile for profile in profiles.values() if profile.operator]
    if len(operators) != 1:
        raise ProfileConfigError(
            f"{path} marks {len(operators)} profiles as operator; exactly one "
            f"must be, since it is the default for commands without --profile."
        )
    return profiles


def operator_profile(profiles: dict[str, Profile]) -> Profile:
    """Return the operator profile.

    Raises:
        ProfileConfigError: If no profile is marked operator.
    """
    for profile in profiles.values():
        if profile.operator:
            return profile
    raise ProfileConfigError("The roster has no operator profile.")


def resolve_profile(
    name: str | None,
    *,
    home: Path = APP_HOME,
    require_db: bool = True,
) -> Profile:
    """Return the profile a command acts on.

    Args:
        name: Profile from ``--profile``, or None for the operator profile.
        home: App home containing the roster.
        require_db: Refuse a profile whose database does not exist yet. Only
            ``init`` passes False.

    Returns:
        The resolved profile.

    Raises:
        ProfileConfigError: If the profile is unknown or has no database.
    """
    profiles = load_profiles(home)
    if name is None:
        profile = operator_profile(profiles)
    elif name in profiles:
        profile = profiles[name]
    else:
        known = ", ".join(sorted(profiles))
        raise ProfileConfigError(f"Unknown profile {name!r}. Known: {known}.")

    if require_db and not profile.db.exists():
        raise ProfileConfigError(
            f"No database for profile {profile.name!r} at {profile.db}. Run "
            f"'uv run python main.py init --profile {profile.name}'."
        )
    return profile


def add_profile(name: str, *, operator: bool = False, home: Path = APP_HOME) -> Profile:
    """Create a profile and its private directory, and add it to the roster.

    Args:
        name: Profile name; becomes a directory name.
        operator: Whether this is the default profile for bare commands.
        home: App home to create the profile under.

    Returns:
        The created profile.

    Raises:
        ProfileConfigError: If the name is taken or invalid, if the operator
            rule would be broken, or if *home* is inside the repository.
    """
    validate_profile_name(name)
    home = home.expanduser().resolve()
    if home.is_relative_to(REPOSITORY_ROOT):
        raise ProfileConfigError(
            f"FINCH_HOME resolves to {home}, inside the repository. Financial "
            f"data must live outside the checkout; choose another FINCH_HOME."
        )

    roster = home / ROSTER_FILENAME
    existing = load_profiles(home) if roster.exists() else {}
    if name in existing:
        raise ProfileConfigError(f"Profile {name!r} already exists.")
    if existing and operator:
        raise ProfileConfigError(
            "The roster already has an operator profile; only one profile may "
            "be the default for commands without --profile."
        )
    if not existing and not operator:
        raise ProfileConfigError(
            "The first profile must be the operator; pass --operator. It is "
            "what commands without --profile act on."
        )

    root = home / "profiles" / name
    if root.exists():
        raise ProfileConfigError(
            f"Profile directory already exists: {root}. Remove it or choose "
            f"another name."
        )
    for directory in (home, home / "profiles", root):
        directory.mkdir(mode=PRIVATE_DIR_MODE, exist_ok=True)
        os.chmod(directory, PRIVATE_DIR_MODE)

    header = "" if roster.exists() else "# finch profile roster.\n"
    with roster.open("a", encoding="utf-8") as handle:
        handle.write(
            f"{header}\n[profiles.{name}]\n"
            f"operator = {str(operator).lower()}\n"
            f"enabled = true\n"
        )
    os.chmod(roster, PRIVATE_FILE_MODE)
    logger.info("Created profile %s at %s", name, root)
    return Profile(name=name, root=root, operator=operator)
