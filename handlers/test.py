import logging
from telegram import Update
from telegram.ext import ContextTypes
from bs4 import BeautifulSoup
from scrapers import TelegramScraper
from utils import format_number

logger = logging.getLogger(__name__)


async def test_scraper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тест скрапера."""
    if not context.args:
        await update.message.reply_text("ℹ️ /test [username]\nПример: /test durov")
        return
    
    raw = context.args[0]
    username = raw.replace("@", "").replace("https://t.me/", "").replace("http://t.me/", "").replace("t.me/", "").strip("/")
    
    msg = await update.message.reply_text(f"🔍 Тестирую @{username}...")
    
    async with TelegramScraper() as scraper:
        info = await scraper.get_channel_info(username)
        if not info:
            await msg.edit_text(f"❌ Канал @{username} не найден или не публичный")
            return
        
        posts = await scraper.get_posts(username, limit=5)
        
        if posts:
            text = f"📨 @{username} ({info['title']})\nНайдено постов: {len(posts)}\n\n"
            for i, p in enumerate(posts[:5], 1):
                text += f"{i}. 👁 {format_number(p['views'])} | ❤️ {format_number(p['reactions'])}\n"
                text += f"   📎 {'📷' if p.get('media_type') == 'photo' else '🎬' if p.get('media_type') == 'video' else '📝'}\n"
                if p.get('text'):
                    text += f"   {p['text'][:50]}...\n"
                text += "\n"
        else:
            text = f"❌ Посты не найдены. Проверьте https://t.me/s/{username}"
    
    await msg.edit_text(text)


async def debug_reactions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отладка парсинга реакций — показывает сырой HTML."""
    if not context.args:
        await update.message.reply_text("ℹ️ /debug_reactions [username]\nПример: /debug_reactions yaplakal")
        return
    
    username = context.args[0].replace("@", "").strip("/")
    msg = await update.message.reply_text(f"🔍 Анализирую реакции @{username}...")
    
    async with TelegramScraper() as scraper:
        url = f"https://t.me/s/{username}"
        html = await scraper._fetch(url)
        
        if not html:
            await msg.edit_text("❌ Не удалось загрузить страницу")
            return
        
        soup = BeautifulSoup(html, "lxml")
        messages = soup.find_all("div", class_="tgme_widget_message")[:3]
        
        if not messages:
            await msg.edit_text("❌ Сообщения не найдены")
            return
        
        result = []
        for i, msg_div in enumerate(messages, 1):
            reactions_div = msg_div.find("div", class_="tgme_widget_message_reactions")
            
            result.append(f"📝 <b>Пост {i}:</b>")
            
            if reactions_div:
                reactions_html = str(reactions_div)[:400]
                result.append(f"✅ Блок реакций найден:")
                result.append(f"<code>{reactions_html}</code>")
                
                spans = reactions_div.find_all("span")
                for span in spans:
                    classes = span.get("class", [])
                    text = span.get_text(strip=True)
                    result.append(f"• Span: classes={classes}, text='{text}'")
                
                # Ищем эмодзи с числами
                import re
                reactions_text = reactions_div.get_text()
                emoji_pattern = r'([^\w\s\d]{1,3})\s*(\d{1,6})'
                matches = re.findall(emoji_pattern, reactions_text)
                if matches:
                    result.append(f"🔍 Найдены эмодзи+числа: {matches}")
            else:
                result.append(f"❌ Блок реакций НЕ найден")
                msg_html = str(msg_div)[:300]
                result.append(f"HTML: <code>{msg_html}</code>")
            
            result.append("")
        
        full_result = "\n".join(result)
        if len(full_result) > 4000:
            full_result = full_result[:4000] + "..."
        
        await msg.edit_text(full_result, parse_mode="HTML")