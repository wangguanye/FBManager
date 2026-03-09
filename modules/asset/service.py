from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_
from sqlalchemy.orm import selectinload
from modules.asset.models import FBAccount, ProxyIP, BrowserWindow
from modules.asset.schemas import FBAccountCreate, FBAccountUpdate, FBAccountBind, ProxyIPCreate, ProxyIPUpdate, BrowserWindowCreate
from core.crypto import encrypt_value
from core.cascade import update_account_status_cascade
from fastapi import HTTPException
from modules.rpa.browser_client import BitBrowserClient, BitBrowserNotRunningError

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
        totp_secret_encrypted=encrypt_value(account.totp_secret) if account.totp_secret else None
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
    return result.scalars().all()

async def get_fb_account_by_id(db: AsyncSession, account_id: int):
    stmt = select(FBAccount).where(FBAccount.id == account_id, FBAccount.is_deleted == False)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()

async def update_fb_account(db: AsyncSession, account_id: int, update_data: FBAccountUpdate):
    account = await get_fb_account_by_id(db, account_id)
    if not account:
        return None
    
    # 检查状态变更并触发级联
    if update_data.status and update_data.status != account.status:
        # 如果是封禁，触发级联
        if update_data.status == "已封禁":
            await update_account_status_cascade(db, account_id, "已封禁")
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
        
    db.add(account)
    await db.flush()
    await db.refresh(account)
    return account

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
    if proxy.status != "空闲":
        raise HTTPException(status_code=400, detail=f"Proxy {proxy.host} is not idle")
        
    # 验证窗口
    window = await db.get(BrowserWindow, bind_data.window_id)
    if not window:
        raise HTTPException(status_code=404, detail="Window not found")
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
    stmt = select(BrowserWindow)
    if status:
        stmt = stmt.where(BrowserWindow.status == status)
    result = await db.execute(stmt)
    return result.scalars().all()

async def sync_browser_windows(db: AsyncSession):
    """同步比特浏览器窗口"""
    client = BitBrowserClient()
    
    # 检查比特浏览器是否在线
    is_alive = await client.check_alive()
    if not is_alive:
        raise BitBrowserNotRunningError("BitBrowser is not running")
        
    # 分页获取所有窗口
    page = 0
    page_size = 50 # 每次获取50个
    all_windows = []
    
    while True:
        try:
            windows = await client.list_browsers(page=page, page_size=page_size)
            if not windows:
                break
            all_windows.extend(windows)
            if len(windows) < page_size:
                break
            page += 1
        except Exception as e:
            # 如果出错，可能是 API 问题，暂时中止同步
            raise e

    # 同步到数据库
    synced_count = 0
    new_count = 0
    
    for w in all_windows:
        bit_id = w.get("id")
        name = w.get("name", "Unknown")
        
        # 查找是否存在
        stmt = select(BrowserWindow).where(BrowserWindow.bit_window_id == bit_id)
        result = await db.execute(stmt)
        db_window = result.scalar_one_or_none()
        
        if db_window:
            # 更新名称
            if db_window.name != name:
                db_window.name = name
                db.add(db_window)
        else:
            # 创建新窗口
            new_window = BrowserWindow(
                bit_window_id=bit_id,
                name=name,
                status="空闲"
            )
            db.add(new_window)
            new_count += 1
        synced_count += 1
            
    await db.flush()
    return {"synced_count": synced_count, "new_count": new_count}

async def open_browser_window(db: AsyncSession, window_id: int):
    """打开浏览器窗口"""
    window = await db.get(BrowserWindow, window_id)
    if not window:
        raise HTTPException(status_code=404, detail="Window not found")
        
    client = BitBrowserClient()
    try:
        res = await client.open_browser(window.bit_window_id)
        # 可以在这里更新窗口状态，比如 "运行中"
        return res
    except BitBrowserNotRunningError:
        raise HTTPException(status_code=503, detail="BitBrowser is not running")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to open browser: {str(e)}")

async def close_browser_window(db: AsyncSession, window_id: int):
    """关闭浏览器窗口"""
    window = await db.get(BrowserWindow, window_id)
    if not window:
        raise HTTPException(status_code=404, detail="Window not found")
        
    client = BitBrowserClient()
    try:
        await client.close_browser(window.bit_window_id)
        return True
    except BitBrowserNotRunningError:
        raise HTTPException(status_code=503, detail="BitBrowser is not running")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to close browser: {str(e)}")
