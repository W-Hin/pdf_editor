from fastapi import APIRouter

from app.core.updates import check_for_update
from web.backend.appinfo import APP_VERSION

router = APIRouter()


@router.get("/version")
def get_version():
    # Best-effort and silent: see app/core/updates.py.
    return check_for_update(APP_VERSION)
