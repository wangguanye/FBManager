from pydantic import BaseModel, ConfigDict, computed_field
from datetime import datetime, date
from typing import Optional

class BMCreate(BaseModel):
    bm_id: str
    fb_account_id: Optional[int] = None
    name: Optional[str] = None
    region: Optional[str] = None

class BMUpdate(BaseModel):
    name: Optional[str] = None
    region: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    fb_account_id: Optional[int] = None

class BMOut(BaseModel):
    id: int
    bm_id: str
    fb_account_id: Optional[int] = None
    name: Optional[str] = None
    region: Optional[str] = None
    status: str
    created_at: datetime
    notes: Optional[str] = None

    @computed_field
    def ad_account_count(self) -> int:
        ad_accounts = getattr(self, "ad_accounts", None)
        if ad_accounts is None:
            return 0
        return len(ad_accounts)

    model_config = ConfigDict(from_attributes=True)

class AdAccountCreate(BaseModel):
    ad_account_id: str
    bm_id: Optional[int] = None
    name: Optional[str] = None
    spending_limit: str
    payment_method: Optional[str] = None

class AdAccountUpdate(BaseModel):
    name: Optional[str] = None
    spending_limit: Optional[str] = None
    payment_method: Optional[str] = None
    status: Optional[str] = None
    daily_budget: Optional[int] = None
    reason: Optional[str] = None
    notes: Optional[str] = None

class AdAccountOut(BaseModel):
    id: int
    ad_account_id: str
    bm_id: Optional[int] = None
    name: Optional[str] = None
    spending_limit: str
    payment_method: Optional[str] = None
    status: str
    daily_budget: int
    total_spend: int
    created_at: datetime
    notes: Optional[str] = None

    @computed_field
    def bm_name(self) -> Optional[str]:
        bm = getattr(self, "bm", None)
        if not bm:
            return None
        return bm.name

    model_config = ConfigDict(from_attributes=True)

class FanpageCreate(BaseModel):
    page_id: str
    fb_account_id: Optional[int] = None
    page_name: str
    page_url: Optional[str] = None

class FanpageUpdate(BaseModel):
    page_name: Optional[str] = None
    page_url: Optional[str] = None
    status: Optional[str] = None
    pixel_installed: Optional[bool] = None
    domain_verified: Optional[bool] = None

class FanpageOut(BaseModel):
    id: int
    page_id: str
    fb_account_id: Optional[int] = None
    page_name: str
    page_url: Optional[str] = None
    status: str
    pixel_installed: bool
    domain_verified: bool
    created_at: datetime

    @computed_field
    def fb_account_name(self) -> Optional[str]:
        fb_account = getattr(self, "fb_account", None)
        if not fb_account:
            return None
        return fb_account.username

    model_config = ConfigDict(from_attributes=True)

class AdDailyStatCreate(BaseModel):
    ad_account_id: int
    date: str
    spend: int
    impressions: int
    clicks: int
    conversions: int

class AdDailyStatOut(BaseModel):
    id: int
    ad_account_id: int
    date: date
    spend: int
    impressions: int
    clicks: int
    conversions: int
    cpm: int
    cpc: int
    ctr: float
    cvr: float
    roas: float
    cpp: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class BudgetChangeCreate(BaseModel):
    ad_account_id: int
    old_budget: int
    new_budget: int
    reason: Optional[str] = None

class BudgetChangeOut(BaseModel):
    id: int
    ad_account_id: int
    old_budget: int
    new_budget: int
    reason: Optional[str] = None
    changed_at: datetime

    model_config = ConfigDict(from_attributes=True)

class BudgetEngineConfigIn(BaseModel):
    auto_enabled: Optional[bool] = None
    tiers: Optional[list[float]] = None
    min_stable_days: Optional[int] = None
    min_roas: Optional[float] = None
    min_ctr: Optional[float] = None
    check_time: Optional[str] = None
