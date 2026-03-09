import yaml
import os
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from modules.monitor.models import NurtureTask

CONFIG_PATH = "config.yaml"

def load_config():
    if not os.path.exists(CONFIG_PATH):
        logger.error(f"Config file not found: {CONFIG_PATH}")
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_sop_for_day(day_number: int) -> dict:
    assert day_number > 0
    config = load_config()
    sop_config = config.get("nurture_sop", {})
    days_config = sop_config.get("days", {})
    day_config = None

    if day_number in days_config:
        day_config = days_config.get(day_number)
    elif str(day_number) in days_config:
        day_config = days_config.get(str(day_number))

    if not day_config:
        for config_item in days_config.values():
            if isinstance(config_item, dict) and config_item.get("is_default") is True:
                day_config = config_item
                break

    if not day_config:
        day_config = sop_config.get("default")

    if not day_config:
        day_config = {"online_minutes": 0, "once_tasks": [], "daily_tasks": []}

    return day_config

def get_daily_tasks(day_number: int) -> list[dict]:
    sop = load_sop_for_day(day_number)
    return sop.get("daily_tasks", [])

def get_once_tasks(day_number: int) -> list[dict]:
    sop = load_sop_for_day(day_number)
    return sop.get("once_tasks", [])

async def is_task_completed(db: AsyncSession, account_id: int, day_number: int, action: str) -> bool:
    assert day_number > 0
    stmt = select(NurtureTask.id).where(
        NurtureTask.fb_account_id == account_id,
        NurtureTask.day_number == day_number,
        NurtureTask.action == action,
        NurtureTask.status == "completed"
    ).limit(1)
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None

def get_tasks_for_day(day_number: int) -> dict:
    sop = load_sop_for_day(day_number)
    return {
        "once_tasks": sop.get("once_tasks", []),
        "daily_tasks": sop.get("daily_tasks", []),
        "online_minutes": sop.get("online_minutes", 0)
    }
