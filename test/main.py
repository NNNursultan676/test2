
import threading
import time
import logging
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from app import app
    from bot import main as bot_main
except ImportError as e:
    logger.error(f"Import error: {e}")
    logger.info("Trying to install requirements...")
    os.system("pip install -r requirements.txt")
    from app import app
    from bot import main as bot_main

def run_bot():
    """Run the Telegram bot in a separate thread"""
    try:
        bot_main()
    except Exception as e:
        logger.error(f"Bot error: {e}")

def run_flask():
    """Run the Flask app"""
    try:
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"Flask error: {e}")

if __name__ == '__main__':
    logger.info("Starting application...")
    
    # Start bot in a separate thread
    try:
        bot_thread = threading.Thread(target=run_bot, daemon=True)
        bot_thread.start()
        logger.info("Bot thread started")
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
    
    # Give bot time to start
    time.sleep(2)
    
    # Run Flask app in main thread
    logger.info("Starting Flask app...")
    run_flask()
