import os
import logging
import requests
import asyncio
import json
import threading
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ConversationHandler, ContextTypes, filters
from config import BOT_TOKEN, GROUP_ID
from admins import is_admin, add_admin, remove_admin, get_admins_list
from datetime import datetime, timedelta, time

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
    try:
        user = update.effective_user
        user_id = user.id
        first_name = user.first_name or "Пользователь"

        # Anti-spam protection - check if user sent /start recently
        current_time = datetime.now()
        user_data = context.user_data
        last_start_time = user_data.get('last_start_time')

        if last_start_time:
            time_diff = (current_time - last_start_time).total_seconds()
            if time_diff < 10:  # 10 seconds cooldown
                logger.info(f"Start command ignored for user {user_id} - spam protection")
                return

        user_data['last_start_time'] = current_time

        # Check if user is a member of the group
        is_member = await check_group_membership(user_id)

        if not is_member:
            access_denied_msg = (
                f"👋 Здравствуйте, {first_name}!\n\n"
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

        # Greeting message for authorized users with gradient and animation styles
        greeting = (
            f"👋 Здравствуйте, {first_name}!\n\n"
            f"🏢 Добро пожаловать в систему бронирования переговорных Sapa Group!\n\n"
            f"✨ Для доступа к системе нажмите кнопку ниже:"
        )

        if admin_level > 0:
            level_text = {3: "Главный администратор", 2: "Админ-модератор", 1: "Администратор"}
            greeting += f"\n\n👑 Ваш уровень: {level_text.get(admin_level, 'Администратор')}"

        # Create inline keyboard with Web App button and gradient/animation styling
        webapp_url = f"https://test-85hz.onrender.com/telegram-auth?telegram_id={user_id}"
        logger.info(f"Generated webapp URL for user {user_id}: {webapp_url}")
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

        # Add system clear button for level 3 admins
        if admin_level >= 3:
            keyboard.append([InlineKeyboardButton("💥 Очистить систему", callback_data="clear_system")])

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

    except Exception as e:
        logger.error(f"Error in start handler: {e}")
        try:
            error_message = await update.message.reply_text(
                "❌ Произошла ошибка. Попробуйте еще раз через несколько секунд.",
                parse_mode='HTML'
            )
            # Auto-delete error message after 1 minute
            asyncio.create_task(auto_delete_message(
                context, 
                error_message.chat_id, 
                error_message.message_id, 
                60
            ))
        except Exception as inner_e:
            logger.error(f"Failed to send error message: {inner_e}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /help command"""
    help_text = (
        "✨ <b>Бот системы бронирования Sapa Group</b> ✨\n\n"
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

    elif query.data == "clear_system":
        if admin_level >= 3:
            await query.edit_message_text(
                "⚠️ ВНИМАНИЕ! Это действие удалит:\n"
                "• Все бронирования\n\n"
                "Вы уверены?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Да, очистить всё", callback_data="confirm_clear_system")],
                    [InlineKeyboardButton("❌ Отмена", callback_data="back_to_start")]
                ])
            )

    elif query.data == "confirm_clear_system":
        if admin_level >= 3:
            try:
                import json
                import os

                # Clear bookings
                bookings_path = "data/bookings.json"
                os.makedirs(os.path.dirname(bookings_path), exist_ok=True)
                with open(bookings_path, 'w') as f:
                    json.dump([], f, indent=2)

                await query.edit_message_text(
                    "✅ Система полностью очищена!\n\n"
                    "Удалено:\n"
                    "• Все бронирования",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Назад", callback_data="back_to_start")
                    ]])
                )

                logger.info(f"System cleared by admin {user_id}")

            except Exception as e:
                logger.error(f"Error clearing system: {e}")
                await query.edit_message_text(
                    "❌ Ошибка при очистке системы",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Назад", callback_data="back_to_start")
                    ]])
                )
        else:
            await query.edit_message_text("❌ Недостаточно прав")

    elif query.data == "cancel_admin" or query.data == "back_to_start":
        # Recreate the start message instead of calling start function
        first_name = query.from_user.first_name or "Пользователь"
        greeting = (
            f"👋 Здравствуйте, {first_name}!\n\n"
            f"🏢 Добро пожаловать в систему бронирования переговорных Sapa Group!\n\n"
            f"✨ Для доступа к системе нажмите кнопку ниже:"
        )

        if admin_level > 0:
            level_text = {3: "Главный администратор", 2: "Админ-модератор", 1: "Администратор"}
            greeting += f"\n\n👑 Ваш уровень: {level_text.get(admin_level, 'Администратор')}"

        # Create inline keyboard with Web App button
        webapp_url = f"https://test-85hz.onrender.com/telegram-auth?telegram_id={user_id}"
        logger.info(f"Generated webapp URL for user {user_id}: {webapp_url}")
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

        # Add system clear button for level 3 admins
        if admin_level >= 3:
            keyboard.append([InlineKeyboardButton("💥 Очистить систему", callback_data="clear_system")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(greeting, reply_markup=reply_markup, parse_mode='HTML')
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

def load_users():
    """Load users data from JSON file"""
    try:
        users_path = "data/users.json"
        with open(users_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def load_notifications():
    """Load notifications data from JSON file"""
    try:
        notifications_path = "data/notifications.json"
        with open(notifications_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_notifications(notifications):
    """Save notifications data to JSON file"""
    try:
        os.makedirs("data", exist_ok=True)
        notifications_path = "data/notifications.json"
        with open(notifications_path, 'w', encoding='utf-8') as f:
            json.dump(notifications, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Error saving notifications: {e}")
        return False

async def send_notification_to_users(message):
    """Send notification to all registered users"""
    try:
        users = load_users()
        sent_count = 0
        failed_count = 0
        
        for user_id, user_data in users.items():
            try:
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                data = {
                    'chat_id': int(user_id),
                    'text': message,
                    'parse_mode': 'HTML'
                }
                response = requests.post(url, json=data, timeout=10)
                if response.json().get('ok', False):
                    sent_count += 1
                    logger.info(f"Notification sent to user {user_id}")
                else:
                    failed_count += 1
                    logger.warning(f"Failed to send notification to user {user_id}")
            except Exception as e:
                failed_count += 1
                logger.error(f"Error sending notification to user {user_id}: {e}")
                
        logger.info(f"Notifications sent: {sent_count}, failed: {failed_count}")
        return sent_count, failed_count
    except Exception as e:
        logger.error(f"Error in send_notification_to_users: {e}")
        return 0, 0

async def schedule_notification(notification_data, app):
    """Schedule a notification to be sent at specified times"""
    try:
        message = notification_data['message']
        send_time = notification_data['notification_time']
        days_of_week = notification_data['days_of_week']
        repeat_count = notification_data.get('repeat_count', 1)
        weeks_count = notification_data.get('weeks_count', 1)
        
        # Convert day names to weekday numbers
        day_mapping = {
            'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
            'friday': 4, 'saturday': 5, 'sunday': 6
        }
        
        for week in range(weeks_count):
            for day_name in days_of_week:
                if day_name not in day_mapping:
                    continue
                    
                target_weekday = day_mapping[day_name]
                
                # Calculate target datetime
                now = datetime.now()
                days_ahead = target_weekday - now.weekday() + (week * 7)
                if days_ahead < 0:
                    days_ahead += 7
                    
                target_date = now + timedelta(days=days_ahead)
                send_hour, send_minute = map(int, send_time.split(':'))
                target_datetime = target_date.replace(hour=send_hour, minute=send_minute, second=0, microsecond=0)
                
                # Skip if time is in the past
                if target_datetime <= now:
                    continue
                
                # Schedule notification with repeats
                for repeat in range(repeat_count):
                    send_datetime = target_datetime + timedelta(minutes=repeat * 10)
                    delay = (send_datetime - now).total_seconds()
                    
                    if delay > 0:
                        # Schedule the notification
                        def create_notification_task(msg, delay_time, repeat_num):
                            async def send_delayed_notification():
                                await asyncio.sleep(delay_time)
                                sent_count, failed_count = await send_notification_to_users(msg)
                                logger.info(f"Scheduled notification sent (repeat {repeat_num + 1}): {sent_count} sent, {failed_count} failed")
                            return send_delayed_notification
                        
                        task = create_notification_task(message, delay, repeat)
                        asyncio.create_task(task())
                        
                        logger.info(f"Scheduled notification for {send_datetime} (repeat {repeat + 1})")
                        
    except Exception as e:
        logger.error(f"Error scheduling notification: {e}")

def start_notification_scheduler(app):
    """Start the notification scheduler in a separate thread"""
    def scheduler_thread():
        while True:
            try:
                notifications = load_notifications()
                active_notifications = [n for n in notifications if n.get('is_active', True)]
                
                for notification in active_notifications:
                    asyncio.run_coroutine_threadsafe(
                        schedule_notification(notification, app),
                        app._loop if hasattr(app, '_loop') else asyncio.get_event_loop()
                    )
                
                # Check every hour for new notifications
                time.sleep(3600)
            except Exception as e:
                logger.error(f"Error in notification scheduler: {e}")
                time.sleep(60)
    
    # Start scheduler thread
    scheduler = threading.Thread(target=scheduler_thread, daemon=True)
    scheduler.start()
    logger.info("Notification scheduler started")

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
            ADD_ADMIN_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_admin_id),
                CallbackQueryHandler(button_handler, pattern="^cancel_admin$")
            ],
            ADD_ADMIN_LEVEL: [
                CallbackQueryHandler(add_admin_level, pattern="^level_[123]$"),
                CallbackQueryHandler(button_handler, pattern="^cancel_admin$")
            ]
        },
        fallbacks=[
            CallbackQueryHandler(button_handler, pattern="^(cancel_admin|back_to_start)$"),
            CommandHandler("start", start)
        ]
    )

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(admin_conv_handler)
    application.add_handler(CallbackQueryHandler(button_handler))

    # Log bot startup
    logger.info("Starting Sapa Room Booking Bot with enhanced design...")

    # Start notification scheduler
    start_notification_scheduler(application)

    # Run the bot until the user presses Ctrl-C
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"Error running bot: {e}")
        raise

if __name__ == '__main__':
    main()