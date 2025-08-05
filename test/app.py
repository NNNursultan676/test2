
import os
import json
import logging
import requests
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from werkzeug.middleware.proxy_fix import ProxyFix
from translations import get_translation, get_companies, TRANSLATIONS
from config import BOT_TOKEN, GROUP_ID, USERS_JSON_PATH, BOOKINGS_JSON_PATH

# Configure logging
logging.basicConfig(level=logging.DEBUG)

# Create the app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key-change-in-production")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

def load_rooms():
    """Load rooms data from JSON file"""
    try:
        with open('data/rooms.json', 'r') as f:
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
    
    if telegram_id:
        users = load_users()
        user_data = users.get(str(telegram_id))
    
    def get_room_name(room, lang='ru'):
        """Get localized room name"""
        if 'name_translations' in room and lang in room['name_translations']:
            return room['name_translations'][lang]
        return room['name']
    
    return {
        'get_translation': lambda key, default=None: get_translation(lang, key, default),
        'get_room_name': get_room_name,
        'lang': lang,
        'companies': get_companies(),
        'user_name': user_data.get('name') if user_data else None,
        'user_company': user_data.get('company') if user_data else None,
        'is_registered': is_user_registered(),
        'telegram_id': telegram_id
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
    bookings = load_bookings()
    booking_to_delete = None

    for i, booking in enumerate(bookings):
        if (booking['id'] == booking_id and 
            str(booking.get('telegram_id')) == str(telegram_id)):
            booking_to_delete = i
            break

    if booking_to_delete is not None:
        deleted_booking = bookings.pop(booking_to_delete)
        if save_bookings(bookings):
            flash(get_translation(get_user_lang(), 'booking_deleted', 'Booking deleted successfully'), 'success')
        else:
            flash(get_translation(get_user_lang(), 'delete_error', 'Error deleting booking'), 'error')
    else:
        flash(get_translation(get_user_lang(), 'booking_not_found', 'Booking not found'), 'error')

    return redirect(url_for('my_bookings'))

@app.route('/edit-booking/<int:booking_id>')
@login_required
def edit_booking(booking_id):
    """Edit booking page"""
    if not is_user_registered():
        return redirect(url_for('register'))

    telegram_id = session.get('telegram_id')
    bookings = load_bookings()
    booking = None

    for b in bookings:
        if (b['id'] == booking_id and 
            str(b.get('telegram_id')) == str(telegram_id)):
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
    lang = get_user_lang()

    bookings = load_bookings()
    booking_index = None
    original_booking = None

    for i, b in enumerate(bookings):
        if (b['id'] == booking_id and 
            str(b.get('telegram_id')) == str(telegram_id)):
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
        'updated_at': datetime.now().isoformat()
    })

    if save_bookings(bookings):
        flash(get_translation(lang, 'booking_updated', 'Booking updated successfully'), 'success')
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

@app.route('/logout')
def logout():
    """Logout user and clear session"""
    session.clear()
    flash(get_translation(get_user_lang(), 'logout_successful', 'You have been logged out successfully'), 'success')
    return redirect(url_for('telegram_auth'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
