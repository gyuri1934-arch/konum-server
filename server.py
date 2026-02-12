from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional, List
import time

app = FastAPI(title="Konum Takip Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

users_locations = {}
conversations = {}
read_timestamps = {}
rooms = {}
location_history = {}  # ✅ {"userId": [{"lat": ..., "lng": ..., "timestamp": "2025-02-12 14:30:00"}, ...]}

class LocationModel(BaseModel):
    userId: str
    deviceType: str = "phone"
    lat: float
    lng: float
    altitude: float = 0.0
    speed: float = 0.0
    animationType: str = "pulse"
    roomName: str = "Genel"

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

def get_conversation_key(user1: str, user2: str):
    return tuple(sorted([user1, user2]))

@app.get("/")
def home():
    total_messages = sum(len(msgs) for msgs in conversations.values())
    total_history = sum(len(h) for h in location_history.values())
    
    rooms_info = {}
    for u in users_locations.values():
        room = u.get('roomName', 'Genel')
        if room not in rooms_info:
            rooms_info[room] = []
        rooms_info[room].append(
            f"{u['userId']} ({u['deviceType']}) - "
            f"🎭 {u.get('animationType', 'pulse')}"
        )
    
    rooms_html = ""
    for room, users in rooms_info.items():
        is_protected = "🔒" if room in rooms else "🌐"
        rooms_html += f"<h3>{is_protected} {room} ({len(users)} kişi)</h3><ul>"
        for user in users:
            rooms_html += f"<li>{user}</li>"
        rooms_html += "</ul>"
    
    return {
        "status": "✅ Server çalışıyor!",
        "toplam_kullanici": len(users_locations),
        "toplam_oda": len(rooms) + 1,
        "toplam_konusma": len(conversations),
        "toplam_mesaj": total_messages,
        "toplam_gecmis_nokta": total_history,
        "odalar_html": rooms_html
    }

@app.get("/ping")
def ping():
    return {"status": "alive"}

@app.post("/create_room")
def create_room(data: RoomCreateModel):
    try:
        if data.roomName == "Genel":
            raise HTTPException(status_code=400, detail="'Genel' oda adı kullanılamaz")
        
        if data.roomName in rooms:
            raise HTTPException(status_code=400, detail="Bu oda zaten var")
        
        if len(data.password) < 3:
            raise HTTPException(status_code=400, detail="Şifre en az 3 karakter olmalı")
        
        rooms[data.roomName] = {
            "password": data.password,
            "created_by": data.createdBy,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        print(f"🚪 Yeni oda: {data.roomName} (by {data.createdBy})")
        return {"status": "success", "message": "Oda oluşturuldu"}
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/join_room")
def join_room(data: RoomJoinModel):
    try:
        if data.roomName == "Genel":
            return {"status": "success", "message": "Genel odaya katıldınız"}
        
        if data.roomName not in rooms:
            raise HTTPException(status_code=404, detail="Oda bulunamadı")
        
        if rooms[data.roomName]["password"] != data.password:
            raise HTTPException(status_code=401, detail="Yanlış şifre")
        
        print(f"✅ Odaya katıldı: {data.roomName}")
        return {"status": "success", "message": "Odaya katıldınız"}
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get_rooms")
def get_rooms():
    try:
        room_list = [
            {
                "name": "Genel",
                "hasPassword": False,
                "userCount": sum(1 for u in users_locations.values() if u.get('roomName', 'Genel') == 'Genel')
            }
        ]
        
        for room_name, room_data in rooms.items():
            room_list.append({
                "name": room_name,
                "hasPassword": True,
                "userCount": sum(1 for u in users_locations.values() if u.get('roomName', 'Genel') == room_name),
                "createdBy": room_data["created_by"]
            })
        
        return room_list
    except Exception as e:
        print(f"❌ Hata: {e}")
        return []

@app.post("/update_location")
def update_location(data: LocationModel):
    try:
        users_locations[data.userId] = {
            "userId": data.userId,
            "deviceType": data.deviceType,
            "lat": data.lat,
            "lng": data.lng,
            "altitude": data.altitude,
            "speed": data.speed,
            "animationType": data.animationType,
            "roomName": data.roomName,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "last_seen": time.time()
        }
        
        if data.userId not in location_history:
            location_history[data.userId] = []
        
        location_history[data.userId].append({
            "lat": data.lat,
            "lng": data.lng,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "speed": data.speed,
            "altitude": data.altitude
        })
        
        # ✅ Son 1000 noktayı tut (1 yıllık veri için)
        if len(location_history[data.userId]) > 1000:
            location_history[data.userId] = location_history[data.userId][-1000:]
        
        print(f"✅ Konum: {data.userId} ({data.deviceType}) - 🚪 {data.roomName}")
        print(f"   📍 {data.lat:.5f}, {data.lng:.5f}  ⛰️ {data.altitude:.1f}m  🚗 {data.speed:.1f}km/h  🎭 {data.animationType}")
        print(f"   📜 Geçmiş: {len(location_history[data.userId])} nokta")
        
        return {"status": "success"}
    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get_locations/{room_name}")
def get_locations(room_name: str):
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
                "speed": u.get("speed", 0.0),
                "animationType": u.get("animationType", "pulse"),
                "roomName": u.get("roomName", "Genel"),
            }
            for u in users_locations.values()
            if u.get("roomName", "Genel") == room_name
        ]
        
        print(f"📡 Konum isteği → {room_name} odasında {len(locations)} kullanıcı")
        return locations
    except Exception as e:
        print(f"❌ Hata: {e}")
        return []

# ✅ KONUM GEÇMİŞİNİ GETIR (TARİH FİLTRELİ)
@app.get("/get_location_history/{user_id}")
def get_location_history(
    user_id: str,
    period: str = "all"  # all, day, week, month, year
):
    try:
        history = location_history.get(user_id, [])
        
        if not history:
            return []
        
        # Filtreleme
        now = datetime.now()
        filtered = []
        
        for point in history:
            try:
                point_time = datetime.strptime(point["timestamp"], "%Y-%m-%d %H:%M:%S")
                
                if period == "all":
                    filtered.append(point)
                elif period == "day":
                    if now - point_time <= timedelta(days=1):
                        filtered.append(point)
                elif period == "week":
                    if now - point_time <= timedelta(weeks=1):
                        filtered.append(point)
                elif period == "month":
                    if now - point_time <= timedelta(days=30):
                        filtered.append(point)
                elif period == "year":
                    if now - point_time <= timedelta(days=365):
                        filtered.append(point)
            except Exception as e:
                print(f"⚠️ Zaman parse hatası: {e}")
                continue
        
        print(f"📜 Geçmiş isteği: {user_id} ({period}) → {len(filtered)}/{len(history)} nokta")
        return filtered
        
    except Exception as e:
        print(f"❌ Hata: {e}")
        return []

@app.delete("/clear_history/{user_id}")
def clear_history(user_id: str):
    try:
        if user_id in location_history:
            count = len(location_history[user_id])
            del location_history[user_id]
            print(f"🧹 Geçmiş temizlendi: {user_id} ({count} nokta)")
            return {"status": "success", "cleared": count}
        return {"status": "success", "cleared": 0}
    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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

@app.post("/clear")
def clear_all():
    users_locations.clear()
    conversations.clear()
    read_timestamps.clear()
    rooms.clear()
    location_history.clear()
    print("🧹 Tüm veriler temizlendi")
    return {"status": "success"}

@app.delete("/remove_user/{user_id}")
def remove_user(user_id: str):
    if user_id in users_locations:
        del users_locations[user_id]
        print(f"🗑️ Kullanıcı silindi: {user_id}")
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
