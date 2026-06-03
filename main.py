import os
import re
import telebot
from telebot import types
from telebot.handler_backends import CancelUpdate
import sqlite3
from flask import Flask
import threading
import random
import time
import datetime
import json

# ==================== FLASK ====================
app = Flask(__name__)

@app.route("/")
def health():
    return "Bot is running"

def run_flask():
    app.run(host="0.0.0.0", port=8099)

threading.Thread(target=run_flask, daemon=True).start()

# ==================== КОНФИГ ====================
TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID_RAW = os.environ.get("ADMIN_CHAT_ID", "0")
try:
    ADMIN_CHAT_ID = int(ADMIN_CHAT_ID_RAW)
except Exception:
    ADMIN_CHAT_ID = 0

ACCEPT_TIMEOUT = 60
MAPS = ["Zone 9", "Rust", "Province", "Sakura", "Sandstone"]

_raw_ids = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS_LIST: list = [int(x.strip()) for x in _raw_ids.split(",") if x.strip().isdigit()]
ADMIN_ID = ADMIN_IDS_LIST[0] if ADMIN_IDS_LIST else 0

telebot.apihelper.ENABLE_MIDDLEWARE = True
bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# ==================== ГЛОБАЛЬНЫЕ СОСТОЯНИЯ ====================
maintenance_mode      = False          # Технические работы
active_lobbies        = {}
running_matches       = {}
user_lobby            = {}
lobby_player_messages = {}
ban_status_messages   = {}
ban_turn_messages     = {}      # {lobby_id: (chat_id, msg_id)}
accept_status_messages= {}      # {lobby_id: {uid: (chat_id, msg_id)}}
match_found_messages  = {}      # {lobby_id: {uid: (chat_id, msg_id)}}
user_flow             = {}
awaiting_screenshot   = {}
rename_flow           = {}
parties               = {}
user_party            = {}
admin_action          = {}
match_registration    = {}
awaiting_party_invite = {}
change_flow           = {}
editstat_flow         = {}      # {uid: {"field": ..., "target_id": ...}}
promo_flow            = {}      # {uid: True}  — ждём ввода промокода
promo_admin_flow      = {}      # {uid: {step, data}}

# ==================== БАЗА ДАННЫХ ====================
DB = "faceit.db"

SHOP_ITEMS_DEFAULT = [
    ("AK-47 | Fuel Injector",  "Легендарный скин на АК-47", "skins", 500,  "skin"),
    ("AK-47 | Bloodsport",     "Агрессивный дизайн",        "skins", 350,  "skin"),
    ("M4A4 | Howl",            "Редкий скин M4A4",           "skins", 800,  "skin"),
    ("M4A4 | Neo-Noir",        "Элегантный скин M4A4",       "skins", 400,  "skin"),
    ("AWP | Dragon Lore",      "Легендарный AWP",            "skins", 1200, "skin"),
    ("AWP | Asiimov",          "Футуристичный AWP",          "skins", 600,  "skin"),
    ("Нож | Butterfly Blue",   "Красивый нож-бабочка",       "skins", 1500, "skin"),
    ("Нож | Karambit Fade",    "Редкий карамбит",            "skins", 2000, "skin"),
    ("Рамка Gold",             "Золотая рамка профиля",      "decor", 300,  "frame"),
    ("Рамка Diamond",          "Алмазная рамка профиля",     "decor", 600,  "frame"),
    ("Рамка Elite",            "Элитная рамка профиля",      "decor", 150,  "frame"),
    ("Стикер 🔥",              "Огненный стикер",            "decor", 50,   "sticker"),
    ("Стикер 💀",              "Стикер черепа",              "decor", 50,   "sticker"),
    ("Стикер ⚡",              "Стикер молнии",              "decor", 50,   "sticker"),
    ("Анимация Победа",        "Анимация при победе",        "decor", 400,  "animation"),
    ("Анимация Убийство",      "Анимация при убийстве",      "decor", 400,  "animation"),
    ("Premium статус",         "30 дней Premium: x1.5 монет, значок 👑", "goods", 1000, "premium"),
    ("x2 монеты",              "Удвоение монет за 7 дней",   "goods", 300,  "x2coins"),
    ("Снятие варна",           "Снять 1 предупреждение",     "goods", 150,  "unwarn"),
    ("Смена ника",             "Изменить ник в боте",        "goods", 10,   "rename"),
    ("Quals доступ",           "Постоянный доступ к QUALS",  "goods", 1500, "quals"),
]

CATEGORY_NAMES = {"skins": "🎨 Скины", "decor": "🖼 Декор", "goods": "📦 Товары"}
CATEGORY_ICONS = {"skins": "🎨", "decor": "🖼", "goods": "📦"}

COIN_PACKAGES = [
    ("Стартовый",   200,   40,   "40 ⭐"),
    ("Оптимальный", 600,   100,  "100 ⭐"),
    ("Выгодный",    2000,  300,  "300 ⭐"),
    ("Мега",        5000,  750,  "750 ⭐"),
    ("Элита",       70000, 1200, "1200 ⭐"),
]


def get_faceit_level(elo: int) -> int:
    if   elo < 801:  return 1
    elif elo < 951:  return 2
    elif elo < 1101: return 3
    elif elo < 1251: return 4
    elif elo < 1401: return 5
    elif elo < 1551: return 6
    elif elo < 1701: return 7
    elif elo < 1851: return 8
    elif elo < 2001: return 9
    else:            return 10


def init_db():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS players (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            game_id TEXT,
            device TEXT,
            elo INTEGER DEFAULT 1000,
            coins INTEGER DEFAULT 100,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            kills INTEGER DEFAULT 0,
            deaths INTEGER DEFAULT 0,
            assists INTEGER DEFAULT 0,
            is_admin INTEGER DEFAULT 0,
            registered INTEGER DEFAULT 0,
            is_bot INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0,
            warns INTEGER DEFAULT 0,
            quals_access INTEGER DEFAULT 0,
            is_game_reg INTEGER DEFAULT 0,
            is_muted INTEGER DEFAULT 0,
            mute_until INTEGER DEFAULT 0,
            is_on_check INTEGER DEFAULT 0,
            check_admin_id INTEGER DEFAULT 0,
            tg_username TEXT DEFAULT ''
        )
    """)
    for col, definition in [
        ("is_banned",      "INTEGER DEFAULT 0"),
        ("warns",          "INTEGER DEFAULT 0"),
        ("quals_access",   "INTEGER DEFAULT 0"),
        ("is_game_reg",    "INTEGER DEFAULT 0"),
        ("is_muted",       "INTEGER DEFAULT 0"),
        ("mute_until",     "INTEGER DEFAULT 0"),
        ("is_on_check",    "INTEGER DEFAULT 0"),
        ("check_admin_id", "INTEGER DEFAULT 0"),
        ("tg_username",    "TEXT DEFAULT ''"),
    ]:
        try:
            cur.execute(f"ALTER TABLE players ADD COLUMN {col} {definition}")
        except Exception:
            pass

    for admin_uid in ADMIN_IDS_LIST:
        cur.execute(
            "INSERT OR IGNORE INTO players (user_id, username, registered, is_admin) VALUES (?, 'Admin', 1, 1)",
            (admin_uid,),
        )
        cur.execute("UPDATE players SET is_admin=1 WHERE user_id=?", (admin_uid,))

    cur.execute("SELECT COUNT(*) FROM players WHERE is_bot=1")
    if cur.fetchone()[0] == 0:
        for i in range(1, 21):
            bot_id = 1000000000 + i
            cur.execute(
                "INSERT OR IGNORE INTO players (user_id, username, game_id, device, registered, is_bot, elo) VALUES (?, ?, ?, ?, 1, 1, 1000)",
                (bot_id, f"Bot_{i}", str(500000000 + i), "PC" if i % 2 == 0 else "MOBILE"),
            )

    cur.execute("""
        CREATE TABLE IF NOT EXISTS shop_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, description TEXT,
            category TEXT NOT NULL, price INTEGER NOT NULL,
            item_type TEXT NOT NULL, is_active INTEGER DEFAULT 1
        )
    """)
    cur.execute("SELECT COUNT(*) FROM shop_items")
    if cur.fetchone()[0] == 0:
        cur.executemany(
            "INSERT INTO shop_items (name, description, category, price, item_type) VALUES (?,?,?,?,?)",
            SHOP_ITEMS_DEFAULT,
        )
    else:
        # Обновляем цены при каждом запуске бота
        price_updates = [
            (1000, "premium"),
            (300,  "x2coins"),
            (150,  "unwarn"),
            (10,   "rename"),
            (1500, "quals"),
        ]
        for price, item_type in price_updates:
            cur.execute("UPDATE shop_items SET price=? WHERE item_type=?", (price, item_type))

    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL, item_id INTEGER NOT NULL,
            purchased_at INTEGER DEFAULT (strftime('%s','now')),
            is_activated INTEGER DEFAULT 0, activated_at INTEGER DEFAULT NULL,
            FOREIGN KEY (user_id) REFERENCES players(user_id),
            FOREIGN KEY (item_id) REFERENCES shop_items(id)
        )
    """)
    for col, definition in [("is_activated","INTEGER DEFAULT 0"),("activated_at","INTEGER DEFAULT NULL")]:
        try:
            cur.execute(f"ALTER TABLE inventory ADD COLUMN {col} {definition}")
        except Exception:
            pass

    cur.execute("CREATE TABLE IF NOT EXISTS match_counter (id INTEGER PRIMARY KEY, value INTEGER DEFAULT 0)")
    cur.execute("INSERT OR IGNORE INTO match_counter (id, value) VALUES (1, 0)")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL, league TEXT, device TEXT, map_name TEXT,
            winner TEXT, score_w INTEGER, score_l INTEGER,
            finished_at INTEGER DEFAULT (strftime('%s','now')), players_json TEXT
        )
    """)

    # Промокоды
    cur.execute("""
        CREATE TABLE IF NOT EXISTS promo_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            reward_type TEXT NOT NULL,
            reward_value INTEGER DEFAULT 0,
            max_uses INTEGER DEFAULT 1,
            uses INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at INTEGER DEFAULT (strftime('%s','now'))
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS promo_uses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            code TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()
    print("✅ БД инициализирована.")


# ==================== БД ХЕЛПЕРЫ ====================
def _db():
    return sqlite3.connect(DB)

def get_player(user_id):
    conn = _db(); cur = conn.cursor()
    cur.execute("SELECT * FROM players WHERE user_id=?", (user_id,))
    row = cur.fetchone(); conn.close(); return row

def is_registered(uid):
    p = get_player(uid); return p is not None and p[12] == 1

def is_admin(uid):
    p = get_player(uid); return p is not None and p[11] == 1

def is_game_reg_check(uid):
    p = get_player(uid)
    return p is not None and (p[11] == 1 or (len(p) > 17 and p[17] == 1))

def is_bot_player(uid):
    p = get_player(uid); return p is not None and p[13] == 1

def is_banned_check(uid):
    p = get_player(uid); return p is not None and len(p) > 14 and p[14] == 1

def is_muted_check(uid):
    p = get_player(uid)
    if p is None: return False
    if len(p) > 19 and p[18] == 1:
        mute_until = p[19] or 0
        if mute_until > time.time():
            return True
        conn = _db(); conn.execute("UPDATE players SET is_muted=0, mute_until=0 WHERE user_id=?", (uid,)); conn.commit(); conn.close()
    return False

def get_mute_remaining(uid):
    p = get_player(uid)
    if p is None or len(p) <= 19: return 0
    return max(0, int((p[19] or 0) - time.time()))

def is_on_check_db(uid):
    p = get_player(uid); return p is not None and len(p) > 20 and p[20] == 1

def get_check_admin(uid):
    p = get_player(uid)
    if p is None or len(p) <= 21: return None
    return p[21]

def has_quals_access(uid):
    if is_admin(uid): return True
    p = get_player(uid); return p is not None and len(p) > 16 and p[16] == 1

def has_active_premium(uid):
    conn = _db(); cur = conn.cursor()
    cur.execute("""SELECT COUNT(*) FROM inventory i JOIN shop_items s ON i.item_id=s.id
                   WHERE i.user_id=? AND s.item_type='premium' AND i.is_activated=1""", (uid,))
    count = cur.fetchone()[0]; conn.close(); return count > 0

def register_user(uid, username, game_id, device, tg_username=""):
    conn = _db()
    conn.execute(
        "INSERT OR REPLACE INTO players (user_id, username, game_id, device, registered, coins, elo, tg_username) VALUES (?,?,?,?,1,100,1000,?)",
        (uid, username, game_id, device, tg_username),
    )
    conn.commit(); conn.close()

def update_tg_username(uid, tg_username):
    conn = _db(); conn.execute("UPDATE players SET tg_username=? WHERE user_id=?", (tg_username or "", uid)); conn.commit(); conn.close()

def nick_taken(nick, exclude_uid=None):
    conn = _db(); cur = conn.cursor()
    if exclude_uid:
        cur.execute("SELECT COUNT(*) FROM players WHERE username=? AND user_id!=? AND is_bot=0", (nick, exclude_uid))
    else:
        cur.execute("SELECT COUNT(*) FROM players WHERE username=? AND is_bot=0", (nick,))
    count = cur.fetchone()[0]; conn.close(); return count > 0

def game_id_taken(game_id, exclude_uid=None):
    conn = _db(); cur = conn.cursor()
    if exclude_uid:
        cur.execute("SELECT COUNT(*) FROM players WHERE game_id=? AND user_id!=? AND is_bot=0", (game_id, exclude_uid))
    else:
        cur.execute("SELECT COUNT(*) FROM players WHERE game_id=? AND is_bot=0", (game_id,))
    count = cur.fetchone()[0]; conn.close(); return count > 0

def get_bots():
    conn = _db(); cur = conn.cursor()
    cur.execute("SELECT user_id, username FROM players WHERE is_bot=1")
    bots = cur.fetchall(); conn.close(); return bots

def get_all_players():
    conn = _db(); cur = conn.cursor()
    cur.execute("""SELECT user_id, username, elo, wins, losses, kills, deaths, coins, is_banned, warns
                   FROM players WHERE is_bot=0 AND registered=1 ORDER BY elo DESC""")
    rows = cur.fetchall(); conn.close(); return rows

def get_player_by_game_id(game_id):
    conn = _db(); cur = conn.cursor()
    cur.execute("SELECT * FROM players WHERE game_id=? AND is_bot=0", (game_id,))
    row = cur.fetchone(); conn.close(); return row

def add_coins_to_player(uid, amount):
    conn = _db(); conn.execute("UPDATE players SET coins=coins+? WHERE user_id=?", (amount, uid)); conn.commit(); conn.close()

def apply_mute(uid, hours=2):
    until = int(time.time()) + hours * 3600
    conn = _db(); conn.execute("UPDATE players SET is_muted=1, mute_until=? WHERE user_id=?", (until, uid)); conn.commit(); conn.close()
    return until

def add_warn_to_player(uid):
    conn = _db(); cur = conn.cursor()
    cur.execute("UPDATE players SET warns=warns+1 WHERE user_id=?", (uid,))
    cur.execute("SELECT warns FROM players WHERE user_id=?", (uid,))
    row = cur.fetchone(); conn.commit(); conn.close()
    return row[0] if row else 1

def get_next_match_id():
    conn = _db(); cur = conn.cursor()
    cur.execute("UPDATE match_counter SET value=value+1 WHERE id=1")
    cur.execute("SELECT value FROM match_counter WHERE id=1")
    val = cur.fetchone()[0]; conn.commit(); conn.close(); return val

def save_match_to_history(lobby, data, all_stats):
    players_info = []
    for uid, s in all_stats.items():
        p = get_player(uid)
        players_info.append({"user_id": uid, "name": p[1] if p else str(uid),
                              "kills": s["kills"], "deaths": s["deaths"],
                              "assists": s["assists"], "won": s["won"]})
    conn = _db()
    conn.execute("INSERT INTO matches (match_id, league, device, map_name, winner, score_w, score_l, players_json) VALUES (?,?,?,?,?,?,?,?)",
                 (lobby.get("match_id", 0), lobby.get("league", ""), lobby.get("device", ""),
                  lobby.get("map_name", ""), data.get("winner", ""),
                  data.get("score_w", 0), data.get("score_l", 0),
                  json.dumps(players_info, ensure_ascii=False)))
    conn.commit(); conn.close()

def get_match_history(limit=10):
    conn = _db(); cur = conn.cursor()
    cur.execute("SELECT match_id, league, device, map_name, winner, score_w, score_l, finished_at FROM matches ORDER BY finished_at DESC LIMIT ?", (limit,))
    rows = cur.fetchall(); conn.close(); return rows

# ==================== ПРОМОКОДЫ ====================
def create_promo_code(code, reward_type, reward_value, max_uses):
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO promo_codes (code, reward_type, reward_value, max_uses) VALUES (?,?,?,?)",
            (code.upper(), reward_type, reward_value, max_uses)
        )
        conn.commit(); return True
    except Exception:
        return False
    finally:
        conn.close()

def use_promo_code(uid, code):
    conn = _db(); cur = conn.cursor()
    code_upper = code.upper()
    cur.execute("SELECT id, reward_type, reward_value, max_uses, uses, is_active FROM promo_codes WHERE code=?", (code_upper,))
    row = cur.fetchone()
    if not row:
        conn.close(); return False, "❌ Промокод не найден"
    pid, reward_type, reward_value, max_uses, uses, is_active = row
    if not is_active:
        conn.close(); return False, "❌ Промокод недействителен"
    if max_uses > 0 and uses >= max_uses:
        conn.close(); return False, "❌ Промокод исчерпан"
    cur.execute("SELECT COUNT(*) FROM promo_uses WHERE user_id=? AND code=?", (uid, code_upper))
    if cur.fetchone()[0] > 0:
        conn.close(); return False, "❌ Вы уже использовали этот промокод"
    if reward_type == "coins":
        cur.execute("UPDATE players SET coins=coins+? WHERE user_id=?", (reward_value, uid))
        msg = f"💰 Начислено <b>{reward_value} AC</b>!"
    elif reward_type == "premium":
        cur.execute("SELECT id FROM shop_items WHERE item_type='premium' LIMIT 1")
        item = cur.fetchone()
        if item:
            cur.execute("INSERT INTO inventory (user_id, item_id, is_activated) VALUES (?,?,1)", (uid, item[0]))
        msg = "👑 <b>Premium</b> активирован!"
    elif reward_type == "quals":
        cur.execute("UPDATE players SET quals_access=1 WHERE user_id=?", (uid,))
        msg = "⭐ Доступ к <b>QUALS</b> открыт!"
    else:
        conn.close(); return False, "❌ Неизвестный тип награды"
    cur.execute("INSERT INTO promo_uses (user_id, code) VALUES (?,?)", (uid, code_upper))
    cur.execute("UPDATE promo_codes SET uses=uses+1 WHERE id=?", (pid,))
    conn.commit(); conn.close()
    return True, msg

def get_all_promo_codes():
    conn = _db(); cur = conn.cursor()
    cur.execute("SELECT code, reward_type, reward_value, max_uses, uses, is_active FROM promo_codes ORDER BY id DESC")
    rows = cur.fetchall(); conn.close(); return rows

def deactivate_promo_code(code):
    conn = _db()
    conn.execute("UPDATE promo_codes SET is_active=0 WHERE code=?", (code.upper(),))
    conn.commit(); conn.close()

# ==================== МАГАЗИН ХЕЛПЕРЫ ====================
def get_shop_item(item_id):
    conn = _db(); cur = conn.cursor()
    cur.execute("SELECT id, name, description, category, price, item_type FROM shop_items WHERE id=?", (item_id,))
    item = cur.fetchone(); conn.close(); return item

def get_shop_items_by_category(category):
    conn = _db(); cur = conn.cursor()
    cur.execute("SELECT id, name, description, price, item_type FROM shop_items WHERE category=? AND is_active=1", (category,))
    items = cur.fetchall(); conn.close(); return items

def has_item_in_inventory(uid, item_id):
    conn = _db(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM inventory WHERE user_id=? AND item_id=?", (uid, item_id))
    count = cur.fetchone()[0]; conn.close(); return count > 0

def buy_item(uid, item_id):
    item = get_shop_item(item_id)
    if not item: return False, "❌ Товар не найден"
    price = item[4]; p = get_player(uid)
    if not p: return False, "❌ Игрок не найден"
    if p[5] < price: return False, f"❌ Недостаточно ActualCoin!\nНужно: {price} AC\nУ вас: {p[5]} AC"
    stackable = {"sticker", "unwarn", "x2coins", "rename"}
    if item[5] not in stackable and has_item_in_inventory(uid, item_id):
        return False, "❌ Этот предмет уже есть в вашем инвентаре!"
    conn = _db()
    conn.execute("UPDATE players SET coins=coins-? WHERE user_id=?", (price, uid))
    conn.execute("INSERT INTO inventory (user_id, item_id) VALUES (?, ?)", (uid, item_id))
    conn.commit(); conn.close()
    return True, f"✅ Куплено: <b>{item[1]}</b>\nСписано: {price} AC\n\n💡 Активируйте предмет в 🎒 Инвентаре"

def get_inventory(uid):
    conn = _db(); cur = conn.cursor()
    cur.execute("""SELECT i.id, s.name, s.category, s.item_type, i.purchased_at, i.is_activated, s.id
                   FROM inventory i JOIN shop_items s ON i.item_id=s.id
                   WHERE i.user_id=? ORDER BY i.purchased_at DESC""", (uid,))
    items = cur.fetchall(); conn.close(); return items

def activate_inventory_item(inv_id, uid, item_type, item_name):
    conn = _db(); cur = conn.cursor()
    if item_type == "unwarn":
        cur.execute("SELECT warns FROM players WHERE user_id=?", (uid,))
        row = cur.fetchone()
        if row and row[0] > 0:
            cur.execute("UPDATE players SET warns=warns-1 WHERE user_id=?", (uid,))
        else:
            conn.close(); return False, "❌ У вас нет варнов для снятия"
    elif item_type == "rename":
        conn.close(); return "rename", "✏️ Введите новый никнейм (2-20 символов):"
    elif item_type == "quals":
        cur.execute("UPDATE players SET quals_access=1 WHERE user_id=?", (uid,))
    cur.execute("UPDATE inventory SET is_activated=1, activated_at=strftime('%s','now') WHERE id=?", (inv_id,))
    conn.commit(); conn.close()
    return True, f"✅ Предмет <b>{item_name}</b> активирован!"

# ==================== ПАТИ ====================
def get_party_of(uid):
    pid = user_party.get(uid)
    return parties.get(pid) if pid else None

def get_party_max_size(party):
    for m in party["members"]:
        if has_active_premium(m): return 3
    return 2

# ==================== КАПИТАН (premium +7%) ====================
def pick_captain(team):
    if not team: return None
    weights = [1.07 if has_active_premium(u) else 1.0 for u in team]
    return random.choices(team, weights=weights, k=1)[0]

# ==================== ТЕХРАБОТЫ (MIDDLEWARE) ====================
@bot.middleware_handler(update_types=["message", "callback_query"])
def maintenance_middleware(bot_instance, update):
    global maintenance_mode
    if not maintenance_mode:
        return
    if hasattr(update, "from_user") and update.from_user:
        uid = update.from_user.id
    else:
        return
    # Администраторам проход разрешён всегда
    if uid in ADMIN_IDS_LIST:
        return
    p = get_player(uid)
    if p and p[11] == 1:
        return
    # Блокируем обычных пользователей
    if hasattr(update, "message"):
        # callback_query
        try:
            bot_instance.answer_callback_query(
                update.id,
                "🔧 Технические работы!\nБот временно недоступен. Попробуйте позже.",
                show_alert=True
            )
        except Exception:
            pass
    else:
        # message
        try:
            bot_instance.send_message(
                update.chat.id,
                "🔧 <b>Технические работы</b>\n\nБот временно недоступен для игроков. Попробуйте позже."
            )
        except Exception:
            pass
    return CancelUpdate()


# ==================== ПРОВЕРКА БЛОКИРОВОК ====================
def check_blocked(uid):
    if is_banned_check(uid):
        return "🚫 Вы заблокированы в боте."
    if is_on_check_db(uid):
        admin_uid = get_check_admin(uid)
        admin_name = "администратора"
        if admin_uid:
            ap = get_player(admin_uid)
            if ap:
                tg_u = ap[22] if len(ap) > 22 else ""
                admin_name = f"@{tg_u}" if tg_u else f"администратора (id:{admin_uid})"
        return f"⚠️ <b>Вас вызвал на проверку {admin_name}</b>\n\nДоступ к боту ограничен до прохождения проверки.\nОбратитесь к администратору."
    return None

# ==================== ГЛАВНОЕ МЕНЮ ====================
def main_menu(uid):
    kb = types.InlineKeyboardMarkup(row_width=2)
    # Если в лобби — кнопка "Вернуться в лобби", иначе "Найти матч"
    if uid in user_lobby:
        kb.add(
            types.InlineKeyboardButton("👤 Профиль", callback_data="profile"),
            types.InlineKeyboardButton("🔄 Вернуться в лобби", callback_data="rejoin_lobby"),
        )
    else:
        kb.add(
            types.InlineKeyboardButton("👤 Профиль", callback_data="profile"),
            types.InlineKeyboardButton("🎮 Найти матч", callback_data="find"),
        )
    kb.add(
        types.InlineKeyboardButton("🏆 Топ", callback_data="top"),
        types.InlineKeyboardButton("🛒 Магазин", callback_data="shop"),
        types.InlineKeyboardButton("🎒 Инвентарь", callback_data="inv"),
        types.InlineKeyboardButton("💳 Купить монеты", callback_data="buy_coins"),
        types.InlineKeyboardButton("🎁 Промокод", callback_data="promo"),
    )
    in_party = uid in user_party
    kb.add(types.InlineKeyboardButton(
        "👥 Моя пати" if in_party else "➕ Создать пати", callback_data="party_menu"
    ))
    if is_admin(uid):
        kb.add(
            types.InlineKeyboardButton("🤖 Добавить ботов", callback_data="add_bots_admin"),
            types.InlineKeyboardButton("⚙️ Админ панель", callback_data="admin_panel"),
        )
    elif is_game_reg_check(uid):
        kb.add(types.InlineKeyboardButton("📋 Регистрация матчей", callback_data="game_reg_panel"))
    return kb


@bot.message_handler(commands=["start"])
def cmd_start(msg):
    uid = msg.from_user.id
    if msg.from_user.username:
        update_tg_username(uid, msg.from_user.username)
    err = check_blocked(uid)
    if err:
        bot.send_message(uid, err); return
    if is_registered(uid):
        bot.send_message(uid, "⚡ ACTUAL FACEIT", reply_markup=main_menu(uid)); return
    user_flow[uid] = {"state": "nick"}
    bot.send_message(uid, "👋 Добро пожаловать!\n\n<b>Шаг 1:</b> Введи свой никнейм (2-20 символов):")


# Кнопка "Вернуться в лобби"
@bot.callback_query_handler(func=lambda c: c.data == "rejoin_lobby")
def cb_rejoin_lobby(c):
    uid = c.from_user.id
    lobby_id = user_lobby.get(uid)
    if not lobby_id:
        bot.answer_callback_query(c.id, "❌ Вы не в лобби")
        bot.edit_message_text("⚡ ACTUAL FACEIT", c.message.chat.id, c.message.message_id, reply_markup=main_menu(uid))
        return
    lobby = active_lobbies.get(lobby_id)
    if not lobby or lobby.get("status") != "waiting":
        bot.answer_callback_query(c.id, "❌ Лобби недоступно")
        bot.edit_message_text("⚡ ACTUAL FACEIT", c.message.chat.id, c.message.message_id, reply_markup=main_menu(uid))
        return
    text = build_lobby_text(lobby_id)
    kb = build_lobby_kb(lobby_id, uid)
    bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=kb)
    if lobby_player_messages.get(lobby_id) is None:
        lobby_player_messages[lobby_id] = {}
    lobby_player_messages[lobby_id][uid] = (c.message.chat.id, c.message.message_id)
    bot.answer_callback_query(c.id)


# ==================== ПРОМОКОД (пользователь) ====================
@bot.callback_query_handler(func=lambda c: c.data == "promo")
def cb_promo(c):
    uid = c.from_user.id
    err = check_blocked(uid)
    if err:
        bot.answer_callback_query(c.id, "⚠️ Доступ ограничен", show_alert=True); return
    if not is_registered(uid):
        bot.answer_callback_query(c.id, "❌ Сначала зарегистрируйтесь /start"); return
    promo_flow[uid] = True
    bot.answer_callback_query(c.id)
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("❌ Отмена", callback_data="promo_cancel"))
    bot.send_message(uid, "🎁 Введите промокод:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "promo_cancel")
def cb_promo_cancel(c):
    uid = c.from_user.id
    promo_flow.pop(uid, None)
    bot.answer_callback_query(c.id)
    try: bot.delete_message(c.message.chat.id, c.message.message_id)
    except Exception: pass

@bot.message_handler(func=lambda m: m.from_user.id in promo_flow and m.text is not None)
def handle_promo_input(msg):
    uid = msg.from_user.id
    promo_flow.pop(uid, None)
    code = msg.text.strip()
    ok, result_msg = use_promo_code(uid, code)
    p = get_player(uid)
    balance = f"\n💰 Баланс: <b>{p[5]} AC</b>" if p and ok else ""
    bot.send_message(uid, f"{result_msg}{balance}")


# ==================== РЕГИСТРАЦИЯ ====================
@bot.message_handler(func=lambda m: user_flow.get(m.from_user.id, {}).get("state") == "nick")
def reg_nick(msg):
    uid = msg.from_user.id
    nick = msg.text.strip()
    if not (2 <= len(nick) <= 20):
        bot.send_message(uid, "❌ Никнейм 2-20 символов"); return
    if nick_taken(nick):
        bot.send_message(uid, "❌ <b>Этот никнейм уже занят!</b>\n\nЕсли это ваш никнейм — обратитесь к администратору.\nВведите другой никнейм:"); return
    user_flow[uid] = {"state": "id", "nick": nick}
    bot.send_message(uid, "<b>Шаг 2:</b> Введи игровой ID\n\nМожно: русские и английские буквы, цифры, <code>_</code> и <code>-</code>")

@bot.message_handler(func=lambda m: user_flow.get(m.from_user.id, {}).get("state") == "id")
def reg_id(msg):
    uid = msg.from_user.id
    game_id = msg.text.strip()
    if not re.match(r'^[a-zA-ZА-Яа-яёЁ0-9_-]+$', game_id):
        bot.send_message(uid, "❌ Недопустимые символы! Только буквы, цифры, <code>_</code>, <code>-</code>"); return
    if game_id_taken(game_id):
        bot.send_message(uid, "❌ <b>Этот Game ID уже занят!</b>\n\nВведите другой Game ID:"); return
    user_flow[uid]["game_id"] = game_id
    user_flow[uid]["state"] = "device"
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.row("MOBILE", "PC")
    bot.send_message(uid, "<b>Шаг 3:</b> Выбери устройство:", reply_markup=kb)

@bot.message_handler(func=lambda m: user_flow.get(m.from_user.id, {}).get("state") == "device")
def reg_device(msg):
    uid = msg.from_user.id
    device = msg.text.strip()
    if device not in ("MOBILE", "PC"):
        bot.send_message(uid, "❌ Выбери MOBILE или PC"); return
    data = user_flow.pop(uid)
    tg_u = msg.from_user.username or ""
    register_user(uid, data["nick"], data["game_id"], device, tg_u)
    bot.send_message(uid, f"✅ Регистрация завершена!\n\nНик: <b>{data['nick']}</b>\nGame ID: <code>{data['game_id']}</code>\nDevice: {device}", reply_markup=types.ReplyKeyboardRemove())
    bot.send_message(uid, "⚡ ACTUAL FACEIT", reply_markup=main_menu(uid))


# ==================== СМЕНА ДАННЫХ ====================
@bot.callback_query_handler(func=lambda c: c.data in ("change_nick", "change_game_id"))
def cb_change_own(c):
    uid = c.from_user.id
    field = "nick" if c.data == "change_nick" else "game_id"
    change_flow[uid] = {"field": field}
    bot.answer_callback_query(c.id)
    if field == "nick":
        bot.send_message(uid, "✏️ Введите новый никнейм (2-20 символов):")
    else:
        bot.send_message(uid, "🎮 Введите новый Game ID:\n\nТолько буквы, цифры, <code>_</code> и <code>-</code>")

@bot.message_handler(func=lambda m: m.from_user.id in change_flow and "field" in change_flow.get(m.from_user.id, {}) and m.text is not None)
def handle_change_flow(msg):
    uid = msg.from_user.id
    if uid not in change_flow: return
    data = change_flow.pop(uid)
    field = data["field"]
    text = msg.text.strip()
    if field == "nick":
        if not (2 <= len(text) <= 20):
            bot.send_message(uid, "❌ Никнейм 2-20 символов."); return
        if nick_taken(text, exclude_uid=uid):
            bot.send_message(uid, "❌ <b>Этот никнейм уже занят!</b>"); return
        conn = _db(); conn.execute("UPDATE players SET username=? WHERE user_id=?", (text, uid)); conn.commit(); conn.close()
        bot.send_message(uid, f"✅ Никнейм изменён на <b>{text}</b>!")
    elif field == "game_id":
        if not re.match(r'^[a-zA-ZА-Яа-яёЁ0-9_-]+$', text):
            bot.send_message(uid, "❌ Только буквы, цифры, <code>_</code> и <code>-</code>"); return
        if game_id_taken(text, exclude_uid=uid):
            bot.send_message(uid, "❌ <b>Этот Game ID уже занят!</b>"); return
        conn = _db(); conn.execute("UPDATE players SET game_id=? WHERE user_id=?", (text, uid)); conn.commit(); conn.close()
        bot.send_message(uid, f"✅ Game ID изменён на <code>{text}</code>!")
    elif field == "admin_nick":
        target_id = data.get("target_id")
        if not target_id: return
        if not (2 <= len(text) <= 20):
            bot.send_message(uid, "❌ Никнейм 2-20 символов."); return
        if nick_taken(text, exclude_uid=target_id):
            bot.send_message(uid, f"❌ Никнейм <b>{text}</b> уже занят!"); return
        conn = _db(); conn.execute("UPDATE players SET username=? WHERE user_id=?", (text, target_id)); conn.commit(); conn.close()
        bot.send_message(uid, f"✅ Никнейм игрока изменён на <b>{text}</b>!")
        try: bot.send_message(target_id, f"✏️ Администратор изменил ваш никнейм на <b>{text}</b>!")
        except Exception: pass
    elif field == "admin_id":
        target_id = data.get("target_id")
        if not target_id: return
        if not re.match(r'^[a-zA-ZА-Яа-яёЁ0-9_-]+$', text):
            bot.send_message(uid, "❌ Только буквы, цифры, <code>_</code> и <code>-</code>"); return
        if game_id_taken(text, exclude_uid=target_id):
            bot.send_message(uid, f"❌ Game ID <code>{text}</code> уже занят!"); return
        conn = _db(); conn.execute("UPDATE players SET game_id=? WHERE user_id=?", (text, target_id)); conn.commit(); conn.close()
        bot.send_message(uid, f"✅ Game ID игрока изменён на <code>{text}</code>!")
        try: bot.send_message(target_id, f"🎮 Администратор изменил ваш Game ID на <code>{text}</code>!")
        except Exception: pass


# ==================== ПРОФИЛЬ ====================
@bot.callback_query_handler(func=lambda c: c.data == "profile")
def cb_profile(c):
    uid = c.from_user.id
    p = get_player(uid)
    if not p:
        bot.edit_message_text("❌ Ошибка", c.message.chat.id, c.message.message_id); bot.answer_callback_query(c.id); return
    games = p[6] + p[7]
    winrate = round(p[6] / games * 100, 1) if games > 0 else 0
    kd = round(p[8] / p[9], 2) if p[9] > 0 else p[8]
    warns = p[15] if len(p) > 15 else 0
    quals = "✅" if (len(p) > 16 and p[16] == 1) else "❌"
    premium = has_active_premium(uid)
    crown = " 👑 Premium" if premium else ""
    lvl = get_faceit_level(p[4])
    muted = is_muted_check(uid)
    mute_text = ""
    if muted:
        mins = get_mute_remaining(uid) // 60
        mute_text = f"\n🔇 Мут: {mins} мин."
    text = (
        f"👤 <b>{p[1]}</b>{crown}\n"
        f"🆔 Telegram ID: <code>{p[0]}</code>\n"
        f"🎮 Game ID: <code>{p[2]}</code>\n"
        f"📱 Device: {p[3]}\n"
        f"📊 ELO: {p[4]} | 🎯 Lvl {lvl}\n"
        f"💰 Баланс: {p[5]} AC\n"
        f"⭐ Quals: {quals}\n"
        f"⚠️ Варны: {warns}/3{mute_text}\n\n"
        f"🏆 Побед: {p[6]}\n❌ Поражений: {p[7]}\n"
        f"🔫 K/D/A: {p[8]}/{p[9]}/{p[10]}\n"
        f"📊 K/D: {kd} | Винрейт: {winrate}%"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✏️ Изменить ник", callback_data="change_nick"),
        types.InlineKeyboardButton("🎮 Изменить Game ID", callback_data="change_game_id"),
        types.InlineKeyboardButton("🔙 Назад", callback_data="back"),
    )
    bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=kb)
    bot.answer_callback_query(c.id)


# ==================== ТОП ====================
@bot.callback_query_handler(func=lambda c: c.data == "top")
def cb_top(c):
    players = get_all_players()
    text = "🏆 <b>ТОП ИГРОКОВ ПО ELO</b>\n\n" if players else "🏆 <b>ТОП</b>\n\nИгроков нет."
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for i, p in enumerate(players[:10], 1):
        uid2, name, elo, wins, losses, kills, deaths, coins, banned, warns = p
        games = wins + losses
        winrate = round(wins / games * 100, 1) if games > 0 else 0
        kd = round(kills / deaths, 2) if deaths > 0 else kills
        lvl = get_faceit_level(elo)
        prem = " 👑" if has_active_premium(uid2) else ""
        text += f"{medals.get(i, f'{i}.')} <b>{name}</b>{prem} [Lvl {lvl}]\n   ELO: {elo} | {wins}W/{losses}L ({winrate}%) | K/D: {kd}\n\n"
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back"))
    bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=kb)
    bot.answer_callback_query(c.id)


# ==================== НАЗАД ====================
@bot.callback_query_handler(func=lambda c: c.data == "back")
def cb_back(c):
    uid = c.from_user.id
    bot.edit_message_text("⚡ ACTUAL FACEIT", c.message.chat.id, c.message.message_id, reply_markup=main_menu(uid))
    bot.answer_callback_query(c.id)


# ==================== ЛОББИ ====================
def build_lobby_text(lobby_id):
    lobby = active_lobbies.get(lobby_id)
    if not lobby: return ""
    parts = lobby_id.split("_")
    league, device, slot = parts[0], parts[1], parts[2]
    text = (f"🎮 <b>Лобби #{slot} ({league.upper()}/{device.upper()})</b>\n"
            f"👥 Игроков: {len(lobby['players'])}/10\n\n")
    for i, pid in enumerate(lobby["players"], 1):
        p = get_player(pid)
        if p:
            icon = "🤖" if p[13] else "👤"
            prem = " 👑" if (not p[13] and has_active_premium(pid)) else ""
            text += f"{i}. {icon} {p[1]}{prem} [Lvl {get_faceit_level(p[4])} | {p[4]} ELO]\n"
        else:
            text += f"{i}. {pid}\n"
    return text

def build_lobby_kb(lobby_id, uid):
    parts = lobby_id.split("_")
    league = parts[0]
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🚪 Выйти из лобби", callback_data=f"leave_{lobby_id}"))
    kb.add(types.InlineKeyboardButton("🔙 К списку", callback_data=f"lobby_{league}"))
    return kb

def broadcast_lobby_update(lobby_id, exclude_uid=None):
    lobby = active_lobbies.get(lobby_id)
    if not lobby: return
    text = build_lobby_text(lobby_id)
    for pid, (cid, mid) in list(lobby_player_messages.get(lobby_id, {}).items()):
        if pid == exclude_uid or pid not in lobby.get("players", []): continue
        try: bot.edit_message_text(text, cid, mid, reply_markup=build_lobby_kb(lobby_id, pid))
        except Exception: pass


@bot.callback_query_handler(func=lambda c: c.data == "find")
def cb_find(c):
    uid = c.from_user.id
    err = check_blocked(uid)
    if err:
        bot.answer_callback_query(c.id, "⚠️ Доступ ограничен", show_alert=True); return
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🎮 Default", callback_data="lobby_default"),
        types.InlineKeyboardButton("⭐ Quals", callback_data="lobby_quals"),
        types.InlineKeyboardButton("🔙 Назад", callback_data="back"),
    )
    bot.edit_message_text("🎮 Выбери лигу:", c.message.chat.id, c.message.message_id, reply_markup=kb)
    bot.answer_callback_query(c.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("lobby_") and len(c.data.split("_")) == 2)
def cb_lobby(c):
    uid = c.from_user.id
    league = c.data.split("_")[1]
    if league == "quals" and not has_quals_access(uid):
        bot.answer_callback_query(c.id, "⭐ Доступ к QUALS закрыт!", show_alert=True); return
    text = f"🎮 <b>ЛОББИ {league.upper()}</b>\n\nPC и Mobile могут играть вместе\n\n"
    kb = types.InlineKeyboardMarkup(row_width=2)
    for slot in range(1, 6):
        m_cnt = len(active_lobbies.get(f"{league}_mobile_{slot}", {}).get("players", []))
        p_cnt = len(active_lobbies.get(f"{league}_pc_{slot}", {}).get("players", []))
        text += f"Лобби #{slot}: Mobile({m_cnt}/10) | PC({p_cnt}/10)\n"
    for slot in range(1, 6):
        m_cnt = len(active_lobbies.get(f"{league}_mobile_{slot}", {}).get("players", []))
        p_cnt = len(active_lobbies.get(f"{league}_pc_{slot}", {}).get("players", []))
        kb.add(
            types.InlineKeyboardButton(f"M{slot}({m_cnt})", callback_data=f"join_{league}_mobile_{slot}"),
            types.InlineKeyboardButton(f"P{slot}({p_cnt})", callback_data=f"join_{league}_pc_{slot}"),
        )
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="find"))
    bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=kb)
    bot.answer_callback_query(c.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("join_"))
def cb_join(c):
    try:
        parts = c.data.split("_")
        if len(parts) < 4:
            bot.answer_callback_query(c.id, "❌ Ошибка формата"); return
        league, device, slot = parts[1], parts[2], int(parts[3])
        uid = c.from_user.id
        if c.from_user.username: update_tg_username(uid, c.from_user.username)
        err = check_blocked(uid)
        if err:
            bot.answer_callback_query(c.id, "⚠️ Доступ ограничен", show_alert=True); return
        if league == "quals" and not has_quals_access(uid):
            bot.answer_callback_query(c.id, "⭐ Доступ к QUALS закрыт!", show_alert=True); return
        if not is_registered(uid):
            bot.answer_callback_query(c.id, "❌ Вы не зарегистрированы! Напишите /start"); return
        if is_muted_check(uid):
            mins = get_mute_remaining(uid) // 60
            bot.answer_callback_query(c.id, f"🔇 Вы замучены! Осталось: {mins} мин.", show_alert=True); return
        lobby_id = f"{league}_{device}_{slot}"
        old = user_lobby.get(uid)
        if old and old in active_lobbies and uid in active_lobbies[old].get("players", []):
            active_lobbies[old]["players"].remove(uid)
            lobby_player_messages.get(old, {}).pop(uid, None)
            if not active_lobbies[old]["players"]:
                del active_lobbies[old]; lobby_player_messages.pop(old, None)
            else:
                broadcast_lobby_update(old)
            user_lobby.pop(uid, None)
        if lobby_id not in active_lobbies:
            active_lobbies[lobby_id] = {"players": [], "league": league, "device": device, "slot": slot, "status": "waiting"}
        lobby = active_lobbies[lobby_id]
        if lobby["status"] != "waiting":
            bot.answer_callback_query(c.id, "❌ Лобби уже в игре!", show_alert=True); return
        if len(lobby["players"]) >= 10:
            bot.answer_callback_query(c.id, "❌ Лобби полное!", show_alert=True); return
        if uid in lobby["players"]:
            bot.answer_callback_query(c.id, "✅ Вы уже в этом лобби!"); return
        lobby["players"].append(uid)
        user_lobby[uid] = lobby_id
        text = build_lobby_text(lobby_id)
        kb = build_lobby_kb(lobby_id, uid)
        try:
            bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=kb)
            if lobby_player_messages.get(lobby_id) is None:
                lobby_player_messages[lobby_id] = {}
            lobby_player_messages[lobby_id][uid] = (c.message.chat.id, c.message.message_id)
        except Exception: pass
        bot.answer_callback_query(c.id, f"✅ Вы вошли в лобби #{slot}!")
        broadcast_lobby_update(lobby_id, exclude_uid=uid)
        if len(lobby["players"]) >= 10:
            start_accept_phase(lobby_id)
    except Exception as e:
        print(f"Join error: {e}")
        bot.answer_callback_query(c.id, "❌ Ошибка")


@bot.callback_query_handler(func=lambda c: c.data.startswith("leave_"))
def cb_leave(c):
    uid = c.from_user.id
    lobby_id = c.data.split("leave_", 1)[1]
    lobby = active_lobbies.get(lobby_id)
    # Нельзя выйти во время фазы принятия
    if lobby and lobby.get("status") == "accepting":
        bot.answer_callback_query(c.id, "❌ Нельзя выйти во время принятия матча!", show_alert=True); return
    if lobby and uid in lobby.get("players", []):
        lobby["players"].remove(uid)
        lobby_player_messages.get(lobby_id, {}).pop(uid, None)
        if not lobby["players"]:
            del active_lobbies[lobby_id]; lobby_player_messages.pop(lobby_id, None)
        else:
            broadcast_lobby_update(lobby_id)
        user_lobby.pop(uid, None)
        bot.answer_callback_query(c.id, "✅ Вы вышли из лобби")
        bot.edit_message_text("⚡ ACTUAL FACEIT", c.message.chat.id, c.message.message_id, reply_markup=main_menu(uid))
    else:
        bot.answer_callback_query(c.id, "❌ Вы не в этом лобби")


# ==================== ФАЗА ПРИНЯТИЯ ====================
def build_accept_text(lobby_id):
    lobby = active_lobbies.get(lobby_id)
    if not lobby: return ""
    accepted = lobby.get("accepted", [])
    real_players = [u for u in lobby["players"] if not is_bot_player(u)]
    text = "🔔 <b>Матч найден! Статус принятия:</b>\n\n"
    for u in real_players:
        p = get_player(u)
        name = p[1] if p else str(u)
        prem = " 👑" if has_active_premium(u) else ""
        icon = "✅" if u in accepted else "⏳"
        text += f"{icon} {name}{prem}\n"
    accepted_cnt = len([u for u in accepted if not is_bot_player(u)])
    text += f"\n<b>{accepted_cnt}/{len(real_players)}</b> приняли"
    return text

def update_accept_status(lobby_id):
    msgs = accept_status_messages.get(lobby_id, {})
    if not msgs: return
    text = build_accept_text(lobby_id)
    for uid, (cid, mid) in list(msgs.items()):
        try: bot.edit_message_text(text, cid, mid)
        except Exception: pass

def delete_accept_status(lobby_id):
    msgs = accept_status_messages.pop(lobby_id, {})
    for uid, (cid, mid) in msgs.items():
        try: bot.delete_message(cid, mid)
        except Exception: pass

def delete_match_found(lobby_id):
    msgs = match_found_messages.pop(lobby_id, {})
    for uid, (cid, mid) in msgs.items():
        try: bot.delete_message(cid, mid)
        except Exception: pass

def delete_ban_status(lobby_id):
    msgs = ban_status_messages.pop(lobby_id, {})
    for uid, (cid, mid) in msgs.items():
        try: bot.delete_message(cid, mid)
        except Exception: pass

def start_accept_phase(lobby_id):
    lobby = active_lobbies.get(lobby_id)
    if not lobby: return
    lobby["status"] = "accepting"
    lobby["accepted"] = []
    lobby_player_messages.pop(lobby_id, None)
    accept_status_messages[lobby_id] = {}

    match_found_messages[lobby_id] = {}
    for uid in lobby["players"]:
        if is_bot_player(uid):
            lobby["accepted"].append(uid); continue
        try:
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("✅ Принять матч", callback_data=f"accept_{lobby_id}"))
            sent = bot.send_message(uid,
                f"🔔 <b>Матч найден!</b>\n\n"
                f"🏷 Лига: {lobby['league'].upper()}\n📱 Устройство: {lobby['device'].upper()}\n\n"
                f"⏱ У вас <b>{ACCEPT_TIMEOUT} секунд</b> чтобы принять.\nПри непринятии — предупреждение ⚠️",
                reply_markup=kb)
            match_found_messages[lobby_id][uid] = (sent.chat.id, sent.message_id)
        except Exception: pass

    # Статусное сообщение со списком игроков
    for uid in lobby["players"]:
        if is_bot_player(uid): continue
        try:
            text = build_accept_text(lobby_id)
            sent = bot.send_message(uid, text)
            accept_status_messages[lobby_id][uid] = (sent.chat.id, sent.message_id)
        except Exception: pass

    def check_accept():
        time.sleep(ACCEPT_TIMEOUT)
        lobby2 = active_lobbies.get(lobby_id)
        if not lobby2 or lobby2["status"] != "accepting": return
        not_accepted = [u for u in lobby2["players"] if u not in lobby2.get("accepted", [])]
        # Удаляем статусное сообщение
        delete_accept_status(lobby_id)
        if not_accepted:
            for uid in not_accepted:
                if is_bot_player(uid): continue
                warns = add_warn_to_player(uid)
                try:
                    if warns >= 3:
                        until = apply_mute(uid, hours=2)
                        dt = datetime.datetime.fromtimestamp(until).strftime("%H:%M")
                        bot.send_message(uid, f"⚠️ Варн {warns}/3 за непринятие.\n🔇 Замучен на 2 часа (до {dt}).")
                    else:
                        bot.send_message(uid, f"⚠️ Варн {warns}/3 за непринятие матча.")
                except Exception: pass
            for uid in lobby2["players"]:
                if is_bot_player(uid): continue
                try:
                    bot.send_message(uid, "❌ Матч отменён: не все приняли приглашение.")
                    user_lobby.pop(uid, None)
                except Exception: pass
            lobby_player_messages.pop(lobby_id, None)
            ban_status_messages.pop(lobby_id, None)
            del active_lobbies[lobby_id]
        else:
            start_map_ban_phase(lobby_id)

    threading.Thread(target=check_accept, daemon=True).start()


@bot.callback_query_handler(func=lambda c: c.data.startswith("accept_"))
def cb_accept(c):
    uid = c.from_user.id
    lobby_id = c.data.split("accept_", 1)[1]
    lobby = active_lobbies.get(lobby_id)
    if not lobby or lobby["status"] not in ("accepting",):
        bot.answer_callback_query(c.id, "❌ Матч уже недоступен"); return
    if uid not in lobby.get("accepted", []):
        lobby["accepted"].append(uid)
    bot.answer_callback_query(c.id, "✅ Принято!")
    # Убираем кнопку принятия
    try: bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=None)
    except Exception: pass
    # Обновляем статусное сообщение для всех
    update_accept_status(lobby_id)

    if len(lobby["accepted"]) >= len(lobby["players"]) and lobby["status"] == "accepting":
        lobby["status"] = "pre_mapban"
        # Удаляем статусное сообщение — матч принят всеми
        delete_accept_status(lobby_id)
        threading.Thread(target=start_map_ban_phase, args=(lobby_id,), daemon=True).start()


# ==================== БАН КАРТ ====================
def build_ban_status_text(lobby_id):
    lobby = active_lobbies.get(lobby_id)
    if not lobby: return ""
    ct_p = get_player(lobby.get("ct_captain"))
    t_p  = get_player(lobby.get("t_captain"))
    ct_name = ct_p[1] if ct_p else "CT капитан"
    t_name  = t_p[1]  if t_p  else "T капитан"
    bans = lobby.get("map_bans", [])
    remaining = lobby.get("maps_remaining", [])
    turn = lobby.get("ban_turn", "ct")
    lines = [f"🗺 <b>Бан карт</b>", "", f"💙 CT: <b>{ct_name}</b>", f"🧡 T: <b>{t_name}</b>", ""]
    if bans:
        lines.append("🚫 <b>Забанено:</b>")
        for b in bans:
            lines.append(f"  {'💙' if b['team']=='ct' else '🧡'} {b['map']}")
        lines.append("")
    if remaining:
        lines.append("✅ <b>Остались:</b>")
        for m in remaining: lines.append(f"  • {m}")
        lines.append("")
        turn_name = ct_name if turn == "ct" else t_name
        lines.append(f"⏳ Ход: {'💙' if turn=='ct' else '🧡'} <b>{turn_name}</b>")
    else:
        lines.append(f"🗺 <b>Карта выбрана: {lobby.get('map_name', '?')}</b>")
    return "\n".join(lines)

def send_ban_status_to_all(lobby_id):
    lobby = active_lobbies.get(lobby_id)
    if not lobby: return
    text = build_ban_status_text(lobby_id)
    if ban_status_messages.get(lobby_id) is None:
        ban_status_messages[lobby_id] = {}
    for uid in lobby["players"]:
        if is_bot_player(uid): continue
        existing = ban_status_messages[lobby_id].get(uid)
        if existing:
            cid, mid = existing
            try: bot.edit_message_text(text, cid, mid); continue
            except Exception: pass
        try:
            sent = bot.send_message(uid, text)
            ban_status_messages[lobby_id][uid] = (sent.chat.id, sent.message_id)
        except Exception: pass

def start_map_ban_phase(lobby_id):
    lobby = active_lobbies.get(lobby_id)
    if not lobby: return
    if lobby["status"] not in ("accepting", "pre_mapban"): return
    lobby["status"] = "mapban"
    lobby["maps_remaining"] = list(MAPS)
    lobby["map_bans"] = []
    lobby["ban_turn"] = "ct"
    lobby["ban_count"] = 0
    players = lobby["players"]
    # Удаляем сообщения "Матч найден!" перед началом бана карт
    delete_match_found(lobby_id)
    # Premium +7% шанс стать капитаном
    lobby["ct_captain"] = pick_captain(players[:5] if len(players) >= 5 else players)
    lobby["t_captain"]  = pick_captain(players[5:] if len(players) > 5 else players[-1:])
    send_ban_status_to_all(lobby_id)
    _do_ban_turn(lobby_id)

def _do_ban_turn(lobby_id):
    lobby = active_lobbies.get(lobby_id)
    if not lobby or lobby["status"] != "mapban": return
    turn = lobby["ban_turn"]
    captain_uid = lobby["ct_captain"] if turn == "ct" else lobby["t_captain"]
    if is_bot_player(captain_uid):
        def bot_auto_ban():
            time.sleep(random.uniform(1, 2))
            lobby2 = active_lobbies.get(lobby_id)
            if not lobby2 or lobby2["status"] != "mapban" or not lobby2["maps_remaining"]: return
            _apply_ban(lobby_id, captain_uid, random.choice(lobby2["maps_remaining"]))
        threading.Thread(target=bot_auto_ban, daemon=True).start()
    else:
        _send_ban_keyboard(lobby_id, captain_uid)

def _send_ban_keyboard(lobby_id, captain_uid):
    lobby = active_lobbies.get(lobby_id)
    if not lobby: return
    turn = lobby["ban_turn"]
    kb = types.InlineKeyboardMarkup(row_width=2)
    for m in lobby["maps_remaining"]:
        kb.add(types.InlineKeyboardButton(f"❌ {m}", callback_data=f"banmap_{lobby_id}_{m}"))
    try:
        sent = bot.send_message(captain_uid,
            f"{'💙' if turn=='ct' else '🧡'} <b>Твой ход — забань карту:</b>",
            reply_markup=kb)
        # Сохраняем сообщение хода для последующего удаления
        ban_turn_messages[lobby_id] = (sent.chat.id, sent.message_id)
    except Exception as e:
        print(f"Ban keyboard error: {e}")

def _apply_ban(lobby_id, banner_uid, map_name):
    lobby = active_lobbies.get(lobby_id)
    if not lobby or lobby["status"] != "mapban": return
    if map_name not in lobby["maps_remaining"]: return
    turn = lobby["ban_turn"]
    lobby["maps_remaining"].remove(map_name)
    lobby["map_bans"].append({"team": turn, "map": map_name})
    lobby["ban_count"] += 1
    if len(lobby["maps_remaining"]) == 1:
        lobby["map_name"] = lobby["maps_remaining"][0]
        send_ban_status_to_all(lobby_id)
        threading.Thread(target=lambda: (time.sleep(2), launch_match(lobby_id)), daemon=True).start()
    else:
        lobby["ban_turn"] = "t" if turn == "ct" else "ct"
        send_ban_status_to_all(lobby_id)
        _do_ban_turn(lobby_id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("banmap_"))
def cb_ban_map(c):
    uid = c.from_user.id
    raw = c.data[len("banmap_"):]
    raw_parts = raw.split("_")
    map_name = raw_parts[-1]
    lobby_id = "_".join(raw_parts[:-1])
    lobby = active_lobbies.get(lobby_id)
    if not lobby or lobby["status"] != "mapban":
        bot.answer_callback_query(c.id, "❌ Фаза бана уже завершена"); return
    turn = lobby["ban_turn"]
    expected_cap = lobby["ct_captain"] if turn == "ct" else lobby["t_captain"]
    if uid != expected_cap:
        bot.answer_callback_query(c.id, "❌ Сейчас не ваш ход!", show_alert=True); return
    if map_name not in lobby["maps_remaining"]:
        bot.answer_callback_query(c.id, "❌ Карта уже забанена"); return
    bot.answer_callback_query(c.id, f"✅ {map_name} забанена!")
    # Удаляем сообщение "твой ход" — не спамим
    try: bot.delete_message(c.message.chat.id, c.message.message_id)
    except Exception: pass
    ban_turn_messages.pop(lobby_id, None)
    _apply_ban(lobby_id, uid, map_name)


# ==================== ЗАПУСК МАТЧА ====================
def pline(uid):
    p = get_player(uid)
    if p:
        icon = "🤖" if p[13] else "👤"
        prem = " 👑" if (not p[13] and has_active_premium(uid)) else ""
        return f"{icon} {p[1]}{prem} [Lvl {get_faceit_level(p[4])} | {p[4]} ELO]"
    return str(uid)

def launch_match(lobby_id):
    lobby = active_lobbies.get(lobby_id)
    if not lobby or lobby["status"] not in ("accepting", "waiting", "mapban", "pre_mapban"): return
    lobby["status"] = "active"
    if not lobby.get("map_name"):
        lobby["map_name"] = random.choice(MAPS)
    match_id = get_next_match_id()
    lobby["match_id"] = match_id
    lobby["screenshots_count"] = 0
    lobby["reg_taken_by"] = None

    players = list(lobby["players"])
    placed, team_ct, team_t, party_groups, solo_players = set(), [], [], [], []
    for uid2 in players:
        if uid2 in placed: continue
        p_obj = get_party_of(uid2)
        if p_obj and len(p_obj["members"]) > 1:
            grp = [m for m in p_obj["members"] if m in players and m not in placed]
            if grp:
                party_groups.append(grp)
                for m in grp: placed.add(m)
        else:
            solo_players.append(uid2); placed.add(uid2)

    random.shuffle(party_groups); random.shuffle(solo_players)
    all_ordered = []
    for grp in party_groups: all_ordered.extend(grp)
    all_ordered.extend(solo_players)
    for uid2 in all_ordered:
        if len(team_ct) < 5: team_ct.append(uid2)
        else: team_t.append(uid2)

    lobby["team_ct"] = team_ct
    lobby["team_t"]  = team_t

    host_uid  = next((u for u in team_ct if not is_bot_player(u)), None)
    host_p    = get_player(host_uid) if host_uid else None
    host_game_id = host_p[2] if host_p else "—"
    host_name    = host_p[1] if host_p else "—"
    lobby["host_uid"]     = host_uid
    lobby["host_game_id"] = host_game_id

    match_text = (
        f"🎮 <b>МАТЧ #{match_id} НАЧАЛСЯ</b>\n\n"
        f"🏷 Лига: {lobby['league'].upper()}\n📱 Устройство: {lobby['device'].upper()}\n"
        f"🗺 Карта: <b>{lobby['map_name']}</b>\n"
        f"👑 Хост: <b>{host_name}</b> | Game ID: <code>{host_game_id}</code>\n\n"
        f"💙 <b>Команда CT</b>\n"
        + "\n".join([f"  {i+1}. {pline(u)}" for i, u in enumerate(team_ct)])
        + f"\n\n🧡 <b>Команда T</b>\n"
        + "\n".join([f"  {i+1}. {pline(u)}" for i, u in enumerate(team_t)])
    )

    if ADMIN_CHAT_ID:
        kb_admin = _build_admin_match_kb(lobby_id, match_id, 0)
        try:
            topic = bot.create_forum_topic(ADMIN_CHAT_ID, f"Match #{match_id}")
            thread_id = topic.message_thread_id
            lobby["admin_thread_id"] = thread_id
            sent = bot.send_message(ADMIN_CHAT_ID, match_text, reply_markup=kb_admin, message_thread_id=thread_id)
            lobby["admin_msg_id"] = sent.message_id
        except Exception:
            try:
                sent = bot.send_message(ADMIN_CHAT_ID, match_text, reply_markup=kb_admin)
                lobby["admin_msg_id"] = sent.message_id
                lobby["admin_thread_id"] = None
            except Exception as e:
                print(f"Admin chat error: {e}")

    for uid in players:
        if is_bot_player(uid): continue
        team = "💙 CT" if uid in team_ct else "🧡 T"
        player_text = (
            f"🎮 <b>МАТЧ #{match_id} НАЧАЛСЯ!</b>\n\n"
            f"🗺 Карта: <b>{lobby['map_name']}</b>\n"
            f"👥 Ваша команда: <b>{team}</b>\n"
            f"👑 Хост: <b>{host_name}</b>\n"
            f"🎮 Game ID хоста: <code>{host_game_id}</code>\n\n"
            f"💙 <b>Команда CT</b>\n"
            + "\n".join([f"  {i+1}. {pline(u)}" for i, u in enumerate(team_ct)])
            + f"\n\n🧡 <b>Команда T</b>\n"
            + "\n".join([f"  {i+1}. {pline(u)}" for i, u in enumerate(team_t)])
        )
        kb_player = types.InlineKeyboardMarkup()
        kb_player.add(types.InlineKeyboardButton("📸 Отправить скриншот", callback_data=f"send_result_{lobby_id}"))
        try: bot.send_message(uid, player_text, reply_markup=kb_player)
        except Exception: pass

    running_matches[lobby_id] = lobby
    parts = lobby_id.split("_")
    if len(parts) >= 3:
        league_r, device_r, slot_r = parts[0], parts[1], parts[2]
        active_lobbies[lobby_id] = {"players": [], "league": league_r, "device": device_r, "slot": slot_r, "status": "waiting"}
    else:
        active_lobbies.pop(lobby_id, None)

    lobby_player_messages.pop(lobby_id, None)
    delete_ban_status(lobby_id)
    for uid in players:
        user_lobby.pop(uid, None)


def _build_admin_match_kb(lobby_id, match_id, screenshots_count, taken_by=None):
    kb = types.InlineKeyboardMarkup(row_width=1)
    if taken_by:
        p = get_player(taken_by)
        name = p[1] if p else str(taken_by)
        kb.add(
            types.InlineKeyboardButton(f"📝 Регистрирует: {name} — ЗАНЯТО", callback_data="noop"),
            types.InlineKeyboardButton("🔓 Освободить регистрацию", callback_data=f"reg_release|{lobby_id}"),
        )
    else:
        kb.add(types.InlineKeyboardButton(f"📝 Зарегистрировать ({screenshots_count}📸)", callback_data=f"reg_match|{lobby_id}"))
    kb.add(
        types.InlineKeyboardButton("❌ Отменить матч",  callback_data=f"cancel_match|{lobby_id}"),
        types.InlineKeyboardButton("🔄 Перерегать",     callback_data=f"reregister_match|{lobby_id}"),
    )
    return kb


# ==================== СКРИНШОТЫ ====================
@bot.callback_query_handler(func=lambda c: c.data.startswith("send_result_"))
def cb_send_result(c):
    uid = c.from_user.id
    lobby_id = c.data.split("send_result_", 1)[1]
    lobby = running_matches.get(lobby_id)
    if not lobby or lobby.get("status") != "active":
        bot.answer_callback_query(c.id, "❌ Матч уже завершён", show_alert=True); return
    awaiting_screenshot[uid] = lobby_id
    bot.answer_callback_query(c.id)
    try: bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=None)
    except Exception: pass
    bot.send_message(uid, "📸 <b>Отправьте скриншот результатов</b>\n\nПрикрепите фото:")


@bot.message_handler(content_types=["photo", "document"])
def handle_player_screenshot(msg):
    uid = msg.from_user.id
    if not is_registered(uid) or is_bot_player(uid): return
    lobby_id = awaiting_screenshot.get(uid)
    if not lobby_id: return
    lobby = running_matches.get(lobby_id)
    if not lobby or lobby.get("status") != "active":
        awaiting_screenshot.pop(uid, None); return
    awaiting_screenshot.pop(uid, None)
    p = get_player(uid)
    name = p[1] if p else str(uid)
    match_id = lobby.get("match_id", "?")
    lobby["screenshots_count"] = lobby.get("screenshots_count", 0) + 1
    sc = lobby["screenshots_count"]
    if ADMIN_CHAT_ID:
        try:
            caption = f"📸 От <b>{name}</b> (<code>{uid}</code>) | Match #{match_id}"
            thread_id = lobby.get("admin_thread_id")
            kw = {"caption": caption}
            if thread_id: kw["message_thread_id"] = thread_id
            elif lobby.get("admin_msg_id"): kw["reply_to_message_id"] = lobby["admin_msg_id"]
            if msg.photo: bot.send_photo(ADMIN_CHAT_ID, msg.photo[-1].file_id, **kw)
            elif msg.document: bot.send_document(ADMIN_CHAT_ID, msg.document.file_id, **kw)
            if lobby.get("admin_msg_id"):
                new_kb = _build_admin_match_kb(lobby_id, match_id, sc, lobby.get("reg_taken_by"))
                edit_kw = {"reply_markup": new_kb}
                if thread_id: edit_kw["message_thread_id"] = thread_id
                try: bot.edit_message_reply_markup(ADMIN_CHAT_ID, lobby["admin_msg_id"], **edit_kw)
                except Exception: pass
        except Exception as e:
            print(f"Screenshot error: {e}")
    try: bot.reply_to(msg, f"✅ Скриншот принят! Всего: {sc}/10")
    except Exception: pass


# ==================== РЕГИСТРАЦИЯ РЕЗУЛЬТАТОВ ====================
match_registration = {}

def reg_send(uid, text, **kwargs):
    data = match_registration.get(uid, {})
    chat_id   = data.get("reply_chat_id", uid)
    thread_id = data.get("reply_thread_id")
    if thread_id: kwargs["message_thread_id"] = thread_id
    bot.send_message(chat_id, text, **kwargs)


@bot.callback_query_handler(func=lambda c: c.data.startswith("reg_match|"))
def cb_reg_match(c):
    uid = c.from_user.id
    if not is_game_reg_check(uid):
        bot.answer_callback_query(c.id, "❌ Нет доступа"); return
    lobby_id = c.data.split("|", 1)[1]
    lobby = running_matches.get(lobby_id)
    if not lobby or lobby.get("status") != "active":
        bot.answer_callback_query(c.id, "❌ Матч не найден или завершён"); return
    taken = lobby.get("reg_taken_by")
    if taken and taken != uid:
        p = get_player(taken)
        bot.answer_callback_query(c.id, f"❌ Регистрацию взял {p[1] if p else taken}", show_alert=True); return
    lobby["reg_taken_by"] = uid
    match_id = lobby.get("match_id", "?"); sc = lobby.get("screenshots_count", 0)
    try:
        new_kb = _build_admin_match_kb(lobby_id, match_id, sc, taken_by=uid)
        thread_id = lobby.get("admin_thread_id")
        edit_kw = {"reply_markup": new_kb}
        if thread_id: edit_kw["message_thread_id"] = thread_id
        bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, **edit_kw)
    except Exception: pass
    bot.answer_callback_query(c.id, "✅ Регистрация захвачена!")
    def pln(uid2):
        p = get_player(uid2); return f"{p[1]} — <code>{uid2}</code>" if p else str(uid2)
    ct_list = "\n".join([pln(u) for u in lobby.get("team_ct", [])])
    t_list  = "\n".join([pln(u) for u in lobby.get("team_t",  [])])
    reply_chat_id   = c.message.chat.id
    reply_thread_id = getattr(c.message, "message_thread_id", None)
    instructions = (
        f"📋 <b>Регистрация матча #{match_id}</b>\n\n"
        f"💙 <b>CT</b>\n{ct_list}\n\n🧡 <b>T</b>\n{t_list}\n\n"
        f"━━━━━━━━━━━━━━━━\n\n<b>Шаг 1/3</b> — Введи счёт:\nФормат: <code>13:11</code>"
    )
    match_registration[uid] = {"lobby_id": lobby_id, "step": "score",
                                "reply_chat_id": reply_chat_id, "reply_thread_id": reply_thread_id}
    send_kw = {"parse_mode": "HTML"}
    if reply_thread_id: send_kw["message_thread_id"] = reply_thread_id
    bot.send_message(reply_chat_id, instructions, **send_kw)


@bot.callback_query_handler(func=lambda c: c.data.startswith("reg_release|"))
def cb_reg_release(c):
    uid = c.from_user.id
    if not is_game_reg_check(uid):
        bot.answer_callback_query(c.id, "❌ Нет доступа"); return
    lobby_id = c.data.split("|", 1)[1]
    lobby = running_matches.get(lobby_id)
    if not lobby:
        bot.answer_callback_query(c.id, "❌ Матч не найден"); return
    lobby["reg_taken_by"] = None
    match_id = lobby.get("match_id", "?"); sc = lobby.get("screenshots_count", 0)
    try:
        new_kb = _build_admin_match_kb(lobby_id, match_id, sc)
        thread_id = lobby.get("admin_thread_id")
        edit_kw = {"reply_markup": new_kb}
        if thread_id: edit_kw["message_thread_id"] = thread_id
        bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, **edit_kw)
    except Exception: pass
    bot.answer_callback_query(c.id, "✅ Регистрация освобождена")


@bot.callback_query_handler(func=lambda c: c.data.startswith("cancel_match|"))
def cb_cancel_match(c):
    uid = c.from_user.id
    if not is_game_reg_check(uid):
        bot.answer_callback_query(c.id, "❌ Нет доступа"); return
    lobby_id = c.data.split("|", 1)[1]
    lobby = running_matches.get(lobby_id)
    if lobby:
        for puid in lobby.get("players", []):
            if is_bot_player(puid): continue
            try: bot.send_message(puid, "❌ Матч отменён администрацией.")
            except Exception: pass
        lobby["status"] = "cancelled"; lobby["reg_taken_by"] = None
    try:
        bot.edit_message_text(
            (c.message.text or "") + "\n\n<b>❌ МАТЧ ОТМЕНЁН</b>",
            c.message.chat.id, c.message.message_id, reply_markup=None)
    except Exception: pass
    bot.answer_callback_query(c.id, "✅ Матч отменён")


@bot.callback_query_handler(func=lambda c: c.data.startswith("reregister_match|"))
def cb_reregister_match(c):
    uid = c.from_user.id
    if not is_admin(uid):
        bot.answer_callback_query(c.id, "❌ Нет доступа"); return
    lobby_id = c.data.split("|", 1)[1]
    lobby = running_matches.get(lobby_id)
    if not lobby:
        bot.answer_callback_query(c.id, "❌ Матч не найден"); return
    was_finished = lobby.get("status") == "finished"
    if was_finished:
        revert_match_stats(lobby)
        match_id = lobby.get("match_id", "?")
        for puid in lobby.get("players", []):
            if is_bot_player(puid): continue
            try: bot.send_message(puid, f"🔄 <b>Матч #{match_id} открыт на перерегистрацию.</b>\nВаша статистика и ELO откатаны.")
            except Exception: pass
    lobby["status"] = "active"; lobby["reg_taken_by"] = None
    match_id = lobby.get("match_id", "?"); sc = lobby.get("screenshots_count", 0)
    try:
        new_kb = _build_admin_match_kb(lobby_id, match_id, sc)
        bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=new_kb)
    except Exception: pass
    bot.answer_callback_query(c.id, "✅ Стата откатана, матч открыт" if was_finished else "✅ Открыто для перерегистрации", show_alert=was_finished)


@bot.callback_query_handler(func=lambda c: c.data.startswith("annul_match|"))
def cb_annul_match(c):
    uid = c.from_user.id
    if not is_admin(uid):
        bot.answer_callback_query(c.id, "❌ Нет доступа"); return
    lobby_id = c.data.split("|", 1)[1]
    lobby = running_matches.get(lobby_id)
    if not lobby:
        bot.answer_callback_query(c.id, "❌ Матч не найден"); return
    match_id = lobby.get("match_id", "?"); was_finished = lobby.get("status") == "finished"
    revert_match_stats(lobby)
    lobby["status"] = "cancelled"; lobby["reg_taken_by"] = None
    for puid in lobby.get("players", []):
        if is_bot_player(puid): continue
        try:
            if was_finished:
                bot.send_message(puid, f"⚠️ <b>Матч #{match_id} аннулирован.</b>\nВаша статистика и ELO откатаны.")
            else:
                bot.send_message(puid, f"❌ Матч #{match_id} аннулирован администрацией.")
        except Exception: pass
    try:
        bot.edit_message_text((c.message.text or "") + "\n\n⚠️ <b>МАТЧ АННУЛИРОВАН</b>", c.message.chat.id, c.message.message_id, reply_markup=None)
    except Exception: pass
    bot.answer_callback_query(c.id, "✅ Матч аннулирован, стата откатана", show_alert=True)


@bot.message_handler(
    func=lambda m: m.from_user.id in match_registration
    and "step" in match_registration.get(m.from_user.id, {})
    and m.from_user.id not in rename_flow
    and m.from_user.id not in change_flow
    and m.text is not None
)
def handle_match_reg(msg):
    uid = msg.from_user.id
    if not is_game_reg_check(uid): return
    data = match_registration[uid]
    step = data["step"]
    text = msg.text.strip()
    lobby = running_matches.get(data["lobby_id"])
    if not lobby:
        del match_registration[uid]; reg_send(uid, "❌ Матч не найден", parse_mode="HTML"); return
    if step == "score":
        m = re.match(r"^(\d+):(\d+)$", text)
        if not m:
            reg_send(uid, "❌ Неверный формат. Пример: <code>13:11</code>", parse_mode="HTML"); return
        w, l = int(m.group(1)), int(m.group(2))
        data["score_w"] = w; data["score_l"] = l; data["step"] = "winner"
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("💙 CT победила", callback_data=f"regwinner_{data['lobby_id']}_ct"),
            types.InlineKeyboardButton("🧡 T победила",  callback_data=f"regwinner_{data['lobby_id']}_t"),
        )
        kw = {"reply_markup": kb, "parse_mode": "HTML"}
        if data.get("reply_thread_id"): kw["message_thread_id"] = data["reply_thread_id"]
        bot.send_message(data["reply_chat_id"], f"<b>Шаг 2/3</b> — Кто победил?\nСчёт: {w}:{l}", **kw)
    elif step == "stats_ct":
        stats = _parse_stats_block(text, lobby.get("team_ct", []))
        if stats is None:
            reg_send(uid, "❌ Формат: 5 строк, каждая <code>K D A</code>", parse_mode="HTML"); return
        data["stats_ct_raw"] = stats; data["step"] = "stats_t"
        t_names = ", ".join([get_player(u)[1] if get_player(u) else str(u) for u in lobby.get("team_t", [])])
        reg_send(uid, f"<b>Шаг 3/3</b> — Статистика T:\n<i>{t_names}</i>\n\nФормат (5 строк): <code>K D A</code>", parse_mode="HTML")
    elif step == "stats_t":
        stats = _parse_stats_block(text, lobby.get("team_t", []))
        if stats is None:
            reg_send(uid, "❌ Формат: 5 строк, каждая <code>K D A</code>", parse_mode="HTML"); return
        data["stats_t_raw"] = stats
        data["stats_ct"] = data["stats_ct_raw"]
        data["stats_t"] = data["stats_t_raw"]
        process_match_result(uid, data, lobby)
        del match_registration[uid]


@bot.callback_query_handler(func=lambda c: c.data.startswith("regwinner_"))
def cb_reg_winner(c):
    uid = c.from_user.id
    if not is_game_reg_check(uid):
        bot.answer_callback_query(c.id, "❌ Нет доступа"); return
    if uid not in match_registration:
        bot.answer_callback_query(c.id, "❌ Сессия не найдена"); return
    parts = c.data.split("_"); winner = parts[-1]
    lobby_id = "_".join(parts[1:-1])
    lobby = running_matches.get(lobby_id)
    if not lobby:
        bot.answer_callback_query(c.id, "❌ Матч не найден"); return
    data = match_registration[uid]
    data["winner"] = winner; data["step"] = "stats_ct"
    try: bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=None)
    except Exception: pass
    bot.answer_callback_query(c.id)
    ct_names = ", ".join([get_player(u)[1] if get_player(u) else str(u) for u in lobby.get("team_ct", [])])
    reg_send(uid,
        f"<b>Шаг 3/3</b> — Статистика CT:\n<i>{ct_names}</i>\n\n"
        f"Формат (5 строк): <code>K D A</code>\nПример:\n<code>13 2 5\n10 3 2\n8 5 1\n7 4 3\n5 6 0</code>",
        parse_mode="HTML")


def _parse_stats_block(text, team_uids):
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    if len(lines) != 5: return None
    result = []
    for i, line in enumerate(lines):
        nums = line.split()
        if len(nums) < 3: return None
        try: k, d, a = int(nums[0]), int(nums[1]), int(nums[2])
        except ValueError: return None
        uid = team_uids[i] if i < len(team_uids) else 0
        result.append({"user_id": uid, "kills": k, "deaths": d, "assists": a})
    return result


def revert_match_stats(lobby):
    changes = lobby.get("applied_changes", {})
    if not changes: return
    for uid, c in changes.items():
        if is_bot_player(uid): continue
        try:
            conn = _db(); cur = conn.cursor()
            cur.execute("SELECT elo, wins, losses, coins FROM players WHERE user_id=?", (uid,))
            old = cur.fetchone()
            if old:
                new_elo    = max(100, old[0] - c["elo_change"])
                new_wins   = max(0,   old[1] - (1 if c["won"] else 0))
                new_losses = max(0,   old[2] - (0 if c["won"] else 1))
                new_coins  = max(0,   old[3] - c["coins"])
                cur.execute(
                    "UPDATE players SET elo=?, wins=?, losses=?, "
                    "kills=MAX(0,kills-?), deaths=MAX(0,deaths-?), assists=MAX(0,assists-?), "
                    "coins=? WHERE user_id=?",
                    (new_elo, new_wins, new_losses, c["kills"], c["deaths"], c["assists"], new_coins, uid))
            conn.commit(); conn.close()
        except Exception as e:
            print(f"Revert error uid={uid}: {e}")
    lobby["applied_changes"] = {}


def _build_finished_match_kb(lobby_id):
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("🔄 Перерегистрировать (откат статы)", callback_data=f"reregister_match|{lobby_id}"),
        types.InlineKeyboardButton("❌ Аннулировать (откат статы)",       callback_data=f"annul_match|{lobby_id}"),
    )
    return kb


def process_match_result(admin_uid, data, lobby):
    winner = data["winner"]
    all_stats = {}
    for s in data.get("stats_ct", []):
        all_stats[s["user_id"]] = {**s, "won": winner == "ct"}
    for s in data.get("stats_t", []):
        all_stats[s["user_id"]] = {**s, "won": winner == "t"}
    match_id = lobby.get("match_id", "?")
    results = (
        f"📊 <b>РЕЗУЛЬТАТЫ МАТЧА #{match_id}</b>\n\n"
        f"🗺 Карта: {lobby.get('map_name','?')}\n"
        f"🏆 Победитель: {'💙 CT' if winner=='ct' else '🧡 T'}\n"
        f"📋 Счёт: {data['score_w']}:{data['score_l']}\n\n"
    )
    applied_changes = {}
    for uid, s in all_stats.items():
        p = get_player(uid); name = p[1] if p else str(uid)
        kills = s["kills"]
        if s["won"]:
            elo_change = 25 if kills >= 12 else 17; coins = random.randint(10, 20); icon = "🏆"
        else:
            elo_change = -15 if kills >= 11 else -25; coins = random.randint(5, 6); icon = "💀"
        applied_changes[uid] = {"elo_change": elo_change, "coins": coins,
                                 "kills": kills, "deaths": s["deaths"], "assists": s["assists"], "won": s["won"]}
        conn = _db(); cur = conn.cursor()
        cur.execute("SELECT elo, wins, losses, coins FROM players WHERE user_id=?", (uid,))
        old = cur.fetchone()
        if old:
            cur.execute(
                "UPDATE players SET elo=?, wins=?, losses=?, kills=kills+?, deaths=deaths+?, assists=assists+?, coins=? WHERE user_id=?",
                (max(100, old[0]+elo_change), old[1]+(1 if s["won"] else 0),
                 old[2]+(0 if s["won"] else 1), kills, s["deaths"], s["assists"], old[3]+coins, uid))
        conn.commit(); conn.close()
        results += f"{icon} <b>{name}</b> | {elo_change:+d} ELO | {kills}/{s['deaths']}/{s['assists']} K/D/A | +{coins} AC\n"
    lobby["applied_changes"] = applied_changes
    lobby["last_result_text"] = results
    for uid in lobby.get("players", []):
        if is_bot_player(uid): continue
        try: bot.send_message(uid, results)
        except Exception: pass
    lobby["status"] = "finished"; lobby["reg_taken_by"] = None
    save_match_to_history(lobby, data, all_stats)
    finished_kb = _build_finished_match_kb(_lobby_id_from(lobby))
    if ADMIN_CHAT_ID:
        lobby_id = _lobby_id_from(lobby)
        thread_id = lobby.get("admin_thread_id")
        send_kw = {"reply_markup": finished_kb}
        if thread_id: send_kw["message_thread_id"] = thread_id
        elif lobby.get("admin_msg_id"): send_kw["reply_to_message_id"] = lobby["admin_msg_id"]
        try:
            if lobby.get("admin_msg_id"):
                bot.edit_message_reply_markup(ADMIN_CHAT_ID, lobby["admin_msg_id"], reply_markup=None)
            sent = bot.send_message(ADMIN_CHAT_ID, results + "\n✅ <b>Матч зарегистрирован!</b>", **send_kw)
            lobby["result_msg_id"] = sent.message_id
        except Exception as e:
            print(f"Result send error: {e}")
    try: bot.send_message(admin_uid, f"✅ Матч #{match_id} зарегистрирован!")
    except Exception: pass


def _lobby_id_from(lobby):
    for lid, l in running_matches.items():
        if l is lobby: return lid
    return str(lobby.get("match_id", "unknown"))


# ==================== ДОБАВЛЕНИЕ БОТОВ ====================
@bot.callback_query_handler(func=lambda c: c.data == "add_bots_admin")
def cb_add_bots_admin(c):
    uid = c.from_user.id
    if not is_admin(uid):
        bot.answer_callback_query(c.id, "❌ Нет доступа"); return
    waiting = {lid: l for lid, l in active_lobbies.items() if l["status"] == "waiting" and len(l["players"]) < 10}
    if not waiting:
        bot.edit_message_text("❌ Нет активных лобби", c.message.chat.id, c.message.message_id); bot.answer_callback_query(c.id); return
    text = "🤖 <b>Выбери лобби:</b>\n\n"
    kb = types.InlineKeyboardMarkup(row_width=1)
    for lobby_id, lobby in waiting.items():
        text += f"• {lobby_id} — {len(lobby['players'])}/10\n"
        kb.add(types.InlineKeyboardButton(f"➕ {lobby_id} ({len(lobby['players'])}/10)", callback_data=f"fill_bots_{lobby_id}"))
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back"))
    bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=kb)
    bot.answer_callback_query(c.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("fill_bots_"))
def cb_fill_bots(c):
    uid = c.from_user.id
    if not is_admin(uid):
        bot.answer_callback_query(c.id, "❌ Нет доступа"); return
    lobby_id = c.data[len("fill_bots_"):]
    lobby = active_lobbies.get(lobby_id)
    if not lobby or lobby["status"] != "waiting":
        bot.answer_callback_query(c.id, "❌ Лобби недоступно"); return
    bots = get_bots(); added = 0
    for bot_id, _ in bots:
        if len(lobby["players"]) >= 10: break
        if bot_id not in lobby["players"]:
            lobby["players"].append(bot_id); user_lobby[bot_id] = lobby_id; added += 1
    if added > 0:
        bot.answer_callback_query(c.id, f"✅ Добавлено {added} ботов!")
        if len(lobby["players"]) >= 10: start_accept_phase(lobby_id)
    else:
        bot.answer_callback_query(c.id, "❌ Не удалось добавить ботов")


# ==================== МАГАЗИН ====================
@bot.callback_query_handler(func=lambda c: c.data == "shop")
def cb_shop(c):
    uid = c.from_user.id
    p = get_player(uid); coins = p[5] if p else 0
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("🖼 Декор", callback_data="shop_cat_decor"),
        types.InlineKeyboardButton("📦 Товары", callback_data="shop_cat_goods"),
        types.InlineKeyboardButton("💳 Купить ActualCoin", callback_data="buy_coins"),
        types.InlineKeyboardButton("🔙 Назад", callback_data="back"),
    )
    bot.edit_message_text(f"🛒 <b>МАГАЗИН</b>\n💰 Баланс: <b>{coins} AC</b>\n\nВыберите категорию:", c.message.chat.id, c.message.message_id, reply_markup=kb)
    bot.answer_callback_query(c.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("shop_cat_"))
def cb_shop_category(c):
    uid = c.from_user.id
    category = c.data.split("shop_cat_")[1]
    if category == "decor":
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="shop"))
        bot.edit_message_text("🚧 <b>Декор — В разработке</b>", c.message.chat.id, c.message.message_id, reply_markup=kb)
        bot.answer_callback_query(c.id); return
    p = get_player(uid); coins = p[5] if p else 0
    items = get_shop_items_by_category(category)
    if not items:
        bot.answer_callback_query(c.id, "❌ Нет товаров"); return
    kb = types.InlineKeyboardMarkup(row_width=1)
    for item_id, name, desc, price, item_type in items:
        owned = has_item_in_inventory(uid, item_id)
        stackable = item_type in {"sticker", "unwarn", "x2coins", "rename"}
        label = (f"✅ {name} — {price} AC" if (owned and not stackable) else f"🛍 {name} — {price} AC")
        kb.add(types.InlineKeyboardButton(label, callback_data=f"shop_item_{item_id}"))
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="shop"))
    bot.edit_message_text(f"🛒 <b>{CATEGORY_NAMES.get(category, category)}</b>\n💰 {coins} AC\n\nНажми для покупки:", c.message.chat.id, c.message.message_id, reply_markup=kb)
    bot.answer_callback_query(c.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("shop_item_"))
def cb_shop_item(c):
    uid = c.from_user.id
    item_id = int(c.data.split("shop_item_")[1])
    item = get_shop_item(item_id)
    if not item:
        bot.answer_callback_query(c.id, "❌ Товар не найден"); return
    p = get_player(uid); coins = p[5] if p else 0
    iid, name, desc, category, price, item_type = item
    if category == "decor":
        bot.answer_callback_query(c.id, "🚧 В разработке", show_alert=True); return
    owned = has_item_in_inventory(uid, item_id)
    stackable = item_type in {"sticker", "unwarn", "x2coins", "rename"}
    status_line = "\n✅ <i>Уже куплено</i>" if (owned and not stackable) else ""
    text = f"🛍 <b>{name}</b>\n📝 {desc}\n💰 Цена: <b>{price} AC</b>\n💳 Баланс: <b>{coins} AC</b>{status_line}"
    kb = types.InlineKeyboardMarkup(row_width=1)
    if owned and not stackable:
        kb.add(types.InlineKeyboardButton("✅ Уже куплено", callback_data="noop"))
    else:
        kb.add(types.InlineKeyboardButton(f"✅ Купить за {price} AC", callback_data=f"shop_buy_{item_id}"))
    kb.add(types.InlineKeyboardButton("🔙 К категории", callback_data=f"shop_cat_{category}"))
    bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=kb)
    bot.answer_callback_query(c.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("shop_buy_"))
def cb_shop_buy(c):
    uid = c.from_user.id
    item_id = int(c.data.split("shop_buy_")[1])
    success, message = buy_item(uid, item_id)
    if success:
        item = get_shop_item(item_id); category = item[3] if item else "goods"
        p = get_player(uid); new_coins = p[5] if p else 0
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(types.InlineKeyboardButton("🎒 Инвентарь", callback_data="inv"),
               types.InlineKeyboardButton("🔙 К категории", callback_data=f"shop_cat_{category}"))
        bot.edit_message_text(f"{message}\n\n💰 Остаток: <b>{new_coins} AC</b>", c.message.chat.id, c.message.message_id, reply_markup=kb)
        bot.answer_callback_query(c.id, "✅ Куплено!")
    else:
        bot.answer_callback_query(c.id, message, show_alert=True)


@bot.callback_query_handler(func=lambda c: c.data == "noop")
def cb_noop(c): bot.answer_callback_query(c.id)


# ==================== ИНВЕНТАРЬ ====================
@bot.callback_query_handler(func=lambda c: c.data == "inv")
def cb_inventory(c):
    uid = c.from_user.id
    items = get_inventory(uid)
    activatable_types = {"premium", "x2coins", "unwarn", "rename", "frame", "sticker", "animation", "quals"}
    kb = types.InlineKeyboardMarkup(row_width=1)
    if not items:
        text = "🎒 <b>ИНВЕНТАРЬ</b>\n\nУ вас пока нет предметов."
        kb.add(types.InlineKeyboardButton("🛒 В магазин", callback_data="shop"),
               types.InlineKeyboardButton("🔙 Назад", callback_data="back"))
        bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=kb)
        bot.answer_callback_query(c.id); return
    text = "🎒 <b>ИНВЕНТАРЬ</b>\n\nНажмите на предмет чтобы активировать:\n\n"
    for inv_id, name, category, item_type, purchased_at, is_activated, s_item_id in items:
        cat_icon = CATEGORY_ICONS.get(category, "📦")
        crown = " 👑" if item_type == "premium" and is_activated else ""
        if item_type in activatable_types:
            if is_activated:
                kb.add(types.InlineKeyboardButton(f"✅ {cat_icon} {name}{crown} (активирован)", callback_data="noop"))
            else:
                kb.add(types.InlineKeyboardButton(f"▶️ {cat_icon} {name} — активировать", callback_data=f"activate_{inv_id}_{item_type}"))
        else:
            kb.add(types.InlineKeyboardButton(f"📦 {cat_icon} {name}", callback_data="noop"))
    kb.add(types.InlineKeyboardButton("🛒 В магазин", callback_data="shop"),
           types.InlineKeyboardButton("🔙 Назад", callback_data="back"))
    bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=kb)
    bot.answer_callback_query(c.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("activate_"))
def cb_activate_item(c):
    uid = c.from_user.id
    try:
        parts = c.data.split("_", 2); inv_id = int(parts[1]); item_type = parts[2]
    except Exception:
        bot.answer_callback_query(c.id, "❌ Ошибка"); return
    conn = _db(); cur = conn.cursor()
    cur.execute("SELECT s.name, i.is_activated FROM inventory i JOIN shop_items s ON i.item_id=s.id WHERE i.id=? AND i.user_id=?", (inv_id, uid))
    row = cur.fetchone(); conn.close()
    if not row:
        bot.answer_callback_query(c.id, "❌ Предмет не найден"); return
    item_name, is_activated = row
    if is_activated:
        bot.answer_callback_query(c.id, "✅ Предмет уже активирован", show_alert=True); return
    result, msg_text = activate_inventory_item(inv_id, uid, item_type, item_name)
    if result == "rename":
        rename_flow[uid] = {"inv_id": inv_id}
        bot.answer_callback_query(c.id)
        bot.send_message(uid, msg_text); return
    if result:
        bot.answer_callback_query(c.id, "✅ Активировано!", show_alert=True)
        try: bot.send_message(uid, msg_text)
        except Exception: pass
    else:
        bot.answer_callback_query(c.id, msg_text, show_alert=True)


@bot.message_handler(func=lambda m: m.from_user.id in rename_flow)
def handle_rename_flow(msg):
    uid = msg.from_user.id
    new_nick = msg.text.strip()
    if not (2 <= len(new_nick) <= 20):
        bot.send_message(uid, "❌ Никнейм 2-20 символов."); return
    if nick_taken(new_nick, exclude_uid=uid):
        bot.send_message(uid, "❌ <b>Этот никнейм уже занят!</b>"); return
    inv_id = rename_flow.pop(uid)["inv_id"]
    conn = _db()
    conn.execute("UPDATE players SET username=? WHERE user_id=?", (new_nick, uid))
    conn.execute("UPDATE inventory SET is_activated=1, activated_at=strftime('%s','now') WHERE id=?", (inv_id,))
    conn.commit(); conn.close()
    bot.send_message(uid, f"✅ Ник изменён на <b>{new_nick}</b>!")


# ==================== ПОКУПКА МОНЕТ ====================
@bot.callback_query_handler(func=lambda c: c.data == "buy_coins")
def cb_buy_coins(c):
    uid = c.from_user.id
    p = get_player(uid); coins = p[5] if p else 0
    kb = types.InlineKeyboardMarkup(row_width=1)
    for i, (name, coins_amount, stars, price_label) in enumerate(COIN_PACKAGES):
        kb.add(types.InlineKeyboardButton(f"⭐ {name}: {coins_amount} AC — {stars} Stars ({price_label})", callback_data=f"buy_pkg_{i}"))
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back"))
    bot.edit_message_text(f"💳 <b>КУПИТЬ ActualCoin</b>\n💰 Баланс: <b>{coins} AC</b>\n\n⭐ Telegram Stars\nВыберите пакет:", c.message.chat.id, c.message.message_id, reply_markup=kb)
    bot.answer_callback_query(c.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_pkg_"))
def cb_buy_package(c):
    uid = c.from_user.id
    pkg_idx = int(c.data.split("buy_pkg_")[1])
    if pkg_idx < 0 or pkg_idx >= len(COIN_PACKAGES):
        bot.answer_callback_query(c.id, "❌ Пакет не найден"); return
    name, coins_amount, stars, price_label = COIN_PACKAGES[pkg_idx]
    bot.answer_callback_query(c.id)
    try:
        bot.send_invoice(chat_id=uid, title=f"💰 {coins_amount} ActualCoin",
                         description=f"Пакет «{name}»: {coins_amount} AC для ACTUAL FACEIT",
                         invoice_payload=f"coins_{pkg_idx}_{uid}",
                         provider_token="", currency="XTR",
                         prices=[types.LabeledPrice(label=f"{coins_amount} AC", amount=stars)],
                         start_parameter=f"buy_coins_{pkg_idx}")
    except Exception as e:
        bot.send_message(uid, f"❌ Ошибка создания счёта: {e}")


@bot.pre_checkout_query_handler(func=lambda q: True)
def pre_checkout(query): bot.answer_pre_checkout_query(query.id, ok=True)


@bot.message_handler(content_types=["successful_payment"])
def successful_payment(msg):
    uid = msg.from_user.id
    payload = msg.successful_payment.invoice_payload
    try:
        _, pkg_idx_str, _ = payload.split("_", 2)
        name, coins_amount, stars, _ = COIN_PACKAGES[int(pkg_idx_str)]
        add_coins_to_player(uid, coins_amount)
        p = get_player(uid)
        bot.send_message(uid, f"✅ <b>Оплата прошла!</b>\n💰 Начислено: <b>{coins_amount} AC</b>\n💳 Баланс: <b>{p[5] if p else '?'} AC</b>")
        if ADMIN_ID:
            bot.send_message(ADMIN_ID, f"💳 Покупка!\nПользователь: {uid}\nПакет: {name} ({coins_amount} AC)\nОплачено: {stars} Stars")
    except Exception as e:
        bot.send_message(uid, f"✅ Оплата получена, монеты будут начислены вручную. Ошибка: {e}")


# ==================== РЕДАКТИРОВАНИЕ СТАТЫ ====================
STAT_FIELDS = {
    "kills":   ("kills",   "🔫 Убийства"),
    "deaths":  ("deaths",  "💀 Смерти"),
    "assists": ("assists", "🤝 Ассисты"),
    "wins":    ("wins",    "🏆 Победы"),
    "losses":  ("losses",  "❌ Поражения"),
    "coins":   ("coins",   "💰 Монеты"),
    "elo":     ("elo",     "📊 ELO"),
}

@bot.callback_query_handler(func=lambda c: c.data.startswith("editstat_"))
def cb_editstat_pick(c):
    uid = c.from_user.id
    if not is_admin(uid):
        bot.answer_callback_query(c.id, "❌ Нет доступа"); return
    parts = c.data.split("_")
    field = parts[1]
    target_id = int(parts[2])
    p = get_player(target_id)
    if not p:
        bot.answer_callback_query(c.id, "❌ Игрок не найден"); return
    editstat_flow[uid] = {"field": field, "target_id": target_id}
    bot.answer_callback_query(c.id)
    _, label = STAT_FIELDS.get(field, (field, field))
    bot.send_message(uid, f"✏️ Введите новое значение для <b>{label}</b> игрока <b>{p[1]}</b>:", parse_mode="HTML")

@bot.message_handler(func=lambda m: m.from_user.id in editstat_flow and m.text is not None)
def handle_editstat_flow(msg):
    uid = msg.from_user.id
    if not is_admin(uid): return
    data = editstat_flow.pop(uid)
    field = data["field"]
    target_id = data["target_id"]
    p = get_player(target_id)
    if not p:
        bot.send_message(uid, "❌ Игрок не найден"); return
    try:
        value = int(msg.text.strip())
        if value < 0: raise ValueError
    except ValueError:
        bot.send_message(uid, "❌ Введите целое неотрицательное число"); return
    db_field, label = STAT_FIELDS.get(field, (field, field))
    conn = _db()
    conn.execute(f"UPDATE players SET {db_field}=? WHERE user_id=?", (value, target_id))
    conn.commit(); conn.close()
    bot.send_message(uid, f"✅ <b>{label}</b> игрока <b>{p[1]}</b> изменено на <b>{value}</b>!", parse_mode="HTML")
    try: bot.send_message(target_id, f"✏️ Администратор изменил вашу статистику (<b>{label}</b>: {value}).", parse_mode="HTML")
    except Exception: pass


# ==================== АДМИН ПАНЕЛЬ ====================
@bot.callback_query_handler(func=lambda c: c.data == "admin_panel")
def cb_admin_panel(c):
    uid = c.from_user.id
    if not is_admin(uid):
        bot.answer_callback_query(c.id, "❌ Нет доступа"); return
    players = get_all_players()
    active_count = sum(1 for l in running_matches.values() if l.get("status") == "active")
    text = (f"⚙️ <b>АДМИН ПАНЕЛЬ</b>\n\n"
            f"👥 Игроков: <b>{len(players)}</b>\n🎮 Лобби: <b>{len(active_lobbies)}</b>\n"
            f"🔴 Матчей: <b>{active_count}</b>\n\nВыберите действие:")
    maint_btn = ("🟢 Вкл. тех. работы" if not maintenance_mode else "🔴 Выкл. тех. работы")
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton(maint_btn,                 callback_data="admin_toggle_maintenance"),
        types.InlineKeyboardButton("👥 Список игроков",       callback_data="admin_players"),
        types.InlineKeyboardButton("🔍 Поиск по нику/ID",    callback_data="admin_search"),
        types.InlineKeyboardButton("🔍 Поиск по Game ID",    callback_data="admin_search_gameid"),
        types.InlineKeyboardButton("💰 Выдать монеты",        callback_data="admin_give_coins"),
        types.InlineKeyboardButton("📊 Изменить ELO",         callback_data="admin_set_elo"),
        types.InlineKeyboardButton("✏️ Изм. ник игрока",     callback_data="admin_change_nick"),
        types.InlineKeyboardButton("🎮 Изм. Game ID игрока", callback_data="admin_change_gid"),
        types.InlineKeyboardButton("📈 Редактировать стату",  callback_data="admin_edit_stats"),
        types.InlineKeyboardButton("⚠️ Выдать варн",          callback_data="admin_warn"),
        types.InlineKeyboardButton("🔇 Мут",                  callback_data="admin_mute"),
        types.InlineKeyboardButton("🔊 Размутить",            callback_data="admin_unmute"),
        types.InlineKeyboardButton("🔎 Вызвать на проверку",  callback_data="admin_check"),
        types.InlineKeyboardButton("✅ Снять проверку",       callback_data="admin_uncheck"),
        types.InlineKeyboardButton("🚫 Бан / Разбан",         callback_data="admin_ban"),
        types.InlineKeyboardButton("👑 Выдать/Снять админку", callback_data="admin_give_admin"),
        types.InlineKeyboardButton("🎮 Роль Гейм Рег",       callback_data="admin_give_game_reg"),
        types.InlineKeyboardButton("⭐ Quals доступ",         callback_data="admin_quals_access"),
        types.InlineKeyboardButton("🎁 Промокоды",            callback_data="admin_promos"),
        types.InlineKeyboardButton("🎮 Управление матчами",   callback_data="admin_matches"),
        types.InlineKeyboardButton("📋 История матчей",       callback_data="admin_match_history"),
        types.InlineKeyboardButton("📢 Рассылка",             callback_data="admin_broadcast"),
        types.InlineKeyboardButton("🔙 Назад",                callback_data="back"),
    )
    bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=kb)
    bot.answer_callback_query(c.id)


@bot.callback_query_handler(func=lambda c: c.data == "admin_toggle_maintenance")
def cb_toggle_maintenance(c):
    global maintenance_mode
    uid = c.from_user.id
    if not is_admin(uid):
        bot.answer_callback_query(c.id, "❌ Нет доступа"); return
    maintenance_mode = not maintenance_mode
    status = "🔴 ВКЛЮЧЕНЫ" if maintenance_mode else "🟢 ВЫКЛЮЧЕНЫ"
    bot.answer_callback_query(c.id, f"Технические работы: {status}", show_alert=True)
    # Обновляем панель чтобы кнопка поменяла цвет
    players = get_all_players()
    active_count = sum(1 for l in running_matches.values() if l.get("status") == "active")
    maint_status = "🔴 Тех. работы АКТИВНЫ" if maintenance_mode else "🟢 Бот работает в штатном режиме"
    text = (f"⚙️ <b>АДМИН ПАНЕЛЬ</b>\n\n"
            f"👥 Игроков: <b>{len(players)}</b>\n🎮 Лобби: <b>{len(active_lobbies)}</b>\n"
            f"🔴 Матчей: <b>{active_count}</b>\n\n{maint_status}\n\nВыберите действие:")
    maint_btn = ("🟢 Вкл. тех. работы" if not maintenance_mode else "🔴 Выкл. тех. работы")
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton(maint_btn,                 callback_data="admin_toggle_maintenance"),
        types.InlineKeyboardButton("👥 Список игроков",       callback_data="admin_players"),
        types.InlineKeyboardButton("🔍 Поиск по нику/ID",    callback_data="admin_search"),
        types.InlineKeyboardButton("🔍 Поиск по Game ID",    callback_data="admin_search_gameid"),
        types.InlineKeyboardButton("💰 Выдать монеты",        callback_data="admin_give_coins"),
        types.InlineKeyboardButton("📊 Изменить ELO",         callback_data="admin_set_elo"),
        types.InlineKeyboardButton("✏️ Изм. ник игрока",     callback_data="admin_change_nick"),
        types.InlineKeyboardButton("🎮 Изм. Game ID игрока", callback_data="admin_change_gid"),
        types.InlineKeyboardButton("📈 Редактировать стату",  callback_data="admin_edit_stats"),
        types.InlineKeyboardButton("⚠️ Выдать варн",          callback_data="admin_warn"),
        types.InlineKeyboardButton("🔇 Мут",                  callback_data="admin_mute"),
        types.InlineKeyboardButton("🔊 Размутить",            callback_data="admin_unmute"),
        types.InlineKeyboardButton("🔎 Вызвать на проверку",  callback_data="admin_check"),
        types.InlineKeyboardButton("✅ Снять проверку",       callback_data="admin_uncheck"),
        types.InlineKeyboardButton("🚫 Бан / Разбан",         callback_data="admin_ban"),
        types.InlineKeyboardButton("👑 Выдать/Снять админку", callback_data="admin_give_admin"),
        types.InlineKeyboardButton("🎮 Роль Гейм Рег",       callback_data="admin_give_game_reg"),
        types.InlineKeyboardButton("⭐ Quals доступ",         callback_data="admin_quals_access"),
        types.InlineKeyboardButton("🎁 Промокоды",            callback_data="admin_promos"),
        types.InlineKeyboardButton("🎮 Управление матчами",   callback_data="admin_matches"),
        types.InlineKeyboardButton("📋 История матчей",       callback_data="admin_match_history"),
        types.InlineKeyboardButton("📢 Рассылка",             callback_data="admin_broadcast"),
        types.InlineKeyboardButton("🔙 Назад",                callback_data="back"),
    )
    try:
        bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=kb)
    except Exception:
        pass


# ==================== ПРОМОКОДЫ (АДМИН) ====================
@bot.callback_query_handler(func=lambda c: c.data == "admin_promos")
def cb_admin_promos(c):
    uid = c.from_user.id
    if not is_admin(uid):
        bot.answer_callback_query(c.id, "❌ Нет доступа"); return
    codes = get_all_promo_codes()
    text = "🎁 <b>ПРОМОКОДЫ</b>\n\n"
    if codes:
        for code, rtype, rval, max_uses, uses, is_active in codes:
            status = "✅" if is_active else "❌"
            max_str = f"/{max_uses}" if max_uses > 0 else "/∞"
            rtype_names = {"coins": f"💰 {rval} AC", "premium": "👑 Premium", "quals": "⭐ Quals"}
            text += f"{status} <code>{code}</code> — {rtype_names.get(rtype, rtype)} | {uses}{max_str} исп.\n"
    else:
        text += "Промокодов нет."
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("➕ Создать промокод", callback_data="admin_promo_create"),
        types.InlineKeyboardButton("❌ Деактивировать промокод", callback_data="admin_promo_deactivate"),
        types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"),
    )
    bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=kb)
    bot.answer_callback_query(c.id)


@bot.callback_query_handler(func=lambda c: c.data == "admin_promo_create")
def cb_admin_promo_create(c):
    uid = c.from_user.id
    if not is_admin(uid):
        bot.answer_callback_query(c.id, "❌ Нет доступа"); return
    promo_admin_flow[uid] = {"step": "code"}
    bot.answer_callback_query(c.id)
    bot.send_message(uid,
        "🎁 <b>Создание промокода</b>\n\n"
        "<b>Шаг 1/4</b> — Введите код промокода (только буквы и цифры):\n"
        "Пример: <code>SUMMER2024</code>", parse_mode="HTML")


@bot.callback_query_handler(func=lambda c: c.data == "admin_promo_deactivate")
def cb_admin_promo_deactivate(c):
    uid = c.from_user.id
    if not is_admin(uid):
        bot.answer_callback_query(c.id, "❌ Нет доступа"); return
    promo_admin_flow[uid] = {"step": "deactivate"}
    bot.answer_callback_query(c.id)
    bot.send_message(uid, "❌ Введите код промокода для деактивации:")


@bot.callback_query_handler(func=lambda c: c.data.startswith("promo_reward_"))
def cb_promo_reward_type(c):
    uid = c.from_user.id
    if not is_admin(uid):
        bot.answer_callback_query(c.id, "❌ Нет доступа"); return
    if uid not in promo_admin_flow:
        bot.answer_callback_query(c.id, "❌ Сессия не найдена"); return
    reward_type = c.data.split("promo_reward_")[1]
    promo_admin_flow[uid]["reward_type"] = reward_type
    promo_admin_flow[uid]["step"] = "value"
    bot.answer_callback_query(c.id)
    try: bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=None)
    except Exception: pass
    if reward_type == "coins":
        bot.send_message(uid, "<b>Шаг 3/4</b> — Сколько монет выдавать?", parse_mode="HTML")
    elif reward_type == "premium":
        promo_admin_flow[uid]["reward_value"] = 0
        promo_admin_flow[uid]["step"] = "max_uses"
        bot.send_message(uid, "<b>Шаг 4/4</b> — Сколько раз можно использовать? (0 = неограничено)", parse_mode="HTML")
    elif reward_type == "quals":
        promo_admin_flow[uid]["reward_value"] = 0
        promo_admin_flow[uid]["step"] = "max_uses"
        bot.send_message(uid, "<b>Шаг 4/4</b> — Сколько раз можно использовать? (0 = неограничено)", parse_mode="HTML")


@bot.message_handler(func=lambda m: m.from_user.id in promo_admin_flow and m.text is not None)
def handle_promo_admin_flow(msg):
    uid = msg.from_user.id
    if not is_admin(uid): return
    data = promo_admin_flow.get(uid, {})
    step = data.get("step")
    text = msg.text.strip()

    if step == "code":
        if not re.match(r'^[A-Za-z0-9]+$', text):
            bot.send_message(uid, "❌ Только буквы и цифры. Попробуйте снова:"); return
        data["code"] = text.upper()
        data["step"] = "reward_type"
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("💰 Монеты", callback_data="promo_reward_coins"),
            types.InlineKeyboardButton("👑 Premium", callback_data="promo_reward_premium"),
            types.InlineKeyboardButton("⭐ Quals",   callback_data="promo_reward_quals"),
        )
        bot.send_message(uid, "<b>Шаг 2/4</b> — Выберите тип награды:", parse_mode="HTML", reply_markup=kb)

    elif step == "value":
        try: value = int(text)
        except ValueError:
            bot.send_message(uid, "❌ Введите число"); return
        data["reward_value"] = value
        data["step"] = "max_uses"
        bot.send_message(uid, "<b>Шаг 4/4</b> — Сколько раз можно использовать? (0 = неограничено)", parse_mode="HTML")

    elif step == "max_uses":
        try: max_uses = int(text)
        except ValueError:
            bot.send_message(uid, "❌ Введите число"); return
        code = data["code"]
        reward_type = data["reward_type"]
        reward_value = data.get("reward_value", 0)
        promo_admin_flow.pop(uid, None)
        ok = create_promo_code(code, reward_type, reward_value, max_uses)
        if ok:
            max_str = f"{max_uses}" if max_uses > 0 else "неограничено"
            rtype_names = {"coins": f"💰 {reward_value} AC", "premium": "👑 Premium", "quals": "⭐ Quals"}
            bot.send_message(uid,
                f"✅ <b>Промокод создан!</b>\n\n"
                f"Код: <code>{code}</code>\n"
                f"Награда: {rtype_names.get(reward_type, reward_type)}\n"
                f"Использований: {max_str}", parse_mode="HTML")
        else:
            bot.send_message(uid, f"❌ Промокод <code>{code}</code> уже существует!", parse_mode="HTML")

    elif step == "deactivate":
        promo_admin_flow.pop(uid, None)
        deactivate_promo_code(text)
        bot.send_message(uid, f"✅ Промокод <code>{text.upper()}</code> деактивирован.", parse_mode="HTML")


# ==================== УПРАВЛЕНИЕ МАТЧАМИ (АДМИН) ====================
@bot.callback_query_handler(func=lambda c: c.data == "admin_matches")
def cb_admin_matches(c):
    uid = c.from_user.id
    if not is_admin(uid):
        bot.answer_callback_query(c.id, "❌ Нет доступа"); return
    active = [(lid, l) for lid, l in running_matches.items() if l.get("status") == "active"]
    if not active:
        text = "🎮 <b>Управление матчами</b>\n\nАктивных матчей нет."
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
        bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=kb)
        bot.answer_callback_query(c.id); return
    text = "🎮 <b>Активные матчи</b>\n\n"
    kb = types.InlineKeyboardMarkup(row_width=1)
    for lid, l in active:
        mid = l.get("match_id", "?"); sc = l.get("screenshots_count", 0)
        text += f"• Match #{mid} — {lid} | 📸{sc}\n"
        kb.add(types.InlineKeyboardButton(f"⚙️ Match #{mid}", callback_data=f"admin_match_manage_{lid}"))
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
    bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=kb)
    bot.answer_callback_query(c.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("admin_match_manage_"))
def cb_admin_match_manage(c):
    uid = c.from_user.id
    if not is_admin(uid):
        bot.answer_callback_query(c.id, "❌ Нет доступа"); return
    lobby_id = c.data[len("admin_match_manage_"):]
    lobby = running_matches.get(lobby_id)
    if not lobby:
        bot.answer_callback_query(c.id, "❌ Матч не найден"); return
    match_id = lobby.get("match_id", "?"); sc = lobby.get("screenshots_count", 0)
    text = (f"⚙️ <b>Match #{match_id}</b>\n🏷 {lobby.get('league','').upper()}/{lobby.get('device','').upper()}\n"
            f"🗺 {lobby.get('map_name','?')}\n📸 {sc}")
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("🔄 Перерегать",  callback_data=f"reregister_match|{lobby_id}"),
        types.InlineKeyboardButton("❌ Отменить",    callback_data=f"cancel_match|{lobby_id}"),
        types.InlineKeyboardButton("🔙 Назад",       callback_data="admin_matches"),
    )
    bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=kb)
    bot.answer_callback_query(c.id)


@bot.callback_query_handler(func=lambda c: c.data == "admin_players")
def cb_admin_players(c):
    uid = c.from_user.id
    if not is_admin(uid):
        bot.answer_callback_query(c.id, "❌ Нет доступа"); return
    players = get_all_players()
    text = "👥 <b>СПИСОК ИГРОКОВ</b>\n\n"
    for p in players[:20]:
        uid2, name, elo, wins, losses, kills, deaths, coins, banned, warns = p
        ban_mark = " 🚫" if banned else ""
        warn_mark = f" ⚠️{warns}" if warns > 0 else ""
        prem = " 👑" if has_active_premium(uid2) else ""
        text += f"• <b>{name}</b>{prem}{ban_mark}{warn_mark} | ELO: {elo} | {wins}W/{losses}L\n"
    if len(players) > 20: text += f"\n<i>...и ещё {len(players)-20}</i>"
    if not players: text += "Игроков нет."
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
    bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=kb)
    bot.answer_callback_query(c.id)


@bot.callback_query_handler(func=lambda c: c.data == "admin_match_history")
def cb_admin_match_history(c):
    uid = c.from_user.id
    if not is_admin(uid):
        bot.answer_callback_query(c.id, "❌ Нет доступа"); return
    matches = get_match_history(10)
    text = "📋 <b>ИСТОРИЯ МАТЧЕЙ</b>\n\nМатчей нет." if not matches else "📋 <b>ИСТОРИЯ МАТЧЕЙ</b>\n\n"
    for row in matches:
        match_id, league, device, map_name, winner, score_w, score_l, finished_at = row
        dt = datetime.datetime.fromtimestamp(finished_at).strftime("%d.%m %H:%M") if finished_at else "?"
        winner_str = "💙 CT" if winner == "ct" else "🧡 T"
        text += f"🔢 <b>Match #{match_id}</b> | {dt}\n   {league.upper()}/{device.upper()} | {map_name}\n   {winner_str} | {score_w}:{score_l}\n\n"
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
    bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=kb)
    bot.answer_callback_query(c.id)


@bot.callback_query_handler(func=lambda c: c.data in [
    "admin_search", "admin_search_gameid", "admin_give_coins", "admin_set_elo",
    "admin_warn", "admin_ban", "admin_broadcast", "admin_give_admin",
    "admin_quals_access", "admin_give_game_reg", "admin_mute", "admin_unmute",
    "admin_check", "admin_uncheck", "admin_change_nick", "admin_change_gid",
    "admin_edit_stats",
])
def cb_admin_action(c):
    uid = c.from_user.id
    if not is_admin(uid):
        bot.answer_callback_query(c.id, "❌ Нет доступа"); return
    action = c.data.split("admin_")[1]
    prompts = {
        "search":         "🔍 Введите Telegram ID или никнейм:",
        "search_gameid":  "🔍 Введите Game ID игрока:",
        "give_coins":     "💰 Формат: <code>USER_ID КОЛИЧЕСТВО</code>",
        "set_elo":        "📊 Формат: <code>USER_ID НОВОЕ_ELO</code>",
        "change_nick":    "✏️ Введите Telegram ID для смены ника:",
        "change_gid":     "🎮 Введите Telegram ID для смены Game ID:",
        "warn":           "⚠️ Формат: <code>USER_ID ПРИЧИНА</code>",
        "ban":            "🚫 Введите Telegram ID для бана/разбана:",
        "broadcast":      "📢 Введите текст рассылки:",
        "give_admin":     "👑 Введите Telegram ID:",
        "quals_access":   "⭐ Введите Telegram ID:",
        "give_game_reg":  "🎮 Введите Telegram ID:",
        "mute":           "🔇 Формат: <code>USER_ID ЧАСЫ</code>",
        "unmute":         "🔊 Введите Telegram ID:",
        "check":          "🔎 Введите Telegram ID для вызова на проверку:",
        "uncheck":        "✅ Введите Telegram ID для снятия проверки:",
        "edit_stats":     "📈 Введите Telegram ID игрока для редактирования статы:",
    }
    admin_action[uid] = {"action": action}
    bot.answer_callback_query(c.id)
    bot.send_message(uid, prompts[action], parse_mode="HTML")


@bot.message_handler(
    func=lambda m: m.from_user.id in admin_action
    and "action" in admin_action.get(m.from_user.id, {})
    and m.from_user.id not in rename_flow
    and m.from_user.id not in match_registration
    and m.from_user.id not in change_flow
    and m.from_user.id not in editstat_flow
    and m.from_user.id not in promo_admin_flow
    and m.text is not None
)
def handle_admin_input(msg):
    uid = msg.from_user.id
    if not is_admin(uid): return
    action_data = admin_action.pop(uid)
    action = action_data.get("action", "")
    text = msg.text.strip()

    if action == "search":
        conn = _db(); cur = conn.cursor()
        if text.isdigit():
            cur.execute("SELECT user_id, username, game_id, elo, wins, losses, coins, is_banned, warns FROM players WHERE user_id=? AND is_bot=0", (int(text),))
        else:
            cur.execute("SELECT user_id, username, game_id, elo, wins, losses, coins, is_banned, warns FROM players WHERE username LIKE ? AND is_bot=0", (f"%{text}%",))
        rows = cur.fetchall(); conn.close()
        if not rows:
            bot.send_message(uid, "❌ Не найдено"); return
        result = "🔍 <b>Результат:</b>\n\n"
        for r in rows[:5]:
            pid, name, game_id, elo, wins, losses, coins, banned, warns = r
            lvl = get_faceit_level(elo)
            check = "🔎 На проверке" if is_on_check_db(pid) else ""
            prem = " 👑" if has_active_premium(pid) else ""
            result += (f"👤 <b>{name}</b>{prem} {check}\n  🆔 <code>{pid}</code> | Game ID: <code>{game_id}</code>\n"
                       f"  ELO: {elo} [Lvl {lvl}] | {wins}W/{losses}L\n  💰 {coins} AC | ⚠️ {warns}/3\n"
                       f"  {'🚫 Забанен' if banned else '✅ Активен'}\n\n")
        bot.send_message(uid, result, parse_mode="HTML")

    elif action == "search_gameid":
        p = get_player_by_game_id(text)
        if not p:
            bot.send_message(uid, f"❌ Игрок с Game ID <code>{text}</code> не найден", parse_mode="HTML"); return
        lvl = get_faceit_level(p[4])
        warns = p[15] if len(p) > 15 else 0
        check = "🔎 На проверке" if is_on_check_db(p[0]) else ""
        prem = " 👑" if has_active_premium(p[0]) else ""
        result = (f"🔍 <b>Найден по Game ID</b> {check}\n\n"
                  f"👤 <b>{p[1]}</b>{prem}\n  🆔 <code>{p[0]}</code>\n  🎮 <code>{p[2]}</code>\n"
                  f"  ELO: {p[4]} [Lvl {lvl}] | {p[6]}W/{p[7]}L\n  💰 {p[5]} AC | ⚠️ {warns}/3\n"
                  f"  {'🚫 Забанен' if (len(p)>14 and p[14]) else '✅ Активен'}")
        bot.send_message(uid, result, parse_mode="HTML")

    elif action == "edit_stats":
        try:
            target_id = int(text)
            p = get_player(target_id)
            if not p:
                bot.send_message(uid, "❌ Игрок не найден"); return
            kb = types.InlineKeyboardMarkup(row_width=2)
            kb.add(
                types.InlineKeyboardButton("🔫 Убийства",  callback_data=f"editstat_kills_{target_id}"),
                types.InlineKeyboardButton("💀 Смерти",    callback_data=f"editstat_deaths_{target_id}"),
                types.InlineKeyboardButton("🤝 Ассисты",   callback_data=f"editstat_assists_{target_id}"),
                types.InlineKeyboardButton("🏆 Победы",    callback_data=f"editstat_wins_{target_id}"),
                types.InlineKeyboardButton("❌ Поражения", callback_data=f"editstat_losses_{target_id}"),
                types.InlineKeyboardButton("💰 Монеты",    callback_data=f"editstat_coins_{target_id}"),
                types.InlineKeyboardButton("📊 ELO",       callback_data=f"editstat_elo_{target_id}"),
            )
            p_cur = get_player(target_id)
            info = (f"📈 <b>Редактирование: {p[1]}</b>\n\n"
                    f"🔫 Убийства: {p_cur[8]}\n💀 Смерти: {p_cur[9]}\n🤝 Ассисты: {p_cur[10]}\n"
                    f"🏆 Победы: {p_cur[6]}\n❌ Поражения: {p_cur[7]}\n"
                    f"📊 ELO: {p_cur[4]}\n💰 Монеты: {p_cur[5]}\n\nВыберите поле:")
            bot.send_message(uid, info, parse_mode="HTML", reply_markup=kb)
        except Exception:
            bot.send_message(uid, "❌ Введите числовой Telegram ID")

    elif action == "change_nick":
        try:
            target_id = int(text)
            p = get_player(target_id)
            if not p:
                bot.send_message(uid, "❌ Игрок не найден"); return
            change_flow[uid] = {"field": "admin_nick", "target_id": target_id}
            bot.send_message(uid, f"✏️ Введите новый никнейм для <b>{p[1]}</b>:", parse_mode="HTML")
        except Exception:
            bot.send_message(uid, "❌ Введите числовой Telegram ID")

    elif action == "change_gid":
        try:
            target_id = int(text)
            p = get_player(target_id)
            if not p:
                bot.send_message(uid, "❌ Игрок не найден"); return
            change_flow[uid] = {"field": "admin_id", "target_id": target_id}
            bot.send_message(uid, f"🎮 Введите новый Game ID для <b>{p[1]}</b>:", parse_mode="HTML")
        except Exception:
            bot.send_message(uid, "❌ Введите числовой Telegram ID")

    elif action == "give_coins":
        try:
            parts = text.split(); target_id, amount = int(parts[0]), int(parts[1])
            p = get_player(target_id)
            if not p:
                bot.send_message(uid, "❌ Не найден"); return
            add_coins_to_player(target_id, amount)
            p2 = get_player(target_id)
            bot.send_message(uid, f"✅ Выдано {amount} AC игроку <b>{p[1]}</b>\nБаланс: {p2[5]} AC", parse_mode="HTML")
            try: bot.send_message(target_id, f"💰 Вам выдано <b>{amount} AC</b>! Баланс: {p2[5]} AC", parse_mode="HTML")
            except Exception: pass
        except Exception:
            bot.send_message(uid, "❌ Формат: 123456789 500")

    elif action == "set_elo":
        try:
            parts = text.split(); target_id, new_elo = int(parts[0]), int(parts[1])
            p = get_player(target_id)
            if not p:
                bot.send_message(uid, "❌ Не найден"); return
            conn = _db(); conn.execute("UPDATE players SET elo=? WHERE user_id=?", (new_elo, target_id)); conn.commit(); conn.close()
            bot.send_message(uid, f"✅ ELO <b>{p[1]}</b>: {p[4]} → {new_elo}", parse_mode="HTML")
            try: bot.send_message(target_id, f"📊 ELO изменён: {p[4]} → <b>{new_elo}</b>", parse_mode="HTML")
            except Exception: pass
        except Exception:
            bot.send_message(uid, "❌ Формат: 123456789 1500")

    elif action == "warn":
        try:
            parts = text.split(maxsplit=1)
            target_id = int(parts[0]); reason = parts[1] if len(parts) > 1 else "Нарушение"
            p = get_player(target_id)
            if not p:
                bot.send_message(uid, "❌ Не найден"); return
            warns = add_warn_to_player(target_id)
            bot.send_message(uid, f"⚠️ Варн <b>{p[1]}</b> ({warns}/3)\nПричина: {reason}", parse_mode="HTML")
            try:
                if warns >= 3:
                    until = apply_mute(target_id, hours=2)
                    dt = datetime.datetime.fromtimestamp(until).strftime("%H:%M")
                    bot.send_message(target_id, f"⚠️ Варн {warns}/3! Причина: {reason}\n🔇 Замучен на 2ч (до {dt}).")
                else:
                    bot.send_message(target_id, f"⚠️ Предупреждение ({warns}/3)! Причина: {reason}")
            except Exception: pass
        except Exception:
            bot.send_message(uid, "❌ Формат: 123456789 Причина")

    elif action == "mute":
        try:
            parts = text.split(); target_id = int(parts[0]); hours = int(parts[1]) if len(parts) > 1 else 2
            p = get_player(target_id)
            if not p:
                bot.send_message(uid, "❌ Не найден"); return
            until = apply_mute(target_id, hours=hours)
            dt = datetime.datetime.fromtimestamp(until).strftime("%d.%m %H:%M")
            bot.send_message(uid, f"🔇 <b>{p[1]}</b> замучен {hours}ч (до {dt})", parse_mode="HTML")
            try: bot.send_message(target_id, f"🔇 Вы замучены на {hours}ч (до {dt}).")
            except Exception: pass
        except Exception:
            bot.send_message(uid, "❌ Формат: 123456789 2")

    elif action == "unmute":
        try:
            target_id = int(text); p = get_player(target_id)
            if not p:
                bot.send_message(uid, "❌ Не найден"); return
            conn = _db(); conn.execute("UPDATE players SET is_muted=0, mute_until=0 WHERE user_id=?", (target_id,)); conn.commit(); conn.close()
            bot.send_message(uid, f"🔊 <b>{p[1]}</b> размучен!", parse_mode="HTML")
            try: bot.send_message(target_id, "🔊 Вы размучены.")
            except Exception: pass
        except Exception:
            bot.send_message(uid, "❌ Введите числовой Telegram ID")

    elif action == "check":
        try:
            target_id = int(text); p = get_player(target_id)
            if not p:
                bot.send_message(uid, "❌ Не найден"); return
            conn = _db(); conn.execute("UPDATE players SET is_on_check=1, check_admin_id=? WHERE user_id=?", (uid, target_id)); conn.commit(); conn.close()
            if msg.from_user.username:
                update_tg_username(uid, msg.from_user.username)
            admin_tg = msg.from_user.username or str(uid)
            bot.send_message(uid, f"🔎 <b>{p[1]}</b> вызван на проверку!", parse_mode="HTML")
            try: bot.send_message(target_id, f"⚠️ <b>Вас вызвал на проверку @{admin_tg}</b>\n\nДоступ к боту ограничен.\nОбратитесь к @{admin_tg}.")
            except Exception: pass
        except Exception:
            bot.send_message(uid, "❌ Введите числовой Telegram ID")

    elif action == "uncheck":
        try:
            target_id = int(text); p = get_player(target_id)
            if not p:
                bot.send_message(uid, "❌ Не найден"); return
            conn = _db(); conn.execute("UPDATE players SET is_on_check=0, check_admin_id=0 WHERE user_id=?", (target_id,)); conn.commit(); conn.close()
            bot.send_message(uid, f"✅ Проверка с <b>{p[1]}</b> снята!", parse_mode="HTML")
            try: bot.send_message(target_id, "✅ Проверка завершена. Доступ к боту восстановлен!")
            except Exception: pass
        except Exception:
            bot.send_message(uid, "❌ Введите числовой Telegram ID")

    elif action == "ban":
        try:
            target_id = int(text); p = get_player(target_id)
            if not p:
                bot.send_message(uid, "❌ Не найден"); return
            currently_banned = len(p) > 14 and p[14] == 1
            conn = _db()
            if currently_banned:
                conn.execute("UPDATE players SET is_banned=0 WHERE user_id=?", (target_id,)); conn.commit(); conn.close()
                bot.send_message(uid, f"✅ <b>{p[1]}</b> разбанен!", parse_mode="HTML")
                try: bot.send_message(target_id, "✅ Вы разбанены!")
                except Exception: pass
            else:
                conn.execute("UPDATE players SET is_banned=1 WHERE user_id=?", (target_id,)); conn.commit(); conn.close()
                bot.send_message(uid, f"🚫 <b>{p[1]}</b> забанен!", parse_mode="HTML")
                try: bot.send_message(target_id, "🚫 Вы забанены.")
                except Exception: pass
        except Exception:
            bot.send_message(uid, "❌ Введите числовой Telegram ID")

    elif action == "give_admin":
        try:
            target_id = int(text); p = get_player(target_id)
            if not p:
                bot.send_message(uid, "❌ Не найден"); return
            new_val = 0 if p[11] == 1 else 1
            conn = _db(); conn.execute("UPDATE players SET is_admin=? WHERE user_id=?", (new_val, target_id)); conn.commit(); conn.close()
            status = "теперь администратор" if new_val else "лишён прав"
            bot.send_message(uid, f"👑 <b>{p[1]}</b> {status}!", parse_mode="HTML")
            try: bot.send_message(target_id, "👑 Вам выдан статус администратора!" if new_val else "❌ Права администратора сняты.")
            except Exception: pass
        except Exception:
            bot.send_message(uid, "❌ Введите числовой Telegram ID")

    elif action == "give_game_reg":
        try:
            target_id = int(text); p = get_player(target_id)
            if not p:
                bot.send_message(uid, "❌ Не найден"); return
            currently = len(p) > 17 and p[17] == 1
            new_val = 0 if currently else 1
            conn = _db(); conn.execute("UPDATE players SET is_game_reg=? WHERE user_id=?", (new_val, target_id)); conn.commit(); conn.close()
            status = "получил роль Гейм Рег" if new_val else "лишён роли Гейм Рег"
            bot.send_message(uid, f"🎮 <b>{p[1]}</b> {status}!", parse_mode="HTML")
            try: bot.send_message(target_id, "🎮 Вам выдана роль Гейм Рег!" if new_val else "❌ Роль Гейм Рег снята.")
            except Exception: pass
        except Exception:
            bot.send_message(uid, "❌ Введите числовой Telegram ID")

    elif action == "quals_access":
        try:
            target_id = int(text); p = get_player(target_id)
            if not p:
                bot.send_message(uid, "❌ Не найден"); return
            currently = len(p) > 16 and p[16] == 1
            new_val = 0 if currently else 1
            conn = _db(); conn.execute("UPDATE players SET quals_access=? WHERE user_id=?", (new_val, target_id)); conn.commit(); conn.close()
            status = "получил доступ к QUALS" if new_val else "лишён доступа к QUALS"
            bot.send_message(uid, f"⭐ <b>{p[1]}</b> {status}!", parse_mode="HTML")
            try: bot.send_message(target_id, "⭐ Вам открыт доступ к QUALS!" if new_val else "❌ Доступ к QUALS закрыт.")
            except Exception: pass
        except Exception:
            bot.send_message(uid, "❌ Введите числовой Telegram ID")

    elif action == "broadcast":
        players = get_all_players(); sent = failed = 0
        for player in players:
            try:
                bot.send_message(player[0], f"📢 <b>Сообщение от администрации:</b>\n\n{text}", parse_mode="HTML")
                sent += 1; time.sleep(0.05)
            except Exception:
                failed += 1
        bot.send_message(uid, f"📢 Рассылка завершена!\n✅ {sent} | ❌ {failed}")


# ==================== ГЕЙМ РЕГ ПАНЕЛЬ ====================
@bot.callback_query_handler(func=lambda c: c.data == "game_reg_panel")
def cb_game_reg_panel(c):
    uid = c.from_user.id
    if not is_game_reg_check(uid):
        bot.answer_callback_query(c.id, "❌ Нет доступа"); return
    active = [(lid, l) for lid, l in running_matches.items() if l.get("status") == "active"]
    if not active:
        text = "📋 <b>Регистрация матчей</b>\n\nАктивных матчей нет."
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back"))
        bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=kb)
        bot.answer_callback_query(c.id); return
    text = "📋 <b>Регистрация матчей</b>\n\n"
    kb = types.InlineKeyboardMarkup(row_width=1)
    for lid, l in active:
        mid = l.get("match_id","?"); sc = l.get("screenshots_count",0)
        taken = l.get("reg_taken_by")
        taken_info = ""
        if taken:
            tp = get_player(taken)
            taken_info = f" [занято: {tp[1] if tp else taken}]"
        text += f"• Match #{mid} | 📸{sc}{taken_info}\n"
        kb.add(types.InlineKeyboardButton(f"📝 Match #{mid} ({sc}📸){taken_info}", callback_data=f"reg_match|{lid}"))
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back"))
    bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=kb)
    bot.answer_callback_query(c.id)


# ==================== ПАТИ ====================
@bot.callback_query_handler(func=lambda c: c.data == "party_menu")
def cb_party_menu(c):
    uid = c.from_user.id
    if not is_registered(uid):
        bot.answer_callback_query(c.id, "❌ Вы не зарегистрированы! /start"); return
    bot.answer_callback_query(c.id)
    party = get_party_of(uid)
    if party:
        _show_party(c.message.chat.id, c.message.message_id, uid, party, edit=True)
    else:
        _create_party(uid, c.message.chat.id, c.message.message_id, edit=True)

def _create_party(uid, chat_id, msg_id, edit=False):
    party_id = str(uid)
    parties[party_id] = {"leader": uid, "members": [uid], "invites": {}}
    user_party[uid] = party_id
    _show_party(chat_id, msg_id, uid, parties[party_id], edit=edit)

def _show_party(chat_id, msg_id, uid, party, edit=False):
    leader = party["leader"]; members = party["members"]
    max_size = get_party_max_size(party)
    text = "👥 <b>Ваша пати</b>\n\n"
    for m in members:
        p = get_player(m); name = p[1] if p else str(m)
        crown = " 👑" if m == leader else ""
        prem = " 👑" if has_active_premium(m) else ""
        text += f"• {name}{crown}{prem}\n"
    text += f"\n👤 {len(members)}/{max_size}"
    if max_size == 2: text += "\n💡 Premium расширяет до 3"
    kb = types.InlineKeyboardMarkup(row_width=1)
    if uid == leader:
        if len(members) < max_size:
            kb.add(types.InlineKeyboardButton("➕ Пригласить по TG ID", callback_data="party_invite"))
        else:
            kb.add(types.InlineKeyboardButton(f"❌ Пати полная ({max_size}/{max_size})", callback_data="noop"))
        if len(members) > 1:
            kb.add(types.InlineKeyboardButton("❌ Расформировать", callback_data="party_disband"))
        else:
            kb.add(types.InlineKeyboardButton("🚪 Выйти", callback_data="party_leave"))
    else:
        kb.add(types.InlineKeyboardButton("🚪 Выйти из пати", callback_data="party_leave"))
    kb.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back"))
    if edit:
        try: bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb); return
        except Exception: pass
    bot.send_message(chat_id, text, reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data == "party_invite")
def cb_party_invite(c):
    uid = c.from_user.id
    party = get_party_of(uid)
    if not party or party["leader"] != uid:
        bot.answer_callback_query(c.id, "❌ Вы не лидер"); return
    max_size = get_party_max_size(party)
    if len(party["members"]) >= max_size:
        bot.answer_callback_query(c.id, f"❌ Пати полная ({max_size}/{max_size})", show_alert=True); return
    bot.answer_callback_query(c.id)
    awaiting_party_invite[uid] = True
    bot.send_message(uid, "👤 Введите <b>Telegram ID</b> игрока:", parse_mode="HTML")


@bot.message_handler(func=lambda m: m.from_user.id in awaiting_party_invite and m.text is not None)
def handle_party_invite_id(msg):
    uid = msg.from_user.id
    awaiting_party_invite.pop(uid, None)
    try: target_id = int(msg.text.strip())
    except ValueError:
        bot.send_message(uid, "❌ Введите числовой Telegram ID"); return
    if target_id == uid:
        bot.send_message(uid, "❌ Нельзя пригласить себя"); return
    if not is_registered(target_id):
        bot.send_message(uid, "❌ Игрок не зарегистрирован"); return
    if target_id in user_party:
        bot.send_message(uid, "❌ Игрок уже в пати"); return
    party_id = user_party.get(uid); party = parties.get(party_id)
    if not party or party["leader"] != uid:
        bot.send_message(uid, "❌ Вы не лидер"); return
    max_size = get_party_max_size(party)
    if len(party["members"]) >= max_size:
        bot.send_message(uid, f"❌ Пати полная ({max_size}/{max_size})"); return
    party["invites"][target_id] = uid
    p_leader = get_player(uid); leader_name = p_leader[1] if p_leader else str(uid)
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ Принять", callback_data=f"party_accept_{party_id}"),
        types.InlineKeyboardButton("❌ Отклонить", callback_data=f"party_decline_{party_id}"),
    )
    try:
        bot.send_message(target_id, f"👥 <b>Приглашение в пати!</b>\nЛидер: <b>{leader_name}</b>\n{len(party['members'])}/{max_size}", reply_markup=kb)
        bot.send_message(uid, "✅ Приглашение отправлено")
    except Exception:
        bot.send_message(uid, "❌ Не удалось отправить приглашение")
        party["invites"].pop(target_id, None)


@bot.callback_query_handler(func=lambda c: c.data.startswith("party_accept_"))
def cb_party_accept(c):
    uid = c.from_user.id
    party_id = c.data.split("party_accept_", 1)[1]; party = parties.get(party_id)
    if not party:
        bot.answer_callback_query(c.id, "❌ Пати не найдена"); return
    if uid not in party.get("invites", {}):
        bot.answer_callback_query(c.id, "❌ Приглашение устарело"); return
    if uid in user_party:
        bot.answer_callback_query(c.id, "❌ Вы уже в другой пати", show_alert=True); return
    max_size = get_party_max_size(party)
    if len(party["members"]) >= max_size:
        bot.answer_callback_query(c.id, "❌ Пати полная!", show_alert=True); return
    party["invites"].pop(uid, None); party["members"].append(uid); user_party[uid] = party_id
    p = get_player(uid); name = p[1] if p else str(uid)
    bot.answer_callback_query(c.id, "✅ Вы вступили!")
    try: bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=None)
    except Exception: pass
    new_max = get_party_max_size(party)
    bot.send_message(uid, f"👥 Вы вступили в пати! {len(party['members'])}/{new_max}")
    try: bot.send_message(party["leader"], f"👥 <b>{name}</b> принял приглашение! {len(party['members'])}/{new_max}", parse_mode="HTML")
    except Exception: pass


@bot.callback_query_handler(func=lambda c: c.data.startswith("party_decline_"))
def cb_party_decline(c):
    uid = c.from_user.id
    party_id = c.data.split("party_decline_", 1)[1]; party = parties.get(party_id)
    if party: party["invites"].pop(uid, None)
    bot.answer_callback_query(c.id, "❌ Отклонено")
    try: bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=None)
    except Exception: pass
    if party:
        try: bot.send_message(party["leader"], f"❌ Игрок <code>{uid}</code> отклонил приглашение.", parse_mode="HTML")
        except Exception: pass


@bot.callback_query_handler(func=lambda c: c.data == "party_leave")
def cb_party_leave(c):
    uid = c.from_user.id
    _do_party_leave(uid)
    bot.answer_callback_query(c.id, "✅ Вы вышли")
    bot.edit_message_text("⚡ ACTUAL FACEIT", c.message.chat.id, c.message.message_id, reply_markup=main_menu(uid))


@bot.callback_query_handler(func=lambda c: c.data == "party_disband")
def cb_party_disband(c):
    uid = c.from_user.id
    party = get_party_of(uid)
    if not party or party["leader"] != uid:
        bot.answer_callback_query(c.id, "❌ Вы не лидер"); return
    members = list(party["members"]); party_id = user_party.get(uid)
    for m in members:
        user_party.pop(m, None)
        if m != uid:
            try: bot.send_message(m, "👥 Пати расформирована лидером.")
            except Exception: pass
    if party_id: parties.pop(party_id, None)
    bot.answer_callback_query(c.id, "✅ Пати расформирована")
    bot.edit_message_text("⚡ ACTUAL FACEIT", c.message.chat.id, c.message.message_id, reply_markup=main_menu(uid))


def _do_party_leave(uid):
    party_id = user_party.pop(uid, None)
    if not party_id: return
    party = parties.get(party_id)
    if not party: return
    if uid in party["members"]: party["members"].remove(uid)
    if party["leader"] == uid:
        if party["members"]:
            party["leader"] = party["members"][0]
            try: bot.send_message(party["leader"], "👑 Вы стали новым лидером пати!")
            except Exception: pass
        else:
            parties.pop(party_id, None)
    elif not party["members"]:
        parties.pop(party_id, None)


# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    init_db()
    print(f"✅ ACTUAL FACEIT Bot запущен! Админы: {ADMIN_IDS_LIST}")
    bot.infinity_polling()
