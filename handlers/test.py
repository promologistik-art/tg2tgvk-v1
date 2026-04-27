async def debug_reactions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отладка парсинга реакций."""
    if not context.args:
        await update.message.reply_text("Использование: /debug_reactions username")
        return
    
    username = context.args[0].replace("@", "")
    msg = await update.message.reply_text(f"🔍 Анализирую реакции @{username}...")
    
    async with TelegramScraper() as scraper:
        url = f"https://t.me/s/{username}"
        html = await scraper._fetch(url)
        
        if not html:
            await msg.edit_text("❌ Не удалось загрузить страницу")
            return
        
        soup = BeautifulSoup(html, "lxml")
        messages = soup.find_all("div", class_="tgme_widget_message")[:3]
        
        result = []
        for i, msg_div in enumerate(messages, 1):
            # Ищем блок реакций
            reactions_div = msg_div.find("div", class_="tgme_widget_message_reactions")
            
            result.append(f"📝 Пост {i}:")
            
            if reactions_div:
                # Показываем HTML блока реакций
                reactions_html = str(reactions_div)[:500]
                result.append(f"   Блок реакций найден:")
                result.append(f"   <code>{reactions_html}</code>")
                
                # Показываем все span'ы внутри
                spans = reactions_div.find_all("span")
                for span in spans:
                    classes = span.get("class", [])
                    text = span.get_text(strip=True)
                    result.append(f"   Span: classes={classes}, text='{text}'")
            else:
                result.append(f"   Блок реакций НЕ найден")
                # Показываем часть HTML сообщения
                msg_html = str(msg_div)[:300]
                result.append(f"   HTML: <code>{msg_html}</code>")
        
        full_result = "\n".join(result)
        if len(full_result) > 4000:
            full_result = full_result[:4000] + "..."
        
        await msg.edit_text(full_result, parse_mode="HTML")