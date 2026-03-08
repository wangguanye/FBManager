from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from db.database import get_db
from modules.monitor import service, schemas

router = APIRouter(prefix="/monitor", tags=["Monitor"])

@router.post("/tasks", response_model=schemas.NurtureTask)
async def create_task(task: schemas.NurtureTaskCreate, db: AsyncSession = Depends(get_db)):
    """创建养号任务"""
    return await service.create_nurture_task(db, task)

@router.get("/tasks", response_model=List[schemas.NurtureTask])
async def list_tasks(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)):
    """列出养号任务"""
    return await service.get_nurture_tasks(db, skip, limit)

@router.post("/logs", response_model=schemas.ActionLog)
async def create_log(log: schemas.ActionLogBase, db: AsyncSession = Depends(get_db)):
    """记录操作日志"""
    return await service.create_action_log(db, log)

@router.get("/logs", response_model=List[schemas.ActionLog])
async def list_logs(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)):
    """列出所有操作日志"""
    return await service.get_action_logs(db, skip, limit)
