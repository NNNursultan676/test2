
import os
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes
from config import BOT_TOKEN, GROUP_ID

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def check_group_membership(user_id):
    """Check if user is a member of the Telegram group"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember"
        params = {
            'chat_id': GROUP_ID,
            'user_id': user_id
        }
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        if data.get('ok'):
            status = data.get('result', {}).get('status')
            return status in ['creator', 'administrator', 'member']
        return False
    except Exception as e:
        logger.error(f"Error checking Telegram group membership: {e}")
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command"""
    user = update.effective_user
    user_id = user.id
    first_name = user.first_name or "Пользователь"
    
    # Check if user is a member of the group
    is_member = await check_group_membership(user_id)
    
    if not is_member:
        access_denied_msg = (
            f"❌ Извините, {first_name}!\n\n"
            f"🔒 Доступ к системе бронирования ограничен только для участников группы Sapa Group.\n\n"
            f"📞 Для получения доступа обратитесь к администратору."
        )
        await update.message.reply_text(access_denied_msg, parse_mode='HTML')
        logger.warning(f"Access denied for user {user_id} ({first_name}) - not a group member")
        return
    
    # Greeting message for authorized users
    greeting = (
        f"👋 Здравствуйте, {first_name}!\n\n"
        f"🏢 Добро пожаловать в систему бронирования переговорных Sapa Group!\n\n"
        f"📱 Для доступа к системе нажмите кнопку ниже:"
    )
    
    # Create inline keyboard with Web App button
    webapp_url = f"https://test2-85hz.onrender.com/telegram-auth?telegram_id={user_id}"
    keyboard = [
        [InlineKeyboardButton(
            "🚀 Открыть веб-приложение", 
            web_app=WebAppInfo(url=webapp_url)
        )],
        [InlineKeyboardButton(
            "📋 Прямая ссылка", 
            url=webapp_url
        )]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        greeting,
        reply_markup=reply_markup,
        parse_mode='HTML'
    )
    
    logger.info(f"Access granted for user {user_id} ({first_name}) - group member")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /help command"""
    help_text = (
        "🤖 <b>Бот системы бронирования Sapa Group</b>\n\n"
        "📋 <b>Доступные команды:</b>\n"
        "/start - Запустить бота и получить доступ к веб-приложению\n"
        "/help - Показать это сообщение помощи\n\n"
        "💡 <b>Как пользоваться:</b>\n"
        "1. Нажмите /start\n"
        "2. Выберите 'Открыть веб-приложение'\n"
        "3. Забронируйте переговорную!\n\n"
        "❓ По вопросам обращайтесь к администратору."
    )
    
    await update.message.reply_text(help_text, parse_mode='HTML')

def main() -> None:
    """Start the bot"""
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))

    # Log bot startup
    logger.info("Starting Sapa Room Booking Bot...")

    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
