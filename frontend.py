"""
Dev Monkey Frontend - Streamlit приложение
Запуск: streamlit run frontend.py
"""
import streamlit as st
import requests
import json
from datetime import datetime
import time
import websocket
import threading

# Конфигурация
API_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000"

# Настройка страницы
st.set_page_config(
    page_title="Dev Monkey",
    page_icon="🐒",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Стили
st.markdown("""
<style>
    .stButton > button {
        width: 100%;
        height: 100px;
        font-size: 20px;
        font-weight: bold;
        border-radius: 10px;
        margin: 5px;
    }
    .account-card {
        background-color: #f0f2f6;
        padding: 20px;
        border-radius: 10px;
        margin: 10px 0;
    }
    .success-msg {
        color: #0f5132;
        background-color: #d1e7dd;
        padding: 10px;
        border-radius: 5px;
        margin: 10px 0;
    }
    .error-msg {
        color: #842029;
        background-color: #f8d7da;
        padding: 10px;
        border-radius: 5px;
        margin: 10px 0;
    }
</style>
""", unsafe_allow_html=True)

# Инициализация session state
if 'token' not in st.session_state:
    st.session_state.token = None
if 'page' not in st.session_state:
    st.session_state.page = 'auth'
if 'temp_session' not in st.session_state:
    st.session_state.temp_session = None
if 'websocket' not in st.session_state:
    st.session_state.websocket = None

# Функции для работы с API
def api_request(method, endpoint, data=None, token=None):
    headers = {}
    if token or st.session_state.token:
        headers['Authorization'] = f"Bearer {token or st.session_state.token}"
    
    try:
        if method == 'GET':
            response = requests.get(f"{API_URL}{endpoint}", headers=headers)
        elif method == 'POST':
            response = requests.post(f"{API_URL}{endpoint}", json=data, headers=headers)
        
        if response.status_code == 200:
            return response.json()
        else:
            st.error(f"Error: {response.text}")
            return None
    except Exception as e:
        st.error(f"Connection error: {e}")
        return None

# Страница авторизации
def auth_page():
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.title("🐒 Dev Monkey")
        st.markdown("---")
        
        tab1, tab2 = st.tabs(["Вход", "Регистрация"])
        
        with tab1:
            with st.form("login_form"):
                username = st.text_input("Логин")
                password = st.text_input("Пароль", type="password")
                
                if st.form_submit_button("Войти", use_container_width=True):
                    result = api_request('POST', '/api/auth/login', {
                        'username': username,
                        'password': password
                    })
                    if result:
                        st.session_state.token = result['access_token']
                        st.session_state.page = 'dashboard'
                        st.rerun()
        
        with tab2:
            with st.form("register_form"):
                username = st.text_input("Логин")
                password = st.text_input("Пароль", type="password")
                password2 = st.text_input("Подтвердите пароль", type="password")
                
                if st.form_submit_button("Зарегистрироваться", use_container_width=True):
                    if password != password2:
                        st.error("Пароли не совпадают")
                    else:
                        result = api_request('POST', '/api/auth/register', {
                            'username': username,
                            'password': password
                        })
                        if result:
                            st.session_state.token = result['access_token']
                            st.session_state.page = 'dashboard'
                            st.rerun()

# Дашборд
def dashboard_page():
    st.sidebar.title("🐒 Dev Monkey")
    st.sidebar.markdown("---")
    
    # Навигация
    pages = {
        "📊 Дашборд": "dashboard",
        "📱 Аккаунты": "accounts",
        "⚙️ Настройки": "settings",
        "🔥 Прогрев": "warmup",
        "❤️ Реакции": "reactions"
    }
    
    for page_name, page_key in pages.items():
        if st.sidebar.button(page_name, use_container_width=True):
            st.session_state.page = page_key
            st.rerun()
    
    st.sidebar.markdown("---")
    if st.sidebar.button("🚪 Выйти", use_container_width=True):
        st.session_state.token = None
        st.session_state.page = 'auth'
        st.rerun()
    
    # Основной контент
    if st.session_state.page == 'dashboard':
        st.title("Главное меню")
        
        col1, col2 = st.columns(2)
        col3, col4 = st.columns(2)
        
        with col1:
            if st.button("📱 Менеджер аккаунтов\n\nУправление Telegram аккаунтами"):
                st.session_state.page = 'accounts'
                st.rerun()
        
        with col2:
            if st.button("❤️ Масс реакции\n\nАвтоматические реакции"):
                st.session_state.page = 'reactions'
                st.rerun()
        
        with col3:
            if st.button("⚙️ Настройка аккаунтов\n\nРедактирование профилей"):
                st.session_state.page = 'settings'
                st.rerun()
        
        with col4:
            if st.button("🔥 Прогрев аккаунтов\n\nИмитация активности"):
                st.session_state.page = 'warmup'
                st.rerun()
        
        # Последние задачи
        st.markdown("---")
        st.subheader("Последние задачи")
        
        tasks = api_request('GET', '/api/tasks')
        if tasks:
            for task in tasks[:5]:
                status_color = {
                    'pending': '🟡',
                    'running': '🟢',
                    'completed': '✅',
                    'failed': '❌'
                }.get(task['status'], '⚪')
                
                st.text(f"{status_color} {task['type']} - {task['progress']}%")

# Страница управления аккаунтами
def accounts_page():
    st.title("📱 Менеджер аккаунтов")
    
    # Получаем список аккаунтов
    accounts = api_request('GET', '/api/accounts')
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        if accounts:
            for acc in accounts:
                with st.container():
                    st.markdown(f"""
                    <div class="account-card">
                        <h4>{acc['phone']}</h4>
                        <p>Статус: {'✅ Активен' if acc['is_authorized'] else '❌ Не активен'}</p>
                        <p>Имя: {acc.get('first_name', 'Не указано')}</p>
                        <p>Username: @{acc.get('username', 'Не указан')}</p>
                    </div>
                    """, unsafe_allow_html=True)
        else:
            st.info("У вас пока нет добавленных аккаунтов")
    
    with col2:
        st.subheader("Добавить аккаунт")
        
        if not accounts or len(accounts) < 3:
            with st.form("add_account"):
                api_id = st.number_input("API ID", min_value=1, value=12345)
                api_hash = st.text_input("API Hash")
                phone = st.text_input("Номер телефона", placeholder="+79001234567")
                
                if st.form_submit_button("Начать добавление"):
                    result = api_request('POST', '/api/telegram/start-auth', {
                        'api_id': api_id,
                        'api_hash': api_hash,
                        'phone': phone
                    })
                    if result:
                        st.session_state.temp_session = result['session_id']
                        st.session_state.auth_step = 'code'
                        st.rerun()
            
            # Шаги авторизации
            if 'auth_step' in st.session_state:
                if st.session_state.auth_step == 'code':
                    code = st.text_input("Введите код из Telegram")
                    if st.button("Подтвердить код"):
                        result = api_request('POST', '/api/telegram/verify-code', {
                            'session_id': st.session_state.temp_session,
                            'code': code
                        })
                        if result:
                            if result.get('need_2fa'):
                                st.session_state.auth_step = '2fa'
                            else:
                                st.success("Аккаунт успешно добавлен!")
                                del st.session_state.temp_session
                                del st.session_state.auth_step
                                st.rerun()
                
                elif st.session_state.auth_step == '2fa':
                    password = st.text_input("Введите пароль 2FA", type="password")
                    if st.button("Подтвердить"):
                        result = api_request('POST', '/api/telegram/verify-2fa', {
                            'session_id': st.session_state.temp_session,
                            'password': password
                        })
                        if result:
                            st.success("Аккаунт успешно добавлен!")
                            del st.session_state.temp_session
                            del st.session_state.auth_step
                            st.rerun()
        else:
            st.warning("Достигнут лимит аккаунтов (максимум 3)")

# Страница настроек
def settings_page():
    st.title("⚙️ Настройка аккаунтов")
    
    accounts = api_request('GET', '/api/accounts')
    if not accounts:
        st.warning("Сначала добавьте аккаунт")
        return
    
    # Выбор аккаунта
    account_options = {acc['phone']: acc['id'] for acc in accounts}
    selected_account = st.selectbox("Выберите аккаунт", list(account_options.keys()))
    account_id = account_options[selected_account]
    
    tab1, tab2 = st.tabs(["Вступление в чаты", "Редактирование профиля"])
    
    with tab1:
        st.subheader("Вступление в чаты")
        chat_links = st.text_area(
            "Ссылки на чаты (по одной на строку)",
            placeholder="https://t.me/chat1\nhttps://t.me/chat2\n@chat3"
        )
        
        if st.button("Добавить чаты на аккаунт"):
            links = [link.strip() for link in chat_links.split('\n') if link.strip()]
            result = api_request('POST', '/api/accounts/join-chats', {
                'account_id': account_id,
                'chat_links': links
            })
            if result:
                st.success(f"Задача запущена! ID: {result['task_id']}")
    
    with tab2:
        st.subheader("Редактирование профиля")
        
        col1, col2 = st.columns(2)
        with col1:
            first_name = st.text_input("Имя")
            last_name = st.text_input("Фамилия")
        
        with col2:
            username = st.text_input("Username (без @)")
            bio = st.text_area("Bio", height=100)
        
        if st.button("Сохранить изменения профиля"):
            update_data = {'account_id': account_id}
            if first_name:
                update_data['first_name'] = first_name
            if last_name:
                update_data['last_name'] = last_name
            if username:
                update_data['username'] = username
            if bio:
                update_data['bio'] = bio
            
            result = api_request('POST', '/api/accounts/update-profile', update_data)
            if result:
                st.success(f"Задача запущена! ID: {result['task_id']}")

# Страница прогрева
def warmup_page():
    st.title("🔥 Прогрев аккаунтов")
    
    accounts = api_request('GET', '/api/accounts')
    if not accounts:
        st.warning("Сначала добавьте аккаунт")
        return
    
    account_options = {acc['phone']: acc['id'] for acc in accounts}
    selected_account = st.selectbox("Выберите аккаунт", list(account_options.keys()))
    account_id = account_options[selected_account]
    
    # Слайдер для выбора времени
    duration = st.slider(
        "Длительность прогрева",
        min_value=10,
        max_value=7200,  # 5 дней в минутах
        value=60,
        step=10,
        format="%d минут"
    )
    
    if st.button("🚀 Запустить прогрев", use_container_width=True):
        result = api_request('POST', '/api/accounts/warmup', {
            'account_id': account_id,
            'duration_minutes': duration
        })
        if result:
            st.success(f"Прогрев запущен! ID задачи: {result['task_id']}")

# Страница реакций
def reactions_page():
    st.title("❤️ Масс реакции")
    
    accounts = api_request('GET', '/api/accounts')
    if not accounts:
        st.warning("Сначала добавьте аккаунт")
        return
    
    account_options = {acc['phone']: acc['id'] for acc in accounts}
    selected_account = st.selectbox("Выберите аккаунт", list(account_options.keys()))
    account_id = account_options[selected_account]
    
    # Здесь нужно получать реальные чаты аккаунта
    st.info("В реальном приложении здесь будет список ваших чатов")
    
    # Настройки реакций
    col1, col2 = st.columns(2)
    
    with col1:
        delay = st.number_input("Задержка (секунд)", min_value=1, max_value=10000, value=10)
        
        reaction_type = st.radio(
            "Тип реакций",
            ["Новые сообщения", "Все сообщения"],
            index=0
        )
    
    with col2:
        reactions = st.multiselect(
            "Выберите реакции",
            ["👍", "❤️", "🔥", "🥰", "😁", "😱", "🤬", "🍓"],
            default=["👍", "❤️"]
        )
    
    if st.button("Запустить масс-реакции", use_container_width=True):
        result = api_request('POST', '/api/accounts/reactions', {
            'account_id': account_id,
            'chat_ids': [],  # В реальном приложении сюда придут выбранные чаты
            'reactions': reactions,
            'delay_seconds': delay,
            'reaction_type': 'new' if reaction_type == "Новые сообщения" else 'all'
        })
        if result:
            st.success(f"Реакции запущены! ID задачи: {result['task_id']}")

# Главная логика
if st.session_state.token is None:
    auth_page()
else:
    dashboard_page()
