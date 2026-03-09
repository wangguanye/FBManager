from fastapi import APIRouter
from modules.system.service import perform_backup

router = APIRouter(tags=["System"])

@router.post("/system/backup")
async def create_backup():
    success, msg = await perform_backup()
    return {"code": 0 if success else 1, "msg": msg, "data": {}}
