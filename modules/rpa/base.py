from abc import ABC, abstractmethod
import asyncio
import random
from typing import Dict, Any, Type
from loguru import logger
import yaml

class BaseAction(ABC):
    action_id: str  # e.g., "rpa.scroll_feed"

    @abstractmethod
    async def execute(self, page: Any, params: dict, logger) -> dict:
        """
        Execute the action.
        :param page: Playwright Page object
        :param params: Action parameters
        :param logger: Logger instance
        :return: {success: bool, message: str, data: {}}
        """
        pass

    async def random_delay(self, min_s=None, max_s=None):
        """
        Sleep for a random amount of time.
        If min_s/max_s are not provided, read from config.yaml rpa.action_delay_min/max.
        """
        if min_s is None or max_s is None:
            try:
                with open("config.yaml", "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f)
                rpa_config = config.get("rpa", {})
                min_s = min_s or rpa_config.get("action_delay_min", 2)
                max_s = max_s or rpa_config.get("action_delay_max", 8)
            except Exception:
                min_s = min_s or 2
                max_s = max_s or 8
        
        delay = random.uniform(min_s, max_s)
        await asyncio.sleep(delay)

ACTION_REGISTRY: Dict[str, Type[BaseAction]] = {}

def register_action(cls):
    """Decorator to register an action class."""
    if hasattr(cls, "action_id"):
        ACTION_REGISTRY[cls.action_id] = cls
    return cls
