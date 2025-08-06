
import json
import os
import logging

ADMINS_JSON_PATH = "data/admins.json"

def load_admins():
    """Load admins data from JSON file"""
    try:
        with open(ADMINS_JSON_PATH, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        # Initialize with level 3 admin
        admins = {
            "8090093417": {
                "telegram_id": 8090093417,
                "level": 3,
                "added_by": "system",
                "added_at": "2024-01-01T00:00:00.000000"
            }
        }
        save_admins(admins)
        return admins

def save_admins(admins):
    """Save admins data to JSON file"""
    try:
        os.makedirs(os.path.dirname(ADMINS_JSON_PATH), exist_ok=True)
        with open(ADMINS_JSON_PATH, 'w') as f:
            json.dump(admins, f, indent=2)
        return True
    except Exception as e:
        logging.error(f"Error saving admins: {e}")
        return False

def is_admin(telegram_id):
    """Check if user is admin and return level"""
    admins = load_admins()
    admin = admins.get(str(telegram_id))
    return admin['level'] if admin else 0

def can_manage_admin(admin_level, target_level):
    """Check if admin can manage another admin"""
    return admin_level >= 2 and admin_level > target_level

def add_admin(telegram_id, level, added_by_id):
    """Add new admin"""
    admins = load_admins()
    admin_level = is_admin(added_by_id)
    
    if not can_manage_admin(admin_level, level):
        return False, "Недостаточно прав для добавления админа этого уровня"
    
    from datetime import datetime
    admins[str(telegram_id)] = {
        "telegram_id": telegram_id,
        "level": level,
        "added_by": added_by_id,
        "added_at": datetime.now().isoformat()
    }
    
    if save_admins(admins):
        return True, "Админ успешно добавлен"
    return False, "Ошибка при сохранении"

def remove_admin(telegram_id, removed_by_id):
    """Remove admin"""
    admins = load_admins()
    admin_level = is_admin(removed_by_id)
    target_admin = admins.get(str(telegram_id))
    
    if not target_admin:
        return False, "Админ не найден"
    
    if not can_manage_admin(admin_level, target_admin['level']):
        return False, "Недостаточно прав для удаления этого админа"
    
    del admins[str(telegram_id)]
    
    if save_admins(admins):
        return True, "Админ успешно удален"
    return False, "Ошибка при сохранении"

def get_admins_list():
    """Get formatted list of admins"""
    admins = load_admins()
    admin_list = []
    
    for telegram_id, admin in admins.items():
        level_text = {3: "Главный админ", 2: "Админ-модератор", 1: "Админ"}
        admin_list.append(f"👤 ID: {telegram_id}\n🔹 Уровень: {level_text.get(admin['level'], 'Неизвестно')}")
    
    return "\n\n".join(admin_list) if admin_list else "Список админов пуст"
