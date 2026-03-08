from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from modules.asset.models import FBAccount, ProxyIP, BrowserWindow
from modules.asset.schemas import FBAccountCreate, ProxyIPCreate, BrowserWindowCreate
from core.crypto import encrypt_value

async def create_fb_account(db: AsyncSession, account: FBAccountCreate):
    """创建 FB 账号并加密敏感信息"""
    db_account = FBAccount(
        username=account.username,
        password_encrypted=encrypt_value(account.password),
        email=account.email,
        email_password_encrypted=encrypt_value(account.email_password),
        region=account.region,
        target_timezone=account.target_timezone,
        status=account.status,
        notes=account.notes,
        totp_secret_encrypted=encrypt_value(account.totp_secret) if account.totp_secret else None
    )
    db.add(db_account)
    await db.flush()
    return db_account

async def get_fb_accounts(db: AsyncSession, skip: int = 0, limit: int = 100):
    """获取所有 FB 账号"""
    result = await db.execute(select(FBAccount).offset(skip).limit(limit))
    return result.scalars().all()

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

async def get_proxies(db: AsyncSession):
    """获取所有代理 IP"""
    result = await db.execute(select(ProxyIP))
    return result.scalars().all()

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

async def get_browser_windows(db: AsyncSession):
    """获取所有浏览器窗口"""
    result = await db.execute(select(BrowserWindow))
    return result.scalars().all()
