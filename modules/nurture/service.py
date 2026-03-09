from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc, func, or_
from datetime import datetime, date, timedelta, time
import pytz
import random
import asyncio
from typing import List, Optional

from modules.asset.models import FBAccount
from modules.monitor.models import NurtureTask, ActionLog
from modules.nurture.sop_loader import get_tasks_for_day
from db.database import AsyncSessionLocal
from loguru import logger
import yaml

async def get_scheduler_config():
    try:
        with open("config.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        return config.get("scheduler", {})
    except Exception as e:
        logger.error(f"Failed to load scheduler config: {e}")
        return {}

async def generate_daily_tasks(db: AsyncSession):
    """
    生成每日养号任务
    """
    logger.info("开始生成每日养号任务...")
    
    # 1. 获取目标账号
    stmt = select(FBAccount).where(
        FBAccount.status.in_(["养号中", "投放养号中"])
    )
    result = await db.execute(stmt)
    accounts = result.scalars().all()
    
    today = datetime.now().date()
    sched_config = await get_scheduler_config()
    
    # 活跃窗口配置
    active_start_hour = sched_config.get("active_window_start", 8)
    active_end_hour = sched_config.get("active_window_end", 22)
    
    tasks_created = 0
    
    for account in accounts:
        # 1. 计算 nurture_day
        if not account.nurture_start_date:
            account.nurture_start_date = today
            account.nurture_day = 1
        else:
            days_diff = (today - account.nurture_start_date).days
            account.nurture_day = days_diff + 1
            
        # 2. 获取 SOP
        sop = get_tasks_for_day(account.nurture_day)
        
        # 准备任务列表
        tasks_to_create = []
        
        # 3. 处理 once_tasks (一次性任务)
        # 检查前置依赖：如果 day > 1，检查前一天的 once 任务是否全部完成
        can_create_once = True
        if account.nurture_day > 1:
            prev_day = account.nurture_day - 1
            stmt_prev = select(func.count()).where(
                and_(
                    NurtureTask.fb_account_id == account.id,
                    NurtureTask.day_number == prev_day,
                    NurtureTask.task_type == "once",
                    NurtureTask.status != "completed"
                )
            )
            result_prev = await db.execute(stmt_prev)
            pending_prev = result_prev.scalar()
            if pending_prev > 0:
                logger.warning(f"账号 {account.username} 第 {prev_day} 天一次性任务未完成，跳过第 {account.nurture_day} 天一次性任务")
                can_create_once = False

        if can_create_once:
            for task_def in sop.get("once_tasks", []):
                action = task_def.get("action")
                stmt_exist = select(NurtureTask).where(
                    and_(
                        NurtureTask.fb_account_id == account.id,
                        NurtureTask.day_number == account.nurture_day,
                        NurtureTask.task_type == "once",
                        NurtureTask.action == action
                    )
                )
                result_exist = await db.execute(stmt_exist)
                if result_exist.scalar():
                    continue
                    
                tasks_to_create.append({
                    "action": action,
                    "task_type": "once",
                    "execution_type": task_def.get("execution_type", "auto")
                })

        # 4. 处理 daily_tasks
        for task_def in sop.get("daily_tasks", []):
            action = task_def.get("action")
            stmt_exist = select(NurtureTask).where(
                and_(
                    NurtureTask.fb_account_id == account.id,
                    NurtureTask.scheduled_date == today,
                    NurtureTask.task_type == "daily",
                    NurtureTask.action == action
                )
            )
            result_exist = await db.execute(stmt_exist)
            if result_exist.scalar():
                continue
                
            tasks_to_create.append({
                "action": action,
                "task_type": "daily",
                "execution_type": task_def.get("execution_type", "auto")
            })

        # 5. 写入数据库并分配时间
        if tasks_to_create:
            try:
                tz = pytz.timezone(account.target_timezone or "America/New_York")
            except:
                tz = pytz.timezone("America/New_York")
            
            now_target = datetime.now(tz)
            target_date = now_target.date()
            
            start_dt_target = tz.localize(datetime.combine(target_date, time(active_start_hour, 0)))
            end_dt_target = tz.localize(datetime.combine(target_date, time(active_end_hour, 0)))
            
            server_tz = datetime.now().astimezone().tzinfo
            start_dt_local = start_dt_target.astimezone(server_tz)
            end_dt_local = end_dt_target.astimezone(server_tz)
            
            if start_dt_local < datetime.now(server_tz):
                start_dt_local = datetime.now(server_tz) + timedelta(minutes=5)
            
            total_window_seconds = (end_dt_local - start_dt_local).total_seconds()
            if total_window_seconds <= 0:
                start_dt_local = datetime.now(server_tz) + timedelta(hours=1)
                total_window_seconds = 3600

            for task_data in tasks_to_create:
                random_seconds = random.randint(0, int(total_window_seconds))
                scheduled_time = start_dt_local + timedelta(seconds=random_seconds)
                scheduled_time_naive = scheduled_time.replace(tzinfo=None)

                db_task = NurtureTask(
                    fb_account_id=account.id,
                    day_number=account.nurture_day,
                    scheduled_date=today,
                    scheduled_time=scheduled_time_naive,
                    action=task_data["action"],
                    task_type=task_data["task_type"],
                    execution_type=task_data["execution_type"],
                    status="pending"
                )
                db.add(db_task)
                tasks_created += 1

    await db.commit()
    logger.info(f"生成养号任务完成，共生成 {tasks_created} 个任务")

async def execute_account_tasks(account_id: int):
    """
    执行指定账号的今日任务 (RPA 占位)
    """
    async with AsyncSessionLocal() as db:
        logger.info(f"开始执行账号 {account_id} 的任务...")
        
        # 获取今日待执行任务（包括 running 状态的任务，防止 check_and_execute_tasks 已修改状态但未执行）
        today = datetime.now().date()
        stmt = select(NurtureTask).where(
            and_(
                NurtureTask.fb_account_id == account_id,
                NurtureTask.scheduled_date == today,
                NurtureTask.status.in_(["pending", "running"]),
                NurtureTask.execution_type == "auto"
            )
        ).order_by(NurtureTask.scheduled_time)
        
        result = await db.execute(stmt)
        tasks = result.scalars().all()
        
        if not tasks:
            logger.info(f"账号 {account_id} 无待执行任务")
            return

        # 模拟执行
        for task in tasks:
            # 确保状态为 running
            if task.status == "pending":
                task.status = "running"
                await db.commit()
                
            logger.info(f"正在执行任务 {task.id}: {task.action}")
            
            # TODO: 调用 RPA 模块执行具体逻辑
            # await rpa_client.execute(task.action, ...)
            
            # 模拟执行耗时
            await asyncio.sleep(2)
            
            # 模拟成功
            task.status = "completed"
            task.executed_at = datetime.now()
            task.result_log = "Executed successfully (Simulation)"
            
            # 记录日志
            log = ActionLog(
                fb_account_id=account_id,
                task_id=task.id,
                action_type=task.action,
                level="INFO",
                message=f"任务 {task.action} 执行成功"
            )
            db.add(log)
            await db.commit() # 及时提交状态
            
        logger.info(f"账号 {account_id} 任务执行完毕")

async def check_and_execute_tasks():
    """
    检查并执行到期的养号任务
    """
    sched_config = await get_scheduler_config()
    max_concurrent = sched_config.get("max_concurrent_windows", 5)
    
    async with AsyncSessionLocal() as db:
        # 1. 检查当前正在执行的任务数量
        stmt_running_count = select(func.count(NurtureTask.id)).where(
            and_(
                NurtureTask.status == "running",
                NurtureTask.execution_type == "auto"
            )
        )
        result_running = await db.execute(stmt_running_count)
        current_running_tasks = result_running.scalar() or 0
        
        # 这里的并发限制是指“同时在跑的任务数”还是“同时在跑的账号数”？
        # 通常是账号数（浏览器窗口数）。
        # 我们假设一个账号同一时间只能跑一个任务（串行）。
        # 所以我们需要统计有多少个 distinct account_id 正在 running。
        # SQLite 的 count(distinct) 支持可能有限，但在 SQLAlchemy 中通常可用。
        # stmt_running_accounts = select(func.count(func.distinct(NurtureTask.fb_account_id))).where(
        #     and_(
        #         NurtureTask.status == "running",
        #         NurtureTask.execution_type == "auto"
        #     )
        # )
        # 简单起见，我们先查询所有 running 任务，然后在 Python 中去重 account_id
        stmt_running_tasks = select(NurtureTask.fb_account_id).where(
             and_(
                NurtureTask.status == "running",
                NurtureTask.execution_type == "auto"
            )
        )
        result_running_tasks = await db.execute(stmt_running_tasks)
        running_account_ids = set(result_running_tasks.scalars().all())
        current_running_accounts = len(running_account_ids)
        
        if current_running_accounts >= max_concurrent:
            logger.info(f"当前并发账号数 {current_running_accounts} 已达上限 {max_concurrent}，跳过本次调度")
            return

        available_slots = max_concurrent - current_running_accounts
        
        # 2. 获取到期的 pending 任务 (scheduled_time <= now)
        # 我们需要找到那些没有正在运行任务的账号，且有到期任务的账号
        now = datetime.now()
        
        # 子查询：正在运行的账号ID
        # running_subquery = select(NurtureTask.fb_account_id).where(NurtureTask.status == "running")
        
        stmt_pending = select(NurtureTask.fb_account_id).where(
            and_(
                NurtureTask.status == "pending",
                NurtureTask.scheduled_time <= now,
                NurtureTask.execution_type == "auto",
                NurtureTask.fb_account_id.notin_(running_account_ids) # 排除正在运行的账号
            )
        ).group_by(NurtureTask.fb_account_id).limit(available_slots)
        
        result_pending = await db.execute(stmt_pending)
        target_account_ids = result_pending.scalars().all()
        
        if not target_account_ids:
            return

        logger.info(f"触发调度：账号 {target_account_ids} 开始执行任务")
        
        for account_id in target_account_ids:
            # 标记该账号的所有 pending && 到期任务为 running
            # 注意：execute_account_tasks 会再次查询，但这里标记是为了占位
            stmt_update = select(NurtureTask).where(
                and_(
                    NurtureTask.fb_account_id == account_id,
                    NurtureTask.status == "pending",
                    NurtureTask.scheduled_time <= now,
                    NurtureTask.execution_type == "auto"
                )
            )
            result_update = await db.execute(stmt_update)
            tasks_to_run = result_update.scalars().all()
            
            if not tasks_to_run:
                continue

            for t in tasks_to_run:
                t.status = "running"
            await db.commit()
            
            # 异步启动执行
            # 注意：这里不 await，而是放飞异步任务
            asyncio.create_task(execute_account_tasks(account_id))

async def get_tasks_for_date(db: AsyncSession, date_obj: date):
    """获取指定日期的任务列表"""
    stmt = select(NurtureTask).where(NurtureTask.scheduled_date == date_obj)
    result = await db.execute(stmt)
    return result.scalars().all()

async def get_account_tasks(db: AsyncSession, account_id: int):
    """获取指定账号的任务历史"""
    stmt = select(NurtureTask).where(NurtureTask.fb_account_id == account_id).order_by(desc(NurtureTask.created_at))
    result = await db.execute(stmt)
    return result.scalars().all()

async def complete_manual_task(db: AsyncSession, task_id: int):
    """手动完成任务"""
    stmt = select(NurtureTask).where(NurtureTask.id == task_id)
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()
    if task:
        task.status = "completed"
        task.executed_at = datetime.now()
        task.result_log = "Manually completed"
        await db.commit()
        return task
    return None
