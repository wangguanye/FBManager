from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date, ForeignKey, Text
from sqlalchemy.orm import relationship
from db.database import Base

class FBAccount(Base):
    """Facebook 账号模型"""
    __tablename__ = "fb_accounts"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password_encrypted = Column(String)
    email = Column(String, index=True)
    email_password_encrypted = Column(String)
    region = Column(String)
    target_timezone = Column(String, default="America/New_York")
    status = Column(String, default="待养号")
    browser_window_id = Column(Integer, ForeignKey("browser_windows.id"), nullable=True)
    proxy_id = Column(Integer, ForeignKey("proxy_ips.id"), nullable=True)
    nurture_day = Column(Integer, default=0)
    nurture_start_date = Column(Date, nullable=True)
    totp_secret_encrypted = Column(String, nullable=True)
    cookie_encrypted = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active_at = Column(DateTime, default=datetime.utcnow)
    notes = Column(Text, nullable=True)
    is_deleted = Column(Boolean, default=False)

    # 关系定义
    browser_window = relationship("BrowserWindow", back_populates="fb_account")
    proxy = relationship("ProxyIP", back_populates="fb_accounts")
    nurture_tasks = relationship("NurtureTask", back_populates="fb_account")
    action_logs = relationship("ActionLog", back_populates="fb_account")
    avatar_assets = relationship("AvatarAsset", back_populates="used_by_account")

class ProxyIP(Base):
    """代理 IP 模型"""
    __tablename__ = "proxy_ips"

    id = Column(Integer, primary_key=True, index=True)
    host = Column(String)
    port = Column(Integer)
    username = Column(String, nullable=True)
    password_encrypted = Column(String, nullable=True)
    region = Column(String, nullable=True)
    type = Column(String, default="socks5")
    status = Column(String, default="空闲")

    # 关系定义
    fb_accounts = relationship("FBAccount", back_populates="proxy")

class BrowserWindow(Base):
    """浏览器窗口模型"""
    __tablename__ = "browser_windows"

    id = Column(Integer, primary_key=True, index=True)
    bit_window_id = Column(String, unique=True, index=True)
    name = Column(String)
    status = Column(String, default="空闲")

    # 关系定义
    fb_account = relationship("FBAccount", back_populates="browser_window", uselist=False)

class CommentPool(Base):
    """评论池模型"""
    __tablename__ = "comment_pool"

    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text)
    language = Column(String, default="en")
    category = Column(String, nullable=True)
    use_count = Column(Integer, default=0)
    last_used_at = Column(DateTime, nullable=True)

class AvatarAsset(Base):
    """头像/封面资源模型"""
    __tablename__ = "avatar_assets"

    id = Column(Integer, primary_key=True, index=True)
    file_path = Column(String)
    type = Column(String) # avatar / cover
    is_used = Column(Boolean, default=False)
    used_by_account_id = Column(Integer, ForeignKey("fb_accounts.id"), nullable=True)

    # 关系定义
    used_by_account = relationship("FBAccount", back_populates="avatar_assets")
