# ═══════════════════════════════════════════════════════════════════════════════
#                         KONUM TAKİP SERVER
# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI server - Konum, pin, mesajlaşma, oda sistemi
# Versiyon: 2.1 (Grup Mesajlaşma + Emoji Karakter + Akıllı Zamanlama)
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
# 📦 KÜTÜPHANE İMPORTLARI
# ═══════════════════════════════════════════════════════════════════════════════

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
from math import radians, sin, cos, sqrt, atan2
import pytz
import uuid

# ═══════════════════════════════════════════════════════════════════════════════
# ⚙️ UYGULAMA BAŞLATMA
# ═══════════════════════════════════════════════════════════════════════════════

app = FastAPI(title="Konum Takip API", version="2.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════════════════════════════════════
# 💾 VERİ SAKLAMASI (RAM)
# ═══════════════════════════════════════════════════════════════════════════════

locations = {}            # userId → konum verisi
location_history = {}     # deviceId → rota geçmişi listesi (isimden bağımsız!)
device_to_user = {}       # deviceId → güncel userId (isim takibi için)
user_to_device = {}       # userId → deviceId (hızlı lookup)
rooms = {}                # roomName → oda bilgisi
scores = {}               # "roomName_userId" → skor
pin_collection_history = {}  # "roomName_userId" → toplama geçmişi
pins = {}                 # pinId → pin verisi
messages = {}             # "fromUser_toUser" → mesaj listesi (1-1)
room_messages = {}        # roomName → grup mesaj listesi (GRUP)
visibility_settings = {}  # userId → görünürlük ayarı

# ═══════════════════════════════════════════════════════════════════════════════
# 🎛️ SİSTEM AYARLARI
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_TIMEZONE = pytz.timezone('Europe/Istanbul')
USER_TIMEOUT = 120          # Kullanıcı timeout (saniye)
IDLE_THRESHOLD = 15         # Hareketsizlik eşiği (metre)
IDLE_TIME_MINUTES = 15      # Hareketsizlik süresi (dakika)

# Hız eşikleri (km/h)
SPEED_VEHICLE = 30
SPEED_RUN = 15
SPEED_WALK = 3

# Rota örnekleme mesafeleri (metre)
MIN_DIST_VEHICLE = 50
MIN_DIST_RUN = 20
MIN_DIST_WALK = 10
MIN_DIST_IDLE = 5

# Rota limitleri
MAX_POINTS_PER_USER = 5000
MAX_HISTORY_DAYS = 90

# Pin toplama mesafeleri (metre)
PIN_COLLECT_START = 20
PIN_COLLECT_END = 25

# Grup mesaj limiti
MAX_ROOM_MESSAGES = 200

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

# ═══════════════════════════════════════════════════════════════════════════════
# 🏠 ANA SAYFA VE SAĞLIK KONTROLÜ
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/")
def root():
    online_count = sum(1 for u in locations.values()
                      if is_user_online(u.get("lastSeen", "")))
    return {
        "status": "✅ Server çalışıyor",
        "time": get_local_time(),
        "online_users": online_count,
        "total_rooms": len(rooms),
        "total_pins": len(pins),
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
    }
    return {"message": f"✅ {data.roomName} odası oluşturuldu"}

@app.post("/join_room")
def join_room(data: JoinRoomModel):
    if data.roomName == "Genel":
        return {"message": "Genel odaya katıldınız"}
    if data.roomName not in rooms:
        raise HTTPException(status_code=404, detail="Oda bulunamadı!")
    if rooms[data.roomName]["password"] != data.password:
        raise HTTPException(status_code=401, detail="Yanlış şifre!")
    return {"message": f"✅ {data.roomName} odasına katıldınız"}

@app.get("/get_rooms")
def get_rooms(user_id: str = ""):
    result = [
        {
            "name": "Genel",
            "hasPassword": False,
            "userCount": sum(1 for u in locations.values()
                           if u.get("roomName") == "Genel"
                           and is_user_online(u.get("lastSeen", ""))),
            "createdBy": "system",
            "isAdmin": False,
            "password": None,
        }
    ]
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

# ═══════════════════════════════════════════════════════════════════════════════
# 👑 ADMİN FONKSİYONLARI
# ═══════════════════════════════════════════════════════════════════════════════

@app.delete("/delete_room/{room_name}")
def delete_room(room_name: str, admin_id: str):
    if room_name not in rooms:
        raise HTTPException(status_code=404, detail="Oda bulunamadı!")
    if rooms[room_name]["createdBy"] != admin_id:
        raise HTTPException(status_code=403, detail="Sadece admin silebilir!")
    del rooms[room_name]
    # Üyeleri Genel'e taşı
    for uid in locations:
        if locations[uid].get("roomName") == room_name:
            locations[uid]["roomName"] = "Genel"
    # Pinleri sil
    for pin_id in list(pins.keys()):
        if pins[pin_id].get("roomName") == room_name:
            del pins[pin_id]
    # Skorları sil
    for key in list(scores.keys()):
        if key.startswith(f"{room_name}_"):
            del scores[key]
    # Grup mesajlarını sil
    if room_name in room_messages:
        del room_messages[room_name]
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

@app.get("/get_room_permissions/{room_name}")
def get_room_permissions(room_name: str):
    if room_name == "Genel":
        return {"admin": None, "collectors": []}
    if room_name not in rooms:
        return {"admin": None, "collectors": []}
    return {
        "admin": rooms[room_name]["createdBy"],
        "collectors": rooms[room_name].get("collectors", []),
    }

@app.post("/set_collector_permission/{room_name}/{target_user}")
def set_collector_permission(room_name: str, target_user: str,
                              admin_id: str, enabled: bool):
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

# ═══════════════════════════════════════════════════════════════════════════════
# 👁️ GÖRÜNÜRLİK SİSTEMİ
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/set_visibility")
def set_visibility(data: VisibilityModel):
    visibility_settings[data.userId] = {
        "mode": data.mode,
        "allowed": data.allowed,
    }
    return {"message": "✅ Görünürlük güncellendi"}

# ═══════════════════════════════════════════════════════════════════════════════
# 📍 KONUM GÜNCELLEMESİ (ANA FONKSİYON)
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/update_location")
def update_location(data: LocationModel):
    uid = data.userId
    now = get_local_time()

    # 1️⃣ HAREKETSİZLİK KONTROLÜ
    idle_status = "online"
    idle_minutes = 0
    if uid in locations:
        old = locations[uid]
        dist = haversine(old["lat"], old["lng"], data.lat, data.lng)
        if dist < IDLE_THRESHOLD:
            # Hareket yok, idle süresini artır
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

    # 2️⃣ ROTA GEÇMİŞİNE EKLE — deviceId bazlı (isim değişse de rota korunur)
    route_key = data.deviceId if data.deviceId else uid  # deviceId yoksa userId fallback
    # deviceId ↔ userId eşlemesini güncelle
    if data.deviceId:
        device_to_user[data.deviceId] = uid
        user_to_device[uid] = data.deviceId

    should_add = False
    if route_key not in location_history:
        location_history[route_key] = []
        should_add = True
    else:
        history = location_history[route_key]
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
        location_history[route_key].append({
            "lat": data.lat,
            "lng": data.lng,
            "timestamp": now,
            "speed": data.speed,
        })
        cleanup_old_routes()

    # 3️⃣ PIN TOPLAMA SİSTEMİ
    if uid in locations:
        room = data.roomName
        can_collect = False
        if room in rooms:
            can_collect = uid in rooms[room].get("collectors", [])

        if can_collect:
            for pin_id, pin in list(pins.items()):
                if pin.get("roomName") != room:
                    continue
                if pin.get("creator") == uid:
                    continue

                pin_dist = haversine(data.lat, data.lng, pin["lat"], pin["lng"])

                if pin_dist <= PIN_COLLECT_START:
                    if pin.get("collectorId") is None:
                        pins[pin_id]["collectorId"] = uid
                        pins[pin_id]["collectionStart"] = now
                        pins[pin_id]["collectionTime"] = 0
                    elif pin.get("collectorId") == uid:
                        try:
                            start = datetime.strptime(
                                pin["collectionStart"], "%Y-%m-%d %H:%M:%S")
                            start = DEFAULT_TIMEZONE.localize(start)
                            now_dt = datetime.now(DEFAULT_TIMEZONE)
                            elapsed = int((now_dt - start).total_seconds())
                            pins[pin_id]["collectionTime"] = elapsed
                        except:
                            pass

                elif pin_dist > PIN_COLLECT_END and pin.get("collectorId") == uid:
                    # Pin toplandı!
                    score_key = f"{room}_{uid}"
                    scores[score_key] = scores.get(score_key, 0) + 1

                    history_key = f"{room}_{uid}"
                    if history_key not in pin_collection_history:
                        pin_collection_history[history_key] = []
                    pin_collection_history[history_key].append({
                        "timestamp": now,
                        "createdAt": pin.get("createdAt", "Bilinmiyor"),
                        "creator": pin.get("creator", ""),
                        "lat": pin["lat"],
                        "lng": pin["lng"],
                    })
                    del pins[pin_id]

    # 4️⃣ KONUMU GÜNCELLE
    locations[uid] = {
        "userId": uid,
        "deviceId": data.deviceId,
        "deviceType": data.deviceType,
        "lat": data.lat,
        "lng": data.lng,
        "altitude": data.altitude,
        "speed": data.speed,
        "animationType": data.animationType,
        "roomName": data.roomName,
        "character": data.character,
        "lastSeen": now,
        "idleStatus": idle_status,
        "idleMinutes": idle_minutes,
        "idleStart": idle_start,
    }

    return {"status": "ok", "time": now}

# ═══════════════════════════════════════════════════════════════════════════════
# 📍 KONUM LİSTESİ VE GEÇMİŞ
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/get_locations/{room_name}")
def get_locations(room_name: str, viewer_id: str = ""):
    result = []
    for uid, data in locations.items():
        if uid == viewer_id:
            continue
        if not is_user_online(data.get("lastSeen", "")):
            continue
        if data.get("roomName") != room_name:
            continue

        vis = visibility_settings.get(uid, {"mode": "all"})
        if vis["mode"] == "hidden":
            continue
        if vis["mode"] == "room":
            viewer_room = locations.get(viewer_id, {}).get("roomName", "Genel")
            if viewer_room != data.get("roomName"):
                continue

        result.append({
            "userId": uid,
            "deviceId": data.get("deviceId", ""),
            "lat": data["lat"],
            "lng": data["lng"],
            "deviceType": data.get("deviceType", "phone"),
            "altitude": data.get("altitude", 0),
            "speed": data.get("speed", 0),
            "animationType": data.get("animationType", "pulse"),
            "roomName": data.get("roomName", "Genel"),
            "idleStatus": data.get("idleStatus", "online"),
            "idleMinutes": data.get("idleMinutes", 0),
            "character": data.get("character", "🧍"),
        })
    return result

@app.get("/get_location_history/{user_id}")
def get_location_history(user_id: str, period: str = "all"):
    # Önce deviceId ile ara (isim değişse de rota erişilebilir)
    device_id = user_to_device.get(user_id)
    route_key = device_id if device_id and device_id in location_history else user_id
    history = location_history.get(route_key, [])
    if period == "all":
        return history
    now = datetime.now(DEFAULT_TIMEZONE)
    if period == "day":
        cutoff = now - timedelta(days=1)
    elif period == "week":
        cutoff = now - timedelta(weeks=1)
    elif period == "month":
        cutoff = now - timedelta(days=30)
    elif period == "year":
        cutoff = now - timedelta(days=365)
    else:
        return history
    return [
        p for p in history
        if datetime.strptime(p["timestamp"], "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=DEFAULT_TIMEZONE) > cutoff
    ]

@app.delete("/clear_history/{user_id}")
def clear_history(user_id: str):
    device_id = user_to_device.get(user_id)
    route_key = device_id if device_id and device_id in location_history else user_id
    if route_key in location_history:
        location_history[route_key] = []
    return {"message": "✅ Geçmiş temizlendi"}

# ═══════════════════════════════════════════════════════════════════════════════
# 📍 PIN SİSTEMİ
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/create_pin")
def create_pin(data: PinModel):
    for pin in pins.values():
        if pin["creator"] == data.creator and pin["roomName"] == data.roomName:
            raise HTTPException(status_code=400,
                detail="Zaten bir pininiz var! Önce kaldırın.")
    pin_id = str(uuid.uuid4())[:8]
    pins[pin_id] = {
        "id": pin_id,
        "roomName": data.roomName,
        "creator": data.creator,
        "lat": data.lat,
        "lng": data.lng,
        "createdAt": get_local_time(),
        "collectorId": None,
        "collectionStart": None,
        "collectionTime": 0,
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

# ═══════════════════════════════════════════════════════════════════════════════
# 🔑 YETKİ VE SKOR SİSTEMİ
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/get_scores/{room_name}")
def get_scores(room_name: str):
    result = []
    for key, score in scores.items():
        if key.startswith(f"{room_name}_"):
            uid = key[len(f"{room_name}_"):]
            result.append({"userId": uid, "score": score})
    result.sort(key=lambda x: x["score"], reverse=True)
    return result

@app.get("/get_collection_history/{room_name}/{user_id}")
def get_collection_history(room_name: str, user_id: str):
    key = f"{room_name}_{user_id}"
    return pin_collection_history.get(key, [])

# ═══════════════════════════════════════════════════════════════════════════════
# 💬 1-1 MESAJLAŞMA SİSTEMİ
# ═══════════════════════════════════════════════════════════════════════════════

def get_conv_key(user1: str, user2: str) -> str:
    return "_".join(sorted([user1, user2]))

@app.post("/send_message")
def send_message(data: MessageModel):
    key = get_conv_key(data.fromUser, data.toUser)
    if key not in messages:
        messages[key] = []
    messages[key].append({
        "from": data.fromUser,
        "to": data.toUser,
        "message": data.message,
        "timestamp": get_local_time(),
        "read": False,
    })
    return {"message": "✅ Mesaj gönderildi"}

@app.get("/get_conversation/{user1}/{user2}")
def get_conversation(user1: str, user2: str):
    key = get_conv_key(user1, user2)
    return messages.get(key, [])

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
    for key, conv in messages.items():
        for msg in conv:
            if msg["to"] == user_id and not msg["read"]:
                sender = msg["from"]
                result[sender] = result.get(sender, 0) + 1
    return result

# ═══════════════════════════════════════════════════════════════════════════════
# 👥 GRUP MESAJLAŞMA SİSTEMİ
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/send_room_message")
def send_room_message(data: RoomMessageModel):
    """Odaya grup mesajı gönder"""
    room = data.roomName

    # Oda kontrolü (Genel dahil)
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

    # Eski mesajları temizle
    if len(room_messages[room]) > MAX_ROOM_MESSAGES:
        room_messages[room] = room_messages[room][-MAX_ROOM_MESSAGES:]

    return {"message": "✅ Grup mesajı gönderildi"}

@app.get("/get_room_messages/{room_name}")
def get_room_messages(room_name: str, limit: int = 50):
    """Oda grup mesajlarını getir"""
    msgs = room_messages.get(room_name, [])
    return msgs[-limit:]  # Son N mesajı döndür

@app.get("/get_room_messages_since/{room_name}")
def get_room_messages_since(room_name: str, last_id: str = ""):
    """Son mesaj ID'sinden sonrakileri getir (polling için)"""
    msgs = room_messages.get(room_name, [])
    if not last_id:
        return msgs[-50:]
    # Son ID'den sonrakileri bul
    for i, msg in enumerate(msgs):
        if msg["id"] == last_id:
            return msgs[i+1:]
    # last_id bulunamadı — boş döndür (duplicate önleme)
    return []

# ═══════════════════════════════════════════════════════════════════════════════
# 👤 KULLANICI ADI DEĞİŞTİRME
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/change_username")
def change_username(data: ChangeUsernameModel):
    old = data.oldName
    new = data.newName.strip()
    device_id = data.deviceId

    if not new or len(new) < 1:
        raise HTTPException(status_code=400, detail="İsim boş olamaz!")

    if old == new:
        return {"message": "✅ İsim aynı, değişiklik yok"}

    # İsim başka cihaz tarafından kullanılıyorsa engelle
    if new in locations:
        existing_device = locations[new].get("deviceId", "")
        if existing_device != device_id:
            raise HTTPException(status_code=400, detail="Bu isim zaten kullanımda!")

    # Konum verisini taşı
    if old in locations:
        locations[new] = locations.pop(old)
        locations[new]["userId"] = new

    # deviceId ↔ userId eşlemesini güncelle (rota deviceId'ye bağlı kalır)
    if device_id:
        device_to_user[device_id] = new
        user_to_device[new] = device_id
        if old in user_to_device:
            del user_to_device[old]
    else:
        if old in location_history and new not in location_history:
            location_history[new] = location_history.pop(old)

    # Oda üyeliği + admin yetkisini yeni isme taşı
    for room_name, room in rooms.items():
        if room.get("createdBy") == old:
            rooms[room_name]["createdBy"] = new
        collectors = room.get("collectors", [])
        if old in collectors:
            collectors.remove(old)
            if new not in collectors:
                collectors.append(new)
            rooms[room_name]["collectors"] = collectors

    # Skorları taşı (birleştirerek)
    for key in list(scores.keys()):
        if key.endswith(f"_{old}"):
            room = key[:-(len(old)+1)]
            new_key = f"{room}_{new}"
            scores[new_key] = scores.get(new_key, 0) + scores.pop(key)

    # Pin toplama geçmişini taşı
    for key in list(pin_collection_history.keys()):
        if key.endswith(f"_{old}"):
            room = key[:-(len(old)+1)]
            new_key = f"{room}_{new}"
            existing = pin_collection_history.get(new_key, [])
            pin_collection_history[new_key] = existing + pin_collection_history.pop(key)

    # Aktif pinleri güncelle
    for pin in pins.values():
        if pin.get("creator") == old:
            pin["creator"] = new
        if pin.get("collectorId") == old:
            pin["collectorId"] = new

    return {"message": f"✅ İsim değiştirildi: {old} → {new}"}




# ═══════════════════════════════════════════════════════════════════════════════
# 📻 WALKİE-TALKİE SİSTEMİ (BAS KONUŞ)
# ═══════════════════════════════════════════════════════════════════════════════

room_walkie = {}    # roomName → {id, from, audioBase64, timestamp}
p2p_walkie = {}     # "user1_user2" → {id, from, audioBase64, timestamp}

class RoomWalkieModel(BaseModel):
    roomName: str
    fromUser: str
    audioBase64: str

class P2pWalkieModel(BaseModel):
    fromUser: str
    toUser: str
    audioBase64: str

@app.post("/room_walkie_send")
def room_walkie_send(data: RoomWalkieModel):
    """Odaya walkie ses gönder"""
    room = data.roomName
    if room != "Genel" and room not in rooms:
        raise HTTPException(status_code=404, detail="Oda bulunamadı!")
    room_walkie[room] = {
        "id": str(uuid.uuid4())[:8],
        "from": data.fromUser,
        "audioBase64": data.audioBase64,
        "timestamp": get_local_time(),
    }
    return {"message": "✅ Walkie gönderildi", "id": room_walkie[room]["id"]}

@app.get("/room_walkie_listen/{room_name}")
def room_walkie_listen(room_name: str, user_id: str = "", last_id: str = ""):
    """Odadan walkie ses al — kendinin sesini dışla"""
    data = room_walkie.get(room_name)
    if not data:
        return {"hasAudio": False}
    # Kendi sesi veya zaten dinlenmiş
    if data["from"] == user_id or data["id"] == last_id:
        return {"hasAudio": False}
    # 10 saniyeden eski sesi gönderme
    try:
        ts = datetime.strptime(data["timestamp"], "%Y-%m-%d %H:%M:%S")
        ts = DEFAULT_TIMEZONE.localize(ts)
        if (datetime.now(DEFAULT_TIMEZONE) - ts).total_seconds() > 10:
            return {"hasAudio": False}
    except:
        pass
    return {
        "hasAudio": True,
        "id": data["id"],
        "from": data["from"],
        "audioBase64": data["audioBase64"],
    }

@app.post("/walkie_send")
def walkie_send(data: P2pWalkieModel):
    """1-1 walkie ses gönder"""
    key = "_".join(sorted([data.fromUser, data.toUser]))
    p2p_walkie[key] = {
        "id": str(uuid.uuid4())[:8],
        "from": data.fromUser,
        "to": data.toUser,
        "audioBase64": data.audioBase64,
        "timestamp": get_local_time(),
    }
    return {"message": "✅ Walkie gönderildi", "id": p2p_walkie[key]["id"]}

@app.get("/walkie_listen/{user_id}/{target}")
def walkie_listen(user_id: str, target: str, last_id: str = ""):
    """1-1 walkie ses al"""
    key = "_".join(sorted([user_id, target]))
    data = p2p_walkie.get(key)
    if not data:
        return {"hasAudio": False}
    # Kendi sesi veya zaten dinlenmiş
    if data["from"] == user_id or data["id"] == last_id:
        return {"hasAudio": False}
    # 10 saniyeden eski sesi gönderme
    try:
        ts = datetime.strptime(data["timestamp"], "%Y-%m-%d %H:%M:%S")
        ts = DEFAULT_TIMEZONE.localize(ts)
        if (datetime.now(DEFAULT_TIMEZONE) - ts).total_seconds() > 10:
            return {"hasAudio": False}
    except:
        pass
    return {
        "hasAudio": True,
        "id": data["id"],
        "from": data["from"],
        "audioBase64": data["audioBase64"],
    }

# ═══════════════════════════════════════════════════════════════════════════════
# 🎤 SES MESAJI SİSTEMİ
# ═══════════════════════════════════════════════════════════════════════════════

voice_messages = {}       # voiceId → ses verisi (oda grup mesajları için)
voice_dm_messages = {}    # voiceId → ses verisi (1-1 mesajlar için)

class RoomVoiceModel(BaseModel):
    roomName: str
    fromUser: str
    audioBase64: str
    durationSeconds: float = 0.0

class VoiceDmModel(BaseModel):
    fromUser: str
    toUser: str
    audioBase64: str
    durationSeconds: float = 0.0

@app.post("/send_room_voice_message")
def send_room_voice_message(data: RoomVoiceModel):
    """Oda grup sesli mesajı gönder"""
    room = data.roomName
    if room != "Genel" and room not in rooms:
        raise HTTPException(status_code=404, detail="Oda bulunamadı!")
    if room not in room_messages:
        room_messages[room] = []

    voice_id = str(uuid.uuid4())[:12]
    voice_messages[voice_id] = {
        "audioBase64": data.audioBase64,
        "durationSeconds": data.durationSeconds,
        "from": data.fromUser,
        "timestamp": get_local_time(),
    }
    room_messages[room].append({
        "id": str(uuid.uuid4())[:8],
        "from": data.fromUser,
        "message": "",
        "type": "voice",
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
    """Oda ses verisini getir"""
    if voice_id not in voice_messages:
        raise HTTPException(status_code=404, detail="Ses mesajı bulunamadı!")
    return voice_messages[voice_id]

@app.post("/send_voice_message")
def send_voice_message(data: VoiceDmModel):
    """1-1 sesli mesaj gönder"""
    key = "_".join(sorted([data.fromUser, data.toUser]))
    if key not in messages:
        messages[key] = []

    voice_id = str(uuid.uuid4())[:12]
    voice_dm_messages[voice_id] = {
        "audioBase64": data.audioBase64,
        "durationSeconds": data.durationSeconds,
        "from": data.fromUser,
        "timestamp": get_local_time(),
    }
    messages[key].append({
        "from": data.fromUser,
        "to": data.toUser,
        "message": "",
        "type": "voice",
        "voiceId": voice_id,
        "durationSeconds": data.durationSeconds,
        "timestamp": get_local_time(),
        "read": False,
    })
    return {"message": "✅ Sesli mesaj gönderildi", "voiceId": voice_id}

@app.get("/get_voice_message/{voice_id}")
def get_voice_message(voice_id: str):
    """1-1 ses verisini getir"""
    if voice_id not in voice_dm_messages:
        raise HTTPException(status_code=404, detail="Ses mesajı bulunamadı!")
    return voice_dm_messages[voice_id]


# ═══════════════════════════════════════════════════════════════════════════════
# 👑 MASTER ADMİN SİSTEMİ
# ═══════════════════════════════════════════════════════════════════════════════

MASTER_PASSWORD = "Yürü.0131"
master_admins = set()  # Aktif master admin cihaz ID'leri

def is_master(device_id: str) -> bool:
    return device_id in master_admins

@app.post("/master_login")
def master_login(device_id: str, password: str):
    if password != MASTER_PASSWORD:
        raise HTTPException(status_code=403, detail="Yanlış şifre!")
    master_admins.add(device_id)
    return {"message": "✅ Master admin girişi başarılı"}

@app.post("/master_logout")
def master_logout(device_id: str):
    master_admins.discard(device_id)
    return {"message": "✅ Çıkış yapıldı"}

@app.get("/master_status")
def master_status(device_id: str):
    return {"isMaster": is_master(device_id)}

@app.get("/master_get_all_users")
def master_get_all_users(device_id: str):
    if not is_master(device_id):
        raise HTTPException(status_code=403, detail="Yetkisiz!")
    result = []
    for uid, data in locations.items():
        result.append({
            "userId": uid,
            "deviceId": data.get("deviceId", ""),
            "deviceType": data.get("deviceType", "phone"),
            "roomName": data.get("roomName", "Genel"),
            "lastSeen": data.get("lastSeen", ""),
            "isOnline": is_user_online(data.get("lastSeen", "")),
            "isMasterAdmin": data.get("deviceId", "") in master_admins,
        })
    return result

@app.get("/master_get_all_rooms")
def master_get_all_rooms(device_id: str):
    if not is_master(device_id):
        raise HTTPException(status_code=403, detail="Yetkisiz!")
    result = [{"name": "Genel", "hasPassword": False, "createdBy": "system",
               "userCount": sum(1 for u in locations.values() if u.get("roomName") == "Genel" and is_user_online(u.get("lastSeen",""))),
               "password": None}]
    for name, room in rooms.items():
        result.append({
            "name": name,
            "hasPassword": True,
            "password": room["password"],
            "createdBy": room["createdBy"],
            "userCount": sum(1 for u in locations.values() if u.get("roomName") == name and is_user_online(u.get("lastSeen",""))),
        })
    return result

@app.delete("/master_delete_room/{room_name}")
def master_delete_room(room_name: str, device_id: str):
    if not is_master(device_id):
        raise HTTPException(status_code=403, detail="Yetkisiz!")
    if room_name not in rooms:
        raise HTTPException(status_code=404, detail="Oda bulunamadı!")
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
    return {"message": f"✅ {room_name} silindi"}

@app.delete("/master_kick_user/{user_id}")
def master_kick_user(user_id: str, device_id: str):
    if not is_master(device_id):
        raise HTTPException(status_code=403, detail="Yetkisiz!")
    if user_id in locations:
        del locations[user_id]
    if user_id in location_history:
        del location_history[user_id]
    if user_id in user_to_device:
        did = user_to_device.pop(user_id)
        device_to_user.pop(did, None)
        master_admins.discard(did)
    return {"message": f"✅ {user_id} sunucudan atıldı"}

@app.get("/master_get_room_password/{room_name}")
def master_get_room_password(room_name: str, device_id: str):
    if not is_master(device_id):
        raise HTTPException(status_code=403, detail="Yetkisiz!")
    if room_name not in rooms:
        raise HTTPException(status_code=404, detail="Oda bulunamadı!")
    return {"password": rooms[room_name]["password"]}

@app.post("/master_set_collector/{room_name}/{target_user}")
def master_set_collector(room_name: str, target_user: str, device_id: str, enabled: bool):
    if not is_master(device_id):
        raise HTTPException(status_code=403, detail="Yetkisiz!")
    if room_name not in rooms:
        raise HTTPException(status_code=404, detail="Oda bulunamadı!")
    collectors = rooms[room_name].get("collectors", [])
    if enabled and target_user not in collectors:
        collectors.append(target_user)
    elif not enabled and target_user in collectors:
        collectors.remove(target_user)
    rooms[room_name]["collectors"] = collectors
    return {"message": "✅ Yetki güncellendi"}

@app.delete("/master_clear_all")
def master_clear_all(device_id: str):
    if not is_master(device_id):
        raise HTTPException(status_code=403, detail="Yetkisiz!")
    locations.clear(); location_history.clear(); pins.clear()
    scores.clear(); pin_collection_history.clear()
    messages.clear(); room_messages.clear()
    voice_messages.clear(); voice_dm_messages.clear()
    room_walkie.clear(); p2p_walkie.clear()
    rooms.clear()
    return {"message": "✅ Tüm veriler temizlendi"}

# ═══════════════════════════════════════════════════════════════════════════════
# 🔧 YÖNETİM FONKSİYONLARI
# ═══════════════════════════════════════════════════════════════════════════════

@app.delete("/remove_user/{user_id}")
def remove_user(user_id: str):
    if user_id in locations:
        del locations[user_id]
    return {"message": f"✅ {user_id} silindi"}

@app.delete("/clear")
def clear_all():
    locations.clear()
    location_history.clear()
    pins.clear()
    scores.clear()
    pin_collection_history.clear()
    messages.clear()
    room_messages.clear()
    voice_messages.clear()
    voice_dm_messages.clear()
    room_walkie.clear()
    p2p_walkie.clear()
    return {"message": "✅ Tüm veriler silindi"}
