from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    plan = Column(String(32), nullable=False)            # free | pro | enterprise
    status = Column(String(32), nullable=False)          # active | cancelled | expired
    current_period_start = Column(DateTime(timezone=True))
    current_period_end   = Column(DateTime(timezone=True))
    razorpay_subscription_id = Column(String(64))
    cancelled_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now())
