from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import os

app = FastAPI(title="Konum Takip Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Veriler
# 🔥 ARTIK KEY = deviceId
users_locations = {}   # deviceId -> location data
conversations = {}     # (user1, user2) -> messages
read_timestamps = {}

# ==========================
# MODELLER
# ==========================

class LocationModel(BaseModel):
    deviceId: str                 # ✅ YENİ
    userId: str
    deviceType: str = "phone"
    lat: float
    lng: float
    altitude: float = 0.0
    speed: float = 0.0            # ✅ hız ekledik (istersen kullanırsın)

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

    users = [
        f"{u['userId']} ({u['deviceType']}) - "
        f"{u['lat']:.5f}, {u['lng']:.5f} - "
        f"⛰️ {u.get('altitude', 0):.1f}m - "
        f"🏃 {u.get('speed', 0):.1f} m/s"
        for u in users_locations.values()
    ]

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
# KONUM
# ==========================

@app.post("/update_location")
def update_location(data: LocationModel):
    try:
        # 🔥 KEY = deviceId
        users_locations[data.deviceId] = {
            "deviceId":   data.deviceId,
            "userId":     data.userId,
            "deviceType": data.deviceType,
            "lat":        data.lat,
            "lng":        data.lng,
            "altitude":   data.altitude,
            "speed":      data.speed,
            "timestamp":  datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        print(f"✅ Konum: {data.userId} ({data.deviceType}) [{data.deviceId}]")
        print(f"   📍 {data.lat:.5f}, {data.lng:.5f}  ⛰️ {data.altitude:.1f} m  🏃 {data.speed:.2f} m/s")
        print("-" * 50)

        return {"status": "success"}

    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get_locations")
def get_locations():
    try:
        locations = [
            {
                "deviceId":   d["deviceId"],
                "userId":     d["userId"],
                "deviceType": d["deviceType"],
                "lat":        d["lat"],
                "lng":        d["lng"],
                "altitude":   d.get("altitude", 0.0),
                "speed":      d.get("speed", 0.0),
            }
            for d in users_locations.values()
        ]

        print(f"📡 Konum isteği → {len(locations)} kullanıcı")
        for loc in locations:
            print(
                f"   - {loc['userId']} ({loc['deviceType']}): "
                f"{loc['lat']:.5f}, {loc['lng']:.5f}  ⛰️ {loc['altitude']:.1f} m  🏃 {loc['speed']:.2f} m/s"
            )
        print("-" * 50)

        return locations

    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==========================
# MESAJLAŞMA
# ==========================

@app.post("/send_message")
def send_message(data: MessageModel):
    try:
        conv_key = get_conversation_key(data.fromUser, data.toUser)
        if conv_key not in conversations:
            conversations[conv_key] = []

        conversations[conv_key].append({
            "from":      data.fromUser,
            "to":        data.toUser,
            "message":   data.message,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "read":      False
        })

        print(f"💬 Mesaj: {data.fromUser} → {data.toUser}: {data.message}")
        print("-" * 50)
        return {"status": "success"}

    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get_conversation/{user1}/{user2}")
def get_conversation(user1: str, user2: str):
    try:
        conv_key = get_conversation_key(user1, user2)
        messages = conversations.get(conv_key, [])
        print(f"💬 Konuşma: {user1} ↔ {user2}  ({len(messages)} mesaj)")
        print("-" * 50)
        return messages

    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/mark_as_read/{reader}/{other_user}")
def mark_as_read(reader: str, other_user: str):
    try:
        conv_key = get_conversation_key(reader, other_user)
        if conv_key in conversations:
            for msg in conversations[conv_key]:
                if msg["to"] == reader:
                    msg["read"] = True

        if reader not in read_timestamps:
            read_timestamps[reader] = {}
        read_timestamps[reader][other_user] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        print(f"👁️ Okundu: {reader} ← {other_user}")
        print("-" * 50)
        return {"status": "success"}

    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get_unread_count/{user_id}")
def get_unread_count(user_id: str):
    try:
        unread_users = {}
        for conv_key, messages in conversations.items():
            if user_id in conv_key:
                other_user = conv_key[0] if conv_key[1] == user_id else conv_key[1]
                count = sum(
                    1 for msg in messages
                    if msg["to"] == user_id and not msg.get("read", False)
                )
                if count > 0:
                    unread_users[other_user] = count
        return unread_users

    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==========================
# YARDIMCI
# ==========================

@app.post("/clear")
def clear_all():
    users_locations.clear()
    conversations.clear()
    read_timestamps.clear()
    print("🧹 Tüm veriler temizlendi")
    return {"status": "success"}


@app.delete("/remove_user/{user_id}")
def remove_user(user_id: str):
    # ❗ artık userId ile silmek tam doğru değil
    # ama yine de destek verelim: userId eşleşen deviceId'yi bulup silelim
    to_delete = None
    for deviceId, data in users_locations.items():
        if data.get("userId") == user_id:
            to_delete = deviceId
            break

    if to_delete:
        del users_locations[to_delete]
        print(f"🗑️ Kullanıcı silindi: {user_id} (deviceId={to_delete})")
        return {"status": "success"}

    raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")


# ==========================
# BAŞLAT
# ==========================

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    print("=" * 50)
    print("🚀 Konum Takip Server Başlatılıyor...")
    print(f"📡 Port: {port}")
    print(f"📖 API Docs: http://localhost:{port}/docs")
    print("=" * 50)
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=True)
