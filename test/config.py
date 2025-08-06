import os

# Telegram Bot Configuration
BOT_TOKEN = "8402895325:AAGra2jy2061DTaZqpWE8_qPowqZDl1hK7g"
GROUP_ID = -1002723413852
THREAD_ID = 4  # Thread ID for notifications (as integer)
NOTIFICATION_THREAD_ID = 4  # Thread ID for recurring notifications (as integer)

# Alternative way to load from environment variables:
# BOT_TOKEN = os.getenv("BOT_TOKEN")
# GROUP_ID = int(os.getenv("GROUP_ID"))

# JSON file paths
USERS_JSON_PATH = "data/users.json"
BOOKINGS_JSON_PATH = "data/bookings.json"

# Database URL for future PostgreSQL migration
DATABASE_URL = "url://..."  # on future