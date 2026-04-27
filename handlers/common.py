import logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from sqlalchemy import select, func
from config import Config
from database import AsyncSessionLocal
from models import User, Project
from .utils import is_admin, check_user_access, TARIFF_LIMITS

logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_new_user = False
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.telegram_id == user.id))
        db_user = result.scalar_one_or_none()
        
        if not db_user:
            is_new_user = True
            db_user = User(
                telegram_id=user.id, username=user.username, full_name=user.full_name,
                is_admin=(user.id == Config.ADMIN_ID),
                max_projects=Config.DEFAULT_MAX_PROJECTS,
                max_sources_per_project=Config.DEFAULT_MAX_SOURCES_PER_PROJECT
            )
            if user.id == Config.ADMIN_ID:
                db_user.is_admin = True
                db_user.tariff = "unlimited"
                db_user.subscription_active = True
                db_user.max_projects = 999
                db_user.max_sources_per_project = 999
                db_user.min_post_interval_minutes = 1
                db_user.min_check_interval_minutes = 5
                db_user.trial_ends_at = datetime.utcnow() + timedelta(days=36500)
            session.add(db_user)
            await session.commit()
        else:
            db_user.username = user.username
            db_user.full_name = user.full_name
            if user.id == Config.ADMIN_ID:
                db_user.is_admin = True
                db_user.tariff = "unlimited"
                db_user.subscription_active = True
                db_user.max_projects = 999
                db_user.max_sources_per_project = 999
            await session.commit()
        
        result = await session.execute(select(func.count()).select_from(Project).where(Project.user_id == user.id))
        has_project = result.scalar() > 0
    
    if is_new_user and user.id != Config.ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=Config.ADMIN_ID,
                text=f"🆕 <b>Новый пользователь!</b>\n👤 {user.full_name or '—'}\n📝 @{user.username or 'нет'}\n🆔 {user.id}",
                parse_mode="HTML"
            )
        except:
            pass
    
    welcome = f"👋 Привет, {user.first_name or 'пользователь'}!\n\nЯ бот для автопостинга из Telegram-каналов в Telegram и VK.\n\n"
    
    if user.id != Config.ADMIN_ID:
        has_access, msg, _ = await check_user_access(user.id)
        if not has_access:
            welcome += f"❌ {msg}\n\n"
    
    if not has_project:
        welcome += "🚀 Создайте проект: /my_projects\n\n"
    
    welcome += "📋 Команды: /my_projects, /add_source, /add_target, /status, /help"
    
    await update.message.reply_text(welcome, parse_mode="HTML")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📚 <b>Команды</b>\n\n"
        "<b>Проекты:</b> /my_projects\n"
        "<b>Источники:</b> /add_source, /my_sources\n"
        "<b>Цели:</b> /add_target, /my_targets\n"
        "<b>Настройки:</b> /set_interval, /set_post_interval, /set_signature\n"
        "<b>Управление:</b> /status, /parse, /queue, /postnow, /reset_history\n"
    )
    if await is_admin(update.effective_user.id):
        text += "\n<b>Админ:</b> /admin"
    else:
        text += "\n<b>Тарифы:</b> Базовый 290₽, Стандарт 590₽, PRO 990₽"
    
    admin_username = Config.ADMIN_USERNAME or "admin"
    text += f"\n\n📲 <a href='https://t.me/{admin_username}'>Написать админу</a>"
    
    await update.message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Отменено")
    return ConversationHandler.END