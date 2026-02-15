"""
Dev Monkey Database - SQLAlchemy модели
"""
from sqlalchemy import create_engine, Column, String, Integer, Boolean, DateTime, ForeignKey, Text, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.sql import func
import uuid

# Функция для генерации UUID
def generate_uuid():
    return str(uuid.uuid4())

# SQLite для простоты (в проде заменить на PostgreSQL)
SQLALCHEMY_DATABASE_URL = "sqlite:///./devmonkey.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    is_active = Column(Boolean, default=True)
    
    accounts = relationship("TelegramAccount", back_populates="user", cascade="all, delete-orphan")

class TelegramAccount(Base):
    __tablename__ = "telegram_accounts"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    phone_number = Column(String, nullable=False)
    api_id = Column(Integer, nullable=False)
    api_hash_encrypted = Column(String, nullable=False)  # В проде шифровать
    session_string_encrypted = Column(String, nullable=True)  # В проде шифровать
    
    # Информация об аккаунте
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    username = Column(String, nullable=True)
    bio = Column(Text, nullable=True)
    
    # Статус
    is_authorized = Column(Boolean, default=False)
    status = Column(String, default="inactive")  # inactive, active, warming
    
    # Метаданные
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    
    user = relationship("User", back_populates="accounts")
    tasks = relationship("Task", back_populates="account", cascade="all, delete-orphan")

class Task(Base):
    __tablename__ = "tasks"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    account_id = Column(String, ForeignKey("telegram_accounts.id", ondelete="CASCADE"), nullable=False)
    task_type = Column(String)  # join_chats, warmup, reactions, edit_profile
    status = Column(String, default="pending")  # pending, running, completed, failed
    
    params = Column(JSON, nullable=True)
    result = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    
    progress = Column(Integer, default=0)
    total = Column(Integer, default=100)
    
    created_at = Column(DateTime, server_default=func.now())
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    celery_task_id = Column(String, nullable=True)
    
    account = relationship("TelegramAccount", back_populates="tasks")

# Создаем таблицы
Base.metadata.create_all(bind=engine)

# Dependency для получения сессии БД
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
