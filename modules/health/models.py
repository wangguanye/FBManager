from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from db.database import Base

class HealthScore(Base):
    __tablename__ = "health_scores"

    id = Column(Integer, primary_key=True, index=True)
    fb_account_id = Column(Integer, ForeignKey("fb_accounts.id"), nullable=False, unique=True)
    score = Column(Integer, nullable=False, default=0)
    grade = Column(String(1), nullable=False, default="F")
    detail_json = Column(Text, nullable=True)
    calculated_at = Column(DateTime, default=datetime.utcnow)
