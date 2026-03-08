from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from modules.monitor.models import NurtureTask, ActionLog
from modules.monitor.schemas import NurtureTaskCreate, ActionLogBase

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

async def get_nurture_tasks(db: AsyncSession, skip: int = 0, limit: int = 100):
    """获取所有养号任务"""
    result = await db.execute(select(NurtureTask).offset(skip).limit(limit))
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

async def get_action_logs(db: AsyncSession, skip: int = 0, limit: int = 100):
    """获取操作日志"""
    result = await db.execute(select(ActionLog).offset(skip).limit(limit).order_by(ActionLog.created_at.desc()))
    return result.scalars().all()
