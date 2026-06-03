import os
from supabase import create_client, Client
from datetime import datetime
import json

# ==================== SUPABASE КОНФИГ ====================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️ SUPABASE_URL или SUPABASE_KEY не настроены, использую SQLite")
    # Фоллбэк на SQLite если нет Supabase
    import sqlite3
    DB = "faceit.db"
    
    def get_player(user_id):
        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        cur.execute("SELECT * FROM players WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        conn.close()
        return row
    
    def register_user(uid, username, game_id, device, tg_username=""):
        conn = sqlite3.connect(DB)
        conn.execute("INSERT OR REPLACE INTO players (user_id, username, game_id, device, registered, coins, elo, tg_username) VALUES (?,?,?,?,1,100,1000,?)", (uid, username, game_id, device, tg_username))
        conn.commit()
        conn.close()
    
    def is_registered(uid):
        p = get_player(uid)
        return p is not None and p[12] == 1
    
    def is_admin(uid):
        p = get_player(uid)
        return p is not None and p[11] == 1
    
    def get_all_players():
        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        cur.execute("SELECT user_id, username, elo, wins, losses, kills, deaths, coins, is_banned, warns FROM players WHERE is_bot=0 AND registered=1 ORDER BY elo DESC")
        rows = cur.fetchall()
        conn.close()
        return rows
    
    def add_coins_to_player(uid, amount):
        conn = sqlite3.connect(DB)
        conn.execute("UPDATE players SET coins=coins+? WHERE user_id=?", (amount, uid))
        conn.commit()
        conn.close()
    
    def get_bots():
        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        cur.execute("SELECT user_id, username FROM players WHERE is_bot=1")
        bots = cur.fetchall()
        conn.close()
        return bots
    
    def get_shop_items_by_category(category):
        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        cur.execute("SELECT id, name, description, price, item_type FROM shop_items WHERE category=? AND is_active=1", (category,))
        items = cur.fetchall()
        conn.close()
        return items
    
    def get_shop_item(item_id):
        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        cur.execute("SELECT id, name, description, category, price, item_type FROM shop_items WHERE id=?", (item_id,))
        item = cur.fetchone()
        conn.close()
        return item
    
    def has_item_in_inventory(uid, item_id):
        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM inventory WHERE user_id=? AND item_id=?", (uid, item_id))
        count = cur.fetchone()[0]
        conn.close()
        return count > 0
    
    def buy_item(uid, item_id):
        item = get_shop_item(item_id)
        if not item:
            return False, "❌ Товар не найден"
        price = item[4]
        p = get_player(uid)
        if not p:
            return False, "❌ Игрок не найден"
        if p[5] < price:
            return False, f"❌ Недостаточно AC! Нужно: {price} AC"
        stackable = {"sticker", "unwarn", "x2coins", "rename"}
        if item[5] not in stackable and has_item_in_inventory(uid, item_id):
            return False, "❌ Этот предмет уже есть"
        conn = sqlite3.connect(DB)
        conn.execute("UPDATE players SET coins=coins-? WHERE user_id=?", (price, uid))
        conn.execute("INSERT INTO inventory (user_id, item_id, purchased_at) VALUES (?, ?, ?)", (uid, item_id, int(datetime.now().timestamp())))
        conn.commit()
        conn.close()
        return True, f"✅ Куплено: {item[1]}"
    
    def get_inventory(uid):
        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        cur.execute("""SELECT i.id, s.name, s.category, s.item_type, i.purchased_at, i.is_activated, s.id
                       FROM inventory i JOIN shop_items s ON i.item_id=s.id
                       WHERE i.user_id=? ORDER BY i.purchased_at DESC""", (uid,))
        items = cur.fetchall()
        conn.close()
        return items
    
    def activate_inventory_item(inv_id, uid, item_type, item_name):
        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        if item_type == "unwarn":
            cur.execute("SELECT warns FROM players WHERE user_id=?", (uid,))
            row = cur.fetchone()
            if row and row[0] > 0:
                cur.execute("UPDATE players SET warns=warns-1 WHERE user_id=?", (uid,))
            else:
                conn.close()
                return False, "❌ Нет варнов"
        elif item_type == "rename":
            conn.close()
            return "rename", "✏️ Введите новый никнейм (2-20 символов):"
        elif item_type == "quals":
            cur.execute("UPDATE players SET quals_access=1 WHERE user_id=?", (uid,))
        cur.execute("UPDATE inventory SET is_activated=1, activated_at=? WHERE id=?", (int(datetime.now().timestamp()), inv_id))
        conn.commit()
        conn.close()
        return True, f"✅ {item_name} активирован!"
    
    def update_player_stats(uid, kills, deaths, assists, won, coins_earned):
        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        cur.execute("SELECT elo, wins, losses, coins FROM players WHERE user_id=?", (uid,))
        old = cur.fetchone()
        if old:
            if won:
                if kills >= 12:
                    elo_change = 25
                else:
                    elo_change = 17
                new_elo = old[0] + elo_change
                new_wins = old[1] + 1
                new_losses = old[2]
            else:
                if kills >= 11:
                    elo_change = -15
                else:
                    elo_change = -25
                new_elo = max(100, old[0] + elo_change)
                new_wins = old[1]
                new_losses = old[2] + 1
            new_coins = old[3] + coins_earned
            cur.execute("UPDATE players SET elo=?, wins=?, losses=?, kills=kills+?, deaths=deaths+?, assists=assists+?, coins=? WHERE user_id=?", 
                       (new_elo, new_wins, new_losses, kills, deaths, assists, new_coins, uid))
        conn.commit()
        conn.close()
    
    def get_next_match_id():
        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        cur.execute("UPDATE match_counter SET value=value+1 WHERE id=1")
        cur.execute("SELECT value FROM match_counter WHERE id=1")
        val = cur.fetchone()[0]
        conn.commit()
        conn.close()
        return val
    
    def save_match_to_history(lobby, data, all_stats):
        players_info = []
        for uid, s in all_stats.items():
            p = get_player(uid)
            players_info.append({"user_id": uid, "name": p[1] if p else str(uid),
                                  "kills": s["kills"], "deaths": s["deaths"],
                                  "assists": s["assists"], "won": s["won"]})
        conn = sqlite3.connect(DB)
        conn.execute("INSERT INTO matches (match_id, league, device, map_name, winner, score_w, score_l, players_json, finished_at) VALUES (?,?,?,?,?,?,?,?,?)",
                     (lobby.get("match_id", 0), lobby.get("league", ""), lobby.get("device", ""),
                      lobby.get("map_name", ""), data.get("winner", ""),
                      data.get("score_w", 0), data.get("score_l", 0),
                      json.dumps(players_info, ensure_ascii=False), int(datetime.now().timestamp())))
        conn.commit()
        conn.close()
    
    def get_match_history(limit=10):
        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        cur.execute("SELECT match_id, league, device, map_name, winner, score_w, score_l, finished_at FROM matches ORDER BY finished_at DESC LIMIT ?", (limit,))
        rows = cur.fetchall()
        conn.close()
        return rows
    
    def create_promo_code(code, reward_type, reward_value, max_uses):
        conn = sqlite3.connect(DB)
        try:
            conn.execute("INSERT INTO promo_codes (code, reward_type, reward_value, max_uses) VALUES (?,?,?,?)", (code.upper(), reward_type, reward_value, max_uses))
            conn.commit()
            return True
        except:
            return False
        finally:
            conn.close()
    
    def use_promo_code(uid, code):
        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        code_upper = code.upper()
        cur.execute("SELECT id, reward_type, reward_value, max_uses, uses, is_active FROM promo_codes WHERE code=?", (code_upper,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return False, "❌ Промокод не найден"
        pid, reward_type, reward_value, max_uses, uses, is_active = row
        if not is_active:
            conn.close()
            return False, "❌ Промокод недействителен"
        if max_uses > 0 and uses >= max_uses:
            conn.close()
            return False, "❌ Промокод исчерпан"
        cur.execute("SELECT COUNT(*) FROM promo_uses WHERE user_id=? AND code=?", (uid, code_upper))
        if cur.fetchone()[0] > 0:
            conn.close()
            return False, "❌ Вы уже использовали этот промокод"
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
            conn.close()
            return False, "❌ Неизвестный тип награды"
        cur.execute("INSERT INTO promo_uses (user_id, code) VALUES (?,?)", (uid, code_upper))
        cur.execute("UPDATE promo_codes SET uses=uses+1 WHERE id=?", (pid,))
        conn.commit()
        conn.close()
        return True, msg
    
    def get_all_promo_codes():
        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        cur.execute("SELECT code, reward_type, reward_value, max_uses, uses, is_active FROM promo_codes ORDER BY id DESC")
        rows = cur.fetchall()
        conn.close()
        return rows
    
    def deactivate_promo_code(code):
        conn = sqlite3.connect(DB)
        conn.execute("UPDATE promo_codes SET is_active=0 WHERE code=?", (code.upper(),))
        conn.commit()
        conn.close()
    
    def is_on_check_db(uid):
        p = get_player(uid)
        return p is not None and len(p) > 20 and p[20] == 1
    
    def get_check_admin(uid):
        p = get_player(uid)
        if p is None or len(p) <= 21:
            return None
        return p[21]
    
    def is_muted_check(uid):
        p = get_player(uid)
        if p is None or len(p) <= 18:
            return False
        if p[18] == 1:
            mute_until = p[19] or 0
            if mute_until > datetime.now().timestamp():
                return True
            conn = sqlite3.connect(DB)
            conn.execute("UPDATE players SET is_muted=0, mute_until=0 WHERE user_id=?", (uid,))
            conn.commit()
            conn.close()
        return False
    
    def get_mute_remaining(uid):
        p = get_player(uid)
        if p is None or len(p) <= 19:
            return 0
        return max(0, int((p[19] or 0) - datetime.now().timestamp()))
    
    def has_active_premium(uid):
        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        cur.execute("""SELECT COUNT(*) FROM inventory i JOIN shop_items s ON i.item_id=s.id
                       WHERE i.user_id=? AND s.item_type='premium' AND i.is_activated=1""", (uid,))
        count = cur.fetchone()[0]
        conn.close()
        return count > 0
    
    def is_banned_check(uid):
        p = get_player(uid)
        return p is not None and len(p) > 14 and p[14] == 1
    
    def get_player_by_game_id(game_id):
        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        cur.execute("SELECT * FROM players WHERE game_id=? AND is_bot=0", (game_id,))
        row = cur.fetchone()
        conn.close()
        return row
    
    def nick_taken(nick, exclude_uid=None):
        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        if exclude_uid:
            cur.execute("SELECT COUNT(*) FROM players WHERE username=? AND user_id!=? AND is_bot=0", (nick, exclude_uid))
        else:
            cur.execute("SELECT COUNT(*) FROM players WHERE username=? AND is_bot=0", (nick,))
        count = cur.fetchone()[0]
        conn.close()
        return count > 0
    
    def game_id_taken(game_id, exclude_uid=None):
        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        if exclude_uid:
            cur.execute("SELECT COUNT(*) FROM players WHERE game_id=? AND user_id!=? AND is_bot=0", (game_id, exclude_uid))
        else:
            cur.execute("SELECT COUNT(*) FROM players WHERE game_id=? AND is_bot=0", (game_id,))
        count = cur.fetchone()[0]
        conn.close()
        return count > 0
    
    def is_game_reg_check(uid):
        p = get_player(uid)
        return p is not None and (p[11] == 1 or (len(p) > 17 and p[17] == 1))
    
    def has_quals_access(uid):
        p = get_player(uid)
        return p is not None and (p[11] == 1 or (len(p) > 16 and p[16] == 1))
    
    def get_faceit_level(elo):
        if elo < 801: return 1
        elif elo < 951: return 2
        elif elo < 1101: return 3
        elif elo < 1251: return 4
        elif elo < 1401: return 5
        elif elo < 1551: return 6
        elif elo < 1701: return 7
        elif elo < 1851: return 8
        elif elo < 2001: return 9
        else: return 10
    
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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS shop_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                category TEXT NOT NULL,
                price INTEGER NOT NULL,
                item_type TEXT NOT NULL,
                is_active INTEGER DEFAULT 1
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                purchased_at INTEGER DEFAULT (strftime('%s','now')),
                is_activated INTEGER DEFAULT 0,
                activated_at INTEGER DEFAULT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS match_counter (
                id INTEGER PRIMARY KEY,
                value INTEGER DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id INTEGER NOT NULL,
                league TEXT,
                device TEXT,
                map_name TEXT,
                winner TEXT,
                score_w INTEGER,
                score_l INTEGER,
                finished_at INTEGER DEFAULT (strftime('%s','now')),
                players_json TEXT
            )
        """)
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
        cur.execute("SELECT COUNT(*) FROM shop_items")
        if cur.fetchone()[0] == 0:
            items = [
                ('AK-47 | Fuel Injector', 'Легендарный скин на АК-47', 'skins', 500, 'skin'),
                ('AK-47 | Bloodsport', 'Агрессивный дизайн', 'skins', 350, 'skin'),
                ('M4A4 | Howl', 'Редкий скин M4A4', 'skins', 800, 'skin'),
                ('M4A4 | Neo-Noir', 'Элегантный скин M4A4', 'skins', 400, 'skin'),
                ('AWP | Dragon Lore', 'Легендарный AWP', 'skins', 1200, 'skin'),
                ('AWP | Asiimov', 'Футуристичный AWP', 'skins', 600, 'skin'),
                ('Нож | Butterfly Blue', 'Красивый нож-бабочка', 'skins', 1500, 'skin'),
                ('Нож | Karambit Fade', 'Редкий карамбит', 'skins', 2000, 'skin'),
                ('Premium статус', '30 дней Premium: x1.5 монет, значок ★', 'goods', 1000, 'premium'),
                ('x2 монеты', 'Удвоение монет за 7 дней', 'goods', 500, 'x2coins'),
                ('Снятие варна', 'Снять 1 предупреждение', 'goods', 200, 'unwarn'),
                ('Смена ника', 'Изменить ник в боте', 'goods', 100, 'rename'),
                ('Quals доступ', 'Постоянный доступ к QUALS', 'goods', 3000, 'quals'),
            ]
            cur.executemany("INSERT INTO shop_items (name, description, category, price, item_type) VALUES (?,?,?,?,?)", items)
        cur.execute("INSERT OR IGNORE INTO match_counter (id, value) VALUES (1, 0)")
        conn.commit()
        conn.close()
        print("✅ База данных инициализирована (SQLite)")
    
    print("⚠️ Использую SQLite (Supabase не настроен)")
    # Продолжаем с SQLite функциями выше...

else:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("✅ Supabase подключён")
    
    # ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
    def _to_dict(result):
        if hasattr(result, 'data'):
            return result.data
        return result
    
    def _player_to_tuple(d):
        return (
            d.get("user_id"), d.get("username", ""), d.get("game_id", ""), d.get("device", ""),
            d.get("elo", 1000), d.get("coins", 100), d.get("wins", 0), d.get("losses", 0),
            d.get("kills", 0), d.get("deaths", 0), d.get("assists", 0),
            d.get("is_admin", 0), d.get("registered", 0), d.get("is_bot", 0),
            d.get("is_banned", 0), d.get("warns", 0), d.get("quals_access", 0),
            d.get("is_game_reg", 0), d.get("is_muted", 0), d.get("mute_until", 0),
            d.get("is_on_check", 0), d.get("check_admin_id", 0), d.get("tg_username", "")
        )
    
    # ==================== ОСНОВНЫЕ ФУНКЦИИ (Supabase) ====================
    def get_player(user_id):
        result = supabase.table("players").select("*").eq("user_id", user_id).execute()
        data = _to_dict(result)
        if data:
            return _player_to_tuple(data[0])
        return None
    
    def get_all_players():
        result = supabase.table("players").select("*").eq("is_bot", 0).eq("registered", 1).order("elo", desc=True).execute()
        data = _to_dict(result)
        players = []
        for d in data:
            players.append((
                d["user_id"], d["username"], d["elo"], d["wins"], d["losses"],
                d["kills"], d["deaths"], d["coins"], d.get("is_banned", 0), d.get("warns", 0)
            ))
        return players
    
    def register_user(uid, username, game_id, device, tg_username=""):
        data = {
            "user_id": uid,
            "username": username,
            "game_id": game_id,
            "device": device,
            "registered": 1,
            "coins": 100,
            "elo": 1000,
            "tg_username": tg_username
        }
        supabase.table("players").upsert(data).execute()
    
    def update_tg_username(uid, tg_username):
        supabase.table("players").update({"tg_username": tg_username or ""}).eq("user_id", uid).execute()
    
    def add_coins_to_player(uid, amount):
        p = get_player(uid)
        if p:
            new_coins = p[5] + amount
            supabase.table("players").update({"coins": new_coins}).eq("user_id", uid).execute()
    
    def apply_mute(uid, hours=2):
        until = int(datetime.now().timestamp()) + hours * 3600
        supabase.table("players").update({"is_muted": 1, "mute_until": until}).eq("user_id", uid).execute()
        return until
    
    def add_warn_to_player(uid):
        p = get_player(uid)
        warns = (p[15] if p else 0) + 1
        supabase.table("players").update({"warns": warns}).eq("user_id", uid).execute()
        return warns
    
    def get_bots():
        result = supabase.table("players").select("user_id, username").eq("is_bot", 1).execute()
        data = _to_dict(result)
        return [(d["user_id"], d["username"]) for d in data]
    
    def get_shop_items_by_category(category):
        result = supabase.table("shop_items").select("id, name, description, price, item_type").eq("category", category).eq("is_active", 1).execute()
        data = _to_dict(result)
        return [(d["id"], d["name"], d["description"], d["price"], d["item_type"]) for d in data]
    
    def get_shop_item(item_id):
        result = supabase.table("shop_items").select("*").eq("id", item_id).execute()
        data = _to_dict(result)
        if data:
            d = data[0]
            return (d["id"], d["name"], d["description"], d["category"], d["price"], d["item_type"])
        return None
    
    def has_item_in_inventory(uid, item_id):
        result = supabase.table("inventory").select("id").eq("user_id", uid).eq("item_id", item_id).execute()
        return len(_to_dict(result)) > 0
    
    def buy_item(uid, item_id):
        item = get_shop_item(item_id)
        if not item:
            return False, "❌ Товар не найден"
        price = item[4]
        p = get_player(uid)
        if not p:
            return False, "❌ Игрок не найден"
        if p[5] < price:
            return False, f"❌ Недостаточно AC! Нужно: {price} AC"
        stackable = {"sticker", "unwarn", "x2coins", "rename"}
        if item[5] not in stackable and has_item_in_inventory(uid, item_id):
            return False, "❌ Этот предмет уже есть"
        new_coins = p[5] - price
        supabase.table("players").update({"coins": new_coins}).eq("user_id", uid).execute()
        supabase.table("inventory").insert({
            "user_id": uid,
            "item_id": item_id,
            "purchased_at": int(datetime.now().timestamp())
        }).execute()
        return True, f"✅ Куплено: {item[1]}"
    
    def get_inventory(uid):
        result = supabase.table("inventory").select("""
            inventory.id, shop_items.name, shop_items.category, shop_items.item_type,
            inventory.purchased_at, inventory.is_activated, shop_items.id
        """).join("shop_items", "inventory.item_id", "shop_items.id").eq("inventory.user_id", uid).order("inventory.purchased_at", desc=True).execute()
        data = _to_dict(result)
        items = []
        for d in data:
            items.append((d["id"], d["name"], d["category"], d["item_type"], d["purchased_at"], d["is_activated"], d["id"]))
        return items
    
    def activate_inventory_item(inv_id, uid, item_type, item_name):
        if item_type == "unwarn":
            p = get_player(uid)
            warns = p[15] if p else 0
            if warns > 0:
                supabase.table("players").update({"warns": warns - 1}).eq("user_id", uid).execute()
            else:
                return False, "❌ Нет варнов"
        elif item_type == "rename":
            return "rename", "✏️ Введите новый никнейм (2-20 символов):"
        elif item_type == "quals":
            supabase.table("players").update({"quals_access": 1}).eq("user_id", uid).execute()
        supabase.table("inventory").update({"is_activated": 1, "activated_at": int(datetime.now().timestamp())}).eq("id", inv_id).execute()
        return True, f"✅ {item_name} активирован!"
    
    def update_player_stats(uid, kills, deaths, assists, won, coins_earned):
        p = get_player(uid)
        if not p:
            return
        new_elo = p[4]
        new_wins = p[6]
        new_losses = p[7]
        if won:
            if kills >= 12:
                new_elo += 25
            else:
                new_elo += 17
            new_wins += 1
        else:
            if kills >= 11:
                new_elo -= 15
            else:
                new_elo -= 25
            new_losses += 1
        new_elo = max(100, new_elo)
        supabase.table("players").update({
            "elo": new_elo,
            "wins": new_wins,
            "losses": new_losses,
            "kills": p[8] + kills,
            "deaths": p[9] + deaths,
            "assists": p[10] + assists,
            "coins": p[5] + coins_earned
        }).eq("user_id", uid).execute()
    
    def get_next_match_id():
        result = supabase.table("match_counter").select("value").eq("id", 1).execute()
        data = _to_dict(result)
        if data:
            val = data[0]["value"] + 1
            supabase.table("match_counter").update({"value": val}).eq("id", 1).execute()
            return val
        else:
            supabase.table("match_counter").insert({"id": 1, "value": 1}).execute()
            return 1
    
    def save_match_to_history(lobby, data, all_stats):
        players_info = []
        for uid, s in all_stats.items():
            p = get_player(uid)
            players_info.append({
                "user_id": uid,
                "name": p[1] if p else str(uid),
                "kills": s["kills"],
                "deaths": s["deaths"],
                "assists": s["assists"],
                "won": s["won"]
            })
        supabase.table("matches").insert({
            "match_id": lobby.get("match_id", 0),
            "league": lobby.get("league", ""),
            "device": lobby.get("device", ""),
            "map_name": lobby.get("map_name", ""),
            "winner": data.get("winner", ""),
            "score_w": data.get("score_w", 0),
            "score_l": data.get("score_l", 0),
            "players_json": json.dumps(players_info, ensure_ascii=False),
            "finished_at": int(datetime.now().timestamp())
        }).execute()
    
    def get_match_history(limit=10):
        result = supabase.table("matches").select("match_id, league, device, map_name, winner, score_w, score_l, finished_at").order("finished_at", desc=True).limit(limit).execute()
        data = _to_dict(result)
        rows = []
        for d in data:
            rows.append((d["match_id"], d["league"], d["device"], d["map_name"],
                         d["winner"], d["score_w"], d["score_l"], d["finished_at"]))
        return rows
    
    def create_promo_code(code, reward_type, reward_value, max_uses):
        try:
            supabase.table("promo_codes").insert({
                "code": code.upper(),
                "reward_type": reward_type,
                "reward_value": reward_value,
                "max_uses": max_uses,
                "uses": 0,
                "is_active": 1
            }).execute()
            return True
        except Exception:
            return False
    
    def use_promo_code(uid, code):
        code_upper = code.upper()
        result = supabase.table("promo_codes").select("*").eq("code", code_upper).execute()
        data = _to_dict(result)
        if not data:
            return False, "❌ Промокод не найден"
        promo = data[0]
        if not promo["is_active"]:
            return False, "❌ Промокод недействителен"
        if promo["max_uses"] > 0 and promo["uses"] >= promo["max_uses"]:
            return False, "❌ Промокод исчерпан"
        used = supabase.table("promo_uses").select("id").eq("user_id", uid).eq("code", code_upper).execute()
        if len(_to_dict(used)) > 0:
            return False, "❌ Вы уже использовали этот промокод"
        reward_type = promo["reward_type"]
        reward_value = promo["reward_value"]
        if reward_type == "coins":
            p = get_player(uid)
            if p:
                supabase.table("players").update({"coins": p[5] + reward_value}).eq("user_id", uid).execute()
            msg = f"💰 Начислено <b>{reward_value} AC</b>!"
        elif reward_type == "premium":
            item = supabase.table("shop_items").select("id").eq("item_type", "premium").limit(1).execute()
            item_data = _to_dict(item)
            if item_data:
                supabase.table("inventory").insert({
                    "user_id": uid,
                    "item_id": item_data[0]["id"],
                    "is_activated": 1,
                    "purchased_at": int(datetime.now().timestamp())
                }).execute()
            msg = "👑 <b>Premium</b> активирован!"
        elif reward_type == "quals":
            supabase.table("players").update({"quals_access": 1}).eq("user_id", uid).execute()
            msg = "⭐ Доступ к <b>QUALS</b> открыт!"
        else:
            return False, "❌ Неизвестный тип награды"
        supabase.table("promo_uses").insert({"user_id": uid, "code": code_upper}).execute()
        supabase.table("promo_codes").update({"uses": promo["uses"] + 1}).eq("id", promo["id"]).execute()
        return True, msg
    
    def get_all_promo_codes():
        result = supabase.table("promo_codes").select("code, reward_type, reward_value, max_uses, uses, is_active").order("id", desc=True).execute()
        data = _to_dict(result)
        return [(d["code"], d["reward_type"], d["reward_value"], d["max_uses"], d["uses"], d["is_active"]) for d in data]
    
    def deactivate_promo_code(code):
        supabase.table("promo_codes").update({"is_active": 0}).eq("code", code.upper()).execute()
    
    def is_on_check_db(uid):
        p = get_player(uid)
        return p is not None and len(p) > 20 and p[20] == 1
    
    def get_check_admin(uid):
        p = get_player(uid)
        if p is None or len(p) <= 21:
            return None
        return p[21]
    
    def is_muted_check(uid):
        p = get_player(uid)
        if p is None or len(p) <= 18:
            return False
        if p[18] == 1:
            mute_until = p[19] or 0
            if mute_until > datetime.now().timestamp():
                return True
            supabase.table("players").update({"is_muted": 0, "mute_until": 0}).eq("user_id", uid).execute()
        return False
    
    def get_mute_remaining(uid):
        p = get_player(uid)
        if p is None or len(p) <= 19:
            return 0
        return max(0, int((p[19] or 0) - datetime.now().timestamp()))
    
    def has_active_premium(uid):
        result = supabase.table("inventory").select("inventory.id").join("shop_items", "inventory.item_id", "shop_items.id").eq("inventory.user_id", uid).eq("shop_items.item_type", "premium").eq("inventory.is_activated", 1).execute()
        return len(_to_dict(result)) > 0
    
    def is_banned_check(uid):
        p = get_player(uid)
        return p is not None and len(p) > 14 and p[14] == 1
    
    def get_player_by_game_id(game_id):
        result = supabase.table("players").select("*").eq("game_id", game_id).eq("is_bot", 0).execute()
        data = _to_dict(result)
        if data:
            return _player_to_tuple(data[0])
        return None
    
    def nick_taken(nick, exclude_uid=None):
        query = supabase.table("players").select("user_id").eq("username", nick).eq("is_bot", 0)
        if exclude_uid:
            query = query.neq("user_id", exclude_uid)
        result = query.execute()
        return len(_to_dict(result)) > 0
    
    def game_id_taken(game_id, exclude_uid=None):
        query = supabase.table("players").select("user_id").eq("game_id", game_id).eq("is_bot", 0)
        if exclude_uid:
            query = query.neq("user_id", exclude_uid)
        result = query.execute()
        return len(_to_dict(result)) > 0
    
    def is_admin(uid):
        p = get_player(uid)
        return p is not None and p[11] == 1
    
    def is_registered(uid):
        p = get_player(uid)
        return p is not None and p[12] == 1
    
    def is_bot_player(uid):
        p = get_player(uid)
        return p is not None and p[13] == 1
    
    def is_game_reg_check(uid):
        p = get_player(uid)
        return p is not None and (p[11] == 1 or (len(p) > 17 and p[17] == 1))
    
    def has_quals_access(uid):
        p = get_player(uid)
        return p is not None and (p[11] == 1 or (len(p) > 16 and p[16] == 1))
    
    def get_faceit_level(elo):
        if elo < 801: return 1
        elif elo < 951: return 2
        elif elo < 1101: return 3
        elif elo < 1251: return 4
        elif elo < 1401: return 5
        elif elo < 1551: return 6
        elif elo < 1701: return 7
        elif elo < 1851: return 8
        elif elo < 2001: return 9
        else: return 10
    
    def init_db():
        print("✅ Supabase готов (таблицы должны быть созданы вручную через SQL Editor)")