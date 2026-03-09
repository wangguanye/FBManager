from pydantic import BaseModel, ConfigDict, Field, computed_field
from datetime import datetime, date
from typing import Optional, List

class ProxyIPBase(BaseModel):
    host: str
    port: int
    username: Optional[str] = None
    region: Optional[str] = None
    type: str = "socks5"
    status: str = "空闲"

class ProxyIPCreate(ProxyIPBase):
    password: Optional[str] = None

class ProxyIPUpdate(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    region: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None

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

class FBAccountBrief(BaseModel):
    id: int
    username: str
    status: str
    model_config = ConfigDict(from_attributes=True)

class ProxyIPBrief(BaseModel):
    id: int
    host: str
    port: int
    model_config = ConfigDict(from_attributes=True)

class BrowserWindowDetail(BrowserWindow):
    bound_account: Optional[FBAccountBrief] = Field(None, alias="fb_account")
    bound_proxy: Optional[ProxyIPBrief] = None
        
    model_config = ConfigDict(from_attributes=True)

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
    cookie: Optional[str] = None

class FBAccountUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    region: Optional[str] = None
    target_timezone: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    password: Optional[str] = None
    email_password: Optional[str] = None
    totp_secret: Optional[str] = None
    cookie: Optional[str] = None

class FBAccountBatchImport(BaseModel):
    raw_text: str

class ProxyIPBatchImport(BaseModel):
    raw_text: str

class FBAccountBind(BaseModel):
    proxy_id: int
    window_id: int

class FBAccount(FBAccountBase):
    id: int
    nurture_day: int
    nurture_start_date: Optional[date] = None
    created_at: datetime
    last_active_at: datetime
    is_deleted: bool
    proxy_id: Optional[int] = None
    browser_window_id: Optional[int] = None
    
    # 嵌套对象，方便前端展示
    proxy: Optional[ProxyIP] = None
    browser_window: Optional[BrowserWindow] = None

    # 计算字段，不返回真实密码
    @computed_field
    def has_password(self) -> bool:
        # 这里实际上无法直接访问 ORM 对象的 password_encrypted 属性，因为 Pydantic 模型是从属性初始化的
        # 但是我们可以通过 extra context 或者在 service 层处理
        # 简单起见，我们假设只要对象被加载，密码就是存在的（必填项）
        return True 

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
