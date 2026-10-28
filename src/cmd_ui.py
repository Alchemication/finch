"""The ui command: the local annotation page."""

from __future__ import annotations

import argparse

from profiles import resolve_profile
from ui_server import serve


def cmd_ui(args: argparse.Namespace) -> None:
    """Serve the annotation page on loopback until Ctrl-C.

    Raises:
        FileNotFoundError: If the profile's database is missing.
    """
    profile = resolve_profile(args.profile)
    serve(profile.db, port=args.port, open_browser=not args.no_open)
