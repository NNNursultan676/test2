
import threading
import time
from app import app
from bot import main as bot_main

def run_bot():
    """Run the Telegram bot in a separate thread"""
    bot_main()

def run_flask():
    """Run the Flask app"""
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

if __name__ == '__main__':
    # Start bot in a separate thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Give bot time to start
    time.sleep(2)
    
    # Run Flask app in main thread
    run_flask()
