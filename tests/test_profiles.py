"""Profile roster, creation rules and private directories."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from config import REPOSITORY_ROOT
from profiles import ProfileConfigError, add_profile, load_profiles, resolve_profile


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


class TestAddProfile:
    def test_first_profile_must_be_operator(self, tmp_path: Path) -> None:
        with pytest.raises(ProfileConfigError, match="--operator"):
            add_profile("me", home=tmp_path / "home")

    def test_creates_private_directory_and_roster(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        profile = add_profile("me", operator=True, home=home)
        assert _mode(home) == 0o700
        assert _mode(profile.root) == 0o700
        assert _mode(home / "profiles.toml") == 0o600
        assert load_profiles(home)["me"].operator

    def test_second_profile_joins_the_roster(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        add_profile("me", operator=True, home=home)
        add_profile("partner", home=home)
        profiles = load_profiles(home)
        assert set(profiles) == {"me", "partner"}
        assert not profiles["partner"].operator

    def test_rejects_second_operator(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        add_profile("me", operator=True, home=home)
        with pytest.raises(ProfileConfigError, match="operator"):
            add_profile("partner", operator=True, home=home)

    def test_rejects_duplicate_name(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        add_profile("me", operator=True, home=home)
        with pytest.raises(ProfileConfigError, match="already exists"):
            add_profile("me", home=home)

    def test_rejects_invalid_name(self, tmp_path: Path) -> None:
        with pytest.raises(ProfileConfigError, match="Invalid profile name"):
            add_profile("My Name", operator=True, home=tmp_path / "home")

    def test_rejects_home_inside_repository(self) -> None:
        home = REPOSITORY_ROOT / "never-created-home"
        with pytest.raises(ProfileConfigError, match="inside the repository"):
            add_profile("me", operator=True, home=home)
        assert not home.exists()


class TestResolveProfile:
    def test_missing_roster_says_how_to_create_one(self, tmp_path: Path) -> None:
        with pytest.raises(ProfileConfigError, match="profile add"):
            resolve_profile(None, home=tmp_path / "home")

    def test_defaults_to_operator(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        add_profile("me", operator=True, home=home)
        add_profile("partner", home=home)
        assert resolve_profile(None, home=home, require_db=False).name == "me"

    def test_unknown_profile_lists_known(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        add_profile("me", operator=True, home=home)
        with pytest.raises(ProfileConfigError, match="Known: me"):
            resolve_profile("nobody", home=home, require_db=False)

    def test_missing_database_says_to_init(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        add_profile("me", operator=True, home=home)
        with pytest.raises(ProfileConfigError, match="init --profile me"):
            resolve_profile("me", home=home)
