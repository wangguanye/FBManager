from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Date, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from db.database import Base

class NurtureTask(Base):
    """养号任务模型"""
    __tablename__ = "nurture_tasks"

    id = Column(Integer, primary_key=True, index=True)
    fb_account_id = Column(Integer, ForeignKey("fb_accounts.id"))
    day_number = Column(Integer)
    scheduled_date = Column(Date)
    scheduled_time = Column(DateTime, nullable=True) # 计划执行时间
    action = Column(String) # 具体动作，如 login, post, like
    task_type = Column(String) # once / daily / manual
    execution_type = Column(String) # auto / manual
    status = Column(String, default="pending")
    retry_count = Column(Integer, default=0)
    result_log = Column(Text, nullable=True)
    executed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系定义
    fb_account = relationship("FBAccount", back_populates="nurture_tasks")
    action_logs = relationship("ActionLog", back_populates="task")

class ActionLog(Base):
    """操作日志模型"""
    __tablename__ = "action_logs"

    id = Column(Integer, primary_key=True, index=True)
    fb_account_id = Column(Integer, ForeignKey("fb_accounts.id"), nullable=True)
    task_id = Column(Integer, ForeignKey("nurture_tasks.id"), nullable=True)
    action_type = Column(String)
    level = Column(String) # INFO / WARN / ERROR / CRITICAL
    message = Column(Text)
    is_dismissed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系定义
    fb_account = relationship("FBAccount", back_populates="action_logs")
    task = relationship("NurtureTask", back_populates="action_logs")
