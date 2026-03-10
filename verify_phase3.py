import asyncio
import httpx
import os
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from db.database import AsyncSessionLocal, Base, sync_engine
from modules.monitor.models import Alert

BASE_URL = os.environ.get("FBM_BASE_URL", "http://127.0.0.1:8000")
AD_SPEND_CENTS = 1000
AD_IMPRESSIONS = 10000
AD_CLICKS = 200
AD_CONVERSIONS = 20
EXPECTED_CPM = 100
EXPECTED_CPC = 5
EXPECTED_CTR = 2.0
ALLOWED_CTR_DELTA = 0.01
FIRST_BUDGET = 200
SECOND_BUDGET = 1000
WARNING_BUDGET_FIRST = 200
WARNING_BUDGET_SECOND = 400

def unwrap_response(payload):
    if isinstance(payload, dict) and "code" in payload and "data" in payload:
        return payload.get("data")
    return payload

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def ensure_tables():
    Base.metadata.create_all(bind=sync_engine)

def reset_database():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path_main = os.path.join(base_dir, "fb_manager.db")
    db_path_legacy = os.path.join(base_dir, "fbmanager.db")
    for path in [db_path_main, db_path_legacy]:
        if os.path.exists(path):
            os.remove(path)

async def http_json(method, path, json_data=None, params=None):
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.request(method, f"{BASE_URL}{path}", json=json_data, params=params)
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

async def create_account(suffix):
    payload = {
        "username": f"phase3_user_{suffix}",
        "password": "password123",
        "email": f"phase3_{suffix}@example.com",
        "email_password": "emailpassword",
        "region": "US"
    }
    resp = await http_json("POST", "/api/accounts", json_data=payload)
    assert_status(resp, 200)
    data = unwrap_response(get_json(resp))
    if not data or not data.get("id"):
        raise RuntimeError(f"账号创建返回异常: {data}")
    return data

async def create_bm(suffix, fb_account_id=None):
    payload = {
        "bm_id": f"BM-{suffix}",
        "name": f"BM {suffix}",
        "region": "US",
        "fb_account_id": fb_account_id
    }
    resp = await http_json("POST", "/api/bm", json_data=payload)
    assert_status(resp, 200)
    data = unwrap_response(get_json(resp))
    if not data or not data.get("id"):
        raise RuntimeError(f"BM 创建返回异常: {data}")
    return data

async def create_ad_account(suffix, bm_id):
    payload = {
        "ad_account_id": f"AD-{suffix}",
        "bm_id": bm_id,
        "name": f"Ad Account {suffix}",
        "spending_limit": "$200",
        "payment_method": "visa"
    }
    resp = await http_json("POST", "/api/ad-accounts", json_data=payload)
    assert_status(resp, 200)
    data = unwrap_response(get_json(resp))
    if not data or not data.get("id"):
        raise RuntimeError(f"广告账户创建返回异常: {data}")
    return data

async def create_fanpage(suffix, fb_account_id):
    payload = {
        "page_id": f"PAGE-{suffix}",
        "fb_account_id": fb_account_id,
        "page_name": f"Fanpage {suffix}",
        "page_url": "https://example.com"
    }
    resp = await http_json("POST", "/api/fanpages", json_data=payload)
    assert_status(resp, 200)
    data = unwrap_response(get_json(resp))
    if not data or not data.get("id"):
        raise RuntimeError(f"Fanpage 创建返回异常: {data}")
    return data

async def upsert_ad_stat(ad_account_id, date_str, spend, impressions, clicks, conversions):
    payload = {
        "ad_account_id": ad_account_id,
        "date": date_str,
        "spend": spend,
        "impressions": impressions,
        "clicks": clicks,
        "conversions": conversions
    }
    resp = await http_json("POST", "/api/ad-stats", json_data=payload)
    assert_status(resp, 200)
    data = unwrap_response(get_json(resp))
    if not data or not data.get("id"):
        raise RuntimeError(f"投放数据录入返回异常: {data}")
    return data

async def test_bm_crud():
    suffix = uuid.uuid4().hex[:8]
    account = await create_account(suffix)
    bm = await create_bm(suffix, account["id"])
    resp_list = await http_json("GET", "/api/bm")
    assert_status(resp_list, 200)
    items = get_json(resp_list)
    if not any(item.get("id") == bm["id"] for item in items):
        raise RuntimeError("BM 列表未找到新增项")
    resp_update = await http_json("PATCH", f"/api/bm/{bm['id']}", json_data={"name": "BM Updated"})
    assert_status(resp_update, 200)
    updated = unwrap_response(get_json(resp_update))
    if updated.get("name") != "BM Updated":
        raise RuntimeError("BM 更新未生效")

async def test_ad_account_crud():
    suffix = uuid.uuid4().hex[:8]
    bm = await create_bm(suffix)
    ad_account = await create_ad_account(suffix, bm["id"])
    resp_list = await http_json("GET", "/api/ad-accounts", params={"bm_id": bm["id"]})
    assert_status(resp_list, 200)
    items = get_json(resp_list)
    if not any(item.get("id") == ad_account["id"] for item in items):
        raise RuntimeError("广告账户列表未找到新增项")
    resp_update = await http_json("PATCH", f"/api/ad-accounts/{ad_account['id']}", json_data={"spending_limit": "$300"})
    assert_status(resp_update, 200)
    payload = get_json(resp_update)
    data = payload.get("data") or {}
    if data.get("spending_limit") != "$300":
        raise RuntimeError("广告账户额度更新未生效")

async def test_fanpage_crud():
    suffix = uuid.uuid4().hex[:8]
    account = await create_account(suffix)
    fanpage = await create_fanpage(suffix, account["id"])
    resp_list = await http_json("GET", "/api/fanpages", params={"fb_account_id": account["id"]})
    assert_status(resp_list, 200)
    items = get_json(resp_list)
    if not any(item.get("id") == fanpage["id"] for item in items):
        raise RuntimeError("Fanpage 列表未找到新增项")
    resp_update = await http_json("PATCH", f"/api/fanpages/{fanpage['id']}", json_data={"pixel_installed": True})
    assert_status(resp_update, 200)
    updated = unwrap_response(get_json(resp_update))
    if updated.get("pixel_installed") is not True:
        raise RuntimeError("Fanpage 更新未生效")

async def test_ad_stat_upsert():
    suffix = uuid.uuid4().hex[:8]
    bm = await create_bm(suffix)
    ad_account = await create_ad_account(suffix, bm["id"])
    date_str = utcnow().date().isoformat()
    await upsert_ad_stat(ad_account["id"], date_str, 500, 1000, 10, 1)
    resp_list = await http_json("GET", "/api/ad-stats", params={"ad_account_id": ad_account["id"], "date_start": date_str, "date_end": date_str})
    assert_status(resp_list, 200)
    items = get_json(resp_list)
    if len(items) != 1:
        raise RuntimeError("首次录入后统计条数异常")
    await upsert_ad_stat(ad_account["id"], date_str, 800, 1000, 10, 1)
    resp_list_again = await http_json("GET", "/api/ad-stats", params={"ad_account_id": ad_account["id"], "date_start": date_str, "date_end": date_str})
    assert_status(resp_list_again, 200)
    items_again = get_json(resp_list_again)
    if len(items_again) != 1:
        raise RuntimeError("二次录入未触发 UPSERT")
    if items_again[0].get("spend") != 800:
        raise RuntimeError("UPSERT 数据未更新")

async def test_stat_metrics():
    suffix = uuid.uuid4().hex[:8]
    bm = await create_bm(suffix)
    ad_account = await create_ad_account(suffix, bm["id"])
    date_str = utcnow().date().isoformat()
    stat = await upsert_ad_stat(ad_account["id"], date_str, AD_SPEND_CENTS, AD_IMPRESSIONS, AD_CLICKS, AD_CONVERSIONS)
    if stat.get("cpm") != EXPECTED_CPM:
        raise RuntimeError(f"CPM 计算错误: {stat.get('cpm')}")
    if stat.get("cpc") != EXPECTED_CPC:
        raise RuntimeError(f"CPC 计算错误: {stat.get('cpc')}")
    ctr = stat.get("ctr")
    if ctr is None or abs(ctr - EXPECTED_CTR) > ALLOWED_CTR_DELTA:
        raise RuntimeError(f"CTR 计算错误: {ctr}")

async def test_budget_changes():
    suffix = uuid.uuid4().hex[:8]
    bm = await create_bm(suffix)
    ad_account = await create_ad_account(suffix, bm["id"])
    resp_first = await http_json("PATCH", f"/api/ad-accounts/{ad_account['id']}", json_data={"daily_budget": FIRST_BUDGET})
    assert_status(resp_first, 200)
    resp_second = await http_json("PATCH", f"/api/ad-accounts/{ad_account['id']}", json_data={"daily_budget": SECOND_BUDGET})
    assert_status(resp_second, 200)
    resp_history = await http_json("GET", "/api/budget-changes", params={"ad_account_id": ad_account["id"]})
    assert_status(resp_history, 200)
    items = get_json(resp_history)
    if not any(item.get("old_budget") == FIRST_BUDGET and item.get("new_budget") == SECOND_BUDGET for item in items):
        raise RuntimeError("预算变更记录缺失")

async def test_ads_page_access():
    resp = await http_json("GET", "/ads")
    assert_status(resp, 200)

async def test_bm_delete_protection():
    suffix = uuid.uuid4().hex[:8]
    bm = await create_bm(suffix)
    await create_ad_account(suffix, bm["id"])
    resp_delete = await http_json("DELETE", f"/api/bm/{bm['id']}")
    if resp_delete.status_code != 400:
        raise RuntimeError(f"删除保护未生效: {resp_delete.status_code}")

async def test_ad_account_detail():
    suffix = uuid.uuid4().hex[:8]
    bm = await create_bm(suffix)
    ad_account = await create_ad_account(suffix, bm["id"])
    date_str = utcnow().date().isoformat()
    await upsert_ad_stat(ad_account["id"], date_str, 300, 500, 5, 1)
    await http_json("PATCH", f"/api/ad-accounts/{ad_account['id']}", json_data={"daily_budget": 100})
    resp_detail = await http_json("GET", f"/api/ad-accounts/{ad_account['id']}/detail")
    assert_status(resp_detail, 200)
    payload = get_json(resp_detail)
    if "recent_stats" not in payload or "budget_changes" not in payload:
        raise RuntimeError("广告账户详情缺少字段")

async def test_ad_overview():
    resp = await http_json("GET", "/api/ad-overview")
    assert_status(resp, 200)
    payload = get_json(resp)
    for key in ["today_spend", "week_spend", "month_spend", "daily_trend"]:
        if key not in payload:
            raise RuntimeError(f"投放概览缺少字段 {key}")

async def test_logs_export():
    resp = await http_json("GET", "/api/logs/export", params={"format": "csv"})
    assert_status(resp, 200)
    content_type = resp.headers.get("content-type", "")
    if "text/csv" not in content_type:
        raise RuntimeError(f"日志导出 Content-Type 异常: {content_type}")

async def test_ad_stats_export():
    suffix = uuid.uuid4().hex[:8]
    bm = await create_bm(suffix)
    ad_account = await create_ad_account(suffix, bm["id"])
    date_str = utcnow().date().isoformat()
    await upsert_ad_stat(ad_account["id"], date_str, 200, 400, 4, 1)
    resp = await http_json("GET", "/api/ad-stats/export", params={"ad_account_id": ad_account["id"], "format": "csv"})
    assert_status(resp, 200)
    content = resp.text
    if str(ad_account["id"]) not in content:
        raise RuntimeError("投放导出 CSV 内容缺失")

async def test_account_ad_assets():
    suffix = uuid.uuid4().hex[:8]
    account = await create_account(suffix)
    bm = await create_bm(suffix, account["id"])
    await create_ad_account(suffix, bm["id"])
    await create_fanpage(suffix, account["id"])
    resp = await http_json("GET", f"/api/accounts/{account['id']}/ad-assets")
    assert_status(resp, 200)
    payload = get_json(resp)
    if not payload.get("bm"):
        raise RuntimeError("广告资产 BM 缺失")
    if not payload.get("ad_accounts"):
        raise RuntimeError("广告资产广告账户缺失")
    if not payload.get("fanpages"):
        raise RuntimeError("广告资产 Fanpage 缺失")

async def test_budget_warning():
    suffix = uuid.uuid4().hex[:8]
    bm = await create_bm(suffix)
    ad_account = await create_ad_account(suffix, bm["id"])
    resp_first = await http_json("PATCH", f"/api/ad-accounts/{ad_account['id']}", json_data={"daily_budget": WARNING_BUDGET_FIRST})
    assert_status(resp_first, 200)
    resp_second = await http_json("PATCH", f"/api/ad-accounts/{ad_account['id']}", json_data={"daily_budget": WARNING_BUDGET_SECOND})
    assert_status(resp_second, 200)
    payload = get_json(resp_second)
    warnings = payload.get("warnings") or []
    if not warnings:
        raise RuntimeError("预算递增警告未返回")

async def test_alert_count():
    async with AsyncSessionLocal() as db:
        alert = Alert(level="CRITICAL", title="Phase3", message="critical")
        db.add(alert)
        await db.commit()
        await db.refresh(alert)
    resp = await http_json("GET", "/api/alerts/count")
    assert_status(resp, 200)
    payload = get_json(resp)
    critical_count = payload.get("critical", 0)
    if critical_count < 1:
        raise RuntimeError("CRITICAL 告警计数未增加")

async def verify_phase3():
    reset_database()
    ensure_tables()
    tests = [
        ("P0-1 BM CRUD", test_bm_crud),
        ("P0-2 广告账户 CRUD", test_ad_account_crud),
        ("P0-3 Fanpage CRUD", test_fanpage_crud),
        ("P0-4 投放数据录入 UPSERT", test_ad_stat_upsert),
        ("P0-5 派生指标计算", test_stat_metrics),
        ("P0-6 预算变更记录", test_budget_changes),
        ("P0-7 ads.html 可访问", test_ads_page_access),
        ("P1-8 BM 删除保护", test_bm_delete_protection),
        ("P1-9 广告账户详情", test_ad_account_detail),
        ("P1-10 投放概览 API", test_ad_overview),
        ("P1-11 日志导出", test_logs_export),
        ("P1-12 投放数据导出", test_ad_stats_export),
        ("P1-13 账号广告资产 API", test_account_ad_assets),
        ("P2-14 预算递增警告", test_budget_warning),
        ("P2-15 告警计数 API", test_alert_count)
    ]
    passed = 0
    failures = []
    total = len(tests)

    async def run_test(name, fn):
        nonlocal passed
        try:
            await fn()
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
    asyncio.run(verify_phase3())
