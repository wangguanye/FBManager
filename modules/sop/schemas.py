from typing import Dict, Any, List
from pydantic import BaseModel, Field, ConfigDict

class TaskItem(BaseModel):
    action: str
    type: str = "auto"
    params: Dict[str, Any] = Field(default_factory=dict)

class DayConfig(BaseModel):
    day: int
    is_default: bool = False
    once_tasks: List[TaskItem] = Field(default_factory=list)
    daily_tasks: List[TaskItem] = Field(default_factory=list)
    online_minutes: Dict[str, int] = Field(default_factory=lambda: {"min": 30, "max": 120})

class SOPConfig(BaseModel):
    days: List[DayConfig] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)
