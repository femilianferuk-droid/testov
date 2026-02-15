"""
Dev Monkey Backend - FastAPI сервер
Запуск: uvicorn backend:app --reload --port 8000
"""
from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import jwt
import bcrypt
from datetime import datetime, timedelta
import asyncio
import random
import os
from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded, PhoneCodeInvalid, FloodWait
from database import SessionLocal, User, TelegramAccount, Task, get_db
from tasks import celery_app
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация
SECRET_KEY = "your-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 дней

app = FastAPI(title="Dev Monkey API")
security = HTTPBearer()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501"],  # Streamlit
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic модели
class UserCreate(BaseModel):
    username: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str

class TelegramAuthStart(BaseModel):
    api_id: int
    api_hash: str
    phone: str

class TelegramAuthVerify(BaseModel):
    session_id: str
    code: str

class TelegramAuth2FA(BaseModel):
    session_id: str
    password: str

class ChatJoinRequest(BaseModel):
    account_id: str
    chat_links: List[str]

class WarmupRequest(BaseModel):
    account_id: str
    duration_minutes: int

class ReactionRequest(BaseModel):
    account_id: str
    chat_ids: List[int]
    reactions: List[str]
    delay_seconds: int
    reaction_type: str

class ProfileUpdate(BaseModel):
    account_id: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    bio: Optional[str] = None
    username: Optional[str] = None

# WebSocket менеджер
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]

    async def send_message(self, message: dict, client_id: str):
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_json(message)

manager = ConnectionManager()

# Временное хранилище для сессий Telegram
temp_sessions = {}

# Аутентификация
def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.PyJWTError:
        raise HTTPException(status_code=403, detail="Invalid token")

# API Routes
@app.post("/api/auth/register", response_model=TokenResponse)
async def register(user: UserCreate):
    db = SessionLocal()
    try:
        # Проверяем существующего пользователя
        if db.query(User).filter(User.username == user.username).first():
            raise HTTPException(status_code=400, detail="Username already exists")
        
        # Создаем пользователя
        db_user = User(
            username=user.username,
            password_hash=bcrypt.hashpw(user.password.encode(), bcrypt.gensalt()).decode()
        )
        db.add(db_user)
        db.commit()
        
        # Создаем токен
        access_token = create_access_token({"sub": str(db_user.id)})
        return {"access_token": access_token, "token_type": "bearer"}
    finally:
        db.close()

@app.post("/api/auth/login", response_model=TokenResponse)
async def login(user: UserLogin):
    db = SessionLocal()
    try:
        db_user = db.query(User).filter(User.username == user.username).first()
        if not db_user or not bcrypt.checkpw(user.password.encode(), db_user.password_hash.encode()):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        access_token = create_access_token({"sub": str(db_user.id)})
        return {"access_token": access_token, "token_type": "bearer"}
    finally:
        db.close()

@app.post("/api/telegram/start-auth")
async def start_telegram_auth(auth_data: TelegramAuthStart, payload: dict = Depends(verify_token)):
    """Шаг 1: Отправка кода подтверждения"""
    session_id = f"{payload['sub']}_{datetime.utcnow().timestamp()}"
    
    try:
        client = Client(
            name=f"temp_{session_id}",
            api_id=auth_data.api_id,
            api_hash=auth_data.api_hash,
            in_memory=True
        )
        await client.connect()
        sent_code = await client.send_code(auth_data.phone)
        
        temp_sessions[session_id] = {
            'client': client,
            'phone': auth_data.phone,
            'phone_code_hash': sent_code.phone_code_hash,
            'api_id': auth_data.api_id,
            'api_hash': auth_data.api_hash,
            'created_at': datetime.utcnow()
        }
        
        return {"session_id": session_id, "timeout": sent_code.timeout}
    except FloodWait as e:
        raise HTTPException(status_code=429, detail=f"Flood wait for {e.value} seconds")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/telegram/verify-code")
async def verify_telegram_code(verify_data: TelegramAuthVerify):
    """Шаг 2: Проверка кода"""
    session = temp_sessions.get(verify_data.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    try:
        client = session['client']
        user = await client.sign_in(
            phone_number=session['phone'],
            phone_code_hash=session['phone_code_hash'],
            phone_code=verify_data.code
        )
        
        session_string = await client.export_session_string()
        
        return {
            "success": True,
            "session_string": session_string,
            "user": {
                "id": user.id,
                "username": user.username,
                "first_name": user.first_name
            }
        }
    except SessionPasswordNeeded:
        return {"need_2fa": True}
    except PhoneCodeInvalid:
        raise HTTPException(status_code=400, detail="Invalid code")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/telegram/verify-2fa")
async def verify_telegram_2fa(verify_data: TelegramAuth2FA, payload: dict = Depends(verify_token)):
    """Шаг 3: Проверка 2FA"""
    session = temp_sessions.get(verify_data.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    try:
        client = session['client']
        user = await client.check_password(verify_data.password)
        session_string = await client.export_session_string()
        
        # Сохраняем аккаунт в БД
        db = SessionLocal()
        try:
            account = TelegramAccount(
                user_id=payload['sub'],
                phone_number=session['phone'],
                api_id=session['api_id'],
                api_hash_encrypted=session['api_hash'],  # В проде шифровать!
                session_string_encrypted=session_string,
                is_authorized=True
            )
            db.add(account)
            db.commit()
            
            return {"success": True, "account_id": str(account.id)}
        finally:
            db.close()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/accounts")
async def get_accounts(payload: dict = Depends(verify_token)):
    """Получение списка аккаунтов"""
    db = SessionLocal()
    try:
        accounts = db.query(TelegramAccount).filter(
            TelegramAccount.user_id == payload['sub']
        ).all()
        
        return [{
            "id": str(acc.id),
            "phone": acc.phone_number,
            "first_name": acc.first_name,
            "username": acc.username,
            "is_authorized": acc.is_authorized,
            "status": acc.status,
            "created_at": acc.created_at.isoformat() if acc.created_at else None
        } for acc in accounts]
    finally:
        db.close()

@app.post("/api/accounts/join-chats")
async def join_chats(request: ChatJoinRequest, payload: dict = Depends(verify_token)):
    """Запуск вступления в чаты"""
    db = SessionLocal()
    try:
        account = db.query(TelegramAccount).filter(
            TelegramAccount.id == request.account_id,
            TelegramAccount.user_id == payload['sub']
        ).first()
        
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        
        # Создаем задачу
        task = Task(
            account_id=account.id,
            task_type="join_chats",
            params={"chat_links": request.chat_links}
        )
        db.add(task)
        db.commit()
        
        # Запускаем Celery задачу
        celery_app.send_task('process_join_chats', args=[str(task.id)])
        
        return {"task_id": str(task.id), "status": "started"}
    finally:
        db.close()

@app.post("/api/accounts/warmup")
async def start_warmup(request: WarmupRequest, payload: dict = Depends(verify_token)):
    """Запуск прогрева аккаунта"""
    db = SessionLocal()
    try:
        account = db.query(TelegramAccount).filter(
            TelegramAccount.id == request.account_id,
            TelegramAccount.user_id == payload['sub']
        ).first()
        
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        
        task = Task(
            account_id=account.id,
            task_type="warmup",
            params={"duration_minutes": request.duration_minutes}
        )
        db.add(task)
        db.commit()
        
        celery_app.send_task('process_warmup', args=[str(task.id)])
        
        return {"task_id": str(task.id), "status": "started"}
    finally:
        db.close()

@app.post("/api/accounts/reactions")
async def start_reactions(request: ReactionRequest, payload: dict = Depends(verify_token)):
    """Запуск массовых реакций"""
    db = SessionLocal()
    try:
        account = db.query(TelegramAccount).filter(
            TelegramAccount.id == request.account_id,
            TelegramAccount.user_id == payload['sub']
        ).first()
        
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        
        task = Task(
            account_id=account.id,
            task_type="reactions",
            params=request.dict()
        )
        db.add(task)
        db.commit()
        
        celery_app.send_task('process_reactions', args=[str(task.id)])
        
        return {"task_id": str(task.id), "status": "started"}
    finally:
        db.close()

@app.post("/api/accounts/update-profile")
async def update_profile(request: ProfileUpdate, payload: dict = Depends(verify_token)):
    """Обновление профиля"""
    db = SessionLocal()
    try:
        account = db.query(TelegramAccount).filter(
            TelegramAccount.id == request.account_id,
            TelegramAccount.user_id == payload['sub']
        ).first()
        
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        
        task = Task(
            account_id=account.id,
            task_type="edit_profile",
            params=request.dict(exclude_unset=True)
        )
        db.add(task)
        db.commit()
        
        celery_app.send_task('process_profile_update', args=[str(task.id)])
        
        return {"task_id": str(task.id), "status": "started"}
    finally:
        db.close()

@app.get("/api/tasks")
async def get_tasks(payload: dict = Depends(verify_token)):
    """Получение списка задач"""
    db = SessionLocal()
    try:
        tasks = db.query(Task).join(TelegramAccount).filter(
            TelegramAccount.user_id == payload['sub']
        ).order_by(Task.created_at.desc()).limit(50).all()
        
        return [{
            "id": str(t.id),
            "type": t.task_type,
            "status": t.status,
            "progress": t.progress,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None
        } for t in tasks]
    finally:
        db.close()

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await manager.connect(websocket, client_id)
    try:
        while True:
            data = await websocket.receive_text()
            # Обработка сообщений
            await manager.send_message({"status": "connected"}, client_id)
    except WebSocketDisconnect:
        manager.disconnect(client_id)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
