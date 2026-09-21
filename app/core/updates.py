"""The app's one optional network call: is a newer release on GitHub?

Best-effort and silent. The apps work fully offline; if this fails for ANY reason
(no internet, GitHub down, an unexpected response) it reports "no update info"
rather than raising.
"""
import json
import urllib.request

RELEASES_API_URL = "https://api.github.com/repos/W-Hin/pdf_editor/releases/latest"
REQUEST_TIMEOUT_SECONDS = 3


def parse_version(value: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(part) for part in value.split("."))
    except (ValueError, AttributeError):
        return None


def is_newer(latest: str, current: str) -> bool:
    """True if `latest` is a strictly newer semver-ish version than `current`.

    Falls back to a plain inequality if either string doesn't parse as
    dot-separated integers, so a non-numeric tag still triggers a notice
    rather than being silently ignored.
    """
    latest_parsed = parse_version(latest)
    current_parsed = parse_version(current)
    if latest_parsed is not None and current_parsed is not None:
        return latest_parsed > current_parsed
    return latest != current


def check_for_update(current_version: str) -> dict:
    result = {
        "version": current_version,
        "latest": None,
        "release_url": None,
        "update_available": False,
    }
    try:
        req = urllib.request.Request(RELEASES_API_URL, headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read())
        latest_tag = (data.get("tag_name") or "").removeprefix("v").strip()
        if latest_tag:
            result["latest"] = latest_tag
            result["release_url"] = data.get("html_url")
            result["update_available"] = is_newer(latest_tag, current_version)
    except Exception:
        pass
    return result
