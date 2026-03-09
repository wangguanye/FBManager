from fastapi import APIRouter, Depends, HTTPException, Query, Path
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from datetime import datetime, date
from db.database import get_db
from modules.monitor import service, schemas
from modules.monitor.models import ActionLog

router = APIRouter()

@router.get("/logs", response_model=List[schemas.ActionLog])
async def list_logs(
    page: int = 1, 
    size: int = 50, 
    account_id: Optional[int] = None,
    level: Optional[str] = None,
    date_start: Optional[datetime] = None,
    date_end: Optional[datetime] = None,
    action_type: Optional[str] = None,
    keyword: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    获取操作日志列表，支持多种筛选条件
    """
    skip = (page - 1) * size
    logs = await service.get_action_logs(
        db, 
        skip=skip, 
        limit=size, 
        account_id=account_id, 
        level=level, 
        date_start=date_start, 
        date_end=date_end, 
        action_type=action_type, 
        keyword=keyword
    )
    return logs

@router.get("/alerts", response_model=List[schemas.ActionLog])
async def list_alerts(db: AsyncSession = Depends(get_db)):
    """
    获取未处理告警（level 为 ERROR 或 CRITICAL 且未 dismiss 的日志）
    """
    alerts = await service.get_alerts(db)
    return alerts

@router.post("/alerts/{id}/dismiss", response_model=schemas.ActionLog)
async def dismiss_alert(
    id: int = Path(..., description="Alert ID"),
    db: AsyncSession = Depends(get_db)
):
    """
    标记告警已处理
    """
    alert = await service.dismiss_alert(db, log_id=id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert

@router.get("/dashboard/stats", response_model=schemas.DashboardStats)
async def get_dashboard_stats(db: AsyncSession = Depends(get_db)):
    """
    获取仪表盘统计数据
    """
    stats = await service.get_dashboard_stats(db)
    return stats

@router.get("/dashboard/tasks", response_model=List[schemas.NurtureTask])
async def list_dashboard_tasks(
    date: Optional[date] = None,
    page: int = 1,
    size: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """
    获取今日任务列表（或指定日期）
    """
    if not date:
        date = datetime.now().date()
    
    skip = (page - 1) * size
    tasks = await service.get_nurture_tasks(db, skip=skip, limit=size, scheduled_date=date)
    return tasks
