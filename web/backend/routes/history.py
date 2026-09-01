from fastapi import APIRouter, HTTPException

from web.backend import storage

router = APIRouter()


@router.get("/history")
def list_history():
    return storage.load_history()


@router.delete("/history/{file_id}")
def delete_history_entry(file_id: str):
    deleted = storage.delete_output(file_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="History entry not found")
    return {"deleted": file_id}
