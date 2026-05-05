from sqlalchemy import Column, Integer, String
from app.core.database import Base


class Topic(Base):
    __tablename__ = "topics"
    id    = Column(Integer, primary_key=True)
    code  = Column(String(8), unique=True, nullable=False, index=True)
    name  = Column(String(120), nullable=False)
    order = Column(Integer, nullable=False)
