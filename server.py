from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import time

app = FastAPI(title="Konum Takip Server")

# ==========================
# CORS
# ==========================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================
# VERİLER (RAM)
# ==========================
users_locations = {}
conversations = {}
read_timestamps = {}

# ==========================
# MODELLER
# ==========================

class LocationModel(BaseModel):
    userId: str
    deviceType: str = "phone"
    lat: float
    lng: float
    altitude: float = 0.0
    speed: float = 0.0
    deviceId: Optional[str] = None


class MessageModel(BaseModel):
    fromUser: str
    toUser: str
    message: str


# ==========================
# YARDIMCI
# ==========================

def get_conversation_key(user1: str, user2: str):
    return tuple(sorted([user1, user2]))


# ==========================
# ANA SAYFA
# ==========================

@app.get("/")
def home():
    total_messages = sum(len(msgs) for msgs in conversations.values())

    users = []
    for u in users_locations.values():
        users.append(
            f"{u['userId']} ({u['deviceType']}) - "
            f"{u['lat']:.5f}, {u['lng']:.5f} - "
            f"⛰️ {u.get('altitude', 0):.1f}m - "
            f"🚗 {u.get('speed', 0):.1f}km/h - "
            f"id:{u.get('deviceId', 'none')}"
        )

    return {
        "status": "✅ Server çalışıyor!",
        "toplam_kullanici": len(users_locations),
        "toplam_konusma": len(conversations),
        "toplam_mesaj": total_messages,
        "kullanicilar": users
    }


# ==========================
# KONUM GÜNCELLE
# ==========================

@app.post("/update_location")
def update_location(data: LocationModel):

    # deviceId yoksa userId ile id gibi davranır (geri uyum)
    device_id = data.deviceId if data.deviceId else data.userId

    users_locations[device_id] = {
        "userId": data.userId,
        "deviceType": data.deviceType,
        "lat": data.lat,
        "lng": data.lng,
        "altitude": data.altitude,
        "speed": data.speed,
        "deviceId": device_id,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_seen": time.time()
    }

    return {"status": "ok"}


# ==========================
# KONUM LİSTESİ
# ==========================

@app.get("/get_locations")
def get_locations():

    # ✅ 60 saniye konum yollamayanları otomatik sil
    now = time.time()
    timeout = 60  # saniye

    to_delete = []
    for uid, u in users_locations.items():
        last_seen = u.get("last_seen", 0)
        if now - last_seen > timeout:
            to_delete.append(uid)

    for uid in to_delete:
        del users_locations[uid]
        print(f"🧹 Otomatik silindi (timeout): {uid}")

    return list(users_locations.values())


# ==========================
# MESAJ GÖNDER
# ==========================

@app.post("/send_message")
def send_message(data: MessageModel):

    key = get_conversation_key(data.fromUser, data.toUser)

    if key not in conversations:
        conversations[key] = []

    conversations[key].append({
        "fromUser": data.fromUser,
        "toUser": data.toUser,
        "message": data.message,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

    return {"status": "ok"}


# ==========================
# MESAJLARI GETİR
# ==========================

@app.get("/get_messages")
def get_messages(user1: str, user2: str):

    key = get_conversation_key(user1, user2)

    msgs = conversations.get(key, [])

    return {
        "messages": msgs,
        "read": read_timestamps.get(key, None)
    }


# ==========================
# OKUNDU İŞARETLE
# ==========================

@app.get("/mark_read")
def mark_read(user1: str, user2: str):

    key = get_conversation_key(user1, user2)

    read_timestamps[key] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return {"status": "ok"}
