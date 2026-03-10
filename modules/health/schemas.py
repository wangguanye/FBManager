from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional, Dict, Any

class HealthScoreOut(BaseModel):
    id: int
    fb_account_id: int
    score: int
    grade: str
    detail_json: Optional[Dict[str, Any]] = None
    calculated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class HealthOverviewOut(BaseModel):
    average_score: int
    total: int
    grade_counts: Dict[str, int]
