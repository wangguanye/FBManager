from fastapi import APIRouter, Depends, HTTPException, Query
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from datetime import date, datetime
from pydantic import BaseModel

from db.database import get_db
from modules.monitor import schemas
from modules.nurture import service
from core.scheduler import pause_scheduler, resume_scheduler, get_scheduler_status, scheduler

router = APIRouter(tags=["Nurture Tasks"])

class MaxConcurrentPayload(BaseModel):
    value: int

class RunActionPayload(BaseModel):
    action: str
    params: dict | None = None

@router.get("/tasks/today", response_model=List[schemas.NurtureTask])
async def get_today_tasks(
    date: date = Query(default_factory=lambda: datetime.now().date()),
    db: AsyncSession = Depends(get_db)
):
    """获取今日所有任务"""
    return await service.get_tasks_for_date(db, date)

@router.get("/tasks/{account_id}", response_model=List[schemas.NurtureTask])
async def get_account_tasks(
    account_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取指定账号任务历史"""
    return await service.get_account_tasks(db, account_id)

@router.post("/tasks/{account_id}/run")
async def run_account_tasks(
    account_id: int,
    db: AsyncSession = Depends(get_db)
):
    """立即触发执行账号任务"""
    asyncio.create_task(service.execute_account_tasks(account_id))
    return {"message": "Task triggered", "account_id": account_id}

@router.post("/tasks/{account_id}/run-action")
async def run_action(account_id: int, payload: RunActionPayload):
    if not payload.action:
        return {"code": 1, "data": {}, "msg": "missing_action"}
    try:
        task_id = await service.execute_custom_action(account_id, payload.action, payload.params)
    except ValueError as e:
        return {"code": 1, "data": {}, "msg": str(e)}
    return {"code": 0, "data": {"task_id": task_id}, "msg": ""}

@router.post("/tasks/{task_id}/complete")
async def complete_task(
    task_id: int,
    db: AsyncSession = Depends(get_db)
):
    """手动确认人工待办完成"""
    task = await service.complete_manual_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"message": "Task completed", "task_id": task.id}

# Scheduler API
@router.post("/scheduler/pause")
async def pause_scheduler_api():
    if pause_scheduler():
        return {"message": "Scheduler paused"}
    return {"message": "Scheduler not running or already paused"}

@router.post("/scheduler/resume")
async def resume_scheduler_api():
    if resume_scheduler():
        return {"message": "Scheduler resumed"}
    return {"message": "Scheduler not running or already running"}

@router.get("/scheduler/status")
async def scheduler_status():
    status = get_scheduler_status()
    # next_run 可能是 datetime，需要序列化
    return status

@router.post("/scheduler/max-concurrent")
async def set_max_concurrent(payload: MaxConcurrentPayload):
    try:
        value = await service.set_scheduler_max_concurrent(payload.value)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid max_concurrent value")
    return {"max_concurrent": value}

@router.get("/scheduler/queue")
async def scheduler_queue(db: AsyncSession = Depends(get_db)):
    return await service.get_scheduler_queue_status(db)
