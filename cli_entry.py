# ============================================================
# cli_entry.py — PyInstaller entry point
# ============================================================
"""Thin launcher for building the exe.

PyInstaller analyzes imports best from a plain top-level script, so this
wraps the package entry point (``web_crawler.cli.main``) instead of pointing
the build at ``web_crawler/cli.py`` directly — that keeps the package's
absolute imports (``from web_crawler import ...``) working inside the bundle.

Build with:  pyinstaller --onefile --console cli_entry.py
(or via the existing .spec files / the PyInstaller GUI).
"""

import multiprocessing
import sys

from web_crawler.cli import main

if __name__ == "__main__":
    # Required in frozen Windows exes: without it, any multiprocessing spawn
    # (e.g. from bundled libs) re-runs the whole app in the child process.
    multiprocessing.freeze_support()
    sys.exit(main())
