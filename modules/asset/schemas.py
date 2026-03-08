from pydantic import BaseModel, ConfigDict
from datetime import datetime, date
from typing import Optional, List

class FBAccountBase(BaseModel):
    username: str
    email: str
    region: str
    target_timezone: str = "America/New_York"
    status: str = "待养号"
    notes: Optional[str] = None

class FBAccountCreate(FBAccountBase):
    password: str
    email_password: str
    totp_secret: Optional[str] = None

class FBAccount(FBAccountBase):
    id: int
    nurture_day: int
    nurture_start_date: Optional[date] = None
    created_at: datetime
    last_active_at: datetime
    is_deleted: bool
    model_config = ConfigDict(from_attributes=True)

class ProxyIPBase(BaseModel):
    host: str
    port: int
    username: Optional[str] = None
    region: Optional[str] = None
    type: str = "socks5"
    status: str = "空闲"

class ProxyIPCreate(ProxyIPBase):
    password: Optional[str] = None

class ProxyIP(ProxyIPBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

class BrowserWindowBase(BaseModel):
    bit_window_id: str
    name: str
    status: str = "空闲"

class BrowserWindowCreate(BrowserWindowBase):
    pass

class BrowserWindow(BrowserWindowBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

class CommentPoolBase(BaseModel):
    content: str
    language: str = "en"
    category: Optional[str] = None

class CommentPoolCreate(CommentPoolBase):
    pass

class CommentPool(CommentPoolBase):
    id: int
    use_count: int
    last_used_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class AvatarAssetBase(BaseModel):
    file_path: str
    type: str

class AvatarAsset(AvatarAssetBase):
    id: int
    is_used: bool
    used_by_account_id: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)
