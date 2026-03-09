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
    if update_data.cookie is not None:
        account.cookie_encrypted = encrypt_value(update_data.cookie)
        
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
    # 预加载绑定的账号和代理
    stmt = select(BrowserWindow).options(
        selectinload(BrowserWindow.fb_account).selectinload(FBAccount.proxy)
    )
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
