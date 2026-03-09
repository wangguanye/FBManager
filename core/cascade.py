from sqlalchemy.ext.asyncio import AsyncSession
from modules.asset.models import FBAccount, ProxyIP, BrowserWindow
from modules.monitor.models import ActionLog

async def cascade_ban(db: AsyncSession, account_id: int):
    """
    级联禁用账号关联的资源。
    1. 关联 proxy_ip 状态改为"永久禁用"
    2. 关联 browser_window 状态改为"永久禁用"
    3. 写一条 CRITICAL 级别 action_log
    """
    account = await db.get(FBAccount, account_id)
    if not account:
        return

    # 1. 禁用关联代理
    if account.proxy_id:
        proxy = await db.get(ProxyIP, account.proxy_id)
        if proxy:
            proxy.status = "永久禁用"
            db.add(proxy)

    # 2. 禁用关联窗口
    if account.browser_window_id:
        window = await db.get(BrowserWindow, account.browser_window_id)
        if window:
            window.status = "永久禁用"
            db.add(window)

    # 3. 写日志
    log = ActionLog(
        fb_account_id=account_id,
        action_type="CASCADE_BAN",
        level="CRITICAL",
        message=f"账号 {account.username} 被封禁，已级联禁用关联代理和窗口"
    )
    db.add(log)
    
    await db.flush()

async def update_account_status_cascade(db: AsyncSession, account_id: int, new_status: str):
    """
    更新账号状态并触发级联操作
    """
    if new_status == "已封禁":
        await cascade_ban(db, account_id)

async def check_resource_availability():
    """
    定期检查并同步资源状态。
    """
    # TODO: 实现资源状态同步逻辑
    pass
