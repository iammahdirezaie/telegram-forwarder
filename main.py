import asyncio
import logging
from pyrogram import Client
from pyrogram.errors import FloodWait, RPCError

from config import (
    API_ID,
    API_HASH,
    SESSION_NAME,
    TARGET_CHANNEL,
    FORWARD_CHANNEL,
    WORKERS,
    MAX_CONCURRENT_TRANSMISSIONS,
)
from core import PostFetcher, _RE_PRIVATE_POST, _RE_PUBLIC_POST

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ChannelWatcher")

app = Client(
    SESSION_NAME,
    api_id=API_ID,
    api_hash=API_HASH,
    workers=WORKERS,
    max_concurrent_transmissions=MAX_CONCURRENT_TRANSMISSIONS,
)


async def watch_channel():
    fetcher = PostFetcher(app)

    chat = await app.get_chat(TARGET_CHANNEL)
    target_chat_id = chat.id
    logger.info(f"Connected to Primary Channel: '{chat.title}' (ID: {target_chat_id})")

    forward_chat_id = None
    if FORWARD_CHANNEL:
        try:
            f_chat = await app.get_chat(FORWARD_CHANNEL)
            forward_chat_id = f_chat.id
            logger.info(f"Connected to Forward Channel: '{f_chat.title}' (ID: {forward_chat_id})")
        except Exception as e:
            logger.warning(f"Could not resolve forward channel '{FORWARD_CHANNEL}': {e}")

    processed_ids = set()
    async for msg in app.get_chat_history(target_chat_id, limit=10):
        processed_ids.add(msg.id)

    logger.info(f"Bot listening for incoming links in @{TARGET_CHANNEL}...")

    while True:
        try:
            async for msg in app.get_chat_history(target_chat_id, limit=5):
                if msg.id in processed_ids:
                    continue

                processed_ids.add(msg.id)
                text = (msg.text or msg.caption or "").strip()
                if not text:
                    continue

                if text.startswith("⏳") or text.startswith("✅") or text.startswith("❌"):
                    continue

                is_link = bool(_RE_PRIVATE_POST.search(text) or _RE_PUBLIC_POST.search(text))
                if not is_link:
                    continue

                logger.info(f"Link detected: {text}")
                status = await app.send_message(
                    chat_id=target_chat_id,
                    text="⏳ در حال شروع دریافت فایل...",
                )

                try:
                    count = await fetcher.fetch_and_deliver(
                        link=text,
                        target_chat=target_chat_id,
                        forward_chat=forward_chat_id,
                        status_msg=status,
                    )
                    await status.edit_text(f"✅ فایل با موفقیت استخراج و ارسال شد! ({count} پیام)")
                    logger.info(f"Successfully processed post from link: {text}")
                except Exception as err:
                    logger.error(f"Error processing link: {err}", exc_info=True)
                    await status.edit_text(f"❌ خطا:\n`{err}`")

            await asyncio.sleep(2)

        except FloodWait as e:
            logger.warning(f"FloodWait encountered: sleeping for {e.value}s")
            await asyncio.sleep(e.value)
        except RPCError as e:
            logger.error(f"Telegram RPC error: {e}")
            await asyncio.sleep(3)
        except Exception as e:
            logger.error(f"Loop error: {e}")
            await asyncio.sleep(3)


async def main():
    async with app:
        await watch_channel()


if __name__ == "__main__":
    app.run(main())