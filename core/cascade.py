from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from modules.asset.models import FBAccount, ProxyIP, BrowserWindow
from modules.monitor.models import ActionLog, NurtureTask
from modules.monitor.service import create_alert

STATUS_ACCOUNT_BANNED = "\u5df2\u5c01\u7981"
STATUS_ACCOUNT_NURTURING = "\u517b\u53f7\u4e2d"
STATUS_PROXY_DISABLED = "\u6c38\u4e45\u7981\u7528"
STATUS_PROXY_IN_USE = "\u4f7f\u7528\u4e2d"
STATUS_WINDOW_DISABLED = "\u6c38\u4e45\u7981\u7528"
STATUS_WINDOW_IN_USE = "\u4f7f\u7528\u4e2d"


async def _log_critical(db: AsyncSession, account_id: int | None, message: str):
    db.add(
        ActionLog(
            fb_account_id=account_id,
            action_type="CASCADE",
            level="CRITICAL",
            message=message,
        )
    )
    await create_alert(
        db=db,
        fb_account_id=account_id,
        level="CRITICAL",
        title="\u8d44\u4ea7\u7ea7\u8054\u7981\u7528",
        message=message,
    )


async def cascade_on_ban(db: AsyncSession, account_id: int) -> dict:
    """Account banned -> disable bound proxy + window."""
    assert account_id > 0
    stmt = (
        select(FBAccount)
        .options(selectinload(FBAccount.proxy), selectinload(FBAccount.browser_window))
        .where(FBAccount.id == account_id)
    )
    result = await db.execute(stmt)
    account = result.scalar_one_or_none()
    if not account:
        return {"proxy_disabled": False, "window_disabled": False}

    account.status = STATUS_ACCOUNT_BANNED
    db.add(account)

    proxy_disabled = False
    window_disabled = False
    proxy_host = "-"
    window_name = "-"

    if account.proxy:
        proxy_host = account.proxy.host or "-"
        if account.proxy.status != STATUS_PROXY_DISABLED:
            account.proxy.status = STATUS_PROXY_DISABLED
            db.add(account.proxy)
            proxy_disabled = True

    if account.browser_window:
        window_name = account.browser_window.name or "-"
        if account.browser_window.status != STATUS_WINDOW_DISABLED:
            account.browser_window.status = STATUS_WINDOW_DISABLED
            account.browser_window.is_running = False
            db.add(account.browser_window)
            window_disabled = True

    stmt_tasks = select(NurtureTask).where(
        NurtureTask.fb_account_id == account_id,
        NurtureTask.status.in_(["pending", "running"]),
    )
    result_tasks = await db.execute(stmt_tasks)
    for task in result_tasks.scalars().all():
        task.status = "cancelled"
        db.add(task)

    msg = (
        f"\u8d26\u53f7 {account.username} \u5df2\u5c01\u7981\uff0c"
        f"\u5df2\u7ea7\u8054\u7981\u7528\u4ee3\u7406 {proxy_host} \u548c\u7a97\u53e3 {window_name}"
    )
    db.add(
        ActionLog(
            fb_account_id=account_id,
            action_type="CASCADE_BAN",
            level="CRITICAL",
            message=msg,
        )
    )
    await create_alert(db, account_id, "CRITICAL", "\u8d26\u53f7\u5c01\u7981\u7ea7\u8054", msg)

    await db.flush()
    return {"proxy_disabled": proxy_disabled, "window_disabled": window_disabled}


async def cascade_on_recovery(db: AsyncSession, account_id: int):
    """Account recovery -> mark bound proxy/window in-use."""
    assert account_id > 0
    stmt = (
        select(FBAccount)
        .options(selectinload(FBAccount.proxy), selectinload(FBAccount.browser_window))
        .where(FBAccount.id == account_id)
    )
    result = await db.execute(stmt)
    account = result.scalar_one_or_none()
    if not account:
        return

    account.status = STATUS_ACCOUNT_NURTURING
    db.add(account)

    proxy_host = "-"
    window_name = "-"

    if account.proxy:
        account.proxy.status = STATUS_PROXY_IN_USE
        proxy_host = account.proxy.host or "-"
        db.add(account.proxy)

    if account.browser_window:
        account.browser_window.status = STATUS_WINDOW_IN_USE
        window_name = account.browser_window.name or "-"
        db.add(account.browser_window)

    db.add(
        ActionLog(
            fb_account_id=account_id,
            action_type="CASCADE_RECOVERY",
            level="INFO",
            message=(
                f"\u8d26\u53f7 {account.username} \u5df2\u6062\u590d\uff0c"
                f"\u4ee3\u7406 {proxy_host} \u4e0e\u7a97\u53e3 {window_name} \u72b6\u6001\u5df2\u6062\u590d"
            ),
        )
    )
    await db.flush()


async def cascade_on_proxy_disabled(proxy_id: int, db: AsyncSession) -> dict:
    """
    Proxy permanently disabled -> ban bound account + disable bound window.
    This function updates related assets directly and does NOT call other cascade functions.
    """
    proxy = await db.get(ProxyIP, proxy_id)
    if not proxy:
        return {"cascaded": False, "account": None, "window": None}

    stmt = (
        select(FBAccount)
        .options(selectinload(FBAccount.browser_window))
        .where(FBAccount.proxy_id == proxy_id, FBAccount.is_deleted == False)
        .limit(1)
    )
    result = await db.execute(stmt)
    account = result.scalar_one_or_none()

    account_name = account.username if account else None
    window_name = None
    cascaded = False

    if account:
        if account.status != STATUS_ACCOUNT_BANNED:
            old_status = account.status
            account.status = STATUS_ACCOUNT_BANNED
            db.add(account)
            cascaded = True
            await _log_critical(
                db,
                account.id,
                (
                    f"\u4ee3\u7406 {proxy.host}:{proxy.port} \u88ab\u6c38\u4e45\u7981\u7528\uff0c"
                    f"\u7ea7\u8054\u5c01\u7981\u8d26\u53f7 {account.username}\uff08\u539f\u72b6\u6001: {old_status}\uff09"
                ),
            )

        window = account.browser_window
        if window:
            window_name = window.name
            if window.status != STATUS_WINDOW_DISABLED or bool(window.is_running):
                window.status = STATUS_WINDOW_DISABLED
                window.is_running = False
                db.add(window)
                cascaded = True
                await _log_critical(
                    db,
                    account.id,
                    (
                        f"\u4ee3\u7406 {proxy.host}:{proxy.port} \u88ab\u6c38\u4e45\u7981\u7528\uff0c"
                        f"\u7ea7\u8054\u7981\u7528\u7a97\u53e3 {window.name}"
                    ),
                )

    await db.flush()
    return {"cascaded": cascaded, "account": account_name, "window": window_name}


async def cascade_on_window_disabled(window_id: int, db: AsyncSession) -> dict:
    """
    Window permanently disabled -> ban bound account + disable bound proxy.
    This function updates related assets directly and does NOT call other cascade functions.
    """
    window = await db.get(BrowserWindow, window_id)
    if not window:
        return {"cascaded": False, "account": None, "proxy": None}

    if window.status == STATUS_WINDOW_DISABLED:
        window.is_running = False
        db.add(window)

    stmt = (
        select(FBAccount)
        .options(selectinload(FBAccount.proxy))
        .where(FBAccount.browser_window_id == window_id, FBAccount.is_deleted == False)
        .limit(1)
    )
    result = await db.execute(stmt)
    account = result.scalar_one_or_none()

    account_name = account.username if account else None
    proxy_label = None
    cascaded = False

    if account:
        if account.status != STATUS_ACCOUNT_BANNED:
            old_status = account.status
            account.status = STATUS_ACCOUNT_BANNED
            db.add(account)
            cascaded = True
            await _log_critical(
                db,
                account.id,
                (
                    f"\u7a97\u53e3 {window.name if window.name else window_id} \u88ab\u6c38\u4e45\u7981\u7528\uff0c"
                    f"\u7ea7\u8054\u5c01\u7981\u8d26\u53f7 {account.username}\uff08\u539f\u72b6\u6001: {old_status}\uff09"
                ),
            )

        proxy = account.proxy
        if proxy:
            proxy_label = f"{proxy.host}:{proxy.port}"
            if proxy.status != STATUS_PROXY_DISABLED:
                proxy.status = STATUS_PROXY_DISABLED
                db.add(proxy)
                cascaded = True
                await _log_critical(
                    db,
                    account.id,
                    (
                        f"\u7a97\u53e3 {window.name if window.name else window_id} \u88ab\u6c38\u4e45\u7981\u7528\uff0c"
                        f"\u7ea7\u8054\u7981\u7528\u4ee3\u7406 {proxy.host}:{proxy.port}"
                    ),
                )

    await db.flush()
    return {"cascaded": cascaded, "account": account_name, "proxy": proxy_label}


async def cascade_ban(db: AsyncSession, account_id: int):
    await cascade_on_ban(db, account_id)


async def update_account_status_cascade(db: AsyncSession, account_id: int, new_status: str):
    """Update account status and trigger cascading side effects."""
    if new_status in [STATUS_ACCOUNT_BANNED, "banned"]:
        await cascade_on_ban(db, account_id)
        return
    if new_status in [STATUS_ACCOUNT_NURTURING, "nurturing"]:
        await cascade_on_recovery(db, account_id)


async def check_resource_availability():
    """Reserved for future resource health sync jobs."""
    return None
