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

    async def publish_post(self, queue_item: PostQueue) -> bool:
        try:
            post_data = queue_item.post_data
            
            # Удаление текста если настроено
            remove_text = post_data.get("remove_original_text", False)
            if remove_text:
                caption = ""
            else:
                caption = clean_caption(post_data.get("text", ""))
            
            # Подпись проекта
            async with AsyncSessionLocal() as session:
                result = await session.execute(select(Project).where(Project.id == queue_item.project_id))
                project = result.scalar_one_or_none()
                signature = project.signature if project else None
            
            if signature:
                if caption:
                    caption += f"\n\n{signature}"
                else:
                    caption = signature
            
            # Источник если включено
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
            
            if media_path and os.path.exists(media_path):
                try:
                    with open(media_path, "rb") as f:
                        if media_type == "photo":
                            await self.bot.send_photo(
                                chat_id=queue_item.target_channel_id,
                                photo=f,
                                caption=caption if caption else None,
                                parse_mode=parse_mode
                            )
                        elif media_type == "video":
                            await self.bot.send_video(
                                chat_id=queue_item.target_channel_id,
                                video=f,
                                caption=caption if caption else None,
                                parse_mode=parse_mode
                            )
                        else:
                            await self.bot.send_document(
                                chat_id=queue_item.target_channel_id,
                                document=f,
                                caption=caption if caption else None,
                                parse_mode=parse_mode
                            )
                    
                    try:
                        os.remove(media_path)
                    except:
                        pass
                    
                    await self._mark_published(queue_item)
                    return True
                    
                except Exception as e:
                    logger.error(f"Failed to send media: {e}")
                    if parse_mode and "parse" in str(e).lower():
                        try:
                            with open(media_path, "rb") as f:
                                if media_type == "photo":
                                    await self.bot.send_photo(chat_id=queue_item.target_channel_id, photo=f, caption=caption if caption else None)
                                elif media_type == "video":
                                    await self.bot.send_video(chat_id=queue_item.target_channel_id, video=f, caption=caption if caption else None)
                                else:
                                    await self.bot.send_document(chat_id=queue_item.target_channel_id, document=f, caption=caption if caption else None)
                            try:
                                os.remove(media_path)
                            except:
                                pass
                            await self._mark_published(queue_item)
                            return True
                        except:
                            pass
                    
                    if caption:
                        try:
                            await self.bot.send_message(chat_id=queue_item.target_channel_id, text=caption, disable_web_page_preview=True)
                            await self._mark_published(queue_item)
                            return True
                        except:
                            pass
                    raise e
                    
            elif caption:
                try:
                    await self.bot.send_message(chat_id=queue_item.target_channel_id, text=caption, disable_web_page_preview=True)
                    await self._mark_published(queue_item)
                    return True
                except Exception as e:
                    logger.error(f"Failed to send text: {e}")
                    raise e
            else:
                await self._mark_failed(queue_item, "Empty post")
                return False
                
        except TelegramError as e:
            await self._mark_failed(queue_item, str(e)[:200])
            return False
        except Exception as e:
            await self._mark_failed(queue_item, str(e)[:200])
            return False

    async def _mark_published(self, queue_item: PostQueue):
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(PostQueue)
                .where(PostQueue.id == queue_item.id)
                .values(status="published", published_at=datetime.utcnow())
            )
            published = PublishedPost(
                project_id=queue_item.project_id,
                target_channel_id=queue_item.target_channel_id,
                platform="telegram",
                source_channel_username=queue_item.post_data.get("source_username", ""),
                post_url=queue_item.post_data.get("url", ""),
                post_data=queue_item.post_data
            )
            session.add(published)
            await session.execute(
                update(TargetChannel)
                .where(TargetChannel.channel_id == queue_item.target_channel_id)
                .values(last_posted=datetime.utcnow())
            )
            await session.commit()

    async def _mark_failed(self, queue_item: PostQueue, error_message: str):
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(PostQueue)
                .where(PostQueue.id == queue_item.id)
                .values(status="failed", error_message=error_message)
            )
            await session.commit()