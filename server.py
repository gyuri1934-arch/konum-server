import os, uuid, json, pytz, psycopg2, psycopg2.extras
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
from datetime import datetime, timedelta
from math import radians, sin, cos, sqrt, atan2
from contextlib import contextmanager

# ═══════════════════════════════════════════════════════════════════
# ⚙️ CONFIG
# ═══════════════════════════════════════════════════════════════════
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://konum_db_user:kmiKUjdHgVeOmw8LNiXs2i4umi7dHBXH@dpg-d6bempl6ubrc73cicdi0-a.frankfurt-postgres.render.com/konum_db"
)
TZ              = pytz.timezone("Europe/Istanbul")
USER_TIMEOUT    = 300   # saniye
IDLE_THRESHOLD  = 15    # metre
IDLE_MINUTES    = 15    # dakika
SPEED_VEHICLE   = 30    # km/h
SPEED_WALK      = 3
MIN_DIST_VEH    = 50    # metre
MIN_DIST_RUN    = 20
MIN_DIST_WALK   = 10
MIN_DIST_IDLE   = 5
MAX_POINTS      = 5000
PIN_START       = 20    # metre
PIN_END         = 25
MAX_ROOM_MSG    = 200

app = FastAPI(title="Konum API", version="3.1")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# RAM (geçici ses/müzik verileri)
_master_devices       = set()
_master_music_allowed = set()
_walkie_p2p   = {}
_walkie_room  = {}
_music_status = {}
_music_chunks = {}
_shared_routes = {}

# ═══════════════════════════════════════════════════════════════════
# 🗄️ VERİTABANI
# ═══════════════════════════════════════════════════════════════════
@contextmanager
def db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield conn
        conn.commit()
    except:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS locations (
            user_id TEXT PRIMARY KEY, device_id TEXT DEFAULT '',
            device_type TEXT DEFAULT 'phone', lat DOUBLE PRECISION DEFAULT 0,
            lng DOUBLE PRECISION DEFAULT 0, altitude DOUBLE PRECISION DEFAULT 0,
            speed DOUBLE PRECISION DEFAULT 0, animation_type TEXT DEFAULT 'pulse',
            room_name TEXT DEFAULT 'Genel', character TEXT DEFAULT '🧍',
            last_seen TEXT, idle_status TEXT DEFAULT 'online',
            idle_minutes INT DEFAULT 0, idle_start TEXT)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS location_history (
            id SERIAL PRIMARY KEY, user_id TEXT NOT NULL,
            lat DOUBLE PRECISION, lng DOUBLE PRECISION,
            timestamp TEXT, speed DOUBLE PRECISION DEFAULT 0)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS device_registry (
            device_id TEXT PRIMARY KEY, user_id TEXT NOT NULL)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS rooms (
            room_name TEXT PRIMARY KEY, password TEXT, created_by TEXT,
            created_by_device TEXT DEFAULT '', created_at TEXT,
            collectors JSONB DEFAULT '[]', music_allowed JSONB DEFAULT '[]')""")
        cur.execute("""CREATE TABLE IF NOT EXISTS scores (
            room_name TEXT, user_id TEXT, score INT DEFAULT 0,
            PRIMARY KEY (room_name, user_id))""")
        cur.execute("""CREATE TABLE IF NOT EXISTS pin_collection_history (
            id SERIAL PRIMARY KEY, room_name TEXT, user_id TEXT,
            timestamp TEXT, created_at TEXT, creator TEXT,
            lat DOUBLE PRECISION, lng DOUBLE PRECISION)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS pins (
            id TEXT PRIMARY KEY, room_name TEXT, creator TEXT,
            lat DOUBLE PRECISION, lng DOUBLE PRECISION, created_at TEXT,
            collector_id TEXT, collection_start TEXT, collection_time INT DEFAULT 0)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY, from_user TEXT, to_user TEXT,
            conv_key TEXT, message TEXT, timestamp TEXT, is_read BOOLEAN DEFAULT FALSE)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS room_messages (
            id TEXT PRIMARY KEY, room_name TEXT, from_user TEXT,
            message TEXT, timestamp TEXT, character TEXT DEFAULT '🧍')""")
        cur.execute("""CREATE TABLE IF NOT EXISTS visibility_settings (
            user_id TEXT PRIMARY KEY, mode TEXT DEFAULT 'all',
            allowed JSONB DEFAULT '[]')""")
        # Migration: eksik kolonlar
        safe = [
            "ALTER TABLE location_history ADD COLUMN IF NOT EXISTS timestamp TEXT",
            "ALTER TABLE location_history ADD COLUMN IF NOT EXISTS speed DOUBLE PRECISION DEFAULT 0",
            "ALTER TABLE locations ADD COLUMN IF NOT EXISTS idle_start TEXT",
            "ALTER TABLE locations ADD COLUMN IF NOT EXISTS idle_minutes INT DEFAULT 0",
            "ALTER TABLE locations ADD COLUMN IF NOT EXISTS idle_status TEXT DEFAULT 'online'",
            "ALTER TABLE locations ADD COLUMN IF NOT EXISTS character TEXT DEFAULT '🧍'",
            "ALTER TABLE locations ADD COLUMN IF NOT EXISTS animation_type TEXT DEFAULT 'pulse'",
            "ALTER TABLE locations ADD COLUMN IF NOT EXISTS device_id TEXT DEFAULT ''",
            "ALTER TABLE locations ADD COLUMN IF NOT EXISTS room_name TEXT DEFAULT 'Genel'",
            "ALTER TABLE locations ADD COLUMN IF NOT EXISTS lat DOUBLE PRECISION DEFAULT 0",
            "ALTER TABLE locations ADD COLUMN IF NOT EXISTS lng DOUBLE PRECISION DEFAULT 0",
            "ALTER TABLE locations ADD COLUMN IF NOT EXISTS altitude DOUBLE PRECISION DEFAULT 0",
            "ALTER TABLE locations ADD COLUMN IF NOT EXISTS speed DOUBLE PRECISION DEFAULT 0",
            "ALTER TABLE locations ADD COLUMN IF NOT EXISTS last_seen TEXT",
            "ALTER TABLE locations ADD COLUMN IF NOT EXISTS device_type TEXT DEFAULT 'phone'",
            "ALTER TABLE rooms ADD COLUMN IF NOT EXISTS created_by_device TEXT DEFAULT ''",
            "ALTER TABLE rooms ADD COLUMN IF NOT EXISTS collectors JSONB DEFAULT '[]'",
            "ALTER TABLE rooms ADD COLUMN IF NOT EXISTS music_allowed JSONB DEFAULT '[]'",
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS conv_key TEXT",
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS is_read BOOLEAN DEFAULT FALSE",
            "ALTER TABLE room_messages ADD COLUMN IF NOT EXISTS character TEXT DEFAULT '🧍'",
        ]
        for sql in safe:
            try: cur.execute(sql)
            except Exception as e: print(f"Migration skip: {e}")
        # conv_key doldur
        try:
            cur.execute("""UPDATE messages SET conv_key=(
                SELECT string_agg(u,'_' ORDER BY u) FROM unnest(ARRAY[from_user,to_user]) u)
                WHERE conv_key IS NULL OR conv_key=''""")
        except: pass
        # Index'ler
        for s in ["CREATE INDEX IF NOT EXISTS idx_lh_user ON location_history(user_id)",
                  "CREATE INDEX IF NOT EXISTS idx_msg_key ON messages(conv_key)",
                  "CREATE INDEX IF NOT EXISTS idx_rm_room ON room_messages(room_name)"]:
            try: cur.execute(s)
            except: pass
    print("✅ DB hazır")

@app.on_event("startup")
def startup(): init_db()

# ═══════════════════════════════════════════════════════════════════
# 🛠️ YARDIMCILAR
# ═══════════════════════════════════════════════════════════════════
def now_str(): return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")

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

def clist(val):
    if isinstance(val, list): return val
    try: return json.loads(val or "[]")
    except: return []

def ckey(u1, u2): return "_".join(sorted([u1, u2]))

# ═══════════════════════════════════════════════════════════════════
# 📋 MODELLER
# ═══════════════════════════════════════════════════════════════════
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

class WalkieSendModel(BaseModel):
    fromUser: str; toUser: str = ""; roomName: str = ""; audioBase64: str

class MusicStartModel(BaseModel):
    roomName: str; broadcaster: str; title: str = ""

class MusicChunkModel(BaseModel):
    roomName: str; broadcaster: str; chunkIndex: int; audioBase64: str

class MusicStopModel(BaseModel):
    roomName: str; broadcaster: str

class SharedRouteModel(BaseModel):
    roomName: str; userId: str; points: list

# ═══════════════════════════════════════════════════════════════════
# 🏠 ANASAYFA
# ═══════════════════════════════════════════════════════════════════
@app.get("/")
def root():
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as c FROM locations WHERE last_seen IS NOT NULL")
        total = cur.fetchone()["c"]
    return {"status": "✅ Çalışıyor", "time": now_str(), "total_users": total}

@app.get("/health")
def health(): return {"status": "ok", "time": now_str()}

@app.get("/debug_locations")
def debug_locations():
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id, room_name, last_seen, lat, lng FROM locations ORDER BY last_seen DESC")
        rows = cur.fetchall()
    now = datetime.now(TZ)
    result = []
    for r in rows:
        try:
            dt = TZ.localize(datetime.strptime(r["last_seen"], "%Y-%m-%d %H:%M:%S"))
            age = int((now - dt).total_seconds())
            online = age < USER_TIMEOUT
        except:
            age = -1; online = False
        result.append({"userId": r["user_id"], "room": r["room_name"],
                        "lastSeen": r["last_seen"], "ageSec": age, "online": online,
                        "lat": r["lat"], "lng": r["lng"]})
    return result

# ═══════════════════════════════════════════════════════════════════
# 📍 KONUM — GÜNCELLEME
# ═══════════════════════════════════════════════════════════════════
@app.post("/update_location")
def update_location(data: LocationModel):
    uid, now = data.userId, now_str()

    try:
        with db() as conn:
            cur = conn.cursor()

            # Device registry
            if data.deviceId:
                cur.execute("SELECT user_id FROM device_registry WHERE device_id=%s", (data.deviceId,))
                prev = cur.fetchone()
                if prev and prev["user_id"] != uid:
                    old_uid = prev["user_id"]
                    for tbl, col in [("location_history","user_id"),("locations","user_id"),
                                     ("rooms","created_by"),("pin_collection_history","user_id"),
                                     ("room_messages","from_user"),("visibility_settings","user_id")]:
                        try: cur.execute(f"UPDATE {tbl} SET {col}=%s WHERE {col}=%s", (uid, old_uid))
                        except: pass
                    try:
                        cur.execute("UPDATE scores SET user_id=%s WHERE user_id=%s", (uid, old_uid))
                    except: pass
                cur.execute("""INSERT INTO device_registry (device_id,user_id) VALUES (%s,%s)
                    ON CONFLICT (device_id) DO UPDATE SET user_id=EXCLUDED.user_id""",
                    (data.deviceId, uid))

            # Idle hesapla
            idle_status, idle_minutes, idle_start = "online", 0, None
            cur.execute("SELECT lat,lng,idle_start FROM locations WHERE user_id=%s", (uid,))
            prev_loc = cur.fetchone()
            if prev_loc:
                dist = haversine(prev_loc["lat"] or 0, prev_loc["lng"] or 0, data.lat, data.lng)
                if dist < IDLE_THRESHOLD:
                    idle_start = prev_loc["idle_start"] or now
                    try:
                        s = TZ.localize(datetime.strptime(idle_start, "%Y-%m-%d %H:%M:%S"))
                        mins = (datetime.now(TZ) - s).total_seconds() / 60
                        if mins >= IDLE_MINUTES:
                            idle_status = "idle"; idle_minutes = int(mins)
                    except:
                        idle_start = now

            # Konumu kaydet
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
    except Exception as e:
        print(f"❌ update_location hatası: {e}")
        return {"status": "error", "error": str(e)}

    # Rota geçmişi (ayrı)
    try:
        with db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT lat,lng FROM location_history WHERE user_id=%s ORDER BY id DESC LIMIT 1", (uid,))
            last = cur.fetchone()
            add = False
            if not last:
                add = True
            else:
                d = haversine(last["lat"], last["lng"], data.lat, data.lng)
                s = data.speed
                if   s >= SPEED_VEHICLE: add = d >= MIN_DIST_VEH
                elif s >= SPEED_WALK:    add = d >= MIN_DIST_RUN
                elif s >= 0.5:           add = d >= MIN_DIST_WALK
                else:                    add = d >= MIN_DIST_IDLE
            if add:
                cur.execute("INSERT INTO location_history (user_id,lat,lng,timestamp,speed) VALUES (%s,%s,%s,%s,%s)",
                            (uid, data.lat, data.lng, now, data.speed))
    except Exception as e:
        print(f"⚠️ Rota hatası: {e}")

    # Pin toplama (ayrı)
    try:
        with db() as conn:
            cur = conn.cursor()
            can = False
            if data.roomName == "Genel":
                can = True
            else:
                cur.execute("SELECT collectors FROM rooms WHERE room_name=%s", (data.roomName,))
                rr = cur.fetchone()
                if rr: can = uid in clist(rr["collectors"])
            if can:
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
                        cur.execute("""INSERT INTO scores (room_name,user_id,score) VALUES (%s,%s,1)
                            ON CONFLICT (room_name,user_id) DO UPDATE SET score=scores.score+1""",
                            (data.roomName, uid))
                        cur.execute("""INSERT INTO pin_collection_history
                            (room_name,user_id,timestamp,created_at,creator,lat,lng)
                            VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                            (data.roomName, uid, now, pin["created_at"] or "", pin["creator"], pin["lat"], pin["lng"]))
                        cur.execute("DELETE FROM pins WHERE id=%s", (pin["id"],))
    except Exception as e:
        print(f"⚠️ Pin hatası: {e}")

    return {"status": "ok", "time": now}

# ═══════════════════════════════════════════════════════════════════
# 📍 KONUM — LİSTE
# ═══════════════════════════════════════════════════════════════════
@app.get("/get_locations/{room_name}")
def get_locations(room_name: str, viewer_id: str = "", viewer_device_id: str = ""):
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
        if viewer_device_id and loc["device_id"] == viewer_device_id: continue
        if not is_online(loc["last_seen"]): continue
        if vis.get(uid) == "hidden": continue
        result.append({
            "userId": uid, "deviceId": loc["device_id"],
            "lat": loc["lat"], "lng": loc["lng"],
            "deviceType": loc["device_type"], "altitude": loc["altitude"] or 0,
            "speed": loc["speed"] or 0, "animationType": loc["animation_type"] or "pulse",
            "roomName": loc["room_name"], "idleStatus": loc["idle_status"] or "online",
            "idleMinutes": loc["idle_minutes"] or 0, "character": loc["character"] or "🧍",
        })
    return result

# ═══════════════════════════════════════════════════════════════════
# 📍 ROTA GEÇMİŞİ
# ═══════════════════════════════════════════════════════════════════
@app.get("/get_location_history/{user_id}")
def get_location_history(user_id: str, period: str = "all", device_id: str = ""):
    with db() as conn:
        cur = conn.cursor()
        if device_id:
            cur.execute("SELECT user_id FROM device_registry WHERE device_id=%s", (device_id,))
            row = cur.fetchone()
            if row: user_id = row["user_id"]
        if period == "all":
            cur.execute("SELECT lat,lng,timestamp,speed FROM location_history WHERE user_id=%s ORDER BY id", (user_id,))
        else:
            delta = {"day":1,"week":7,"month":30,"year":365}.get(period,30)
            cutoff = (datetime.now(TZ) - timedelta(days=delta)).strftime("%Y-%m-%d %H:%M:%S")
            cur.execute("SELECT lat,lng,timestamp,speed FROM location_history WHERE user_id=%s AND timestamp>%s ORDER BY id",
                        (user_id, cutoff))
        return cur.fetchall()

@app.delete("/clear_history/{user_id}")
def clear_history(user_id: str):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM location_history WHERE user_id=%s", (user_id,))
    return {"message": "✅ Geçmiş temizlendi"}

# ═══════════════════════════════════════════════════════════════════
# 🚪 ODA YÖNETİMİ
# ═══════════════════════════════════════════════════════════════════
@app.post("/create_room")
def create_room(data: RoomModel):
    if len(data.password) < 3:
        raise HTTPException(400, "Şifre en az 3 karakter!")
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM rooms WHERE room_name=%s", (data.roomName,))
        if cur.fetchone(): raise HTTPException(400, "Bu oda adı zaten var!")
        cur.execute("""INSERT INTO rooms (room_name,password,created_by,created_by_device,created_at)
            VALUES (%s,%s,%s,%s,%s)""",
            (data.roomName, data.password, data.createdBy, data.createdByDevice, now_str()))
    return {"message": f"✅ {data.roomName} oluşturuldu"}

@app.post("/join_room")
def join_room(data: JoinRoomModel):
    if data.roomName == "Genel": return {"message": "Genel'e katıldınız"}
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT password FROM rooms WHERE room_name=%s", (data.roomName,))
        row = cur.fetchone()
        if not row: raise HTTPException(404, "Oda bulunamadı!")
        if row["password"] != data.password: raise HTTPException(401, "Yanlış şifre!")
    return {"message": f"✅ {data.roomName}'a katıldınız"}

@app.get("/get_rooms")
def get_rooms(user_id: str = ""):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM rooms")
        rooms = cur.fetchall()
        cur.execute("SELECT room_name, COUNT(*) as c FROM locations GROUP BY room_name")
        counts = {r["room_name"]: r["c"] for r in cur.fetchall()}
    result = [{"name":"Genel","hasPassword":False,"userCount":counts.get("Genel",0),"isAdmin":False,"password":None}]
    for r in rooms:
        is_admin = r["created_by"] == user_id
        result.append({"name":r["room_name"],"hasPassword":True,
                        "userCount":counts.get(r["room_name"],0),
                        "createdBy":r["created_by"],"isAdmin":is_admin,
                        "password":r["password"] if is_admin else None})
    return result

@app.delete("/delete_room/{room_name}")
def delete_room(room_name: str, admin_id: str):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT created_by FROM rooms WHERE room_name=%s", (room_name,))
        row = cur.fetchone()
        if not row: raise HTTPException(404, "Oda bulunamadı!")
        if row["created_by"] != admin_id: raise HTTPException(403, "Sadece admin silebilir!")
        cur.execute("DELETE FROM rooms WHERE room_name=%s", (room_name,))
        cur.execute("UPDATE locations SET room_name='Genel' WHERE room_name=%s", (room_name,))
        cur.execute("DELETE FROM pins WHERE room_name=%s", (room_name,))
        cur.execute("DELETE FROM room_messages WHERE room_name=%s", (room_name,))
    return {"message": f"✅ {room_name} silindi"}

@app.get("/get_room_permissions/{room_name}")
def get_room_permissions(room_name: str, user_id: str = ""):
    if room_name == "Genel": return {"admin": None, "collectors": [], "voiceAllowed": []}
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT created_by,collectors FROM rooms WHERE room_name=%s", (room_name,))
        row = cur.fetchone()
        if not row: return {"admin": None, "collectors": [], "voiceAllowed": []}
    return {"admin": row["created_by"], "collectors": clist(row["collectors"]), "voiceAllowed": []}

@app.post("/set_collector_permission/{room_name}/{target_user}")
def set_collector_permission(room_name: str, target_user: str, admin_id: str, enabled: bool):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT created_by, collectors FROM rooms WHERE room_name=%s", (room_name,))
        row = cur.fetchone()
        if not row: raise HTTPException(404, "Oda bulunamadı!")
        if row["created_by"] != admin_id: raise HTTPException(403, "Sadece admin yetkilendirebilir!")
        lst = clist(row["collectors"])
        if enabled and target_user not in lst: lst.append(target_user)
        elif not enabled and target_user in lst: lst.remove(target_user)
        cur.execute("UPDATE rooms SET collectors=%s WHERE room_name=%s", (json.dumps(lst), room_name))
    return {"message": "✅ Yetki güncellendi"}

@app.post("/set_voice_permission/{room_name}/{target_user}")
def set_voice_permission(room_name: str, target_user: str, admin_id: str, enabled: bool):
    return {"message": "✅ (Ses yetkisi bu sürümde oda bazlı değil)"}

@app.get("/get_room_password/{room_name}")
def get_room_password(room_name: str, admin_id: str):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT password,created_by FROM rooms WHERE room_name=%s", (room_name,))
        row = cur.fetchone()
        if not row: raise HTTPException(404, "Oda bulunamadı!")
        if row["created_by"] != admin_id: raise HTTPException(403, "Sadece admin görebilir!")
    return {"password": row["password"]}

# ═══════════════════════════════════════════════════════════════════
# 📍 PIN SİSTEMİ
# ═══════════════════════════════════════════════════════════════════
@app.post("/create_pin")
def create_pin(data: PinModel):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pins WHERE creator=%s AND room_name=%s", (data.creator, data.roomName))
        if cur.fetchone(): raise HTTPException(400, "Zaten bir pininiz var!")
        pin_id = str(uuid.uuid4())[:8]
        cur.execute("""INSERT INTO pins (id,room_name,creator,lat,lng,created_at)
            VALUES (%s,%s,%s,%s,%s,%s)""",
            (pin_id, data.roomName, data.creator, data.lat, data.lng, now_str()))
    return {"message": "✅ Pin yerleştirildi", "pinId": pin_id}

@app.get("/get_pins/{room_name}")
def get_pins(room_name: str):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM pins WHERE room_name=%s", (room_name,))
        return cur.fetchall()

@app.delete("/remove_pin/{pin_id}")
def remove_pin(pin_id: str, user_id: str):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT creator FROM pins WHERE id=%s", (pin_id,))
        row = cur.fetchone()
        if not row: raise HTTPException(404, "Pin bulunamadı!")
        if row["creator"] != user_id: raise HTTPException(403, "Sadece pin sahibi kaldırabilir!")
        cur.execute("DELETE FROM pins WHERE id=%s", (pin_id,))
    return {"message": "✅ Pin kaldırıldı"}

@app.get("/get_scores/{room_name}")
def get_scores(room_name: str):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id, score FROM scores WHERE room_name=%s ORDER BY score DESC", (room_name,))
        return [{"userId": r["user_id"], "score": r["score"]} for r in cur.fetchall()]

@app.get("/get_collection_history/{room_name}/{user_id}")
def get_collection_history(room_name: str, user_id: str):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM pin_collection_history WHERE room_name=%s AND user_id=%s", (room_name, user_id))
        return cur.fetchall()

# ═══════════════════════════════════════════════════════════════════
# 💬 MESAJLAŞMA
# ═══════════════════════════════════════════════════════════════════
@app.post("/send_message")
def send_message(data: MessageModel):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""INSERT INTO messages (from_user,to_user,conv_key,message,timestamp)
            VALUES (%s,%s,%s,%s,%s)""",
            (data.fromUser, data.toUser, ckey(data.fromUser,data.toUser), data.message, now_str()))
    return {"message": "✅ Gönderildi"}

@app.get("/get_conversation/{user1}/{user2}")
def get_conversation(user1: str, user2: str):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM messages WHERE conv_key=%s ORDER BY id", (ckey(user1,user2),))
        return cur.fetchall()

@app.post("/mark_as_read/{user_id}/{other_user}")
def mark_as_read(user_id: str, other_user: str):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE messages SET is_read=TRUE WHERE conv_key=%s AND to_user=%s",
                    (ckey(user_id,other_user), user_id))
    return {"message": "✅ Okundu"}

@app.get("/get_unread_count/{user_id}")
def get_unread_count(user_id: str):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""SELECT from_user, COUNT(*) as c FROM messages
            WHERE to_user=%s AND is_read=FALSE GROUP BY from_user""", (user_id,))
        return {r["from_user"]: r["c"] for r in cur.fetchall()}

# ═══════════════════════════════════════════════════════════════════
# 👥 GRUP MESAJ
# ═══════════════════════════════════════════════════════════════════
@app.post("/send_room_message")
def send_room_message(data: RoomMessageModel):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT character FROM locations WHERE user_id=%s", (data.fromUser,))
        row = cur.fetchone()
        char = row["character"] if row else "🧍"
        cur.execute("""INSERT INTO room_messages (id,room_name,from_user,message,timestamp,character)
            VALUES (%s,%s,%s,%s,%s,%s)""",
            (str(uuid.uuid4())[:8], data.roomName, data.fromUser, data.message, now_str(), char))
        cur.execute("""DELETE FROM room_messages WHERE room_name=%s AND id NOT IN (
            SELECT id FROM room_messages WHERE room_name=%s ORDER BY timestamp DESC LIMIT %s)""",
            (data.roomName, data.roomName, MAX_ROOM_MSG))
    return {"message": "✅ Gönderildi"}

@app.get("/get_room_messages/{room_name}")
def get_room_messages(room_name: str, limit: int = 50):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""SELECT * FROM (SELECT * FROM room_messages WHERE room_name=%s
            ORDER BY timestamp DESC LIMIT %s) sub ORDER BY timestamp ASC""",
            (room_name, limit))
        return cur.fetchall()

@app.get("/get_room_messages_since/{room_name}")
def get_room_messages_since(room_name: str, last_id: str = ""):
    with db() as conn:
        cur = conn.cursor()
        if not last_id:
            cur.execute("""SELECT * FROM room_messages WHERE room_name=%s
                ORDER BY timestamp DESC LIMIT 50""", (room_name,))
            rows = list(reversed(cur.fetchall()))
            return rows
        cur.execute("SELECT timestamp FROM room_messages WHERE id=%s", (last_id,))
        row = cur.fetchone()
        if not row:
            cur.execute("SELECT * FROM room_messages WHERE room_name=%s ORDER BY timestamp DESC LIMIT 50", (room_name,))
            return list(reversed(cur.fetchall()))
        cur.execute("SELECT * FROM room_messages WHERE room_name=%s AND timestamp>%s ORDER BY timestamp ASC",
                    (room_name, row["timestamp"]))
        return cur.fetchall()

# ═══════════════════════════════════════════════════════════════════
# 👁️ GÖRÜNÜRLİK
# ═══════════════════════════════════════════════════════════════════
@app.post("/set_visibility")
def set_visibility(data: VisibilityModel):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""INSERT INTO visibility_settings (user_id,mode,allowed) VALUES (%s,%s,%s)
            ON CONFLICT (user_id) DO UPDATE SET mode=EXCLUDED.mode, allowed=EXCLUDED.allowed""",
            (data.userId, data.mode, json.dumps(data.allowed)))
    return {"message": "✅ Güncellendi"}

# ═══════════════════════════════════════════════════════════════════
# 👤 KULLANICI ADI DEĞİŞTİR
# ═══════════════════════════════════════════════════════════════════
@app.post("/change_username")
def change_username(data: ChangeUsernameModel):
    old, new = data.oldName, data.newName.strip()
    if not new: raise HTTPException(400, "İsim boş olamaz!")
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM locations WHERE user_id=%s", (new,))
        if cur.fetchone() and new != old: raise HTTPException(400, "Bu isim kullanımda!")
        cur.execute("UPDATE device_registry SET user_id=%s WHERE user_id=%s", (new, old))
        cur.execute("UPDATE locations SET user_id=%s WHERE user_id=%s", (new, old))
        cur.execute("UPDATE location_history SET user_id=%s WHERE user_id=%s", (new, old))
        cur.execute("UPDATE rooms SET created_by=%s WHERE created_by=%s", (new, old))
        cur.execute("UPDATE scores SET user_id=%s WHERE user_id=%s", (new, old))
        cur.execute("UPDATE pin_collection_history SET user_id=%s WHERE user_id=%s", (new, old))
        cur.execute("UPDATE room_messages SET from_user=%s WHERE from_user=%s", (new, old))
        cur.execute("UPDATE visibility_settings SET user_id=%s WHERE user_id=%s", (new, old))
        cur.execute("SELECT id,from_user,to_user FROM messages WHERE from_user=%s OR to_user=%s", (old,old))
        for msg in cur.fetchall():
            nf = new if msg["from_user"]==old else msg["from_user"]
            nt = new if msg["to_user"]==old else msg["to_user"]
            cur.execute("UPDATE messages SET from_user=%s,to_user=%s,conv_key=%s WHERE id=%s",
                        (nf, nt, ckey(nf,nt), msg["id"]))
    return {"message": f"✅ {old} → {new}"}

# ═══════════════════════════════════════════════════════════════════
# 🔐 YETKİ İSTEK SİSTEMİ
# ═══════════════════════════════════════════════════════════════════
_perm_requests = {}  # RAM

class PermRequestModel(BaseModel):
    roomName: str; requesterUserId: str
    permissionType: str = ""; type: str = ""
    message: str = ""; note: str = ""

@app.post("/request_permission")
def request_permission(data: PermRequestModel):
    req_id = str(uuid.uuid4())[:8]
    ptype = data.permissionType or data.type
    if data.roomName not in _perm_requests: _perm_requests[data.roomName] = []
    _perm_requests[data.roomName].append({
        "id":req_id,"requester":data.requesterUserId,
        "type":ptype,"note":data.message or data.note,"time":now_str()})
    return {"message":"✅ İstek gönderildi","requestId":req_id}

@app.get("/get_permission_requests/{room_name}")
def get_permission_requests(room_name: str, admin_id: str = ""):
    return _perm_requests.get(room_name, [])

@app.post("/respond_permission/{request_id}")
def respond_permission(request_id: str, approved: bool, admin_id: str = ""):
    for key, reqs in _perm_requests.items():
        for req in reqs:
            if req["id"] == request_id:
                reqs.remove(req)
                return {"message": "✅ Yanıt verildi", "approved": approved}
    raise HTTPException(404, "İstek bulunamadı")

@app.get("/check_permission_status/{request_id}")
def check_permission_status(request_id: str):
    for reqs in _perm_requests.values():
        for req in reqs:
            if req["id"] == request_id:
                return {"status": "pending"}
    return {"status": "approved"}

# ═══════════════════════════════════════════════════════════════════
# 🎵 MÜZİK YETKİSİ
# ═══════════════════════════════════════════════════════════════════
@app.get("/get_music_permission/{room_name}/{user_id}")
def get_music_permission(room_name: str, user_id: str, device_id: str = ""):
    if device_id in _master_devices: return {"canBroadcast": True, "reason": "master"}
    with db() as conn:
        cur = conn.cursor()
        if device_id:
            cur.execute("SELECT device_id FROM locations WHERE user_id=%s", (user_id,))
            row = cur.fetchone()
            if row and row["device_id"] in _master_devices:
                return {"canBroadcast": True, "reason": "master"}
        if room_name == "Genel":
            return {"canBroadcast": user_id in _master_music_allowed, "reason": "master_allowed"}
        cur.execute("SELECT created_by, music_allowed FROM rooms WHERE room_name=%s", (room_name,))
        row = cur.fetchone()
        if not row: return {"canBroadcast": False, "reason": "no_room"}
        if row["created_by"] == user_id: return {"canBroadcast": True, "reason": "admin"}
        allowed = clist(row["music_allowed"])
    return {"canBroadcast": user_id in allowed, "reason": "allowed"}

@app.post("/set_music_permission/{room_name}/{target_user}")
def set_music_permission(room_name: str, target_user: str, admin_id: str, enabled: bool):
    if room_name == "Genel":
        if admin_id not in _master_devices:
            with db() as conn:
                cur = conn.cursor()
                cur.execute("SELECT device_id FROM locations WHERE user_id=%s", (admin_id,))
                row = cur.fetchone()
                if not row or row["device_id"] not in _master_devices:
                    raise HTTPException(403, "Sadece master admin yetkilendirebilir!")
        if enabled: _master_music_allowed.add(target_user)
        else: _master_music_allowed.discard(target_user)
        return {"message": "✅ Müzik yetkisi güncellendi"}
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT created_by, music_allowed FROM rooms WHERE room_name=%s", (room_name,))
        row = cur.fetchone()
        if not row: raise HTTPException(404, "Oda bulunamadı!")
        if row["created_by"] != admin_id: raise HTTPException(403, "Sadece admin yetkilendirebilir!")
        lst = clist(row["music_allowed"])
        if enabled and target_user not in lst: lst.append(target_user)
        elif not enabled and target_user in lst: lst.remove(target_user)
        cur.execute("UPDATE rooms SET music_allowed=%s WHERE room_name=%s", (json.dumps(lst), room_name))
    return {"message": "✅ Müzik yetkisi güncellendi"}

# ═══════════════════════════════════════════════════════════════════
# 🎙️ WALKİE-TALKİE
# ═══════════════════════════════════════════════════════════════════
@app.post("/walkie_send")
def walkie_send(data: WalkieSendModel):
    key = ckey(data.fromUser, data.toUser)
    _walkie_p2p[key] = {"id":str(uuid.uuid4())[:8],"from":data.fromUser,"audio":data.audioBase64,"timestamp":now_str()}
    return {"message":"✅ Gönderildi"}

@app.get("/walkie_listen/{user_id}/{target}")
def walkie_listen(user_id: str, target: str, last_id: str = ""):
    msg = _walkie_p2p.get(ckey(user_id, target))
    if not msg or msg["from"] == user_id or msg["id"] == last_id: return []
    return [msg]

@app.post("/room_walkie_send")
def room_walkie_send(data: WalkieSendModel):
    room = data.roomName or "Genel"
    if room not in _walkie_room: _walkie_room[room] = []
    _walkie_room[room].append({"id":str(uuid.uuid4())[:8],"from":data.fromUser,"audio":data.audioBase64,"timestamp":now_str()})
    _walkie_room[room] = _walkie_room[room][-10:]
    return {"message":"✅ Gönderildi"}

@app.get("/room_walkie_listen/{room_name}")
def room_walkie_listen(room_name: str, user_id: str = "", last_id: str = ""):
    msgs = _walkie_room.get(room_name, [])
    if not last_id:
        for msg in reversed(msgs):
            if msg["from"] != user_id: return [msg]
        return []
    result = []
    found = False
    for msg in msgs:
        if found and msg["from"] != user_id: result.append(msg)
        if msg["id"] == last_id: found = True
    return result

# ═══════════════════════════════════════════════════════════════════
# 🎵 MÜZİK YAYINI
# ═══════════════════════════════════════════════════════════════════
@app.post("/music_start")
def music_start(data: MusicStartModel):
    _music_status[data.roomName] = {"broadcaster":data.broadcaster,"title":data.title,"active":True}
    _music_chunks[data.roomName] = []
    return {"message":"✅ Başladı"}

@app.post("/music_chunk")
def music_chunk(data: MusicChunkModel):
    room = data.roomName
    if room not in _music_chunks: _music_chunks[room] = []
    cid = str(uuid.uuid4())[:8]
    _music_chunks[room].append({"id":cid,"index":data.chunkIndex,"from":data.broadcaster,"audio":data.audioBase64,"timestamp":now_str()})
    _music_chunks[room] = _music_chunks[room][-20:]
    return {"message":"✅ Chunk","id":cid}

@app.get("/music_chunk_data/{room_name}/{chunk_id}")
def music_chunk_data(room_name: str, chunk_id: str):
    for c in _music_chunks.get(room_name, []):
        if c["id"] == chunk_id: return c
    raise HTTPException(404, "Chunk bulunamadı")

@app.post("/music_stop")
def music_stop(data: MusicStopModel):
    if data.roomName in _music_status: _music_status[data.roomName]["active"] = False
    _music_chunks.pop(data.roomName, None)
    return {"message":"✅ Durduruldu"}

@app.get("/music_status/{room_name}")
def music_status(room_name: str):
    s = _music_status.get(room_name, {"active":False,"broadcaster":None,"title":""})
    return {"active":s.get("active",False),"broadcaster":s.get("broadcaster"),"title":s.get("title",""),"chunks":_music_chunks.get(room_name,[])}

# ═══════════════════════════════════════════════════════════════════
# 🗺️ PAYLAŞILAN ROTA
# ═══════════════════════════════════════════════════════════════════
@app.post("/share_route")
def share_route(data: SharedRouteModel):
    _shared_routes[data.roomName] = {"userId":data.userId,"points":data.points,"timestamp":now_str()}
    return {"message":"✅ Rota paylaşıldı"}

@app.get("/get_shared_route/{room_name}")
def get_shared_route(room_name: str):
    r = _shared_routes.get(room_name)
    if not r: return {"active":False,"points":[],"userId":None}
    return {"active":True,**r}

@app.delete("/clear_shared_route/{room_name}")
def clear_shared_route(room_name: str):
    _shared_routes.pop(room_name, None)
    return {"message":"✅ Temizlendi"}

# ═══════════════════════════════════════════════════════════════════
# 👑 MASTER ADMİN
# ═══════════════════════════════════════════════════════════════════
MASTER_PASSWORD = "Yuri2024!"

def is_master(device_id: str): return device_id in _master_devices

@app.get("/master_status")
def master_status(device_id: str = ""):
    return {"isMaster": is_master(device_id)}

@app.get("/master_login")
def master_login(device_id: str = "", password: str = ""):
    if password != MASTER_PASSWORD: raise HTTPException(401, "Yanlış şifre!")
    if device_id: _master_devices.add(device_id)
    return {"message":"✅ Master giriş","isMaster":True}

@app.post("/master_logout")
def master_logout(device_id: str = ""):
    _master_devices.discard(device_id)
    return {"message":"✅ Çıkış"}

@app.get("/master_get_all_users")
def master_get_all_users(device_id: str = ""):
    if not is_master(device_id): raise HTTPException(403, "Yetkisiz!")
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id,device_id,device_type,room_name,last_seen,idle_status,speed FROM locations")
        return [{"userId":r["user_id"],"deviceId":r["device_id"],"deviceType":r["device_type"],
                 "roomName":r["room_name"],"lastSeen":r["last_seen"],"idleStatus":r["idle_status"],
                 "speed":r["speed"],"online":is_online(r["last_seen"])} for r in cur.fetchall()]

@app.get("/master_get_all_rooms")
def master_get_all_rooms(device_id: str = ""):
    if not is_master(device_id): raise HTTPException(403, "Yetkisiz!")
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT room_name,created_by,password FROM rooms")
        rooms = cur.fetchall()
        cur.execute("SELECT room_name,COUNT(*) as c FROM locations GROUP BY room_name")
        counts = {r["room_name"]:r["c"] for r in cur.fetchall()}
    result = [{"name":"Genel","createdBy":"system","userCount":counts.get("Genel",0),"password":None}]
    for r in rooms:
        result.append({"name":r["room_name"],"createdBy":r["created_by"],
                        "userCount":counts.get(r["room_name"],0),"password":r["password"]})
    return result

@app.delete("/master_kick_user/{user_id}")
def master_kick_user(user_id: str, device_id: str = ""):
    if not is_master(device_id): raise HTTPException(403, "Yetkisiz!")
    with db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM locations WHERE user_id=%s", (user_id,))
    return {"message":f"✅ {user_id} atıldı"}

@app.delete("/master_delete_room/{room_name}")
def master_delete_room(room_name: str, device_id: str = ""):
    if not is_master(device_id): raise HTTPException(403, "Yetkisiz!")
    with db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM rooms WHERE room_name=%s", (room_name,))
        cur.execute("UPDATE locations SET room_name='Genel' WHERE room_name=%s", (room_name,))
        cur.execute("DELETE FROM pins WHERE room_name=%s", (room_name,))
        cur.execute("DELETE FROM room_messages WHERE room_name=%s", (room_name,))
    return {"message":f"✅ {room_name} silindi"}

@app.delete("/master_clear_all")
def master_clear_all(device_id: str = ""):
    if not is_master(device_id): raise HTTPException(403, "Yetkisiz!")
    with db() as conn:
        cur = conn.cursor()
        for t in ["locations","location_history","pins","scores","pin_collection_history","messages","room_messages"]:
            cur.execute(f"DELETE FROM {t}")
    return {"message":"✅ Tüm veriler silindi"}

@app.get("/get_offline_users")
def get_offline_users(admin_id: str = "", device_id: str = ""):
    if not is_master(device_id): return []
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id,room_name,last_seen FROM locations")
        return [{"userId":r["user_id"],"roomName":r["room_name"],"lastSeen":r["last_seen"]}
                for r in cur.fetchall() if not is_online(r["last_seen"])]

# ═══════════════════════════════════════════════════════════════════
# 🗑️ YÖNETİM
# ═══════════════════════════════════════════════════════════════════
@app.delete("/remove_user/{user_id}")
def remove_user(user_id: str):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM locations WHERE user_id=%s", (user_id,))
    return {"message":f"✅ {user_id} silindi"}

@app.delete("/clear")
def clear_all():
    with db() as conn:
        cur = conn.cursor()
        for t in ["locations","location_history","pins","scores","pin_collection_history","messages","room_messages"]:
            cur.execute(f"DELETE FROM {t}")
    return {"message":"✅ Tüm veriler silindi"}
