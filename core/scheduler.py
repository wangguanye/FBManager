from apscheduler.schedulers.asyncio import AsyncIOScheduler

# APScheduler 调度器实例（先空壳）
scheduler = AsyncIOScheduler()

async def start_scheduler():
    """
    启动调度器。
    """
    if not scheduler.running:
        scheduler.start()

async def stop_scheduler():
    """
    停止调度器。
    """
    if scheduler.running:
        scheduler.shutdown()
