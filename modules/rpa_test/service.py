import asyncio
import json
import time
import traceback
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import AsyncSessionLocal
from modules.asset.models import BrowserWindow, FBAccount
from modules.monitor.models import ActionLog
from modules.rpa.base import ActionRegistry
from modules.rpa.browser_client import BitBrowserClient, BitBrowserNotRunningError
from modules.rpa_test.models import RpaTestResult

# Ensure action modules are imported and registered.
import modules.rpa.actions  # noqa: F401


class RpaTestService:
    """RPA 行为模块冒烟测试服务。"""

    _test_logs: Dict[str, List[Dict[str, str]]] = {}
    _test_states: Dict[str, Dict[str, Any]] = {}
    _max_log_lines = 1000

    @classmethod
    async def get_modules(cls, db: AsyncSession) -> List[Dict[str, Any]]:
        _ = db
        modules: List[Dict[str, Any]] = []
        for full_action_id, action_cls in sorted(ActionRegistry.get_all().items(), key=lambda item: item[0]):
            schema = cls._extract_params_schema(action_cls)
            module_meta = cls._extract_module_meta(action_cls)
            display_action_id = cls._display_action_id(full_action_id)
            modules.append(
                {
                    "action_id": display_action_id,
                    "name": getattr(action_cls, "NAME", None) or module_meta.get("name") or display_action_id,
                    "description": getattr(action_cls, "DESCRIPTION", "") or module_meta.get("description", ""),
                    "params_schema": schema,
                }
            )
        return modules

    @classmethod
    async def start_single(
        cls,
        account_id: int,
        action_id: str,
        params: Optional[Dict[str, Any]] = None,
        keep_open: bool = False,
    ) -> Dict[str, Any]:
        test_id = uuid.uuid4().hex[:8]
        cls._test_logs[test_id] = []
        cls._set_state(test_id, "running", None, action_id)
        cls._log(test_id, "INFO", f"测试任务已创建，模块: {action_id}")
        asyncio.create_task(
            cls._run_single_background(
                test_id=test_id,
                account_id=account_id,
                action_id=action_id,
                params=params or {},
                keep_open=keep_open,
            )
        )
        return {"test_id": test_id, "status": "running"}

    @classmethod
    async def _run_single_background(
        cls,
        test_id: str,
        account_id: int,
        action_id: str,
        params: Dict[str, Any],
        keep_open: bool,
    ) -> None:
        async with AsyncSessionLocal() as db:
            try:
                await cls._run_single(
                    db=db,
                    account_id=account_id,
                    action_id=action_id,
                    params=params,
                    keep_open=keep_open,
                    test_id=test_id,
                )
            except Exception as exc:
                logger.exception("RPA test background runner crashed")
                fallback_result = {
                    "test_id": test_id,
                    "action_id": cls._display_action_id(action_id),
                    "success": False,
                    "message": str(exc),
                    "duration_seconds": 0.0,
                    "error_detail": traceback.format_exc(),
                }
                cls._log(test_id, "ERROR", f"后台执行异常: {exc}")
                cls._set_state(test_id, "failed", fallback_result, action_id)

    @classmethod
    async def run_single(
        cls,
        db: AsyncSession,
        account_id: int,
        action_id: str,
        params: Optional[Dict[str, Any]] = None,
        keep_open: bool = False,
    ) -> Dict[str, Any]:
        test_id = uuid.uuid4().hex[:8]
        cls._test_logs[test_id] = []
        cls._set_state(test_id, "running", None, action_id)
        return await cls._run_single(
            db=db,
            account_id=account_id,
            action_id=action_id,
            params=params or {},
            keep_open=keep_open,
            test_id=test_id,
        )

    @classmethod
    async def _run_single(
        cls,
        db: AsyncSession,
        account_id: int,
        action_id: str,
        params: Dict[str, Any],
        keep_open: bool,
        test_id: Optional[str],
    ) -> Dict[str, Any]:
        normalized_action_id = cls._normalize_action_id(action_id)
        display_action_id = cls._display_action_id(normalized_action_id)

        success = False
        message = ""
        error_detail = None
        duration = 0.0
        start = time.perf_counter()

        bit_window_id = None
        playwright = None
        browser = None
        client = BitBrowserClient()
        result: Dict[str, Any] = {}

        try:
            account_stmt = select(FBAccount).where(FBAccount.id == account_id, FBAccount.is_deleted == False)
            account_result = await db.execute(account_stmt)
            account = account_result.scalar_one_or_none()
            if not account:
                raise ValueError("账号不存在")
            if not account.browser_window_id:
                raise ValueError("账号未绑定窗口")

            window = await db.get(BrowserWindow, account.browser_window_id)
            if not window or not window.bit_window_id:
                raise ValueError("账号绑定窗口无效")

            bit_window_id = window.bit_window_id

            if not await client.check_alive():
                raise BitBrowserNotRunningError("BitBrowser 未运行")

            cls._log(test_id, "INFO", f"正在打开窗口 {bit_window_id}...")
            open_result = await client.open_browser(bit_window_id)
            ws_endpoint = open_result.get("ws")
            if not ws_endpoint:
                raise RuntimeError("未获取到浏览器 WS 端点")

            cls._log(test_id, "INFO", "Playwright 正在接管浏览器...")
            from playwright.async_api import async_playwright

            playwright = await async_playwright().start()
            browser = await playwright.chromium.connect_over_cdp(ws_endpoint)

            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = context.pages[0] if context.pages else await context.new_page()

            action_cls = ActionRegistry.get(normalized_action_id)
            if not action_cls:
                raise ValueError(f"未找到模块: {display_action_id}")

            effective_params = dict(params or {})
            effective_params.setdefault("account_id", account.id)
            cls._log(test_id, "INFO", f"执行模块 {display_action_id}，参数: {json.dumps(effective_params, ensure_ascii=False)}")

            action_instance = action_cls()
            action_result = await action_instance.execute(page, effective_params, logger)

            if isinstance(action_result, dict):
                success = bool(action_result.get("success", True))
                message = str(action_result.get("message", "执行完成"))
            else:
                success = True
                message = "执行完成"

            cls._log(test_id, "INFO" if success else "ERROR", f"模块执行{'成功' if success else '失败'}: {message}")

        except Exception as exc:
            success = False
            message = str(exc)
            error_detail = traceback.format_exc()
            cls._log(test_id, "ERROR", f"执行异常: {message}")

        finally:
            duration = round(time.perf_counter() - start, 2)

            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

            if playwright:
                try:
                    await playwright.stop()
                except Exception:
                    pass

            if bit_window_id:
                if keep_open:
                    cls._log(test_id, "INFO", "窗口保持打开")
                else:
                    try:
                        await client.close_browser(bit_window_id)
                        cls._log(test_id, "INFO", "窗口已关闭")
                    except Exception as close_exc:
                        cls._log(test_id, "WARN", f"关闭窗口失败: {close_exc}")

            try:
                await client.client.aclose()
            except Exception:
                pass

            result = await cls._persist_result(
                db=db,
                test_id=test_id,
                action_id=display_action_id,
                account_id=account_id,
                params=params,
                success=success,
                message=message,
                duration_seconds=duration,
                error_detail=error_detail,
            )
            cls._log(test_id, "INFO", f"测试完成，耗时 {duration:.2f}s")

        cls._set_state(test_id, "completed" if success else "failed", result, display_action_id)
        return result

    @classmethod
    async def run_all(
        cls,
        db: AsyncSession,
        account_id: int,
        keep_open: bool = False,
    ) -> Dict[str, Any]:
        modules = await cls.get_modules(db)
        results: List[Dict[str, Any]] = []

        for index, module_item in enumerate(modules):
            default_params = cls._build_default_params(module_item.get("params_schema") or {})
            should_keep_open = keep_open and index == len(modules) - 1
            module_result = await cls.run_single(
                db=db,
                account_id=account_id,
                action_id=module_item["action_id"],
                params=default_params,
                keep_open=should_keep_open,
            )
            module_result["name"] = module_item.get("name") or module_item["action_id"]
            results.append(module_result)

        passed = sum(1 for item in results if item.get("success"))
        failed = len(results) - passed
        return {
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "results": results,
        }

    @classmethod
    async def list_results(cls, db: AsyncSession, limit: int = 100) -> List[Dict[str, Any]]:
        stmt = select(RpaTestResult).order_by(RpaTestResult.tested_at.desc()).limit(limit)
        query_result = await db.execute(stmt)
        rows = query_result.scalars().all()
        return [cls._serialize_result_row(row) for row in rows]

    @classmethod
    async def get_latest_result(cls, db: AsyncSession, action_id: str) -> Dict[str, Any]:
        display_action_id = cls._display_action_id(action_id)
        stmt = (
            select(RpaTestResult)
            .where(RpaTestResult.action_id == display_action_id)
            .order_by(RpaTestResult.tested_at.desc())
            .limit(1)
        )
        query_result = await db.execute(stmt)
        row = query_result.scalar_one_or_none()
        if not row:
            return {"action_id": display_action_id, "tested": False}

        payload = cls._serialize_result_row(row)
        payload["tested"] = True
        return payload

    @classmethod
    def get_logs(cls, test_id: str) -> Dict[str, Any]:
        state = cls._test_states.get(test_id, {})
        return {
            "test_id": test_id,
            "status": state.get("status", "unknown"),
            "logs": cls._test_logs.get(test_id, []),
            "result": state.get("result"),
            "action_id": state.get("action_id"),
            "updated_at": state.get("updated_at"),
        }

    @classmethod
    async def _persist_result(
        cls,
        db: AsyncSession,
        test_id: Optional[str],
        action_id: str,
        account_id: int,
        params: Dict[str, Any],
        success: bool,
        message: str,
        duration_seconds: float,
        error_detail: Optional[str],
    ) -> Dict[str, Any]:
        params_json = json.dumps(params or {}, ensure_ascii=False)
        row = RpaTestResult(
            action_id=action_id,
            account_id=account_id,
            params=params_json,
            success=success,
            message=message,
            duration_seconds=duration_seconds,
            error_detail=error_detail,
        )
        db.add(row)

        action_log = ActionLog(
            fb_account_id=account_id,
            task_id=None,
            action_type=f"test.{action_id}",
            level="INFO" if success else "ERROR",
            message=(message or "")[:500],
        )
        db.add(action_log)

        try:
            await db.commit()
            await db.refresh(row)
        except Exception as db_exc:
            await db.rollback()
            logger.exception("Failed to persist RPA test result")
            cls._log(test_id, "ERROR", f"写入测试结果失败: {db_exc}")

        return {
            "test_id": test_id,
            "id": row.id,
            "action_id": action_id,
            "account_id": account_id,
            "success": success,
            "message": message,
            "duration_seconds": duration_seconds,
            "error_detail": error_detail,
            "tested_at": row.tested_at.isoformat() if row.tested_at else None,
        }

    @classmethod
    def _extract_module_meta(cls, action_cls: Any) -> Dict[str, Any]:
        module_name = getattr(action_cls, "__module__", None)
        if not module_name:
            return {}
        module = __import__(module_name, fromlist=["META"])
        meta = getattr(module, "META", None)
        return meta if isinstance(meta, dict) else {}

    @classmethod
    def _extract_params_schema(cls, action_cls: Any) -> Dict[str, Any]:
        schema = getattr(action_cls, "PARAMS_SCHEMA", None)
        if isinstance(schema, dict):
            return schema

        default_params = getattr(action_cls, "DEFAULT_PARAMS", None)
        if isinstance(default_params, dict):
            converted = {}
            for key, value in default_params.items():
                converted[key] = {"default": value, "type": type(value).__name__}
            return converted

        module_meta = cls._extract_module_meta(action_cls)
        meta_schema = module_meta.get("params_schema")
        return meta_schema if isinstance(meta_schema, dict) else {}

    @classmethod
    def _build_default_params(cls, params_schema: Dict[str, Any]) -> Dict[str, Any]:
        defaults: Dict[str, Any] = {}
        for key, schema in params_schema.items():
            if not isinstance(schema, dict):
                continue
            if "default" in schema:
                defaults[key] = schema["default"]
                continue
            if schema.get("type") == "number":
                defaults[key] = 0
                continue
            if schema.get("type") == "select" and isinstance(schema.get("options"), list):
                defaults[key] = schema["options"][0] if schema["options"] else ""
                continue
            defaults[key] = ""
        return defaults

    @classmethod
    def _set_state(
        cls,
        test_id: Optional[str],
        status: str,
        result: Optional[Dict[str, Any]],
        action_id: Optional[str],
    ) -> None:
        if not test_id:
            return
        cls._test_states[test_id] = {
            "status": status,
            "result": result,
            "action_id": cls._display_action_id(action_id),
            "updated_at": datetime.utcnow().isoformat(),
        }

    @classmethod
    def _normalize_action_id(cls, action_id: str) -> str:
        action_value = (action_id or "").strip()
        if action_value.startswith("rpa."):
            return action_value
        return f"rpa.{action_value}"

    @classmethod
    def _display_action_id(cls, action_id: Optional[str]) -> str:
        if not action_id:
            return ""
        action_value = str(action_id)
        return action_value[4:] if action_value.startswith("rpa.") else action_value

    @classmethod
    def _log(cls, test_id: Optional[str], level: str, message: str) -> None:
        if not test_id:
            logger.info(f"[TEST] [{level}] {message}")
            return

        entry = {
            "time": datetime.utcnow().isoformat(),
            "level": level,
            "message": message,
        }
        logs = cls._test_logs.setdefault(test_id, [])
        logs.append(entry)
        if len(logs) > cls._max_log_lines:
            cls._test_logs[test_id] = logs[-cls._max_log_lines :]

        logger.info(f"[TEST:{test_id}] [{level}] {message}")

    @classmethod
    def _serialize_result_row(cls, row: RpaTestResult) -> Dict[str, Any]:
        return {
            "id": row.id,
            "action_id": row.action_id,
            "account_id": row.account_id,
            "params": row.params,
            "success": row.success,
            "message": row.message,
            "duration_seconds": row.duration_seconds,
            "error_detail": row.error_detail,
            "tested_at": row.tested_at.isoformat() if row.tested_at else None,
        }
