import asyncio
import httpx
import os
import tempfile
import uuid
import sys
import types
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, delete, text
from db.database import AsyncSessionLocal, Base, sync_engine
stub_scheduler = types.ModuleType("core.scheduler")
async def pause_scheduler():
    return None
async def resume_scheduler():
    return None
stub_scheduler.pause_scheduler = pause_scheduler
stub_scheduler.resume_scheduler = resume_scheduler
sys.modules["core.scheduler"] = stub_scheduler
stub_pyotp = types.ModuleType("pyotp")
class _StubTOTP:
    def __init__(self, secret):
        self.secret = secret
    def now(self):
        return "000000"
stub_pyotp.TOTP = _StubTOTP
sys.modules["pyotp"] = stub_pyotp

from modules.asset.models import CommentPool, AvatarAsset, FBAccount, ProxyIP, BrowserWindow
from modules.asset.service import pick_comment, pick_avatar
from modules.monitor.models import ActionLog, NurtureTask, Alert
from modules.nurture.service import generate_daily_tasks, check_manual_task_timeout
from modules.nurture.sop_loader import load_sop_for_day
from modules.rpa.base import ACTION_REGISTRY
from modules.rpa.executor import RPAExecutor
import modules.rpa.actions

BASE_URL = os.environ.get("FBM_BASE_URL", "http://127.0.0.1:8000")
TEST_LANGUAGE = "en"
TIMEOUT_HOURS = 73
EXPECTED_ACTION_COUNT = 15
CONCURRENCY_TASKS = 6
BATCH_IMPORT_COUNT = 10
AVATAR_UPLOAD_COUNT = 1
CASCADE_CONTEXT = {}
SCHEMA_STATE = {}

def unwrap_response(payload):
    if isinstance(payload, dict) and "code" in payload and "data" in payload:
        return payload.get("data")
    return payload

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def ensure_tables():
    Base.metadata.create_all(bind=sync_engine)

async def table_exists(db, table_name):
    result = await db.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"), {"name": table_name})
    return result.scalar_one_or_none() is not None

async def get_table_columns(db, table_name):
    result = await db.execute(text(f"PRAGMA table_info({table_name})"))
    return {row[1] for row in result.fetchall()}

async def check_schema():
    state = {}
    async with AsyncSessionLocal() as db:
        for table_name in ["comment_pool", "alerts", "nurture_tasks", "action_logs"]:
            exists = await table_exists(db, table_name)
            columns = set()
            if exists:
                columns = await get_table_columns(db, table_name)
            state[table_name] = {"exists": exists, "columns": columns}
    return state

def require_table(table_name):
    table = SCHEMA_STATE.get(table_name) or {}
    if not table.get("exists"):
        raise RuntimeError(f"{table_name} 表不存在，请先初始化数据库")

def require_column(table_name, column_name):
    table = SCHEMA_STATE.get(table_name) or {}
    if not table.get("exists"):
        raise RuntimeError(f"{table_name} 表不存在，请先初始化数据库")
    columns = table.get("columns") or set()
    if column_name not in columns:
        raise RuntimeError(f"{table_name} 缺少字段 {column_name}，请迁移数据库")

async def http_json(method, path, json_data=None, data=None, files=None):
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.request(method, f"{BASE_URL}{path}", json=json_data, data=data, files=files)
            return resp
    except Exception as e:
        raise RuntimeError(f"请求失败: {e}")

def assert_status(resp, expected):
    if resp.status_code != expected:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}")

def get_json(resp):
    try:
        return resp.json()
    except Exception as e:
        raise RuntimeError(f"JSON 解析失败: {e}")

async def create_account_via_api(suffix):
    account_data = {
        "username": f"phase2_user_{suffix}",
        "password": "password123",
        "email": f"phase2_{suffix}@example.com",
        "email_password": "emailpassword",
        "region": "US"
    }
    resp = await http_json("POST", "/api/accounts", json_data=account_data)
    assert_status(resp, 200)
    payload = unwrap_response(get_json(resp))
    if not payload or not payload.get("id"):
        raise RuntimeError(f"账号创建返回异常: {payload}")
    return payload["id"]

async def create_proxy_via_api(suffix):
    proxy_data = {
        "host": f"127.0.0.{suffix % 255}",
        "port": 10000 + suffix % 5000,
        "type": "socks5",
        "username": "testuser",
        "password": "testpassword"
    }
    resp = await http_json("POST", "/api/proxies", json_data=proxy_data)
    assert_status(resp, 200)
    payload = unwrap_response(get_json(resp))
    if not payload or not payload.get("id"):
        raise RuntimeError(f"代理创建返回异常: {payload}")
    return payload["id"]

async def create_window_via_api(suffix):
    window_data = {
        "bit_window_id": f"phase2_window_{suffix}",
        "name": f"Phase2 Window {suffix}",
        "status": "空闲"
    }
    resp = await http_json("POST", "/api/browser-windows", json_data=window_data)
    assert_status(resp, 200)
    payload = unwrap_response(get_json(resp))
    if not payload or not payload.get("id"):
        raise RuntimeError(f"窗口创建返回异常: {payload}")
    return payload["id"]

async def bind_resources(account_id, proxy_id, window_id):
    bind_data = {"proxy_id": proxy_id, "window_id": window_id}
    resp = await http_json("POST", f"/api/accounts/{account_id}/bind", json_data=bind_data)
    assert_status(resp, 200)

async def test_comment_crud():
    require_column("comment_pool", "created_at")
    suffix = uuid.uuid4().hex[:8]
    category = f"phase2-crud-{suffix}"
    payload = {"content": f"test comment {suffix}", "language": TEST_LANGUAGE, "category": category}
    resp_create = await http_json("POST", "/api/comments", json_data=payload)
    assert_status(resp_create, 200)
    created = unwrap_response(get_json(resp_create))
    if not created or not created.get("id"):
        raise RuntimeError(f"新增语料返回异常: {created}")
    comment_id = created["id"]

    resp_list = await http_json("GET", f"/api/comments?category={category}")
    assert_status(resp_list, 200)
    items = get_json(resp_list)
    if not isinstance(items, list):
        raise RuntimeError(f"语料列表返回异常: {items}")
    if not any(item.get("id") == comment_id for item in items):
        raise RuntimeError("语料列表未找到新增项")

    resp_delete = await http_json("DELETE", f"/api/comments/{comment_id}")
    assert_status(resp_delete, 204)

    resp_list_after = await http_json("GET", f"/api/comments?category={category}")
    assert_status(resp_list_after, 200)
    items_after = get_json(resp_list_after)
    if len(items_after) != 0:
        raise RuntimeError("语料删除后列表不为空")

async def test_comment_batch_import():
    require_column("comment_pool", "created_at")
    suffix = uuid.uuid4().hex[:8]
    category = f"phase2-batch-{suffix}"
    items = [{"content": f"batch {suffix}-{i}", "language": TEST_LANGUAGE, "category": category} for i in range(BATCH_IMPORT_COUNT)]
    resp = await http_json("POST", "/api/comments/batch", json_data={"items": items})
    assert_status(resp, 200)
    payload = get_json(resp)
    imported = payload.get("imported")
    if imported is None:
        imported = payload.get("success_count")
    if imported != BATCH_IMPORT_COUNT:
        raise RuntimeError(f"导入数量不一致: {payload}")

    async with AsyncSessionLocal() as db:
        stmt = delete(CommentPool).where(CommentPool.category == category)
        await db.execute(stmt)
        await db.commit()

async def test_avatar_upload():
    suffix = uuid.uuid4().hex[:8]
    file_bytes = b"\xff\xd8\xff\xd9"
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        with open(tmp_path, "rb") as f:
            files = {"files": ("test.jpg", f, "image/jpeg")}
            resp = await http_json("POST", "/api/avatars/upload", data={"type": "avatar"}, files=files)
        assert_status(resp, 200)
        payload = get_json(resp)
        if payload.get("uploaded") != AVATAR_UPLOAD_COUNT:
            raise RuntimeError(f"上传返回异常: {payload}")
        items = payload.get("items") or []
        if len(items) != AVATAR_UPLOAD_COUNT:
            raise RuntimeError(f"上传返回 items 异常: {payload}")
        avatar_id = items[0].get("id")

        resp_list = await http_json("GET", "/api/avatars?type=avatar")
        assert_status(resp_list, 200)
        avatars = get_json(resp_list)
        if not any(item.get("id") == avatar_id for item in avatars):
            raise RuntimeError("头像列表未找到上传项")
        return avatar_id
    finally:
        os.unlink(tmp_path)

async def test_sop_load():
    for day in range(1, 21):
        data = load_sop_for_day(day)
        assert isinstance(data, dict)
        assert "once_tasks" in data
        assert "daily_tasks" in data

async def test_cascade_ban():
    suffix = int(utcnow().timestamp())
    account_id = await create_account_via_api(suffix)
    proxy_id = await create_proxy_via_api(suffix)
    window_id = await create_window_via_api(suffix)
    await bind_resources(account_id, proxy_id, window_id)
    CASCADE_CONTEXT["account_id"] = account_id
    CASCADE_CONTEXT["proxy_id"] = proxy_id
    CASCADE_CONTEXT["window_id"] = window_id

    resp_ban = await http_json("PATCH", f"/api/accounts/{account_id}", json_data={"status": "banned"})
    assert_status(resp_ban, 200)

    async with AsyncSessionLocal() as db:
        proxy = await db.get(ProxyIP, proxy_id)
        window = await db.get(BrowserWindow, window_id)
        assert proxy and proxy.status == "permanently_disabled"
        assert window and window.status == "permanently_disabled"

async def test_cascade_recovery():
    account_id = CASCADE_CONTEXT.get("account_id")
    proxy_id = CASCADE_CONTEXT.get("proxy_id")
    window_id = CASCADE_CONTEXT.get("window_id")
    if not account_id or not proxy_id or not window_id:
        raise RuntimeError("级联封禁未成功，缺少上下文")
    resp_recover = await http_json("PATCH", f"/api/accounts/{account_id}", json_data={"status": "nurturing"})
    assert_status(resp_recover, 200)

    async with AsyncSessionLocal() as db:
        proxy = await db.get(ProxyIP, proxy_id)
        window = await db.get(BrowserWindow, window_id)
        assert proxy and proxy.status == "in_use"
        assert window and window.status == "in_use"

async def test_alert_crud():
    require_table("alerts")
    async with AsyncSessionLocal() as db:
        alert = Alert(
            fb_account_id=None,
            level="ERROR",
            title="测试告警",
            message="phase2 alert"
        )
        db.add(alert)
        await db.commit()
        await db.refresh(alert)
        alert_id = alert.id

    resp_list = await http_json("GET", "/api/alerts")
    assert_status(resp_list, 200)
    alerts = get_json(resp_list)
    if not any(item.get("id") == alert_id for item in alerts):
        raise RuntimeError("告警列表未找到新增项")

    resp_dismiss = await http_json("POST", f"/api/alerts/{alert_id}/dismiss")
    assert_status(resp_dismiss, 200)

    resp_list_after = await http_json("GET", "/api/alerts")
    assert_status(resp_list_after, 200)
    alerts_after = get_json(resp_list_after)
    if any(item.get("id") == alert_id for item in alerts_after):
        raise RuntimeError("告警关闭后仍存在")

async def test_avatar_pick_dedup():
    avatar_ids = []
    for _ in range(2):
        avatar_ids.append(await test_avatar_upload())
    async with AsyncSessionLocal() as db:
        first = await pick_avatar(db, "avatar")
        assert first is not None
        refreshed = await db.get(AvatarAsset, first.id)
        assert refreshed and refreshed.is_used is True
        second = await pick_avatar(db, "avatar")
        if second is not None:
            assert second.id != first.id

async def test_pick_comment():
    require_column("comment_pool", "created_at")
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        comment = CommentPool(content=f"pick {suffix}", language=TEST_LANGUAGE, category=f"phase2-pick-{suffix}", use_count=0)
        db.add(comment)
        await db.commit()
        await db.refresh(comment)
        picked = await pick_comment(db, TEST_LANGUAGE)
        assert picked and picked.id == comment.id
        refreshed = await db.get(CommentPool, comment.id)
        assert refreshed and refreshed.use_count == 1

async def test_generate_tasks_day8():
    require_column("nurture_tasks", "created_at")
    async with AsyncSessionLocal() as db:
        suffix = uuid.uuid4().hex[:8]
        account = FBAccount(
            username=f"phase2_day8_{suffix}",
            password_encrypted="x",
            email=f"phase2_day8_{suffix}@example.com",
            email_password_encrypted="x",
            region="US",
            status="养号中",
            nurture_start_date=utcnow().date() - timedelta(days=7)
        )
        db.add(account)
        await db.commit()
        await db.refresh(account)
        account_id = account.id

    async with AsyncSessionLocal() as db:
        await generate_daily_tasks(db)

    async with AsyncSessionLocal() as db:
        today = utcnow().date()
        stmt = select(NurtureTask).where(
            NurtureTask.fb_account_id == account_id,
            NurtureTask.day_number == 8,
            NurtureTask.scheduled_date == today
        )
        result = await db.execute(stmt)
        tasks = result.scalars().all()
        once_count = len([t for t in tasks if t.task_type == "once"])
        daily_count = len([t for t in tasks if t.task_type == "daily"])
        assert once_count > 0
        assert daily_count > 0

async def test_manual_timeout_error_log():
    require_column("nurture_tasks", "created_at")
    require_column("action_logs", "is_dismissed")
    async with AsyncSessionLocal() as db:
        suffix = uuid.uuid4().hex[:8]
        account = FBAccount(
            username=f"phase2_manual_{suffix}",
            password_encrypted="x",
            email=f"phase2_manual_{suffix}@example.com",
            email_password_encrypted="x",
            region="US",
            status="养号中"
        )
        db.add(account)
        await db.commit()
        await db.refresh(account)
        task = NurtureTask(
            fb_account_id=account.id,
            day_number=1,
            scheduled_date=utcnow().date(),
            task_type="manual",
            execution_type="manual",
            status="pending",
            action="manual_check",
            created_at=utcnow() - timedelta(hours=TIMEOUT_HOURS)
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        task_id = task.id

    await check_manual_task_timeout()

    async with AsyncSessionLocal() as db:
        stmt = select(ActionLog).where(
            ActionLog.task_id == task_id,
            ActionLog.level == "ERROR",
            ActionLog.action_type == "manual_timeout"
        )
        result = await db.execute(stmt)
        log = result.scalar_one_or_none()
        assert log is not None

async def test_failure_circuit():
    require_column("action_logs", "is_dismissed")
    async with AsyncSessionLocal() as db:
        suffix = uuid.uuid4().hex[:8]
        account = FBAccount(
            username=f"phase2_fail_{suffix}",
            password_encrypted="x",
            email=f"phase2_fail_{suffix}@example.com",
            email_password_encrypted="x",
            region="US",
            status="养号中"
        )
        db.add(account)
        await db.commit()
        await db.refresh(account)
        for _ in range(3):
            log = ActionLog(
                fb_account_id=account.id,
                action_type="TEST_FAIL",
                level="ERROR",
                message="fail"
            )
            db.add(log)
        await db.commit()
        account_id = account.id

    executor = RPAExecutor()
    result = await executor._apply_account_failure_circuit(account_id)
    assert result is True

    async with AsyncSessionLocal() as db:
        account = await db.get(FBAccount, account_id)
        assert account and account.status == "abnormal"

async def test_action_registry():
    action_ids = list(ACTION_REGISTRY.keys())
    if len(action_ids) != EXPECTED_ACTION_COUNT:
        raise RuntimeError(f"当前注册 {len(action_ids)} 项: {', '.join(sorted(action_ids))}")

async def test_concurrency_control():
    executor = RPAExecutor()
    semaphore = executor.semaphore
    expected = getattr(RPAExecutor, "_max_concurrent", 5)
    current = 0
    max_seen = 0
    lock = asyncio.Lock()

    async def worker():
        nonlocal current, max_seen
        async with semaphore:
            async with lock:
                current += 1
                max_seen = max(max_seen, current)
            await asyncio.sleep(0.1)
            async with lock:
                current -= 1

    await asyncio.gather(*[worker() for _ in range(CONCURRENCY_TASKS)])
    assert max_seen <= expected

async def test_avatar_delete_protection():
    avatar_id = await test_avatar_upload()
    async with AsyncSessionLocal() as db:
        suffix = uuid.uuid4().hex[:8]
        account = FBAccount(
            username=f"phase2_avatar_{suffix}",
            password_encrypted="x",
            email=f"phase2_avatar_{suffix}@example.com",
            email_password_encrypted="x",
            region="US",
            status="养号中"
        )
        db.add(account)
        await db.commit()
        await db.refresh(account)
        avatar = await db.get(AvatarAsset, avatar_id)
        assert avatar is not None
        avatar.used_by_account_id = account.id
        db.add(avatar)
        await db.commit()

    resp = await http_json("DELETE", f"/api/avatars/{avatar_id}")
    assert resp.status_code == 400

async def verify_phase2():
    ensure_tables()
    global SCHEMA_STATE
    SCHEMA_STATE = await check_schema()
    tests = [
        ("P0-1 评论语料 CRUD", test_comment_crud),
        ("P0-2 批量导入语料", test_comment_batch_import),
        ("P0-3 头像上传", test_avatar_upload),
        ("P0-4 SOP 加载", test_sop_load),
        ("P0-5 级联封禁", test_cascade_ban),
        ("P0-6 级联恢复", test_cascade_recovery),
        ("P0-7 告警 CRUD", test_alert_crud),
        ("P1-8 头像防重复", test_avatar_pick_dedup),
        ("P1-9 语料选取", test_pick_comment),
        ("P1-10 任务生成 Day8", test_generate_tasks_day8),
        ("P1-11 人工待办超时", test_manual_timeout_error_log),
        ("P1-12 熔断机制", test_failure_circuit),
        ("P2-13 RPA 模块注册", test_action_registry),
        ("P2-14 并发控制", test_concurrency_control),
        ("P2-15 头像删除保护", test_avatar_delete_protection)
    ]

    passed = 0
    failures = []
    total = 15

    async def run_test(name, fn):
        nonlocal passed
        try:
            result = await fn()
            if name == "P0-3 头像上传" and isinstance(result, int):
                pass
            print(f"✅ PASS {name}", flush=True)
            passed += 1
        except Exception as e:
            failures.append((name, str(e)))
            print(f"❌ FAIL {name}: {e}", flush=True)

    for name, fn in tests:
        await run_test(name, fn)

    print(f"\n{passed}/{total} passed", flush=True)
    if failures:
        print("\n失败项：", flush=True)
        for name, reason in failures:
            print(f"- {name}: {reason}", flush=True)

if __name__ == "__main__":
    asyncio.run(verify_phase2())
