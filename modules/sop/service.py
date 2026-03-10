from __future__ import annotations

import importlib
import os
import shutil
from datetime import datetime
from typing import Dict, Any, List

import yaml
from loguru import logger

from modules.sop.schemas import SOPConfig, DayConfig, TaskItem

CONFIG_PATH = "config.yaml"
DEFAULT_MAX_DAYS = 15
BACKUP_PREFIX = "config_"
BACKUP_TIME_FORMAT = "%Y%m%d_%H%M%S"
DEFAULT_BACKUP_DIR = "backups"

def _load_config_dict() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def _get_backup_dir(config: Dict[str, Any]) -> str:
    backup_config = config.get("backup", {}) if isinstance(config, dict) else {}
    backup_dir = backup_config.get("backup_dir", DEFAULT_BACKUP_DIR)
    return str(backup_dir).rstrip("/\\")

def _safe_dump_config(config: Dict[str, Any]) -> None:
    try:
        content = yaml.safe_dump(config, allow_unicode=True, sort_keys=False, preserve_quotes=True)
    except TypeError:
        content = yaml.safe_dump(config, allow_unicode=True, sort_keys=False)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(content)

def _normalize_online_minutes(value: Any) -> Dict[str, int]:
    if isinstance(value, dict):
        min_value = int(value.get("min", 0))
        max_value = int(value.get("max", min_value))
        return {"min": min_value, "max": max_value}
    if isinstance(value, (int, float)):
        int_value = int(value)
        return {"min": int_value, "max": int_value}
    return {"min": 30, "max": 120}

def _parse_task_items(items: Any) -> List[TaskItem]:
    result = []
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, dict):
            continue
        action = item.get("action")
        if not action:
            continue
        task_type = item.get("execution_type", item.get("type", "auto"))
        params = item.get("params") if isinstance(item.get("params"), dict) else {}
        result.append(TaskItem(action=action, type=task_type, params=params))
    return result

def _dump_task_items(items: List[TaskItem]) -> List[Dict[str, Any]]:
    result = []
    for item in items:
        payload = {"action": item.action, "execution_type": item.type}
        if item.params:
            payload["params"] = item.params
        result.append(payload)
    return result

def _reload_sop_loader() -> None:
    try:
        module = importlib.import_module("modules.nurture.sop_loader")
        importlib.reload(module)
    except Exception as e:
        logger.error(f"Failed to reload sop_loader: {e}")

def load_sop() -> SOPConfig:
    config = _load_config_dict()
    sop_config = config.get("nurture_sop", {}) if isinstance(config, dict) else {}
    max_days = int(sop_config.get("max_days", DEFAULT_MAX_DAYS))
    days_config = sop_config.get("days", {}) if isinstance(sop_config, dict) else {}
    day_items: List[DayConfig] = []
    if isinstance(days_config, dict):
        for key, value in days_config.items():
            if not isinstance(value, dict):
                continue
            try:
                day_number = int(key)
            except Exception:
                continue
            day_items.append(DayConfig(
                day=day_number,
                is_default=bool(value.get("is_default", False)),
                once_tasks=_parse_task_items(value.get("once_tasks", [])),
                daily_tasks=_parse_task_items(value.get("daily_tasks", [])),
                online_minutes=_normalize_online_minutes(value.get("online_minutes"))
            ))
    default_config = sop_config.get("default") if isinstance(sop_config, dict) else None
    if isinstance(default_config, dict):
        day_items.append(DayConfig(
            day=max_days + 1,
            is_default=True,
            once_tasks=_parse_task_items(default_config.get("once_tasks", [])),
            daily_tasks=_parse_task_items(default_config.get("daily_tasks", [])),
            online_minutes=_normalize_online_minutes(default_config.get("online_minutes"))
        ))
    day_items.sort(key=lambda item: item.day)
    return SOPConfig(days=day_items)

def save_sop(config: SOPConfig) -> SOPConfig:
    assert config is not None
    errors = validate_sop(config)
    if errors:
        raise ValueError(";".join(errors))
    current_config = _load_config_dict()
    max_days = int((current_config.get("nurture_sop", {}) or {}).get("max_days", DEFAULT_MAX_DAYS))
    days_map: Dict[int, Dict[str, Any]] = {}
    default_item = None
    for item in config.days:
        if item.is_default:
            if default_item is None:
                default_item = item
            continue
        if item.day in days_map:
            raise ValueError("duplicate_day")
        days_map[item.day] = {
            "online_minutes": item.online_minutes,
            "once_tasks": _dump_task_items(item.once_tasks),
            "daily_tasks": _dump_task_items(item.daily_tasks)
        }
    if not default_item:
        raise ValueError("missing_default")
    default_payload = {
        "is_default": True,
        "online_minutes": default_item.online_minutes,
        "once_tasks": _dump_task_items(default_item.once_tasks),
        "daily_tasks": _dump_task_items(default_item.daily_tasks)
    }
    current_config["nurture_sop"] = {
        "max_days": max_days,
        "days": days_map,
        "default": default_payload
    }
    backup_dir = _get_backup_dir(current_config)
    os.makedirs(backup_dir, exist_ok=True)
    backup_name = f"{BACKUP_PREFIX}{datetime.now().strftime(BACKUP_TIME_FORMAT)}.yaml"
    backup_path = os.path.join(backup_dir, backup_name)
    if os.path.exists(CONFIG_PATH):
        shutil.copyfile(CONFIG_PATH, backup_path)
    _safe_dump_config(current_config)
    _reload_sop_loader()
    return load_sop()

def get_available_actions() -> List[Dict[str, Any]]:
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "rpa", "actions"))
    if not os.path.isdir(base_dir):
        return []
    action_list: List[Dict[str, Any]] = []
    for filename in os.listdir(base_dir):
        if not filename.endswith(".py"):
            continue
        if filename.startswith("__"):
            continue
        module_name = filename[:-3]
        module_path = f"modules.rpa.actions.{module_name}"
        try:
            module = importlib.import_module(module_path)
            meta = getattr(module, "META", None)
            if not isinstance(meta, dict):
                continue
            action_list.append({
                "action_id": meta.get("action_id"),
                "name": meta.get("name"),
                "params_schema": meta.get("params_schema", {})
            })
        except Exception as e:
            logger.error(f"Failed to load action module {module_path}: {e}")
    return action_list

def validate_sop(config: SOPConfig) -> List[str]:
    assert config is not None
    errors: List[str] = []
    available_actions = {item["action_id"] for item in get_available_actions() if item.get("action_id")}
    day_set = set()
    default_count = 0
    for day in config.days:
        if day.is_default:
            default_count += 1
        else:
            if day.day in day_set:
                errors.append(f"duplicate_day:{day.day}")
            day_set.add(day.day)
        if len(day.daily_tasks) < 1:
            errors.append(f"missing_daily_tasks:{day.day}")
        for task in day.once_tasks + day.daily_tasks:
            if not task.action:
                errors.append(f"missing_action:{day.day}")
                continue
            if task.action not in available_actions:
                errors.append(f"invalid_action:{task.action}")
    if default_count != 1:
        errors.append("missing_default_template")
    return errors

def list_sop_backups() -> List[str]:
    config = _load_config_dict()
    backup_dir = _get_backup_dir(config)
    if not os.path.isdir(backup_dir):
        return []
    files = [name for name in os.listdir(backup_dir) if name.startswith(BACKUP_PREFIX) and name.endswith(".yaml")]
    files.sort(reverse=True)
    return files

def restore_sop_backup(filename: str) -> SOPConfig:
    assert filename
    safe_name = os.path.basename(filename)
    config = _load_config_dict()
    backup_dir = _get_backup_dir(config)
    backup_path = os.path.join(backup_dir, safe_name)
    if not os.path.exists(backup_path):
        raise FileNotFoundError("backup_not_found")
    shutil.copyfile(backup_path, CONFIG_PATH)
    _reload_sop_loader()
    return load_sop()
