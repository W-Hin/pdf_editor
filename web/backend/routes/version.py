import json
import urllib.error
import urllib.request

from fastapi import APIRouter

from web.backend.appinfo import APP_VERSION

router = APIRouter()

# Best-effort, non-blocking check against this repo's GitHub Releases. The
# app must work fully offline — if this fails or times out for any reason
# (no internet, GitHub down, etc.), we silently report "no update info"
# rather than raising, since this endpoint is the app's one optional,
# non-essential network call.
_RELEASES_API_URL = "https://api.github.com/repos/W-Hin/pdf_editor/releases/latest"
_REQUEST_TIMEOUT_SECONDS = 3


@router.get("/version")
def get_version():
    result = {
        "version": APP_VERSION,
        "latest": None,
        "release_url": None,
        "update_available": False,
    }
    try:
        req = urllib.request.Request(
            _RELEASES_API_URL, headers={"Accept": "application/vnd.github+json"}
        )
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read())
        latest_tag = (data.get("tag_name") or "").lstrip("v").strip()
        if latest_tag:
            result["latest"] = latest_tag
            result["release_url"] = data.get("html_url")
            result["update_available"] = latest_tag != APP_VERSION
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        pass
    return result
