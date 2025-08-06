import os
import json
import logging
import requests
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from werkzeug.middleware.proxy_fix import ProxyFix
from translations import get_translation, get_companies, TRANSLATIONS
from config import BOT_TOKEN, GROUP_ID, THREAD_ID, NOTIFICATION_THREAD_ID, USERS_JSON_PATH, BOOKINGS_JSON_PATH
from admins import is_admin

# Configure logging
logging.basicConfig(level=logging.DEBUG)

# Create the app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key-change-in-production")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

def load_rooms():
    """Load rooms data from JSON file"""
    try:
        # Use absolute path based on script location
        import os
        script_dir = os.path.dirname(os.path.abspath(__file__))
        rooms_path = os.path.join(script_dir, 'data', 'rooms.json')
        with open(rooms_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logging.error("Rooms data file not found")
        return []

def load_bookings():
    """Load bookings data from JSON file"""
    try:
        with open(BOOKINGS_JSON_PATH, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        logging.debug("Bookings file not found, creating empty bookings")
        return []

def save_bookings(bookings):
    """Save bookings data to JSON file"""
    try:
        os.makedirs(os.path.dirname(BOOKINGS_JSON_PATH), exist_ok=True)
        with open(BOOKINGS_JSON_PATH, 'w') as f:
            json.dump(bookings, f, indent=2)
        return True
    except Exception as e:
        logging.error(f"Error saving bookings: {e}")
        return False

def load_notifications():
    """Load notifications data from JSON file"""
    try:
        notifications_path = os.path.join(os.path.dirname(BOOKINGS_JSON_PATH), 'notifications.json')
        with open(notifications_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        logging.debug("Notifications file not found, creating empty notifications")
        return []

def save_notifications(notifications):
    """Save notifications data to JSON file"""
    try:
        notifications_path = os.path.join(os.path.dirname(BOOKINGS_JSON_PATH), 'notifications.json')
        os.makedirs(os.path.dirname(notifications_path), exist_ok=True)
        with open(notifications_path, 'w') as f:
            json.dump(notifications, f, indent=2)
        return True
    except Exception as e:
        logging.error(f"Error saving notifications: {e}")
        return False

def load_recurring_notifications():
    """Load recurring notifications data from JSON file"""
    try:
        recurring_notifications_path = os.path.join(os.path.dirname(BOOKINGS_JSON_PATH), 'recurring_notifications.json')
        with open(recurring_notifications_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        logging.debug("Recurring notifications file not found, creating empty recurring notifications")
        return []

def save_recurring_notifications(recurring_notifications):
    """Save recurring notifications data to JSON file"""
    try:
        recurring_notifications_path = os.path.join(os.path.dirname(BOOKINGS_JSON_PATH), 'recurring_notifications.json')
        os.makedirs(os.path.dirname(recurring_notifications_path), exist_ok=True)
        with open(recurring_notifications_path, 'w') as f:
            json.dump(recurring_notifications, f, indent=2)
        return True
    except Exception as e:
        logging.error(f"Error saving recurring notifications: {e}")
        return False

def clear_all_system_data():
    """Clear all bookings and notifications (only for level 3 admins)"""
    try:
        # Clear bookings
        if save_bookings([]):
            logging.info("All bookings cleared")

        # Clear notifications
        if save_notifications([]):
            logging.info("All notifications cleared")

        # Clear recurring notifications
        if save_recurring_notifications([]):
            logging.info("All recurring notifications cleared")

        return True
    except Exception as e:
        logging.error(f"Error clearing system data: {e}")
        return False

def send_telegram_notification(user_id, message):
    """Send notification to user via Telegram bot"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {
            'chat_id': user_id,
            'text': message,
            'parse_mode': 'HTML'
        }
        response = requests.post(url, json=data, timeout=10)
        return response.json().get('ok', False)
    except Exception as e:
        logging.error(f"Error sending Telegram notification: {e}")
        return False

def send_group_notification(message, thread_id=None):
    """Send notification to Telegram group"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {
            'chat_id': GROUP_ID,
            'text': message,
            'parse_mode': 'HTML'
        }
        # Use default thread ID if none provided
        if thread_id is None:
            thread_id = THREAD_ID
        if thread_id:
            data['message_thread_id'] = thread_id
        response = requests.post(url, json=data, timeout=10)
        return response.json().get('ok', False)
    except Exception as e:
        logging.error(f"Error sending group notification: {e}")
        return False

def send_recurring_notification_to_group(message):
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
        logging.info(f"Sent recurring notification to group: {result.get('ok', False)} - Response: {result}")
        return result.get('ok', False)
    except Exception as e:
        logging.error(f"Error sending recurring notification to group: {e}")
        return False

def create_recurring_bookings(base_booking, days_of_week, weeks_count):
    """Create recurring bookings for specified days and weeks"""
    bookings = load_bookings()
    new_bookings = []

    base_date = datetime.strptime(base_booking['date'], '%Y-%m-%d').date()

    for week in range(weeks_count):
        for day_offset in days_of_week:
            # Calculate the date for this occurrence
            current_date = base_date + timedelta(days=day_offset + (week * 7))
            date_str = current_date.strftime('%Y-%m-%d')

            # Skip if date is in the past
            if current_date < datetime.now().date():
                continue

            # Check if room is available for this time slot
            if is_room_available(base_booking['room_id'], date_str, 
                               base_booking['start_time'], base_booking['end_time']):

                recurring_booking = base_booking.copy()
                recurring_booking.update({
                    'id': len(bookings) + len(new_bookings) + 1,
                    'date': date_str,
                    'is_recurring': True,
                    'parent_booking_id': base_booking.get('id'),
                    'created_at': datetime.now().isoformat()
                })
                new_bookings.append(recurring_booking)

    return new_bookings

def load_users():
    """Load users data from JSON file"""
    try:
        with open(USERS_JSON_PATH, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        logging.debug("Users file not found, creating empty users")
        return {}

def save_users(users):
    """Save users data to JSON file"""
    try:
        os.makedirs(os.path.dirname(USERS_JSON_PATH), exist_ok=True)
        with open(USERS_JSON_PATH, 'w') as f:
            json.dump(users, f, indent=2)
        return True
    except Exception as e:
        logging.error(f"Error saving users: {e}")
        return False

def check_telegram_group_membership(user_id):
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
        logging.error(f"Error checking Telegram group membership: {e}")
        return False

def login_required(f):
    """Decorator to require authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('telegram_id'):
            flash(get_translation(session.get('lang', 'ru'), 'auth_required', 'Авторизуйтесь через Telegram, чтобы продолжить'), 'warning')
            return redirect(url_for('telegram_auth'))
        return f(*args, **kwargs)
    return decorated_function

def get_user_lang():
    """Get user's preferred language"""
    return session.get('lang', 'ru')

def is_user_registered():
    """Check if current user is registered"""
    telegram_id = session.get('telegram_id')
    if not telegram_id:
        return False

    users = load_users()
    return str(telegram_id) in users

def is_room_available(room_id, date, start_time, end_time):
    """Check if a room is available for the given time slot"""
    bookings = load_bookings()

    for booking in bookings:
        if (booking['room_id'] == room_id and 
            booking['date'] == date and
            booking['status'] == 'confirmed'):

            # Check for time overlap
            booking_start = datetime.strptime(booking['start_time'], '%H:%M').time()
            booking_end = datetime.strptime(booking['end_time'], '%H:%M').time()
            slot_start = datetime.strptime(start_time, '%H:%M').time()
            slot_end = datetime.strptime(end_time, '%H:%M').time()

            # Check if there's any overlap
            if not (slot_end <= booking_start or slot_start >= booking_end):
                return False

    return True

def is_booking_time_valid(date, start_time, end_time):
    """Validate booking time restrictions"""
    now = datetime.now()

    try:
        # Parse booking date and time
        booking_date = datetime.strptime(date, '%Y-%m-%d').date()
        booking_start_time = datetime.strptime(start_time, '%H:%M').time()
        booking_end_time = datetime.strptime(end_time, '%H:%M').time()
    except ValueError:
        return False, 'invalid_time'

    # Create full datetime objects
    booking_datetime = datetime.combine(booking_date, booking_start_time)

    # More strict past time check - add 1 minute buffer to current time
    current_time_with_buffer = now + timedelta(minutes=1)

    # Check if booking is in the past (with buffer)
    if booking_datetime <= current_time_with_buffer:
        return False, 'cannot_book_past_time'

    # Additional check for today's date
    if booking_date == now.date():
        current_time = now.time()
        current_hour = now.hour
        current_minute = now.minute
        start_hour = booking_start_time.hour
        start_minute = booking_start_time.minute

        # If it's the same hour, check minutes more strictly
        if start_hour == current_hour and start_minute <= current_minute + 1:
            return False, 'cannot_book_past_time'
        elif start_hour < current_hour:
            return False, 'cannot_book_past_time'

    # Check working hours (9:00 - 18:00)
    start_hour = booking_start_time.hour
    end_hour = booking_end_time.hour
    start_minute = booking_start_time.minute
    end_minute = booking_end_time.minute

    # Start time must be between 9:00 and 17:45
    if start_hour < 9 or (start_hour == 17 and start_minute > 45) or start_hour >= 18:
        return False, 'outside_working_hours'

    # End time must be between 9:15 and 18:00 (18:01 allowed for form validation)
    if end_hour < 9 or (end_hour == 9 and end_minute < 15) or end_hour > 18 or (end_hour == 18 and end_minute > 1):
        return False, 'outside_working_hours'

    # End time must be after start time
    if booking_end_time <= booking_start_time:
        return False, 'invalid_time'

    return True, None

def get_room_status(room_id):
    """Get current status of a room (available/occupied)"""
    from datetime import timezone, timedelta

    # Use Kazakhstan time (UTC+5)
    kz_timezone = timezone(timedelta(hours=5))
    now = datetime.now(kz_timezone)
    current_date = now.strftime('%Y-%m-%d')
    current_time = now.time()

    bookings = load_bookings()

    logging.debug(f"Checking room {room_id} status at {current_time.strftime('%H:%M:%S')} on {current_date} (Kazakhstan time UTC+5)")

    # Check all bookings for today
    for booking in bookings:
        if (booking['room_id'] == room_id and 
            booking['date'] == current_date and
            booking['status'] == 'confirmed'):

            try:
                # Parse booking times
                booking_start = datetime.strptime(booking['start_time'], '%H:%M').time()
                booking_end = datetime.strptime(booking['end_time'], '%H:%M').time()

                logging.debug(f"Found booking {booking_start.strftime('%H:%M')} - {booking_end.strftime('%H:%M')} by {booking.get('user_name', 'Unknown')}")

                # Convert times to minutes for easier comparison
                current_minutes = current_time.hour * 60 + current_time.minute
                start_minutes = booking_start.hour * 60 + booking_start.minute
                end_minutes = booking_end.hour * 60 + booking_end.minute

                # Check if current time is within booking period (inclusive of start, exclusive of end)
                if start_minutes <= current_minutes < end_minutes:
                    logging.debug(f"Room is OCCUPIED - Current time {current_time.strftime('%H:%M')} is within booking {booking_start.strftime('%H:%M')}-{booking_end.strftime('%H:%M')} by {booking.get('user_name', 'Unknown')}")
                    return 'occupied'

            except ValueError as e:
                logging.error(f"Invalid time format in booking: {booking} - Error: {e}")
                continue

    logging.debug(f"Room is AVAILABLE - No active bookings at current time")
    return 'available'

@app.context_processor
def inject_globals():
    """Inject global template variables"""
    lang = get_user_lang()
    telegram_id = session.get('telegram_id')
    user_data = None
    admin_level = 0

    if telegram_id:
        users = load_users()
        user_data = users.get(str(telegram_id))
        admin_level = is_admin(telegram_id)

    def get_room_name(room, lang='ru'):
        """Get localized room name"""
        if 'name_translations' in room and lang in room['name_translations']:
            return room['name_translations'][lang]
        return room['name']

    def get_room_location(room, lang='ru'):
        """Get localized room location"""
        if 'location_translations' in room and lang in room['location_translations']:
            return room['location_translations'][lang]
        return room.get('location', '')

    return {
        'get_translation': lambda key, default=None: get_translation(lang, key, default),
        'get_room_name': get_room_name,
        'get_room_location': get_room_location,
        'lang': lang,
        'companies': get_companies(),
        'user_name': user_data.get('name') if user_data else None,
        'user_company': user_data.get('company') if user_data else None,
        'is_registered': is_user_registered(),
        'telegram_id': telegram_id,
        'admin_level': admin_level
    }

@app.route('/telegram-auth')
def telegram_auth():
    """Telegram authentication page"""
    # Set default language if not selected
    if 'lang' not in session:
        session['lang'] = 'ru'

    # Check if telegram_id is provided in URL parameters (from Telegram WebApp)
    telegram_id = request.args.get('telegram_id')

    if telegram_id:
        try:
            telegram_id = int(telegram_id)  # Validate that it's a number
            logging.info(f"Telegram ID received: {telegram_id}")

            # Check if user is a member of the Telegram group
            if check_telegram_group_membership(telegram_id):
                session['telegram_id'] = telegram_id
                logging.info(f"User {telegram_id} authenticated successfully")

                # Check if user is already registered
                if is_user_registered():
                    return redirect(url_for('index'))
                else:
                    return redirect(url_for('register'))
            else:
                logging.warning(f"User {telegram_id} is not a member of the group")
                flash(get_translation(session.get('lang', 'ru'), 'access_denied', 'Доступ запрещен. Вы не являетесь участником группы.'), 'error')
        except (ValueError, TypeError):
            logging.error(f"Invalid Telegram ID format: {telegram_id}")
            flash(get_translation(session.get('lang', 'ru'), 'invalid_telegram_id', 'Неверный формат Telegram ID'), 'error')
    else:
        logging.info("No Telegram ID provided in request")

    return render_template('telegram_auth.html')

@app.route('/set_language/<lang>')
def set_language(lang):
    """Set user's preferred language"""
    if lang in TRANSLATIONS:
        session['lang'] = lang
    # If coming from language selection, go to authentication
    if request.referrer and 'language' in request.referrer:
        return redirect(url_for('telegram_auth'))
    return redirect(request.referrer or url_for('index'))

@app.route('/')
@login_required
def index():
    """Main page showing room availability"""
    # Check if user is registered, if not redirect to registration
    if not is_user_registered():
        return redirect(url_for('register'))

    rooms = load_rooms()

    # Add current status to each room
    for room in rooms:
        room['current_status'] = get_room_status(room['id'])

    today = datetime.now().strftime('%Y-%m-%d')
    return render_template('index.html', rooms=rooms, today=today)

@app.route('/register', methods=['GET', 'POST'])
@login_required
def register():
    """User registration page"""
    telegram_id = session.get('telegram_id')
    if not telegram_id:
        return redirect(url_for('telegram_auth'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        company = request.form.get('company', '').strip()
        lang = session.get('lang', 'ru')

        if not name:
            flash(get_translation(lang, 'name_required'), 'error')
            return render_template('register.html')

        if not company:
            flash(get_translation(lang, 'company_required'), 'error')
            return render_template('register.html')

        # Save user info to JSON file
        users = load_users()
        users[str(telegram_id)] = {
            'telegram_id': telegram_id,
            'name': name,
            'company': company,
            'registered_at': datetime.now().isoformat()
        }

        if save_users(users):
            flash(get_translation(lang, 'registration_successful', 'Регистрация успешна'), 'success')
            return redirect(url_for('index'))
        else:
            flash(get_translation(lang, 'registration_error', 'Ошибка регистрации'), 'error')

    return render_template('register.html')

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """User profile page"""
    if not is_user_registered():
        return redirect(url_for('register'))

    telegram_id = session.get('telegram_id')
    users = load_users()
    user_data = users.get(str(telegram_id))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        company = request.form.get('company', '').strip()

        if name and company:
            users[str(telegram_id)].update({
                'name': name,
                'company': company,
                'updated_at': datetime.now().isoformat()
            })

            if save_users(users):
                flash(get_translation(get_user_lang(), 'profile_updated', 'Profile updated successfully'), 'success')

    return render_template('profile.html', user_data=user_data)

@app.route('/book/<int:room_id>')
@login_required
def book_room(room_id):
    """Room booking page"""
    if not is_user_registered():
        return redirect(url_for('register'))

    rooms = load_rooms()
    room = next((r for r in rooms if r['id'] == room_id), None)

    if not room:
        flash(get_translation(get_user_lang(), 'room_not_found', 'Room not found'), 'error')
        return redirect(url_for('index'))

    today = datetime.now().strftime('%Y-%m-%d')
    return render_template('book_room.html', room=room, today=today)

@app.route('/book/<int:room_id>', methods=['POST'])
@login_required
def process_booking(room_id):
    """Process room booking form submission"""
    if not is_user_registered():
        return redirect(url_for('register'))

    rooms = load_rooms()
    room = next((r for r in rooms if r['id'] == room_id), None)
    lang = get_user_lang()

    if not room:
        flash(get_translation(lang, 'room_not_found', 'Room not found'), 'error')
        return redirect(url_for('index'))

    # Get form data
    date = request.form.get('date')
    start_time = request.form.get('start_time')
    end_time = request.form.get('end_time')
    purpose = request.form.get('purpose', '')

    # Get user data
    telegram_id = session.get('telegram_id')
    users = load_users()
    user_data = users.get(str(telegram_id))

    # Validate form data
    if not all([date, start_time, end_time]):
        flash(get_translation(lang, 'fill_required_fields', 'Please fill in all required fields'), 'error')
        return render_template('book_room.html', room=room, today=datetime.now().strftime('%Y-%m-%d'))

    # Validate time restrictions
    time_valid, error_key = is_booking_time_valid(date, start_time, end_time)
    if not time_valid:
        flash(get_translation(lang, error_key), 'error')
        return render_template('book_room.html', room=room, today=datetime.now().strftime('%Y-%m-%d'))

    # Validate time range
    if start_time and end_time:
        start_dt = datetime.strptime(start_time, '%H:%M').time()
        end_dt = datetime.strptime(end_time, '%H:%M').time()

        if start_dt >= end_dt:
            flash(get_translation(lang, 'invalid_time'), 'error')
            return render_template('book_room.html', room=room, today=datetime.now().strftime('%Y-%m-%d'))

    # Check availability
    if not is_room_available(room_id, date, start_time, end_time):
        flash(get_translation(lang, 'room_unavailable'), 'error')
        return render_template('book_room.html', room=room, today=datetime.now().strftime('%Y-%m-%d'))

    # Create booking
    bookings = load_bookings()
    new_booking = {
        'id': len(bookings) + 1,
        'room_id': room_id,
        'room_name': room['name'],
        'date': date,
        'start_time': start_time,
        'end_time': end_time,
        'telegram_id': telegram_id,
        'user_name': user_data.get('name'),
        'user_company': user_data.get('company'),
        'purpose': purpose,
        'status': 'confirmed',
        'created_at': datetime.now().isoformat()
    }

    bookings.append(new_booking)

    if save_bookings(bookings):
        flash(get_translation(lang, 'booking_successful'), 'success')
        # Redirect to schedule to show the booking
        return redirect(url_for('room_schedule', room_id=room_id, date=date))
    else:
        flash(get_translation(lang, 'booking_error'), 'error')
        return render_template('book_room.html', room=room, today=datetime.now().strftime('%Y-%m-%d'))

@app.route('/api/room-availability/<int:room_id>')
@login_required
def room_availability_api(room_id):
    """API endpoint for checking room availability"""
    date = request.args.get('date')
    if not date:
        return jsonify({'error': 'Date parameter required'}), 400

    bookings = load_bookings()
    room_bookings = [b for b in bookings if b['room_id'] == room_id and b['date'] == date and b['status'] == 'confirmed']

    occupied_slots = []
    for booking in room_bookings:
        occupied_slots.append({
            'start': booking['start_time'],
            'end': booking['end_time'],
            'user': booking['user_name'],
            'purpose': booking.get('purpose', '')
        })

    return jsonify({'occupied_slots': occupied_slots})

@app.route('/schedule/<int:room_id>')
@login_required
def room_schedule(room_id):
    """Show room schedule for a specific date"""
    if not is_user_registered():
        return redirect(url_for('register'))

    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    rooms = load_rooms()
    room = next((r for r in rooms if r['id'] == room_id), None)

    if not room:
        flash(get_translation(get_user_lang(), 'room_not_found', 'Room not found'), 'error')
        return redirect(url_for('index'))

    bookings = load_bookings()
    room_bookings = [b for b in bookings if b['room_id'] == room_id and b['date'] == date and b['status'] == 'confirmed']
    room_bookings.sort(key=lambda x: x['start_time'])

    return render_template('schedule.html', room=room, bookings=room_bookings, selected_date=date)

@app.route('/api/schedule/<int:room_id>')
@login_required
def api_room_schedule(room_id):
    """API endpoint for room schedule"""
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    bookings = load_bookings()
    room_bookings = [b for b in bookings if b['room_id'] == room_id and b['date'] == date and b['status'] == 'confirmed']
    room_bookings.sort(key=lambda x: x['start_time'])

    return jsonify({'bookings': room_bookings})

@app.route('/my-bookings')
@login_required
def my_bookings():
    """Show user's bookings"""
    if not is_user_registered():
        return redirect(url_for('register'))

    telegram_id = session.get('telegram_id')
    bookings = load_bookings()
    user_bookings = [b for b in bookings if str(b.get('telegram_id')) == str(telegram_id)]

    # Sort by date and time
    user_bookings.sort(key=lambda x: (x['date'], x['start_time']))

    # Add room names
    rooms = load_rooms()
    room_names = {room['id']: room['name'] for room in rooms}

    for booking in user_bookings:
        booking['room_name'] = room_names.get(booking['room_id'], f"Room {booking['room_id']}")

    today = datetime.now().strftime('%Y-%m-%d')
    return render_template('my_bookings.html', bookings=user_bookings, today=today)

@app.route('/delete-booking/<int:booking_id>', methods=['POST'])
@login_required
def delete_booking(booking_id):
    """Delete a booking"""
    if not is_user_registered():
        return redirect(url_for('register'))

    telegram_id = session.get('telegram_id')
    admin_level = is_admin(telegram_id)
    reason = request.form.get('admin_reason', '').strip()

    # If admin is deleting someone else's booking, reason is required
    bookings = load_bookings()
    booking_to_delete = None
    target_booking = None

    for i, booking in enumerate(bookings):
        if booking['id'] == booking_id:
            # Check if user owns booking or is admin
            if str(booking.get('telegram_id')) == str(telegram_id):
                # User deleting their own booking
                booking_to_delete = i
                target_booking = booking
                break
            elif admin_level > 0:
                # Admin deleting someone else's booking
                if not reason:
                    flash('Администратор должен указать причину удаления бронирования', 'error')
                    return redirect(request.referrer or url_for('my_bookings'))
                booking_to_delete = i
                target_booking = booking
                break

    if booking_to_delete is not None:
        deleted_booking = bookings.pop(booking_to_delete)

        if save_bookings(bookings):
            # Send notification to user if admin deleted their booking
            if admin_level > 0 and str(deleted_booking.get('telegram_id')) != str(telegram_id):
                users = load_users()
                admin_data = users.get(str(telegram_id))
                admin_name = admin_data.get('name', 'Администратор') if admin_data else 'Администратор'

                notification_message = (
                    f"🗑 <b>Ваше бронирование было удалено</b>\n\n"
                    f"📅 Дата: {deleted_booking['date']}\n"
                    f"🕐 Время: {deleted_booking['start_time']} - {deleted_booking['end_time']}\n"
                    f"🏢 Комната: {deleted_booking['room_name']}\n"
                    f"👤 Удалил: {admin_name}\n"
                    f"📝 Причина: {reason}\n\n"
                    f"По вопросам обращайтесь к администратору."
                )

                send_telegram_notification(deleted_booking.get('telegram_id'), notification_message)

            flash(get_translation(get_user_lang(), 'booking_deleted', 'Booking deleted successfully'), 'success')
        else:
            flash(get_translation(get_user_lang(), 'delete_error', 'Error deleting booking'), 'error')
    else:
        flash(get_translation(get_user_lang(), 'booking_not_found', 'Booking not found'), 'error')

    # Redirect based on context
    if request.referrer and 'schedule' in request.referrer:
        room_id = deleted_booking.get('room_id') if booking_to_delete is not None else None
        date = deleted_booking.get('date') if booking_to_delete is not None else None
        if room_id and date:
            return redirect(url_for('room_schedule', room_id=room_id, date=date))

    return redirect(url_for('my_bookings'))

@app.route('/edit-booking/<int:booking_id>')
@login_required
def edit_booking(booking_id):
    """Edit booking page"""
    if not is_user_registered():
        return redirect(url_for('register'))

    telegram_id = session.get('telegram_id')
    admin_level = is_admin(telegram_id)
    bookings = load_bookings()
    booking = None

    for b in bookings:
        # Allow editing if user owns booking or is admin
        if (b['id'] == booking_id and 
            (str(b.get('telegram_id')) == str(telegram_id) or admin_level > 0)):
            booking = b
            break

    if not booking:
        flash(get_translation(get_user_lang(), 'booking_not_found', 'Booking not found'), 'error')
        return redirect(url_for('my_bookings'))

    rooms = load_rooms()
    room = next((r for r in rooms if r['id'] == booking['room_id']), None)

    if not room:
        flash(get_translation(get_user_lang(), 'room_not_found', 'Room not found'), 'error')
        return redirect(url_for('my_bookings'))

    return render_template('edit_booking.html', booking=booking, room=room)

@app.route('/edit-booking/<int:booking_id>', methods=['POST'])
@login_required
def update_booking(booking_id):
    """Update booking"""
    if not is_user_registered():
        return redirect(url_for('register'))

    telegram_id = session.get('telegram_id')
    admin_level = is_admin(telegram_id)
    lang = get_user_lang()

    bookings = load_bookings()
    booking_index = None
    original_booking = None

    for i, b in enumerate(bookings):
        # Allow updating if user owns booking or is admin
        if (b['id'] == booking_id and 
            (str(b.get('telegram_id')) == str(telegram_id) or admin_level > 0)):
            booking_index = i
            original_booking = b
            break

    if booking_index is None:
        flash(get_translation(lang, 'booking_not_found', 'Booking not found'), 'error')
        return redirect(url_for('my_bookings'))

    # Get form data
    date = request.form.get('date')
    start_time = request.form.get('start_time')
    end_time = request.form.get('end_time')
    purpose = request.form.get('purpose', '')
    admin_reason = request.form.get('admin_reason', '') if admin_level > 0 else original_booking.get('admin_reason', '')

    # If admin is editing someone else's booking, reason is required
    if admin_level > 0 and str(original_booking.get('telegram_id')) != str(telegram_id):
        if not admin_reason.strip():
            flash('Администратор должен указать причину изменения бронирования', 'error')
            return redirect(url_for('edit_booking', booking_id=booking_id))

    # Validate form data
    if not all([date, start_time, end_time]):
        flash(get_translation(lang, 'fill_required_fields', 'Please fill in all required fields'), 'error')
        return redirect(url_for('edit_booking', booking_id=booking_id))

    # Validate time restrictions
    time_valid, error_key = is_booking_time_valid(date, start_time, end_time)
    if not time_valid:
        flash(get_translation(lang, error_key), 'error')
        return redirect(url_for('edit_booking', booking_id=booking_id))

    # Validate time range
    if start_time >= end_time:
        flash(get_translation(lang, 'invalid_time'), 'error')
        return redirect(url_for('edit_booking', booking_id=booking_id))

    # Check availability (exclude current booking)
    temp_bookings = [b for b in bookings if b['id'] != booking_id]
    room_id = original_booking['room_id']

    for booking in temp_bookings:
        if (booking['room_id'] == room_id and 
            booking['date'] == date and
            booking['status'] == 'confirmed'):

            # Check for time overlap
            booking_start = datetime.strptime(booking['start_time'], '%H:%M').time()
            booking_end = datetime.strptime(booking['end_time'], '%H:%M').time()
            slot_start = datetime.strptime(start_time, '%H:%M').time()
            slot_end = datetime.strptime(end_time, '%H:%M').time()

            if not (slot_end <= booking_start or slot_start >= booking_end):
                flash(get_translation(lang, 'room_unavailable'), 'error')
                return redirect(url_for('edit_booking', booking_id=booking_id))

    # Update booking
    bookings[booking_index].update({
        'date': date,
        'start_time': start_time,
        'end_time': end_time,
        'purpose': purpose,
        'admin_reason': admin_reason,
        'updated_at': datetime.now().isoformat()
    })

    if save_bookings(bookings):
        # Send notification to user if admin modified their booking
        if admin_level > 0 and str(original_booking.get('telegram_id')) != str(telegram_id):
            users = load_users()
            admin_data = users.get(str(telegram_id))
            admin_name = admin_data.get('name', 'Администратор') if admin_data else 'Администратор'
            edit_reason = admin_reason if admin_reason else 'Причина не указана'

            notification_message = (
                f"✏️ <b>Ваше бронирование было изменено</b>\n\n"
                f"🏢 Комната: {original_booking['room_name']}\n\n"
                f"📅 Старая дата: {original_booking['date']}\n"
                f"🕐 Старое время: {original_booking['start_time']} - {original_booking['end_time']}\n\n"
                f"📅 Новая дата: {date}\n"
                f"🕐 Новое время: {start_time} - {end_time}\n\n"
                f"👤 Изменил: {admin_name}\n"
                f"📝 Причина: {edit_reason}\n\n"
                f"По вопросам обращайтесь к администратору."
            )

            send_telegram_notification(original_booking.get('telegram_id'), notification_message)

        flash(get_translation(lang, 'booking_updated', 'Booking updated successfully'), 'success')
        # Redirect based on context
        if request.referrer and 'schedule' in request.referrer:
            return redirect(url_for('room_schedule', room_id=original_booking['room_id'], date=date))
        return redirect(url_for('my_bookings'))
    else:
        flash(get_translation(lang, 'update_error', 'Error updating booking'), 'error')
        return redirect(url_for('edit_booking', booking_id=booking_id))

@app.route('/api/room-status')
@login_required
def api_room_status():
    """API endpoint for getting all room statuses"""
    rooms = load_rooms()
    room_statuses = {}

    for room in rooms:
        room_statuses[room['id']] = get_room_status(room['id'])

    return jsonify(room_statuses)

@app.route('/admin/recurring-booking/<int:room_id>')
@login_required
def recurring_booking(room_id):
    """Recurring booking page for admins"""
    telegram_id = session.get('telegram_id')
    admin_level = is_admin(telegram_id)

    if admin_level == 0:
        flash(get_translation(get_user_lang(), 'admin_only', 'Admin access required'), 'error')
        return redirect(url_for('index'))

    rooms = load_rooms()
    room = next((r for r in rooms if r['id'] == room_id), None)

    if not room:
        flash(get_translation(get_user_lang(), 'room_not_found', 'Room not found'), 'error')
        return redirect(url_for('index'))

    today = datetime.now().strftime('%Y-%m-%d')
    return render_template('recurring_booking.html', room=room, today=today)

@app.route('/admin/recurring-booking/<int:room_id>', methods=['POST'])
@login_required
def process_recurring_booking(room_id):
    """Process recurring booking form submission"""
    telegram_id = session.get('telegram_id')
    admin_level = is_admin(telegram_id)
    lang = get_user_lang()

    if admin_level == 0:
        flash(get_translation(lang, 'admin_only', 'Admin access required'), 'error')
        return redirect(url_for('index'))

    # Get form data
    start_date = request.form.get('start_date')
    start_time = request.form.get('start_time')
    end_time = request.form.get('end_time')
    purpose = request.form.get('purpose', '')
    days_of_week = request.form.getlist('days_of_week')
    weeks_count = int(request.form.get('weeks_count', 1))

    # Validate form data
    if not all([start_date, start_time, end_time, days_of_week]):
        flash(get_translation(lang, 'fill_required_fields'), 'error')
        return redirect(url_for('recurring_booking', room_id=room_id))

    # Get user data
    users = load_users()
    user_data = users.get(str(telegram_id))

    # Create base booking
    base_booking = {
        'room_id': room_id,
        'room_name': next((r['name'] for r in load_rooms() if r['id'] == room_id), f'Room {room_id}'),
        'date': start_date,
        'start_time': start_time,
        'end_time': end_time,
        'telegram_id': telegram_id,
        'user_name': user_data.get('name'),
        'user_company': user_data.get('company'),
        'purpose': purpose,
        'status': 'confirmed',
        'is_recurring': True,
        'created_by_admin': admin_level
    }

    # Convert day names to day offsets
    day_mapping = {
        'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
        'friday': 4, 'saturday': 5, 'sunday': 6
    }
    day_offsets = [day_mapping[day] for day in days_of_week if day in day_mapping]

    # Create recurring bookings
    new_bookings = create_recurring_bookings(base_booking, day_offsets, weeks_count)

    if new_bookings:
        bookings = load_bookings()
        bookings.extend(new_bookings)

        if save_bookings(bookings):
            flash(f'{len(new_bookings)} повторяющихся бронирований создано успешно', 'success')
            return redirect(url_for('index'))
        else:
            flash(get_translation(lang, 'booking_error'), 'error')
    else:
        flash('Не удалось создать повторяющиеся бронирования. Проверьте доступность комнат.', 'warning')

    return redirect(url_for('recurring_booking', room_id=room_id))

@app.route('/admin/notifications')
@login_required
def manage_notifications():
    """Manage notifications page for admins"""
    telegram_id = session.get('telegram_id')
    admin_level = is_admin(telegram_id)

    if admin_level == 0:
        flash(get_translation(get_user_lang(), 'admin_only', 'Admin access required'), 'error')
        return redirect(url_for('index'))

    notifications = load_notifications()
    return render_template('manage_notifications.html', notifications=notifications)

@app.route('/admin/notifications', methods=['POST'])
@login_required
def create_notification():
    """Create a new notification"""
    telegram_id = session.get('telegram_id')
    admin_level = is_admin(telegram_id)
    lang = get_user_lang()

    if admin_level == 0:
        flash(get_translation(lang, 'admin_only', 'Admin access required'), 'error')
        return redirect(url_for('index'))

    # Get form data
    message = request.form.get('message', '').strip()
    days_of_week = request.form.getlist('days_of_week')
    notification_time = request.form.get('notification_time')
    weeks_count = int(request.form.get('weeks_count', 1))
    repeat_count = int(request.form.get('repeat_count', 1))
    repeat_interval = int(request.form.get('repeat_interval', 1))  # hours
    thread_id = request.form.get('thread_id', '')

    if not all([message, days_of_week, notification_time]):
        flash('Заполните все обязательные поля', 'error')
        return redirect(url_for('manage_notifications'))

    users = load_users()
    user_data = users.get(str(telegram_id))

    # Create notification
    notifications = load_notifications()
    new_notification = {
        'id': len(notifications) + 1,
        'message': message,
        'days_of_week': days_of_week,
        'notification_time': notification_time,
        'weeks_count': weeks_count,
        'repeat_count': repeat_count,
        'repeat_interval': repeat_interval,
        'thread_id': thread_id if thread_id else None,
        'created_by': user_data.get('name'),
        'created_by_id': telegram_id,
        'created_at': datetime.now().isoformat(),
        'is_active': True
    }

    notifications.append(new_notification)

    if save_notifications(notifications):
        flash('Уведомление создано успешно', 'success')
    else:
        flash('Ошибка при создании уведомления', 'error')

    return redirect(url_for('manage_notifications'))

@app.route('/admin/notifications/update', methods=['POST'])
@login_required
def update_notification():
    """Update a notification"""
    telegram_id = session.get('telegram_id')
    admin_level = is_admin(telegram_id)

    if admin_level == 0:
        flash(get_translation(get_user_lang(), 'admin_only', 'Admin access required'), 'error')
        return redirect(url_for('index'))

    notification_id = int(request.form.get('notification_id'))
    message = request.form.get('message', '').strip()
    days_of_week = request.form.getlist('days_of_week')
    notification_time = request.form.get('notification_time')
    weeks_count = int(request.form.get('weeks_count', 1))
    repeat_count = int(request.form.get('repeat_count', 1))
    repeat_interval = int(request.form.get('repeat_interval', 1))

    if not all([message, days_of_week, notification_time]):
        flash('Заполните все обязательные поля', 'error')
        return redirect(url_for('manage_notifications'))

    notifications = load_notifications()
    for notification in notifications:
        if notification['id'] == notification_id:
            notification.update({
                'message': message,
                'days_of_week': days_of_week,
                'notification_time': notification_time,
                'weeks_count': weeks_count,
                'repeat_count': repeat_count,
                'repeat_interval': repeat_interval,
                'updated_at': datetime.now().isoformat()
            })
            break

    if save_notifications(notifications):
        flash('Уведомление обновлено успешно', 'success')
    else:
        flash('Ошибка при обновлении уведомления', 'error')

    return redirect(url_for('manage_notifications'))

@app.route('/admin/notifications/<int:notification_id>/delete', methods=['POST'])
@login_required
def delete_notification(notification_id):
    """Delete a notification"""
    telegram_id = session.get('telegram_id')
    admin_level = is_admin(telegram_id)

    if admin_level == 0:
        flash(get_translation(get_user_lang(), 'admin_only', 'Admin access required'), 'error')
        return redirect(url_for('index'))

    notifications = load_notifications()
    notifications = [n for n in notifications if n['id'] != notification_id]

    if save_notifications(notifications):
        flash('Уведомление удалено', 'success')
    else:
        flash('Ошибка при удалении уведомления', 'error')

    return redirect(url_for('manage_notifications'))

@app.route('/admin/recurring-notifications')
@login_required
def manage_recurring_notifications():
    """Manage recurring notifications page for all admins"""
    telegram_id = session.get('telegram_id')
    admin_level = is_admin(telegram_id)

    if admin_level == 0:
        flash(get_translation(get_user_lang(), 'admin_only', 'Admin access required'), 'error')
        return redirect(url_for('index'))

    recurring_notifications = load_recurring_notifications()
    return render_template('recurring_notifications.html', recurring_notifications=recurring_notifications)

@app.route('/admin/recurring-notifications', methods=['POST'])
@login_required
def create_recurring_notification():
    """Create a new recurring notification"""
    telegram_id = session.get('telegram_id')
    admin_level = is_admin(telegram_id)
    lang = get_user_lang()

    if admin_level == 0:
        flash(get_translation(lang, 'admin_only', 'Admin access required'), 'error')
        return redirect(url_for('index'))

    # Get form data
    message = request.form.get('message', '').strip()
    days_of_week = request.form.getlist('days_of_week')
    notification_time = request.form.get('notification_time')
    weeks_count = int(request.form.get('weeks_count', 1))
    repeat_count = int(request.form.get('repeat_count', 1))
    repeat_interval = int(request.form.get('repeat_interval', 24))
    interval_unit = request.form.get('interval_unit', 'hours')

    # Convert interval to seconds
    unit_multipliers = {
        'seconds': 1,
        'minutes': 60,
        'hours': 3600,
        'days': 86400
    }
    repeat_interval_seconds = repeat_interval * unit_multipliers.get(interval_unit, 3600)

    if not all([message, days_of_week, notification_time]):
        flash('Заполните все обязательные поля', 'error')
        return redirect(url_for('manage_recurring_notifications'))

    users = load_users()
    user_data = users.get(str(telegram_id))

    # Create recurring notification
    recurring_notifications = load_recurring_notifications()
    new_recurring_notification = {
        'id': len(recurring_notifications) + 1,
        'message': message,
        'days_of_week': days_of_week,
        'notification_time': notification_time,
        'weeks_count': weeks_count,
        'repeat_count': repeat_count,
        'repeat_interval_seconds': repeat_interval_seconds,
        'created_by': user_data.get('name'),
        'created_by_id': telegram_id,
        'created_at': datetime.now().isoformat(),
        'is_active': True,
        'sent_count': 0
    }

    recurring_notifications.append(new_recurring_notification)

    if save_recurring_notifications(recurring_notifications):
        flash('Повторяющееся уведомление создано успешно', 'success')
    else:
        flash('Ошибка при создании повторяющегося уведомления', 'error')

    return redirect(url_for('manage_recurring_notifications'))

@app.route('/admin/recurring-notifications/<int:notification_id>/delete', methods=['POST'])
@login_required
def delete_recurring_notification(notification_id):
    """Delete a recurring notification"""
    telegram_id = session.get('telegram_id')
    admin_level = is_admin(telegram_id)

    if admin_level == 0:
        flash(get_translation(get_user_lang(), 'admin_only', 'Admin access required'), 'error')
        return redirect(url_for('index'))

    recurring_notifications = load_recurring_notifications()
    recurring_notifications = [n for n in recurring_notifications if n['id'] != notification_id]

    if save_recurring_notifications(recurring_notifications):
        flash('Повторяющееся уведомление удалено', 'success')
    else:
        flash('Ошибка при удалении повторяющегося уведомления', 'error')

    return redirect(url_for('manage_recurring_notifications'))

@app.route('/admin/clear-system', methods=['POST'])
@login_required
def clear_system():
    """Clear all system data (only for level 3 admins)"""
    telegram_id = session.get('telegram_id')
    admin_level = is_admin(telegram_id)

    if admin_level < 3:
        flash('Недостаточно прав для очистки системы', 'error')
        return redirect(url_for('index'))

    if clear_all_system_data():
        flash('Система успешно очищена', 'success')
    else:
        flash('Ошибка при очистке системы', 'error')

    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    """Logout user and clear session"""
    session.clear()
    flash(get_translation(get_user_lang(), 'logout_successful', 'You have been logged out successfully'), 'success')
    return redirect(url_for('telegram_auth'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)