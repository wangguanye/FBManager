import asyncio
from typing import List, Dict, Any
from loguru import logger
from playwright.async_api import async_playwright
from datetime import datetime, timedelta
import yaml

from modules.rpa.base import ACTION_REGISTRY, BaseAction
from modules.rpa.browser_client import BitBrowserClient
from modules.monitor.models import ActionLog, NurtureTask
from modules.monitor.service import create_alert
from modules.asset.models import FBAccount, ProxyIP
from core.cascade import cascade_on_ban
from core.scheduler import pause_scheduler
from db.database import AsyncSessionLocal
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
import modules.rpa.actions

class RPAExecutor:
    def __init__(self):
        self.browser_client = BitBrowserClient()
        max_concurrent = self._load_max_concurrent()
        if not hasattr(RPAExecutor, "_semaphore"):
            RPAExecutor._semaphore = asyncio.Semaphore(max_concurrent)
            RPAExecutor._max_concurrent = max_concurrent
        elif getattr(RPAExecutor, "_max_concurrent", None) != max_concurrent:
            RPAExecutor._semaphore = asyncio.Semaphore(max_concurrent)
            RPAExecutor._max_concurrent = max_concurrent
        self.semaphore = RPAExecutor._semaphore

    def _load_max_concurrent(self) -> int:
        try:
            with open("config.yaml", "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            scheduler_config = config.get("scheduler", {})
            max_concurrent = int(scheduler_config.get("max_concurrent_windows", 5))
            return max_concurrent if max_concurrent > 0 else 5
        except Exception:
            return 5

    async def run_task(self, account, task, actions: List[Dict]):
        """
        Execute a list of actions for an account.
        :param account: FBAccount object
        :param task: NurtureTask object (optional, for logging context)
        :param actions: List of dicts, e.g. [{"action": "rpa.scroll_feed", "params": {...}}]
        """
        assert isinstance(actions, list)

        if account.status not in ["养号中", "投放养号中"]:
            await self._handle_precheck_failure(account, task, "account_status_not_allowed", "WARN")
            return

        if not account.proxy_id or not account.browser_window_id:
            await self._handle_precheck_failure(account, task, "missing_proxy_or_window", "ERROR")
            return

        if not await self.browser_client.check_alive():
            pause_scheduler()
            await self._handle_precheck_failure(account, task, "bitbrowser_not_running", "ERROR")
            return

        if not account.browser_window:
            await self._handle_precheck_failure(account, task, "browser_window_not_loaded", "ERROR")
            return

        window_id = account.browser_window.bit_window_id
        if not window_id:
            await self._handle_precheck_failure(account, task, "missing_bit_window_id", "ERROR")
            return

        async with self.semaphore:
            logger.info(f"Starting RPA task for account {account.username} (Window {window_id})")

            playwright = None
            browser = None
            overall_success = True
            failure_message = ""

            try:
                res = await self.browser_client.open_browser(window_id)
                ws_endpoint = res.get("ws")
                if not ws_endpoint:
                    await self._handle_task_failure(account, task, "missing_ws_endpoint")
                    return

                playwright = await async_playwright().start()
                browser = await playwright.chromium.connect_over_cdp(ws_endpoint)

                if browser.contexts:
                    context = browser.contexts[0]
                else:
                    context = await browser.new_context()

                if context.pages:
                    page = context.pages[0]
                else:
                    page = await context.new_page()

                stop_remaining_tasks = False
                for action_config in actions:
                    action_id = action_config.get("action")
                    params = action_config.get("params", {})
                    params = {**params, "account_id": account.id}

                    action_cls = ACTION_REGISTRY.get(action_id)
                    if not action_cls:
                        await self._write_action_log(account.id, task.id if task else None, action_id, "WARN", "action_not_found")
                        overall_success = False
                        failure_message = "action_not_found"
                        continue

                    action_instance = action_cls()
                    logger.info(f"Executing action: {action_id}")

                    action_failed = False
                    action_message = ""
                    exception_raised = False

                    try:
                        result = await action_instance.execute(page, params, logger)
                        action_success = result.get("success", False)
                        action_message = result.get("message", "")
                        action_failed = not action_success
                        if action_id == "rpa.check_status":
                            check_data = result.get("data", {})
                            check_status = check_data.get("status")
                            if check_status:
                                action_message = check_status
                            if check_status == "disabled":
                                logger.critical(f"Account {account.id} is DISABLED!")
                            elif check_status in ["verification_required", "suspicious"]:
                                logger.warning(f"Account {account.id} requires verification.")
                            await self._handle_check_status_post(account.id, check_status)

                    except Exception as e:
                        exception_raised = True
                        action_failed = True
                        action_message = str(e)
                        logger.error(f"Action {action_id} failed with exception: {e}")

                    log_level = "INFO"
                    if action_failed:
                        log_level = "ERROR" if exception_raised else "WARN"

                    await self._write_action_log(
                        account.id,
                        task.id if task else None,
                        action_id,
                        log_level,
                        action_message or "action_completed"
                    )

                    if action_failed:
                        overall_success = False
                        failure_message = action_message or "action_failed"
                        if await self._apply_account_failure_circuit(account.id):
                            stop_remaining_tasks = True
                        await self._apply_proxy_failure_circuit(account.proxy_id)

                    if stop_remaining_tasks:
                        break

            except Exception as e:
                overall_success = False
                failure_message = str(e)
                logger.error(f"RPA Execution failed: {e}")
            finally:
                if browser:
                    await browser.close()
                if playwright:
                    await playwright.stop()
                if window_id:
                    await self.browser_client.close_browser(window_id)

            if overall_success and not stop_remaining_tasks:
                await self._handle_task_success(account, task, "task_completed")
            else:
                await self._handle_task_failure(account, task, failure_message or "task_failed")

    async def _handle_precheck_failure(self, account, task, message: str, level: str) -> None:
        await self._write_action_log(account.id, task.id if task else None, task.action if task else "precheck", level, message)
        if message == "bitbrowser_not_running":
            async with AsyncSessionLocal() as db:
                await create_alert(
                    db,
                    account.id,
                    "ERROR",
                    "比特浏览器未运行",
                    f"账号 {account.username} 无法连接比特浏览器，调度已暂停"
                )
                await db.commit()
        await self._handle_task_failure(account, task, message)

    async def _handle_task_success(self, account, task, message: str) -> None:
        if not task:
            return
        async with AsyncSessionLocal() as db:
            db_task = await db.get(NurtureTask, task.id)
            if not db_task:
                return
            db_task.status = "completed"
            db_task.executed_at = datetime.utcnow()
            db_task.result_log = message
            db.add(db_task)
            await db.commit()

    async def _handle_task_failure(self, account, task, message: str) -> None:
        if not task:
            return
        async with AsyncSessionLocal() as db:
            db_task = await db.get(NurtureTask, task.id)
            if not db_task:
                return
            db_task.status = "failed"
            db_task.executed_at = datetime.utcnow()
            db_task.result_log = message
            db_task.retry_count += 1
            db.add(db_task)
            if db_task.retry_count >= 3:
                db_account = await db.get(FBAccount, account.id)
                if db_account:
                    db_account.status = "abnormal"
                    db.add(db_account)
            await db.commit()

    async def _write_action_log(self, account_id: int, task_id: int | None, action_type: str, level: str, message: str) -> None:
        async with AsyncSessionLocal() as db:
            log = ActionLog(
                fb_account_id=account_id,
                task_id=task_id,
                action_type=action_type,
                level=level,
                message=message[:500]
            )
            db.add(log)
            await db.commit()

    async def _handle_check_status_post(self, account_id: int, check_status: str | None) -> None:
        if not check_status:
            return
        if check_status == "disabled":
            async with AsyncSessionLocal() as db:
                await cascade_on_ban(db, account_id)
                await db.commit()
            return
        if check_status in ["verification_required", "suspicious"]:
            if check_status == "verification_required":
                await self._mark_account_abnormal(account_id, "检测到账号需要验证")
            else:
                await self._mark_account_abnormal(account_id, "检测到账号异常登录")
            await self._check_consecutive_unhealthy(account_id)
            return
        if check_status != "healthy":
            await self._check_consecutive_unhealthy(account_id)

    async def _mark_account_abnormal(self, account_id: int, message: str) -> None:
        async with AsyncSessionLocal() as db:
            account = await db.get(FBAccount, account_id)
            if not account:
                return
            account.status = "abnormal"
            db.add(account)
            await self._cancel_pending_tasks(db, account_id)
            await self._ensure_manual_verification_task(db, account, message)
            log = ActionLog(
                fb_account_id=account_id,
                action_type="ACCOUNT_ABNORMAL",
                level="ERROR",
                message=message
            )
            db.add(log)
            await create_alert(
                db,
                account_id,
                "ERROR",
                "账号验证异常",
                message
            )
            await db.commit()

    async def _cancel_pending_tasks(self, db: AsyncSession, account_id: int) -> None:
        today = datetime.utcnow().date()
        stmt = select(NurtureTask).where(
            NurtureTask.fb_account_id == account_id,
            NurtureTask.scheduled_date == today,
            NurtureTask.status.in_(["pending", "running"])
        )
        result = await db.execute(stmt)
        tasks = result.scalars().all()
        for task in tasks:
            task.status = "cancelled"
            db.add(task)

    async def _ensure_manual_verification_task(self, db: AsyncSessionLocal, account: FBAccount, message: str) -> None:
        today = datetime.utcnow().date()
        stmt = select(NurtureTask).where(
            NurtureTask.fb_account_id == account.id,
            NurtureTask.scheduled_date == today,
            NurtureTask.task_type == "manual",
            NurtureTask.action == "manual_verification",
            NurtureTask.status.in_(["pending", "in_progress"])
        )
        result = await db.execute(stmt)
        if result.scalar_one_or_none():
            return
        now = datetime.utcnow()
        db_task = NurtureTask(
            fb_account_id=account.id,
            day_number=account.nurture_day,
            scheduled_date=today,
            scheduled_time=now,
            action="manual_verification",
            task_type="manual",
            execution_type="manual",
            status="pending",
            result_log=message
        )
        db.add(db_task)

    async def _check_consecutive_unhealthy(self, account_id: int) -> None:
        today = datetime.utcnow().date()
        since_date = today - timedelta(days=2)
        async with AsyncSessionLocal() as db:
            stmt = select(ActionLog).where(
                ActionLog.fb_account_id == account_id,
                ActionLog.action_type == "rpa.check_status",
                func.date(ActionLog.created_at) >= since_date
            ).order_by(ActionLog.created_at.desc())
            result = await db.execute(stmt)
            logs = result.scalars().all()
            status_by_date = {}
            for log in logs:
                log_date = log.created_at.date()
                if log_date not in status_by_date:
                    status_by_date[log_date] = log.message
            if len(status_by_date) < 3:
                return
            last_three = [status_by_date.get(today - timedelta(days=offset)) for offset in range(3)]
            if all(item and item != "healthy" for item in last_three):
                account = await db.get(FBAccount, account_id)
                if not account:
                    return
                account.status = "abnormal"
                db.add(account)
                log = ActionLog(
                    fb_account_id=account_id,
                    action_type="ACCOUNT_ABNORMAL",
                    level="ERROR",
                    message="连续 3 天检测到异常状态"
                )
                db.add(log)
                await db.commit()

    async def _apply_account_failure_circuit(self, account_id: int) -> bool:
        today = datetime.utcnow().date()
        async with AsyncSessionLocal() as db:
            stmt = select(func.count()).where(
                ActionLog.fb_account_id == account_id,
                ActionLog.level == "ERROR",
                func.date(ActionLog.created_at) == today
            )
            result = await db.execute(stmt)
            failure_count = result.scalar() or 0
            if failure_count < 3:
                return False
            account = await db.get(FBAccount, account_id)
            if not account:
                return False
            account.status = "abnormal"
            db.add(account)
            await self._cancel_pending_tasks(db, account_id)
            log = ActionLog(
                fb_account_id=account_id,
                action_type="CIRCUIT_BREAKER",
                level="ERROR",
                message="当日失败次数达到上限，已停止剩余任务"
            )
            db.add(log)
            await db.commit()
            return True

    async def _apply_proxy_failure_circuit(self, proxy_id: int | None) -> None:
        if not proxy_id:
            return
        async with AsyncSessionLocal() as db:
            stmt = select(ActionLog.fb_account_id).join(
                FBAccount, FBAccount.id == ActionLog.fb_account_id
            ).where(
                FBAccount.proxy_id == proxy_id,
                ActionLog.level == "ERROR"
            ).order_by(ActionLog.created_at.desc()).limit(10)
            result = await db.execute(stmt)
            account_ids = []
            for account_id in result.scalars().all():
                if account_id not in account_ids:
                    account_ids.append(account_id)
                if len(account_ids) >= 2:
                    break
            if len(account_ids) < 2:
                return
            proxy = await db.get(ProxyIP, proxy_id)
            if not proxy:
                return
            if proxy.status == "suspicious":
                return
            proxy.status = "suspicious"
            db.add(proxy)
            log = ActionLog(
                fb_account_id=account_ids[0],
                action_type="PROXY_SUSPICIOUS",
                level="WARN",
                message=f"代理 {proxy.host} 关联账号连续失败"
            )
            db.add(log)
            await create_alert(
                db,
                account_ids[0],
                "WARN",
                "代理超时异常",
                f"代理 {proxy.host} 关联账号连续失败"
            )
            await db.commit()
