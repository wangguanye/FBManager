from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc, func, or_
from datetime import datetime, date, timedelta, time
import pytz
import random
import asyncio
from typing import List, Optional

from modules.asset.models import FBAccount
from modules.monitor.models import NurtureTask, ActionLog
from modules.monitor.service import create_alert
from modules.nurture.sop_loader import get_daily_tasks, get_once_tasks, is_task_completed
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

async def get_manual_timeout_config():
    try:
        with open("config.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        return config.get("manual_task_timeout", {})
    except Exception as e:
        logger.error(f"Failed to load manual timeout config: {e}")
        return {}

PRIORITY_STATUS_SCORE = 100
PRIORITY_MANUAL_OVERDUE_SCORE = 50
PRIORITY_NURTURE_DAY_7_SCORE = 30
PRIORITY_NURTURE_DAY_14_SCORE = 20
PRIORITY_INACTIVE_24H_SCORE = 40
PRIORITY_INACTIVE_12H_SCORE = 20
PRIORITY_INACTIVE_DEFAULT_HOURS = 9999
MIN_SCHEDULE_GAP_MINUTES = 5
MAX_SCHEDULE_GAP_MINUTES = 15
MIN_START_DELAY_MINUTES = 5
ACCOUNT_TASK_SPREAD_MINUTES = 30

def calculate_priority(account: FBAccount, has_overdue_manual: bool, now_utc: datetime) -> int:
    assert account is not None
    assert now_utc is not None
    score = 0
    if account.status == "投放养号中":
        score += PRIORITY_STATUS_SCORE
    if has_overdue_manual:
        score += PRIORITY_MANUAL_OVERDUE_SCORE
    nurture_day = account.nurture_day or 0
    if nurture_day <= 7:
        score += PRIORITY_NURTURE_DAY_7_SCORE
    elif nurture_day <= 14:
        score += PRIORITY_NURTURE_DAY_14_SCORE
    last_active_at = account.last_active_at
    if last_active_at and last_active_at.tzinfo:
        last_active_at = last_active_at.replace(tzinfo=None)
    hours_since_active = PRIORITY_INACTIVE_DEFAULT_HOURS
    if last_active_at:
        hours_since_active = (now_utc - last_active_at).total_seconds() / 3600
    if hours_since_active > 24:
        score += PRIORITY_INACTIVE_24H_SCORE
    elif hours_since_active > 12:
        score += PRIORITY_INACTIVE_12H_SCORE
    return score

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
    manual_timeout_config = await get_manual_timeout_config()
    block_hours = manual_timeout_config.get("block_hours", 72)
    warn_hours = manual_timeout_config.get("warn_hours", 24)
    overdue_threshold = datetime.utcnow() - timedelta(hours=warn_hours)
    stmt_overdue = select(NurtureTask.fb_account_id).where(
        and_(
            NurtureTask.task_type == "manual",
            NurtureTask.status == "pending",
            NurtureTask.created_at <= overdue_threshold
        )
    ).group_by(NurtureTask.fb_account_id)
    result_overdue = await db.execute(stmt_overdue)
    overdue_account_ids = set(result_overdue.scalars().all())
    now_utc = datetime.utcnow()
    
    # 活跃窗口配置
    active_start_hour = sched_config.get("active_window_start", 8)
    active_end_hour = sched_config.get("active_window_end", 22)
    
    tasks_created = 0
    
    accounts_sorted = sorted(
        accounts,
        key=lambda account: calculate_priority(account, account.id in overdue_account_ids, now_utc),
        reverse=True
    )
    last_scheduled_time = None
    for account in accounts_sorted:
        if not account.nurture_start_date:
            account.nurture_start_date = today

        day_number = (today - account.nurture_start_date).days + 1
        account.nurture_day = day_number
        db.add(account)

        tasks_to_create = []

        can_create_once = True
        if day_number > 1:
            prev_day = day_number - 1
            stmt_prev = select(func.count()).where(
                and_(
                    NurtureTask.fb_account_id == account.id,
                    NurtureTask.day_number == prev_day,
                    NurtureTask.task_type == "manual",
                    NurtureTask.status != "completed"
                )
            )
            result_prev = await db.execute(stmt_prev)
            pending_prev = result_prev.scalar()
            if pending_prev > 0:
                can_create_once = False

        if can_create_once and block_hours:
            block_threshold = datetime.utcnow() - timedelta(hours=block_hours)
            stmt_block = select(func.count()).where(
                and_(
                    NurtureTask.fb_account_id == account.id,
                    NurtureTask.task_type == "manual",
                    NurtureTask.status == "pending",
                    NurtureTask.created_at <= block_threshold
                )
            )
            result_block = await db.execute(stmt_block)
            if (result_block.scalar() or 0) > 0:
                can_create_once = False

        if can_create_once:
            for task_def in get_once_tasks(day_number):
                action = task_def.get("action")
                if not action:
                    continue
                if await is_task_completed(db, account.id, day_number, action):
                    continue
                stmt_exist = select(NurtureTask).where(
                    and_(
                        NurtureTask.fb_account_id == account.id,
                        NurtureTask.day_number == day_number,
                        NurtureTask.task_type.in_(["once", "manual"]),
                        NurtureTask.action == action
                    )
                )
                result_exist = await db.execute(stmt_exist)
                if result_exist.scalar():
                    continue
                execution_type = task_def.get("execution_type") or task_def.get("type") or "auto"
                task_type = "manual" if execution_type == "manual" else "once"
                tasks_to_create.append({
                    "action": action,
                    "task_type": task_type,
                    "execution_type": execution_type
                })

        for task_def in get_daily_tasks(day_number):
            action = task_def.get("action")
            if not action:
                continue
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
            execution_type = task_def.get("execution_type") or task_def.get("type") or "auto"
            tasks_to_create.append({
                "action": action,
                "task_type": "daily",
                "execution_type": execution_type
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
                start_dt_local = datetime.now(server_tz) + timedelta(minutes=MIN_START_DELAY_MINUTES)
            
            total_window_seconds = (end_dt_local - start_dt_local).total_seconds()
            if total_window_seconds <= 0:
                start_dt_local = datetime.now(server_tz) + timedelta(hours=1)
                total_window_seconds = 3600

            gap_minutes = random.randint(MIN_SCHEDULE_GAP_MINUTES, MAX_SCHEDULE_GAP_MINUTES)
            if last_scheduled_time and last_scheduled_time > start_dt_local:
                base_time = last_scheduled_time + timedelta(minutes=gap_minutes)
            else:
                base_time = start_dt_local
            if base_time > end_dt_local:
                base_time = end_dt_local - timedelta(minutes=MIN_SCHEDULE_GAP_MINUTES)
            if base_time < start_dt_local:
                base_time = start_dt_local
            last_scheduled_time = base_time
            task_spread_seconds = ACCOUNT_TASK_SPREAD_MINUTES * 60

            for task_data in tasks_to_create:
                random_seconds = random.randint(0, int(task_spread_seconds))
                scheduled_time = base_time + timedelta(seconds=random_seconds)
                if scheduled_time > end_dt_local:
                    scheduled_time = end_dt_local - timedelta(seconds=30)
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

from modules.rpa.executor import RPAExecutor
from sqlalchemy.orm import selectinload

async def execute_account_tasks(account_id: int):
    """
    执行指定账号的今日任务
    """
    async with AsyncSessionLocal() as db:
        logger.info(f"开始执行账号 {account_id} 的任务...")
        
        # 获取账号信息（含关联窗口）
        stmt_account = select(FBAccount).where(FBAccount.id == account_id).options(
            selectinload(FBAccount.browser_window),
            selectinload(FBAccount.proxy)
        )
        result_account = await db.execute(stmt_account)
        account = result_account.scalar_one_or_none()
        
        if not account:
            logger.error(f"账号 {account_id} 不存在")
            return

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

        executor = RPAExecutor()

        for task in tasks:
            # 确保状态为 running
            if task.status == "pending":
                task.status = "running"
                await db.commit()
                
            logger.info(f"正在执行任务 {task.id}: {task.action}")
            
            # 构建 RPA 动作
            # 简单映射：将 task.action (如 like_post) 映射为 rpa.like_post
            action_name = f"rpa.{task.action}"
            actions = [{"action": action_name, "params": {}}]
            
            try:
                await executor.enqueue_task(account, task, actions)
            except Exception as e:
                logger.error(f"Task {task.id} execution failed: {e}")
                task.status = "failed"
                task.result_log = str(e)
                task.retry_count += 1
                await db.commit()
            
        logger.info(f"账号 {account_id} 任务执行完毕")

async def execute_custom_action(account_id: int, action: str, params: dict | None) -> int:
    assert account_id > 0
    assert action
    async with AsyncSessionLocal() as db:
        stmt_account = select(FBAccount).where(FBAccount.id == account_id).options(
            selectinload(FBAccount.browser_window),
            selectinload(FBAccount.proxy)
        )
        result_account = await db.execute(stmt_account)
        account = result_account.scalar_one_or_none()
        if not account:
            raise ValueError("account_not_found")
        payload_params = params if isinstance(params, dict) else {}
        now = datetime.now()
        task = NurtureTask(
            fb_account_id=account_id,
            day_number=account.nurture_day or 0,
            scheduled_date=now.date(),
            scheduled_time=now,
            action=action,
            task_type="manual",
            execution_type="auto",
            status="running",
            result_log=None,
            retry_count=0
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)

    executor = RPAExecutor()
    actions = [{"action": f"rpa.{action}", "params": payload_params}]

    async def _safe_enqueue():
        try:
            await executor.enqueue_task(account, task, actions)
        except Exception as e:
            logger.error(f"Custom action enqueue failed: {e}")
            async with AsyncSessionLocal() as inner_db:
                db_task = await inner_db.get(NurtureTask, task.id)
                if db_task:
                    db_task.status = "failed"
                    db_task.result_log = str(e)
                    db_task.retry_count += 1
                    inner_db.add(db_task)
                    await inner_db.commit()

    asyncio.create_task(_safe_enqueue())
    return task.id

async def check_and_execute_tasks():
    """
    检查并执行到期的养号任务
    """
    sched_config = await get_scheduler_config()
    max_concurrent = sched_config.get("max_concurrent_windows", 5)
    max_concurrent = max(max_concurrent, 1)
    
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

async def get_scheduler_queue_status(db: AsyncSession):
    now = datetime.utcnow()
    stmt_running = select(NurtureTask, FBAccount).join(FBAccount, FBAccount.id == NurtureTask.fb_account_id).where(
        and_(
            NurtureTask.status == "running",
            NurtureTask.execution_type == "auto"
        )
    )
    result_running = await db.execute(stmt_running)
    running_items = []
    running_account_ids = set()
    for task, account in result_running.all():
        running_account_ids.add(account.id)
        started_at = task.scheduled_time or task.created_at
        running_items.append({
            "account": account.username or str(account.id),
            "task": task.action,
            "started_at": started_at
        })

    stmt_pending = select(NurtureTask, FBAccount).join(FBAccount, FBAccount.id == NurtureTask.fb_account_id).where(
        and_(
            NurtureTask.status == "pending",
            NurtureTask.execution_type == "auto"
        )
    )
    result_pending = await db.execute(stmt_pending)
    pending_map = {}
    for task, account in result_pending.all():
        if account.id in pending_map:
            existing_time = pending_map[account.id]["scheduled_time"]
            candidate_time = task.scheduled_time or task.created_at
            if existing_time and candidate_time and candidate_time < existing_time:
                pending_map[account.id] = {
                    "account": account,
                    "scheduled_time": candidate_time
                }
            continue
        pending_map[account.id] = {
            "account": account,
            "scheduled_time": task.scheduled_time or task.created_at
        }

    manual_timeout_config = await get_manual_timeout_config()
    warn_hours = manual_timeout_config.get("warn_hours", 24)
    overdue_threshold = now - timedelta(hours=warn_hours)
    stmt_overdue = select(NurtureTask.fb_account_id).where(
        and_(
            NurtureTask.task_type == "manual",
            NurtureTask.status == "pending",
            NurtureTask.created_at <= overdue_threshold
        )
    ).group_by(NurtureTask.fb_account_id)
    result_overdue = await db.execute(stmt_overdue)
    overdue_account_ids = set(result_overdue.scalars().all())

    queued_items = []
    for item in pending_map.values():
        account = item["account"]
        scheduled_time = item["scheduled_time"]
        priority_score = calculate_priority(account, account.id in overdue_account_ids, now)
        queued_items.append({
            "account": account.username or str(account.id),
            "priority": priority_score,
            "estimated_start": scheduled_time
        })
    queued_items.sort(key=lambda item: item["priority"], reverse=True)

    sched_config = await get_scheduler_config()
    max_concurrent = max(int(sched_config.get("max_concurrent_windows", 5)), 1)
    current_concurrent = len(running_account_ids)
    return {
        "running": running_items,
        "queued": queued_items,
        "max_concurrent": max_concurrent,
        "current_concurrent": current_concurrent
    }

async def set_scheduler_max_concurrent(value: int) -> int:
    assert value is not None
    value = int(value)
    if value < 1 or value > 10:
        raise ValueError("max_concurrent_out_of_range")
    try:
        with open("config.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except Exception:
        config = {}
    scheduler_config = config.get("scheduler", {})
    scheduler_config["max_concurrent_windows"] = value
    config["scheduler"] = scheduler_config
    with open("config.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)
    RPAExecutor.set_max_concurrent(value)
    return value

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

async def check_manual_task_timeout():
    """
    检查手动任务超时并记录警告
    """
    logger.info("Checking for overdue manual tasks...")
    async with AsyncSessionLocal() as db:
        manual_timeout_config = await get_manual_timeout_config()
        warn_hours = manual_timeout_config.get("warn_hours", 24)
        alert_hours = manual_timeout_config.get("alert_hours", 48)
        block_hours = manual_timeout_config.get("block_hours", 72)
        now = datetime.utcnow()

        stmt = select(NurtureTask).where(
            and_(
                NurtureTask.task_type == "manual",
                NurtureTask.status == "pending"
            )
        )
        result = await db.execute(stmt)
        pending_tasks = result.scalars().all()

        async def has_timeout_log(task_id: int, level: str) -> bool:
            stmt_log = select(ActionLog.id).where(
                and_(
                    ActionLog.task_id == task_id,
                    ActionLog.action_type == "manual_timeout",
                    ActionLog.level == level
                )
            ).limit(1)
            res_log = await db.execute(stmt_log)
            return res_log.scalar_one_or_none() is not None

        for task in pending_tasks:
            if not task.created_at:
                continue
            hours_elapsed = (now - task.created_at).total_seconds() / 3600
            timeout_days = max(1, int(hours_elapsed // 24))

            if block_hours and hours_elapsed >= block_hours:
                if not await has_timeout_log(task.id, "ERROR"):
                    log_entry = ActionLog(
                        fb_account_id=task.fb_account_id,
                        task_id=task.id,
                        action_type="manual_timeout",
                        level="ERROR",
                        message=f"人工待办已超时 {timeout_days} 天，后续一次性任务已暂停"
                    )
                    db.add(log_entry)
                logger.error(f"Manual task {task.id} blocked after {hours_elapsed:.2f}h")
            elif alert_hours and hours_elapsed >= alert_hours:
                if not await has_timeout_log(task.id, "WARN"):
                    log_entry = ActionLog(
                        fb_account_id=task.fb_account_id,
                        task_id=task.id,
                        action_type="manual_timeout",
                        level="WARN",
                        message=f"人工待办已超时 {timeout_days} 天"
                    )
                    db.add(log_entry)
                await create_alert(
                    db,
                    task.fb_account_id,
                    "WARN",
                    "人工待办超时",
                    f"人工待办已超时 {timeout_days} 天"
                )
                logger.warning(f"Manual task {task.id} alert after {hours_elapsed:.2f}h")

            if warn_hours and hours_elapsed >= warn_hours:
                timeout_log = f"manual_timeout: 已超时 {timeout_days} 天"
                if task.result_log != timeout_log:
                    task.result_log = timeout_log
                    db.add(task)

        await db.commit()
