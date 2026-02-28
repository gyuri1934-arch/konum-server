# ═══════════════════════════════════════════════════════════════════════════════
#                    KONUM TAKİP SERVER — PostgreSQL Kalıcı v3.0
# ═══════════════════════════════════════════════════════════════════════════════
# Tüm veriler PostgreSQL'de kalıcı — Render restart etse bile korunur
# ═══════════════════════════════════════════════════════════════════════════════

import os, uuid, json, pytz, psycopg2, psycopg2.extras
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
from datetime import datetime, timedelta
from math import radians, sin, cos, sqrt, atan2
from contextlib import contextmanager

# ═══════════════════════════════════════════════════════════════════════════════
# ⚙️ UYGULAMA
# ═══════════════════════════════════════════════════════════════════════════════

app = FastAPI(title="Konum Takip API", version="3.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://konum_db_user:kmiKUjdHgVeOmw8LNiXs2i4umi7dHBXH@dpg-d6bempl6ubrc73cicdi0-a.frankfurt-postgres.render.com/konum_db"
)

TZ = pytz.timezone("Europe/Istanbul")
USER_TIMEOUT       = 120
IDLE_THRESHOLD     = 15
IDLE_TIME_MINUTES  = 15
SPEED_VEHICLE      = 30
SPEED_WALK         = 3
MIN_DIST_VEHICLE   = 50
MIN_DIST_RUN       = 20
MIN_DIST_WALK      = 10
MIN_DIST_IDLE      = 5
MAX_POINTS         = 5000
MAX_HISTORY_DAYS   = 90
PIN_START          = 20
PIN_END            = 25
MAX_ROOM_MSGS      = 200

# ═══════════════════════════════════════════════════════════════════════════════
# 🗄️ VERİTABANI
# ═══════════════════════════════════════════════════════════════════════════════

@contextmanager
def db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS locations (
                user_id TEXT PRIMARY KEY,
                device_id TEXT DEFAULT '',
                device_type TEXT DEFAULT 'phone',
                lat DOUBLE PRECISION,
                lng DOUBLE PRECISION,
                altitude DOUBLE PRECISION DEFAULT 0,
                speed DOUBLE PRECISION DEFAULT 0,
                animation_type TEXT DEFAULT 'pulse',
                room_name TEXT DEFAULT 'Genel',
                character TEXT DEFAULT '🧍',
                last_seen TEXT,
                idle_status TEXT DEFAULT 'online',
                idle_minutes INT DEFAULT 0,
                idle_start TEXT
            )""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS location_history (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                lat DOUBLE PRECISION,
                lng DOUBLE PRECISION,
                timestamp TEXT,
                speed DOUBLE PRECISION DEFAULT 0
            )""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_lh_user ON location_history(user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_lh_ts   ON location_history(timestamp)")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS device_registry (
                device_id TEXT PRIMARY KEY,
                user_id   TEXT NOT NULL
            )""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS rooms (
                room_name         TEXT PRIMARY KEY,
                password          TEXT,
                created_by        TEXT,
                created_by_device TEXT DEFAULT '',
                created_at        TEXT,
                collectors        JSONB DEFAULT '[]'
            )""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS scores (
                room_name TEXT,
                user_id   TEXT,
                score     INT DEFAULT 0,
                PRIMARY KEY (room_name, user_id)
            )""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pin_collection_history (
                id         SERIAL PRIMARY KEY,
                room_name  TEXT,
                user_id    TEXT,
                timestamp  TEXT,
                created_at TEXT,
                creator    TEXT,
                lat        DOUBLE PRECISION,
                lng        DOUBLE PRECISION
            )""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pins (
                id               TEXT PRIMARY KEY,
                room_name        TEXT,
                creator          TEXT,
                lat              DOUBLE PRECISION,
                lng              DOUBLE PRECISION,
                created_at       TEXT,
                collector_id     TEXT,
                collection_start TEXT,
                collection_time  INT DEFAULT 0
            )""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id        SERIAL PRIMARY KEY,
                from_user TEXT,
                to_user   TEXT,
                conv_key  TEXT,
                message   TEXT,
                timestamp TEXT,
                is_read   BOOLEAN DEFAULT FALSE
            )""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_msg_key ON messages(conv_key)")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS room_messages (
                id        TEXT PRIMARY KEY,
                room_name TEXT,
                from_user TEXT,
                message   TEXT,
                timestamp TEXT,
                character TEXT DEFAULT '🧍'
            )""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_rm_room ON room_messages(room_name)")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS visibility_settings (
                user_id TEXT PRIMARY KEY,
                mode    TEXT DEFAULT 'all',
                allowed JSONB DEFAULT '[]'
            )""")
    print("✅ DB tabloları hazır")

# ═══════════════════════════════════════════════════════════════════════════════
# 🛠️ YARDIMCILAR
# ═══════════════════════════════════════════════════════════════════════════════

def now_str():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")

def haversine(lat1, lng1, lat2, lng2):
    R = 6371000
    dlat, dlng = radians(lat2-lat1), radians(lng2-lng1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlng/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1-a))

def is_online(last_seen):
    if not last_seen: return False
    try:
        dt = TZ.localize(datetime.strptime(last_seen, "%Y-%m-%d %H:%M:%S"))
        return (datetime.now(TZ) - dt).total_seconds() < USER_TIMEOUT
    except: return False

def conv_key(u1, u2):
    return "_".join(sorted([u1, u2]))

def collectors_list(val):
    if isinstance(val, list): return val
    try: return json.loads(val or "[]")
    except: return []

def get_device_id(user_id: str) -> str:
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT device_id FROM locations WHERE user_id=%s", (user_id,))
        row = cur.fetchone()
        return row["device_id"] if row else ""

def is_admin(room_name: str, user_id: str, device_id: str = "") -> bool:
    """userId VEYA deviceId ile admin kontrolü — gerekirse odayı günceller"""
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT created_by, created_by_device FROM rooms WHERE room_name=%s", (room_name,))
        row = cur.fetchone()
        if not row: return False
        if row["created_by"] == user_id: return True
        if device_id and row["created_by_device"] == device_id:
            cur.execute("UPDATE rooms SET created_by=%s WHERE room_name=%s", (user_id, room_name))
            return True
    return False

# ═══════════════════════════════════════════════════════════════════════════════
# 📋 MODELLER
# ═══════════════════════════════════════════════════════════════════════════════

class LocationModel(BaseModel):
    userId: str; deviceId: str = ""; deviceType: str = "phone"
    lat: float; lng: float; altitude: float = 0; speed: float = 0
    animationType: str = "pulse"; roomName: str = "Genel"; character: str = "🧍"

class RoomModel(BaseModel):
    roomName: str; password: str; createdBy: str; createdByDevice: str = ""

class JoinRoomModel(BaseModel):
    roomName: str; password: str

class PinModel(BaseModel):
    roomName: str; creator: str; lat: float; lng: float

class MessageModel(BaseModel):
    fromUser: str; toUser: str; message: str

class RoomMessageModel(BaseModel):
    roomName: str; fromUser: str; message: str

class VisibilityModel(BaseModel):
    userId: str; mode: str; allowed: List[str] = []

class ChangeUsernameModel(BaseModel):
    deviceId: str; oldName: str; newName: str

# ═══════════════════════════════════════════════════════════════════════════════
# 🚀 BAŞLANGIÇ
# ═══════════════════════════════════════════════════════════════════════════════

@app.on_event("startup")
def startup(): init_db()

@app.get("/")
def root():
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as c FROM locations")
        users = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) as c FROM rooms")
        rms = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) as c FROM pins")
        pns = cur.fetchone()["c"]
    return {"status": "✅ Server çalışıyor", "time": now_str(),
            "total_users": users, "total_rooms": rms, "total_pins": pns}

@app.get("/health")
def health(): return {"status": "ok", "time": now_str()}

# ═══════════════════════════════════════════════════════════════════════════════
# 🚪 ODA YÖNETİMİ
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/create_room")
def create_room(data: RoomModel):
    if len(data.password) < 3:
        raise HTTPException(400, "Şifre en az 3 karakter olmalı!")
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM rooms WHERE room_name=%s", (data.roomName,))
        if cur.fetchone(): raise HTTPException(400, "Bu oda adı zaten mevcut!")
        cur.execute("""
            INSERT INTO rooms (room_name,password,created_by,created_by_device,created_at,collectors)
            VALUES (%s,%s,%s,%s,%s,'[]')
        """, (data.roomName, data.password, data.createdBy, data.createdByDevice, now_str()))
    return {"message": f"✅ {data.roomName} odası oluşturuldu"}

@app.post("/join_room")
def join_room(data: JoinRoomModel):
    if data.roomName == "Genel": return {"message": "Genel odaya katıldınız"}
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT password FROM rooms WHERE room_name=%s", (data.roomName,))
        row = cur.fetchone()
        if not row: raise HTTPException(404, "Oda bulunamadı!")
        if row["password"] != data.password: raise HTTPException(401, "Yanlış şifre!")
    return {"message": f"✅ {data.roomName} odasına katıldınız"}

@app.get("/get_rooms")
def get_rooms(user_id: str = ""):
    dev_id = get_device_id(user_id) if user_id else ""
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM rooms")
        all_rooms = cur.fetchall()
        cur.execute("""
            SELECT room_name, COUNT(*) as c FROM locations
            WHERE last_seen IS NOT NULL GROUP BY room_name
        """)
        counts = {r["room_name"]: r["c"] for r in cur.fetchall()}

    result = [{"name":"Genel","hasPassword":False,"userCount":counts.get("Genel",0),
               "createdBy":"system","isAdmin":False,"password":None}]
    for room in all_rooms:
        adm = is_admin(room["room_name"], user_id, dev_id) if user_id else False
        result.append({
            "name": room["room_name"], "hasPassword": True,
            "userCount": counts.get(room["room_name"], 0),
            "createdBy": room["created_by"], "isAdmin": adm,
            "password": room["password"] if adm else None,
        })
    return result

@app.delete("/delete_room/{room_name}")
def delete_room(room_name: str, admin_id: str):
    if not is_admin(room_name, admin_id, get_device_id(admin_id)):
        raise HTTPException(403, "Sadece admin silebilir!")
    with db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM rooms WHERE room_name=%s", (room_name,))
        cur.execute("UPDATE locations SET room_name='Genel' WHERE room_name=%s", (room_name,))
        cur.execute("DELETE FROM pins WHERE room_name=%s", (room_name,))
        cur.execute("DELETE FROM scores WHERE room_name=%s", (room_name,))
        cur.execute("DELETE FROM room_messages WHERE room_name=%s", (room_name,))
    return {"message": f"✅ {room_name} silindi"}

@app.get("/get_room_password/{room_name}")
def get_room_password(room_name: str, admin_id: str):
    if not is_admin(room_name, admin_id, get_device_id(admin_id)):
        raise HTTPException(403, "Sadece admin görebilir!")
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT password FROM rooms WHERE room_name=%s", (room_name,))
        row = cur.fetchone()
    return {"password": row["password"] if row else ""}

@app.post("/change_room_password/{room_name}")
def change_room_password(room_name: str, admin_id: str, new_password: str):
    if not is_admin(room_name, admin_id, get_device_id(admin_id)):
        raise HTTPException(403, "Sadece admin değiştirebilir!")
    if len(new_password) < 3: raise HTTPException(400, "Şifre en az 3 karakter!")
    with db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE rooms SET password=%s WHERE room_name=%s", (new_password, room_name))
    return {"message": "✅ Şifre değiştirildi"}

@app.get("/get_room_permissions/{room_name}")
def get_room_permissions(room_name: str, user_id: str = ""):
    if room_name == "Genel": return {"admin": None, "collectors": []}
    if user_id:
        is_admin(room_name, user_id, get_device_id(user_id))
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT created_by, collectors FROM rooms WHERE room_name=%s", (room_name,))
        row = cur.fetchone()
    if not row: return {"admin": None, "collectors": []}
    return {"admin": row["created_by"], "collectors": collectors_list(row["collectors"])}

@app.post("/set_collector_permission/{room_name}/{target_user}")
def set_collector_permission(room_name: str, target_user: str, admin_id: str, enabled: bool):
    if not is_admin(room_name, admin_id, get_device_id(admin_id)):
        raise HTTPException(403, "Sadece admin yetkilendirebilir!")
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT collectors FROM rooms WHERE room_name=%s", (room_name,))
        row = cur.fetchone()
        cols = collectors_list(row["collectors"] if row else [])
        if enabled and target_user not in cols: cols.append(target_user)
        elif not enabled and target_user in cols: cols.remove(target_user)
        cur.execute("UPDATE rooms SET collectors=%s WHERE room_name=%s", (json.dumps(cols), room_name))
    return {"message": "✅ Yetki güncellendi", "collectors": cols}

# ═══════════════════════════════════════════════════════════════════════════════
# 👁️ GÖRÜNÜRLİK
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/set_visibility")
def set_visibility(data: VisibilityModel):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO visibility_settings (user_id,mode,allowed) VALUES (%s,%s,%s)
            ON CONFLICT (user_id) DO UPDATE SET mode=EXCLUDED.mode, allowed=EXCLUDED.allowed
        """, (data.userId, data.mode, json.dumps(data.allowed)))
    return {"message": "✅ Görünürlük güncellendi"}

# ═══════════════════════════════════════════════════════════════════════════════
# 📍 KONUM GÜNCELLEMESİ
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/update_location")
def update_location(data: LocationModel):
    uid, now = data.userId, now_str()

    with db() as conn:
        cur = conn.cursor()

        # ── device_registry + isim değişikliği tespiti ──────────────────────
        if data.deviceId:
            cur.execute("SELECT user_id FROM device_registry WHERE device_id=%s", (data.deviceId,))
            prev = cur.fetchone()
            if prev and prev["user_id"] != uid:
                old_uid = prev["user_id"]
                cur.execute("UPDATE location_history SET user_id=%s WHERE user_id=%s", (uid, old_uid))
                cur.execute("UPDATE locations SET user_id=%s WHERE user_id=%s", (uid, old_uid))
                cur.execute("UPDATE rooms SET created_by=%s WHERE created_by=%s", (uid, old_uid))
                cur.execute("""
                    UPDATE scores SET user_id=%s WHERE user_id=%s
                    AND NOT EXISTS (SELECT 1 FROM scores s2 WHERE s2.room_name=scores.room_name AND s2.user_id=%s)
                """, (uid, old_uid, uid))
            cur.execute("""
                INSERT INTO device_registry (device_id,user_id) VALUES (%s,%s)
                ON CONFLICT (device_id) DO UPDATE SET user_id=EXCLUDED.user_id
            """, (data.deviceId, uid))

        # ── Hareketsizlik kontrolü ───────────────────────────────────────────
        cur.execute("SELECT lat,lng,idle_start FROM locations WHERE user_id=%s", (uid,))
        old = cur.fetchone()
        idle_status, idle_minutes, idle_start = "online", 0, None
        if old:
            dist = haversine(old["lat"], old["lng"], data.lat, data.lng)
            if dist < IDLE_THRESHOLD:
                idle_start = old["idle_start"] or now
                try:
                    start_dt = TZ.localize(datetime.strptime(idle_start, "%Y-%m-%d %H:%M:%S"))
                    mins = (datetime.now(TZ) - start_dt).total_seconds() / 60
                    if mins >= IDLE_TIME_MINUTES:
                        idle_status = "idle"
                        idle_minutes = int(mins)
                except: idle_start = now

        # ── Rota geçmişi ─────────────────────────────────────────────────────
        cur.execute("SELECT lat,lng FROM location_history WHERE user_id=%s ORDER BY id DESC LIMIT 1", (uid,))
        last_pt = cur.fetchone()
        add_pt = False
        if not last_pt:
            add_pt = True
        else:
            d = haversine(last_pt["lat"], last_pt["lng"], data.lat, data.lng)
            s = data.speed
            if   s >= SPEED_VEHICLE: add_pt = d >= MIN_DIST_VEHICLE
            elif s >= SPEED_WALK:    add_pt = d >= MIN_DIST_RUN
            elif s >= 0.5:           add_pt = d >= MIN_DIST_WALK
            else:                    add_pt = d >= MIN_DIST_IDLE

        if add_pt:
            cur.execute("INSERT INTO location_history (user_id,lat,lng,timestamp,speed) VALUES (%s,%s,%s,%s,%s)",
                        (uid, data.lat, data.lng, now, data.speed))
            cur.execute("""
                DELETE FROM location_history WHERE user_id=%s AND id NOT IN (
                    SELECT id FROM location_history WHERE user_id=%s ORDER BY id DESC LIMIT %s)
            """, (uid, uid, MAX_POINTS))

        # ── Pin toplama ───────────────────────────────────────────────────────
        can_collect = False
        if data.roomName == "Genel":
            can_collect = True
        else:
            cur.execute("SELECT collectors FROM rooms WHERE room_name=%s", (data.roomName,))
            rr = cur.fetchone()
            if rr: can_collect = uid in collectors_list(rr["collectors"])

        if can_collect:
            cur.execute("SELECT * FROM pins WHERE room_name=%s", (data.roomName,))
            for pin in cur.fetchall():
                if pin["creator"] == uid: continue
                d = haversine(data.lat, data.lng, pin["lat"], pin["lng"])
                if d <= PIN_START:
                    if not pin["collector_id"]:
                        cur.execute("UPDATE pins SET collector_id=%s,collection_start=%s,collection_time=0 WHERE id=%s",
                                    (uid, now, pin["id"]))
                    elif pin["collector_id"] == uid:
                        try:
                            s = TZ.localize(datetime.strptime(pin["collection_start"], "%Y-%m-%d %H:%M:%S"))
                            elapsed = int((datetime.now(TZ) - s).total_seconds())
                            cur.execute("UPDATE pins SET collection_time=%s WHERE id=%s", (elapsed, pin["id"]))
                        except: pass
                elif d > PIN_END and pin["collector_id"] == uid:
                    cur.execute("""
                        INSERT INTO scores (room_name,user_id,score) VALUES (%s,%s,1)
                        ON CONFLICT (room_name,user_id) DO UPDATE SET score=scores.score+1
                    """, (data.roomName, uid))
                    cur.execute("""
                        INSERT INTO pin_collection_history (room_name,user_id,timestamp,created_at,creator,lat,lng)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)
                    """, (data.roomName, uid, now, pin["created_at"] or "", pin["creator"], pin["lat"], pin["lng"]))
                    cur.execute("DELETE FROM pins WHERE id=%s", (pin["id"],))

        # ── Konum kaydet ──────────────────────────────────────────────────────
        cur.execute("""
            INSERT INTO locations
              (user_id,device_id,device_type,lat,lng,altitude,speed,animation_type,
               room_name,character,last_seen,idle_status,idle_minutes,idle_start)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (user_id) DO UPDATE SET
              device_id=EXCLUDED.device_id, device_type=EXCLUDED.device_type,
              lat=EXCLUDED.lat, lng=EXCLUDED.lng, altitude=EXCLUDED.altitude,
              speed=EXCLUDED.speed, animation_type=EXCLUDED.animation_type,
              room_name=EXCLUDED.room_name, character=EXCLUDED.character,
              last_seen=EXCLUDED.last_seen, idle_status=EXCLUDED.idle_status,
              idle_minutes=EXCLUDED.idle_minutes, idle_start=EXCLUDED.idle_start
        """, (uid, data.deviceId, data.deviceType, data.lat, data.lng, data.altitude,
              data.speed, data.animationType, data.roomName, data.character,
              now, idle_status, idle_minutes, idle_start))

    return {"status": "ok", "time": now}

# ═══════════════════════════════════════════════════════════════════════════════
# 📍 KONUM LİSTESİ
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/get_locations/{room_name}")
def get_locations(room_name: str, viewer_id: str = ""):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM locations WHERE room_name=%s", (room_name,))
        locs = cur.fetchall()
        cur.execute("SELECT user_id,mode FROM visibility_settings")
        vis = {r["user_id"]: r["mode"] for r in cur.fetchall()}

    result = []
    for loc in locs:
        uid = loc["user_id"]
        if uid == viewer_id: continue
        if not is_online(loc["last_seen"]): continue
        mode = vis.get(uid, "all")
        if mode == "hidden": continue
        if mode == "room":
            # sadece aynı odadaki viewer'a görün
            pass
        result.append({
            "userId": uid, "deviceId": loc["device_id"],
            "lat": loc["lat"], "lng": loc["lng"],
            "deviceType": loc["device_type"], "altitude": loc["altitude"],
            "speed": loc["speed"], "animationType": loc["animation_type"],
            "roomName": loc["room_name"], "idleStatus": loc["idle_status"],
            "idleMinutes": loc["idle_minutes"], "character": loc["character"],
        })
    return result

# ═══════════════════════════════════════════════════════════════════════════════
# 📍 ROTA GEÇMİŞİ
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/get_location_history/{user_id}")
def get_location_history(user_id: str, period: str = "all", device_id: str = ""):
    with db() as conn:
        cur = conn.cursor()
        # deviceId ile güncel userId bul
        if device_id:
            cur.execute("SELECT user_id FROM device_registry WHERE device_id=%s", (device_id,))
            row = cur.fetchone()
            if row: user_id = row["user_id"]

        if period == "all":
            cur.execute("SELECT lat,lng,timestamp,speed FROM location_history WHERE user_id=%s ORDER BY id", (user_id,))
        else:
            delta = {"day": timedelta(days=1), "week": timedelta(weeks=1),
                     "month": timedelta(days=30), "year": timedelta(days=365)}.get(period, timedelta(days=1))
            cutoff = (datetime.now(TZ) - delta).strftime("%Y-%m-%d %H:%M:%S")
            cur.execute("SELECT lat,lng,timestamp,speed FROM location_history WHERE user_id=%s AND timestamp>%s ORDER BY id",
                        (user_id, cutoff))
        return [dict(r) for r in cur.fetchall()]

@app.delete("/clear_history/{user_id}")
def clear_history(user_id: str, device_id: str = ""):
    with db() as conn:
        cur = conn.cursor()
        if device_id:
            cur.execute("SELECT user_id FROM device_registry WHERE device_id=%s", (device_id,))
            row = cur.fetchone()
            if row: user_id = row["user_id"]
        cur.execute("DELETE FROM location_history WHERE user_id=%s", (user_id,))
    return {"message": "✅ Geçmiş temizlendi"}

# ═══════════════════════════════════════════════════════════════════════════════
# 📍 PİN
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/create_pin")
def create_pin(data: PinModel):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pins WHERE creator=%s AND room_name=%s", (data.creator, data.roomName))
        if cur.fetchone(): raise HTTPException(400, "Zaten bir pininiz var! Önce kaldırın.")
        pid = str(uuid.uuid4())[:8]
        cur.execute("INSERT INTO pins (id,room_name,creator,lat,lng,created_at,collector_id,collection_start,collection_time) VALUES (%s,%s,%s,%s,%s,%s,NULL,NULL,0)",
                    (pid, data.roomName, data.creator, data.lat, data.lng, now_str()))
    return {"message": "✅ Pin yerleştirildi", "pinId": pid}

@app.get("/get_pins/{room_name}")
def get_pins(room_name: str):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM pins WHERE room_name=%s", (room_name,))
        return [{"id":r["id"],"roomName":r["room_name"],"creator":r["creator"],
                 "lat":r["lat"],"lng":r["lng"],"createdAt":r["created_at"],
                 "collectorId":r["collector_id"],"collectionStart":r["collection_start"],
                 "collectionTime":r["collection_time"]} for r in cur.fetchall()]

@app.delete("/remove_pin/{pin_id}")
def remove_pin(pin_id: str, user_id: str):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT creator FROM pins WHERE id=%s", (pin_id,))
        row = cur.fetchone()
        if not row: raise HTTPException(404, "Pin bulunamadı!")
        if row["creator"] != user_id: raise HTTPException(403, "Sadece sahibi kaldırabilir!")
        cur.execute("DELETE FROM pins WHERE id=%s", (pin_id,))
    return {"message": "✅ Pin kaldırıldı"}

# ═══════════════════════════════════════════════════════════════════════════════
# 🏆 SKOR
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/get_scores/{room_name}")
def get_scores(room_name: str):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id,score FROM scores WHERE room_name=%s ORDER BY score DESC", (room_name,))
        return [{"userId": r["user_id"], "score": r["score"]} for r in cur.fetchall()]

@app.get("/get_collection_history/{room_name}/{user_id}")
def get_collection_history(room_name: str, user_id: str):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM pin_collection_history WHERE room_name=%s AND user_id=%s ORDER BY id",
                    (room_name, user_id))
        return [dict(r) for r in cur.fetchall()]

# ═══════════════════════════════════════════════════════════════════════════════
# 💬 1-1 MESAJ
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/send_message")
def send_message(data: MessageModel):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO messages (from_user,to_user,conv_key,message,timestamp,is_read) VALUES (%s,%s,%s,%s,%s,FALSE)",
                    (data.fromUser, data.toUser, conv_key(data.fromUser, data.toUser), data.message, now_str()))
    return {"message": "✅ Mesaj gönderildi"}

@app.get("/get_conversation/{user1}/{user2}")
def get_conversation(user1: str, user2: str):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM messages WHERE conv_key=%s ORDER BY id", (conv_key(user1, user2),))
        return [{"from":r["from_user"],"to":r["to_user"],"message":r["message"],
                 "timestamp":r["timestamp"],"read":r["is_read"]} for r in cur.fetchall()]

@app.post("/mark_as_read/{user_id}/{other_user}")
def mark_as_read(user_id: str, other_user: str):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE messages SET is_read=TRUE WHERE conv_key=%s AND to_user=%s",
                    (conv_key(user_id, other_user), user_id))
    return {"message": "✅ Okundu"}

@app.get("/get_unread_count/{user_id}")
def get_unread_count(user_id: str):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT from_user, COUNT(*) as c FROM messages WHERE to_user=%s AND is_read=FALSE GROUP BY from_user",
                    (user_id,))
        return {r["from_user"]: r["c"] for r in cur.fetchall()}

# ═══════════════════════════════════════════════════════════════════════════════
# 👥 GRUP MESAJ
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/send_room_message")
def send_room_message(data: RoomMessageModel):
    with db() as conn:
        cur = conn.cursor()
        if data.roomName != "Genel":
            cur.execute("SELECT 1 FROM rooms WHERE room_name=%s", (data.roomName,))
            if not cur.fetchone(): raise HTTPException(404, "Oda bulunamadı!")
        cur.execute("SELECT character FROM locations WHERE user_id=%s", (data.fromUser,))
        char_row = cur.fetchone()
        character = char_row["character"] if char_row else "🧍"
        mid = str(uuid.uuid4())[:8]
        cur.execute("INSERT INTO room_messages (id,room_name,from_user,message,timestamp,character) VALUES (%s,%s,%s,%s,%s,%s)",
                    (mid, data.roomName, data.fromUser, data.message, now_str(), character))
        # Eski temizle
        cur.execute("""
            DELETE FROM room_messages WHERE room_name=%s AND id NOT IN (
                SELECT id FROM room_messages WHERE room_name=%s ORDER BY timestamp DESC LIMIT %s)
        """, (data.roomName, data.roomName, MAX_ROOM_MSGS))
    return {"message": "✅ Gönderildi"}

@app.get("/get_room_messages/{room_name}")
def get_room_messages(room_name: str, limit: int = 50):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM (SELECT * FROM room_messages WHERE room_name=%s ORDER BY timestamp DESC LIMIT %s) sub
            ORDER BY timestamp ASC
        """, (room_name, limit))
        return [{"id":r["id"],"from":r["from_user"],"message":r["message"],
                 "timestamp":r["timestamp"],"character":r["character"]} for r in cur.fetchall()]

@app.get("/get_room_messages_since/{room_name}")
def get_room_messages_since(room_name: str, last_id: str = ""):
    with db() as conn:
        cur = conn.cursor()
        if not last_id:
            cur.execute("SELECT * FROM room_messages WHERE room_name=%s ORDER BY timestamp DESC LIMIT 50", (room_name,))
            rows = list(reversed(cur.fetchall()))
        else:
            cur.execute("SELECT timestamp FROM room_messages WHERE id=%s", (last_id,))
            ts_row = cur.fetchone()
            if ts_row:
                cur.execute("SELECT * FROM room_messages WHERE room_name=%s AND timestamp>%s ORDER BY timestamp",
                            (room_name, ts_row["timestamp"]))
                rows = cur.fetchall()
            else:
                cur.execute("SELECT * FROM room_messages WHERE room_name=%s ORDER BY timestamp DESC LIMIT 50", (room_name,))
                rows = list(reversed(cur.fetchall()))
        return [{"id":r["id"],"from":r["from_user"],"message":r["message"],
                 "timestamp":r["timestamp"],"character":r["character"]} for r in rows]

# ═══════════════════════════════════════════════════════════════════════════════
# 👤 KULLANICI ADI DEĞİŞTİRME
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/change_username")
def change_username(data: ChangeUsernameModel):
    old, new = data.oldName, data.newName.strip()
    if not new: raise HTTPException(400, "İsim boş olamaz!")
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM locations WHERE user_id=%s", (new,))
        if cur.fetchone() and new != old:
            raise HTTPException(400, "Bu isim zaten kullanımda!")

        cur.execute("UPDATE device_registry SET user_id=%s WHERE user_id=%s", (new, old))
        cur.execute("UPDATE rooms SET created_by=%s WHERE created_by=%s", (new, old))
        cur.execute("UPDATE locations SET user_id=%s WHERE user_id=%s", (new, old))
        cur.execute("UPDATE location_history SET user_id=%s WHERE user_id=%s", (new, old))
        cur.execute("""
            UPDATE scores SET user_id=%s WHERE user_id=%s
            AND NOT EXISTS (SELECT 1 FROM scores s2 WHERE s2.room_name=scores.room_name AND s2.user_id=%s)
        """, (new, old, new))
        cur.execute("UPDATE pin_collection_history SET user_id=%s WHERE user_id=%s", (new, old))
        cur.execute("UPDATE room_messages SET from_user=%s WHERE from_user=%s", (new, old))
        cur.execute("UPDATE visibility_settings SET user_id=%s WHERE user_id=%s", (new, old))
        # 1-1 mesajlar
        cur.execute("SELECT id,from_user,to_user FROM messages WHERE from_user=%s OR to_user=%s", (old, old))
        for msg in cur.fetchall():
            nf = new if msg["from_user"] == old else msg["from_user"]
            nt = new if msg["to_user"]   == old else msg["to_user"]
            cur.execute("UPDATE messages SET from_user=%s,to_user=%s,conv_key=%s WHERE id=%s",
                        (nf, nt, conv_key(nf, nt), msg["id"]))
    return {"message": f"✅ İsim değiştirildi: {old} → {new}"}

# ═══════════════════════════════════════════════════════════════════════════════
# 🔧 YÖNETİM
# ═══════════════════════════════════════════════════════════════════════════════

@app.delete("/remove_user/{user_id}")
def remove_user(user_id: str):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM locations WHERE user_id=%s", (user_id,))
    return {"message": f"✅ {user_id} silindi"}

@app.post("/register_fcm_token")
def register_fcm_token(data: dict):
    return {"message": "✅ FCM token kaydedildi"}

@app.delete("/clear")
def clear_all():
    with db() as conn:
        cur = conn.cursor()
        for t in ["locations","location_history","pins","scores",
                  "pin_collection_history","messages","room_messages"]:
            cur.execute(f"DELETE FROM {t}")
    return {"message": "✅ Tüm veriler silindi"}
