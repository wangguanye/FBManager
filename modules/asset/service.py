# FIX-11 done
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_, func, desc
from sqlalchemy.orm import selectinload
from modules.asset.models import FBAccount, ProxyIP, BrowserWindow, CommentPool, AvatarAsset
from modules.health.models import HealthScore
from modules.asset.schemas import FBAccountCreate, FBAccountUpdate, FBAccountBind, ProxyIPCreate, ProxyIPUpdate, BrowserWindowCreate, CommentCreate
from modules.ad.models import BMAccount, AdAccount, Fanpage
from core.crypto import encrypt_value
from core.cascade import cascade_on_ban, cascade_on_recovery
from fastapi import HTTPException
from modules.rpa.browser_client import BitBrowserClient, BitBrowserNotRunningError
from datetime import datetime
import os
from uuid import uuid4
import csv
import io
from typing import Any, Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

async def create_fb_account(db: AsyncSession, account: FBAccountCreate):
    """创建 FB 账号并加密敏感信息"""
    db_account = FBAccount(
        username=account.username,
        password_encrypted=encrypt_value(account.password),
        email=account.email,
        email_password_encrypted=encrypt_value(account.email_password),
        region=account.region,
        target_timezone=account.target_timezone,
        status="待养号",
        notes=account.notes,
        totp_secret_encrypted=encrypt_value(account.totp_secret) if account.totp_secret else None,
        cookie_encrypted=encrypt_value(account.cookie) if account.cookie else None
    )
    db.add(db_account)
    await db.flush()
    return db_account

async def get_fb_accounts(
    db: AsyncSession, 
    skip: int = 0, 
    limit: int = 100, 
    status: str = None, 
    q: str = None
):
    """获取所有 FB 账号，支持筛选和模糊搜索"""
    stmt = select(FBAccount).where(FBAccount.is_deleted == False).options(
        selectinload(FBAccount.proxy),
        selectinload(FBAccount.browser_window)
    )
    
    if status:
        stmt = stmt.where(FBAccount.status == status)
        
    if q:
        search_filter = or_(
            FBAccount.username.ilike(f"%{q}%"),
            FBAccount.notes.ilike(f"%{q}%")
        )
        stmt = stmt.where(search_filter)
        
    stmt = stmt.offset(skip).limit(limit).order_by(FBAccount.created_at.desc())
    result = await db.execute(stmt)
    accounts = result.scalars().all()
    if not accounts:
        return accounts
    account_ids = [item.id for item in accounts]
    score_stmt = select(HealthScore).where(HealthScore.fb_account_id.in_(account_ids))
    score_result = await db.execute(score_stmt)
    score_items = score_result.scalars().all()
    score_map = {item.fb_account_id: item for item in score_items}
    for account in accounts:
        score_item = score_map.get(account.id)
        account.health_score = score_item.score if score_item else 0
        account.health_grade = score_item.grade if score_item else "F"
    return accounts

async def get_fb_account_by_id(db: AsyncSession, account_id: int):
    stmt = select(FBAccount).where(FBAccount.id == account_id, FBAccount.is_deleted == False)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()

async def get_account_ad_assets(db: AsyncSession, account_id: int):
    assert account_id > 0
    account = await get_fb_account_by_id(db, account_id)
    if not account:
        return None
    bm_stmt = select(BMAccount).where(BMAccount.fb_account_id == account_id).order_by(desc(BMAccount.created_at)).limit(1)
    bm_result = await db.execute(bm_stmt)
    bm = bm_result.scalar_one_or_none()
    ad_accounts = []
    if bm:
        ad_account_stmt = select(AdAccount).where(AdAccount.bm_id == bm.id).order_by(desc(AdAccount.created_at))
        ad_account_result = await db.execute(ad_account_stmt)
        ad_accounts = ad_account_result.scalars().all()
    fanpage_stmt = select(Fanpage).where(Fanpage.fb_account_id == account_id).order_by(desc(Fanpage.created_at))
    fanpage_result = await db.execute(fanpage_stmt)
    fanpages = fanpage_result.scalars().all()
    bm_payload = None
    if bm:
        bm_payload = {"bm_id": bm.bm_id, "name": bm.name, "status": bm.status}
    ad_accounts_payload = [
        {
            "ad_account_id": item.ad_account_id,
            "spending_limit": item.spending_limit,
            "daily_budget": item.daily_budget,
            "status": item.status
        }
        for item in ad_accounts
    ]
    fanpages_payload = [
        {
            "page_id": item.page_id,
            "page_name": item.page_name,
            "pixel_installed": item.pixel_installed,
            "domain_verified": item.domain_verified
        }
        for item in fanpages
    ]
    return {
        "bm": bm_payload,
        "ad_accounts": ad_accounts_payload,
        "fanpages": fanpages_payload
    }

async def update_fb_account(db: AsyncSession, account_id: int, update_data: FBAccountUpdate):
    account = await get_fb_account_by_id(db, account_id)
    if not account:
        return None

    previous_status = account.status
    warning_message = None

    if update_data.status and update_data.status != account.status:
        if update_data.status in ["已封禁", "banned"]:
            warning_message = "账号将被封禁并触发级联禁用代理与窗口"
            await cascade_on_ban(db, account_id)
        elif previous_status in ["abnormal", "异常", "banned", "已封禁"] and update_data.status in ["nurturing", "养号中"]:
            await cascade_on_recovery(db, account_id)
        if update_data.status in ["已封禁", "banned"]:
            account.status = "已封禁"
        elif update_data.status in ["养号中", "nurturing"]:
            account.status = "养号中"
        else:
            account.status = update_data.status

    if update_data.username is not None:
        account.username = update_data.username
    if update_data.email is not None:
        account.email = update_data.email
    if update_data.region is not None:
        account.region = update_data.region
    if update_data.target_timezone is not None:
        account.target_timezone = update_data.target_timezone
    if update_data.notes is not None:
        account.notes = update_data.notes
        
    # 处理密码更新
    if update_data.password is not None:
        account.password_encrypted = encrypt_value(update_data.password)
    if update_data.email_password is not None:
        account.email_password_encrypted = encrypt_value(update_data.email_password)
    if update_data.totp_secret is not None:
        account.totp_secret_encrypted = encrypt_value(update_data.totp_secret)
    if update_data.cookie is not None:
        account.cookie_encrypted = encrypt_value(update_data.cookie)
        
    db.add(account)
    await db.flush()
    stmt = select(FBAccount).where(FBAccount.id == account_id).options(
        selectinload(FBAccount.proxy),
        selectinload(FBAccount.browser_window)
    )
    result = await db.execute(stmt)
    refreshed_account = result.scalar_one_or_none()
    return {"account": refreshed_account, "warning": warning_message}

async def delete_fb_account(db: AsyncSession, account_id: int):
    """软删除账号"""
    account = await get_fb_account_by_id(db, account_id)
    if not account:
        return False
        
    account.is_deleted = True
    db.add(account)
    await db.flush()
    return True

async def bind_account_resources(db: AsyncSession, account_id: int, bind_data: FBAccountBind):
    """绑定代理和窗口"""
    account = await get_fb_account_by_id(db, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
        
    # 验证代理
    proxy = await db.get(ProxyIP, bind_data.proxy_id)
    if not proxy:
        raise HTTPException(status_code=404, detail="Proxy not found")
    if proxy.status == "永久禁用":
        raise HTTPException(status_code=400, detail="该代理已被永久禁用，不可绑定")
    if proxy.status != "空闲":
        raise HTTPException(status_code=400, detail=f"Proxy {proxy.host} is not idle")
        
    # 验证窗口
    window = await db.get(BrowserWindow, bind_data.window_id)
    if not window:
        raise HTTPException(status_code=404, detail="Window not found")
    if window.status == "永久禁用":
        raise HTTPException(status_code=400, detail="该窗口已被永久禁用，不可绑定")
    if window.status != "空闲":
        raise HTTPException(status_code=400, detail=f"Window {window.name} is not idle")
        
    # 解绑旧资源（如果有）
    if account.proxy_id:
        old_proxy = await db.get(ProxyIP, account.proxy_id)
        if old_proxy:
            old_proxy.status = "空闲"
            db.add(old_proxy)
            
    if account.browser_window_id:
        old_window = await db.get(BrowserWindow, account.browser_window_id)
        if old_window:
            old_window.status = "空闲"
            db.add(old_window)

    # 绑定新资源
    account.proxy_id = proxy.id
    account.browser_window_id = window.id
    
    proxy.status = "使用中"
    window.status = "使用中"
    
    db.add(account)
    db.add(proxy)
    db.add(window)
    
    await db.flush()
    await db.refresh(account)
    # 重新加载关联对象以返回完整信息
    stmt = select(FBAccount).where(FBAccount.id == account_id).options(
        selectinload(FBAccount.proxy),
        selectinload(FBAccount.browser_window)
    )
    result = await db.execute(stmt)
    return result.scalar_one()

async def create_proxy(db: AsyncSession, proxy: ProxyIPCreate):
    """创建代理 IP"""
    db_proxy = ProxyIP(
        host=proxy.host,
        port=proxy.port,
        username=proxy.username,
        password_encrypted=encrypt_value(proxy.password) if proxy.password else None,
        region=proxy.region,
        type=proxy.type,
        status=proxy.status
    )
    db.add(db_proxy)
    await db.flush()
    return db_proxy

async def get_proxies(db: AsyncSession, status: str = None, q: str = None):
    """获取所有代理 IP"""
    stmt = select(ProxyIP)
    if status:
        stmt = stmt.where(ProxyIP.status == status)
    if q:
        search_filter = or_(
            ProxyIP.host.ilike(f"%{q}%"),
            ProxyIP.username.ilike(f"%{q}%")
        )
        stmt = stmt.where(search_filter)
    result = await db.execute(stmt)
    return result.scalars().all()

async def update_proxy(db: AsyncSession, proxy_id: int, update_data: ProxyIPUpdate):
    """更新代理 IP"""
    proxy = await db.get(ProxyIP, proxy_id)
    if not proxy:
        return None
        
    if update_data.host is not None:
        proxy.host = update_data.host
    if update_data.port is not None:
        proxy.port = update_data.port
    if update_data.username is not None:
        proxy.username = update_data.username
    if update_data.password is not None:
        proxy.password_encrypted = encrypt_value(update_data.password)
    if update_data.region is not None:
        proxy.region = update_data.region
    if update_data.type is not None:
        proxy.type = update_data.type
    if update_data.status is not None:
        if proxy.status == "永久禁用" and update_data.status in ["空闲", "使用中"]:
            raise HTTPException(status_code=400, detail="永久禁用的代理不可恢复为空闲或使用中")
        proxy.status = update_data.status
        
    db.add(proxy)
    await db.flush()
    await db.refresh(proxy)
    return proxy

async def create_browser_window(db: AsyncSession, window: BrowserWindowCreate):
    """创建浏览器窗口"""
    db_window = BrowserWindow(
        bit_window_id=window.bit_window_id,
        name=window.name,
        status=window.status
    )
    db.add(db_window)
    await db.flush()
    return db_window

async def get_browser_windows(db: AsyncSession, status: str = None):
    """获取所有浏览器窗口"""
    stmt = select(BrowserWindow).options(
        selectinload(BrowserWindow.fb_account).selectinload(FBAccount.proxy)
    )
    if status:
        stmt = stmt.where(BrowserWindow.status == status)
    stmt = stmt.order_by(BrowserWindow.id.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


WINDOW_STATUS_IDLE = "\u7a7a\u95f2"
WINDOW_STATUS_IN_USE = "\u4f7f\u7528\u4e2d"
WINDOW_STATUS_RUNNING = "\u8fd0\u884c\u4e2d"
WINDOW_STATUS_BANNED = "\u6c38\u4e45\u7981\u7528"
WINDOW_STATUS_LOST = "\u5df2\u5931\u8054"


def _to_bool_flag(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on", "running", "run", "open", "opened", "active", "online", "started"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", "stopped", "stop", "close", "closed", "inactive", "idle"}:
            return False
        if normalized.isdigit():
            return int(normalized) != 0
    return None


def _extract_running_flag(list_item: Dict[str, Any], detail: Dict[str, Any]) -> Optional[bool]:
    candidate_keys = (
        "isRunning",
        "running",
        "isOpen",
        "open",
        "isActive",
        "active",
        "isStart",
        "isStarted",
        "status",
    )
    for source in (detail, list_item):
        for key in candidate_keys:
            if key not in source:
                continue
            parsed = _to_bool_flag(source.get(key))
            if parsed is not None:
                return parsed
    return None


async def _has_active_binding(db: AsyncSession, window_id: int) -> bool:
    binding_stmt = (
        select(FBAccount.id)
        .where(FBAccount.browser_window_id == window_id, FBAccount.is_deleted == False)
        .limit(1)
    )
    binding_result = await db.execute(binding_stmt)
    return binding_result.scalar_one_or_none() is not None


async def sync_browser_windows(db: AsyncSession):
    """Sync BitBrowser windows including proxy/account/running-state metadata."""
    client = BitBrowserClient()

    is_alive = await client.check_alive()
    if not is_alive:
        raise BitBrowserNotRunningError("BitBrowser is not running")

    # Step 1: paginated list
    page = 0
    page_size = 50
    all_windows = []
    while True:
        batch = await client.list_browsers(page=page, page_size=page_size)
        logger.info("BitBrowser list page=%s raw=%s", page, batch)
        if not batch:
            break
        all_windows.extend(batch)
        if len(batch) < page_size:
            break
        page += 1

    synced_count = 0
    new_count = 0
    auto_bound_count = 0
    remote_ids = set()

    for w in all_windows:
        bit_id = str(w.get("id")).strip() if w.get("id") is not None else ""
        if not bit_id:
            continue
        remote_ids.add(bit_id)

        # Step 2: get detail for each window
        detail = await client.get_browser_detail(bit_id)
        logger.info("Window %s list raw: %s", bit_id, w)
        logger.info("Window %s detail raw: %s", bit_id, detail)
        logger.info(
            "Window %s detail: proxyMethod=%s, host=%s, userName=%s",
            bit_id,
            detail.get("proxyMethod"),
            detail.get("host"),
            detail.get("userName"),
        )

        name = detail.get("name") or w.get("name", "Unknown")

        # Extract proxy fields: save if host is non-empty, regardless of proxyMethod
        proxy_host = detail.get("host") or w.get("host") or w.get("proxyHost") or None
        proxy_port = None
        raw_port = detail.get("port") or w.get("port") or w.get("proxyPort")
        if raw_port:
            try:
                proxy_port = int(raw_port)
            except (ValueError, TypeError):
                proxy_port = None
        proxy_type = detail.get("proxyType") or w.get("proxyType") or w.get("proxy_type") or None
        proxy_username = detail.get("proxyUserName") or w.get("proxyUserName") or w.get("proxy_username") or None
        remark = detail.get("remark") or w.get("remark") or None

        # Only null out if host is truly empty, NOT based on proxyMethod
        if not proxy_host:
            proxy_host = proxy_port = proxy_type = proxy_username = None

        # Platform login username (FB username) from BitBrowser
        synced_username = detail.get("userName") or None
        if not synced_username:
            fallback_username = detail.get("username") or detail.get("user_name")
            if fallback_username:
                logger.warning("BitBrowser detail for %s uses non-standard username field, adaptively mapped.", bit_id)
                synced_username = fallback_username
            elif isinstance(detail.get("platform"), dict):
                platform_username = detail["platform"].get("userName") or detail["platform"].get("username")
                if platform_username:
                    logger.warning("BitBrowser detail for %s nests username in platform object, adaptively mapped.", bit_id)
                    synced_username = platform_username
            elif w.get("userName") or w.get("username"):
                logger.warning("BitBrowser list for %s carries username field; using list fallback.", bit_id)
                synced_username = w.get("userName") or w.get("username")

        running_flag = _extract_running_flag(w, detail)
        is_running = bool(running_flag) if running_flag is not None else False

        # Step 3: upsert
        stmt = select(BrowserWindow).where(BrowserWindow.bit_window_id == bit_id)
        result = await db.execute(stmt)
        db_window = result.scalar_one_or_none()

        if db_window:
            if db_window.status == WINDOW_STATUS_LOST:
                db_window.status = WINDOW_STATUS_IDLE
            if is_running:
                if db_window.status not in (WINDOW_STATUS_BANNED, WINDOW_STATUS_LOST):
                    db_window.status = WINDOW_STATUS_RUNNING
            elif db_window.status == WINDOW_STATUS_RUNNING:
                has_binding = await _has_active_binding(db, db_window.id)
                db_window.status = WINDOW_STATUS_IN_USE if has_binding else WINDOW_STATUS_IDLE

            db_window.name = name
            db_window.synced_proxy_host = proxy_host
            db_window.synced_proxy_port = proxy_port
            db_window.synced_proxy_type = proxy_type
            db_window.synced_proxy_username = proxy_username
            db_window.synced_username = synced_username
            db_window.is_running = is_running
            db_window.remark = remark
            db_window.last_synced_at = datetime.utcnow()
            db.add(db_window)
        else:
            new_window = BrowserWindow(
                bit_window_id=bit_id,
                name=name,
                status=WINDOW_STATUS_RUNNING if is_running else WINDOW_STATUS_IDLE,
                synced_proxy_host=proxy_host,
                synced_proxy_port=proxy_port,
                synced_proxy_type=proxy_type,
                synced_proxy_username=proxy_username,
                synced_username=synced_username,
                is_running=is_running,
                remark=remark,
                last_synced_at=datetime.utcnow(),
            )
            db.add(new_window)
            new_count += 1

        synced_count += 1

    # Step 3b: Auto-match windows to fb_accounts by synced_username
    windows_with_username = await db.execute(
        select(BrowserWindow).where(BrowserWindow.synced_username.isnot(None))
    )
    for win in windows_with_username.scalars():
        if not win.synced_username:
            continue

        username_key = win.synced_username.strip()
        if not username_key:
            continue

        # Check if already bound (an account already has browser_window_id = this window)
        existing_binding = await db.execute(
            select(FBAccount).where(FBAccount.browser_window_id == win.id)
        )
        if existing_binding.scalar_one_or_none():
            continue

        # Find matching account by username
        matching_account = await db.execute(
            select(FBAccount).where(
                FBAccount.username == username_key,
                FBAccount.is_deleted == False,
            )
        )
        account = matching_account.scalar_one_or_none()
        if account and account.browser_window_id is None:
            account.browser_window_id = win.id
            if not win.is_running and win.status not in (WINDOW_STATUS_BANNED, WINDOW_STATUS_LOST):
                win.status = WINDOW_STATUS_IN_USE
                db.add(win)
            auto_bound_count += 1

            # Also auto-match proxy if account currently has no proxy
            if win.synced_proxy_host and win.synced_proxy_port and account.proxy_id is None:
                matching_proxy = await db.execute(
                    select(ProxyIP).where(
                        ProxyIP.host == win.synced_proxy_host,
                        ProxyIP.port == win.synced_proxy_port,
                    )
                )
                proxy = matching_proxy.scalar_one_or_none()
                if proxy:
                    account.proxy_id = proxy.id

            db.add(account)

    # Step 4: mark local-only windows as lost
    all_local_stmt = select(BrowserWindow)
    all_local_result = await db.execute(all_local_stmt)
    lost_count = 0
    for local_win in all_local_result.scalars():
        if local_win.bit_window_id not in remote_ids and local_win.status != WINDOW_STATUS_BANNED:
            local_win.status = WINDOW_STATUS_LOST
            local_win.is_running = False
            db.add(local_win)
            lost_count += 1

    await db.flush()
    return {
        "synced_count": synced_count,
        "new_count": new_count,
        "lost_count": lost_count,
        "auto_bound_count": auto_bound_count,
    }


async def open_browser_window(db: AsyncSession, window_id: int):
    """Open browser window and mark running state."""
    stmt = select(BrowserWindow).where(BrowserWindow.id == window_id)
    result = await db.execute(stmt)
    window = result.scalar_one_or_none()
    if not window:
        raise HTTPException(status_code=404, detail="Window not found")
    if window.status == WINDOW_STATUS_BANNED:
        raise HTTPException(status_code=403, detail="Window is permanently disabled")

    client = BitBrowserClient()
    try:
        res = await client.open_browser(window.bit_window_id)
        window.is_running = True
        if window.status not in (WINDOW_STATUS_BANNED, WINDOW_STATUS_LOST):
            window.status = WINDOW_STATUS_RUNNING
        db.add(window)
        await db.flush()
        return res
    except BitBrowserNotRunningError:
        raise HTTPException(status_code=503, detail="BitBrowser is not running")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to open browser: {str(e)}")


async def close_browser_window(db: AsyncSession, window_id: int):
    """Close browser window and mark running state with safe DB updates."""
    stmt = select(BrowserWindow).where(BrowserWindow.id == window_id)
    result = await db.execute(stmt)
    window = result.scalar_one_or_none()
    if not window:
        raise HTTPException(status_code=404, detail="Window not found")

    client = BitBrowserClient()
    try:
        await client.close_browser(window.bit_window_id)
    except BitBrowserNotRunningError:
        raise HTTPException(status_code=503, detail="BitBrowser is not running")
    except Exception as e:
        logger.warning("close_browser API warning for %s: %s", window.bit_window_id, e)

    window.is_running = False
    if window.status not in (WINDOW_STATUS_BANNED, WINDOW_STATUS_LOST):
        has_binding = await _has_active_binding(db, window.id)
        window.status = WINDOW_STATUS_IN_USE if has_binding else WINDOW_STATUS_IDLE
    db.add(window)
    await db.flush()
    return True

ACCOUNT_HEADERS = ("username", "password", "totp_secret", "email", "email_password", "cookie", "browser_profile_id")
ACCOUNT_REQUIRED_FIELDS = ("username", "password", "email", "email_password")
PROXY_HEADERS = ("ip", "port", "username", "password")
PROXY_REQUIRED_FIELDS = ("ip", "port")

def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()

def _get_first_non_empty_line(content: str) -> str:
    for line in content.splitlines():
        if line.strip():
            return line
    return ""

def _has_standard_header(first_line: str, expected_headers: Tuple[str, ...]) -> bool:
    if "," not in first_line:
        return False
    reader = csv.reader([first_line])
    row = next(reader, [])
    header_set = {str(item).strip().lower() for item in row if item is not None}
    expected_set = set(expected_headers)
    return expected_set.issubset(header_set)

def _build_account_preview_item(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "line": payload.get("line"),
        "username": payload.get("username"),
        "email": payload.get("email"),
        "has_2fa": bool(payload.get("totp_secret")),
        "has_cookie": bool(payload.get("cookie")),
        "browser_profile_id": payload.get("browser_profile_id"),
        "valid": payload.get("valid", True),
        "error": payload.get("error")
    }

def _build_proxy_preview_item(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "line": payload.get("line"),
        "host": payload.get("host"),
        "port": payload.get("port"),
        "username": payload.get("username"),
        "has_password": bool(payload.get("password")),
        "valid": payload.get("valid", True),
        "error": payload.get("error")
    }

def _parse_accounts_colon_lines(content: str) -> Dict[str, Any]:
    preview = []
    rows = []
    errors = []
    total = 0
    for line_index, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        total += 1
        parts = [part.strip() for part in line.split(":")]
        error_reason = None
        if len(parts) < 6:
            error_reason = "格式错误：字段数量不足"
        username = parts[0].strip() if len(parts) > 0 else ""
        password = parts[1].strip() if len(parts) > 1 else ""
        totp_secret = parts[2].strip() if len(parts) > 2 else ""
        email = parts[3].strip() if len(parts) > 3 else ""
        email_password = parts[4].strip() if len(parts) > 4 else ""
        cookie = ""
        browser_profile_id = ""
        if len(parts) >= 6:
            if len(parts) == 6:
                cookie = ""
                browser_profile_id = parts[5].strip()
            else:
                cookie = ":".join(parts[5:-1]).strip()
                browser_profile_id = parts[-1].strip()
        if not error_reason:
            missing_fields = [field for field, value in {
                "username": username,
                "password": password,
                "email": email,
                "email_password": email_password
            }.items() if not value]
            if missing_fields:
                error_reason = "必填字段缺失：" + "、".join(missing_fields)
        row_payload = {
            "line": line_index,
            "username": username,
            "password": password,
            "totp_secret": totp_secret,
            "email": email,
            "email_password": email_password,
            "cookie": cookie,
            "browser_profile_id": browser_profile_id
        }
        if error_reason:
            preview.append(_build_account_preview_item({**row_payload, "valid": False, "error": error_reason}))
            errors.append({"line": line_index, "reason": error_reason})
            continue
        preview.append(_build_account_preview_item({**row_payload, "valid": True}))
        rows.append(row_payload)
    valid = len(rows)
    invalid = len(errors)
    return {"preview": preview, "rows": rows, "errors": errors, "total": total, "valid": valid, "invalid": invalid}

def _parse_accounts_standard_csv(content: str) -> Dict[str, Any]:
    preview = []
    rows = []
    errors = []
    total = 0
    reader = csv.DictReader(io.StringIO(content))
    for row in reader:
        line_index = reader.line_num
        row_lower = {str(key).strip().lower(): value for key, value in row.items() if key}
        username = _clean_text(row_lower.get("username"))
        password = _clean_text(row_lower.get("password"))
        totp_secret = _clean_text(row_lower.get("totp_secret"))
        email = _clean_text(row_lower.get("email"))
        email_password = _clean_text(row_lower.get("email_password"))
        cookie = _clean_text(row_lower.get("cookie"))
        browser_profile_id = _clean_text(row_lower.get("browser_profile_id"))
        if not any([username, password, totp_secret, email, email_password, cookie, browser_profile_id]):
            continue
        total += 1
        error_reason = None
        missing_fields = [field for field, value in {
            "username": username,
            "password": password,
            "email": email,
            "email_password": email_password
        }.items() if not value]
        if missing_fields:
            error_reason = "必填字段缺失：" + "、".join(missing_fields)
        row_payload = {
            "line": line_index,
            "username": username,
            "password": password,
            "totp_secret": totp_secret,
            "email": email,
            "email_password": email_password,
            "cookie": cookie,
            "browser_profile_id": browser_profile_id
        }
        if error_reason:
            preview.append(_build_account_preview_item({**row_payload, "valid": False, "error": error_reason}))
            errors.append({"line": line_index, "reason": error_reason})
            continue
        preview.append(_build_account_preview_item({**row_payload, "valid": True}))
        rows.append(row_payload)
    valid = len(rows)
    invalid = len(errors)
    return {"preview": preview, "rows": rows, "errors": errors, "total": total, "valid": valid, "invalid": invalid}

def _parse_proxies_colon_lines(content: str) -> Dict[str, Any]:
    preview = []
    rows = []
    errors = []
    total = 0
    for line_index, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        total += 1
        parts = [part.strip() for part in line.split(":")]
        error_reason = None
        host = parts[0].strip() if len(parts) > 0 else ""
        port_value = parts[1].strip() if len(parts) > 1 else ""
        username = parts[2].strip() if len(parts) > 2 else ""
        password = parts[3].strip() if len(parts) > 3 else ""
        port = None
        if not host or not port_value:
            error_reason = "必填字段缺失：ip、port"
        if not error_reason:
            try:
                port = int(port_value)
            except ValueError:
                error_reason = "端口必须是数字"
        row_payload = {
            "line": line_index,
            "host": host,
            "port": port,
            "username": username or None,
            "password": password or None
        }
        if error_reason:
            preview.append(_build_proxy_preview_item({**row_payload, "valid": False, "error": error_reason}))
            errors.append({"line": line_index, "reason": error_reason})
            continue
        preview.append(_build_proxy_preview_item({**row_payload, "valid": True}))
        rows.append(row_payload)
    valid = len(rows)
    invalid = len(errors)
    return {"preview": preview, "rows": rows, "errors": errors, "total": total, "valid": valid, "invalid": invalid}

def _parse_proxies_standard_csv(content: str) -> Dict[str, Any]:
    preview = []
    rows = []
    errors = []
    total = 0
    reader = csv.DictReader(io.StringIO(content))
    for row in reader:
        line_index = reader.line_num
        row_lower = {str(key).strip().lower(): value for key, value in row.items() if key}
        host = _clean_text(row_lower.get("ip")) or _clean_text(row_lower.get("host"))
        port_value = _clean_text(row_lower.get("port"))
        username = _clean_text(row_lower.get("username"))
        password = _clean_text(row_lower.get("password"))
        if not any([host, port_value, username, password]):
            continue
        total += 1
        error_reason = None
        port = None
        if not host or not port_value:
            error_reason = "必填字段缺失：ip、port"
        if not error_reason:
            try:
                port = int(port_value)
            except ValueError:
                error_reason = "端口必须是数字"
        row_payload = {
            "line": line_index,
            "host": host,
            "port": port,
            "username": username or None,
            "password": password or None
        }
        if error_reason:
            preview.append(_build_proxy_preview_item({**row_payload, "valid": False, "error": error_reason}))
            errors.append({"line": line_index, "reason": error_reason})
            continue
        preview.append(_build_proxy_preview_item({**row_payload, "valid": True}))
        rows.append(row_payload)
    valid = len(rows)
    invalid = len(errors)
    return {"preview": preview, "rows": rows, "errors": errors, "total": total, "valid": valid, "invalid": invalid}

async def preview_accounts_csv(file_content: str) -> Dict[str, Any]:
    assert isinstance(file_content, str)
    content = file_content.replace("\ufeff", "")
    first_line = _get_first_non_empty_line(content)
    if not first_line:
        return {"preview": [], "rows": [], "errors": [], "total": 0, "valid": 0, "invalid": 0}
    is_standard = _has_standard_header(first_line, ACCOUNT_HEADERS)
    if is_standard:
        return _parse_accounts_standard_csv(content)
    return _parse_accounts_colon_lines(content)

async def preview_proxies_csv(file_content: str) -> Dict[str, Any]:
    assert isinstance(file_content, str)
    content = file_content.replace("\ufeff", "")
    first_line = _get_first_non_empty_line(content)
    if not first_line:
        return {"preview": [], "rows": [], "errors": [], "total": 0, "valid": 0, "invalid": 0}
    is_standard = _has_standard_header(first_line, PROXY_HEADERS)
    if is_standard:
        return _parse_proxies_standard_csv(content)
    return _parse_proxies_colon_lines(content)

def build_accounts_csv_template() -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(list(ACCOUNT_HEADERS))
    writer.writerow(["user001", "pass001", "2fa-secret", "user001@example.com", "emailpass", "cookie-string", "profile001"])
    return output.getvalue()

def build_proxies_csv_template() -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(list(PROXY_HEADERS))
    writer.writerow(["130.180.231.83", "8225", "user", "pass"])
    return output.getvalue()

async def batch_import_accounts(db: AsyncSession, raw_text: str):
    """批量导入 FB 账号"""
    success_count = 0
    fail_count = 0
    errors = []
    
    lines = raw_text.strip().split('\n')
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
            
        try:
            # 解析 UID:密码:2FA密钥:邮箱:邮箱密码:Cookie:浏览器ProfileID
            # 按照建议：先从左取前 5 个字段（username, password, totp, email, email_password）
            # 剩余部分包含 Cookie 和 ProfileID
            parts = line.split(":", 5)
            if len(parts) < 6:
                raise ValueError("Format error: Not enough fields (expected at least 6 parts)")
                
            username = parts[0].strip()
            password = parts[1].strip()
            totp_secret = parts[2].strip()
            email = parts[3].strip()
            email_password = parts[4].strip()
            
            rest = parts[5]
            # 从右边找最后一个 : 分割 Cookie 和 ProfileID
            last_colon_index = rest.rfind(":")
            if last_colon_index == -1:
                 # 如果没有冒号，说明缺少 ProfileID 或者 Cookie 格式不对
                 # 这里假设必须有 ProfileID，哪怕为空也应该有分隔符？
                 # 根据示例数据，最后是 :ProfileID
                 raise ValueError("Format error: Cannot separate Cookie and ProfileID")
            
            cookie = rest[:last_colon_index].strip()
            browser_profile_id = rest[last_colon_index+1:].strip()
            
            # 检查 username 是否存在
            stmt = select(FBAccount).where(FBAccount.username == username)
            result = await db.execute(stmt)
            if result.scalar_one_or_none():
                raise ValueError(f"Username {username} already exists")
                
            # 查找并自动绑定窗口
            browser_window_id = None
            notes = None
            if browser_profile_id:
                stmt_win = select(BrowserWindow).where(BrowserWindow.bit_window_id == browser_profile_id)
                res_win = await db.execute(stmt_win)
                win = res_win.scalar_one_or_none()
                if win:
                    # 检查窗口是否被占用
                    if win.status == "空闲":
                        browser_window_id = win.id
                        win.status = "使用中"
                        db.add(win)
                    else:
                         notes = f"Browser Profile {browser_profile_id} found but busy/bound."
                else:
                    notes = f"Browser Profile {browser_profile_id} not found."
            
            new_account = FBAccount(
                username=username,
                password_encrypted=encrypt_value(password),
                totp_secret_encrypted=encrypt_value(totp_secret) if totp_secret else None,
                email=email,
                email_password_encrypted=encrypt_value(email_password),
                cookie_encrypted=encrypt_value(cookie),
                region="US", # Default
                status="待养号",
                browser_window_id=browser_window_id,
                notes=notes
            )
            db.add(new_account)
            success_count += 1
            
        except Exception as e:
            fail_count += 1
            errors.append({"line": i + 1, "reason": str(e)})
            
    await db.commit()
    return {"success_count": success_count, "fail_count": fail_count, "errors": errors}

async def batch_import_proxies(db: AsyncSession, raw_text: str):
    """批量导入代理 IP"""
    success_count = 0
    fail_count = 0
    errors = []
    
    lines = raw_text.strip().split('\n')
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
            
        try:
            # IP地址:端口:用户名:密码
            parts = line.split(":")
            if len(parts) < 2:
                raise ValueError("Format error: Host:Port required")
                
            host = parts[0].strip()
            try:
                port = int(parts[1].strip())
            except ValueError:
                raise ValueError("Port must be integer")
                
            username = parts[2].strip() if len(parts) > 2 else None
            password = parts[3].strip() if len(parts) > 3 else None
            
            # 检查重复
            stmt = select(ProxyIP).where(and_(ProxyIP.host == host, ProxyIP.port == port))
            result = await db.execute(stmt)
            if result.scalar_one_or_none():
                raise ValueError(f"Proxy {host}:{port} already exists")
                
            new_proxy = ProxyIP(
                host=host,
                port=port,
                username=username,
                password_encrypted=encrypt_value(password) if password else None,
                type="socks5",
                status="空闲"
            )
            db.add(new_proxy)
            success_count += 1
            
        except Exception as e:
            fail_count += 1
            errors.append({"line": i + 1, "reason": str(e)})
            
    await db.commit()
    return {"success_count": success_count, "fail_count": fail_count, "errors": errors}

async def delete_browser_window(db: AsyncSession, window_id: int):
    """删除浏览器窗口记录"""
    window = await db.get(BrowserWindow, window_id)
    if not window:
        raise HTTPException(status_code=404, detail="Window not found")
        
    # 检查是否有绑定账号
    stmt = select(FBAccount).where(FBAccount.browser_window_id == window.id, FBAccount.is_deleted == False)
    result = await db.execute(stmt)
    bound_account = result.scalar_one_or_none()
    
    if bound_account:
        raise HTTPException(status_code=400, detail=f"该窗口仍被账号 {bound_account.username} 绑定，请先解绑")
        
    if window.bit_window_id:
        client = BitBrowserClient()
        try:
            await client.delete_browser(window.bit_window_id)
        except BitBrowserNotRunningError:
            raise HTTPException(status_code=503, detail="比特浏览器未运行，无法删除窗口")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"比特浏览器删除失败: {str(e)}")

    await db.delete(window)
    await db.commit()
    return True

async def delete_proxy(db: AsyncSession, proxy_id: int):
    """删除代理 IP"""
    # 检查是否有账号绑定该代理
    stmt = select(FBAccount).where(FBAccount.proxy_id == proxy_id, FBAccount.is_deleted == False)
    result = await db.execute(stmt)
    bound_account = result.scalar_one_or_none()
    
    if bound_account:
        raise HTTPException(status_code=400, detail=f"该代理仍被账号 {bound_account.username} 绑定，请先解绑")
        
    proxy = await db.get(ProxyIP, proxy_id)
    if not proxy:
        raise HTTPException(status_code=404, detail="Proxy not found")
        
    await db.delete(proxy)
    await db.commit()
    return True

async def get_comments(db: AsyncSession, language: str = None, category: str = None):
    stmt = select(CommentPool)
    if language:
        stmt = stmt.where(CommentPool.language == language)
    if category:
        stmt = stmt.where(CommentPool.category == category)
    stmt = stmt.order_by(CommentPool.use_count.asc())
    result = await db.execute(stmt)
    return result.scalars().all()

async def create_comment(db: AsyncSession, data: CommentCreate):
    comment = CommentPool(
        content=data.content,
        language=data.language,
        category=data.category
    )
    db.add(comment)
    await db.flush()
    await db.refresh(comment)
    return comment

async def batch_create_comments(db: AsyncSession, items: list[CommentCreate]) -> int:
    success_count = 0
    for item in items:
        comment = CommentPool(
            content=item.content,
            language=item.language,
            category=item.category
        )
        db.add(comment)
        success_count += 1
    await db.commit()
    return success_count

async def update_comment(db: AsyncSession, comment_id: int, data: CommentCreate):
    comment = await db.get(CommentPool, comment_id)
    if not comment:
        return None
    comment.content = data.content
    comment.language = data.language
    comment.category = data.category
    db.add(comment)
    await db.flush()
    await db.refresh(comment)
    return comment

async def delete_comment(db: AsyncSession, comment_id: int) -> bool:
    comment = await db.get(CommentPool, comment_id)
    if not comment:
        return False
    await db.delete(comment)
    await db.commit()
    return True

async def pick_comment(db: AsyncSession, language: str = "en"):
    stmt = (
        select(CommentPool)
        .where(CommentPool.language == language)
        .order_by(CommentPool.use_count.asc(), CommentPool.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    result = await db.execute(stmt)
    comment = result.scalar_one_or_none()
    if not comment:
        return None
    comment.use_count += 1
    comment.last_used_at = datetime.utcnow()
    db.add(comment)
    await db.commit()
    await db.refresh(comment)
    return comment

async def upload_avatars(db: AsyncSession, files, asset_type: str):
    if asset_type not in ["avatar", "cover"]:
        raise HTTPException(status_code=400, detail="Invalid type")
    if not files:
        return []
    target_dir = "assets/avatars" if asset_type == "avatar" else "assets/covers"
    os.makedirs(target_dir, exist_ok=True)
    allowed_extensions = {".jpg", ".jpeg", ".png"}
    max_size = 5 * 1024 * 1024
    created_items = []
    for file in files:
        original_name = file.filename or ""
        extension = os.path.splitext(original_name)[1].lower()
        if extension not in allowed_extensions:
            raise HTTPException(status_code=400, detail="Invalid file type")
        content = await file.read()
        if len(content) > max_size:
            raise HTTPException(status_code=400, detail="File too large")
        new_name = f"{uuid4().hex}{extension}"
        relative_path = os.path.join(target_dir, new_name).replace("\\", "/")
        absolute_path = os.path.join(target_dir, new_name)
        with open(absolute_path, "wb") as out_file:
            out_file.write(content)
        avatar = AvatarAsset(
            file_path=relative_path,
            original_filename=original_name,
            type=asset_type,
            is_used=False
        )
        db.add(avatar)
        created_items.append(avatar)
    await db.commit()
    for avatar in created_items:
        await db.refresh(avatar)
    return created_items

async def get_avatars(db: AsyncSession, asset_type: str = None, is_used: bool = None):
    stmt = select(AvatarAsset)
    if asset_type:
        stmt = stmt.where(AvatarAsset.type == asset_type)
    if is_used is not None:
        stmt = stmt.where(AvatarAsset.is_used == is_used)
    result = await db.execute(stmt)
    return result.scalars().all()

async def delete_avatar(db: AsyncSession, avatar_id: int):
    avatar = await db.get(AvatarAsset, avatar_id)
    if not avatar:
        return None
    if avatar.used_by_account_id is not None:
        return False
    absolute_path = avatar.file_path.replace("/", os.sep)
    if os.path.exists(absolute_path):
        try:
            os.remove(absolute_path)
        except OSError:
            raise HTTPException(status_code=500, detail="Failed to delete file")
    await db.delete(avatar)
    await db.commit()
    return True

async def pick_avatar(db: AsyncSession, asset_type: str = "avatar"):
    stmt = (
        select(AvatarAsset)
        .where(AvatarAsset.is_used == False, AvatarAsset.type == asset_type)
        .order_by(func.random())
        .limit(1)
        .with_for_update()
    )
    result = await db.execute(stmt)
    avatar = result.scalar_one_or_none()
    if not avatar:
        return None
    avatar.is_used = True
    db.add(avatar)
    await db.commit()
    await db.refresh(avatar)
    return avatar

async def release_avatar(db: AsyncSession, account_id: int):
    stmt = select(AvatarAsset).where(AvatarAsset.used_by_account_id == account_id)
    result = await db.execute(stmt)
    avatars = result.scalars().all()
    for avatar in avatars:
        avatar.is_used = False
        avatar.used_by_account_id = None
        db.add(avatar)
    await db.commit()


