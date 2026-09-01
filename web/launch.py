import threading
import time
import webbrowser

import uvicorn

from web.backend.main import app

HOST = "127.0.0.1"
PORT = 8756


def _open_browser_when_ready() -> None:
    time.sleep(1.0)
    webbrowser.open(f"http://{HOST}:{PORT}/")


def main() -> None:
    threading.Thread(target=_open_browser_when_ready, daemon=True).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
