
import os
import logging
import requests
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ConversationHandler, ContextTypes, filters
from config import BOT_TOKEN, GROUP_ID
from admins import is_admin, add_admin, remove_admin, get_admins_list

# Conversation states
ADD_ADMIN_ID, ADD_ADMIN_LEVEL = range(2)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def auto_delete_message(context, chat_id, message_id, delay=300):
    """Auto delete message after specified delay (default 5 minutes)"""
    try:
        await asyncio.sleep(delay)
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"Auto-deleted message {message_id} in chat {chat_id}")
    except Exception as e:
        logger.warning(f"Failed to auto-delete message {message_id}: {e}")

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
        denied_message = await update.message.reply_text(access_denied_msg, parse_mode='HTML')
        
        # Schedule auto-deletion after 5 minutes
        asyncio.create_task(auto_delete_message(
            context, 
            denied_message.chat_id, 
            denied_message.message_id, 
            300  # 5 minutes
        ))
        
        logger.warning(f"Access denied for user {user_id} ({first_name}) - not a group member")
        return
    
    # Check admin level
    admin_level = is_admin(user_id)
    
    # Greeting message for authorized users
    greeting = (
        f"👋 Здравствуйте, {first_name}!\n\n"
        f"🏢 Добро пожаловать в систему бронирования переговорных Sapa Group!\n\n"
        f"📱 Для доступа к системе нажмите кнопку ниже:"
    )
    
    if admin_level > 0:
        level_text = {3: "Главный администратор", 2: "Админ-модератор", 1: "Администратор"}
        greeting += f"\n\n👑 Ваш уровень: {level_text.get(admin_level, 'Администратор')}"
    
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
    
    # Add admin buttons for level 2 and 3 admins
    if admin_level >= 2:
        keyboard.extend([
            [InlineKeyboardButton("👨‍💼 Добавить админа", callback_data="add_admin")],
            [InlineKeyboardButton("📋 Список админов", callback_data="list_admins")]
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    sent_message = await update.message.reply_text(
        greeting,
        reply_markup=reply_markup,
        parse_mode='HTML'
    )
    
    # Schedule auto-deletion after 5 minutes
    asyncio.create_task(auto_delete_message(
        context, 
        sent_message.chat_id, 
        sent_message.message_id, 
        300  # 5 minutes
    ))
    
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
    
    help_message = await update.message.reply_text(help_text, parse_mode='HTML')
    
    # Schedule auto-deletion after 5 minutes
    asyncio.create_task(auto_delete_message(
        context, 
        help_message.chat_id, 
        help_message.message_id, 
        300  # 5 minutes
    ))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    admin_level = is_admin(user_id)
    
    if query.data == "add_admin":
        if admin_level >= 2:
            await query.edit_message_text(
                "👨‍💼 Добавление нового администратора\n\n"
                "📝 Введите Telegram ID нового администратора:",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Отмена", callback_data="cancel_admin")
                ]])
            )
            return ADD_ADMIN_ID
        else:
            await query.edit_message_text("❌ Недостаточно прав для добавления администратора")
    
    elif query.data == "list_admins":
        if admin_level >= 2:
            admins_list = get_admins_list()
            await query.edit_message_text(
                f"📋 Список администраторов:\n\n{admins_list}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Назад", callback_data="back_to_start")
                ]])
            )
    
    elif query.data == "cancel_admin" or query.data == "back_to_start":
        await start(update, context)
        return ConversationHandler.END

async def add_admin_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle admin ID input"""
    user_id = update.effective_user.id
    admin_level = is_admin(user_id)
    
    if admin_level < 2:
        await update.message.reply_text("❌ Недостаточно прав")
        return ConversationHandler.END
    
    try:
        new_admin_id = int(update.message.text)
        context.user_data['new_admin_id'] = new_admin_id
        
        keyboard = [
            [InlineKeyboardButton("1️⃣ Уровень 1 (Админ)", callback_data="level_1")],
            [InlineKeyboardButton("2️⃣ Уровень 2 (Админ-модератор)", callback_data="level_2")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_admin")]
        ]
        
        # Level 3 admins can create level 2 admins
        if admin_level >= 3:
            keyboard.insert(-1, [InlineKeyboardButton("3️⃣ Уровень 3 (Главный админ)", callback_data="level_3")])
        
        await update.message.reply_text(
            f"🔹 ID: {new_admin_id}\n\n"
            "🎚️ Выберите уровень доступа:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ADD_ADMIN_LEVEL
        
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат ID. Введите числовой Telegram ID:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отмена", callback_data="cancel_admin")
            ]])
        )
        return ADD_ADMIN_ID

async def add_admin_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle admin level selection"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    admin_level = is_admin(user_id)
    new_admin_id = context.user_data.get('new_admin_id')
    
    if not new_admin_id:
        await query.edit_message_text("❌ Ошибка: ID не найден")
        return ConversationHandler.END
    
    level_map = {"level_1": 1, "level_2": 2, "level_3": 3}
    selected_level = level_map.get(query.data, 1)
    
    success, message = add_admin(new_admin_id, selected_level, user_id)
    
    if success:
        level_text = {3: "Главный админ", 2: "Админ-модератор", 1: "Админ"}
        await query.edit_message_text(
            f"✅ Администратор добавлен!\n\n"
            f"👤 ID: {new_admin_id}\n"
            f"🔹 Уровень: {level_text.get(selected_level)}"
        )
    else:
        await query.edit_message_text(f"❌ Ошибка: {message}")
    
    return ConversationHandler.END

def main() -> None:
    """Start the bot"""
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()

    # Add conversation handler for admin management
    admin_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^add_admin$")],
        states={
            ADD_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_admin_id)],
            ADD_ADMIN_LEVEL: [CallbackQueryHandler(add_admin_level, pattern="^level_[123]$")]
        },
        fallbacks=[
            CallbackQueryHandler(button_handler, pattern="^cancel_admin$"),
            CommandHandler("start", start)
        ]
    )

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(admin_conv_handler)
    application.add_handler(CallbackQueryHandler(button_handler))

    # Log bot startup
    logger.info("Starting Sapa Room Booking Bot...")

    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
