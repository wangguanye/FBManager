from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from modules.asset.models import FBAccount, ProxyIP, BrowserWindow
from modules.monitor.models import ActionLog, NurtureTask
from modules.monitor.service import create_alert

async def cascade_on_ban(db: AsyncSession, account_id: int) -> dict:
    assert account_id > 0
    account = await db.get(FBAccount, account_id)
    if not account:
        return {"proxy_disabled": False, "window_disabled": False}

    account.status = "已封禁"
    db.add(account)

    proxy_disabled = False
    window_disabled = False
    proxy_host = "-"
    window_name = "-"

    if account.proxy_id:
        proxy = await db.get(ProxyIP, account.proxy_id)
        if proxy:
            proxy.status = "永久禁用"
            proxy_disabled = True
            proxy_host = proxy.host or "-"
            db.add(proxy)

    if account.browser_window_id:
        window = await db.get(BrowserWindow, account.browser_window_id)
        if window:
            window.status = "永久禁用"
            window_disabled = True
            window_name = window.name or "-"
            db.add(window)

    stmt_tasks = select(NurtureTask).where(
        NurtureTask.fb_account_id == account_id,
        NurtureTask.status.in_(["pending", "running"])
    )
    result_tasks = await db.execute(stmt_tasks)
    tasks = result_tasks.scalars().all()
    for task in tasks:
        task.status = "cancelled"
        db.add(task)

    log = ActionLog(
        fb_account_id=account_id,
        action_type="CASCADE_BAN",
        level="CRITICAL",
        message=f"账号 {account.username} 已封禁，已级联禁用代理 {proxy_host} 和窗口 {window_name}"
    )
    db.add(log)
    await create_alert(
        db,
        account_id,
        "CRITICAL",
        "账号封禁级联",
        f"账号 {account.username} 已封禁，已级联禁用代理 {proxy_host} 和窗口 {window_name}"
    )

    await db.flush()
    return {"proxy_disabled": proxy_disabled, "window_disabled": window_disabled}

async def cascade_on_recovery(db: AsyncSession, account_id: int):
    assert account_id > 0
    account = await db.get(FBAccount, account_id)
    if not account:
        return

    account.status = "养号中"
    db.add(account)

    proxy_host = "-"
    window_name = "-"

    if account.proxy_id:
        proxy = await db.get(ProxyIP, account.proxy_id)
        if proxy:
            proxy.status = "使用中"
            proxy_host = proxy.host or "-"
            db.add(proxy)

    if account.browser_window_id:
        window = await db.get(BrowserWindow, account.browser_window_id)
        if window:
            window.status = "使用中"
            window_name = window.name or "-"
            db.add(window)

    log = ActionLog(
        fb_account_id=account_id,
        action_type="CASCADE_RECOVERY",
        level="INFO",
        message=f"账号 {account.username} 已恢复，代理 {proxy_host} 与窗口 {window_name} 状态恢复"
    )
    db.add(log)
    await db.flush()

async def cascade_ban(db: AsyncSession, account_id: int):
    await cascade_on_ban(db, account_id)

async def update_account_status_cascade(db: AsyncSession, account_id: int, new_status: str):
    """
    更新账号状态并触发级联操作
    """
    if new_status in ["已封禁", "banned"]:
        await cascade_on_ban(db, account_id)
        return
    if new_status in ["养号中", "nurturing"]:
        await cascade_on_recovery(db, account_id)

async def check_resource_availability():
    """
    定期检查并同步资源状态。
    """
    # TODO: 实现资源状态同步逻辑
    pass
