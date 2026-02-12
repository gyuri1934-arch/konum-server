from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional, List
import time
import math

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
location_history = {}
pins = {}  # ✅ {"pin_id": {"lat": ..., "lng": ..., "creator": ..., "roomName": ..., "timestamp": ...}}
user_scores = {}  # ✅ {"roomName_userId": score}
pin_collection_state = {}  # ✅ {"pin_id": {"collector": "userId", "start_time": ...}}
room_permissions = {}  # ✅ {"roomName": {"admin": "userId", "collectors": ["user1", "user2"]}}
user_visibility = {}  # ✅ {"userId": {"mode": "all/room/custom", "allowed": ["user1"]}}
user_pins_count = {}  # ✅ {"roomName_userId": pin_count}

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

class PinCreateModel(BaseModel):
    roomName: str
    creator: str
    lat: float
    lng: float

class VisibilityModel(BaseModel):
    userId: str
    mode: str  # "all", "room", "custom", "hidden"
    allowed: List[str] = []

def get_conversation_key(user1: str, user2: str):
    return tuple(sorted([user1, user2]))

def calculate_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Mesafe hesapla (metre cinsinden)"""
    R = 6371000  # Dünya yarıçapı (metre)
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)
    
    a = math.sin(delta_phi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return R * c

@app.get("/")
def home():
    total_messages = sum(len(msgs) for msgs in conversations.values())
    total_history = sum(len(h) for h in location_history.values())
    total_pins = len(pins)
    
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
        "toplam_pin": total_pins,
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
        
        # ✅ Oda oluşturulunca admin yetkisi ver
        room_permissions[data.roomName] = {
            "admin": data.createdBy,
            "collectors": []
        }
        
        print(f"🚪 Yeni oda: {data.roomName} (admin: {data.createdBy})")
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

# ✅ GÖRÜNÜRLİK AYARI
@app.post("/set_visibility")
def set_visibility(data: VisibilityModel):
    try:
        user_visibility[data.userId] = {
            "mode": data.mode,
            "allowed": data.allowed
        }
        print(f"👁️ Görünürlük: {data.userId} → {data.mode}")
        return {"status": "success"}
    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get_visibility/{user_id}")
def get_visibility(user_id: str):
    return user_visibility.get(user_id, {"mode": "all", "allowed": []})

@app.post("/update_location")
def update_location(data: LocationModel):
    try:
        # ✅ Hareketsizlik tespiti
        user_key = data.userId
        idle_status = "online"
        idle_minutes = 0
        
        if user_key in users_locations:
            old_loc = users_locations[user_key]
            distance = calculate_distance(
                old_loc["lat"], old_loc["lng"],
                data.lat, data.lng
            )
            
            # 15m'den az hareket = hareketsiz
            if distance < 15:
                # Hareketsizlik süresini hesapla
                last_move_time = old_loc.get("last_move_time", time.time())
                idle_seconds = time.time() - last_move_time
                idle_minutes = int(idle_seconds / 60)
                
                if idle_minutes > 0:
                    idle_status = "idle"
            else:
                # Hareket etti, zamanı sıfırla
                old_loc["last_move_time"] = time.time()
        
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
            "last_seen": time.time(),
            "last_move_time": users_locations.get(user_key, {}).get("last_move_time", time.time()),
            "idle_status": idle_status,
            "idle_minutes": idle_minutes
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
        
        if len(location_history[data.userId]) > 1000:
            location_history[data.userId] = location_history[data.userId][-1000:]
        
        # ✅ PIN TOPLAMA KONTROLÜ
        if data.roomName in room_permissions:
            perms = room_permissions[data.roomName]
            if data.userId in perms["collectors"]:
                # Yetkili kişi, pinleri kontrol et
                for pin_id, pin_data in list(pins.items()):
                    if pin_data["roomName"] != data.roomName:
                        continue
                    
                    dist = calculate_distance(data.lat, data.lng, pin_data["lat"], pin_data["lng"])
                    
                    # 20m içine girdi
                    if dist <= 20:
                        if pin_id not in pin_collection_state:
                            # İlk giren kişi toplayıcı olur
                            pin_collection_state[pin_id] = {
                                "collector": data.userId,
                                "start_time": time.time()
                            }
                            print(f"📍 Pin toplama başladı: {data.userId} → {pin_id}")
                        elif pin_collection_state[pin_id]["collector"] == data.userId:
                            # Aynı kişi hala yakın
                            pass
                    
                    # 25m dışına çıktı
                    elif dist > 25:
                        if pin_id in pin_collection_state:
                            if pin_collection_state[pin_id]["collector"] == data.userId:
                                # Pin toplandı!
                                score_key = f"{data.roomName}_{data.userId}"
                                user_scores[score_key] = user_scores.get(score_key, 0) + 1
                                
                                # Pin'i sil
                                del pins[pin_id]
                                del pin_collection_state[pin_id]
                                
                                # Pin sayısını azalt
                                pin_count_key = f"{data.roomName}_{pin_data['creator']}"
                                if pin_count_key in user_pins_count:
                                    user_pins_count[pin_count_key] -= 1
                                
                                print(f"✅ Pin toplandı: {data.userId} → +1 skor (toplam: {user_scores[score_key]})")
        
        print(f"✅ Konum: {data.userId} ({idle_status}) - 🚪 {data.roomName}")
        return {"status": "success"}
    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get_locations/{room_name}")
def get_locations(room_name: str, viewer_id: str = ""):
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
        
        locations = []
        for u in users_locations.values():
            if u.get("roomName", "Genel") != room_name:
                continue
            
            # ✅ Görünürlük kontrolü
            user_id = u["userId"]
            visibility = user_visibility.get(user_id, {"mode": "all", "allowed": []})
            
            visible = False
            if visibility["mode"] == "all":
                visible = True
            elif visibility["mode"] == "room":
                visible = True  # Aynı odadayız zaten
            elif visibility["mode"] == "custom":
                visible = viewer_id in visibility["allowed"]
            elif visibility["mode"] == "hidden":
                visible = False
            
            if not visible and viewer_id != user_id:
                continue
            
            locations.append({
                "userId": u["userId"],
                "deviceType": u["deviceType"],
                "lat": u["lat"],
                "lng": u["lng"],
                "altitude": u.get("altitude", 0.0),
                "speed": u.get("speed", 0.0),
                "animationType": u.get("animationType", "pulse"),
                "roomName": u.get("roomName", "Genel"),
                "idleStatus": u.get("idle_status", "online"),
                "idleMinutes": u.get("idle_minutes", 0)
            })
        
        return locations
    except Exception as e:
        print(f"❌ Hata: {e}")
        return []

@app.get("/get_location_history/{user_id}")
def get_location_history(user_id: str, period: str = "all"):
    try:
        history = location_history.get(user_id, [])
        
        if not history:
            return []
        
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

# ✅ PIN SİSTEMİ
@app.post("/create_pin")
def create_pin(data: PinCreateModel):
    try:
        # Her üye sadece 1 pin koyabilir
        pin_count_key = f"{data.roomName}_{data.creator}"
        if user_pins_count.get(pin_count_key, 0) >= 1:
            raise HTTPException(status_code=400, detail="Zaten bir pin koydunuz!")
        
        pin_id = f"{data.roomName}_{data.creator}_{int(time.time())}"
        pins[pin_id] = {
            "id": pin_id,
            "roomName": data.roomName,
            "creator": data.creator,
            "lat": data.lat,
            "lng": data.lng,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        user_pins_count[pin_count_key] = user_pins_count.get(pin_count_key, 0) + 1
        
        print(f"📍 Pin oluşturuldu: {pin_id}")
        return {"status": "success", "pinId": pin_id}
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get_pins/{room_name}")
def get_pins(room_name: str):
    try:
        room_pins = [
            p for p in pins.values()
            if p["roomName"] == room_name
        ]
        
        # Pin toplama durumlarını da ekle
        for pin in room_pins:
            if pin["id"] in pin_collection_state:
                state = pin_collection_state[pin["id"]]
                pin["collectorId"] = state["collector"]
                pin["collectionTime"] = int(time.time() - state["start_time"])
            else:
                pin["collectorId"] = None
                pin["collectionTime"] = 0
        
        return room_pins
    except Exception as e:
        print(f"❌ Hata: {e}")
        return []

@app.delete("/remove_pin/{pin_id}")
def remove_pin(pin_id: str, user_id: str):
    try:
        if pin_id not in pins:
            raise HTTPException(status_code=404, detail="Pin bulunamadı")
        
        pin_data = pins[pin_id]
        if pin_data["creator"] != user_id:
            raise HTTPException(status_code=403, detail="Sadece kendi pininizi silebilirsiniz")
        
        # Pin sayısını azalt
        pin_count_key = f"{pin_data['roomName']}_{user_id}"
        if pin_count_key in user_pins_count:
            user_pins_count[pin_count_key] -= 1
        
        del pins[pin_id]
        
        if pin_id in pin_collection_state:
            del pin_collection_state[pin_id]
        
        print(f"🗑️ Pin silindi: {pin_id}")
        return {"status": "success"}
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ✅ YETKİLENDİRME
@app.post("/set_collector_permission/{room_name}/{user_id}")
def set_collector_permission(room_name: str, user_id: str, admin_id: str, enabled: bool):
    try:
        if room_name not in room_permissions:
            raise HTTPException(status_code=404, detail="Oda bulunamadı")
        
        perms = room_permissions[room_name]
        if perms["admin"] != admin_id:
            raise HTTPException(status_code=403, detail="Sadece admin yetki verebilir")
        
        if enabled:
            if user_id not in perms["collectors"]:
                perms["collectors"].append(user_id)
        else:
            if user_id in perms["collectors"]:
                perms["collectors"].remove(user_id)
        
        print(f"🔑 Yetki: {room_name} → {user_id} → {'Eklendi' if enabled else 'Kaldırıldı'}")
        return {"status": "success"}
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get_room_permissions/{room_name}")
def get_room_permissions(room_name: str):
    return room_permissions.get(room_name, {"admin": None, "collectors": []})

# ✅ SKOR SİSTEMİ
@app.get("/get_scores/{room_name}")
def get_scores(room_name: str):
    try:
        scores = {}
        for key, score in user_scores.items():
            if key.startswith(f"{room_name}_"):
                user_id = key.replace(f"{room_name}_", "")
                scores[user_id] = score
        
        # Sıralı liste olarak döndür
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [{"userId": u, "score": s} for u, s in sorted_scores]
    except Exception as e:
        print(f"❌ Hata: {e}")
        return []

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
    pins.clear()
    user_scores.clear()
    pin_collection_state.clear()
    room_permissions.clear()
    user_visibility.clear()
    user_pins_count.clear()
    print("🧹 Tüm veriler temizlendi")
    return {"status": "success"}

@app.delete("/remove_user/{user_id}")
def remove_user(user_id: str):
    if user_id in users_locations:
        del users_locations[user_id]
        print(f"🗑️ Kullanıcı silindi: {user_id}")
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
