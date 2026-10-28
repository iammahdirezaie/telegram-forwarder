import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
TEMP_DOWNLOAD_DIR = BASE_DIR / ".clone-temp"
TEMP_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# تلگرام سشن
SESSION_NAME = os.getenv("TG_SESSION_NAME", "account")

# کلیدهای دسکتاپ تلگرام (یا کلیدهای اختصاصی خودتان)
API_ID = int(os.getenv("TG_API_ID", ""))
API_HASH = os.getenv("TG_API_HASH", "")

# کانال اول: کانالی که لینک‌ها داخلش ارسال و مانیتور می‌شوند
TARGET_CHANNEL = os.getenv("TG_TARGET_CHANNEL", "")

# کانال دوم: کانال مقصد جهت فوروارد/کپی محتوا (می‌تواند آیدی عددی مثل -100xxx یا یوزرنیم باشد)
# اگر نیازی ندارید، مقدار آن را None بگذارید
FORWARD_CHANNEL = os.getenv("TG_FORWARD_CHANNEL", "YourSecondChannelUsername")

# تنظیمات بهینه ارتباطی برای سرورهای اشتراکی
WORKERS = 1
MAX_CONCURRENT_TRANSMISSIONS = 1
DOWNLOAD_ATTEMPTS = 3
UPLOAD_PART_ATTEMPTS = 3