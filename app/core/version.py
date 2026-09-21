import sys
from pathlib import Path

if hasattr(sys, "_MEIPASS"):
    # Running from a PyInstaller bundle — VERSION is bundled as a data file
    # via --add-data "VERSION;.", landing at the root of sys._MEIPASS.
    _base_dir = Path(sys._MEIPASS)
else:
    _base_dir = Path(__file__).resolve().parent.parent.parent

_version_file = _base_dir / "VERSION"
APP_VERSION = _version_file.read_text(encoding="utf-8").strip() if _version_file.exists() else "0.0.0-dev"
