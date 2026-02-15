"""
Dev Monkey Tasks - Celery worker
Запуск: celery -A tasks worker --loglevel=info
"""
from celery import Celery
import asyncio
import random
from datetime import datetime, timedelta
import logging
from pyrogram import Client
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Celery приложение
celery_app = Celery(
    'devmonkey',
    broker='redis://localhost:6379/0',
    backend='redis://localhost:6379/0',
    include=['tasks']
)

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 минут
    task_soft_time_limit=25 * 60,  # 25 минут
)

# База данных
engine = create_engine("sqlite:///./devmonkey.db", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Шаблоны сообщений для прогрева
MESSAGE_TEMPLATES = [
    "Привет всем! Как дела?",
    "Интересный чат, давно искал что-то подобное",
    "Спасибо за полезную информацию!",
    "Приятно познакомиться с единомышленниками",
    "Актуальная тема, спасибо за обсуждение",
    "Давно наблюдаю, очень познавательно",
    "Кто-нибудь участвовал в подобных проектах?",
    "Интересная точка зрения",
    "Полезный пост, сохранил себе",
    "Согласен с предыдущим оратором",
]

async def get_client(account):
    """Получение клиента для аккаунта"""
    return Client(
        name=f"account_{account.id}",
        api_id=account.api_id,
        api_hash=account.api_hash_encrypted,  # В проде расшифровывать
        session_string=account.session_string_encrypted,  # В проде расшифровывать
        in_memory=True
    )

@celery_app.task(bind=True, name='process_join_chats')
def process_join_chats(self, task_id):
    """Задача для вступления в чаты"""
    db = SessionLocal()
    try:
        from database import Task, TelegramAccount
        
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            logger.error(f"Task {task_id} not found")
            return
        
        account = task.account
        chat_links = task.params.get('chat_links', [])
        
        task.status = "running"
        task.started_at = datetime.utcnow()
        db.commit()
        
        async def join_chats_async():
            client = await get_client(account)
            await client.connect()
            
            total = len(chat_links)
            for i, link in enumerate(chat_links):
                try:
                    # Очищаем ссылку
                    link = link.strip()
                    if 't.me/' in link:
                        link = link.split('t.me/')[-1]
                    if link.startswith('@'):
                        link = link[1:]
                    
                    await client.join_chat(link)
                    logger.info(f"Joined {link}")
                    
                    # Обновляем прогресс
                    task.progress = int((i + 1) / total * 100)
                    db.commit()
                    
                    # Задержка между вступлениями
                    delay = random.randint(60, 300)
                    await asyncio.sleep(delay)
                    
                except Exception as e:
                    logger.error(f"Error joining {link}: {e}")
                    task.error = str(e)
                    db.commit()
            
            await client.disconnect()
            task.status = "completed"
            task.completed_at = datetime.utcnow()
            task.progress = 100
            db.commit()
        
        # Запускаем асинхронную функцию
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(join_chats_async())
        loop.close()
        
    except Exception as e:
        logger.error(f"Task failed: {e}")
        task.status = "failed"
        task.error = str(e)
        db.commit()
        raise self.retry(exc=e, countdown=60)
    finally:
        db.close()

@celery_app.task(bind=True, name='process_warmup')
def process_warmup(self, task_id):
    """Задача для прогрева аккаунта"""
    db = SessionLocal()
    try:
        from database import Task, TelegramAccount
        
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return
        
        account = task.account
        duration_minutes = task.params.get('duration_minutes', 60)
        
        task.status = "running"
        task.started_at = datetime.utcnow()
        db.commit()
        
        async def warmup_async():
            client = await get_client(account)
            await client.connect()
            
            end_time = datetime.utcnow() + timedelta(minutes=duration_minutes)
            
            # Популярные чаты для поиска
            search_queries = ['news', 'tech', 'chat', 'games', 'music', 'movies']
            
            while datetime.utcnow() < end_time and task.status == "running":
                try:
                    # Ищем чаты
                    query = random.choice(search_queries)
                    async for chat in client.search_global(query, limit=5):
                        # Вступаем в чат если есть username
                        if chat.username:
                            try:
                                await client.join_chat(chat.username)
                                logger.info(f"Joined {chat.username}")
                                
                                # Задержка
                                await asyncio.sleep(random.randint(300, 600))
                                
                                # Иногда отправляем сообщение
                                if random.random() < 0.3:  # 30% шанс
                                    message = random.choice(MESSAGE_TEMPLATES)
                                    await client.send_message(chat.id, message)
                                    logger.info(f"Sent message to {chat.username}")
                                
                                # Длительная задержка
                                await asyncio.sleep(random.randint(600, 1200))
                                
                            except Exception as e:
                                logger.error(f"Error with chat {chat.username}: {e}")
                    
                    # Обновляем прогресс
                    elapsed = (datetime.utcnow() - task.started_at).total_seconds() / 60
                    task.progress = min(int(elapsed / duration_minutes * 100), 99)
                    db.commit()
                    
                except Exception as e:
                    logger.error(f"Warmup error: {e}")
                    await asyncio.sleep(60)
            
            await client.disconnect()
            task.status = "completed"
            task.completed_at = datetime.utcnow()
            task.progress = 100
            db.commit()
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(warmup_async())
        loop.close()
        
    except Exception as e:
        logger.error(f"Warmup failed: {e}")
        task.status = "failed"
        task.error = str(e)
        db.commit()
    finally:
        db.close()

@celery_app.task(bind=True, name='process_reactions')
def process_reactions(self, task_id):
    """Задача для массовых реакций"""
    db = SessionLocal()
    try:
        from database import Task, TelegramAccount
        
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return
        
        account = task.account
        params = task.params
        chat_ids = params.get('chat_ids', [])
        reactions = params.get('reactions', ['👍'])
        delay = params.get('delay_seconds', 10)
        
        task.status = "running"
        task.started_at = datetime.utcnow()
        db.commit()
        
        async def reactions_async():
            client = await get_client(account)
            await client.connect()
            
            total = len(chat_ids)
            for i, chat_id in enumerate(chat_ids):
                try:
                    # Получаем сообщения из чата
                    async for message in client.get_chat_history(chat_id, limit=50):
                        # Не реагируем на свои сообщения
                        if message.from_user and message.from_user.is_self:
                            continue
                        
                        # Ставим случайную реакцию
                        reaction = random.choice(reactions)
                        await client.send_reaction(chat_id, message.id, reaction)
                        logger.info(f"Reacted {reaction} to message {message.id}")
                        
                        # Задержка
                        await asyncio.sleep(delay)
                    
                    # Обновляем прогресс
                    task.progress = int((i + 1) / total * 100)
                    db.commit()
                    
                except Exception as e:
                    logger.error(f"Error in chat {chat_id}: {e}")
            
            await client.disconnect()
            task.status = "completed"
            task.completed_at = datetime.utcnow()
            task.progress = 100
            db.commit()
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(reactions_async())
        loop.close()
        
    except Exception as e:
        logger.error(f"Reactions failed: {e}")
        task.status = "failed"
        task.error = str(e)
        db.commit()
    finally:
        db.close()

@celery_app.task(bind=True, name='process_profile_update')
def process_profile_update(self, task_id):
    """Задача для обновления профиля"""
    db = SessionLocal()
    try:
        from database import Task, TelegramAccount
        
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return
        
        account = task.account
        params = task.params
        
        task.status = "running"
        task.started_at = datetime.utcnow()
        db.commit()
        
        async def update_profile_async():
            client = await get_client(account)
            await client.connect()
            
            try:
                # Обновляем имя
                if params.get('first_name') or params.get('last_name'):
                    await client.update_profile(
                        first_name=params.get('first_name'),
                        last_name=params.get('last_name')
                    )
                    logger.info("Profile name updated")
                
                # Обновляем био
                if params.get('bio'):
                    await client.update_profile(bio=params.get('bio'))
                    logger.info("Bio updated")
                
                # Обновляем username
                if params.get('username'):
                    await client.set_username(params.get('username'))
                    logger.info("Username updated")
                
                task.status = "completed"
                task.result = {"success": True}
                
            except Exception as e:
                logger.error(f"Profile update error: {e}")
                task.status = "failed"
                task.error = str(e)
            
            await client.disconnect()
            task.completed_at = datetime.utcnow()
            db.commit()
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(update_profile_async())
        loop.close()
        
    except Exception as e:
        logger.error(f"Profile update failed: {e}")
        task.status = "failed"
        task.error = str(e)
        db.commit()
    finally:
        db.close()
