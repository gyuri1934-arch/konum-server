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

Geliştirici: [Adın]
Versiyon: 2.0
Güncelleme: 2026-02-16

═══════════════════════════════════════════════════════════════════════════════
"""

# ═══════════════════════════════════════════════════════════════════════════════
# 📦 KÜTÜPHANE İMPORTLARI
# ═══════════════════════════════════════════════════════════════════════════════

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
from typing import Optional, List
import time
import math
import pytz

# ═══════════════════════════════════════════════════════════════════════════════
# ⚙️ UYGULAMA BAŞLATMA VE AYARLAR
# ═══════════════════════════════════════════════════════════════════════════════

app = FastAPI(title="Konum Takip Server")

# CORS ayarları
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════════════════════════════════════
# 💾 VERİ SAKLAMASI (RAM)
# ═══════════════════════════════════════════════════════════════════════════════
# NOT: Server restart olunca tüm veriler sıfırlanır!

users_locations = {}           # Anlık konumlar
conversations = {}             # Mesajlar
read_timestamps = {}           # Mesaj okunma zamanları
rooms = {}                     # Odalar
location_history = {}          # Rota geçmişi
pins = {}                      # Haritadaki pinler
user_scores = {}               # Skorlar
pin_collection_state = {}      # Pin toplama durumu
room_permissions = {}          # Oda yetkileri
user_visibility = {}           # Görünürlük ayarları
user_pins_count = {}           # Pin sayıları
pin_collection_history = {}    # Pin geçmişi

# ═══════════════════════════════════════════════════════════════════════════════
# 🎛️ SİSTEM AYARLARI
# ═══════════════════════════════════════════════════════════════════════════════
# Buradan ayarları değiştirebilirsin!

# --- Rota Örnekleme Ayarları ---
SPEED_THRESHOLD_VEHICLE = 30   # Araç hız eşiği (km/h)
SPEED_THRESHOLD_RUN = 15        # Koşu hız eşiği (km/h)
SPEED_THRESHOLD_WALK = 3        # Yürüyüş hız eşiği (km/h)

MIN_DISTANCE_VEHICLE = 50       # Araç için min mesafe (metre)
MIN_DISTANCE_RUN = 20            # Koşu için min mesafe (metre)
MIN_DISTANCE_WALK = 10           # Yürüyüş için min mesafe (metre)
MIN_DISTANCE_IDLE = 5            # Durgun için min mesafe (metre)

# --- Rota Limitleri ---
MAX_POINTS_PER_USER = 5000      # Max nokta sayısı
MAX_HISTORY_DAYS = 90            # Max geçmiş süresi (gün)

# --- Timezone ---
DEFAULT_TIMEZONE = pytz.timezone('Europe/Istanbul')  # Türkiye saati

# --- Timeout ---
USER_TIMEOUT = 120               # Kullanıcı timeout süresi (saniye)

# ═══════════════════════════════════════════════════════════════════════════════
# 🛠️ YARDIMCI FONKSİYONLAR
# ═══════════════════════════════════════════════════════════════════════════════

def get_local_time():
    """Türkiye saatini döndür (YYYY-MM-DD HH:MM:SS)"""
    return datetime.now(DEFAULT_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")

def get_conversation_key(user1: str, user2: str):
    """İki kullanıcı için unique konuşma key'i"""
    return tuple(sorted([user1, user2]))

def calculate_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """İki nokta arası mesafe hesapla (metre) - Haversine formülü"""
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
    mode: str
    allowed: List[str] = []

# ═══════════════════════════════════════════════════════════════════════════════
# 🏠 ANA SAYFA VE SAĞLIK KONTROLÜ
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/")
def home():
    """Ana sayfa - İstatistikler"""
    total_messages = sum(len(msgs) for msgs in conversations.values())
    total_history = sum(len(h) for h in location_history.values())
    total_pins = len(pins)
    
    rooms_info = {}
    for u in users_locations.values():
        room = u.get('roomName', 'Genel')
        if room not in rooms_info:
            rooms_info[room] = []
        rooms_info[room].append(f"{u['userId']} ({u['deviceType']})")
    
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
    """Health check"""
    return {"status": "alive"}

# ═══════════════════════════════════════════════════════════════════════════════
# 🚪 ODA YÖNETİMİ
# ═══════════════════════════════════════════════════════════════════════════════
# BÖLÜM: Oda oluşturma, katılma, silme, şifre değiştirme

@app.post("/create_room")
def create_room(data: RoomCreateModel):
    """
    📌 ODA OLUŞTUR
    
    Kurallar:
    - "Genel" oda adı yasak
    - Oda zaten varsa hata
    - Şifre min 3 karakter
    - Oluşturan kişi admin olur
    """
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
            "created_at": get_local_time()
        }
        
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
    """
    📌 ODAYA KATIL
    
    - "Genel" odaya şifresiz
    - Diğer odalara şifre gerekli
    """
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
def get_rooms(user_id: str = ""):
    """
    📌 ODA LİSTESİ
    
    Döner:
    - Oda adı
    - Kullanıcı sayısı
    - Admin mi?
    - Şifre (admin ise)
    """
    try:
        room_list = [
            {
                "name": "Genel",
                "hasPassword": False,
                "userCount": sum(1 for u in users_locations.values() if u.get('roomName', 'Genel') == 'Genel'),
                "isAdmin": False,
                "password": None
            }
        ]
        
        for room_name, room_data in rooms.items():
            perms = room_permissions.get(room_name, {})
            is_admin = perms.get("admin") == user_id
            
            room_list.append({
                "name": room_name,
                "hasPassword": True,
                "userCount": sum(1 for u in users_locations.values() if u.get('roomName', 'Genel') == room_name),
                "createdBy": room_data["created_by"],
                "isAdmin": is_admin,
                "password": rooms[room_name]["password"] if is_admin else None
            })
        
        return room_list
    
    except Exception as e:
        print(f"❌ Hata: {e}")
        return []

@app.delete("/delete_room/{room_name}")
def delete_room(room_name: str, admin_id: str):
    """
    📌 ODAYI SİL (Sadece Admin)
    
    Silme işlemi:
    1. Tüm üyeler → "Genel" odaya
    2. Tüm pinler → Silinir
    3. Tüm skorlar → Sıfırlanır
    """
    try:
        if room_name == "Genel":
            raise HTTPException(status_code=400, detail="Genel oda silinemez")
        
        if room_name not in rooms:
            raise HTTPException(status_code=404, detail="Oda bulunamadı")
        
        if room_permissions.get(room_name, {}).get("admin") != admin_id:
            raise HTTPException(status_code=403, detail="Sadece admin oda silebilir")
        
        # Üyeleri taşı
        for uid, user in users_locations.items():
            if user.get("roomName") == room_name:
                user["roomName"] = "Genel"
        
        # Odayı sil
        del rooms[room_name]
        if room_name in room_permissions:
            del room_permissions[room_name]
        
        # Pinleri sil
        pins_to_delete = [pid for pid, p in pins.items() if p["roomName"] == room_name]
        for pid in pins_to_delete:
            del pins[pid]
        
        # Skorları sil
        scores_to_delete = [k for k in user_scores.keys() if k.startswith(f"{room_name}_")]
        for k in scores_to_delete:
            del user_scores[k]
        
        # Geçmişi sil
        history_to_delete = [k for k in pin_collection_history.keys() if k.startswith(f"{room_name}_")]
        for k in history_to_delete:
            del pin_collection_history[k]
        
        print(f"🗑️ Oda silindi: {room_name} (by {admin_id})")
        return {"status": "success", "message": f"{room_name} odası silindi"}
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get_room_password/{room_name}")
def get_room_password(room_name: str, admin_id: str):
    """📌 ŞİFREYİ GÖR (Sadece Admin)"""
    try:
        if room_name == "Genel":
            raise HTTPException(status_code=400, detail="Genel odanın şifresi yok")
        
        if room_name not in rooms:
            raise HTTPException(status_code=404, detail="Oda bulunamadı")
        
        if room_permissions.get(room_name, {}).get("admin") != admin_id:
            raise HTTPException(status_code=403, detail="Sadece admin şifreyi görebilir")
        
        password = rooms[room_name]["password"]
        print(f"🔑 Şifre görüntülendi: {room_name}")
        return {"password": password}
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/change_room_password/{room_name}")
def change_room_password(room_name: str, admin_id: str, new_password: str):
    """📌 ŞİFREYİ DEĞİŞTİR (Sadece Admin)"""
    try:
        if room_name == "Genel":
            raise HTTPException(status_code=400, detail="Genel odanın şifresi değiştirilemez")
        
        if room_name not in rooms:
            raise HTTPException(status_code=404, detail="Oda bulunamadı")
        
        if room_permissions.get(room_name, {}).get("admin") != admin_id:
            raise HTTPException(status_code=403, detail="Sadece admin şifreyi değiştirebilir")
        
        if len(new_password) < 3:
            raise HTTPException(status_code=400, detail="Şifre en az 3 karakter olmalı")
        
        rooms[room_name]["password"] = new_password
        print(f"🔑 Şifre değiştirildi: {room_name}")
        return {"status": "success", "message": "Şifre değiştirildi"}
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ═══════════════════════════════════════════════════════════════════════════════
# 👁️ GÖRÜNÜRLİK SİSTEMİ
# ═══════════════════════════════════════════════════════════════════════════════
# BÖLÜM: Kullanıcı görünürlük ayarları

@app.post("/set_visibility")
def set_visibility(data: VisibilityModel):
    """
    📌 GÖRÜNÜRLİK AYARLA
    
    Modlar:
    - "all": Herkese görünür
    - "room": Sadece oda üyeleri
    - "hidden": Kimse görmesin
    """
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
    """📌 GÖRÜNÜRLİK AYARINI GETİR"""
    return user_visibility.get(user_id, {"mode": "all", "allowed": []})

# ═══════════════════════════════════════════════════════════════════════════════
# 📍 KONUM GÜNCELLEMESİ (ANA FONKSİYON)
# ═══════════════════════════════════════════════════════════════════════════════
# BÖLÜM: Konum güncelleme, rota kaydetme, pin toplama

@app.post("/update_location")
def update_location(data: LocationModel):
    """
    📌 KONUM GÜNCELLE
    
    Bu fonksiyon 3 şey yapar:
    1. Hareketsizlik kontrolü (15m < = idle)
    2. Rota geçmişine ekle (hıza göre)
    3. Pin toplama sistemi
    """
    try:
        user_key = data.userId
        idle_status = "online"
        idle_minutes = 0
        
        # ─────────────────────────────────────────────────────────────────────
        # 1️⃣ HAREKETSİZLİK KONTROLÜ
        # ─────────────────────────────────────────────────────────────────────
        if user_key in users_locations:
            old_loc = users_locations[user_key]
            distance = calculate_distance(
                old_loc["lat"], old_loc["lng"],
                data.lat, data.lng
            )
            
            if distance < 15:  # 15m'den az hareket
                last_move_time = old_loc.get("last_move_time", time.time())
                idle_seconds = time.time() - last_move_time
                idle_minutes = int(idle_seconds / 60)
                
                if idle_minutes > 0:
                    idle_status = "idle"
            else:
                old_loc["last_move_time"] = time.time()
        
        # Kullanıcı konumunu güncelle
        users_locations[data.userId] = {
            "userId": data.userId,
            "deviceType": data.deviceType,
            "lat": data.lat,
            "lng": data.lng,
            "altitude": data.altitude,
            "speed": data.speed,
            "animationType": data.animationType,
            "roomName": data.roomName,
            "timestamp": get_local_time(),
            "last_seen": time.time(),
            "last_move_time": users_locations.get(user_key, {}).get("last_move_time", time.time()),
            "idle_status": idle_status,
            "idle_minutes": idle_minutes
        }
        
        # ─────────────────────────────────────────────────────────────────────
        # 2️⃣ ROTA GEÇMİŞİNE EKLE (HIZA GÖRE FİLTRELEME)
        # ─────────────────────────────────────────────────────────────────────
        # Bu bölümü değiştirerek rota kayıt mantığını ayarlayabilirsin
        
        if data.userId not in location_history:
            location_history[data.userId] = []
        
        # Hıza göre min mesafe
        speed_kmh = data.speed
        
        if speed_kmh > SPEED_THRESHOLD_VEHICLE:
            min_distance = MIN_DISTANCE_VEHICLE
        elif speed_kmh > SPEED_THRESHOLD_RUN:
            min_distance = MIN_DISTANCE_RUN
        elif speed_kmh > SPEED_THRESHOLD_WALK:
            min_distance = MIN_DISTANCE_WALK
        else:
            min_distance = MIN_DISTANCE_IDLE
        
        # Son noktaya mesafe kontrolü
        should_add = True
        
        if location_history[data.userId]:
            last_point = location_history[data.userId][-1]
            distance_from_last = calculate_distance(
                last_point["lat"], last_point["lng"],
                data.lat, data.lng
            )
            
            if distance_from_last < min_distance:
                should_add = False
                print(f"⏭️ Rota atlandı: {data.userId} ({distance_from_last:.1f}m < {min_distance}m)")
        
        # Nokta ekle
        if should_add:
            location_history[data.userId].append({
                "lat": data.lat,
                "lng": data.lng,
                "timestamp": get_local_time(),
                "speed": data.speed,
                "altitude": data.altitude
            })
            
            # Zaman bazlı temizlik (90 gün)
            now = datetime.now(DEFAULT_TIMEZONE)
            cutoff_date = now - timedelta(days=MAX_HISTORY_DAYS)
            
            cleaned_history = []
            for point in location_history[data.userId]:
                try:
                    point_time_str = point["timestamp"].replace(' ', 'T')
                    point_time = datetime.fromisoformat(point_time_str)
                    
                    if point_time.tzinfo is None:
                        point_time = DEFAULT_TIMEZONE.localize(point_time)
                    
                    if point_time > cutoff_date:
                        cleaned_history.append(point)
                except:
                    pass
            
            location_history[data.userId] = cleaned_history
            
            # Nokta bazlı temizlik (5000 nokta)
            if len(location_history[data.userId]) > MAX_POINTS_PER_USER:
                location_history[data.userId] = location_history[data.userId][-MAX_POINTS_PER_USER:]
            
            print(f"📍 Rota: {data.userId} (hız:{speed_kmh:.1f}km/h, total:{len(location_history[data.userId])})")
        
        # ─────────────────────────────────────────────────────────────────────
        # 3️⃣ PIN TOPLAMA SİSTEMİ
        # ─────────────────────────────────────────────────────────────────────
        # Bu bölümü değiştirerek pin mekaniğini ayarlayabilirsin
        
        if data.roomName in room_permissions:
            perms = room_permissions[data.roomName]
            
            if data.userId in perms["collectors"]:
                for pin_id, pin_data in list(pins.items()):
                    if pin_data["roomName"] != data.roomName:
                        continue
                    
                    dist = calculate_distance(data.lat, data.lng, pin_data["lat"], pin_data["lng"])
                    
                    # 20m yakın → Toplama başla
                    if dist <= 20:
                        if pin_id not in pin_collection_state:
                            pin_collection_state[pin_id] = {
                                "collector": data.userId,
                                "start_time": time.time()
                            }
                            print(f"📍 Pin toplama başladı: {data.userId} → {pin_id}")
                    
                    # 25m uzak → Pin toplandı
                    elif dist > 25:
                        if pin_id in pin_collection_state:
                            if pin_collection_state[pin_id]["collector"] == data.userId:
                                # Skor artır
                                score_key = f"{data.roomName}_{data.userId}"
                                user_scores[score_key] = user_scores.get(score_key, 0) + 1
                                
                                # Geçmişe kaydet
                                history_key = f"{data.roomName}_{data.userId}"
                                if history_key not in pin_collection_history:
                                    pin_collection_history[history_key] = []
                                
                                collected_time = get_local_time()
                                
                                pin_collection_history[history_key].append({
                                    "pinId": pin_id,
                                    "creator": pin_data["creator"],
                                    "timestamp": collected_time,
                                    "createdAt": pin_data.get("createdAt", pin_data.get("timestamp", "Bilinmiyor")),
                                    "lat": pin_data["lat"],
                                    "lng": pin_data["lng"]
                                })
                                
                                # Pin'i sil
                                del pins[pin_id]
                                del pin_collection_state[pin_id]
                                
                                pin_count_key = f"{data.roomName}_{pin_data['creator']}"
                                if pin_count_key in user_pins_count:
                                    user_pins_count[pin_count_key] -= 1
                                
                                print(f"✅ Pin toplandı: {data.userId} (+1, total:{user_scores[score_key]})")
        
        print(f"✅ {data.userId} ({idle_status}) - {data.roomName}")
        return {"status": "success"}
    
    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ═══════════════════════════════════════════════════════════════════════════════
# 📍 KONUM LİSTESİ VE GEÇMİŞ
# ═══════════════════════════════════════════════════════════════════════════════
# BÖLÜM: Kullanıcı konumlarını getirme, rota geçmişi

@app.get("/get_locations/{room_name}")
def get_locations(room_name: str, viewer_id: str = ""):
    """
    📌 ODADAKİ KULLANICILARI GETİR
    
    - Timeout kontrolü (2 dakika)
    - Görünürlük filtreleme
    """
    try:
        now = time.time()
        to_delete = []
        
        # Timeout kontrolü
        for uid, u in users_locations.items():
            last_seen = u.get("last_seen", 0)
            if now - last_seen > USER_TIMEOUT:
                to_delete.append(uid)
        
        for uid in to_delete:
            del users_locations[uid]
            print(f"🧹 Timeout: {uid}")
        
        # Konum listesi
        locations = []
        
        for u in users_locations.values():
            if u.get("roomName", "Genel") != room_name:
                continue
            
            user_id = u["userId"]
            visibility = user_visibility.get(user_id, {"mode": "all", "allowed": []})
            
            visible = False
            
            if visibility["mode"] == "all":
                visible = True
            elif visibility["mode"] == "room":
                visible = True
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
    """
    📌 ROTA GEÇMİŞİNİ GETİR
    
    Dönemler: all, day, week, month, year
    """
    try:
        history = location_history.get(user_id, [])
        
        if not history:
            return []
        
        now = datetime.now(DEFAULT_TIMEZONE)
        filtered = []
        
        for point in history:
            try:
                point_time_str = point["timestamp"].replace(' ', 'T')
                point_time = datetime.fromisoformat(point_time_str)
                
                if point_time.tzinfo is None:
                    point_time = DEFAULT_TIMEZONE.localize(point_time)
                
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
                continue
        
        print(f"📜 Rota: {user_id} ({period}) → {len(filtered)}/{len(history)}")
        return filtered
    
    except Exception as e:
        print(f"❌ Hata: {e}")
        return []

@app.delete("/clear_history/{user_id}")
def clear_history(user_id: str):
    """📌 ROTA GEÇMİŞİNİ TEMİZLE"""
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

# ═══════════════════════════════════════════════════════════════════════════════
# 📍 PIN SİSTEMİ
# ═══════════════════════════════════════════════════════════════════════════════
# BÖLÜM: Pin oluşturma, silme, listeleme

@app.post("/create_pin")
def create_pin(data: PinCreateModel):
    """
    📌 PIN OLUŞTUR
    
    - Kullanıcı başına 1 pin
    - Konulma saati kaydedilir
    """
    try:
        pin_count_key = f"{data.roomName}_{data.creator}"
        if user_pins_count.get(pin_count_key, 0) >= 1:
            raise HTTPException(status_code=400, detail="Zaten bir pin koydunuz!")
        
        pin_id = f"{data.roomName}_{data.creator}_{int(time.time())}"
        created_time = get_local_time()
        
        pins[pin_id] = {
            "id": pin_id,
            "roomName": data.roomName,
            "creator": data.creator,
            "lat": data.lat,
            "lng": data.lng,
            "timestamp": created_time,
            "createdAt": created_time
        }
        
        user_pins_count[pin_count_key] = user_pins_count.get(pin_count_key, 0) + 1
        
        print(f"📍 Pin oluşturuldu: {pin_id} ({created_time})")
        return {"status": "success", "pinId": pin_id}
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get_pins/{room_name}")
def get_pins(room_name: str):
    """📌 ODADAKİ PİNLERİ GETİR"""
    try:
        room_pins = [
            p for p in pins.values()
            if p["roomName"] == room_name
        ]
        
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
    """📌 PİNİ SİL"""
    try:
        if pin_id not in pins:
            raise HTTPException(status_code=404, detail="Pin bulunamadı")
        
        pin_data = pins[pin_id]
        
        if pin_data["creator"] != user_id:
            raise HTTPException(status_code=403, detail="Sadece kendi pininizi silebilirsiniz")
        
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

# ═══════════════════════════════════════════════════════════════════════════════
# 🔑 YETKİ VE SKOR SİSTEMİ
# ═══════════════════════════════════════════════════════════════════════════════
# BÖLÜM: Pin toplama yetkileri, skor tablosu

@app.post("/set_collector_permission/{room_name}/{user_id}")
def set_collector_permission(room_name: str, user_id: str, admin_id: str, enabled: bool):
    """📌 PIN TOPLAMA YETKİSİ VER/KALDIR"""
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
        
        print(f"🔑 Yetki: {room_name} → {user_id} → {'✅' if enabled else '❌'}")
        return {"status": "success"}
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get_room_permissions/{room_name}")
def get_room_permissions(room_name: str):
    """📌 ODA YETKİLERİNİ GETİR"""
    return room_permissions.get(room_name, {"admin": None, "collectors": []})

@app.get("/get_scores/{room_name}")
def get_scores(room_name: str):
    """📌 SKOR TABLOSUNU GETİR (Sıralı)"""
    try:
        scores = {}
        
        for key, score in user_scores.items():
            if key.startswith(f"{room_name}_"):
                user_id = key.replace(f"{room_name}_", "")
                scores[user_id] = score
        
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        
        result = []
        for user_id, score in sorted_scores:
            result.append({
                "userId": user_id,
                "score": score
            })
        
        return result
    
    except Exception as e:
        print(f"❌ Hata: {e}")
        return []

@app.get("/get_collection_history/{room_name}/{user_id}")
def get_collection_history(room_name: str, user_id: str):
    """📌 TOPLANAN PİN GEÇMİŞİ"""
    try:
        history_key = f"{room_name}_{user_id}"
        history = pin_collection_history.get(history_key, [])
        
        print(f"📜 Pin geçmişi: {user_id} → {len(history)}")
        return history
    
    except Exception as e:
        print(f"❌ Hata: {e}")
        return []

# ═══════════════════════════════════════════════════════════════════════════════
# 💬 MESAJLAŞMA SİSTEMİ
# ═══════════════════════════════════════════════════════════════════════════════
# BÖLÜM: Mesaj gönderme, okuma, okunmadı sayısı

@app.post("/send_message")
def send_message(data: MessageModel):
    """📌 MESAJ GÖNDER"""
    try:
        key = get_conversation_key(data.fromUser, data.toUser)
        
        if key not in conversations:
            conversations[key] = []
        
        conversations[key].append({
            "from": data.fromUser,
            "to": data.toUser,
            "message": data.message,
            "timestamp": get_local_time(),
            "read": False
        })
        
        print(f"💬 {data.fromUser} → {data.toUser}: {data.message}")
        return {"status": "success"}
    
    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get_conversation/{user1}/{user2}")
def get_conversation(user1: str, user2: str):
    """📌 KONUŞMAYI GETİR"""
    try:
        key = get_conversation_key(user1, user2)
        msgs = conversations.get(key, [])
        print(f"💬 {user1} ↔ {user2} ({len(msgs)})")
        return msgs
    
    except Exception as e:
        print(f"❌ Hata: {e}")
        return []

@app.post("/mark_as_read/{reader}/{other_user}")
def mark_as_read(reader: str, other_user: str):
    """📌 OKUNDU İŞARETLE"""
    try:
        key = get_conversation_key(reader, other_user)
        
        if key in conversations:
            for msg in conversations[key]:
                if msg["to"] == reader:
                    msg["read"] = True
        
        read_timestamps[key] = get_local_time()
        print(f"👁️ Okundu: {reader} ← {other_user}")
        return {"status": "success"}
    
    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get_unread_count/{user_id}")
def get_unread_count(user_id: str):
    """📌 OKUNMAMIŞ MESAJ SAYISI"""
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

# ═══════════════════════════════════════════════════════════════════════════════
# 🔧 YÖNETİM FONKSİYONLARI
# ═══════════════════════════════════════════════════════════════════════════════
# BÖLÜM: Temizlik ve yönetim işlemleri

@app.post("/clear")
def clear_all():
    """
    📌 TÜM VERİLERİ TEMİZLE
    
    ⚠️ DİKKAT: Geri dönüşü yok!
    """
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
    pin_collection_history.clear()
    
    print("🧹 TÜM VERİLER TEMİZLENDİ")
    return {"status": "success"}

@app.delete("/remove_user/{user_id}")
def remove_user(user_id: str):
    """📌 KULLANICIYI SİL"""
    if user_id in users_locations:
        del users_locations[user_id]
        print(f"🗑️ Silindi: {user_id}")
        return {"status": "success"}
    
    raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")

# ═══════════════════════════════════════════════════════════════════════════════
#                              SON
# ═══════════════════════════════════════════════════════════════════════════════
