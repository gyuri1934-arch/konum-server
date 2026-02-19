# ═══════════════════════════════════════════════════════════════════════════════
#                    KONUM TAKİP SERVER — PostgreSQL
# ═══════════════════════════════════════════════════════════════════════════════
# Versiyon: 3.0 — Kalıcı veritabanı, restart'ta veri kaybolmaz
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
# 📦 İMPORTLAR
# ═══════════════════════════════════════════════════════════════════════════════

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
from math import radians, sin, cos, sqrt, atan2
from contextlib import contextmanager
import psycopg2
import psycopg2.extras
import pytz
import uuid
import os
import base64

# ═══════════════════════════════════════════════════════════════════════════════
# ⚙️ UYGULAMA
# ═══════════════════════════════════════════════════════════════════════════════

app = FastAPI(title="Konum Takip API", version="3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════════════════════════════════════
# 🗄️ VERİTABANI BAĞLANTISI
# ═══════════════════════════════════════════════════════════════════════════════
# Render PostgreSQL → Dashboard > Environment > DATABASE_URL otomatik eklenir
# Yerel test için: export DATABASE_URL="postgresql://user:pass@localhost/dbname"

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Render bazen "postgres://" prefix verir, psycopg2 "postgresql://" ister
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

@contextmanager
def get_db():
    """Her request için ayrı bağlantı — thread-safe"""
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def db_execute(sql: str, params=None, fetch: str = None):
    """Tek satır helper — SELECT/INSERT/UPDATE/DELETE"""
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            if fetch == "one":
                return cur.fetchone()
            if fetch == "all":
                return cur.fetchall()
            return None

# ═══════════════════════════════════════════════════════════════════════════════
# 🏗️ TABLO OLUŞTURMA (uygulama ilk açıldığında çalışır)
# ═══════════════════════════════════════════════════════════════════════════════

def create_tables():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            -- Kullanıcı konumları
            CREATE TABLE IF NOT EXISTS locations (
                user_id       TEXT PRIMARY KEY,
                device_id     TEXT DEFAULT '',
                device_type   TEXT DEFAULT 'phone',
                lat           DOUBLE PRECISION NOT NULL,
                lng           DOUBLE PRECISION NOT NULL,
                altitude      DOUBLE PRECISION DEFAULT 0,
                speed         DOUBLE PRECISION DEFAULT 0,
                animation_type TEXT DEFAULT 'pulse',
                room_name     TEXT DEFAULT 'Genel',
                character     TEXT DEFAULT '🧍',
                idle_status   TEXT DEFAULT 'online',
                idle_minutes  INTEGER DEFAULT 0,
                idle_start    TEXT,
                visibility    TEXT DEFAULT 'all',
                fcm_token     TEXT,
                last_seen     TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );

            -- Rota geçmişi
            CREATE TABLE IF NOT EXISTS location_history (
                id         SERIAL PRIMARY KEY,
                user_id    TEXT NOT NULL,
                lat        DOUBLE PRECISION NOT NULL,
                lng        DOUBLE PRECISION NOT NULL,
                speed      DOUBLE PRECISION DEFAULT 0,
                recorded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_history_user ON location_history(user_id);
            CREATE INDEX IF NOT EXISTS idx_history_time ON location_history(recorded_at);

            -- Odalar
            CREATE TABLE IF NOT EXISTS rooms (
                name        TEXT PRIMARY KEY,
                password    TEXT NOT NULL,
                created_by  TEXT NOT NULL,
                created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );

            -- Oda yetkileri (collector + voice)
            CREATE TABLE IF NOT EXISTS room_permissions (
                room_name   TEXT NOT NULL,
                user_id     TEXT NOT NULL,
                can_collect BOOLEAN DEFAULT FALSE,
                can_voice   BOOLEAN DEFAULT FALSE,
                PRIMARY KEY (room_name, user_id)
            );

            -- Pinler
            CREATE TABLE IF NOT EXISTS pins (
                id              TEXT PRIMARY KEY,
                room_name       TEXT NOT NULL,
                creator         TEXT NOT NULL,
                lat             DOUBLE PRECISION NOT NULL,
                lng             DOUBLE PRECISION NOT NULL,
                collector_id    TEXT,
                collection_start TIMESTAMP WITH TIME ZONE,
                collection_time INTEGER DEFAULT 0,
                created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );

            -- Skorlar
            CREATE TABLE IF NOT EXISTS scores (
                room_name  TEXT NOT NULL,
                user_id    TEXT NOT NULL,
                score      INTEGER DEFAULT 0,
                PRIMARY KEY (room_name, user_id)
            );

            -- 1-1 mesajlar
            CREATE TABLE IF NOT EXISTS messages (
                id         SERIAL PRIMARY KEY,
                from_user  TEXT NOT NULL,
                to_user    TEXT NOT NULL,
                message    TEXT NOT NULL,
                is_read    BOOLEAN DEFAULT FALSE,
                sent_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_msg_users ON messages(from_user, to_user);

            -- Grup mesajları
            CREATE TABLE IF NOT EXISTS room_messages (
                id         TEXT PRIMARY KEY,
                room_name  TEXT NOT NULL,
                from_user  TEXT NOT NULL,
                message    TEXT NOT NULL,
                character  TEXT DEFAULT '🧍',
                sent_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_rmsg_room ON room_messages(room_name, sent_at);

            -- Walkie-talkie ses chunk'ları (kısa süreli, temizlenir)
            CREATE TABLE IF NOT EXISTS walkie_chunks (
                id          TEXT PRIMARY KEY,
                type        TEXT NOT NULL,  -- 'room' veya 'p2p'
                room_name   TEXT,
                from_user   TEXT NOT NULL,
                to_user     TEXT,
                audio_data  BYTEA NOT NULL,
                created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );

            -- Müzik yayını chunk'ları
            CREATE TABLE IF NOT EXISTS music_chunks (
                id           TEXT PRIMARY KEY,
                room_name    TEXT NOT NULL,
                broadcaster  TEXT NOT NULL,
                chunk_index  INTEGER NOT NULL,
                audio_data   BYTEA NOT NULL,
                created_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );

            -- Aktif müzik yayınları
            CREATE TABLE IF NOT EXISTS music_streams (
                room_name    TEXT PRIMARY KEY,
                broadcaster  TEXT NOT NULL,
                title        TEXT DEFAULT '🎵 Müzik Yayını',
                active       BOOLEAN DEFAULT TRUE,
                chunk_index  INTEGER DEFAULT 0,
                started_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );

            -- Ban listesi
            CREATE TABLE IF NOT EXISTS bans (
                id           SERIAL PRIMARY KEY,
                user_id      TEXT,
                fingerprint  TEXT,
                banned_by    TEXT NOT NULL,
                reason       TEXT DEFAULT '',
                banned_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_ban_fp ON bans(fingerprint);
            CREATE INDEX IF NOT EXISTS idx_ban_uid ON bans(user_id);

            -- Pin toplama geçmişi
            CREATE TABLE IF NOT EXISTS pin_collection_history (
                id          SERIAL PRIMARY KEY,
                room_name   TEXT NOT NULL,
                collector   TEXT NOT NULL,
                creator     TEXT NOT NULL,
                lat         DOUBLE PRECISION,
                lng         DOUBLE PRECISION,
                collected_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
            """)
    print("✅ Tablolar hazır")

# Uygulama başlarken tabloları oluştur
@app.on_event("startup")
def startup():
    create_tables()
    # Eski walkie chunk'larını temizle (1 saatten eskiler)
    db_execute("DELETE FROM walkie_chunks WHERE created_at < NOW() - INTERVAL '1 hour'")
    db_execute("DELETE FROM music_chunks WHERE created_at < NOW() - INTERVAL '2 hours'")

# ═══════════════════════════════════════════════════════════════════════════════
# 🎛️ SİSTEM AYARLARI
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_TIMEZONE   = pytz.timezone('Europe/Istanbul')
USER_TIMEOUT       = 120
IDLE_THRESHOLD     = 15
IDLE_TIME_MINUTES  = 15
SPEED_VEHICLE      = 30
SPEED_WALK         = 3
MIN_DIST_VEHICLE   = 50
MIN_DIST_RUN       = 20
MIN_DIST_WALK      = 10
MIN_DIST_IDLE      = 5
MAX_POINTS_PER_USER = 5000
MAX_HISTORY_DAYS   = 90
PIN_COLLECT_START  = 20
PIN_COLLECT_END    = 25
MAX_ROOM_MESSAGES  = 200
MAX_WALKIE_CHUNKS  = 30
MAX_MUSIC_CHUNKS   = 60

# ═══════════════════════════════════════════════════════════════════════════════
# 👑 SÜPER ADMİN
# ═══════════════════════════════════════════════════════════════════════════════

SUPER_ADMIN_DEVICE_IDS = {
    "BURAYA_KENDI_CIHAZ_ID_NI_YAZ",
}

_failed_attempts: dict = {}
MAX_FAILED_ATTEMPTS    = 5
BLOCK_DURATION_MINUTES = 30

def _check_rate_limit(ip: str) -> bool:
    e = _failed_attempts.get(ip)
    if not e: return True
    if e.get("blocked_until") and datetime.now(DEFAULT_TIMEZONE) < e["blocked_until"]:
        return False
    _failed_attempts.pop(ip, None)
    return True

def _record_failure(ip: str):
    e = _failed_attempts.setdefault(ip, {"count": 0, "blocked_until": None})
    e["count"] += 1
    if e["count"] >= MAX_FAILED_ATTEMPTS:
        e["blocked_until"] = datetime.now(DEFAULT_TIMEZONE) + timedelta(minutes=BLOCK_DURATION_MINUTES)

def _record_success(ip: str):
    _failed_attempts.pop(ip, None)

def is_super_admin(user_id: str, device_id: str = "") -> bool:
    if device_id and device_id in SUPER_ADMIN_DEVICE_IDS:
        return True
    row = db_execute("SELECT device_id FROM locations WHERE user_id=%s", (user_id,), fetch="one")
    if row and row["device_id"] in SUPER_ADMIN_DEVICE_IDS:
        return True
    return False

# ═══════════════════════════════════════════════════════════════════════════════
# 🛠️ YARDIMCI FONKSİYONLAR
# ═══════════════════════════════════════════════════════════════════════════════

def get_local_time():
    return datetime.now(DEFAULT_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")

def haversine(lat1, lng1, lat2, lng2):
    R = 6371000
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1-a))

def is_user_online(last_seen) -> bool:
    if last_seen is None: return False
    try:
        if isinstance(last_seen, str):
            last_seen = datetime.strptime(last_seen, "%Y-%m-%d %H:%M:%S")
            last_seen = DEFAULT_TIMEZONE.localize(last_seen)
        elif last_seen.tzinfo is None:
            last_seen = DEFAULT_TIMEZONE.localize(last_seen)
        return (datetime.now(DEFAULT_TIMEZONE) - last_seen).total_seconds() < USER_TIMEOUT
    except:
        return False

def is_banned(user_id: str, device_id: str) -> bool:
    row = db_execute(
        "SELECT 1 FROM bans WHERE user_id=%s OR fingerprint=%s LIMIT 1",
        (user_id, device_id), fetch="one")
    return row is not None

def fmt_ago(last_seen) -> str:
    try:
        if isinstance(last_seen, str):
            last_seen = datetime.strptime(last_seen, "%Y-%m-%d %H:%M:%S")
            last_seen = DEFAULT_TIMEZONE.localize(last_seen)
        elif last_seen.tzinfo is None:
            last_seen = DEFAULT_TIMEZONE.localize(last_seen)
        mins = int((datetime.now(DEFAULT_TIMEZONE) - last_seen).total_seconds() / 60)
        if mins < 60:   return f"{mins} dakika önce"
        if mins < 1440: return f"{mins//60} saat önce"
        return f"{mins//1440} gün önce"
    except:
        return "Bilinmiyor"

# ═══════════════════════════════════════════════════════════════════════════════
# 📋 VERİ MODELLERİ
# ═══════════════════════════════════════════════════════════════════════════════

class LocationModel(BaseModel):
    userId: str
    deviceId: str = ""
    deviceType: str = "phone"
    lat: float
    lng: float
    altitude: float = 0
    speed: float = 0
    animationType: str = "pulse"
    roomName: str = "Genel"
    character: str = "🧍"

class RoomModel(BaseModel):
    roomName: str
    password: str
    createdBy: str

class JoinRoomModel(BaseModel):
    roomName: str
    password: str

class PinModel(BaseModel):
    roomName: str
    creator: str
    lat: float
    lng: float

class MessageModel(BaseModel):
    fromUser: str
    toUser: str
    message: str

class RoomMessageModel(BaseModel):
    roomName: str
    fromUser: str
    message: str

class VisibilityModel(BaseModel):
    userId: str
    mode: str
    allowed: List[str] = []

class ChangeUsernameModel(BaseModel):
    deviceId: str
    oldName: str
    newName: str

class WalkieChunkModel(BaseModel):
    roomName: str = ""
    fromUser: str
    toUser: str = ""
    audioBase64: str

class MusicStartModel(BaseModel):
    roomName: str
    broadcasterId: str
    title: str = "🎵 Müzik Yayını"

class MusicChunkModel(BaseModel):
    roomName: str
    broadcasterId: str
    audioBase64: str

class MusicStopModel(BaseModel):
    roomName: str
    broadcasterId: str

class BanModel(BaseModel):
    userId: str
    adminId: str
    deviceId: str = ""
    reason: str = ""

# ═══════════════════════════════════════════════════════════════════════════════
# 🏠 SAĞLIK
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/")
def root():
    online = db_execute(
        "SELECT COUNT(*) as n FROM locations WHERE last_seen > NOW() - INTERVAL '2 minutes'",
        fetch="one")
    rooms_count = db_execute("SELECT COUNT(*) as n FROM rooms", fetch="one")
    pins_count  = db_execute("SELECT COUNT(*) as n FROM pins", fetch="one")
    return {
        "status": "✅ Server çalışıyor (PostgreSQL)",
        "time": get_local_time(),
        "online_users": online["n"] if online else 0,
        "total_rooms": (rooms_count["n"] if rooms_count else 0) + 1,
        "total_pins": pins_count["n"] if pins_count else 0,
    }

@app.get("/health")
def health():
    return {"status": "ok", "time": get_local_time()}

# ═══════════════════════════════════════════════════════════════════════════════
# 🚪 ODA YÖNETİMİ
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/create_room")
def create_room(data: RoomModel):
    exists = db_execute("SELECT 1 FROM rooms WHERE name=%s", (data.roomName,), fetch="one")
    if exists:
        raise HTTPException(400, "Bu oda adı zaten mevcut!")
    if len(data.password) < 3:
        raise HTTPException(400, "Şifre en az 3 karakter olmalı!")
    db_execute(
        "INSERT INTO rooms(name, password, created_by) VALUES(%s,%s,%s)",
        (data.roomName, data.password, data.createdBy))
    return {"message": f"✅ {data.roomName} odası oluşturuldu"}

@app.post("/join_room")
def join_room(data: JoinRoomModel):
    if data.roomName == "Genel":
        return {"message": "Genel odaya katıldınız"}
    row = db_execute("SELECT password FROM rooms WHERE name=%s", (data.roomName,), fetch="one")
    if not row:
        raise HTTPException(404, "Oda bulunamadı!")
    if row["password"] != data.password:
        raise HTTPException(401, "Yanlış şifre!")
    return {"message": f"✅ {data.roomName} odasına katıldınız"}

@app.get("/get_rooms")
def get_rooms(user_id: str = ""):
    rooms = db_execute("SELECT * FROM rooms ORDER BY created_at", fetch="all") or []
    result = [{
        "name": "Genel",
        "hasPassword": False,
        "userCount": db_execute(
            "SELECT COUNT(*) as n FROM locations WHERE room_name='Genel' AND last_seen > NOW()-INTERVAL '2 minutes'",
            fetch="one")["n"],
        "createdBy": "system", "isAdmin": False, "password": None,
    }]
    for r in rooms:
        is_admin = r["created_by"] == user_id
        perms = db_execute(
            "SELECT user_id FROM room_permissions WHERE room_name=%s", (r["name"],), fetch="all") or []
        result.append({
            "name": r["name"],
            "hasPassword": True,
            "userCount": db_execute(
                "SELECT COUNT(*) as n FROM locations WHERE room_name=%s AND last_seen > NOW()-INTERVAL '2 minutes'",
                (r["name"],), fetch="one")["n"],
            "createdBy": r["created_by"],
            "isAdmin": is_admin,
            "password": r["password"] if is_admin else None,
        })
    return result

@app.delete("/delete_room/{room_name}")
def delete_room(room_name: str, admin_id: str):
    row = db_execute("SELECT created_by FROM rooms WHERE name=%s", (room_name,), fetch="one")
    if not row: raise HTTPException(404, "Oda bulunamadı!")
    if row["created_by"] != admin_id: raise HTTPException(403, "Sadece admin silebilir!")
    db_execute("DELETE FROM rooms WHERE name=%s", (room_name,))
    db_execute("DELETE FROM room_permissions WHERE room_name=%s", (room_name,))
    db_execute("DELETE FROM pins WHERE room_name=%s", (room_name,))
    db_execute("DELETE FROM scores WHERE room_name=%s", (room_name,))
    db_execute("DELETE FROM room_messages WHERE room_name=%s", (room_name,))
    db_execute("UPDATE locations SET room_name='Genel' WHERE room_name=%s", (room_name,))
    return {"message": f"✅ {room_name} silindi"}

@app.get("/get_room_password/{room_name}")
def get_room_password(room_name: str, admin_id: str):
    row = db_execute("SELECT password, created_by FROM rooms WHERE name=%s", (room_name,), fetch="one")
    if not row: raise HTTPException(404, "Oda bulunamadı!")
    if row["created_by"] != admin_id: raise HTTPException(403, "Sadece admin görebilir!")
    return {"password": row["password"]}

@app.get("/get_room_permissions/{room_name}")
def get_room_permissions(room_name: str):
    if room_name == "Genel":
        return {"admin": None, "collectors": [], "voiceAllowed": []}
    row = db_execute("SELECT created_by FROM rooms WHERE name=%s", (room_name,), fetch="one")
    if not row: return {"admin": None, "collectors": [], "voiceAllowed": []}
    perms = db_execute(
        "SELECT user_id, can_collect, can_voice FROM room_permissions WHERE room_name=%s",
        (room_name,), fetch="all") or []
    return {
        "admin": row["created_by"],
        "collectors": [p["user_id"] for p in perms if p["can_collect"]],
        "voiceAllowed": [p["user_id"] for p in perms if p["can_voice"]],
    }

@app.post("/set_collector_permission/{room_name}/{target_user}")
def set_collector_permission(room_name: str, target_user: str, admin_id: str, enabled: bool):
    row = db_execute("SELECT created_by FROM rooms WHERE name=%s", (room_name,), fetch="one")
    if not row: raise HTTPException(404, "Oda bulunamadı!")
    if row["created_by"] != admin_id: raise HTTPException(403, "Sadece admin yetkilendirebilir!")
    db_execute("""
        INSERT INTO room_permissions(room_name, user_id, can_collect)
        VALUES(%s,%s,%s)
        ON CONFLICT(room_name, user_id) DO UPDATE SET can_collect=EXCLUDED.can_collect
    """, (room_name, target_user, enabled))
    return {"message": "✅ Yetki güncellendi"}

@app.post("/set_voice_permission/{room_name}/{target_user}")
def set_voice_permission(room_name: str, target_user: str, admin_id: str, enabled: bool):
    row = db_execute("SELECT created_by FROM rooms WHERE name=%s", (room_name,), fetch="one")
    if not row: raise HTTPException(404, "Oda bulunamadı!")
    if row["created_by"] != admin_id: raise HTTPException(403, "Sadece admin yetkilendirebilir!")
    db_execute("""
        INSERT INTO room_permissions(room_name, user_id, can_voice)
        VALUES(%s,%s,%s)
        ON CONFLICT(room_name, user_id) DO UPDATE SET can_voice=EXCLUDED.can_voice
    """, (room_name, target_user, enabled))
    return {"message": "✅ Ses yetkisi güncellendi"}

# ═══════════════════════════════════════════════════════════════════════════════
# 👁️ GÖRÜNÜRLİK
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/set_visibility")
def set_visibility(data: VisibilityModel):
    db_execute(
        "UPDATE locations SET visibility=%s WHERE user_id=%s",
        (data.mode, data.userId))
    return {"message": "✅ Görünürlük güncellendi"}

# ═══════════════════════════════════════════════════════════════════════════════
# 📍 KONUM GÜNCELLEMESİ
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/update_location")
def update_location(data: LocationModel):
    uid = data.userId

    # Ban kontrolü
    if is_banned(uid, data.deviceId):
        raise HTTPException(403, "Bu cihaz/kullanıcı banlanmıştır.")

    now = get_local_time()

    # Mevcut konumu al
    old = db_execute("SELECT * FROM locations WHERE user_id=%s", (uid,), fetch="one")

    # Hareketsizlik kontrolü
    idle_status  = "online"
    idle_minutes = 0
    idle_start   = None

    if old:
        dist = haversine(old["lat"], old["lng"], data.lat, data.lng)
        if dist < IDLE_THRESHOLD:
            idle_start = old["idle_start"] or now
            try:
                s_dt = datetime.strptime(idle_start, "%Y-%m-%d %H:%M:%S")
                s_dt = DEFAULT_TIMEZONE.localize(s_dt)
                mins = (datetime.now(DEFAULT_TIMEZONE) - s_dt).total_seconds() / 60
                if mins >= IDLE_TIME_MINUTES:
                    idle_status  = "idle"
                    idle_minutes = int(mins)
            except:
                idle_start = now
        # else: hareket var, idle_start=None kalır

    # Rota geçmişine ekle
    should_add = True
    if old:
        last_h = db_execute(
            "SELECT lat, lng FROM location_history WHERE user_id=%s ORDER BY recorded_at DESC LIMIT 1",
            (uid,), fetch="one")
        if last_h:
            dist = haversine(last_h["lat"], last_h["lng"], data.lat, data.lng)
            spd  = data.speed
            if   spd >= SPEED_VEHICLE: should_add = dist >= MIN_DIST_VEHICLE
            elif spd >= SPEED_WALK:    should_add = dist >= MIN_DIST_RUN
            elif spd >= 0.5:           should_add = dist >= MIN_DIST_WALK
            else:                      should_add = dist >= MIN_DIST_IDLE

    if should_add:
        db_execute(
            "INSERT INTO location_history(user_id,lat,lng,speed) VALUES(%s,%s,%s,%s)",
            (uid, data.lat, data.lng, data.speed))
        # Eski kayıtları temizle
        db_execute("""
            DELETE FROM location_history
            WHERE user_id=%s
              AND id NOT IN (
                SELECT id FROM location_history
                WHERE user_id=%s ORDER BY recorded_at DESC LIMIT %s
              )
              AND recorded_at < NOW() - INTERVAL '%s days'
        """, (uid, uid, MAX_POINTS_PER_USER, MAX_HISTORY_DAYS))

    # Pin toplama — yetki kontrolü
    perms = db_execute(
        "SELECT can_collect FROM room_permissions WHERE room_name=%s AND user_id=%s",
        (data.roomName, uid), fetch="one")
    can_collect = perms and perms["can_collect"]

    if can_collect:
        active_pins = db_execute(
            "SELECT * FROM pins WHERE room_name=%s AND creator!=%s",
            (data.roomName, uid), fetch="all") or []
        for pin in active_pins:
            pin_dist = haversine(data.lat, data.lng, pin["lat"], pin["lng"])
            if pin_dist <= PIN_COLLECT_START:
                if pin["collector_id"] is None:
                    db_execute(
                        "UPDATE pins SET collector_id=%s, collection_start=NOW(), collection_time=0 WHERE id=%s",
                        (uid, pin["id"]))
                elif pin["collector_id"] == uid:
                    db_execute(
                        "UPDATE pins SET collection_time=EXTRACT(EPOCH FROM (NOW()-collection_start))::int WHERE id=%s",
                        (pin["id"],))
            elif pin_dist > PIN_COLLECT_END and pin["collector_id"] == uid:
                # Toplandı!
                db_execute("""
                    INSERT INTO scores(room_name, user_id, score) VALUES(%s,%s,1)
                    ON CONFLICT(room_name,user_id) DO UPDATE SET score=scores.score+1
                """, (data.roomName, uid))
                db_execute("""
                    INSERT INTO pin_collection_history(room_name,collector,creator,lat,lng)
                    VALUES(%s,%s,%s,%s,%s)
                """, (data.roomName, uid, pin["creator"], pin["lat"], pin["lng"]))
                db_execute("DELETE FROM pins WHERE id=%s", (pin["id"],))

    # Konumu kaydet/güncelle
    db_execute("""
        INSERT INTO locations(
            user_id, device_id, device_type, lat, lng, altitude, speed,
            animation_type, room_name, character, idle_status, idle_minutes,
            idle_start, last_seen)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
        ON CONFLICT(user_id) DO UPDATE SET
            device_id=%s, device_type=%s, lat=%s, lng=%s, altitude=%s, speed=%s,
            animation_type=%s, room_name=%s, character=%s, idle_status=%s,
            idle_minutes=%s, idle_start=%s, last_seen=NOW()
    """, (
        uid, data.deviceId, data.deviceType, data.lat, data.lng, data.altitude, data.speed,
        data.animationType, data.roomName, data.character, idle_status, idle_minutes, idle_start,
        # UPDATE kısmı
        data.deviceId, data.deviceType, data.lat, data.lng, data.altitude, data.speed,
        data.animationType, data.roomName, data.character, idle_status, idle_minutes, idle_start,
    ))

    return {"status": "ok", "time": now}

# ═══════════════════════════════════════════════════════════════════════════════
# 📍 KONUM LİSTESİ
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/get_locations/{room_name}")
def get_locations(room_name: str, viewer_id: str = "", viewer_device_id: str = ""):
    super_admin = is_super_admin(viewer_id, viewer_device_id)
    viewer_row  = db_execute("SELECT room_name FROM locations WHERE user_id=%s", (viewer_id,), fetch="one")
    viewer_room = viewer_row["room_name"] if viewer_row else "Genel"

    if super_admin:
        rows = db_execute(
            "SELECT * FROM locations WHERE user_id!=%s AND last_seen > NOW()-INTERVAL '2 minutes'",
            (viewer_id,), fetch="all") or []
    else:
        rows = db_execute(
            "SELECT * FROM locations WHERE user_id!=%s AND room_name=%s AND last_seen > NOW()-INTERVAL '2 minutes'",
            (viewer_id, room_name), fetch="all") or []

    result = []
    for r in rows:
        if not super_admin:
            vis = r["visibility"] or "all"
            if vis == "hidden": continue
            if vis == "room" and r["room_name"] != viewer_room: continue
        result.append({
            "userId":      r["user_id"],
            "deviceId":    r["device_id"],
            "lat":         r["lat"],
            "lng":         r["lng"],
            "deviceType":  r["device_type"],
            "altitude":    r["altitude"],
            "speed":       r["speed"],
            "animationType": r["animation_type"],
            "roomName":    r["room_name"],
            "idleStatus":  r["idle_status"],
            "idleMinutes": r["idle_minutes"],
            "character":   r["character"],
            "isHidden":    r["visibility"] == "hidden",
        })
    return result

@app.get("/get_offline_users")
def get_offline_users(admin_id: str, device_id: str = ""):
    if not is_super_admin(admin_id, device_id):
        raise HTTPException(403, "Sadece süper admin görebilir!")
    rows = db_execute(
        "SELECT * FROM locations WHERE last_seen <= NOW()-INTERVAL '2 minutes' ORDER BY last_seen DESC",
        fetch="all") or []
    return [{
        "userId":    r["user_id"],
        "lat":       r["lat"],
        "lng":       r["lng"],
        "lastSeen":  str(r["last_seen"])[:16] if r["last_seen"] else "-",
        "agoText":   fmt_ago(r["last_seen"]),
        "roomName":  r["room_name"],
        "deviceType": r["device_type"],
        "character": r["character"],
    } for r in rows]

@app.get("/check_super_admin/{user_id}")
def check_super_admin(request: Request, user_id: str, device_id: str = ""):
    ip = request.client.host
    if not _check_rate_limit(ip):
        raise HTTPException(429, "Çok fazla deneme. 30 dakika bekle.")
    result = is_super_admin(user_id, device_id)
    (_record_success if result else _record_failure)(ip)
    return {"isSuperAdmin": result}

@app.get("/get_all_rooms_info")
def get_all_rooms_info(request: Request, admin_id: str, device_id: str = ""):
    ip = request.client.host
    if not _check_rate_limit(ip): raise HTTPException(429, "Rate limit.")
    if not is_super_admin(admin_id, device_id):
        _record_failure(ip); raise HTTPException(403, "Yetkisiz!")
    _record_success(ip)
    room_names = ["Genel"] + [r["name"] for r in (db_execute("SELECT name FROM rooms", fetch="all") or [])]
    result = []
    for rn in room_names:
        users = db_execute(
            "SELECT * FROM locations WHERE room_name=%s AND last_seen > NOW()-INTERVAL '2 minutes'",
            (rn,), fetch="all") or []
        result.append({
            "name": rn,
            "userCount": len(users),
            "users": [{
                "userId": u["user_id"], "lat": u["lat"], "lng": u["lng"],
                "idleStatus": u["idle_status"], "idleMinutes": u["idle_minutes"],
                "character": u["character"], "deviceType": u["device_type"],
                "isHidden": u["visibility"] == "hidden",
            } for u in users],
        })
    return result

# ═══════════════════════════════════════════════════════════════════════════════
# 📍 ROTA GEÇMİŞİ
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/get_location_history/{user_id}")
def get_location_history(user_id: str, period: str = "all"):
    interval_map = {
        "day": "1 day", "week": "7 days",
        "month": "30 days", "year": "365 days"
    }
    if period in interval_map:
        rows = db_execute(
            f"SELECT lat, lng, speed, recorded_at FROM location_history WHERE user_id=%s AND recorded_at > NOW()-INTERVAL '{interval_map[period]}' ORDER BY recorded_at",
            (user_id,), fetch="all") or []
    else:
        rows = db_execute(
            "SELECT lat, lng, speed, recorded_at FROM location_history WHERE user_id=%s ORDER BY recorded_at",
            (user_id,), fetch="all") or []
    return [{"lat": r["lat"], "lng": r["lng"], "speed": r["speed"],
             "timestamp": str(r["recorded_at"])[:19]} for r in rows]

@app.delete("/clear_history/{user_id}")
def clear_history(user_id: str):
    db_execute("DELETE FROM location_history WHERE user_id=%s", (user_id,))
    return {"message": "✅ Geçmiş temizlendi"}

# ═══════════════════════════════════════════════════════════════════════════════
# 📍 PIN SİSTEMİ
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/create_pin")
def create_pin(data: PinModel):
    existing = db_execute(
        "SELECT 1 FROM pins WHERE creator=%s AND room_name=%s", (data.creator, data.roomName), fetch="one")
    if existing: raise HTTPException(400, "Zaten bir pininiz var! Önce kaldırın.")
    pin_id = str(uuid.uuid4())[:8]
    db_execute(
        "INSERT INTO pins(id, room_name, creator, lat, lng) VALUES(%s,%s,%s,%s,%s)",
        (pin_id, data.roomName, data.creator, data.lat, data.lng))
    # 🔔 FCM — odadaki herkese bildirim
    _send_fcm_to_room(
        room_name    = data.roomName,
        title        = f"📍 Yeni Pin — {data.roomName}",
        body         = f"{data.creator} bir pin yerleştirdi!",
        exclude_user = data.creator,
        data         = {"type": "pin", "roomName": data.roomName, "creator": data.creator})
    return {"message": "✅ Pin yerleştirildi", "pinId": pin_id}

@app.get("/get_pins/{room_name}")
def get_pins(room_name: str):
    rows = db_execute("SELECT * FROM pins WHERE room_name=%s", (room_name,), fetch="all") or []
    return [{
        "id": r["id"], "roomName": r["room_name"], "creator": r["creator"],
        "lat": r["lat"], "lng": r["lng"],
        "collectorId": r["collector_id"],
        "collectionTime": r["collection_time"] or 0,
        "createdAt": str(r["created_at"])[:19] if r["created_at"] else "",
    } for r in rows]

@app.delete("/remove_pin/{pin_id}")
def remove_pin(pin_id: str, user_id: str):
    row = db_execute("SELECT creator FROM pins WHERE id=%s", (pin_id,), fetch="one")
    if not row: raise HTTPException(404, "Pin bulunamadı!")
    if row["creator"] != user_id: raise HTTPException(403, "Sadece sahibi kaldırabilir!")
    db_execute("DELETE FROM pins WHERE id=%s", (pin_id,))
    return {"message": "✅ Pin kaldırıldı"}

# ═══════════════════════════════════════════════════════════════════════════════
# 🏆 SKOR
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/get_scores/{room_name}")
def get_scores(room_name: str):
    rows = db_execute(
        "SELECT user_id, score FROM scores WHERE room_name=%s ORDER BY score DESC",
        (room_name,), fetch="all") or []
    return [{"userId": r["user_id"], "score": r["score"]} for r in rows]

# ═══════════════════════════════════════════════════════════════════════════════
# 💬 1-1 MESAJLAŞMA
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/send_message")
def send_message(data: MessageModel):
    db_execute(
        "INSERT INTO messages(from_user, to_user, message) VALUES(%s,%s,%s)",
        (data.fromUser, data.toUser, data.message))
    # 🔔 FCM — alıcıya bildirim
    _preview = data.message[:60] + ("..." if len(data.message) > 60 else "")
    _send_fcm_to_user(
        user_id = data.toUser,
        title   = f"💬 {data.fromUser}",
        body    = _preview,
        data    = {"type": "message", "fromUser": data.fromUser})
    return {"message": "✅ Mesaj gönderildi"}

@app.get("/get_conversation/{user1}/{user2}")
def get_conversation(user1: str, user2: str):
    rows = db_execute("""
        SELECT id, from_user, to_user, message, is_read, sent_at
        FROM messages
        WHERE (from_user=%s AND to_user=%s) OR (from_user=%s AND to_user=%s)
        ORDER BY sent_at
        LIMIT 200
    """, (user1, user2, user2, user1), fetch="all") or []
    return [{
        "from": r["from_user"], "to": r["to_user"],
        "message": r["message"], "read": r["is_read"],
        "timestamp": str(r["sent_at"])[:19],
    } for r in rows]

@app.post("/mark_as_read/{user_id}/{other_user}")
def mark_as_read(user_id: str, other_user: str):
    db_execute(
        "UPDATE messages SET is_read=TRUE WHERE to_user=%s AND from_user=%s",
        (user_id, other_user))
    return {"message": "✅ Okundu"}

@app.get("/get_unread_count/{user_id}")
def get_unread_count(user_id: str):
    rows = db_execute("""
        SELECT from_user, COUNT(*) as cnt
        FROM messages WHERE to_user=%s AND is_read=FALSE
        GROUP BY from_user
    """, (user_id,), fetch="all") or []
    return {r["from_user"]: r["cnt"] for r in rows}

# ═══════════════════════════════════════════════════════════════════════════════
# 👥 GRUP MESAJLAŞMA
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/send_room_message")
def send_room_message(data: RoomMessageModel):
    if data.roomName != "Genel":
        exists = db_execute("SELECT 1 FROM rooms WHERE name=%s", (data.roomName,), fetch="one")
        if not exists: raise HTTPException(404, "Oda bulunamadı!")
    char_row = db_execute("SELECT character FROM locations WHERE user_id=%s", (data.fromUser,), fetch="one")
    character = char_row["character"] if char_row else "🧍"
    msg_id = str(uuid.uuid4())[:8]
    db_execute(
        "INSERT INTO room_messages(id, room_name, from_user, message, character) VALUES(%s,%s,%s,%s,%s)",
        (msg_id, data.roomName, data.fromUser, data.message, character))
    # Limiti aş → eski sil
    db_execute("""
        DELETE FROM room_messages WHERE room_name=%s AND id NOT IN (
            SELECT id FROM room_messages WHERE room_name=%s
            ORDER BY sent_at DESC LIMIT %s)
    """, (data.roomName, data.roomName, MAX_ROOM_MESSAGES))
    # 🔔 FCM — odadaki diğer kullanıcılara bildirim
    _preview = data.message[:60] + ("..." if len(data.message) > 60 else "")
    _send_fcm_to_room(
        room_name    = data.roomName,
        title        = f"👥 {data.roomName} — {data.fromUser}",
        body         = _preview,
        exclude_user = data.fromUser,
        data         = {"type": "room_message", "roomName": data.roomName, "fromUser": data.fromUser})
    return {"message": "✅ Grup mesajı gönderildi"}

@app.get("/get_room_messages/{room_name}")
def get_room_messages(room_name: str, limit: int = 50):
    rows = db_execute("""
        SELECT id, from_user, message, character, sent_at
        FROM room_messages WHERE room_name=%s
        ORDER BY sent_at DESC LIMIT %s
    """, (room_name, limit), fetch="all") or []
    rows.reverse()
    return [{
        "id": r["id"], "from": r["from_user"],
        "message": r["message"], "character": r["character"],
        "timestamp": str(r["sent_at"])[:19],
    } for r in rows]

@app.get("/get_room_messages_since/{room_name}")
def get_room_messages_since(room_name: str, last_id: str = ""):
    if not last_id:
        return get_room_messages(room_name, 50)
    rows = db_execute("""
        SELECT id, from_user, message, character, sent_at
        FROM room_messages
        WHERE room_name=%s AND sent_at > (
            SELECT sent_at FROM room_messages WHERE id=%s
        )
        ORDER BY sent_at
    """, (room_name, last_id), fetch="all") or []
    return [{
        "id": r["id"], "from": r["from_user"],
        "message": r["message"], "character": r["character"],
        "timestamp": str(r["sent_at"])[:19],
    } for r in rows]

# ═══════════════════════════════════════════════════════════════════════════════
# 🎤 WALKİE-TALKİE
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/room_walkie_send")
def room_walkie_send(data: WalkieChunkModel):
    audio = base64.b64decode(data.audioBase64)
    chunk_id = str(uuid.uuid4())[:8]
    db_execute(
        "INSERT INTO walkie_chunks(id,type,room_name,from_user,audio_data) VALUES(%s,'room',%s,%s,%s)",
        (chunk_id, data.roomName, data.fromUser, psycopg2.Binary(audio)))
    # 30'dan fazla chunk varsa eskiyi sil
    db_execute("""
        DELETE FROM walkie_chunks WHERE type='room' AND room_name=%s
        AND id NOT IN (SELECT id FROM walkie_chunks WHERE type='room' AND room_name=%s ORDER BY created_at DESC LIMIT %s)
    """, (data.roomName, data.roomName, MAX_WALKIE_CHUNKS))
    return {"id": chunk_id}

@app.get("/room_walkie_listen/{room_name}")
def room_walkie_listen(room_name: str, user_id: str = "", last_id: str = ""):
    if last_id:
        rows = db_execute("""
            SELECT id, from_user, created_at FROM walkie_chunks
            WHERE type='room' AND room_name=%s AND from_user!=%s
              AND created_at > (SELECT created_at FROM walkie_chunks WHERE id=%s)
            ORDER BY created_at
        """, (room_name, user_id, last_id), fetch="all") or []
    else:
        rows = db_execute("""
            SELECT id, from_user, created_at FROM walkie_chunks
            WHERE type='room' AND room_name=%s AND from_user!=%s
            ORDER BY created_at DESC LIMIT 5
        """, (room_name, user_id), fetch="all") or []
        rows.reverse()
    return [{"id": r["id"], "from": r["from_user"], "timestamp": str(r["created_at"])[:19]} for r in rows]

@app.get("/room_walkie_chunk/{chunk_id}")
def get_walkie_chunk(chunk_id: str, room_name: str = ""):
    from fastapi.responses import Response
    row = db_execute("SELECT audio_data FROM walkie_chunks WHERE id=%s", (chunk_id,), fetch="one")
    if not row: raise HTTPException(404, "Chunk bulunamadı")
    return Response(content=bytes(row["audio_data"]), media_type="audio/aac")

@app.post("/p2p_walkie_send")
def p2p_walkie_send(data: WalkieChunkModel):
    audio = base64.b64decode(data.audioBase64)
    chunk_id = str(uuid.uuid4())[:8]
    db_execute(
        "INSERT INTO walkie_chunks(id,type,from_user,to_user,audio_data) VALUES(%s,'p2p',%s,%s,%s)",
        (chunk_id, data.fromUser, data.toUser, psycopg2.Binary(audio)))
    db_execute("""
        DELETE FROM walkie_chunks WHERE type='p2p' AND from_user=%s AND to_user=%s
        AND id NOT IN (SELECT id FROM walkie_chunks WHERE type='p2p' AND from_user=%s AND to_user=%s
                       ORDER BY created_at DESC LIMIT %s)
    """, (data.fromUser, data.toUser, data.fromUser, data.toUser, MAX_WALKIE_CHUNKS))
    return {"id": chunk_id}

@app.get("/p2p_walkie_listen/{to_user}")
def p2p_walkie_listen(to_user: str, from_user: str, last_id: str = ""):
    if last_id:
        rows = db_execute("""
            SELECT id, from_user, created_at FROM walkie_chunks
            WHERE type='p2p' AND from_user=%s AND to_user=%s
              AND created_at > (SELECT created_at FROM walkie_chunks WHERE id=%s)
            ORDER BY created_at
        """, (from_user, to_user, last_id), fetch="all") or []
    else:
        rows = db_execute("""
            SELECT id, from_user, created_at FROM walkie_chunks
            WHERE type='p2p' AND from_user=%s AND to_user=%s
            ORDER BY created_at DESC LIMIT 5
        """, (from_user, to_user), fetch="all") or []
        rows.reverse()
    return [{"id": r["id"], "from": r["from_user"], "timestamp": str(r["created_at"])[:19]} for r in rows]

@app.get("/p2p_walkie_chunk/{chunk_id}")
def get_p2p_chunk(chunk_id: str, from_user: str = "", to_user: str = ""):
    from fastapi.responses import Response
    row = db_execute("SELECT audio_data FROM walkie_chunks WHERE id=%s AND type='p2p'", (chunk_id,), fetch="one")
    if not row: raise HTTPException(404, "Chunk bulunamadı")
    return Response(content=bytes(row["audio_data"]), media_type="audio/aac")

# ═══════════════════════════════════════════════════════════════════════════════
# 🎵 MÜZİK YAYINI
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/music_start")
def music_start(data: MusicStartModel):
    existing = db_execute(
        "SELECT broadcaster FROM music_streams WHERE room_name=%s AND active=TRUE",
        (data.roomName,), fetch="one")
    if existing and existing["broadcaster"] != data.broadcasterId:
        raise HTTPException(409, f"{existing['broadcaster']} zaten yayın yapıyor!")
    db_execute("""
        INSERT INTO music_streams(room_name, broadcaster, title, active, chunk_index)
        VALUES(%s,%s,%s,TRUE,0)
        ON CONFLICT(room_name) DO UPDATE SET
            broadcaster=%s, title=%s, active=TRUE, chunk_index=0, started_at=NOW()
    """, (data.roomName, data.broadcasterId, data.title, data.broadcasterId, data.title))
    return {"message": "✅ Yayın başladı"}

@app.post("/music_chunk")
def music_chunk_post(data: MusicChunkModel):
    stream = db_execute(
        "SELECT * FROM music_streams WHERE room_name=%s AND active=TRUE", (data.roomName,), fetch="one")
    if not stream: raise HTTPException(404, "Aktif yayın yok")
    if stream["broadcaster"] != data.broadcasterId: raise HTTPException(403, "Sen yayıncı değilsin")
    audio = base64.b64decode(data.audioBase64)
    chunk_id = str(uuid.uuid4())[:8]
    new_idx = stream["chunk_index"]
    db_execute(
        "INSERT INTO music_chunks(id, room_name, broadcaster, chunk_index, audio_data) VALUES(%s,%s,%s,%s,%s)",
        (chunk_id, data.roomName, data.broadcasterId, new_idx, psycopg2.Binary(audio)))
    db_execute(
        "UPDATE music_streams SET chunk_index=chunk_index+1 WHERE room_name=%s",
        (data.roomName,))
    # Eski chunk'ları temizle
    db_execute("""
        DELETE FROM music_chunks WHERE room_name=%s
        AND id NOT IN (SELECT id FROM music_chunks WHERE room_name=%s ORDER BY chunk_index DESC LIMIT %s)
    """, (data.roomName, data.roomName, MAX_MUSIC_CHUNKS))
    return {"id": chunk_id, "index": new_idx}

@app.get("/music_status/{room_name}")
def music_status(room_name: str):
    row = db_execute(
        "SELECT * FROM music_streams WHERE room_name=%s AND active=TRUE", (room_name,), fetch="one")
    if not row: return {"active": False}
    return {
        "active": True, "broadcaster": row["broadcaster"],
        "title": row["title"], "startedAt": str(row["started_at"])[:19],
        "totalChunks": row["chunk_index"],
    }

@app.get("/music_listen/{room_name}")
def music_listen(room_name: str, after_index: int = -1):
    rows = db_execute("""
        SELECT id, chunk_index FROM music_chunks
        WHERE room_name=%s AND chunk_index > %s ORDER BY chunk_index
    """, (room_name, after_index), fetch="all") or []
    return [{"id": r["id"], "index": r["chunk_index"]} for r in rows]

@app.get("/music_chunk_data/{room_name}/{chunk_id}")
def music_chunk_data(room_name: str, chunk_id: str):
    from fastapi.responses import Response
    row = db_execute(
        "SELECT audio_data FROM music_chunks WHERE id=%s AND room_name=%s", (chunk_id, room_name), fetch="one")
    if not row: raise HTTPException(404, "Chunk bulunamadı")
    return Response(content=bytes(row["audio_data"]), media_type="audio/aac")

@app.post("/music_stop")
def music_stop(data: MusicStopModel):
    stream = db_execute(
        "SELECT broadcaster FROM music_streams WHERE room_name=%s", (data.roomName,), fetch="one")
    if not stream: raise HTTPException(404, "Yayın yok")
    if stream["broadcaster"] != data.broadcasterId: raise HTTPException(403, "Yetkisiz")
    db_execute("UPDATE music_streams SET active=FALSE WHERE room_name=%s", (data.roomName,))
    db_execute("DELETE FROM music_chunks WHERE room_name=%s", (data.roomName,))
    return {"message": "⏹ Yayın durduruldu"}

# ═══════════════════════════════════════════════════════════════════════════════
# 👤 KULLANICI ADI DEĞİŞTİRME
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/change_username")
def change_username(data: ChangeUsernameModel):
    if not data.newName.strip(): raise HTTPException(400, "İsim boş olamaz!")
    clash = db_execute("SELECT 1 FROM locations WHERE user_id=%s", (data.newName,), fetch="one")
    if clash and data.newName != data.oldName: raise HTTPException(400, "Bu isim zaten kullanımda!")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE locations SET user_id=%s WHERE user_id=%s", (data.newName, data.oldName))
            cur.execute("UPDATE location_history SET user_id=%s WHERE user_id=%s", (data.newName, data.oldName))
            cur.execute("UPDATE scores SET user_id=%s WHERE user_id=%s", (data.newName, data.oldName))
            cur.execute("UPDATE pins SET creator=%s WHERE creator=%s", (data.newName, data.oldName))
            cur.execute("UPDATE messages SET from_user=%s WHERE from_user=%s", (data.newName, data.oldName))
            cur.execute("UPDATE messages SET to_user=%s WHERE to_user=%s", (data.newName, data.oldName))
            cur.execute("UPDATE room_messages SET from_user=%s WHERE from_user=%s", (data.newName, data.oldName))
            cur.execute("UPDATE room_permissions SET user_id=%s WHERE user_id=%s", (data.newName, data.oldName))
            cur.execute("UPDATE pin_collection_history SET collector=%s WHERE collector=%s", (data.newName, data.oldName))
    return {"message": f"✅ {data.oldName} → {data.newName}"}

# ═══════════════════════════════════════════════════════════════════════════════
# 🚫 BAN SİSTEMİ
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/ban_user/{user_id}")
def ban_user(user_id: str, admin_id: str, device_id: str = "", reason: str = ""):
    if not is_super_admin(admin_id, device_id): raise HTTPException(403, "Sadece süper admin banlayabilir!")
    fp_row = db_execute("SELECT device_id FROM locations WHERE user_id=%s", (user_id,), fetch="one")
    fingerprint = fp_row["device_id"] if fp_row else ""
    db_execute(
        "INSERT INTO bans(user_id, fingerprint, banned_by, reason) VALUES(%s,%s,%s,%s)",
        (user_id, fingerprint, admin_id, reason))
    db_execute("DELETE FROM locations WHERE user_id=%s", (user_id,))
    return {"message": f"🚫 {user_id} banlandı", "fingerprintBanned": bool(fingerprint)}

@app.post("/unban_user/{user_id}")
def unban_user(user_id: str, admin_id: str, device_id: str = ""):
    if not is_super_admin(admin_id, device_id): raise HTTPException(403, "Yetkisiz!")
    db_execute("DELETE FROM bans WHERE user_id=%s", (user_id,))
    return {"message": f"✅ {user_id} banı kaldırıldı"}

@app.get("/get_ban_list")
def get_ban_list(admin_id: str, device_id: str = ""):
    if not is_super_admin(admin_id, device_id): raise HTTPException(403, "Yetkisiz!")
    rows = db_execute("SELECT * FROM bans ORDER BY banned_at DESC LIMIT 50", fetch="all") or []
    return {
        "banned_users": list({r["user_id"] for r in rows if r["user_id"]}),
        "ban_log": [{"userId": r["user_id"], "fingerprint": r["fingerprint"],
                     "bannedBy": r["banned_by"], "reason": r["reason"],
                     "timestamp": str(r["banned_at"])[:19]} for r in rows],
    }

# ═══════════════════════════════════════════════════════════════════════════════
# 🔧 YÖNETİM
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/set_voice_permission_request/{room_name}")
def voice_permission_request(room_name: str, user_id: str):
    # Basit — admin panelde görünmesi için room_messages'a sistem mesajı ekle
    return {"message": "İstek gönderildi"}

@app.delete("/remove_user/{user_id}")
def remove_user(user_id: str):
    db_execute("DELETE FROM locations WHERE user_id=%s", (user_id,))
    return {"message": f"✅ {user_id} silindi"}

@app.delete("/clear")
def clear_all():
    with get_db() as conn:
        with conn.cursor() as cur:
            for t in ["locations","location_history","pins","scores",
                      "messages","room_messages","walkie_chunks",
                      "music_chunks","music_streams","pin_collection_history"]:
                cur.execute(f"DELETE FROM {t}")
    return {"message": "✅ Tüm veriler silindi"}

# ═══════════════════════════════════════════════════════════════════════════════
# 🔔 FCM PUSH BİLDİRİM SİSTEMİ
# ═══════════════════════════════════════════════════════════════════════════════
#
# KURULUM:
# 1. Firebase Console → Proje → Ayarlar → Hizmet Hesabı → JSON indir
# 2. Render Environment → FIREBASE_CREDENTIALS = JSON içeriğini yapıştır
# 3. Ya da FIREBASE_SERVICE_ACCOUNT_PATH = /path/to/credentials.json
#
# FCM v1 API → OAuth2 token ile çalışır (eski server key değil)
#

import json
import threading
try:
    import google.auth
    import google.auth.transport.requests
    from google.oauth2 import service_account
    _FCM_AVAILABLE = True
except ImportError:
    _FCM_AVAILABLE = False

FCM_PROJECT_ID = os.environ.get("FCM_PROJECT_ID", "")
_fcm_credentials = None

def _get_fcm_credentials():
    """Service account credentials — lazy init, thread-safe"""
    global _fcm_credentials
    if _fcm_credentials is not None:
        return _fcm_credentials
    if not _FCM_AVAILABLE or not FCM_PROJECT_ID:
        return None
    try:
        # Önce JSON string dene (Render env var)
        creds_json = os.environ.get("FIREBASE_CREDENTIALS", "")
        if creds_json:
            info = json.loads(creds_json)
        else:
            # Dosya yolu dene
            path = os.environ.get("FIREBASE_SERVICE_ACCOUNT_PATH", "firebase-credentials.json")
            if not os.path.exists(path):
                return None
            with open(path) as f:
                info = json.load(f)
        _fcm_credentials = service_account.Credentials.from_service_account_info(
            info,
            scopes=["https://www.googleapis.com/auth/firebase.messaging"])
        return _fcm_credentials
    except Exception as e:
        print(f"❌ FCM credentials: {e}")
        return None

def _get_access_token() -> str | None:
    """OAuth2 access token al"""
    creds = _get_fcm_credentials()
    if not creds: return None
    try:
        request = google.auth.transport.requests.Request()
        creds.refresh(request)
        return creds.token
    except Exception as e:
        print(f"❌ FCM token: {e}")
        return None

def _send_fcm(token: str, title: str, body: str, data: dict = None):
    """Tek cihaza FCM v1 bildirimi gönder"""
    import urllib.request
    access_token = _get_access_token()
    if not access_token:
        return False
    url = f"https://fcm.googleapis.com/v1/projects/{FCM_PROJECT_ID}/messages:send"
    payload = {
        "message": {
            "token": token,
            "notification": {"title": title, "body": body},
            "android": {
                "priority": "high",
                "notification": {
                    "sound": "default",
                    "channel_id": "konum_alerts",
                    "notification_priority": "PRIORITY_MAX",
                    "visibility": "PUBLIC",
                }
            },
            "apns": {
                "payload": {"aps": {"sound": "default", "badge": 1}},
                "headers": {"apns-priority": "10"}
            },
            "data": {k: str(v) for k, v in (data or {}).items()},
        }
    }
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {access_token}",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"❌ FCM send: {e}")
        return False

def _send_fcm_to_room(room_name: str, title: str, body: str,
                      exclude_user: str = "", data: dict = None):
    """Odadaki tüm online kullanıcılara bildirim gönder (arka planda)"""
    def _worker():
        rows = db_execute(
            "SELECT user_id, fcm_token FROM locations WHERE room_name=%s AND fcm_token IS NOT NULL AND last_seen > NOW()-INTERVAL '10 minutes'",
            (room_name,), fetch="all") or []
        for r in rows:
            if r["user_id"] == exclude_user:
                continue
            _send_fcm(r["fcm_token"], title, body, data)
    threading.Thread(target=_worker, daemon=True).start()

def _send_fcm_to_user(user_id: str, title: str, body: str, data: dict = None):
    """Belirli kullanıcıya bildirim gönder (arka planda)"""
    def _worker():
        row = db_execute(
            "SELECT fcm_token FROM locations WHERE user_id=%s AND fcm_token IS NOT NULL",
            (user_id,), fetch="one")
        if row:
            _send_fcm(row["fcm_token"], title, body, data)
    threading.Thread(target=_worker, daemon=True).start()

# FCM token kayıt endpoint'i
class FCMTokenModel(BaseModel):
    userId: str
    token: str

@app.post("/register_fcm_token")
def register_fcm_token(data: FCMTokenModel):
    """Flutter uygulaması başlayınca FCM token'ı kaydet"""
    db_execute(
        "UPDATE locations SET fcm_token=%s WHERE user_id=%s",
        (data.token, data.userId))
    return {"message": "✅ FCM token kaydedildi"}

# ═══════════════════════════════════════════════════════════════════════════════
# 🆘 SOS & ROTA PAYLAŞIMI
# ═══════════════════════════════════════════════════════════════════════════════

class SOSModel(BaseModel):
    userId: str
    roomName: str
    lat: float
    lng: float
    message: str = ""

class ShareRouteModel(BaseModel):
    roomName: str
    sharedBy: str
    waypoints: List[dict]

# SOS kayıtları (RAM — kritik değil, restart'ta silinebilir)
sos_alerts = []

@app.post("/sos_alert")
def sos_alert(data: SOSModel):
    """SOS uyarısını kaydet ve odadaki herkese FCM gönder"""
    now = get_local_time()
    sos_alerts.append({
        "userId":   data.userId,
        "roomName": data.roomName,
        "lat":      data.lat,
        "lng":      data.lng,
        "time":     now,
    })
    if len(sos_alerts) > 100:
        sos_alerts.pop(0)

    # 🔔 FCM — odadaki herkese acil bildirim
    _send_fcm_to_room(
        room_name    = data.roomName,
        title        = "🆘 ACİL DURUM!",
        body         = f"{data.userId} yardım istiyor! Konumu paylaştı.",
        exclude_user = data.userId,
        data         = {
            "type":     "sos",
            "userId":   data.userId,
            "roomName": data.roomName,
            "lat":      data.lat,
            "lng":      data.lng,
        })

    return {"message": "✅ SOS kaydedildi ve bildirimler gönderildi", "time": now}

@app.get("/get_sos_alerts/{room_name}")
def get_sos_alerts(room_name: str, admin_id: str = "", device_id: str = ""):
    """Süper admin: oda SOS geçmişi"""
    if not is_super_admin(admin_id, device_id):
        raise HTTPException(403, "Yetkisiz!")
    return [s for s in sos_alerts if s["roomName"] == room_name]

# Paylaşılan rotalar (RAM — gruba anlık iletilir)
shared_routes = {}  # roomName → {sharedBy, waypoints, sharedAt}

@app.post("/share_route")
def share_route(data: ShareRouteModel):
    """Grup rotasını odaya paylaş + FCM bildir"""
    shared_routes[data.roomName] = {
        "sharedBy":  data.sharedBy,
        "waypoints": data.waypoints,
        "sharedAt":  get_local_time(),
    }
    # 🔔 FCM — rota paylaşıldı
    _send_fcm_to_room(
        room_name    = data.roomName,
        title        = "🗺️ Yeni Grup Rotası",
        body         = f"{data.sharedBy} grup rotasını paylaştı — {len(data.waypoints)} durak",
        exclude_user = data.sharedBy,
        data         = {"type": "route", "roomName": data.roomName})
    return {"message": "✅ Rota paylaşıldı"}

@app.get("/get_shared_route/{room_name}")
def get_shared_route(room_name: str):
    """Odanın paylaşılan rotasını getir"""
    route = shared_routes.get(room_name)
    if not route:
        return {"active": False}
    return {"active": True, **route}

@app.post("/migrate_add_fcm_token")
def migrate_add_fcm_token(admin_id: str, device_id: str = ""):
    """Mevcut DB'ye fcm_token kolonu ekle (bir kez çalıştır)"""
    if not is_super_admin(admin_id, device_id):
        raise HTTPException(403, "Yetkisiz!")
    try:
        db_execute("ALTER TABLE locations ADD COLUMN IF NOT EXISTS fcm_token TEXT")
        return {"message": "✅ fcm_token kolonu eklendi"}
    except Exception as e:
        return {"message": f"⚠️ {e}"}

# ═══════════════════════════════════════════════════════════════════════════════
# 🚌 TRANSPORT MODU
# ═══════════════════════════════════════════════════════════════════════════════
# Rol sistemi: driver (sürücü) / passenger (yolcu) / manager (yönetici)

class TransportRoleModel(BaseModel):
    roomName: str
    userId: str
    role: str          # "driver" | "passenger" | "manager"
    vehicleName: str = ""  # Araç adı (sürücüler için)

class TransportSessionModel(BaseModel):
    roomName: str
    managerId: str
    title: str = "Sefer"
    vehicleNames: List[str] = []

@app.post("/set_transport_role")
def set_transport_role(data: TransportRoleModel):
    """Kullanıcıya transport rolü ata"""
    valid = {"driver", "passenger", "manager"}
    if data.role not in valid:
        raise HTTPException(400, f"Geçersiz rol. Olabilir: {valid}")
    db_execute("""
        INSERT INTO room_permissions(room_name, user_id, can_collect, can_voice)
        VALUES(%s, %s, FALSE, FALSE)
        ON CONFLICT(room_name, user_id) DO NOTHING
    """, (data.roomName, data.userId))
    # transport_role alanı için JSON olarak saklayalım
    db_execute("""
        UPDATE locations SET
            animation_type = %s
        WHERE user_id = %s
    """, (f"transport_{data.role}_{data.vehicleName}", data.userId))
    return {"message": f"✅ Rol atandı: {data.role}"}

@app.get("/get_transport_status/{room_name}")
def get_transport_status(room_name: str):
    """Odadaki tüm araç/yolcu durumlarını getir"""
    rows = db_execute("""
        SELECT user_id, lat, lng, speed, animation_type, character, last_seen
        FROM locations
        WHERE room_name = %s
          AND animation_type LIKE 'transport_%'
          AND last_seen > NOW() - INTERVAL '5 minutes'
        ORDER BY last_seen DESC
    """, (room_name,), fetch="all") or []

    drivers    = []
    passengers = []
    managers   = []

    for r in rows:
        anim   = r["animation_type"] or ""
        parts  = anim.split("_", 2)  # transport_driver_AraçAdı
        role   = parts[1] if len(parts) > 1 else "passenger"
        vname  = parts[2] if len(parts) > 2 else ""
        entry  = {
            "userId":      r["user_id"],
            "lat":         r["lat"],
            "lng":         r["lng"],
            "speed":       r["speed"],
            "character":   r["character"],
            "vehicleName": vname,
            "lastSeen":    str(r["last_seen"])[:19] if r["last_seen"] else "",
        }
        if role   == "driver":    drivers.append(entry)
        elif role == "manager":   managers.append(entry)
        else:                     passengers.append(entry)

    return {
        "drivers":    drivers,
        "passengers": passengers,
        "managers":   managers,
        "total":      len(rows),
    }

@app.post("/transport_broadcast")
def transport_broadcast(data: RoomMessageModel):
    """Sürücüden yolculara sistem mesajı (geç kalma, durak değişimi vs.)"""
    # Özel sistem mesajı olarak gönder
    char_row = db_execute(
        "SELECT character FROM locations WHERE user_id=%s", (data.fromUser,), fetch="one")
    character = char_row["character"] if char_row else "🚌"
    msg_id = str(uuid.uuid4())[:8]
    system_msg = f"🚌 [{data.fromUser}]: {data.message}"
    db_execute(
        "INSERT INTO room_messages(id, room_name, from_user, message, character) VALUES(%s,%s,%s,%s,%s)",
        (msg_id, data.roomName, data.fromUser, system_msg, character))
    # FCM bildirimi
    _send_fcm_to_room(
        room_name    = data.roomName,
        title        = f"🚌 Sürücü Mesajı — {data.fromUser}",
        body         = data.message,
        exclude_user = data.fromUser,
        data         = {"type": "transport", "fromUser": data.fromUser})
    return {"message": "✅ Yayın yapıldı"}
