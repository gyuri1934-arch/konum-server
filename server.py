from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import os
from typing import Dict, List, Tuple

app = FastAPI(title="Konum Takip Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================================================
# VERİLER (RAM - Render restart olursa sıfırlanır)
# =====================================================
users_locations: Dict[str, dict] = {}
conversations: Dict[Tuple[str, str], List[dict]] = {}

# =====================================================
# MODELLER
# =====================================================
class LocationModel(BaseModel):
    deviceId: str
    displayName: str = "Misafir"
    deviceType: str = "phone"
    lat: float
    lng: float
    altitude: float = 0.0
    speedMs: float = 0.0
    speedKmh: float = 0.0


class MessageModel(BaseModel):
    fromDeviceId: str
    fromName: str = ""
    toDeviceId: str
    message: str


# =====================================================
# YARDIMCI
# =====================================================
def get_conversation_key(a: str, b: str):
    return tuple(sorted([a, b]))


# =====================================================
# TEST
# =====================================================
@app.get("/ping")
def ping():
    return {"status": "alive"}


# =====================================================
# ANA SAYFA
# =====================================================
@app.get("/")
def home():
    total_messages = sum(len(msgs) for msgs in conversations.values())

    users = []
    for u in users_locations.values():
        users.append(
            f"{u.get('displayName','?')} ({u.get('deviceType','?')}) "
            f"- {u.get('lat',0):.5f}, {u.get('lng',0):.5f} "
            f"- ⛰️ {u.get('altitude',0):.1f}m "
            f"- 🚗 {u.get('speedKmh',0):.1f}km/h "
            f"- id:{u.get('deviceId','')[:8]}"
        )

    return {
        "status": "✅ Server çalışıyor!",
        "toplam_kullanici": len(users_locations),
        "toplam_konusma": len(conversations),
        "toplam_mesaj": total_messages,
        "kullanicilar": users
    }


# =====================================================
# KONUM
# =====================================================
@app.post("/update_location")
def update_location(data: LocationModel):
    try:
        users_locations[data.deviceId] = {
            "deviceId": data.deviceId,
            "displayName": data.displayName,
            "deviceType": data.deviceType,
            "lat": data.lat,
            "lng": data.lng,
            "altitude": data.altitude,
            "speedMs": data.speedMs,
            "speedKmh": data.speedKmh,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        return {"status": "success"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get_locations")
def get_locations():
    try:
        locations = []
        for d in users_locations.values():
            locations.append({
                "deviceId": d["deviceId"],
                "displayName": d.get("displayName", "Bilinmeyen"),
                "deviceType": d.get("deviceType", "phone"),
                "lat": d["lat"],
                "lng": d["lng"],
                "altitude": d.get("altitude", 0.0),
                "speedMs": d.get("speedMs", 0.0),
                "speedKmh": d.get("speedKmh", 0.0),
            })
        return locations

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/remove_device/{device_id}")
def remove_device(device_id: str):
    if device_id in users_locations:
        del users_locations[device_id]
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Cihaz bulunamadı")


# =====================================================
# MESAJLAŞMA
# =====================================================
@app.post("/send_message")
def send_message(data: MessageModel):
    try:
        conv_key = get_conversation_key(data.fromDeviceId, data.toDeviceId)
        if conv_key not in conversations:
            conversations[conv_key] = []

        conversations[conv_key].append({
            "fromDeviceId": data.fromDeviceId,
            "toDeviceId": data.toDeviceId,
            "fromName": data.fromName,
            "message": data.message,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "read": False
        })

        return {"status": "success"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get_conversation/{device1}/{device2}")
def get_conversation(device1: str, device2: str):
    try:
        conv_key = get_conversation_key(device1, device2)
        return conversations.get(conv_key, [])

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/mark_as_read/{reader}/{other_device}")
def mark_as_read(reader: str, other_device: str):
    try:
        conv_key = get_conversation_key(reader, other_device)
        if conv_key in conversations:
            for msg in conversations[conv_key]:
                if msg["toDeviceId"] == reader:
                    msg["read"] = True
        return {"status": "success"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get_unread_count/{device_id}")
def get_unread_count(device_id: str):
    try:
        unread_users = {}

        for conv_key, messages in conversations.items():
            if device_id in conv_key:
                other = conv_key[0] if conv_key[1] == device_id else conv_key[1]

                count = sum(
                    1 for msg in messages
                    if msg["toDeviceId"] == device_id and not msg.get("read", False)
                )

                if count > 0:
                    unread_users[other] = count

        return unread_users

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================
# TEMİZLE
# =====================================================
@app.post("/clear")
def clear_all():
    users_locations.clear()
    conversations.clear()
    return {"status": "success"}


# =====================================================
# START
# =====================================================
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=True)
