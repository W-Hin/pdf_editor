import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from web.backend.main import app

HOST = "127.0.0.1"
PORT = 8756


def _open_browser_when_ready() -> None:
    time.sleep(1.0)
    webbrowser.open(f"http://{HOST}:{PORT}/")


def main() -> None:
    dist_dir = Path(__file__).resolve().parent / "frontend" / "dist"
    if not dist_dir.exists():
        print(
            "Frontend build not found — the app will start but the browser tab will show "
            "an error page. Run `cd web/frontend && npm run build` first, then relaunch."
        )
    threading.Thread(target=_open_browser_when_ready, daemon=True).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
