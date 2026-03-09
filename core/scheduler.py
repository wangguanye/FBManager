from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from db.database import AsyncSessionLocal
from modules.nurture.service import generate_daily_tasks, check_and_execute_tasks, check_manual_task_timeout
from loguru import logger
from datetime import datetime

# APScheduler 调度器实例
scheduler = AsyncIOScheduler()

async def job_generate_daily_tasks():
    """
    每日定时生成养号任务
    """
    logger.info("Executing job: generate_daily_tasks")
    async with AsyncSessionLocal() as db:
        await generate_daily_tasks(db)

async def job_execute_tasks():
    """
    每分钟检查是否有到期任务需要执行
    """
    # logger.debug("Executing job: check_and_execute_tasks") # Debug level to avoid spam
    await check_and_execute_tasks()

async def job_check_manual_timeout():
    """
    检查手动任务超时
    """
    await check_manual_task_timeout()

async def start_scheduler():
    """
    启动调度器。
    """
    if not scheduler.running:
        # 1. 每日 job "generate_tasks"：在本地时间 06:00 执行
        scheduler.add_job(
            job_generate_daily_tasks,
            CronTrigger(hour=6, minute=0),
            id="generate_tasks",
            replace_existing=True
        )
        
        # 2. 每日 job "execute_tasks"：这里实现为每分钟检查一次
        # 也可以设置为 06:30 开始每分钟运行，直到 23:00？
        # 为了简单，全天候运行检查，因为 generate_daily_tasks 会控制 scheduled_time
        scheduler.add_job(
            job_execute_tasks,
            IntervalTrigger(minutes=1),
            id="execute_tasks",
            replace_existing=True
        )
        
        # 3. 手动任务超时检查：每 30 分钟检查一次
        scheduler.add_job(
            job_check_manual_timeout,
            IntervalTrigger(minutes=30),
            id="check_manual_timeout",
            replace_existing=True
        )
        
        scheduler.start()
        logger.info("Scheduler started.")

async def stop_scheduler():
    """
    停止调度器。
    """
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped.")

def pause_scheduler():
    if scheduler.running:
        scheduler.pause()
        return True
    return False

def resume_scheduler():
    if scheduler.running:
        scheduler.resume()
        return True
    return False

def get_scheduler_status():
    next_run = None
    if scheduler.get_job("generate_tasks"):
        next_run = scheduler.get_job("generate_tasks").next_run_time
        
    return {
        "running": scheduler.running and (scheduler.state != 2), # 2 is PAUSED state in APScheduler? No, state is separate.
        # APScheduler running property returns True if start() was called and not shutdown.
        # Check if paused:
        "paused": scheduler.state == 2, # STATE_PAUSED = 2
        "next_run_generate": next_run
    }
