from fastapi import FastAPI, HTTPException
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
    speed: float = 0.0  # ✅ km/h cinsinden hız

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
            f"🚗 {u.get('speed', 0):.1f}km/h"  # ✅ Hız eklendi
        )
    return {
        "status": "✅ Server çalışıyor!",
        "toplam_kullanici": len(users_locations),
        "toplam_konusma": len(conversations),
        "toplam_mesaj": total_messages,
        "kullanicilar": users
    }

@app.get("/ping")
def ping():
    return {"status": "alive"}

# ==========================
# KONUM GÜNCELLE
# ==========================
@app.post("/update_location")
def update_location(data: LocationModel):
    try:
        users_locations[data.userId] = {
            "userId": data.userId,
            "deviceType": data.deviceType,
            "lat": data.lat,
            "lng": data.lng,
            "altitude": data.altitude,
            "speed": data.speed,  # ✅ Hız kaydet
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "last_seen": time.time()
        }
        
        print(f"✅ Konum: {data.userId} ({data.deviceType})")
        print(f"   📍 {data.lat:.5f}, {data.lng:.5f}  ⛰️ {data.altitude:.1f}m  🚗 {data.speed:.1f}km/h")
        
        return {"status": "success"}
    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==========================
# KONUM LİSTESİ
# ==========================
@app.get("/get_locations")
def get_locations():
    try:
        now = time.time()
        timeout = 120
        to_delete = []
        
        for uid, u in users_locations.items():
            last_seen = u.get("last_seen", 0)
            if now - last_seen > timeout:
                to_delete.append(uid)
        
        for uid in to_delete:
            del users_locations[uid]
            print(f"🧹 Otomatik silindi (timeout): {uid}")
        
        locations = [
            {
                "userId": u["userId"],
                "deviceType": u["deviceType"],
                "lat": u["lat"],
                "lng": u["lng"],
                "altitude": u.get("altitude", 0.0),
                "speed": u.get("speed", 0.0),  # ✅ Hız gönder
            }
            for u in users_locations.values()
        ]
        
        return locations
    except Exception as e:
        print(f"❌ Hata: {e}")
        return []

# ==========================
# MESAJ GÖNDER
# ==========================
@app.post("/send_message")
def send_message(data: MessageModel):
    try:
        key = get_conversation_key(data.fromUser, data.toUser)
        if key not in conversations:
            conversations[key] = []
        
        conversations[key].append({
            "from": data.fromUser,
            "to": data.toUser,
            "message": data.message,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "read": False
        })
        
        print(f"💬 Mesaj: {data.fromUser} → {data.toUser}: {data.message}")
        return {"status": "success"}
    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==========================
# MESAJLARI GETİR
# ==========================
@app.get("/get_conversation/{user1}/{user2}")
def get_conversation(user1: str, user2: str):
    try:
        key = get_conversation_key(user1, user2)
        msgs = conversations.get(key, [])
        print(f"💬 Konuşma: {user1} ↔ {user2}  ({len(msgs)} mesaj)")
        return msgs
    except Exception as e:
        print(f"❌ Hata: {e}")
        return []

# ==========================
# OKUNDU İŞARETLE
# ==========================
@app.post("/mark_as_read/{reader}/{other_user}")
def mark_as_read(reader: str, other_user: str):
    try:
        key = get_conversation_key(reader, other_user)
        if key in conversations:
            for msg in conversations[key]:
                if msg["to"] == reader:
                    msg["read"] = True
        
        read_timestamps[key] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"👁️ Okundu: {reader} ← {other_user}")
        return {"status": "success"}
    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==========================
# OKUNMAYAN MESAJ SAYISI
# ==========================
@app.get("/get_unread_count/{user_id}")
def get_unread_count(user_id: str):
    try:
        counts = {}
        for key, msgs in conversations.items():
            if user_id in key:
                other = key[1] if key[0] == user_id else key[0]
                unread = sum(
                    1 for m in msgs 
                    if m["to"] == user_id and not m.get("read", False)
                )
                if unread > 0:
                    counts[other] = unread
        return counts
    except Exception as e:
        print(f"❌ Hata: {e}")
        return {}

# ==========================
# TEMİZLE
# ==========================
@app.post("/clear")
def clear_all():
    users_locations.clear()
    conversations.clear()
    read_timestamps.clear()
    print("🧹 Tüm veriler temizlendi")
    return {"status": "success"}

# ==========================
# KULLANICI SİL
# ==========================
@app.delete("/remove_user/{user_id}")
def remove_user(user_id: str):
    if user_id in users_locations:
        del users_locations[user_id]
        print(f"🗑️ Kullanıcı silindi: {user_id}")
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
