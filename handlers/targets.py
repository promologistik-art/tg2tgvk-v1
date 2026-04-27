import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from sqlalchemy import delete
from database import AsyncSessionLocal
from models import TargetChannel
from .utils import require_project, get_sources_count, get_project_target, send_project_ready_message
from .constants import AWAITING_TARGET_PLATFORM, AWAITING_TARGET_FORWARD, AWAITING_VK_TOKEN, AWAITING_VK_GROUP

logger = logging.getLogger(__name__)


async def add_target_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 0: Выбор платформы."""
    project = await require_project(update, context)
    if not project:
        return ConversationHandler.END
    
    target = await get_project_target(project.id)
    if target:
        await update.message.reply_text(f"⚠️ В проекте уже есть цель: {target.channel_title or target.vk_group_name}\nУдалите через /my_targets")
        return ConversationHandler.END
    
    context.user_data['temp_project_id'] = project.id
    context.user_data['temp_project_name'] = project.name
    
    keyboard = [
        [InlineKeyboardButton("🟢 Telegram", callback_data="platform_telegram")],
        [InlineKeyboardButton("🔵 VK", callback_data="platform_vk")],
    ]
    
    await update.message.reply_text(
        f"📤 <b>Добавление цели в «{project.name}»</b>\n\nВыберите платформу:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return AWAITING_TARGET_PLATFORM


async def add_target_platform(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора платформы."""
    query = update.callback_query
    await query.answer()
    
    platform = query.data.replace("platform_", "")
    context.user_data['temp_platform'] = platform
    
    if platform == "telegram":
        me = await context.bot.get_me()
        await query.edit_message_text(
            f"🎯 <b>Добавление Telegram-канала</b>\n\n"
            f"1. Добавьте @{me.username} в админы канала\n"
            f"2. Выдайте права на публикацию\n"
            f"3. Перешлите сюда любое сообщение из канала",
            parse_mode="HTML"
        )
        return AWAITING_TARGET_FORWARD
    
    elif platform == "vk":
        await query.edit_message_text(
            f"🔵 <b>Добавление VK-паблика</b>\n\n"
            f"<b>Шаг 1 из 2:</b> Отправьте токен доступа VK.\n\n"
            f"<b>Как получить токен:</b>\n"
            f"1. Перейдите на <a href='https://vkhost.github.io'>vkhost.github.io</a>\n"
            f"2. Выберите «VK Admin»\n"
            f"3. Разрешите доступ\n"
            f"4. Скопируйте токен из адресной строки (после access_token=)\n"
            f"5. Отправьте его сюда\n\n"
            f"<i>Токен будет сохранён только для этого проекта.</i>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return AWAITING_VK_TOKEN


async def add_target_vk_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение токена VK."""
    token = update.message.text.strip()
    
    if len(token) < 50:
        await update.message.reply_text("❌ Токен слишком короткий. Отправьте полный токен доступа VK.")
        return AWAITING_VK_TOKEN
    
    context.user_data['temp_vk_token'] = token
    
    await update.message.reply_text(
        f"🔵 <b>Шаг 2 из 2:</b> Отправьте ID группы VK.\n\n"
        f"<b>Где найти ID:</b>\n"
        f"• Откройте группу VK\n"
        f"• В адресной строке: vk.com/public123456 → ID = 123456\n"
        f"• Или vk.com/club123456 → ID = 123456\n"
        f"• Или vk.com/короткое_имя → откройте vk.com/foaf.php?acting=короткое_имя\n\n"
        f"<i>Отправьте ID (только цифры).</i>",
        parse_mode="HTML"
    )
    return AWAITING_VK_GROUP


async def add_target_vk_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение VK-цели."""
    group_id_str = update.message.text.strip()
    
    try:
        group_id = int(group_id_str.replace("-", "").replace("public", "").replace("club", ""))
    except:
        await update.message.reply_text("❌ ID должен быть числом. Попробуйте ещё раз.")
        return AWAITING_VK_GROUP
    
    project_id = context.user_data.get('temp_project_id')
    project_name = context.user_data.get('temp_project_name')
    vk_token = context.user_data.get('temp_vk_token')
    
    async with AsyncSessionLocal() as session:
        channel = TargetChannel(
            project_id=project_id,
            platform="vk",
            vk_token=vk_token,
            vk_group_id=group_id,
            vk_group_name=f"VK Group {group_id}"
        )
        session.add(channel)
        await session.commit()
    
    await update.message.reply_text(
        f"✅ VK-паблик добавлен!\n🆔 ID: {group_id}\n\n"
        f"💡 Теперь добавьте источники через /add_source"
    )
    
    for key in ['temp_project_id', 'temp_project_name', 'temp_platform', 'temp_vk_token']:
        context.user_data.pop(key, None)
    
    sources_count = await get_sources_count(project_id)
    if sources_count > 0:
        await send_project_ready_message(update, project_name)
    
    return ConversationHandler.END


async def add_target_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавление Telegram-канала (пересланное сообщение)."""
    msg = update.message
    
    if not msg.forward_from_chat or msg.forward_from_chat.type != 'channel':
        await update.message.reply_text("❌ Перешлите сообщение из канала.")
        return AWAITING_TARGET_FORWARD
    
    chat = msg.forward_from_chat
    project_id = context.user_data.get('temp_project_id')
    project_name = context.user_data.get('temp_project_name')
    
    try:
        test_msg = await context.bot.send_message(chat.id, "🔧 Проверка прав...")
        await test_msg.delete()
    except:
        await update.message.reply_text("❌ Бот не имеет прав администратора.")
        return AWAITING_TARGET_FORWARD
    
    async with AsyncSessionLocal() as session:
        channel = TargetChannel(
            project_id=project_id,
            platform="telegram",
            channel_id=chat.id,
            channel_username=chat.username,
            channel_title=chat.title
        )
        session.add(channel)
        await session.commit()
    
    await update.message.reply_text(f"✅ Канал «{chat.title}» добавлен!")
    
    for key in ['temp_project_id', 'temp_project_name', 'temp_platform']:
        context.user_data.pop(key, None)
    
    sources_count = await get_sources_count(project_id)
    if sources_count > 0:
        await send_project_ready_message(update, project_name)
    
    return ConversationHandler.END


async def my_targets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    project = await require_project(update, context)
    if not project:
        return
    
    target = await get_project_target(project.id)
    if not target:
        await update.message.reply_text(f"📭 В проекте «{project.name}» нет цели.\nДобавьте: /add_target")
        return
    
    text = f"🎯 <b>Цель «{project.name}»</b>\n\n"
    
    if target.platform == "telegram":
        text += f"🟢 <b>Telegram</b>\n📝 {target.channel_title}\n"
        if target.channel_username:
            text += f"🔗 @{target.channel_username}\n"
        text += f"🆔 {target.channel_id}\n"
    elif target.platform == "vk":
        text += f"🔵 <b>VK</b>\n📝 {target.vk_group_name or 'Группа VK'}\n🆔 {target.vk_group_id}\n"
    
    keyboard = [[InlineKeyboardButton("❌ Удалить", callback_data=f"del_target_{target.id}")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def delete_target_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    target_id = int(query.data.replace("del_target_", ""))
    async with AsyncSessionLocal() as session:
        await session.execute(delete(TargetChannel).where(TargetChannel.id == target_id))
        await session.commit()
    await query.edit_message_text("✅ Цель удалена")