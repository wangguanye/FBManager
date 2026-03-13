# FIX-9 done
import os
import yaml
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
        return yaml.safe_load(f) or {}


def _normalize_online_minutes(value):
    if isinstance(value, dict):
        min_value = int(value.get("min", 30))
        max_value = int(value.get("max", min_value))
        return {"min": min_value, "max": max_value}
    if isinstance(value, (int, float)):
        int_value = int(value)
        return {"min": int_value, "max": int_value}
    return {"min": 30, "max": 120}


def _migrate_list_to_dict(sop_list: list) -> dict:
    """Convert legacy list-format SOP into dict-format SOP."""
    days = {}
    default_item = None
    max_days = 15

    for item in sop_list:
        if not isinstance(item, dict):
            continue

        payload = {
            "once_tasks": item.get("once_tasks", []),
            "daily_tasks": item.get("daily_tasks", []),
            "online_minutes": _normalize_online_minutes(item.get("online_minutes")),
        }

        if item.get("is_default"):
            payload["is_default"] = True
            default_item = payload
            continue

        day_num = item.get("day")
        if day_num is None:
            continue
        try:
            day_int = int(day_num)
        except (TypeError, ValueError):
            continue

        days[day_int] = payload
        if day_int > max_days:
            max_days = day_int

    result = {"max_days": max_days, "days": days}
    if default_item:
        result["default"] = default_item
    return result


def load_sop_config() -> dict:
    """Return nurture_sop in dict format."""
    config = load_config()
    sop_config = config.get("nurture_sop", {})

    if isinstance(sop_config, dict):
        return sop_config
    if isinstance(sop_config, list):
        return _migrate_list_to_dict(sop_config)
    return {}


def load_sop_for_day(day_number: int) -> dict:
    assert day_number > 0

    sop = load_sop_config()
    days = sop.get("days", {}) if isinstance(sop, dict) else {}

    day_config = None
    if isinstance(days, dict):
        day_config = days.get(str(day_number)) or days.get(day_number)

    if not day_config:
        default_item = sop.get("default") if isinstance(sop, dict) else None
        if isinstance(default_item, dict):
            day_config = default_item

    if not isinstance(day_config, dict):
        day_config = {
            "online_minutes": {"min": 0, "max": 0},
            "once_tasks": [],
            "daily_tasks": [],
        }

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
        NurtureTask.status == "completed",
    ).limit(1)
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


def get_tasks_for_day(day_number: int) -> dict:
    sop = load_sop_for_day(day_number)
    return {
        "once_tasks": sop.get("once_tasks", []),
        "daily_tasks": sop.get("daily_tasks", []),
        "online_minutes": sop.get("online_minutes", {"min": 0, "max": 0}),
    }
