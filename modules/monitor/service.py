from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, and_
from modules.monitor.models import NurtureTask, ActionLog, Alert
from modules.asset.models import FBAccount
from modules.monitor.schemas import NurtureTaskCreate, ActionLogBase, DashboardStats
from loguru import logger
from datetime import datetime, date
from typing import Optional

async def create_nurture_task(db: AsyncSession, task: NurtureTaskCreate):
    """创建养号任务"""
    db_task = NurtureTask(
        fb_account_id=task.fb_account_id,
        day_number=task.day_number,
        scheduled_date=task.scheduled_date,
        task_type=task.task_type,
        execution_type=task.execution_type,
        status=task.status
    )
    db.add(db_task)
    await db.flush()
    return db_task

async def get_nurture_tasks(db: AsyncSession, skip: int = 0, limit: int = 100, scheduled_date: date = None):
    """获取所有养号任务"""
    query = select(NurtureTask)
    if scheduled_date:
        query = query.where(NurtureTask.scheduled_date == scheduled_date)
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()

async def create_action_log(db: AsyncSession, log: ActionLogBase):
    """创建操作日志"""
    db_log = ActionLog(
        fb_account_id=log.fb_account_id,
        task_id=log.task_id,
        action_type=log.action_type,
        level=log.level,
        message=log.message
    )
    db.add(db_log)
    await db.flush()
    return db_log

async def write_log(db: AsyncSession, fb_account_id: Optional[int], task_id: Optional[int], action_type: str, level: str, message: str):
    """写入 action_logs 表，同时用 loguru 输出到控制台"""
    # Loguru logging
    log_msg = f"[{action_type}] Account:{fb_account_id} Task:{task_id} - {message}"
    if level == "INFO":
        logger.info(log_msg)
    elif level == "WARN":
        logger.warning(log_msg)
    elif level == "ERROR":
        logger.error(log_msg)
    elif level == "CRITICAL":
        logger.critical(log_msg)
    
    # DB logging
    db_log = ActionLog(
        fb_account_id=fb_account_id,
        task_id=task_id,
        action_type=action_type,
        level=level,
        message=message
    )
    db.add(db_log)
    await db.commit() # Using commit to ensure log is written immediately
    await db.refresh(db_log)
    return db_log

async def get_action_logs(
    db: AsyncSession, 
    skip: int = 0, 
    limit: int = 50,
    account_id: Optional[int] = None,
    task_id: Optional[int] = None,
    level: Optional[str] = None,
    date_start: Optional[datetime] = None,
    date_end: Optional[datetime] = None,
    action_type: Optional[str] = None,
    keyword: Optional[str] = None
):
    """获取操作日志，支持筛选"""
    query = select(ActionLog, NurtureTask.result_log).outerjoin(
        NurtureTask, ActionLog.task_id == NurtureTask.id
    ).order_by(desc(ActionLog.created_at))
    
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
        
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    logs = []
    for log, result_log in result.all():
        logs.append({
            "id": log.id,
            "fb_account_id": log.fb_account_id,
            "task_id": log.task_id,
            "action_type": log.action_type,
            "level": log.level,
            "message": log.message,
            "is_dismissed": log.is_dismissed,
            "created_at": log.created_at,
            "result_log": result_log
        })
    return logs

async def create_alert(db: AsyncSession, fb_account_id: Optional[int], level: str, title: str, message: str) -> Alert | None:
    stmt_exist = select(Alert.id).where(
        and_(
            Alert.fb_account_id == fb_account_id,
            Alert.level == level,
            Alert.title == title,
            Alert.is_dismissed == False
        )
    ).order_by(desc(Alert.created_at)).limit(1)
    result_exist = await db.execute(stmt_exist)
    if result_exist.scalar_one_or_none():
        return None
    alert = Alert(
        fb_account_id=fb_account_id,
        level=level,
        title=title,
        message=message
    )
    db.add(alert)
    await db.flush()
    return alert

async def get_alerts(db: AsyncSession):
    query = select(Alert, FBAccount.username).outerjoin(
        FBAccount, Alert.fb_account_id == FBAccount.id
    ).where(
        Alert.is_dismissed == False
    ).order_by(desc(Alert.created_at))
    result = await db.execute(query)
    alerts = []
    for alert, username in result.all():
        alerts.append({
            "id": alert.id,
            "fb_account_id": alert.fb_account_id,
            "account_username": username,
            "level": alert.level,
            "title": alert.title,
            "message": alert.message,
            "is_dismissed": alert.is_dismissed,
            "created_at": alert.created_at,
            "dismissed_at": alert.dismissed_at
        })
    return alerts

async def dismiss_alert(db: AsyncSession, alert_id: int):
    query = select(Alert).where(Alert.id == alert_id)
    result = await db.execute(query)
    alert = result.scalar_one_or_none()
    if alert:
        alert.is_dismissed = True
        alert.dismissed_at = datetime.utcnow()
        await db.commit()
        await db.refresh(alert)
        return {
            "id": alert.id,
            "fb_account_id": alert.fb_account_id,
            "account_username": None,
            "level": alert.level,
            "title": alert.title,
            "message": alert.message,
            "is_dismissed": alert.is_dismissed,
            "created_at": alert.created_at,
            "dismissed_at": alert.dismissed_at
        }
    return None

async def get_alert_counts(db: AsyncSession) -> dict:
    stmt_total = select(func.count(Alert.id)).where(Alert.is_dismissed == False)
    total_res = await db.execute(stmt_total)
    total = total_res.scalar() or 0

    stmt_error = select(func.count(Alert.id)).where(
        Alert.is_dismissed == False,
        Alert.level == "ERROR"
    )
    error_res = await db.execute(stmt_error)
    error = error_res.scalar() or 0

    stmt_critical = select(func.count(Alert.id)).where(
        Alert.is_dismissed == False,
        Alert.level == "CRITICAL"
    )
    critical_res = await db.execute(stmt_critical)
    critical = critical_res.scalar() or 0

    return {"total": total, "error": error, "critical": critical}

async def get_dashboard_stats(db: AsyncSession) -> DashboardStats:
    """获取仪表盘统计数据"""
    # Account Stats - Group by status
    account_query = select(FBAccount.status, func.count(FBAccount.id)).where(FBAccount.is_deleted == False).group_by(FBAccount.status)
    account_res = await db.execute(account_query)
    account_stats = {row[0]: row[1] for row in account_res.all()}
    
    # Task Stats (Today)
    today = date.today()
    task_query = select(NurtureTask.status, func.count(NurtureTask.id)).where(NurtureTask.scheduled_date == today).group_by(NurtureTask.status)
    task_res = await db.execute(task_query)
    task_stats_raw = {row[0]: row[1] for row in task_res.all()}
    
    total_tasks = sum(task_stats_raw.values())
    completed_tasks = task_stats_raw.get("completed", 0)
    failed_tasks = task_stats_raw.get("failed", 0)
    pending_tasks = task_stats_raw.get("pending", 0)
    
    task_stats = {
        "total": total_tasks,
        "completed": completed_tasks,
        "failed": failed_tasks,
        "pending": pending_tasks
    }
    
    # Active RPA Count (tasks with status='running')
    active_query = select(func.count(NurtureTask.id)).where(NurtureTask.status == "running")
    active_res = await db.execute(active_query)
    active_rpa_count = active_res.scalar() or 0
    
    # Alert Count
    alert_query = select(func.count(Alert.id)).where(
        Alert.level.in_(["ERROR", "CRITICAL"]),
        Alert.is_dismissed == False
    )
    alert_res = await db.execute(alert_query)
    alert_count = alert_res.scalar() or 0
    
    return DashboardStats(
        account_stats=account_stats,
        task_stats=task_stats,
        active_rpa_count=active_rpa_count,
        alert_count=alert_count
    )
