from fastapi import APIRouter, Depends, HTTPException, Query, Path
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from datetime import datetime, date
from sqlalchemy import select, desc
import csv
import io
from db.database import get_db
from modules.monitor import service, schemas
from modules.monitor.models import ActionLog
from modules.asset.models import FBAccount
router = APIRouter()

@router.get("/logs", response_model=List[schemas.ActionLog])
async def list_logs(
    page: int = 1, 
    size: int = 50, 
    account_id: Optional[int] = None,
    task_id: Optional[int] = None,
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
        task_id=task_id,
        level=level, 
        date_start=date_start, 
        date_end=date_end, 
        action_type=action_type, 
        keyword=keyword
    )
    return logs

@router.get("/alerts", response_model=List[schemas.Alert])
async def list_alerts(db: AsyncSession = Depends(get_db)):
    alerts = await service.get_alerts(db)
    return alerts

@router.post("/alerts/{id}/dismiss", response_model=schemas.Alert)
async def dismiss_alert(
    id: int = Path(..., description="Alert ID"),
    db: AsyncSession = Depends(get_db)
):
    alert = await service.dismiss_alert(db, alert_id=id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert

@router.get("/alerts/count", response_model=schemas.AlertCount)
async def get_alert_count(db: AsyncSession = Depends(get_db)):
    counts = await service.get_alert_counts(db)
    return counts

@router.get("/logs/export")
async def export_logs(
    account_id: Optional[int] = None,
    task_id: Optional[int] = None,
    level: Optional[str] = None,
    date_start: Optional[datetime] = None,
    date_end: Optional[datetime] = None,
    action_type: Optional[str] = None,
    keyword: Optional[str] = None,
    format: str = "csv",
    db: AsyncSession = Depends(get_db)
):
    if format != "csv":
        raise HTTPException(status_code=400, detail="Unsupported format")
    query = select(ActionLog).order_by(desc(ActionLog.created_at))
    if account_id:
        query = query.where(ActionLog.fb_account_id == account_id)
    if task_id:
        query = query.where(ActionLog.task_id == task_id)
    if level:
        if "," in level:
            levels = level.split(",")
            query = query.where(ActionLog.level.in_(levels))
        else:
            query = query.where(ActionLog.level == level)
    if date_start:
        query = query.where(ActionLog.created_at >= date_start)
    if date_end:
        query = query.where(ActionLog.created_at <= date_end)
    if action_type:
        query = query.where(ActionLog.action_type == action_type)
    if keyword:
        query = query.where(ActionLog.message.ilike(f"%{keyword}%"))
    result = await db.execute(query)
    logs = result.scalars().all()
    account_map = {}
    account_ids = {item.fb_account_id for item in logs if item.fb_account_id}
    if account_ids:
        account_result = await db.execute(
            select(FBAccount.id, FBAccount.username).where(FBAccount.id.in_(account_ids))
        )
        account_map = {account_id: username for account_id, username in account_result.all()}
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow(["时间", "账号名", "任务ID", "行为模块", "级别", "日志内容"])
    for item in logs:
        account_name = account_map.get(item.fb_account_id, "")
        created_at = item.created_at.strftime("%Y-%m-%d %H:%M:%S") if item.created_at else ""
        writer.writerow([
            created_at,
            account_name,
            item.task_id or "",
            item.action_type or "",
            item.level or "",
            item.message or ""
        ])
    output.seek(0)
    filename = f"logs_{datetime.now().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

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
