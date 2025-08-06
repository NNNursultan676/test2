import os
import logging
import requests
import asyncio
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ConversationHandler, ContextTypes, filters
from config import BOT_TOKEN, GROUP_ID
from admins import is_admin, add_admin, remove_admin, get_admins_list
from config import NOTIFICATION_THREAD_ID
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
                [InlineKeyboardButton("📋 Список админов", callback_data="list_admins")],
                [InlineKeyboardButton("🔔 Удалить все повторяющиеся уведомления", callback_data="clear_recurring_notifications")]
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

    elif query.data == "clear_recurring_notifications":
        if admin_level >= 2:
            # Clear all recurring notifications
            try:
                import json
                import os
                recurring_notifications_path = "data/recurring_notifications.json"
                os.makedirs(os.path.dirname(recurring_notifications_path), exist_ok=True)
                with open(recurring_notifications_path, 'w') as f:
                    json.dump([], f, indent=2)

                await query.edit_message_text(
                    "✅ Все повторяющиеся уведомления удалены",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Назад", callback_data="back_to_start")
                    ]])
                )
            except Exception as e:
                logger.error(f"Error clearing recurring notifications: {e}")
                await query.edit_message_text(
                    "❌ Ошибка при удалении уведомлений",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Назад", callback_data="back_to_start")
                    ]])
                )

    elif query.data == "clear_system":
        if admin_level >= 3:
            await query.edit_message_text(
                "⚠️ ВНИМАНИЕ! Это действие удалит:\n"
                "• Все бронирования\n"
                "• Все уведомления\n"
                "• Все повторяющиеся уведомления\n\n"
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

                # Clear notifications
                notifications_path = "data/notifications.json"
                os.makedirs(os.path.dirname(notifications_path), exist_ok=True)
                with open(notifications_path, 'w') as f:
                    json.dump([], f, indent=2)

                # Clear recurring notifications
                recurring_notifications_path = "data/recurring_notifications.json"
                os.makedirs(os.path.dirname(recurring_notifications_path), exist_ok=True)
                with open(recurring_notifications_path, 'w') as f:
                    json.dump([], f, indent=2)

                await query.edit_message_text(
                    "✅ Система полностью очищена!\n\n"
                    "Удалено:\n"
                    "• Все бронирования\n"
                    "• Все уведомления\n"
                    "• Все повторяющиеся уведомления",
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
            f"📱 Для доступа к системе нажмите кнопку ниже:"
        )

        if admin_level > 0:
            level_text = {3: "Главный администратор", 2: "Админ-модератор", 1: "Администратор"}
            greeting += f"\n\n👑 Ваш уровень: {level_text.get(admin_level, 'Администратор')}"

        # Create inline keyboard with Web App button
        webapp_url = f"https://test2-85hz.onrender.com/telegram-auth?telegram_id={user_id}"
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
                [InlineKeyboardButton("📋 Список админов", callback_data="list_admins")],
                [InlineKeyboardButton("🔔 Удалить все повторяющиеся уведомления", callback_data="clear_recurring_notifications")]
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

def load_recurring_notifications():
    """Load recurring notifications data from JSON file"""
    try:
        recurring_notifications_path = "data/recurring_notifications.json"
        with open(recurring_notifications_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_recurring_notifications(recurring_notifications):
    """Save recurring notifications data to JSON file"""
    try:
        recurring_notifications_path = "data/recurring_notifications.json"
        os.makedirs(os.path.dirname(recurring_notifications_path), exist_ok=True)
        with open(recurring_notifications_path, 'w') as f:
            json.dump(recurring_notifications, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving recurring notifications: {e}")
        return False

async def send_recurring_notification_to_group(message):
    """Send recurring notification to specific thread in Telegram group"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {
            'chat_id': '-1002723413852',
            'text': message,
            'parse_mode': 'HTML',
            'message_thread_id': 4
        }

        response = requests.post(url, json=data, timeout=10)
        result = response.json()
        logger.info(f"Sent recurring notification to group: {result.get('ok', False)} - Response: {result}")
        return result.get('ok', False)
    except Exception as e:
        logger.error(f"Error sending recurring notification to group: {e}")
        return False

async def process_recurring_notifications(context: ContextTypes.DEFAULT_TYPE):
    """Process and send recurring notifications"""
    try:
        now = datetime.now()
        current_time = now.time()
        current_day = now.strftime('%A').lower()

        # Map English day names to match what's stored in JSON
        day_mapping = {
            'monday': 'monday', 'tuesday': 'tuesday', 'wednesday': 'wednesday',
            'thursday': 'thursday', 'friday': 'friday', 'saturday': 'saturday', 'sunday': 'sunday'
        }

        recurring_notifications = load_recurring_notifications()
        regular_notifications = load_notifications()  # Load regular notifications too
        updated_recurring = False
        updated_regular = False

        # Process recurring notifications
        for notification in recurring_notifications:
            if not notification.get('is_active', True):
                continue

            # Check if it's the right day
            if current_day not in notification.get('days_of_week', []):
                continue

            # Check if it's the right time (within 2 minutes)
            notification_time = datetime.strptime(notification['notification_time'], '%H:%M').time()
            time_diff = abs((datetime.combine(datetime.today(), current_time) - 
                           datetime.combine(datetime.today(), notification_time)).total_seconds())

            if time_diff > 120:  # More than 2 minutes difference
                continue

            # Check if we need to send this notification
            sent_count = notification.get('sent_count', 0)
            repeat_count = notification.get('repeat_count', 1)

            if sent_count >= repeat_count:
                continue

            # Check interval (convert hours to seconds)
            last_sent = notification.get('last_sent')
            interval_hours = notification.get('repeat_interval', 24)
            interval_seconds = interval_hours * 3600

            if last_sent:
                last_sent_time = datetime.fromisoformat(last_sent)
                if (now - last_sent_time).total_seconds() < interval_seconds:
                    continue

            # Send notification
            success = await send_recurring_notification_to_group(notification['message'])

            if success:
                notification['sent_count'] = sent_count + 1
                notification['last_sent'] = now.isoformat()
                updated_recurring = True
                logger.info(f"Sent recurring notification {notification.get('id', 'unknown')}: {sent_count + 1}/{repeat_count}")

                # Deactivate if all repeats are done
                if notification['sent_count'] >= repeat_count:
                    notification['is_active'] = False
                    logger.info(f"Recurring notification {notification.get('id', 'unknown')} completed all repeats")

        # Process regular notifications (similar logic)
        for notification in regular_notifications:
            if not notification.get('is_active', True):
                continue

            # Check if it's the right day
            if current_day not in notification.get('days_of_week', []):
                continue

            # Check if it's the right time (within 2 minutes)
            notification_time = datetime.strptime(notification['notification_time'], '%H:%M').time()
            time_diff = abs((datetime.combine(datetime.today(), current_time) - 
                           datetime.combine(datetime.today(), notification_time)).total_seconds())

            if time_diff > 120:  # More than 2 minutes difference
                continue

            # Check if we need to send this notification
            sent_count = notification.get('sent_count', 0)
            repeat_count = notification.get('repeat_count', 1)

            if sent_count >= repeat_count:
                continue

            # Check interval
            last_sent = notification.get('last_sent')
            interval_hours = notification.get('repeat_interval', 24)
            interval_seconds = interval_hours * 3600

            if last_sent:
                last_sent_time = datetime.fromisoformat(last_sent)
                if (now - last_sent_time).total_seconds() < interval_seconds:
                    continue

            # Send notification to group using thread_id if specified
            thread_id = notification.get('thread_id', 4)
            success = await send_recurring_notification_to_group(notification['message'])

            if success:
                notification['sent_count'] = sent_count + 1
                notification['last_sent'] = now.isoformat()
                updated_regular = True
                logger.info(f"Sent regular notification {notification.get('id', 'unknown')}: {sent_count + 1}/{repeat_count}")

                # Deactivate if all repeats are done
                if notification['sent_count'] >= repeat_count:
                    notification['is_active'] = False
                    logger.info(f"Regular notification {notification.get('id', 'unknown')} completed all repeats")

        # Save updates
        if updated_recurring:
            save_recurring_notifications(recurring_notifications)
        if updated_regular:
            save_notifications(regular_notifications)

    except Exception as e:
        logger.error(f"Error processing recurring notifications: {e}")

def load_notifications():
    """Load notifications data from JSON file"""
    try:
        notifications_path = "data/notifications.json"
        with open(notifications_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_notifications(notifications):
    """Save notifications data to JSON file"""
    try:
        notifications_path = "data/notifications.json"
        os.makedirs(os.path.dirname(notifications_path), exist_ok=True)
        with open(notifications_path, 'w') as f:
            json.dump(notifications, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving notifications: {e}")
        return False

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

    # Add job queue for recurring notifications (check every minute)
    job_queue = application.job_queue
    job_queue.run_repeating(process_recurring_notifications, interval=60, first=10)

    # Log bot startup
    logger.info("Starting Sapa Room Booking Bot...")

    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()