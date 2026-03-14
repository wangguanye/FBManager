from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, func

from db.database import Base


class RpaTestResult(Base):
    __tablename__ = "rpa_test_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    action_id = Column(String, nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("fb_accounts.id"), nullable=True, index=True)
    params = Column(Text, nullable=True)
    success = Column(Boolean, nullable=False)
    message = Column(Text, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    error_detail = Column(Text, nullable=True)
    tested_at = Column(DateTime, default=func.now(), nullable=False, index=True)
