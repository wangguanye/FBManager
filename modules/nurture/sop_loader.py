import yaml
import os
from loguru import logger

CONFIG_PATH = "config.yaml"

def load_config():
    if not os.path.exists(CONFIG_PATH):
        logger.error(f"Config file not found: {CONFIG_PATH}")
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def get_tasks_for_day(day_number: int) -> dict:
    """
    根据天数获取养号任务模板
    :param day_number: 养号第几天
    :return: {once_tasks: [], daily_tasks: [], online_minutes: int}
    """
    config = load_config()
    sop_config = config.get("nurture_sop", {})
    
    max_days = sop_config.get("max_days", 0)
    days_config = sop_config.get("days", {})
    default_config = sop_config.get("default", {
        "online_minutes": 30,
        "once_tasks": [],
        "daily_tasks": []
    })

    if day_number <= max_days:
        day_config = days_config.get(day_number, default_config)
    else:
        # 超过最大配置天数，使用默认配置
        day_config = default_config
        
    return {
        "once_tasks": day_config.get("once_tasks", []),
        "daily_tasks": day_config.get("daily_tasks", []),
        "online_minutes": day_config.get("online_minutes", 0)
    }
