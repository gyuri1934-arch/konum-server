# ═══════════════════════════════════════════════════════════════════════════════
#                         KONUM TAKİP SERVER
# ═══════════════════════════════════════════════════════════════════════════════
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
from math import radians, sin, cos, sqrt, atan2
import pytz
import uuid
import json
import os
import asyncio

# Türkçe karakter ve emoji desteği için ensure_ascii=False
class UnicodeJSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"

    def render(self, content) -> bytes:
        return json.dumps(content, ensure_ascii=False,
                          allow_nan=False, separators=(",", ":")).encode("utf-8")

app = FastAPI(title="Konum Takip API", version="3.0", default_response_class=UnicodeJSONResponse)

@app.exception_handler(StarletteHTTPException)
async def unicode_http_exception_handler(request: Request, exc: StarletteHTTPException):
    return UnicodeJSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail})

@app.exception_handler(RequestValidationError)
async def unicode_validation_exception_handler(request: Request, exc: RequestValidationError):
    return UnicodeJSONResponse(
        status_code=422,
        content={"detail": str(exc)})

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════════════════════════════════════
# 💾 DISK KALICILIĞI — Fly.io volume /data'ya mount edilmişse persist eder
# ═══════════════════════════════════════════════════════════════════════════════

_DATA_DIR           = "/data" if os.path.isdir("/data") else os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE        = os.path.join(_DATA_DIR, "location_history.json")
ROUTE_LIBRARY_FILE  = os.path.join(_DATA_DIR, "route_library.json")
ROUTE_WAYPOINTS_FILE= os.path.join(_DATA_DIR, "route_waypoints.json")
_save_pending = False

def _flush_history():
    """location_history'yi diske yaz."""
    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(location_history, f, ensure_ascii=False)
    except Exception as e:
        print(f"❌ History kayıt hatası: {e}")

async def _periodic_save():
    """Her 60 saniyede bir bekleyen kayıt varsa diske yaz."""
    global _save_pending
    while True:
        await asyncio.sleep(60)
        if _save_pending:
            _flush_history()
            _save_pending = False

def _flush_route_library():
    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
        with open(ROUTE_LIBRARY_FILE, 'w', encoding='utf-8') as f:
            json.dump(route_library, f, ensure_ascii=False)
    except Exception as e:
        print(f"❌ Rota kütüphanesi kayıt hatası: {e}")

def _flush_route_waypoints():
    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
        with open(ROUTE_WAYPOINTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(room_route_waypoints, f, ensure_ascii=False)
    except Exception as e:
        print(f"❌ POI noktaları kayıt hatası: {e}")

@app.on_event("startup")
async def startup_event():
    global location_history, route_library, room_route_waypoints
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                location_history.update(loaded)
            total_pts = sum(len(v) for v in location_history.values())
            print(f"✅ Geçmiş yüklendi: {len(location_history)} kullanıcı, {total_pts} nokta")
        else:
            print("ℹ️ Geçmiş dosyası yok — temiz başlangıç")
    except Exception as e:
        print(f"❌ Geçmiş yükleme hatası: {e}")
    try:
        if os.path.exists(ROUTE_LIBRARY_FILE):
            with open(ROUTE_LIBRARY_FILE, 'r', encoding='utf-8') as f:
                route_library.update(json.load(f))
            total_routes = sum(len(v) for v in route_library.values())
            print(f"✅ Rota kütüphanesi yüklendi: {total_routes} rota")
    except Exception as e:
        print(f"❌ Rota kütüphanesi yükleme hatası: {e}")
    try:
        if os.path.exists(ROUTE_WAYPOINTS_FILE):
            with open(ROUTE_WAYPOINTS_FILE, 'r', encoding='utf-8') as f:
                room_route_waypoints.update(json.load(f))
            total_pois = sum(len(v) for v in room_route_waypoints.values())
            print(f"✅ POI noktaları yüklendi: {total_pois} nokta")
    except Exception as e:
        print(f"❌ POI noktaları yükleme hatası: {e}")
    asyncio.create_task(_periodic_save())

@app.on_event("shutdown")
async def shutdown_event():
    print("💾 Kapatılıyor — veriler kaydediliyor...")
    _flush_history()
    _flush_route_library()
    _flush_route_waypoints()

# ═══════════════════════════════════════════════════════════════════════════════
# 🗄️ VERİ SAKLAMASI (RAM)
# ═══════════════════════════════════════════════════════════════════════════════

locations = {}
location_history = {}
rooms = {}
scores = {}
pin_collection_history = {}
pins = {}
messages = {}
room_messages = {}
visibility_settings = {}
fcm_tokens = {}

# ─── Walkie-talkie (RAM kuyruk) ───────────────────────────────────────────────
walkie_queue = {}
room_walkie_queue = {}

# ─── Sesli mesajlar ───────────────────────────────────────────────────────────
voice_messages = {}
room_voice_messages = {}

# ─── Yetki istekleri ──────────────────────────────────────────────────────────
permission_requests = {}

# ─── SOS uyarıları ────────────────────────────────────────────────────────────
sos_alerts = {}

# ─── Müzik yayını ─────────────────────────────────────────────────────────────
music_broadcasts = {}

# ─── Geofence bölgeleri ───────────────────────────────────────────────────────
room_geofences = {}
user_geofences: dict = {}
geofence_entries = {}

# ─── Kullanıcı yönetimi ───────────────────────────────────────────────────────
kicked_users  = {}
banned_users  = {}
banned_devices = {}
muted_users   = {}

# ─── Paylaşılan rotalar ───────────────────────────────────────────────────────
shared_routes = {}

# ─── Transport modu rolleri ───────────────────────────────────────────────────
transport_roles: dict = {}    # roomName → {userId → {role, vehicleName, joinedAt}}
transport_broadcasts: dict = {}  # roomName → {id, fromUser, vehicleName, message, timestamp}
transport_stops: dict = {}     # roomName → {stopId → {id,name,lat,lng,radius,addedBy,addedByRole,createdAt}}
transport_arrivals: dict = {}  # roomName → [{id,stopId,stopName,userId,character,arrivalTime}]

# ─── Rota kütüphanesi (kullanıcılar arası paylaşım) ──────────────────────────
route_library: dict = {}  # roomName → [{id, name, creator, waypoints, distKm, durMin, createdAt}]

# ─── Oda POI noktaları (mola/kamp/vb.) ───────────────────────────────────────
room_route_waypoints: dict = {}  # roomName → [{id, icon, name, lat, lng, radius, color, cap, geofenceActive, desc, createdBy}]

# ═══════════════════════════════════════════════════════════════════════════════
# 🔐 SÜPER ADMİN
# ═══════════════════════════════════════════════════════════════════════════════

SUPER_ADMIN_DEVICE_IDS: set = {}

SUPER_ADMIN_CREDENTIALS: dict = {
    "admin": "1234",
}

_super_admin_sessions: dict = {}

def is_super_admin(user_id: str, device_id: str = "", token: str = "") -> bool:
    if token and token in _super_admin_sessions:
        sess = _super_admin_sessions[token]
        if datetime.now(DEFAULT_TIMEZONE) < sess["expiresAt"]:
            return True
        else:
            _super_admin_sessions.pop(token, None)
    if device_id and device_id in SUPER_ADMIN_DEVICE_IDS:
        return True
    loc = locations.get(user_id, {})
    if loc.get("deviceId", "") in SUPER_ADMIN_DEVICE_IDS:
        return True
    return False

# ═══════════════════════════════════════════════════════════════════════════════
# ⚙️ AYARLAR
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_TIMEZONE   = pytz.timezone('Europe/Istanbul')
USER_TIMEOUT       = 120
IDLE_THRESHOLD     = 15
IDLE_TIME_MINUTES  = 15
SPEED_VEHICLE      = 30
SPEED_RUN          = 15
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
MAX_WALKIE_QUEUE   = 20
MAX_VOICE_MESSAGES = 500

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

def is_user_online(last_seen_str):
    try:
        last_seen = datetime.strptime(last_seen_str, "%Y-%m-%d %H:%M:%S")
        last_seen = DEFAULT_TIMEZONE.localize(last_seen)
        now = datetime.now(DEFAULT_TIMEZONE)
        return (now - last_seen).total_seconds() < USER_TIMEOUT
    except:
        return False

def cleanup_old_routes():
    cutoff = datetime.now(DEFAULT_TIMEZONE) - timedelta(days=MAX_HISTORY_DAYS)
    for uid in list(location_history.keys()):
        history = location_history[uid]
        history[:] = [
            p for p in history
            if datetime.strptime(p["timestamp"], "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=DEFAULT_TIMEZONE) > cutoff
        ]
        if len(history) > MAX_POINTS_PER_USER:
            location_history[uid] = history[-MAX_POINTS_PER_USER:]

def get_conv_key(user1, user2):
    return "_".join(sorted([user1, user2]))

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
    permMsg: str = "odadakiler"
    permLocationHist: str = "yonetici"

class RoomModel(BaseModel):
    roomName: str
    password: str
    createdBy: str

class JoinRoomModel(BaseModel):
    roomName: str
    password: str = ""
    adminId:  str = ""
    token:    str = ""
    deviceId: str = ""

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

class WalkieSendModel(BaseModel):
    fromUser: str
    toUser: str
    audioBase64: str

class RoomWalkieSendModel(BaseModel):
    roomName: str
    fromUser: str
    audioBase64: str

class VoiceMessageModel(BaseModel):
    fromUser: str
    toUser: str
    audioBase64: str
    durationSeconds: float = 0

class RoomVoiceMessageModel(BaseModel):
    roomName: str
    fromUser: str
    audioBase64: str
    durationSeconds: float = 0

class FcmTokenModel(BaseModel):
    userId: str
    token: str

class SosModel(BaseModel):
    userId: str
    roomName: str
    lat: float
    lng: float
    message: str = "SOS!"

class MusicStartModel(BaseModel):
    roomName: str
    broadcasterId: str
    title: str = "Müzik Yayını"

class MusicChunkModel(BaseModel):
    roomName: str
    broadcasterId: str
    audioBase64: str
    index: int = 0

class MusicStopModel(BaseModel):
    roomName: str
    broadcasterId: str

class PermissionRequestModel(BaseModel):
    roomName: str
    requesterUserId: str
    permissionType: str
    message: str = ""

class PermissionRespondModel(BaseModel):
    requestId: str
    adminUserId: str
    approved: bool

class GeofenceSaveModel(BaseModel):
    roomName: str
    adminId: str
    geofences: list

class GeofenceEntryModel(BaseModel):
    roomName: str
    userId: str
    geofenceId: str
    inside: bool

class GeofenceRenameModel(BaseModel):
    roomName: str
    adminId: str
    geofenceId: str
    newName: str

class ShareRouteModel(BaseModel):
    roomName: str
    sharedBy: str
    waypoints: list

class RouteLibraryModel(BaseModel):
    roomName: str
    name: str
    creator: str
    waypoints: list
    distKm: Optional[float] = None
    durMin: Optional[int] = None

# ═══════════════════════════════════════════════════════════════════════════════
# 🏠 ANA SAYFA
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/")
def root():
    online_count = sum(1 for u in locations.values()
                      if is_user_online(u.get("lastSeen", "")))
    total_pts = sum(len(v) for v in location_history.values())
    return {
        "status": "✅ Server çalışıyor",
        "time": get_local_time(),
        "online_users": online_count,
        "total_rooms": len(rooms),
        "total_pins": len(pins),
        "history_users": len(location_history),
        "history_points": total_pts,
        "data_dir": _DATA_DIR,
    }

@app.get("/health")
def health():
    return {"status": "ok", "time": get_local_time()}

# ═══════════════════════════════════════════════════════════════════════════════
# 🚪 ODA YÖNETİMİ
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/create_room")
def create_room(data: RoomModel):
    if data.roomName in rooms:
        raise HTTPException(status_code=400, detail="Bu oda adı zaten mevcut!")
    if len(data.password) < 3:
        raise HTTPException(status_code=400, detail="Şifre en az 3 karakter olmalı!")
    rooms[data.roomName] = {
        "name": data.roomName,
        "password": data.password,
        "createdBy": data.createdBy,
        "createdAt": get_local_time(),
        "collectors": [],
        "voiceAllowed": [],
    }
    return {"message": f"✅ {data.roomName} odası oluşturuldu"}

@app.post("/join_room")
def join_room(data: JoinRoomModel):
    if data.roomName == "Genel":
        return {"message": "Genel odaya katıldınız"}
    if data.roomName not in rooms:
        raise HTTPException(status_code=404, detail="Oda bulunamadı!")
    if is_super_admin(data.adminId, data.deviceId, data.token):
        return {"message": f"✅ {data.roomName} odasına katıldınız (admin)"}
    if rooms[data.roomName]["password"] != data.password:
        raise HTTPException(status_code=401, detail="Yanlış Şifre!")
    return {"message": f"✅ {data.roomName} odasına katıldınız"}

@app.get("/get_rooms")
def get_rooms(user_id: str = ""):
    result = [{
        "name": "Genel",
        "hasPassword": False,
        "userCount": sum(1 for u in locations.values()
                       if u.get("roomName") == "Genel"
                       and is_user_online(u.get("lastSeen", ""))),
        "createdBy": "system",
        "isAdmin": False,
        "password": None,
    }]
    for room_name, room in rooms.items():
        is_admin = room["createdBy"] == user_id
        result.append({
            "name": room_name,
            "hasPassword": True,
            "userCount": sum(1 for u in locations.values()
                           if u.get("roomName") == room_name
                           and is_user_online(u.get("lastSeen", ""))),
            "createdBy": room["createdBy"],
            "isAdmin": is_admin,
            "password": room["password"] if is_admin else None,
        })
    return result

@app.delete("/delete_room/{room_name}")
def delete_room(room_name: str, admin_id: str):
    if room_name not in rooms:
        raise HTTPException(status_code=404, detail="Oda bulunamadı!")
    if rooms[room_name]["createdBy"] != admin_id:
        raise HTTPException(status_code=403, detail="Sadece admin silebilir!")
    del rooms[room_name]
    for uid in locations:
        if locations[uid].get("roomName") == room_name:
            locations[uid]["roomName"] = "Genel"
    for pin_id in list(pins.keys()):
        if pins[pin_id].get("roomName") == room_name:
            del pins[pin_id]
    for key in list(scores.keys()):
        if key.startswith(f"{room_name}_"):
            del scores[key]
    if room_name in room_messages:
        del room_messages[room_name]
    if room_name in room_walkie_queue:
        del room_walkie_queue[room_name]
    return {"message": f"✅ {room_name} odası silindi"}

@app.get("/get_room_password/{room_name}")
def get_room_password(room_name: str, admin_id: str):
    if room_name not in rooms:
        raise HTTPException(status_code=404, detail="Oda bulunamadı!")
    if rooms[room_name]["createdBy"] != admin_id:
        raise HTTPException(status_code=403, detail="Sadece admin görebilir!")
    return {"password": rooms[room_name]["password"]}

@app.post("/change_room_password/{room_name}")
def change_room_password(room_name: str, admin_id: str, new_password: str):
    if room_name not in rooms:
        raise HTTPException(status_code=404, detail="Oda bulunamadı!")
    if rooms[room_name]["createdBy"] != admin_id:
        raise HTTPException(status_code=403, detail="Sadece admin değiştirebilir!")
    if len(new_password) < 3:
        raise HTTPException(status_code=400, detail="Şifre en az 3 karakter!")
    rooms[room_name]["password"] = new_password
    return {"message": "✅ Şifre değiştirildi"}

# ═══════════════════════════════════════════════════════════════════════════════
# 🔑 YETKİ SİSTEMİ
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/get_room_permissions/{room_name}")
def get_room_permissions(room_name: str):
    if room_name == "Genel":
        return {"admin": None, "collectors": [], "voiceAllowed": []}
    if room_name not in rooms:
        return {"admin": None, "collectors": [], "voiceAllowed": []}
    return {
        "admin":        rooms[room_name]["createdBy"],
        "collectors":   rooms[room_name].get("collectors", []),
        "voiceAllowed": rooms[room_name].get("voiceAllowed", []),
        "mutedUsers":   list(muted_users.keys()),
    }

@app.post("/set_collector_permission/{room_name}/{target_user}")
def set_collector_permission(room_name: str, target_user: str, admin_id: str, enabled: bool):
    if room_name not in rooms:
        raise HTTPException(status_code=404, detail="Oda bulunamadı!")
    if rooms[room_name]["createdBy"] != admin_id:
        raise HTTPException(status_code=403, detail="Sadece admin yetkilendirebilir!")
    collectors = rooms[room_name].get("collectors", [])
    if enabled and target_user not in collectors:
        collectors.append(target_user)
    elif not enabled and target_user in collectors:
        collectors.remove(target_user)
    rooms[room_name]["collectors"] = collectors
    return {"message": "✅ Yetki güncellendi", "collectors": collectors}

@app.post("/set_voice_permission/{room_name}/{target_user}")
def set_voice_permission(room_name: str, target_user: str, admin_id: str, enabled: bool):
    if room_name not in rooms:
        raise HTTPException(status_code=404, detail="Oda bulunamadı!")
    if rooms[room_name]["createdBy"] != admin_id:
        raise HTTPException(status_code=403, detail="Sadece admin yetkilendirebilir!")
    voice_allowed = rooms[room_name].get("voiceAllowed", [])
    if enabled and target_user not in voice_allowed:
        voice_allowed.append(target_user)
    elif not enabled and target_user in voice_allowed:
        voice_allowed.remove(target_user)
    rooms[room_name]["voiceAllowed"] = voice_allowed
    return {"message": "✅ Ses yetkisi güncellendi", "voiceAllowed": voice_allowed}

@app.post("/request_permission")
def request_permission(data: PermissionRequestModel):
    if data.roomName not in rooms:
        raise HTTPException(status_code=404, detail="Oda bulunamadı!")
    req_id = str(uuid.uuid4())[:8]
    permission_requests[req_id] = {
        "requestId": req_id,
        "roomName": data.roomName,
        "requesterUserId": data.requesterUserId,
        "permissionType": data.permissionType,
        "message": data.message,
        "status": "pending",
        "timestamp": get_local_time(),
    }
    return {"requestId": req_id, "message": "✅ İstek gönderildi"}

@app.post("/respond_permission")
def respond_permission(data: PermissionRespondModel):
    if data.requestId not in permission_requests:
        raise HTTPException(status_code=404, detail="İstek bulunamadı!")
    req = permission_requests[data.requestId]
    room_name = req["roomName"]
    if room_name not in rooms:
        raise HTTPException(status_code=404, detail="Oda bulunamadı!")
    if rooms[room_name]["createdBy"] != data.adminUserId:
        raise HTTPException(status_code=403, detail="Sadece admin yanıtlayabilir!")
    req["status"] = "approved" if data.approved else "rejected"
    if data.approved:
        ptype = req["permissionType"]
        uid = req["requesterUserId"]
        if ptype == "pin":
            collectors = rooms[room_name].get("collectors", [])
            if uid not in collectors:
                collectors.append(uid)
            rooms[room_name]["collectors"] = collectors
        elif ptype == "voice":
            voice_allowed = rooms[room_name].get("voiceAllowed", [])
            if uid not in voice_allowed:
                voice_allowed.append(uid)
            rooms[room_name]["voiceAllowed"] = voice_allowed
    return {"message": "✅ Yanıt kaydedildi", "approved": data.approved}

@app.get("/get_pending_requests/{user_id}")
def get_pending_requests(user_id: str):
    result = []
    for req in permission_requests.values():
        room_name = req["roomName"]
        is_admin = room_name in rooms and rooms[room_name]["createdBy"] == user_id
        is_own = req["requesterUserId"] == user_id
        if is_admin and req["status"] == "pending":
            result.append(req)
        elif is_own:
            result.append(req)
    return result

@app.get("/get_request_result/{request_id}/{user_id}")
def get_request_result(request_id: str, user_id: str):
    if request_id not in permission_requests:
        raise HTTPException(status_code=404, detail="İstek bulunamadı!")
    req = permission_requests[request_id]
    if req["requesterUserId"] != user_id:
        raise HTTPException(status_code=403, detail="Bu istek size ait değil!")
    return {
        "requestId": request_id,
        "status": req["status"],
        "permissionType": req["permissionType"],
        "roomName": req["roomName"],
    }

# ═══════════════════════════════════════════════════════════════════════════════
# 👁️ GÖRÜNÜRLÜK
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/set_visibility")
def set_visibility(data: VisibilityModel):
    visibility_settings[data.userId] = {"mode": data.mode, "allowed": data.allowed}
    return {"message": "✅ Görünürlük güncellendi"}

# ═══════════════════════════════════════════════════════════════════════════════
# 📍 KONUM
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/update_location")
def update_location(data: LocationModel):
    global _save_pending
    uid = data.userId
    now = get_local_time()

    if uid in banned_users or (data.deviceId and data.deviceId in banned_devices):
        data.roomName = "Genel"

    idle_status = "online"
    idle_minutes = 0
    if uid in locations:
        old = locations[uid]
        dist = haversine(old["lat"], old["lng"], data.lat, data.lng)
        if dist < IDLE_THRESHOLD:
            idle_start = old.get("idleStart")
            if idle_start is None:
                idle_start = now
            else:
                try:
                    start_dt = datetime.strptime(idle_start, "%Y-%m-%d %H:%M:%S")
                    start_dt = DEFAULT_TIMEZONE.localize(start_dt)
                    now_dt = datetime.now(DEFAULT_TIMEZONE)
                    minutes = (now_dt - start_dt).total_seconds() / 60
                    if minutes >= IDLE_TIME_MINUTES:
                        idle_status = "idle"
                        idle_minutes = int(minutes)
                except:
                    idle_start = now
        else:
            idle_start = None
    else:
        idle_start = None

    should_add = False
    if uid not in location_history:
        location_history[uid] = []
        should_add = True
    else:
        history = location_history[uid]
        if len(history) == 0:
            should_add = True
        else:
            last = history[-1]
            dist = haversine(last["lat"], last["lng"], data.lat, data.lng)
            speed = data.speed
            if speed >= SPEED_VEHICLE:
                should_add = dist >= MIN_DIST_VEHICLE
            elif speed >= SPEED_WALK:
                should_add = dist >= MIN_DIST_RUN
            elif speed >= 0.5:
                should_add = dist >= MIN_DIST_WALK
            else:
                should_add = dist >= MIN_DIST_IDLE

    if should_add:
        location_history[uid].append({
            "lat": data.lat, "lng": data.lng,
            "timestamp": now, "speed": data.speed,
        })
        cleanup_old_routes()
        _save_pending = True   # ← diske yaz işaretlendi

    if uid in locations:
        room = data.roomName
        can_collect = False
        if room in rooms:
            can_collect = uid in rooms[room].get("collectors", [])
        if can_collect:
            for pin_id, pin in list(pins.items()):
                if pin.get("roomName") != room or pin.get("creator") == uid:
                    continue
                pin_dist = haversine(data.lat, data.lng, pin["lat"], pin["lng"])
                if pin_dist <= PIN_COLLECT_START:
                    if pin.get("collectorId") is None:
                        pins[pin_id]["collectorId"] = uid
                        pins[pin_id]["collectionStart"] = now
                        pins[pin_id]["collectionTime"] = 0
                    elif pin.get("collectorId") == uid:
                        try:
                            start = datetime.strptime(pin["collectionStart"], "%Y-%m-%d %H:%M:%S")
                            start = DEFAULT_TIMEZONE.localize(start)
                            elapsed = int((datetime.now(DEFAULT_TIMEZONE) - start).total_seconds())
                            pins[pin_id]["collectionTime"] = elapsed
                        except:
                            pass
                elif pin_dist > PIN_COLLECT_END and pin.get("collectorId") == uid:
                    score_key = f"{room}_{uid}"
                    scores[score_key] = scores.get(score_key, 0) + 1
                    hkey = f"{room}_{uid}"
                    if hkey not in pin_collection_history:
                        pin_collection_history[hkey] = []
                    pin_collection_history[hkey].append({
                        "timestamp": now,
                        "createdAt": pin.get("createdAt", ""),
                        "creator": pin.get("creator", ""),
                        "lat": pin["lat"], "lng": pin["lng"],
                    })
                    del pins[pin_id]

    locations[uid] = {
        "userId": uid, "deviceId": data.deviceId, "deviceType": data.deviceType,
        "lat": data.lat, "lng": data.lng, "altitude": data.altitude,
        "speed": data.speed, "animationType": data.animationType,
        "roomName": data.roomName, "character": data.character,
        "permMsg": data.permMsg, "permLocationHist": data.permLocationHist,
        "lastSeen": now, "idleStatus": idle_status,
        "idleMinutes": idle_minutes, "idleStart": idle_start,
    }
    return {"status": "ok", "time": now}

@app.get("/get_locations/{room_name}")
def get_locations(room_name: str, viewer_id: str = "", viewer_device_id: str = ""):
    result = []
    viewer_is_banned = viewer_id in banned_users or (
        viewer_device_id and viewer_device_id in banned_devices
    )
    for uid, data in locations.items():
        if uid == viewer_id:
            continue
        if not is_user_online(data.get("lastSeen", "")):
            continue
        if data.get("roomName") != room_name:
            continue
        uid_is_banned = uid in banned_users
        if viewer_is_banned and not uid_is_banned:
            continue
        if not viewer_is_banned and uid_is_banned:
            continue
        vis = visibility_settings.get(uid, {"mode": "all"})
        if vis["mode"] == "hidden":
            continue
        if vis["mode"] == "room":
            viewer_room = locations.get(viewer_id, {}).get("roomName", "Genel")
            if viewer_room != data.get("roomName"):
                continue
        user_room = data.get("roomName", "Genel")
        room_data = rooms.get(user_room, {})
        is_creator   = bool(room_data.get("createdBy")) and room_data.get("createdBy") == uid
        is_super_now = any(
            s["userId"] == uid and datetime.now(DEFAULT_TIMEZONE) < s["expiresAt"]
            for s in _super_admin_sessions.values()
        )
        is_room_admin = is_creator or is_super_now
        result.append({
            "userId": uid, "deviceId": data.get("deviceId", ""),
            "lat": data["lat"], "lng": data["lng"],
            "deviceType": data.get("deviceType", "phone"),
            "altitude": data.get("altitude", 0), "speed": data.get("speed", 0),
            "animationType": data.get("animationType", "pulse"),
            "roomName": data.get("roomName", "Genel"),
            "idleStatus": data.get("idleStatus", "online"),
            "idleMinutes": data.get("idleMinutes", 0),
            "character": data.get("character", "🧍"),
            "isHidden": False,
            "isRoomAdmin": is_room_admin,
            "isSuperAdmin": is_super_now,
            "permMsg": data.get("permMsg", "odadakiler"),
            "permLocationHist": data.get("permLocationHist", "yonetici"),
            "transportRole": transport_roles.get(data.get("roomName",""), {}).get(uid, {}).get("role", ""),
        })
    return result

@app.get("/get_offline_users")
def get_offline_users(admin_id: str = "", device_id: str = "", token: str = ""):
    if not is_super_admin(admin_id, device_id, token):
        raise HTTPException(status_code=403, detail="Yetkisiz!")
    result = []
    for uid, data in locations.items():
        if not is_user_online(data.get("lastSeen", "")):
            result.append({
                "userId": uid, "lastSeen": data.get("lastSeen", ""),
                "roomName": data.get("roomName", "Genel"),
                "deviceType": data.get("deviceType", "phone"),
            })
    return result

@app.get("/get_location_history/{user_id}")
def get_location_history(user_id: str, period: str = "all",
                          requester_id: str = "", device_id: str = ""):
    # Yetki kontrolü
    if requester_id and requester_id != user_id:
        admin_rooms = {name for name, room in rooms.items() if room.get("createdBy") == requester_id}
        target_room = locations.get(user_id, {}).get("roomName", "")
        if target_room not in admin_rooms and not is_super_admin(requester_id, device_id):
            raise HTTPException(status_code=403, detail="Bu kullanıcının geçmişini görme yetkiniz yok")

    history = location_history.get(user_id, [])
    if period == "all":
        return history

    now = datetime.now(DEFAULT_TIMEZONE)
    cutoffs = {
        "day":   timedelta(days=1),
        "week":  timedelta(weeks=1),
        "month": timedelta(days=30),
        "year":  timedelta(days=365),
    }
    cutoff = now - cutoffs.get(period, timedelta(days=1))
    return [
        p for p in history
        if datetime.strptime(p["timestamp"], "%Y-%m-%d %H:%M:%S")
           .replace(tzinfo=DEFAULT_TIMEZONE) > cutoff
    ]

@app.delete("/clear_history/{user_id}")
def clear_history(user_id: str):
    global _save_pending
    if user_id in location_history:
        location_history[user_id] = []
    _save_pending = True
    return {"message": "✅ Geçmiş temizlendi"}

# ═══════════════════════════════════════════════════════════════════════════════
# 📌 PIN SİSTEMİ
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/create_pin")
def create_pin(data: PinModel):
    for pin in pins.values():
        if pin["creator"] == data.creator and pin["roomName"] == data.roomName:
            raise HTTPException(status_code=400, detail="Zaten bir pininiz var! Önce kaldırın.")
    pin_id = str(uuid.uuid4())[:8]
    pins[pin_id] = {
        "id": pin_id, "roomName": data.roomName, "creator": data.creator,
        "lat": data.lat, "lng": data.lng, "createdAt": get_local_time(),
        "collectorId": None, "collectionStart": None, "collectionTime": 0,
    }
    return {"message": "✅ Pin yerleştirildi", "pinId": pin_id}

@app.get("/get_pins/{room_name}")
def get_pins(room_name: str):
    return [p for p in pins.values() if p.get("roomName") == room_name]

@app.delete("/remove_pin/{pin_id}")
def remove_pin(pin_id: str, user_id: str):
    if pin_id not in pins:
        raise HTTPException(status_code=404, detail="Pin bulunamadı!")
    if pins[pin_id]["creator"] != user_id:
        raise HTTPException(status_code=403, detail="Sadece pin sahibi kaldırabilir!")
    del pins[pin_id]
    return {"message": "✅ Pin kaldırıldı"}

@app.get("/get_scores/{room_name}")
def get_scores(room_name: str):
    result = [{"userId": key[len(f"{room_name}_"):], "score": score}
              for key, score in scores.items() if key.startswith(f"{room_name}_")]
    result.sort(key=lambda x: x["score"], reverse=True)
    return result

@app.get("/get_collection_history/{room_name}/{user_id}")
def get_collection_history(room_name: str, user_id: str):
    return pin_collection_history.get(f"{room_name}_{user_id}", [])

# ═══════════════════════════════════════════════════════════════════════════════
# 💬 1-1 MESAJLAŞMA
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/send_message")
def send_message(data: MessageModel):
    if data.fromUser in muted_users:
        raise HTTPException(403, "🔇 Mesaj gönderme yetkiniz kaldırılmıştır")
    key = get_conv_key(data.fromUser, data.toUser)
    if key not in messages:
        messages[key] = []
    messages[key].append({
        "id": str(uuid.uuid4())[:8],
        "from": data.fromUser, "to": data.toUser,
        "message": data.message, "timestamp": get_local_time(), "read": False,
    })
    return {"message": "✅ Mesaj gönderildi"}

@app.get("/get_conversation/{user1}/{user2}")
def get_conversation(user1: str, user2: str):
    return messages.get(get_conv_key(user1, user2), [])

@app.post("/mark_as_read/{user_id}/{other_user}")
def mark_as_read(user_id: str, other_user: str):
    key = get_conv_key(user_id, other_user)
    if key in messages:
        for msg in messages[key]:
            if msg["to"] == user_id:
                msg["read"] = True
    return {"message": "✅ Okundu"}

@app.get("/get_unread_count/{user_id}")
def get_unread_count(user_id: str):
    result = {}
    for conv in messages.values():
        for msg in conv:
            if msg["to"] == user_id and not msg["read"]:
                result[msg["from"]] = result.get(msg["from"], 0) + 1
    return result

# ═══════════════════════════════════════════════════════════════════════════════
# 👥 GRUP MESAJLAŞMA
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/send_room_message")
def send_room_message(data: RoomMessageModel):
    if data.fromUser in muted_users:
        raise HTTPException(403, "🔇 Mesaj gönderme yetkiniz kaldırılmıştır")
    room = data.roomName
    if room != "Genel" and room not in rooms:
        raise HTTPException(status_code=404, detail="Oda bulunamadı!")
    if room not in room_messages:
        room_messages[room] = []
    room_messages[room].append({
        "id": str(uuid.uuid4())[:8],
        "from": data.fromUser,
        "message": data.message,
        "timestamp": get_local_time(),
        "character": locations.get(data.fromUser, {}).get("character", "🧍"),
    })
    if len(room_messages[room]) > MAX_ROOM_MESSAGES:
        room_messages[room] = room_messages[room][-MAX_ROOM_MESSAGES:]
    return {"message": "✅ Grup mesajı gönderildi"}

@app.get("/get_room_messages/{room_name}")
def get_room_messages(room_name: str, limit: int = 50):
    return room_messages.get(room_name, [])[-limit:]

@app.get("/get_room_messages_since/{room_name}")
def get_room_messages_since(room_name: str, last_id: str = ""):
    msgs = room_messages.get(room_name, [])
    if not last_id:
        return msgs[-50:]
    for i, msg in enumerate(msgs):
        if msg["id"] == last_id:
            return msgs[i+1:]
    return msgs[-50:]

@app.get("/get_room_unread/{room_name}/{user_id}")
def get_room_unread(room_name: str, user_id: str):
    msgs = room_messages.get(room_name, [])
    return {"count": len(msgs), "lastId": msgs[-1]["id"] if msgs else ""}

# ═══════════════════════════════════════════════════════════════════════════════
# 🎙️ SESLİ MESAJLAR (1-1)
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/send_voice_message")
def send_voice_message(data: VoiceMessageModel):
    voice_id = str(uuid.uuid4())[:12]
    voice_messages[voice_id] = {
        "voiceId": voice_id,
        "fromUser": data.fromUser, "toUser": data.toUser,
        "audioBase64": data.audioBase64,
        "durationSeconds": data.durationSeconds,
        "timestamp": get_local_time(), "read": False,
    }
    key = get_conv_key(data.fromUser, data.toUser)
    if key not in messages:
        messages[key] = []
    messages[key].append({
        "id": str(uuid.uuid4())[:8],
        "from": data.fromUser, "to": data.toUser,
        "message": "", "type": "voice",
        "voiceId": voice_id,
        "durationSeconds": data.durationSeconds,
        "timestamp": get_local_time(), "read": False,
    })
    if len(voice_messages) > MAX_VOICE_MESSAGES:
        oldest_key = next(iter(voice_messages))
        del voice_messages[oldest_key]
    return {"message": "✅ Sesli mesaj gönderildi", "voiceId": voice_id}

@app.get("/get_voice_message/{voice_id}")
def get_voice_message(voice_id: str):
    if voice_id not in voice_messages:
        raise HTTPException(status_code=404, detail="Sesli mesaj bulunamadı!")
    return voice_messages[voice_id]

# ═══════════════════════════════════════════════════════════════════════════════
# 🎙️ SESLİ MESAJLAR (GRUP)
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/send_room_voice_message")
def send_room_voice_message(data: RoomVoiceMessageModel):
    room = data.roomName
    if room != "Genel" and room not in rooms:
        raise HTTPException(status_code=404, detail="Oda bulunamadı!")
    voice_id = str(uuid.uuid4())[:12]
    room_voice_messages[voice_id] = {
        "voiceId": voice_id, "fromUser": data.fromUser, "roomName": room,
        "audioBase64": data.audioBase64,
        "durationSeconds": data.durationSeconds,
        "timestamp": get_local_time(),
    }
    if room not in room_messages:
        room_messages[room] = []
    room_messages[room].append({
        "id": str(uuid.uuid4())[:8],
        "from": data.fromUser,
        "message": "", "type": "voice",
        "voiceId": voice_id,
        "durationSeconds": data.durationSeconds,
        "timestamp": get_local_time(),
        "character": locations.get(data.fromUser, {}).get("character", "🧍"),
    })
    if len(room_messages[room]) > MAX_ROOM_MESSAGES:
        room_messages[room] = room_messages[room][-MAX_ROOM_MESSAGES:]
    return {"message": "✅ Sesli mesaj gönderildi", "voiceId": voice_id}

@app.get("/get_room_voice_message/{voice_id}")
def get_room_voice_message(voice_id: str):
    if voice_id not in room_voice_messages:
        raise HTTPException(status_code=404, detail="Sesli mesaj bulunamadı!")
    return room_voice_messages[voice_id]

# ═══════════════════════════════════════════════════════════════════════════════
# 📻 WALKİE-TALKİE (1-1)
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/walkie_send")
def walkie_send(data: WalkieSendModel):
    key = get_conv_key(data.fromUser, data.toUser)
    walkie_queue[key] = {
        "id": str(uuid.uuid4())[:8],
        "from": data.fromUser, "to": data.toUser,
        "audioBase64": data.audioBase64,
        "timestamp": get_local_time(),
    }
    return {"message": "✅ Walkie gönderildi"}

@app.get("/walkie_listen/{user_id}/{other_user}")
def walkie_listen(user_id: str, other_user: str, last_id: str = ""):
    key = get_conv_key(user_id, other_user)
    entry = walkie_queue.get(key)
    if entry and entry.get("to") == user_id and entry.get("id") != last_id:
        return {"hasAudio": True, "id": entry["id"],
                "from": entry["from"], "audioBase64": entry["audioBase64"]}
    return {"hasAudio": False, "id": last_id}

# ═══════════════════════════════════════════════════════════════════════════════
# 📻 WALKİE-TALKİE (ODA)
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/room_walkie_send")
def room_walkie_send(data: RoomWalkieSendModel):
    room = data.roomName
    if room not in room_walkie_queue:
        room_walkie_queue[room] = []
    entry = {
        "id": str(uuid.uuid4())[:8],
        "from": data.fromUser, "roomName": room,
        "audioBase64": data.audioBase64,
        "timestamp": get_local_time(),
    }
    room_walkie_queue[room].append(entry)
    if len(room_walkie_queue[room]) > MAX_WALKIE_QUEUE:
        room_walkie_queue[room] = room_walkie_queue[room][-MAX_WALKIE_QUEUE:]
    return {"message": "✅ Oda walkie gönderildi", "id": entry["id"]}

@app.get("/room_walkie_listen/{room_name}")
def room_walkie_listen(room_name: str, user_id: str = "", last_id: str = ""):
    queue = room_walkie_queue.get(room_name, [])
    if not last_id:
        for entry in reversed(queue):
            if entry["from"] != user_id:
                return {"hasAudio": True, "id": entry["id"],
                        "from": entry["from"], "audioBase64": entry["audioBase64"]}
        return {"hasAudio": False, "id": ""}
    found_last = False
    for entry in queue:
        if entry["id"] == last_id:
            found_last = True
            continue
        if found_last and entry["from"] != user_id:
            return {"hasAudio": True, "id": entry["id"],
                    "from": entry["from"], "audioBase64": entry["audioBase64"]}
    return {"hasAudio": False, "id": last_id}

# ═══════════════════════════════════════════════════════════════════════════════
# 🆘 SOS SİSTEMİ
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/sos_alert")
def sos_alert(data: SosModel):
    sos_alerts[data.roomName] = {
        "userId": data.userId, "roomName": data.roomName,
        "lat": data.lat, "lng": data.lng,
        "message": data.message, "timestamp": get_local_time(), "active": True,
    }
    return {"message": "✅ SOS gönderildi"}

@app.get("/get_sos/{room_name}")
def get_sos(room_name: str):
    return sos_alerts.get(room_name, {"active": False})

@app.delete("/cancel_sos/{room_name}")
def cancel_sos(room_name: str, user_id: str):
    if room_name in sos_alerts:
        sos_alerts[room_name]["active"] = False
    return {"message": "✅ SOS iptal edildi"}

# ═══════════════════════════════════════════════════════════════════════════════
# 🎵 MÜZİK YAYINI
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/music_start")
def music_start(data: MusicStartModel):
    music_broadcasts[data.roomName] = {
        "broadcasterId": data.broadcasterId, "title": data.title,
        "startedAt": get_local_time(), "chunks": [], "chunkIndex": 0,
    }
    return {"message": "✅ Yayın başladı"}

@app.post("/music_chunk")
def music_chunk(data: MusicChunkModel):
    if data.roomName not in music_broadcasts:
        raise HTTPException(status_code=404, detail="Yayın bulunamadı!")
    broadcast = music_broadcasts[data.roomName]
    chunk_id = str(uuid.uuid4())[:8]
    broadcast["chunks"].append({
        "id": chunk_id, "index": broadcast["chunkIndex"],
        "audioBase64": data.audioBase64, "timestamp": get_local_time(),
    })
    broadcast["chunkIndex"] += 1
    if len(broadcast["chunks"]) > 10:
        broadcast["chunks"] = broadcast["chunks"][-10:]
    return {"message": "✅ Chunk kaydedildi", "chunkId": chunk_id}

@app.post("/music_stop")
def music_stop(data: MusicStopModel):
    if data.roomName in music_broadcasts:
        del music_broadcasts[data.roomName]
    return {"message": "✅ Yayın durduruldu"}

@app.get("/music_status/{room_name}")
def music_status(room_name: str):
    broadcast = music_broadcasts.get(room_name)
    if not broadcast:
        return {"active": False, "broadcasterId": None, "title": ""}
    return {"active": True, "broadcasterId": broadcast["broadcasterId"],
            "title": broadcast["title"], "chunkCount": len(broadcast["chunks"])}

@app.get("/music_listen/{room_name}")
def music_listen(room_name: str, after_index: int = 0):
    broadcast = music_broadcasts.get(room_name)
    if not broadcast:
        return {"active": False, "chunks": []}
    chunks = [c for c in broadcast["chunks"] if c["index"] > after_index]
    return {"active": True, "broadcasterId": broadcast["broadcasterId"],
            "title": broadcast["title"],
            "chunks": [{"id": c["id"], "index": c["index"]} for c in chunks]}

@app.get("/music_chunk_data/{room_name}/{chunk_id}")
def music_chunk_data(room_name: str, chunk_id: str):
    broadcast = music_broadcasts.get(room_name)
    if not broadcast:
        raise HTTPException(status_code=404, detail="Yayın bulunamadı!")
    for chunk in broadcast["chunks"]:
        if chunk["id"] == chunk_id:
            return {"audioBase64": chunk["audioBase64"]}
    raise HTTPException(status_code=404, detail="Chunk bulunamadı!")

# ═══════════════════════════════════════════════════════════════════════════════
# 👑 SÜPER ADMİN
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/check_super_admin/{user_id}")
def check_super_admin(user_id: str, device_id: str = "", token: str = ""):
    return {"isSuperAdmin": is_super_admin(user_id, device_id, token)}

@app.post("/super_admin_login")
def super_admin_login(data: dict):
    admin_id  = data.get("adminId", "").strip()
    password  = data.get("password", "").strip()
    if not admin_id or not password:
        raise HTTPException(400, "ID ve Şifre gerekli")
    if SUPER_ADMIN_CREDENTIALS.get(admin_id) != password:
        raise HTTPException(403, "Hatalı ID veya Şifre")
    now = datetime.now(DEFAULT_TIMEZONE)
    requester_device = data.get("deviceId", "").strip()
    stale_tokens = [t for t, s in _super_admin_sessions.items()
                    if s["userId"] == admin_id and now < s["expiresAt"]]
    for t in stale_tokens:
        del _super_admin_sessions[t]
    token = str(uuid.uuid4())
    _super_admin_sessions[token] = {
        "userId": admin_id,
        "expiresAt": datetime.now(DEFAULT_TIMEZONE) + timedelta(hours=24),
        "deviceId": requester_device,
    }
    return {"token": token, "message": "✅ Süper admin girişi başarılı"}

@app.post("/super_admin_logout")
def super_admin_logout(data: dict):
    admin_id = data.get("adminId", "")
    token    = data.get("token", "")
    if token and token in _super_admin_sessions:
        del _super_admin_sessions[token]
        return {"message": "✅ Admin oturumu kapatıldı"}
    to_delete = [t for t, s in _super_admin_sessions.items() if s["userId"] == admin_id]
    for t in to_delete:
        del _super_admin_sessions[t]
    return {"message": "✅ Çıkış yapıldı"}

@app.get("/get_all_rooms_info")
def get_all_rooms_info(admin_id: str = "", device_id: str = "", token: str = ""):
    if not is_super_admin(admin_id, device_id, token):
        raise HTTPException(status_code=403, detail="Yetkisiz!")
    result = []
    for room_name in ["Genel"] + list(rooms.keys()):
        room_data = rooms.get(room_name, {})
        room_admin = room_data.get("createdBy")
        online = [u for u in locations.values()
                  if u.get("roomName") == room_name and is_user_online(u.get("lastSeen", ""))]
        user_list = []
        for u in online:
            uid = u["userId"]
            is_room_creator = any(r.get("createdBy") == uid for r in rooms.values())
            user_list.append({
                "userId": uid, "character": u.get("character", "🧍"),
                "isAdmin": uid == room_admin, "isCreator": is_room_creator, "isHidden": False,
            })
        result.append({
            "roomName": room_name, "onlineCount": len(online),
            "roomAdmin": room_admin, "hasPassword": bool(room_data.get("password")),
            "users": user_list,
        })
    return result

# ═══════════════════════════════════════════════════════════════════════════════
# 📲 FCM TOKEN
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/register_fcm_token")
def register_fcm_token(data: FcmTokenModel):
    fcm_tokens[data.userId] = data.token
    return {"message": "✅ FCM token kaydedildi"}

# ═══════════════════════════════════════════════════════════════════════════════
# 🤝 KULLANICI ADI DEĞİŞTİRME
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/change_username")
def change_username(data: ChangeUsernameModel):
    old = data.oldName
    new = data.newName
    if not new or len(new.strip()) < 1:
        raise HTTPException(status_code=400, detail="İsim boş olamaz!")
    if new in locations and new != old:
        existing    = locations[new]
        req_device  = (data.deviceId or "").strip()
        exist_device = existing.get("deviceId", "").strip()
        same_device = req_device and exist_device and req_device == exist_device
        timed_out   = not is_user_online(existing.get("lastSeen", ""))
        if same_device or timed_out:
            locations.pop(new, None)
        else:
            raise HTTPException(status_code=400, detail="Bu isim zaten kullanımda!")
    if old in locations:
        locations[new] = locations.pop(old)
        locations[new]["userId"] = new
    if old in location_history:
        location_history[new] = location_history.pop(old)
        global _save_pending
        _save_pending = True
    for key in list(scores.keys()):
        if key.endswith(f"_{old}"):
            room = key[:-(len(old)+1)]
            scores[f"{room}_{new}"] = scores.pop(key)
    for key in list(pin_collection_history.keys()):
        if key.endswith(f"_{old}"):
            room = key[:-(len(old)+1)]
            pin_collection_history[f"{room}_{new}"] = pin_collection_history.pop(key)
    for key in list(messages.keys()):
        parts = key.split('_')
        if old in parts:
            conv = messages.pop(key)
            for msg in conv:
                if msg['from'] == old: msg['from'] = new
                if msg['to']   == old: msg['to']   = new
            other = parts[1] if parts[0] == old else parts[0]
            new_key = '_'.join(sorted([new, other]))
            if new_key in messages:
                messages[new_key].extend(conv)
                messages[new_key].sort(key=lambda m: m.get('timestamp', ''))
            else:
                messages[new_key] = conv
    for room_msgs in room_messages.values():
        for msg in room_msgs:
            if msg.get('from') == old: msg['from'] = new
    for room in rooms.values():
        if room.get("createdBy") == old:
            room["createdBy"] = new
        collectors = room.get("collectors", [])
        if old in collectors:
            collectors.remove(old); collectors.append(new)
        voice = room.get("voiceAllowed", [])
        if old in voice:
            voice.remove(old); voice.append(new)
    for key in list(geofence_entries.keys()):
        entry = geofence_entries[key]
        if entry.get("userId") == old:
            geofence_entries.pop(key)
            entry["userId"] = new
            geofence_entries[f"{new}_{entry['geofenceId']}"] = entry
    for gf_list in room_geofences.values():
        for gf in gf_list:
            if gf.get("createdBy") == old: gf["createdBy"] = new
    if old in fcm_tokens:
        fcm_tokens[new] = fcm_tokens.pop(old)
    if old in kicked_users:
        kicked_users[new] = kicked_users.pop(old)
    if old in muted_users:
        muted_users[new] = muted_users.pop(old)
    for pin in pins.values():
        if pin.get("creator") == old: pin["creator"] = new
    for key in list(walkie_queue.keys()):
        entry = walkie_queue[key]
        if entry.get("from") == old: entry["from"] = new
        parts = key.split("_", 1)
        if len(parts) == 2:
            frm, to = parts
            if frm == old or to == old:
                walkie_queue.pop(key)
                new_key = f"{new if frm==old else frm}_{new if to==old else to}"
                walkie_queue[new_key] = entry
    for room_queue in room_walkie_queue.values():
        for entry in room_queue:
            if entry.get("from") == old: entry["from"] = new
    for vm in voice_messages.values():
        if vm.get("fromUser") == old: vm["fromUser"] = new
        if vm.get("toUser")   == old: vm["toUser"]   = new
    for rvm in room_voice_messages.values():
        if rvm.get("fromUser") == old: rvm["fromUser"] = new
    for req in permission_requests.values():
        if req.get("requesterUserId") == old: req["requesterUserId"] = new
    for alert in sos_alerts.values():
        if alert.get("userId") == old: alert["userId"] = new
    for broadcast in music_broadcasts.values():
        if broadcast.get("broadcasterId") == old: broadcast["broadcasterId"] = new
    if old in visibility_settings:
        visibility_settings[new] = visibility_settings.pop(old)
    for vs in visibility_settings.values():
        allowed = vs.get("allowed", [])
        if old in allowed:
            allowed.remove(old); allowed.append(new)
    return {"message": f"✅ İsim değiştirildi: {old} → {new}"}

# ═══════════════════════════════════════════════════════════════════════════════
# 🗺️ GEOFENCE
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/geofence/save")
def geofence_save(data: GeofenceSaveModel):
    room = rooms.get(data.roomName)
    if not room:
        raise HTTPException(status_code=404, detail="Oda bulunamadı")
    if room.get("createdBy") != data.adminId and not is_super_admin(data.adminId):
        raise HTTPException(status_code=403, detail="Sadece oda admini veya süper admin kaydedebilir")
    now = get_local_time()
    saved = [{
        "id": gf["id"], "name": gf["name"],
        "center_lat": gf["center_lat"], "center_lng": gf["center_lng"],
        "radius": gf["radius"], "createdBy": data.adminId,
        "createdAt": gf.get("createdAt", now),
    } for gf in data.geofences]
    room_geofences[data.roomName] = saved
    return {"message": f"✅ {len(saved)} geofence kaydedildi"}

@app.get("/geofence/get/{room_name}")
def geofence_get(room_name: str):
    gfs = room_geofences.get(room_name, [])
    result = []
    for gf in gfs:
        entries = [v for k, v in geofence_entries.items()
                   if k.endswith(f"_{gf['id']}") and v.get("roomName") == room_name]
        result.append({**gf, "entries": entries})
    return {"geofences": result}

@app.post("/geofence/entry")
def geofence_entry(data: GeofenceEntryModel):
    key = f"{data.userId}_{data.geofenceId}"
    now = get_local_time()
    if data.inside:
        geofence_entries[key] = {
            "userId": data.userId, "geofenceId": data.geofenceId,
            "entryTime": now, "roomName": data.roomName,
        }
    else:
        geofence_entries.pop(key, None)
    return {"ok": True}

@app.post("/geofence/personal/save")
def personal_geofence_save(data: dict):
    user_id   = data.get("userId", "").strip()
    geofences = data.get("geofences", [])
    if not user_id:
        raise HTTPException(400, "userId gerekli")
    now = get_local_time()
    saved = [{
        "id":         gf.get("id", str(uuid.uuid4())[:8]),
        "name":       gf.get("name", "Bölgem"),
        "center_lat": float(gf.get("center_lat", 0)),
        "center_lng": float(gf.get("center_lng", 0)),
        "radius":     float(gf.get("radius", 100)),
        "threshold":  int(gf.get("threshold", 0)),
        "createdAt":  gf.get("createdAt", now),
    } for gf in geofences]
    user_geofences[user_id] = saved
    return {"message": f"✅ {len(saved)} kişisel geofence kaydedildi"}

@app.get("/geofence/personal/get/{user_id}")
def personal_geofence_get(user_id: str, requester: str = ""):
    if requester != user_id and not any(
        s["userId"] == requester and datetime.now(DEFAULT_TIMEZONE) < s["expiresAt"]
        for s in _super_admin_sessions.values()
    ):
        raise HTTPException(403, "Yetkisiz")
    return {"geofences": user_geofences.get(user_id, [])}

@app.delete("/geofence/personal/delete/{user_id}/{geofence_id}")
def personal_geofence_delete(user_id: str, geofence_id: str, requester: str = ""):
    if requester != user_id:
        raise HTTPException(403, "Sadece sahibi silebilir")
    user_geofences[user_id] = [g for g in user_geofences.get(user_id, []) if g["id"] != geofence_id]
    return {"message": "✅ Silindi"}

@app.post("/geofence/personal/rename")
def personal_geofence_rename(data: dict):
    user_id = data.get("userId", ""); geofence_id = data.get("geofenceId", "")
    new_name = data.get("newName", "")
    if not user_id or not geofence_id:
        raise HTTPException(400, "Eksik parametre")
    for gf in user_geofences.get(user_id, []):
        if gf["id"] == geofence_id:
            gf["name"] = new_name
            return {"message": "✅ İsim güncellendi"}
    raise HTTPException(404, "Geofence bulunamadı")

@app.post("/geofence/personal/threshold")
def personal_geofence_threshold(data: dict):
    user_id = data.get("userId", ""); geofence_id = data.get("geofenceId", "")
    threshold = int(data.get("threshold", 0))
    for gf in user_geofences.get(user_id, []):
        if gf["id"] == geofence_id:
            gf["threshold"] = threshold
            return {"message": "✅ Kota güncellendi"}
    raise HTTPException(404, "Geofence bulunamadı")

@app.post("/geofence/rename")
def geofence_rename(data: GeofenceRenameModel):
    room = rooms.get(data.roomName)
    if not room:
        raise HTTPException(status_code=404, detail="Oda bulunamadı")
    if room.get("createdBy") != data.adminId and not is_super_admin(data.adminId):
        raise HTTPException(status_code=403, detail="Sadece oda admini veya süper admin yeniden adlandırabilir")
    for gf in room_geofences.get(data.roomName, []):
        if gf["id"] == data.geofenceId:
            gf["name"] = data.newName
            return {"message": "✅ İsim güncellendi"}
    raise HTTPException(status_code=404, detail="Geofence bulunamadı")

@app.delete("/geofence/delete/{room_name}/{geofence_id}")
def geofence_delete(room_name: str, geofence_id: str, admin_id: str):
    room = rooms.get(room_name)
    if not room or (room.get("createdBy") != admin_id and not is_super_admin(admin_id)):
        raise HTTPException(status_code=403, detail="Yetkisiz")
    room_geofences[room_name] = [g for g in room_geofences.get(room_name, []) if g["id"] != geofence_id]
    for k in list(geofence_entries.keys()):
        if k.endswith(f"_{geofence_id}"):
            del geofence_entries[k]
    return {"message": "✅ Silindi"}

# ═══════════════════════════════════════════════════════════════════════════════
# 🗺️ GRUP ROTASI
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/share_route")
def share_route(data: ShareRouteModel):
    room = rooms.get(data.roomName)
    if not room:
        raise HTTPException(status_code=404, detail="Oda bulunamadı")
    shared_routes[data.roomName] = {
        "sharedBy": data.sharedBy, "waypoints": data.waypoints,
        "active": True, "sharedAt": get_local_time(),
    }
    return {"message": "✅ Rota paylaşıldı"}

@app.get("/get_shared_route/{room_name}")
def get_shared_route(room_name: str):
    route = shared_routes.get(room_name)
    if not route or not route.get("active"):
        return {"active": False}
    return {"active": True, **route}

@app.delete("/clear_shared_route/{room_name}")
def clear_shared_route(room_name: str, admin_id: str):
    route = shared_routes.get(room_name)
    if not route:
        return {"message": "Rota zaten yok"}
    room = rooms.get(room_name)
    if room and room.get("createdBy") != admin_id:
        raise HTTPException(status_code=403, detail="Sadece admin silebilir")
    shared_routes[room_name] = {"active": False}
    return {"message": "✅ Rota temizlendi"}

# ═══════════════════════════════════════════════════════════════════════════════
# 📚 ROTA KÜTÜPHANESİ
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/route_library")
def add_route_library(data: RouteLibraryModel):
    if data.roomName not in route_library:
        route_library[data.roomName] = []
    route_id = str(uuid.uuid4())[:8]
    route_library[data.roomName].append({
        "id": route_id,
        "name": data.name,
        "creator": data.creator,
        "waypoints": data.waypoints,
        "distKm": data.distKm,
        "durMin": data.durMin,
        "createdAt": get_local_time(),
    })
    _flush_route_library()
    return {"id": route_id, "message": "✅ Rota kütüphaneye eklendi"}

@app.get("/route_library/{room_name}")
def get_route_library(room_name: str):
    return {"routes": route_library.get(room_name, [])}

@app.delete("/route_library/{room_name}/{route_id}")
def delete_route_library(room_name: str, route_id: str, user_id: str):
    lib = route_library.get(room_name, [])
    route = next((r for r in lib if r["id"] == route_id), None)
    if not route:
        raise HTTPException(status_code=404, detail="Rota bulunamadı")
    if route["creator"] != user_id and not is_super_admin(user_id):
        raise HTTPException(status_code=403, detail="Sadece oluşturan silebilir")
    route_library[room_name] = [r for r in lib if r["id"] != route_id]
    _flush_route_library()
    return {"message": "✅ Silindi"}

# ═══════════════════════════════════════════════════════════════════════════════
# 📌 ODA POI NOKTALARI (mola/kamp/vb.)
# ═══════════════════════════════════════════════════════════════════════════════

class RoomPoiModel(BaseModel):
    roomName: str
    id: str
    icon: str
    name: str
    lat: float
    lng: float
    radius: float = 50.0
    color: int = 0
    cap: int = 0
    geofenceActive: bool = False
    desc: str = ""
    createdBy: str = ""

@app.post("/route_waypoints")
def add_room_poi(data: RoomPoiModel):
    if data.roomName not in room_route_waypoints:
        room_route_waypoints[data.roomName] = []
    # Aynı id varsa güncelle, yoksa ekle
    wps = room_route_waypoints[data.roomName]
    idx = next((i for i, w in enumerate(wps) if w["id"] == data.id), None)
    entry = {
        "id": data.id, "icon": data.icon, "name": data.name,
        "lat": data.lat, "lng": data.lng, "radius": data.radius,
        "color": data.color, "cap": data.cap,
        "geofenceActive": data.geofenceActive, "desc": data.desc,
        "createdBy": data.createdBy, "updatedAt": get_local_time(),
    }
    if idx is not None:
        wps[idx] = entry
    else:
        wps.append(entry)
    _flush_route_waypoints()
    return {"message": "✅ POI kaydedildi"}

@app.get("/route_waypoints/{room_name}")
def get_room_pois(room_name: str):
    return {"waypoints": room_route_waypoints.get(room_name, [])}

@app.delete("/route_waypoints/{room_name}/{poi_id}")
def delete_room_poi(room_name: str, poi_id: str, user_id: str = ""):
    wps = room_route_waypoints.get(room_name, [])
    poi = next((w for w in wps if w["id"] == poi_id), None)
    if not poi:
        raise HTTPException(status_code=404, detail="POI bulunamadı")
    if user_id and poi.get("createdBy") and poi["createdBy"] != user_id and not is_super_admin(user_id):
        raise HTTPException(status_code=403, detail="Sadece oluşturan silebilir")
    room_route_waypoints[room_name] = [w for w in wps if w["id"] != poi_id]
    _flush_route_waypoints()
    return {"message": "✅ POI silindi"}

# ═══════════════════════════════════════════════════════════════════════════════
# 🚪 KULLANICI ATMA / BAN
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/kick_user/{room_name}/{target_user}")
def kick_user(room_name: str, target_user: str, admin_id: str,
              token: str = "", device_id: str = ""):
    room = rooms.get(room_name)
    if not room:
        raise HTTPException(status_code=404, detail="Oda bulunamadı")
    is_creator = room.get("createdBy") == admin_id
    is_sadmin  = is_super_admin(admin_id, device_id, token)
    if not is_creator and not is_sadmin:
        raise HTTPException(status_code=403, detail="Sadece oda admini veya süper admin atabilir")
    if target_user == admin_id:
        raise HTTPException(status_code=400, detail="Kendinizi atamazsınız")
    target_is_sadmin = any(
        s["userId"] == target_user and datetime.now(DEFAULT_TIMEZONE) < s["expiresAt"]
        for s in _super_admin_sessions.values()
    )
    if target_is_sadmin and not is_sadmin:
        raise HTTPException(status_code=403, detail="Süper admini atamazsınız")
    if room.get("createdBy") == target_user and not is_sadmin:
        raise HTTPException(status_code=403, detail="Oda kurucusunu atamazsınız")
    now = get_local_time()
    if target_user in locations and locations[target_user].get("roomName") == room_name:
        locations[target_user]["roomName"] = "Genel"
    kicked_users[target_user] = {"roomName": room_name, "kickedAt": now, "kickedBy": admin_id}
    return {"message": f"✅ {target_user} odadan atıldı"}

@app.post("/super_admin_ban")
def super_admin_ban(data: dict):
    admin_id  = data.get("adminId", ""); token = data.get("token", "")
    device_id = data.get("deviceId", ""); target = data.get("targetUser", "").strip()
    reason    = data.get("reason", "Süper admin kararı").strip()
    if not is_super_admin(admin_id, device_id, token):
        raise HTTPException(403, "Yetkisiz")
    if not target: raise HTTPException(400, "Hedef kullanıcı belirtilmedi")
    if target == admin_id: raise HTTPException(400, "Kendinizi banlayamazsınız")
    now = get_local_time()
    target_device = locations.get(target, {}).get("deviceId", "")
    banned_users[target]  = {"bannedAt": now, "bannedBy": admin_id, "reason": reason, "deviceId": target_device}
    if target_device:
        banned_devices[target_device] = {"bannedAt": now, "bannedBy": admin_id, "reason": reason}
    if target in locations:
        locations[target]["roomName"] = "Genel"
    kicked_users[target] = {"roomName": "Genel", "kickedAt": now, "kickedBy": f"⛔ BAN: {admin_id}"}
    return {"message": f"✅ {target} banlandı"}

@app.post("/super_admin_unban")
def super_admin_unban(data: dict):
    admin_id = data.get("adminId", ""); token = data.get("token", "")
    device_id = data.get("deviceId", ""); target = data.get("targetUser", "").strip()
    if not is_super_admin(admin_id, device_id, token):
        raise HTTPException(403, "Yetkisiz")
    device = banned_users.get(target, {}).get("deviceId", "")
    banned_users.pop(target, None)
    if device: banned_devices.pop(device, None)
    return {"message": f"✅ {target} banı kaldırıldı"}

@app.post("/super_admin_mute")
def super_admin_mute(data: dict):
    admin_id = data.get("adminId", ""); token = data.get("token", "")
    device_id = data.get("deviceId", ""); target = data.get("targetUser", "").strip()
    reason = data.get("reason", "Süper admin kararı").strip()
    if not is_super_admin(admin_id, device_id, token):
        raise HTTPException(403, "Yetkisiz")
    if not target: raise HTTPException(400, "Hedef kullanıcı belirtilmedi")
    now = get_local_time()
    muted_users[target] = {"mutedAt": now, "mutedBy": admin_id, "reason": reason}
    for room in rooms.values():
        va = room.get("voiceAllowed", [])
        if target in va: va.remove(target)
    return {"message": f"🔇 {target} susturuldu"}

@app.post("/super_admin_unmute")
def super_admin_unmute(data: dict):
    admin_id = data.get("adminId", ""); token = data.get("token", "")
    device_id = data.get("deviceId", ""); target = data.get("targetUser", "").strip()
    if not is_super_admin(admin_id, device_id, token):
        raise HTTPException(403, "Yetkisiz")
    muted_users.pop(target, None)
    return {"message": f"🔊 {target} susturması kaldırıldı"}

@app.post("/super_admin_kick")
def super_admin_kick(data: dict):
    admin_id = data.get("adminId", ""); token = data.get("token", "")
    device_id = data.get("deviceId", ""); target = data.get("targetUser", "").strip()
    if not is_super_admin(admin_id, device_id, token):
        raise HTTPException(403, "Yetkisiz")
    if not target: raise HTTPException(400, "Hedef kullanıcı belirtilmedi")
    now = get_local_time()
    room = locations.get(target, {}).get("roomName", "Genel")
    if room == "Genel":
        raise HTTPException(400, f"{target} zaten Genel odada")
    if target in locations:
        locations[target]["roomName"] = "Genel"
    kicked_users[target] = {"roomName": room, "kickedAt": now, "kickedBy": f"⚡ {admin_id}"}
    return {"message": f"🚪 {target} odadan atıldı ({room})"}

@app.get("/check_muted/{user_id}")
def check_muted(user_id: str):
    return {"muted": user_id in muted_users}

@app.get("/get_banned_users")
def get_banned_users(admin_id: str = "", device_id: str = "", token: str = ""):
    if not is_super_admin(admin_id, device_id, token):
        raise HTTPException(403, "Yetkisiz")
    return [{"userId": uid, **info} for uid, info in banned_users.items()]

@app.get("/check_kicked/{user_id}")
def check_kicked(user_id: str):
    kick = kicked_users.get(user_id)
    if not kick:
        return {"kicked": False}
    del kicked_users[user_id]
    is_ban = "BAN" in str(kick.get("kickedBy", ""))
    return {"kicked": True, "isBan": is_ban,
            "roomName": kick["roomName"], "kickedBy": kick["kickedBy"]}

# ═══════════════════════════════════════════════════════════════════════════════
# 🔧 YÖNETİM
# ═══════════════════════════════════════════════════════════════════════════════

@app.delete("/remove_user/{user_id}")
def remove_user(user_id: str):
    if user_id in locations:
        del locations[user_id]
    return {"message": f"✅ {user_id} silindi"}

@app.delete("/clear")
def clear_all():
    global _save_pending
    locations.clear(); location_history.clear(); pins.clear()
    scores.clear(); pin_collection_history.clear(); messages.clear()
    room_messages.clear(); walkie_queue.clear(); room_walkie_queue.clear()
    voice_messages.clear(); room_voice_messages.clear()
    sos_alerts.clear(); music_broadcasts.clear(); permission_requests.clear()
    _save_pending = True
    return {"message": "✅ Tüm veriler silindi"}

# ═══════════════════════════════════════════════════════════════════════════════
# 🚌 TRANSPORT MODU
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/set_transport_role")
def set_transport_role(data: dict):
    room = data.get("roomName", "Genel")
    uid = data.get("userId", "")
    role = data.get("role", "")
    vehicle = data.get("vehicleName", "")
    if not uid:
        raise HTTPException(400, "userId gerekli")
    if room not in transport_roles:
        transport_roles[room] = {}
    if role:
        transport_roles[room][uid] = {
            "role": role,
            "vehicleName": vehicle,
            "joinedAt": get_local_time(),
        }
    else:
        transport_roles[room].pop(uid, None)
    return {"ok": True}

@app.get("/get_transport_status/{room_name}")
def get_transport_status(room_name: str):
    roles = transport_roles.get(room_name, {})
    drivers, passengers, managers = [], [], []
    for uid, info in roles.items():
        loc = locations.get(uid, {})
        if not is_user_online(loc.get("lastSeen", "")):
            continue
        entry = {
            "userId": uid,
            "role": info["role"],
            "vehicleName": info.get("vehicleName", ""),
            "character": loc.get("character", "🧍"),
            "lat": loc.get("lat", 0),
            "lng": loc.get("lng", 0),
            "speed": loc.get("speed", 0),
        }
        if info["role"] == "driver":
            drivers.append(entry)
        elif info["role"] == "passenger":
            passengers.append(entry)
        elif info["role"] == "manager":
            managers.append(entry)
    return {"drivers": drivers, "passengers": passengers, "managers": managers}

@app.post("/transport_broadcast")
def transport_broadcast_msg(data: dict):
    room = data.get("roomName", "Genel")
    uid = data.get("fromUser", "")
    msg = data.get("message", "")
    if not msg:
        raise HTTPException(400, "Mesaj boş olamaz")
    vehicle = transport_roles.get(room, {}).get(uid, {}).get("vehicleName", "")
    transport_broadcasts[room] = {
        "id": str(uuid.uuid4())[:8],
        "fromUser": uid,
        "vehicleName": vehicle,
        "message": msg,
        "timestamp": get_local_time(),
    }
    return {"ok": True}

@app.get("/get_transport_broadcast/{room_name}")
def get_transport_broadcast(room_name: str):
    return transport_broadcasts.get(room_name, {})

# ─── Transport Durak (Stop) Yönetimi ─────────────────────────────────────────

class TransportStopModel(BaseModel):
    roomName: str
    id: str
    name: str
    lat: float
    lng: float
    radius: float = 80.0
    addedBy: str = ""
    addedByRole: str = ""

@app.post("/transport_stop")
def add_transport_stop(data: TransportStopModel):
    if data.roomName not in transport_stops:
        transport_stops[data.roomName] = {}
    transport_stops[data.roomName][data.id] = {
        "id": data.id, "name": data.name,
        "lat": data.lat, "lng": data.lng,
        "radius": data.radius,
        "addedBy": data.addedBy,
        "addedByRole": data.addedByRole,
        "createdAt": get_local_time(),
    }
    return {"ok": True}

@app.get("/transport_stops/{room_name}")
def get_transport_stops(room_name: str):
    return {"stops": list(transport_stops.get(room_name, {}).values())}

@app.delete("/transport_stop/{room_name}/{stop_id}")
def delete_transport_stop(room_name: str, stop_id: str):
    transport_stops.get(room_name, {}).pop(stop_id, None)
    return {"ok": True}

@app.post("/transport_arrival")
def report_transport_arrival(data: dict):
    room = data.get("roomName", "Genel")
    if room not in transport_arrivals:
        transport_arrivals[room] = []
    entry = {
        "id": str(uuid.uuid4())[:8],
        "stopId": data.get("stopId", ""),
        "stopName": data.get("stopName", ""),
        "userId": data.get("userId", ""),
        "character": data.get("character", "🧍"),
        "arrivalTime": get_local_time(),
    }
    # Keep last 50 arrivals per room
    transport_arrivals[room].append(entry)
    if len(transport_arrivals[room]) > 50:
        transport_arrivals[room] = transport_arrivals[room][-50:]
    return {"ok": True}

@app.get("/transport_arrivals/{room_name}")
def get_transport_arrivals(room_name: str):
    return {"arrivals": transport_arrivals.get(room_name, [])}
