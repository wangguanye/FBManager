from fastapi import APIRouter

from modules.sop.schemas import SOPConfig
from modules.sop.service import load_sop, save_sop, get_available_actions, validate_sop, list_sop_backups, restore_sop_backup

router = APIRouter(prefix="/api/sop")

def _ok(data):
    return {"code": 0, "data": data, "msg": ""}

def _error(message, code=1, data=None):
    return {"code": code, "data": data or {}, "msg": message}

@router.get("")
async def get_sop():
    return _ok(load_sop().model_dump())

@router.put("")
async def update_sop(config: SOPConfig):
    try:
        saved = save_sop(config)
        return _ok(saved.model_dump())
    except Exception as e:
        return _error(str(e))

@router.get("/actions")
async def list_actions():
    return _ok(get_available_actions())

@router.post("/validate")
async def validate_config(config: SOPConfig):
    errors = validate_sop(config)
    return _ok({"errors": errors})

@router.get("/backups")
async def get_backups():
    return _ok({"files": list_sop_backups()})

@router.post("/restore/{filename}")
async def restore_backup(filename: str):
    try:
        restored = restore_sop_backup(filename)
        return _ok(restored.model_dump())
    except Exception as e:
        return _error(str(e))
