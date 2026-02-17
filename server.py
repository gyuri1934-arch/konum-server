"""
═══════════════════════════════════════════════════════════════════════════════
                        KONUM TAKİP SERVER
═══════════════════════════════════════════════════════════════════════════════

Özellikler:
- Real-time konum takibi
- Çok odalı sistem (şifreli odalar)
- Pin toplama oyunu
- Rota geçmişi (hıza göre örnekleme)
- Mesajlaşma sistemi
- Admin yetkileri
- deviceId ile sabit cihaz takibi
- userId ve character (emoji) değiştirilebilir

Versiyon: 2.1 (deviceId + character desteği)
Güncelleme: 2026-02-17
═══════════════════════════════════════════════════════════════════════════════
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional, List
import time
import math
import pytz

# ═══════════════════════════════════════════════════════════════════════════════
# ⚙️ UYGULAMA BAŞLATMA VE AYARLAR
# ═══════════════════════════════════════════════════════════════════════════════

app = FastAPI(title="Konum Takip Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════════════════════════════════════
# 💾 VERİ SAKLAMASI (RAM - production için MongoDB önerilir)
# ═══════════════════════════════════════════════════════════════════════════════

users_locations = {}          # key = deviceId
conversations = {}
read_timestamps = {}
rooms = {}
location_history = {}         # key = deviceId
pins = {}
user_scores = {}
pin_collection_state = {}
room_permissions = {}
user_visibility = {}
user_pins_count = {}
pin_collection_history = {}

# ═══════════════════════════════════════════════════════════════════════════════
# 🎛️ SİSTEM AYARLARI
# ═══════════════════════════════════════════════════════════════════════════════

SPEED_THRESHOLD_VEHICLE = 30
SPEED_THRESHOLD_RUN = 15
SPEED_THRESHOLD_WALK = 3

MIN_DISTANCE_VEHICLE = 50
MIN_DISTANCE_RUN = 20
MIN_DISTANCE_WALK = 10
MIN_DISTANCE_IDLE = 5

MAX_POINTS_PER_USER = 5000
MAX_HISTORY_DAYS = 90

DEFAULT_TIMEZONE = pytz.timezone('Europe/Istanbul')
USER_TIMEOUT = 120  # saniye

# ═══════════════════════════════════════════════════════════════════════════════
# 🛠️ YARDIMCI FONKSİYONLAR
# ═══════════════════════════════════════════════════════════════════════════════

def get_local_time():
    return datetime.now(DEFAULT_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")

def get_conversation_key(user1: str, user2: str):
    return tuple(sorted([user1, user2]))

def calculate_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)
    
    a = math.sin(delta_phi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return R * c

# ═══════════════════════════════════════════════════════════════════════════════
# 📋 VERİ MODELLERİ
# ═══════════════════════════════════════════════════════════════════════════════

class LocationModel(BaseModel):
    deviceId: str
    userId: Optional[str] = None
    deviceType: str = "phone"
    lat: float
    lng: float
    altitude: float = 0.0
    speed: float = 0.0
    animationType: str = "pulse"
    roomName: str = "Genel"
    character: str = "🧍"           # emoji / karakter

class ProfileUpdateModel(BaseModel):
    deviceId: str
    userId: Optional[str] = None
    character: Optional[str] = None

class MessageModel(BaseModel):
    fromUser: str
    toUser: str
    message: str

class RoomCreateModel(BaseModel):
    roomName: str
    password: str
    createdBy: str

class RoomJoinModel(BaseModel):
    roomName: str
    password: str

class PinCreateModel(BaseModel):
    roomName: str
    creator: str
    lat: float
    lng: float

class VisibilityModel(BaseModel):
    userId: str
    mode: str
    allowed: List[str] = []

# ═══════════════════════════════════════════════════════════════════════════════
# 🏠 ANA SAYFA VE SAĞLIK KONTROLÜ
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/")
def home():
    total_messages = sum(len(msgs) for msgs in conversations.values())
    total_history = sum(len(h) for h in location_history.values())
    total_pins = len(pins)
    
    return {
        "status": "✅ Server çalışıyor!",
        "toplam_kullanici": len(users_locations),
        "toplam_oda": len(rooms) + 1,
        "toplam_konusma": len(conversations),
        "toplam_mesaj": total_messages,
        "toplam_gecmis_nokta": total_history,
        "toplam_pin": total_pins,
    }

@app.get("/ping")
def ping():
    return {"status": "alive"}

# ═══════════════════════════════════════════════════════════════════════════════
# 👤 PROFİL GÜNCELLEME (yeni endpoint)
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/update_profile")
async def update_profile(data: ProfileUpdateModel):
    if not data.deviceId:
        raise HTTPException(status_code=400, detail="deviceId zorunludur")

    key = data.deviceId

    if key not in users_locations:
        users_locations[key] = {
            "deviceId": key,
            "userId": "Misafir",
            "character": "🧍",
            "lat": 0.0,
            "lng": 0.0,
            "roomName": "Genel",
            "timestamp": get_local_time(),
            "last_seen": time.time(),
            "idle_status": "online",
            "idle_minutes": 0,
            "last_move_time": time.time(),
        }

    updated = False
    
    if data.userId is not None:
        new_name = data.userId.strip()
        users_locations[key]["userId"] = new_name if new_name else "Misafir"
        updated = True
    
    if data.character is not None:
        users_locations[key]["character"] = data.character
        updated = True

    if updated:
        print(f"👤 Profil güncellendi → deviceId={key} | userId={users_locations[key]['userId']} | char={users_locations[key]['character']}")
        return {"status": "success", "message": "Profil güncellendi"}
    
    return {"status": "success", "message": "Değişiklik yapılmadı"}

# ═══════════════════════════════════════════════════════════════════════════════
# 📍 KONUM GÜNCELLEMESİ (ANA FONKSİYON - deviceId ile)
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/update_location")
async def update_location(data: LocationModel):
    if not data.deviceId:
        raise HTTPException(status_code=400, detail="deviceId zorunludur")

    key = data.deviceId
    existing = users_locations.get(key, {})

    # Idle kontrolü
    idle_status = "online"
    idle_minutes = 0
    last_move_time = existing.get("last_move_time", time.time())

    if key in users_locations:
        old_loc = users_locations[key]
        distance = calculate_distance(old_loc["lat"], old_loc["lng"], data.lat, data.lng)
        if distance < 15:
            idle_seconds = time.time() - last_move_time
            idle_minutes = int(idle_seconds / 60)
            if idle_minutes > 0:
                idle_status = "idle"
            else:
                last_move_time = time.time()

    # Birleştirilmiş veri
    user_data = {
        "deviceId": data.deviceId,
        "userId": data.userId or existing.get("userId", "Misafir"),
        "character": data.character or existing.get("character", "🧍"),
        "deviceType": data.deviceType,
        "lat": data.lat,
        "lng": data.lng,
        "altitude": data.altitude,
        "speed": data.speed,
        "animationType": data.animationType,
        "roomName": data.roomName,
        "timestamp": get_local_time(),
        "last_seen": time.time(),
        "last_move_time": last_move_time,
        "idle_status": idle_status,
        "idle_minutes": idle_minutes,
    }

    users_locations[key] = user_data

    # ────────────────────────────────────────────────────────────────
    # ROTA GEÇMİŞİ (mevcut mantık - deviceId ile kaydediliyor)
    # ────────────────────────────────────────────────────────────────
    if key not in location_history:
        location_history[key] = []

    speed_kmh = data.speed
    if speed_kmh > SPEED_THRESHOLD_VEHICLE:
        min_dist = MIN_DISTANCE_VEHICLE
    elif speed_kmh > SPEED_THRESHOLD_RUN:
        min_dist = MIN_DISTANCE_RUN
    elif speed_kmh > SPEED_THRESHOLD_WALK:
        min_dist = MIN_DISTANCE_WALK
    else:
        min_dist = MIN_DISTANCE_IDLE

    should_add = True
    if location_history[key]:
        last = location_history[key][-1]
        dist = calculate_distance(last["lat"], last["lng"], data.lat, data.lng)
        if dist < min_dist:
            should_add = False

    if should_add:
        location_history[key].append({
            "lat": data.lat,
            "lng": data.lng,
            "timestamp": get_local_time(),
            "speed": data.speed,
            "altitude": data.altitude
        })

        # temizlik (mevcut kodunuzdaki gibi)
        now = datetime.now(DEFAULT_TIMEZONE)
        cutoff = now - timedelta(days=MAX_HISTORY_DAYS)
        cleaned = []
        for p in location_history[key]:
            try:
                pt = datetime.strptime(p["timestamp"], "%Y-%m-%d %H:%M:%S")
                pt = DEFAULT_TIMEZONE.localize(pt)
                if pt > cutoff:
                    cleaned.append(p)
            except:
                pass
        location_history[key] = cleaned[-MAX_POINTS_PER_USER:]

    # ────────────────────────────────────────────────────────────────
    # PIN TOPLAMA (mevcut mantık - userId yerine deviceId ile de çalışır)
    # ────────────────────────────────────────────────────────────────
    if data.roomName in room_permissions:
        perms = room_permissions[data.roomName]
        # collector kontrolü userId ile yapılıyor, isterseniz deviceId'ye çevirebilirsiniz
        if user_data["userId"] in perms["collectors"]:
            for pin_id, pin_data in list(pins.items()):
                if pin_data["roomName"] != data.roomName:
                    continue
                dist = calculate_distance(data.lat, data.lng, pin_data["lat"], pin_data["lng"])
                
                if dist <= 20:
                    if pin_id not in pin_collection_state:
                        pin_collection_state[pin_id] = {
                            "collector": user_data["userId"],
                            "start_time": time.time()
                        }
                elif dist > 25:
                    if pin_id in pin_collection_state:
                        if pin_collection_state[pin_id]["collector"] == user_data["userId"]:
                            score_key = f"{data.roomName}_{user_data['userId']}"
                            user_scores[score_key] = user_scores.get(score_key, 0) + 1
                            
                            hist_key = f"{data.roomName}_{user_data['userId']}"
                            if hist_key not in pin_collection_history:
                                pin_collection_history[hist_key] = []
                            
                            pin_collection_history[hist_key].append({
                                "pinId": pin_id,
                                "creator": pin_data["creator"],
                                "timestamp": get_local_time(),
                                "createdAt": pin_data.get("createdAt", "Bilinmiyor"),
                                "lat": pin_data["lat"],
                                "lng": pin_data["lng"]
                            })
                            
                            del pins[pin_id]
                            del pin_collection_state[pin_id]

    return {"status": "success"}

# ═══════════════════════════════════════════════════════════════════════════════
# 📍 KONUM LİSTESİ (character eklendi)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/get_locations/{room_name}")
async def get_locations(room_name: str, viewer_id: str = ""):
    now = time.time()
    to_delete = []

    for key, u in users_locations.items():
        if now - u.get("last_seen", 0) > USER_TIMEOUT:
            to_delete.append(key)

    for key in to_delete:
        del users_locations[key]

    locations = []
    for u in users_locations.values():
        if u.get("roomName", "Genel") != room_name:
            continue

        # görünürlük filtresi (mevcut kodunuzdaki gibi)
        visibility = user_visibility.get(u["userId"], {"mode": "all", "allowed": []})
        visible = False
        if visibility["mode"] == "all":
            visible = True
        elif visibility["mode"] == "room":
            visible = True
        elif visibility["mode"] == "hidden":
            visible = False

        if not visible and viewer_id != u["userId"]:
            continue

        locations.append({
            "deviceId": u["deviceId"],
            "userId": u["userId"],
            "deviceType": u["deviceType"],
            "lat": u["lat"],
            "lng": u["lng"],
            "altitude": u.get("altitude", 0.0),
            "speed": u.get("speed", 0.0),
            "animationType": u.get("animationType", "pulse"),
            "character": u.get("character", "🧍"),          # <--- eklendi
            "roomName": u.get("roomName", "Genel"),
            "idleStatus": u.get("idle_status", "online"),
            "idleMinutes": u.get("idle_minutes", 0)
        })

    return locations

# ═══════════════════════════════════════════════════════════════════════════════
# GERİ KALAN ENDPOINTLER (değişmeden kalabilir)
# ──────────────────────────────────────────────────────────────────────────────
# Aşağıdaki fonksiyonlar büyük oranda aynı kalıyor, sadece userId ile
# yapılan işlemlerde dikkatli olun (örneğin pin toplama yetkisi userId ile)
# ═══════════════════════════════════════════════════════════════════════════════

# ... (oda oluşturma, katılma, silme, şifre değiştirme, pin oluşturma,
#       skorlar, mesajlaşma, rota geçmişi getirme vs. fonksiyonlarınız
#       aynı şekilde kalabilir. Gerekirse onları da deviceId'ye uyarlarız)

# Örneğin get_rooms, create_room, join_room, delete_room vs. 
# mevcut halleriyle çalışmaya devam eder.

# SON
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
