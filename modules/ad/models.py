from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean, Date, Float, UniqueConstraint
from sqlalchemy.orm import relationship
from db.database import Base

class BMAccount(Base):
    __tablename__ = "bm_accounts"

    id = Column(Integer, primary_key=True, index=True)
    fb_account_id = Column(Integer, ForeignKey("fb_accounts.id"), nullable=True)
    bm_id = Column(String(50), unique=True, nullable=False)
    name = Column(String(200), nullable=True)
    region = Column(String(50), nullable=True)
    status = Column(String(20), default="active")
    created_at = Column(DateTime, default=datetime.utcnow)
    notes = Column(Text, nullable=True)

    fb_account = relationship("FBAccount", back_populates="bm_account")
    ad_accounts = relationship("AdAccount", back_populates="bm")

class AdAccount(Base):
    __tablename__ = "ad_accounts"

    id = Column(Integer, primary_key=True, index=True)
    bm_id = Column(Integer, ForeignKey("bm_accounts.id"), nullable=True)
    ad_account_id = Column(String(50), unique=True, nullable=False)
    name = Column(String(200), nullable=True)
    spending_limit = Column(String(20), default="$100")
    payment_method = Column(String(100), nullable=True)
    status = Column(String(20), default="active")
    daily_budget = Column(Integer, default=0)
    total_spend = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    notes = Column(Text, nullable=True)

    bm = relationship("BMAccount", back_populates="ad_accounts")
    daily_stats = relationship("AdDailyStat", back_populates="ad_account")
    budget_changes = relationship("BudgetChange", back_populates="ad_account")

class Fanpage(Base):
    __tablename__ = "fanpages"

    id = Column(Integer, primary_key=True, index=True)
    fb_account_id = Column(Integer, ForeignKey("fb_accounts.id"), nullable=True)
    page_id = Column(String(50), unique=True, nullable=False)
    page_name = Column(String(200), nullable=False)
    page_url = Column(String(500), nullable=True)
    status = Column(String(20), default="active")
    pixel_installed = Column(Boolean, default=False)
    domain_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    fb_account = relationship("FBAccount", back_populates="fanpages")

class AdDailyStat(Base):
    __tablename__ = "ad_daily_stats"
    __table_args__ = (
        UniqueConstraint("ad_account_id", "date", name="uq_ad_daily_stats_account_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    ad_account_id = Column(Integer, ForeignKey("ad_accounts.id"), nullable=False)
    date = Column(Date, index=True)
    spend = Column(Integer, default=0)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    conversions = Column(Integer, default=0)
    cpm = Column(Integer, default=0)
    cpc = Column(Integer, default=0)
    ctr = Column(Float, default=0.0)
    cvr = Column(Float, default=0.0)
    roas = Column(Float, default=0.0)
    cpp = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    ad_account = relationship("AdAccount", back_populates="daily_stats")

class BudgetChange(Base):
    __tablename__ = "budget_changes"

    id = Column(Integer, primary_key=True, index=True)
    ad_account_id = Column(Integer, ForeignKey("ad_accounts.id"), nullable=False)
    old_budget = Column(Integer, nullable=False)
    new_budget = Column(Integer, nullable=False)
    reason = Column(Text, nullable=True)
    changed_at = Column(DateTime, default=datetime.utcnow)

    ad_account = relationship("AdAccount", back_populates="budget_changes")
