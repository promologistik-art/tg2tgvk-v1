import os
import logging
from datetime import datetime
from telegram import Bot
from telegram.error import TelegramError
from sqlalchemy import select, update
from database import AsyncSessionLocal
from models import PostQueue, PublishedPost, TargetChannel, Project
from utils import clean_caption
from config import Config

logger = logging.getLogger(__name__)


class TelegramPoster:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def add_to_queue(self, project_id: int, target_channel_id: int, post_data: dict, scheduled_time: datetime):
        """Добавить пост в очередь публикации."""
        async with AsyncSessionLocal() as session:
            queue_item = PostQueue(
                project_id=project_id,
                target_channel_id=target_channel_id,
                platform="telegram",
                post_data=post_data,
                scheduled_time=scheduled_time,
                status="pending"
            )
            session.add(queue_item)
            await session.commit()
            logger.info(f"📨 Post queued for project {project_id}, scheduled at {scheduled_time}")

    async def publish_post(self, queue_item: PostQueue) -> bool:
        """Опубликовать пост в Telegram."""
        try:
            # Получаем данные целевого канала
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(TargetChannel).where(TargetChannel.id == queue_item.target_channel_id)
                )
                target = result.scalar_one_or_none()
                
                if not target:
                    await self._mark_failed(queue_item, "Целевой канал не найден в базе")
                    return False
                
                real_chat_id = target.channel_id  # Реальный Telegram chat_id
                
                # Получаем подпись проекта
                result = await session.execute(
                    select(Project).where(Project.id == queue_item.project_id)
                )
                project = result.scalar_one_or_none()
                signature = project.signature if project else None
            
            post_data = queue_item.post_data
            
            # Удаление текста если настроено
            remove_text = post_data.get("remove_original_text", False)
            if remove_text:
                caption = ""
            else:
                caption = clean_caption(post_data.get("text", ""))
            
            # Добавляем подпись проекта
            if signature:
                if caption:
                    caption += f"\n\n{signature}"
                else:
                    caption = signature
            
            # Добавляем источник если включено
            if Config.SHOW_SOURCE_SIGNATURE:
                source = post_data.get("source_username", "")
                if source:
                    if caption:
                        caption += f"\n\n📡 @{source}"
                    else:
                        caption = f"📡 @{source}"
            
            media_path = post_data.get("media_path")
            media_type = post_data.get("media_type")
            
            # Определяем parse_mode
            parse_mode = None
            if caption and ("<a href=" in caption or "<b>" in caption or "<i>" in caption):
                parse_mode = "HTML"
            
            # Отправка с медиа
            if media_path and os.path.exists(media_path):
                try:
                    with open(media_path, "rb") as f:
                        if media_type == "photo":
                            await self.bot.send_photo(
                                chat_id=real_chat_id,
                                photo=f,
                                caption=caption if caption else None,
                                parse_mode=parse_mode
                            )
                        elif media_type == "video":
                            await self.bot.send_video(
                                chat_id=real_chat_id,
                                video=f,
                                caption=caption if caption else None,
                                parse_mode=parse_mode
                            )
                        else:
                            await self.bot.send_document(
                                chat_id=real_chat_id,
                                document=f,
                                caption=caption if caption else None,
                                parse_mode=parse_mode
                            )
                    
                    # Удаляем временный файл
                    try:
                        os.remove(media_path)
                    except:
                        pass
                    
                    await self._mark_published(queue_item)
                    logger.info(f"✅ Published post {queue_item.id} with media to {real_chat_id}")
                    return True
                    
                except TelegramError as e:
                    logger.error(f"Failed to send media to {real_chat_id}: {e}")
                    
                    # Если ошибка из-за parse_mode, пробуем без него
                    if parse_mode and "parse" in str(e).lower():
                        try:
                            with open(media_path, "rb") as f:
                                if media_type == "photo":
                                    await self.bot.send_photo(
                                        chat_id=real_chat_id,
                                        photo=f,
                                        caption=caption if caption else None
                                    )
                                elif media_type == "video":
                                    await self.bot.send_video(
                                        chat_id=real_chat_id,
                                        video=f,
                                        caption=caption if caption else None
                                    )
                                else:
                                    await self.bot.send_document(
                                        chat_id=real_chat_id,
                                        document=f,
                                        caption=caption if caption else None
                                    )
                            
                            try:
                                os.remove(media_path)
                            except:
                                pass
                            
                            await self._mark_published(queue_item)
                            logger.info(f"✅ Published post {queue_item.id} (no parse_mode)")
                            return True
                        except Exception as e2:
                            logger.error(f"Failed to send without parse_mode: {e2}")
                    
                    # Пробуем отправить только текст
                    if caption:
                        try:
                            await self.bot.send_message(
                                chat_id=real_chat_id,
                                text=caption,
                                disable_web_page_preview=True
                            )
                            await self._mark_published(queue_item)
                            logger.info(f"✅ Published post {queue_item.id} (text only after media fail)")
                            return True
                        except Exception as e3:
                            logger.error(f"Failed to send text: {e3}")
                    
                    await self._mark_failed(queue_item, str(e)[:200])
                    return False
            
            # Отправка только текста
            elif caption:
                try:
                    await self.bot.send_message(
                        chat_id=real_chat_id,
                        text=caption,
                        parse_mode=parse_mode,
                        disable_web_page_preview=True
                    )
                    await self._mark_published(queue_item)
                    logger.info(f"✅ Published post {queue_item.id} (text only)")
                    return True
                except TelegramError as e:
                    # Пробуем без parse_mode
                    if parse_mode:
                        try:
                            await self.bot.send_message(
                                chat_id=real_chat_id,
                                text=caption,
                                disable_web_page_preview=True
                            )
                            await self._mark_published(queue_item)
                            return True
                        except:
                            pass
                    
                    logger.error(f"Failed to send text to {real_chat_id}: {e}")
                    await self._mark_failed(queue_item, str(e)[:200])
                    return False
            
            # Пустой пост
            else:
                logger.warning(f"Empty post {queue_item.id}")
                await self._mark_failed(queue_item, "Empty post")
                return False
                
        except Exception as e:
            logger.error(f"Unexpected error publishing post {queue_item.id}: {e}")
            await self._mark_failed(queue_item, str(e)[:200])
            return False

    async def _mark_published(self, queue_item: PostQueue):
        """Отметить пост как опубликованный."""
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(PostQueue)
                .where(PostQueue.id == queue_item.id)
                .values(status="published", published_at=datetime.utcnow())
            )
            
            post_data = queue_item.post_data
            published = PublishedPost(
                project_id=queue_item.project_id,
                target_channel_id=queue_item.target_channel_id,
                platform="telegram",
                source_channel_username=post_data.get("source_username", ""),
                post_url=post_data.get("url", ""),
                post_data=post_data
            )
            session.add(published)
            
            # Обновляем last_posted у целевого канала
            result = await session.execute(
                select(TargetChannel).where(TargetChannel.id == queue_item.target_channel_id)
            )
            target = result.scalar_one_or_none()
            if target:
                target.last_posted = datetime.utcnow()
            
            await session.commit()
            logger.info(f"📊 Marked post {queue_item.id} as published")

    async def _mark_failed(self, queue_item: PostQueue, error_message: str):
        """Отметить пост как failed."""
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(PostQueue)
                .where(PostQueue.id == queue_item.id)
                .values(status="failed", error_message=error_message)
            )
            await session.commit()
            logger.warning(f"❌ Marked post {queue_item.id} as failed: {error_message}")