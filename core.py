import asyncio
import logging
import os
import re
import shutil
import stat
import tempfile
import time
from typing import Optional, Tuple, List

from pyrogram import Client
from pyrogram.errors import (
    FilePartMissing,
    FileReferenceExpired,
    RPCError,
)
from pyrogram.types import (
    InputMediaAudio,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
)

from config import (
    TEMP_DOWNLOAD_DIR,
    DOWNLOAD_ATTEMPTS,
    UPLOAD_PART_ATTEMPTS,
)

logger = logging.getLogger("MediaEngine")

_RE_PUBLIC_POST = re.compile(
    r"https?://(?:www\.)?t\.me/(?:s/)?([a-zA-Z_][a-zA-Z0-9_]{3,})(?:/\d+)?/(\d+)/?(?:\?.*)?$"
)
_RE_PRIVATE_POST = re.compile(
    r"https?://(?:www\.)?t\.me/c/(\d+)(?:/(\d+))?(?:/(\d+))?/?(?:\?.*)?$"
)


def parse_post_link(link: str) -> Tuple[int | str, int]:
    """تبدیل انواع لینک‌های پابلیک و پرایوت (عادی یا تاپیک‌دار) به آیدی چت و پیام"""
    val = link.strip()
    m_priv = _RE_PRIVATE_POST.search(val)
    if m_priv:
        channel_id = int(f"-100{m_priv.group(1)}")
        msg_id_str = m_priv.group(3) or m_priv.group(2)
        if not msg_id_str:
            raise ValueError("شناسه پیام در لینک یافت نشد.")
        return channel_id, int(msg_id_str)

    m_pub = _RE_PUBLIC_POST.search(val)
    if m_pub:
        return m_pub.group(1), int(m_pub.group(2))

    raise ValueError("ساختار لینک تلگرام نامعتبر است.")


class PostFetcher:
    def __init__(self, client: Client):
        self.app = client
        self.temp_dir = TEMP_DOWNLOAD_DIR
        self._last_edit_time = 0.0

    def _make_temp_dir(self, prefix: str) -> str:
        return tempfile.mkdtemp(prefix=prefix, dir=str(self.temp_dir.resolve()))

    @staticmethod
    def _remove_temp_dir(path: str) -> None:
        if not os.path.exists(path):
            return

        def remove_readonly(func, item_path, _):
            os.chmod(item_path, stat.S_IWRITE)
            func(item_path)

        for attempt in range(3):
            try:
                shutil.rmtree(path, onerror=remove_readonly)
                return
            except OSError:
                if attempt < 2:
                    time.sleep(0.3)

    async def _progress_tracker(self, current: int, total: int, status_msg: Optional[Message], action_name: str):
        if not total:
            return
        percent = (current / total) * 100
        cur_mb = current / (1024 * 1024)
        tot_mb = total / (1024 * 1024)
        now = time.time()

        if (now - self._last_edit_time > 4.0) or current == total:
            self._last_edit_time = now
            logger.info(f"{action_name}: {percent:.1f}% ({cur_mb:.1f}MB / {tot_mb:.1f}MB)")
            if status_msg:
                try:
                    await status_msg.edit_text(
                        f"⏳ {action_name}: {percent:.1f}%\n"
                        f"📊 حجم: {cur_mb:.1f}MB از {tot_mb:.1f}MB"
                    )
                except RPCError:
                    pass

    async def resolve_range(self, source_chat: int | str, msg_id: int) -> List[Message]:
        message = await self.app.get_messages(source_chat, msg_id, replies=0)
        if message is None or getattr(message, "empty", False):
            raise ValueError(f"پیام شماره {msg_id} یافت نشد یا دسترسی وجود ندارد.")

        if message.media_group_id:
            try:
                group = await self.app.get_media_group(source_chat, message.id)
                return sorted(list(group), key=lambda x: x.id)
            except (RPCError, ValueError):
                pass
        return [message]

    async def _send_single_file(self, msg: Message, kind: str, path: str, target_chat: int | str) -> Message:
        cap = msg.caption or ""
        ce = msg.caption_entities
        spoiler = bool(getattr(msg, "has_media_spoiler", False))

        if kind == "photo":
            return await self.app.send_photo(target_chat, path, caption=cap, caption_entities=ce, has_spoiler=spoiler)
        elif kind == "video":
            try:
                return await self.app.send_video(
                    target_chat, path, caption=cap, caption_entities=ce, has_spoiler=spoiler, supports_streaming=True
                )
            except Exception:
                return await self.app.send_document(target_chat, path, caption=cap, caption_entities=ce)
        elif kind == "document":
            return await self.app.send_document(target_chat, path, caption=cap, caption_entities=ce)
        elif kind == "audio":
            return await self.app.send_audio(target_chat, path, caption=cap, caption_entities=ce)
        elif kind == "voice":
            return await self.app.send_voice(target_chat, path, caption=cap, caption_entities=ce)
        else:
            return await self.app.send_document(target_chat, path, caption=cap, caption_entities=ce)

    async def _forward_or_copy(self, sent_msg: Message, forward_chat: int | str) -> None:
        """ارسال خودکار فایل آپلود شده به کانال دوم"""
        if not forward_chat:
            return
        try:
            await self.app.copy_message(chat_id=forward_chat, from_chat_id=sent_msg.chat.id, message_id=sent_msg.id)
            logger.info(f"Delivered copy to forward channel: {forward_chat}")
        except Exception as e:
            logger.warning(f"Could not forward to second channel: {e}")

    async def _process_single(self, msg: Message, target_chat: int | str, forward_chat: Optional[int | str], status_msg: Optional[Message]) -> None:
        if not msg.media:
            if msg.text:
                sent = await self.app.send_message(target_chat, msg.text, entities=msg.entities)
                if forward_chat:
                    await self._forward_or_copy(sent, forward_chat)
            return

        kind = None
        for k in ("photo", "video", "document", "audio", "voice", "animation", "sticker"):
            if getattr(msg, k, None) is not None:
                kind = k
                break

        if not kind:
            sent = await self.app.copy_message(target_chat, msg.chat.id, msg.id)
            if forward_chat:
                await self._forward_or_copy(sent, forward_chat)
            return

        ext_map = {"photo": ".jpg", "video": ".mp4", "audio": ".mp3", "voice": ".ogg", "animation": ".mp4"}
        ext = ext_map.get(kind, ".dat")
        if kind == "document":
            fn = getattr(msg.document, "file_name", "")
            if fn and "." in fn:
                ext = "." + fn.split(".")[-1]

        temp_dir = self._make_temp_dir(f"single_{msg.id}_")
        target_file_path = os.path.join(temp_dir, f"media_{msg.id}{ext}")

        async def dl_progress(current, total):
            await self._progress_tracker(current, total, status_msg, "در حال دانلود از کانال مبدأ")

        try:
            path = None
            for att in range(1, DOWNLOAD_ATTEMPTS + 1):
                try:
                    path = await self.app.download_media(msg, file_name=target_file_path, progress=dl_progress)
                    if path and os.path.isfile(path) and os.path.getsize(path) > 0:
                        break
                except (FileReferenceExpired, RPCError) as exc:
                    if att == DOWNLOAD_ATTEMPTS:
                        raise exc
                    await asyncio.sleep(1)

            if not path or not os.path.isfile(path):
                raise RuntimeError("فایل دانلود نشد یا روی دیسک یافت نشد.")

            if status_msg:
                try:
                    await status_msg.edit_text("⏳ دانلود تکمیل شد. در حال آپلود فایل در کانال...")
                except RPCError:
                    pass

            sent_msg = None
            for att in range(1, UPLOAD_PART_ATTEMPTS + 1):
                try:
                    sent_msg = await self._send_single_file(msg, kind, path, target_chat)
                    break
                except FilePartMissing:
                    if att == UPLOAD_PART_ATTEMPTS:
                        raise
                    await asyncio.sleep(2)

            if sent_msg and forward_chat:
                await self._forward_or_copy(sent_msg, forward_chat)

        finally:
            self._remove_temp_dir(temp_dir)

    async def _process_album(self, messages: List[Message], target_chat: int | str, forward_chat: Optional[int | str]) -> None:
        temp_dir = self._make_temp_dir(f"album_{messages[0].media_group_id}_")
        paths: List[str] = []
        media_inputs = []

        try:
            for idx, msg in enumerate(messages):
                file_dest = os.path.join(temp_dir, f"file_{msg.id}")
                p = await self.app.download_media(msg, file_name=file_dest)
                if not p or not os.path.isfile(p):
                    continue
                paths.append(p)
                cap = msg.caption if idx == 0 else ""
                ce = msg.caption_entities if idx == 0 else None
                spoiler = bool(getattr(msg, "has_media_spoiler", False))

                if msg.photo:
                    media_inputs.append(InputMediaPhoto(p, caption=cap, caption_entities=ce, has_spoiler=spoiler))
                elif msg.video:
                    media_inputs.append(InputMediaVideo(p, caption=cap, caption_entities=ce, has_spoiler=spoiler))
                elif msg.audio:
                    media_inputs.append(InputMediaAudio(p, caption=cap, caption_entities=ce))
                else:
                    media_inputs.append(InputMediaDocument(p, caption=cap, caption_entities=ce))

            if media_inputs:
                sent_group = await self.app.send_media_group(target_chat, media_inputs)
                if forward_chat and sent_group:
                    for g_msg in sent_group:
                        await self._forward_or_copy(g_msg, forward_chat)
        finally:
            self._remove_temp_dir(temp_dir)

    async def fetch_and_deliver(
        self,
        link: str,
        target_chat: int | str,
        forward_chat: Optional[int | str] = None,
        status_msg: Optional[Message] = None,
    ) -> int:
        source_chat, msg_id = parse_post_link(link)
        messages = await self.resolve_range(source_chat, msg_id)

        if len(messages) > 1 and messages[0].media_group_id:
            await self._process_album(messages, target_chat, forward_chat)
            return len(messages)
        else:
            await self._process_single(messages[0], target_chat, forward_chat, status_msg)
            return 1