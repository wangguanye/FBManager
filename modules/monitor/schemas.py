from pydantic import BaseModel, ConfigDict
from datetime import datetime, date
from typing import Optional, List

class NurtureTaskBase(BaseModel):
    fb_account_id: int
    day_number: int
    scheduled_date: date
    scheduled_time: Optional[datetime] = None
    action: Optional[str] = None
    task_type: str
    execution_type: str
    status: str = "pending"

class NurtureTaskCreate(NurtureTaskBase):
    pass

class NurtureTask(NurtureTaskBase):
    id: int
    retry_count: int
    result_log: Optional[str] = None
    executed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class ActionLogBase(BaseModel):
    fb_account_id: Optional[int] = None
    task_id: Optional[int] = None
    action_type: str
    level: str
    message: str

class ActionLog(ActionLogBase):
    id: int
    is_dismissed: bool = False
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class Alert(BaseModel):
    id: int
    fb_account_id: Optional[int] = None
    account_username: Optional[str] = None
    level: str
    title: str
    message: str
    is_dismissed: bool = False
    created_at: datetime
    dismissed_at: Optional[datetime] = None

class DashboardStats(BaseModel):
    account_stats: dict
    task_stats: dict
    active_rpa_count: int
    alert_count: int

class AlertCount(BaseModel):
    total: int
    error: int
    critical: int
