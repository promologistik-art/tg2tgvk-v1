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
        platform_name = "Telegram" if target.platform == "telegram" else "VK"
        target_name = target.channel_title or target.vk_group_name or "—"
        await update.message.reply_text(
            f"⚠️ В проекте уже есть цель ({platform_name}): {target_name}\n"
            f"Удалите через /my_targets"
        )
        return ConversationHandler.END
    
    context.user_data['temp_project_id'] = project.id
    context.user_data['temp_project_name'] = project.name
    
    keyboard = [
        [InlineKeyboardButton("🟢 Telegram", callback_data="platform_telegram")],
        [InlineKeyboardButton("🔵 VK", callback_data="platform_vk")],
    ]
    
    await update.message.reply_text(
        f"📤 <b>Добавление цели в «{project.name}»</b>\n\n"
        f"Выберите платформу для публикации:",
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
            f"🟢 <b>Добавление Telegram-канала</b>\n\n"
            f"1. Добавьте @{me.username} в администраторы канала\n"
            f"2. Выдайте боту права на публикацию сообщений\n"
            f"3. Перешлите сюда любое сообщение из этого канала\n\n"
            f"⚠️ Пересылать нужно именно из канала, не из избранного.",
            parse_mode="HTML"
        )
        return AWAITING_TARGET_FORWARD
    
    elif platform == "vk":
        await query.edit_message_text(
            f"🔵 <b>Добавление VK-сообщества</b>\n\n"
            f"<b>Шаг 1 из 2:</b> Отправьте ключ доступа сообщества VK.\n\n"
            f"<b>Как получить ключ:</b>\n"
            f"1. Создайте сообщество (группу/паблик) в VK\n"
            f"2. Перейдите: Управление → Дополнительно → Работа с API\n"
            f"3. Нажмите «Создать ключ»\n"
            f"4. Отметьте права: <b>wall, photos, video, groups</b>\n"
            f"5. Подтвердите создание ключа\n"
            f"6. Скопируйте ключ и отправьте его сюда\n\n"
            f"🔐 <i>Ключ сохраняется только для этого проекта.\n"
            f"Не передавайте ключ третьим лицам.</i>",
            parse_mode="HTML"
        )
        return AWAITING_VK_TOKEN


async def add_target_vk_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение ключа доступа VK."""
    token = update.message.text.strip()
    
    # Валидация: ключ VK обычно длинный, содержит буквы и цифры
    if len(token) < 20:
        await update.message.reply_text(
            "❌ Ключ слишком короткий.\n"
            "Отправьте полный ключ доступа сообщества из настроек VK."
        )
        return AWAITING_VK_TOKEN
    
    # Сохраняем токен
    context.user_data['temp_vk_token'] = token
    
    await update.message.reply_text(
        f"🔵 <b>Шаг 2 из 2:</b> Отправьте ID сообщества VK.\n\n"
        f"<b>Где найти ID:</b>\n"
        f"• Откройте сообщество VK\n"
        f"• В адресной строке будет:\n"
        f"  <code>vk.com/public123456</code> → ID = <b>123456</b>\n"
        f"  <code>vk.com/club123456</code> → ID = <b>123456</b>\n"
        f"  <code>vk.com/короткое_имя</code> → откройте:\n"
        f"  <code>vk.com/foaf.php?acting=короткое_имя</code>\n\n"
        f"Отправьте только цифры ID.",
        parse_mode="HTML"
    )
    return AWAITING_VK_GROUP


async def add_target_vk_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение VK-цели."""
    group_id_str = update.message.text.strip()
    
    # Извлекаем только цифры из ввода
    import re
    digits = re.sub(r'\D', '', group_id_str)
    
    if not digits:
        await update.message.reply_text(
            "❌ Не удалось найти ID.\n"
            "Отправьте ID сообщества (только цифры).\n"
            "Например: 123456"
        )
        return AWAITING_VK_GROUP
    
    group_id = int(digits)
    
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
        logger.info(f"Added VK target: group {group_id} to project {project_id}")
    
    await update.message.reply_text(
        f"✅ <b>VK-сообщество добавлено!</b>\n\n"
        f"🆔 ID сообщества: <code>{group_id}</code>\n"
        f"🔐 Ключ доступа сохранён\n\n"
        f"💡 Теперь добавьте источники через /add_source\n"
        f"Бот будет парсить каналы и публиковать посты в это сообщество VK."
    )
    
    # Очищаем временные данные
    for key in ['temp_project_id', 'temp_project_name', 'temp_platform', 'temp_vk_token']:
        context.user_data.pop(key, None)
    
    # Проверяем, готов ли проект
    sources_count = await get_sources_count(project_id)
    if sources_count > 0:
        await send_project_ready_message(update, project_name)
    
    return ConversationHandler.END


async def add_target_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавление Telegram-канала через пересланное сообщение."""
    msg = update.message
    
    if not msg.forward_from_chat or msg.forward_from_chat.type != 'channel':
        await update.message.reply_text(
            "❌ Это не пересланное сообщение из канала.\n"
            "Перешлите любое сообщение из целевого Telegram-канала."
        )
        return AWAITING_TARGET_FORWARD
    
    chat = msg.forward_from_chat
    project_id = context.user_data.get('temp_project_id')
    project_name = context.user_data.get('temp_project_name')
    
    # Проверяем права бота в канале
    try:
        test_msg = await context.bot.send_message(chat.id, "🔧 Проверка прав доступа...")
        await test_msg.delete()
    except Exception as e:
        logger.error(f"Bot permission check failed: {e}")
        await update.message.reply_text(
            "❌ Бот не имеет прав администратора в этом канале.\n\n"
            "Убедитесь, что:\n"
            "• Бот добавлен в администраторы канала\n"
            "• У бота есть право публиковать сообщения"
        )
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
        logger.info(f"Added Telegram target: {chat.title} (ID: {chat.id})")
    
    await update.message.reply_text(
        f"✅ <b>Telegram-канал добавлен!</b>\n\n"
        f"📝 Название: {chat.title}\n"
        f"🆔 ID: <code>{chat.id}</code>\n"
        f"{'🔗 @' + chat.username if chat.username else ''}"
    )
    
    # Очищаем временные данные
    for key in ['temp_project_id', 'temp_project_name', 'temp_platform']:
        context.user_data.pop(key, None)
    
    # Проверяем, готов ли проект
    sources_count = await get_sources_count(project_id)
    if sources_count > 0:
        await send_project_ready_message(update, project_name)
    
    return ConversationHandler.END


async def my_targets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать цель проекта."""
    project = await require_project(update, context)
    if not project:
        return
    
    target = await get_project_target(project.id)
    
    if not target:
        await update.message.reply_text(
            f"📭 В проекте «{project.name}» нет цели.\n"
            f"Добавьте через /add_target"
        )
        return
    
    text = f"🎯 <b>Цель проекта «{project.name}»</b>\n\n"
    
    if target.platform == "telegram":
        text += f"🟢 <b>Платформа:</b> Telegram\n"
        text += f"📝 <b>Канал:</b> {target.channel_title}\n"
        if target.channel_username:
            text += f"🔗 @{target.channel_username}\n"
        text += f"🆔 <code>{target.channel_id}</code>\n"
        if target.last_posted:
            text += f"📤 Последняя публикация: {target.last_posted.strftime('%d.%m.%Y %H:%M')}\n"
    
    elif target.platform == "vk":
        text += f"🔵 <b>Платформа:</b> VK\n"
        text += f"📝 <b>Сообщество:</b> {target.vk_group_name or 'Группа VK'}\n"
        text += f"🆔 <code>{target.vk_group_id}</code>\n"
        text += f"🔐 Ключ: {'установлен' if target.vk_token else 'не установлен'}\n"
        if target.last_posted:
            text += f"📤 Последняя публикация: {target.last_posted.strftime('%d.%m.%Y %H:%M')}\n"
    
    keyboard = [[InlineKeyboardButton("❌ Удалить цель", callback_data=f"del_target_{target.id}")]]
    
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )


async def delete_target_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удалить цель."""
    query = update.callback_query
    await query.answer()
    
    target_id = int(query.data.replace("del_target_", ""))
    
    async with AsyncSessionLocal() as session:
        await session.execute(delete(TargetChannel).where(TargetChannel.id == target_id))
        await session.commit()
        logger.info(f"Deleted target {target_id}")
    
    await query.edit_message_text("✅ Цель удалена")