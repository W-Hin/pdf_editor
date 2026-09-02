import json
import urllib.request

from fastapi import APIRouter

from web.backend.appinfo import APP_VERSION

router = APIRouter()

# Best-effort, non-blocking check against this repo's GitHub Releases. The
# app must work fully offline — if this fails for ANY reason (no internet,
# GitHub down, a malformed/unexpected response shape, etc.), we silently
# report "no update info" rather than raising, since this endpoint is the
# app's one optional, non-essential network call and must never error.
_RELEASES_API_URL = "https://api.github.com/repos/W-Hin/pdf_editor/releases/latest"
_REQUEST_TIMEOUT_SECONDS = 3


def _parse_version(value: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(part) for part in value.split("."))
    except (ValueError, AttributeError):
        return None


def _is_newer(latest: str, current: str) -> bool:
    """True if `latest` is a strictly newer semver-ish version than `current`.

    Falls back to a plain inequality if either string doesn't parse as
    dot-separated integers, so a non-numeric tag still triggers a notice
    rather than being silently ignored.
    """
    latest_parsed = _parse_version(latest)
    current_parsed = _parse_version(current)
    if latest_parsed is not None and current_parsed is not None:
        return latest_parsed > current_parsed
    return latest != current


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
        latest_tag = (data.get("tag_name") or "").removeprefix("v").strip()
        if latest_tag:
            result["latest"] = latest_tag
            result["release_url"] = data.get("html_url")
            result["update_available"] = _is_newer(latest_tag, APP_VERSION)
    except Exception:
        pass
    return result
