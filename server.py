# ========== KÜTÜPHANELER ==========
from fastapi import FastAPI, HTTPException  # Web framework
from fastapi.middleware.cors import CORSMiddleware  # Cross-origin istekleri için
from pydantic import BaseModel  # Veri modelleri için
from datetime import datetime, timedelta, timezone  # Tarih/saat işlemleri
from typing import Optional, List  # Tip belirteçleri
import time  # Unix timestamp için
import math  # Mesafe hesaplama için
import pytz  # Timezone desteği için

# ========== UYGULAMA BAŞLATMA ==========
app = FastAPI(title="Konum Takip Server")

# ========== CORS AYARLARı (Tüm domainlerden erişime izin ver) ==========
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tüm domainler
    allow_methods=["*"],  # Tüm HTTP metodları (GET, POST, DELETE, vb.)
    allow_headers=["*"],  # Tüm headerlar
)

# ========== BELLEK İÇİ VERİ SAKLAMASI (RAM) ==========
users_locations = {}           # Kullanıcıların anlık konumları
conversations = {}             # Mesajlaşma geçmişi
read_timestamps = {}           # Mesaj okunma zamanları
rooms = {}                     # Oda bilgileri (şifre, admin, vb.)
location_history = {}          # Rota geçmişi
pins = {}                      # Haritadaki pinler
user_scores = {}               # Kullanıcı skorları
pin_collection_state = {}      # Pin toplama durumları (hangi pin kim tarafından toplanıyor)
room_permissions = {}          # Oda yetkileri (admin, pin toplayıcılar)
user_visibility = {}           # Görünürlük ayarları
user_pins_count = {}           # Her kullanıcının kaç pin koyduğu
pin_collection_history = {}    # Toplanan pinlerin geçmişi

# ========== AYARLAR ==========
# Hız eşikleri (km/h)
SPEED_THRESHOLD_VEHICLE = 30   # Araç (30+ km/h)
SPEED_THRESHOLD_RUN = 15        # Koşu/Bisiklet (15-30 km/h)
SPEED_THRESHOLD_WALK = 3        # Yürüyüş (3-15 km/h)

# Minimum mesafeler (metre) - Rota kayıt için
MIN_DISTANCE_VEHICLE = 50       # Araç: Her 50 metrede bir nokta
MIN_DISTANCE_RUN = 20            # Koşu: Her 20 metrede bir nokta
MIN_DISTANCE_WALK = 10           # Yürüyüş: Her 10 metrede bir nokta
MIN_DISTANCE_IDLE = 5            # Durgun: Her 5 metrede bir nokta

# Rota geçmişi limitleri
MAX_POINTS_PER_USER = 5000      # Kullanıcı başına max 5000 nokta
MAX_HISTORY_DAYS = 90           # Max 90 gün geçmiş

# Timezone ayarı (Türkiye saati)
DEFAULT_TIMEZONE = pytz.timezone('Europe/Istanbul')

# ========== YARDIMCI FONKSİYONLAR ==========

def get_local_time():
    """Türkiye saatini döndür (YYYY-MM-DD HH:MM:SS formatında)"""
    return datetime.now(DEFAULT_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")

def get_conversation_key(user1: str, user2: str):
    """İki kullanıcı arasındaki konuşma için unique key oluştur"""
    # Alfabetik sıralama yaparak her zaman aynı key'i üret
    return tuple(sorted([user1, user2]))

def calculate_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    İki konum arasındaki mesafeyi hesapla (Haversine formülü)
    Döndürülen değer metre cinsindendir
    """
    R = 6371000  # Dünya yarıçapı (metre)
    
    # Dereceleri radyana çevir
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)
    
    # Haversine formülü
    a = math.sin(delta_phi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return R * c  # Mesafe (metre)

# ========== VERİ MODELLERİ (Pydantic) ==========

class LocationModel(BaseModel):
    """Konum güncelleme modeli"""
    userId: str                      # Kullanıcı adı
    deviceType: str = "phone"        # Cihaz tipi (phone/pc)
    lat: float                       # Enlem
    lng: float                       # Boylam
    altitude: float = 0.0            # Yükseklik (metre)
    speed: float = 0.0               # Hız (km/h)
    animationType: str = "pulse"     # Animasyon tipi
    roomName: str = "Genel"          # Bulunduğu oda

class MessageModel(BaseModel):
    """Mesaj modeli"""
    fromUser: str      # Gönderen
    toUser: str        # Alıcı
    message: str       # Mesaj içeriği

class RoomCreateModel(BaseModel):
    """Oda oluşturma modeli"""
    roomName: str      # Oda adı
    password: str      # Oda şifresi
    createdBy: str     # Oluşturan kişi

class RoomJoinModel(BaseModel):
    """Odaya katılma modeli"""
    roomName: str      # Oda adı
    password: str      # Oda şifresi

class PinCreateModel(BaseModel):
    """Pin oluşturma modeli"""
    roomName: str      # Hangi odaya pin konuyor
    creator: str       # Pin'i koyan kişi
    lat: float         # Pin'in enlemi
    lng: float         # Pin'in boylamı

class VisibilityModel(BaseModel):
    """Görünürlük ayarları modeli"""
    userId: str                # Kullanıcı adı
    mode: str                  # Mod: "all", "room", "hidden"
    allowed: List[str] = []    # Özel izin verilen kullanıcılar

# ========== ANA SAYFA ==========

@app.get("/")
def home():
    """
    Ana sayfa - Server durumu ve istatistikler
    Web tarayıcıdan https://konum-server.onrender.com/ adresine gidince görünür
    """
    # İstatistikleri hesapla
    total_messages = sum(len(msgs) for msgs in conversations.values())
    total_history = sum(len(h) for h in location_history.values())
    total_pins = len(pins)
    
    # Odaları grupla
    rooms_info = {}
    for u in users_locations.values():
        room = u.get('roomName', 'Genel')
        if room not in rooms_info:
            rooms_info[room] = []
        rooms_info[room].append(
            f"{u['userId']} ({u['deviceType']}) - "
            f"🎭 {u.get('animationType', 'pulse')}"
        )
    
    # HTML formatında oda listesi
    rooms_html = ""
    for room, users in rooms_info.items():
        is_protected = "🔒" if room in rooms else "🌐"
        rooms_html += f"<h3>{is_protected} {room} ({len(users)} kişi)</h3><ul>"
        for user in users:
            rooms_html += f"<li>{user}</li>"
        rooms_html += "</ul>"
    
    # JSON yanıt döndür
    return {
        "status": "✅ Server çalışıyor!",
        "toplam_kullanici": len(users_locations),
        "toplam_oda": len(rooms) + 1,  # +1 çünkü "Genel" oda hep var
        "toplam_konusma": len(conversations),
        "toplam_mesaj": total_messages,
        "toplam_gecmis_nokta": total_history,
        "toplam_pin": total_pins,
        "odalar_html": rooms_html
    }

# ========== SAĞLIK KONTROLÜ ==========

@app.get("/ping")
def ping():
    """
    Server'ın ayakta olup olmadığını kontrol et
    Render.com bu endpoint'i otomatik kontrol eder
    """
    return {"status": "alive"}

# ========== ODA YÖNETİMİ ==========

@app.post("/create_room")
def create_room(data: RoomCreateModel):
    """
    Yeni oda oluştur
    - Oda adı "Genel" olamaz
    - Oda zaten varsa hata ver
    - Şifre en az 3 karakter olmalı
    - Oluşturan kişi otomatik admin olur
    """
    try:
        # "Genel" oda adı yasak
        if data.roomName == "Genel":
            raise HTTPException(status_code=400, detail="'Genel' oda adı kullanılamaz")
        
        # Oda zaten var mı?
        if data.roomName in rooms:
            raise HTTPException(status_code=400, detail="Bu oda zaten var")
        
        # Şifre kontrolü
        if len(data.password) < 3:
            raise HTTPException(status_code=400, detail="Şifre en az 3 karakter olmalı")
        
        # Odayı oluştur
        rooms[data.roomName] = {
            "password": data.password,
            "created_by": data.createdBy,
            "created_at": get_local_time()  # Türkiye saati
        }
        
        # Oda yetkilerini ayarla (oluşturan kişi admin)
        room_permissions[data.roomName] = {
            "admin": data.createdBy,         # Admin
            "collectors": []                  # Pin toplayıcılar (başlangıçta boş)
        }
        
        print(f"🚪 Yeni oda: {data.roomName} (admin: {data.createdBy})")
        return {"status": "success", "message": "Oda oluşturuldu"}
    
    except HTTPException as he:
        raise he  # HTTP hatasını aynen ilet
    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/join_room")
def join_room(data: RoomJoinModel):
    """
    Odaya katıl
    - "Genel" odaya şifresiz katılınır
    - Diğer odalara şifre gerekir
    """
    try:
        # "Genel" odaya direkt katıl
        if data.roomName == "Genel":
            return {"status": "success", "message": "Genel odaya katıldınız"}
        
        # Oda var mı?
        if data.roomName not in rooms:
            raise HTTPException(status_code=404, detail="Oda bulunamadı")
        
        # Şifre doğru mu?
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
    Tüm odaları listele
    - Her oda için kullanıcı sayısı
    - Kullanıcı admin mi kontrolü
    - Admin ise şifreyi de döndür
    """
    try:
        room_list = [
            {
                "name": "Genel",
                "hasPassword": False,
                "userCount": sum(1 for u in users_locations.values() if u.get('roomName', 'Genel') == 'Genel'),
                "isAdmin": False,  # Genel odanın admini yok
                "password": None
            }
        ]
        
        # Tüm odaları ekle
        for room_name, room_data in rooms.items():
            perms = room_permissions.get(room_name, {})
            is_admin = perms.get("admin") == user_id  # Bu kullanıcı admin mi?
            
            room_list.append({
                "name": room_name,
                "hasPassword": True,
                "userCount": sum(1 for u in users_locations.values() if u.get('roomName', 'Genel') == room_name),
                "createdBy": room_data["created_by"],
                "isAdmin": is_admin,
                "password": rooms[room_name]["password"] if is_admin else None  # Admin ise şifreyi göster
            })
        
        return room_list
    
    except Exception as e:
        print(f"❌ Hata: {e}")
        return []

@app.delete("/delete_room/{room_name}")
def delete_room(room_name: str, admin_id: str):
    """
    Odayı sil (sadece admin yapabilir)
    - Tüm üyeler "Genel" odaya aktarılır
    - Odadaki tüm pinler silinir
    - Odadaki tüm skorlar sıfırlanır
    """
    try:
        # "Genel" oda silinemez
        if room_name == "Genel":
            raise HTTPException(status_code=400, detail="Genel oda silinemez")
        
        # Oda var mı?
        if room_name not in rooms:
            raise HTTPException(status_code=404, detail="Oda bulunamadı")
        
        # Kullanıcı admin mi?
        if room_permissions.get(room_name, {}).get("admin") != admin_id:
            raise HTTPException(status_code=403, detail="Sadece admin oda silebilir")
        
        # Tüm üyeleri "Genel" odaya taşı
        for uid, user in users_locations.items():
            if user.get("roomName") == room_name:
                user["roomName"] = "Genel"
        
        # Odayı sil
        del rooms[room_name]
        if room_name in room_permissions:
            del room_permissions[room_name]
        
        # Odadaki pinleri sil
        pins_to_delete = [pid for pid, p in pins.items() if p["roomName"] == room_name]
        for pid in pins_to_delete:
            del pins[pid]
        
        # Odadaki skorları sil
        scores_to_delete = [k for k in user_scores.keys() if k.startswith(f"{room_name}_")]
        for k in scores_to_delete:
            del user_scores[k]
        
        # Pin geçmişini sil
        history_to_delete = [k for k in pin_collection_history.keys() if k.startswith(f"{room_name}_")]
        for k in history_to_delete:
            del pin_collection_history[k]
        
        print(f"🗑️ Oda silindi: {room_name} (by {admin_id})")
        return {"status": "success", "message": f"{room_name} odası silindi, üyeler Genel odaya aktarıldı"}
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get_room_password/{room_name}")
def get_room_password(room_name: str, admin_id: str):
    """
    Oda şifresini görüntüle (sadece admin)
    """
    try:
        # "Genel" odanın şifresi yok
        if room_name == "Genel":
            raise HTTPException(status_code=400, detail="Genel odanın şifresi yok")
        
        # Oda var mı?
        if room_name not in rooms:
            raise HTTPException(status_code=404, detail="Oda bulunamadı")
        
        # Kullanıcı admin mi?
        if room_permissions.get(room_name, {}).get("admin") != admin_id:
            raise HTTPException(status_code=403, detail="Sadece admin şifreyi görebilir")
        
        password = rooms[room_name]["password"]
        print(f"🔑 Şifre görüntülendi: {room_name} (by {admin_id})")
        return {"password": password}
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/change_room_password/{room_name}")
def change_room_password(room_name: str, admin_id: str, new_password: str):
    """
    Oda şifresini değiştir (sadece admin)
    """
    try:
        # "Genel" odanın şifresi değiştirilemez
        if room_name == "Genel":
            raise HTTPException(status_code=400, detail="Genel odanın şifresi değiştirilemez")
        
        # Oda var mı?
        if room_name not in rooms:
            raise HTTPException(status_code=404, detail="Oda bulunamadı")
        
        # Kullanıcı admin mi?
        if room_permissions.get(room_name, {}).get("admin") != admin_id:
            raise HTTPException(status_code=403, detail="Sadece admin şifreyi değiştirebilir")
        
        # Şifre kontrolü
        if len(new_password) < 3:
            raise HTTPException(status_code=400, detail="Şifre en az 3 karakter olmalı")
        
        # Şifreyi değiştir
        rooms[room_name]["password"] = new_password
        print(f"🔑 Şifre değiştirildi: {room_name} (by {admin_id})")
        return {"status": "success", "message": "Şifre değiştirildi"}
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ========== GÖRÜNÜRLİK AYARLARI ==========

@app.post("/set_visibility")
def set_visibility(data: VisibilityModel):
    """
    Kullanıcı görünürlük ayarını değiştir
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
    """
    Kullanıcının görünürlük ayarını getir
    """
    return user_visibility.get(user_id, {"mode": "all", "allowed": []})

# ========== KONUM GÜNCELLEMEİŞLEMİ (EN ÖNEMLİ FONKSİYON) ==========

@app.post("/update_location")
def update_location(data: LocationModel):
    """
    Kullanıcının konumunu güncelle
    
    Bu fonksiyon:
    1. Hareketsizlik durumunu kontrol eder (15m < = idle)
    2. Kullanıcı konumunu günceller
    3. Rota geçmişine ekler (hıza göre filtreleme)
    4. Pin toplama sistemini çalıştırır
    """
    try:
        user_key = data.userId
        idle_status = "online"  # Varsayılan: aktif
        idle_minutes = 0
        
        # ========== HAREKETSİZLİK KONTROLÜ ==========
        # Önceki konum var mı?
        if user_key in users_locations:
            old_loc = users_locations[user_key]
            
            # Eski konum ile yeni konum arası mesafe
            distance = calculate_distance(
                old_loc["lat"], old_loc["lng"],
                data.lat, data.lng
            )
            
            # 15 metreden az hareket ettiyse → hareketsiz
            if distance < 15:
                last_move_time = old_loc.get("last_move_time", time.time())
                idle_seconds = time.time() - last_move_time
                idle_minutes = int(idle_seconds / 60)
                
                if idle_minutes > 0:
                    idle_status = "idle"
            else:
                # 15m+ hareket etti, son hareket zamanını güncelle
                old_loc["last_move_time"] = time.time()
        
        # ========== KULLANICI KONUMUNU GÜNCELLE ==========
        users_locations[data.userId] = {
            "userId": data.userId,
            "deviceType": data.deviceType,
            "lat": data.lat,
            "lng": data.lng,
            "altitude": data.altitude,
            "speed": data.speed,
            "animationType": data.animationType,
            "roomName": data.roomName,
            "timestamp": get_local_time(),  # Türkiye saati
            "last_seen": time.time(),       # Son görülme (unix timestamp)
            "last_move_time": users_locations.get(user_key, {}).get("last_move_time", time.time()),
            "idle_status": idle_status,     # "online" veya "idle"
            "idle_minutes": idle_minutes    # Kaç dakika hareketsiz
        }
        
        # ========== ROTA GEÇMİŞİNE EKLE (HIZA GÖRE FİLTRELEME) ==========
        
        # Kullanıcının rota geçmişi yoksa oluştur
        if data.userId not in location_history:
            location_history[data.userId] = []
        
        # Hıza göre minimum mesafe belirle
        speed_kmh = data.speed  # km/h
        
        if speed_kmh > SPEED_THRESHOLD_VEHICLE:  # 30+ km/h (Araç)
            min_distance = MIN_DISTANCE_VEHICLE  # 50 metre
        elif speed_kmh > SPEED_THRESHOLD_RUN:  # 15-30 km/h (Koşu/Bisiklet)
            min_distance = MIN_DISTANCE_RUN  # 20 metre
        elif speed_kmh > SPEED_THRESHOLD_WALK:  # 3-15 km/h (Yürüyüş)
            min_distance = MIN_DISTANCE_WALK  # 10 metre
        else:  # 0-3 km/h (Durgun/Çok yavaş)
            min_distance = MIN_DISTANCE_IDLE  # 5 metre
        
        # Son noktaya olan mesafeyi kontrol et
        should_add = True  # Varsayılan: ekle
        
        if location_history[data.userId]:  # Daha önce nokta var mı?
            last_point = location_history[data.userId][-1]  # Son nokta
            
            # Son noktaya olan mesafe
            distance_from_last = calculate_distance(
                last_point["lat"], last_point["lng"],
                data.lat, data.lng
            )
            
            # Minimum mesafeden azsa ekleme
            if distance_from_last < min_distance:
                should_add = False
                print(f"⏭️ Rota atlandı: {data.userId} (hız: {speed_kmh:.1f}km/h, mesafe: {distance_from_last:.1f}m < {min_distance}m)")
        
        # Minimum mesafeden fazlaysa ekle
        if should_add:
            location_history[data.userId].append({
                "lat": data.lat,
                "lng": data.lng,
                "timestamp": get_local_time(),  # Türkiye saati
                "speed": data.speed,
                "altitude": data.altitude
            })
            
            # ===== ZAMAN BAZLI TEMİZLİK (90 günden eski noktalar) =====
            now = datetime.now(DEFAULT_TIMEZONE)
            cutoff_date = now - timedelta(days=MAX_HISTORY_DAYS)
            
            cleaned_history = []
            for point in location_history[data.userId]:
                try:
                    # Timestamp'i parse et
                    point_time_str = point["timestamp"].replace(' ', 'T')
                    point_time = datetime.fromisoformat(point_time_str)
                    
                    # Timezone bilgisi yoksa ekle
                    if point_time.tzinfo is None:
                        point_time = DEFAULT_TIMEZONE.localize(point_time)
                    
                    # 90 günden yeni mi?
                    if point_time > cutoff_date:
                        cleaned_history.append(point)
                except:
                    # Hatalı timestamp'leri atla
                    pass
            
            location_history[data.userId] = cleaned_history
            
            # ===== NOKTA BAZLI TEMİZLİK (Max 5000 nokta) =====
            if len(location_history[data.userId]) > MAX_POINTS_PER_USER:
                # En eski noktaları sil, en yeni 5000'i tut
                location_history[data.userId] = location_history[data.userId][-MAX_POINTS_PER_USER:]
            
            print(f"📍 Rota eklendi: {data.userId} (hız: {speed_kmh:.1f}km/h, min: {min_distance}m, toplam: {len(location_history[data.userId])} nokta)")
        
        # ========== PIN TOPLAMA SİSTEMİ ==========
        
        # Bu odada pin toplama yetkisi var mı?
        if data.roomName in room_permissions:
            perms = room_permissions[data.roomName]
            
            # Bu kullanıcı pin toplayabilir mi?
            if data.userId in perms["collectors"]:
                
                # Odadaki tüm pinleri kontrol et
                for pin_id, pin_data in list(pins.items()):
                    
                    # Pin bu odada mı?
                    if pin_data["roomName"] != data.roomName:
                        continue
                    
                    # Kullanıcı ile pin arası mesafe
                    dist = calculate_distance(data.lat, data.lng, pin_data["lat"], pin_data["lng"])
                    
                    # ===== 20 METRE YAKIN → TOPLAMA BAŞLA =====
                    if dist <= 20:
                        # Pin henüz toplanmaya başlanmamış mı?
                        if pin_id not in pin_collection_state:
                            # İlk yaklaşan kişi toplayıcı olur
                            pin_collection_state[pin_id] = {
                                "collector": data.userId,
                                "start_time": time.time()  # Başlangıç zamanı
                            }
                            print(f"📍 Pin toplama başladı: {data.userId} → {pin_id}")
                        
                        # Zaten bu kullanıcı mı topluyor?
                        elif pin_collection_state[pin_id]["collector"] == data.userId:
                            pass  # Devam et, henüz 25m'ye çıkmadı
                    
                    # ===== 25 METRE UZAK → PIN TOPLANDI =====
                    elif dist > 25:
                        # Pin toplanma durumunda mı?
                        if pin_id in pin_collection_state:
                            # Bu kullanıcı mı topluyordu?
                            if pin_collection_state[pin_id]["collector"] == data.userId:
                                
                                # ===== SKORU ARTIR =====
                                score_key = f"{data.roomName}_{data.userId}"
                                user_scores[score_key] = user_scores.get(score_key, 0) + 1
                                
                                # ===== GEÇMİŞE KAYDET =====
                                history_key = f"{data.roomName}_{data.userId}"
                                if history_key not in pin_collection_history:
                                    pin_collection_history[history_key] = []
                                
                                collected_time = get_local_time()  # Toplandığı saat (Türkiye)
                                
                                pin_collection_history[history_key].append({
                                    "pinId": pin_id,
                                    "creator": pin_data["creator"],
                                    "timestamp": collected_time,  # Toplandığı saat
                                    "createdAt": pin_data.get("createdAt", pin_data.get("timestamp", "Bilinmiyor")),  # Konulduğu saat
                                    "lat": pin_data["lat"],
                                    "lng": pin_data["lng"]
                                })
                                
                                # ===== PİNİ SİL =====
                                del pins[pin_id]
                                del pin_collection_state[pin_id]
                                
                                # Pin sayacını azalt
                                pin_count_key = f"{data.roomName}_{pin_data['creator']}"
                                if pin_count_key in user_pins_count:
                                    user_pins_count[pin_count_key] -= 1
                                
                                print(f"✅ Pin toplandı: {data.userId} → +1 skor (toplam: {user_scores[score_key]}) - Saat: {collected_time}")
        
        # ========== LOG ==========
        print(f"✅ Konum: {data.userId} ({idle_status}) - 🚪 {data.roomName}")
        return {"status": "success"}
    
    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ========== KONUM LİSTESİ ==========

@app.get("/get_locations/{room_name}")
def get_locations(room_name: str, viewer_id: str = ""):
    """
    Odadaki tüm kullanıcıların konumlarını getir
    
    - 120 saniye (2 dakika) boyunca güncelleme yapmayanları sil
    - Görünürlük ayarlarına göre filtrele
    """
    try:
        now = time.time()
        timeout = 120  # 2 dakika
        to_delete = []
        
        # ===== TIMEOUT KONTROLÜ =====
        # 2 dakika güncelleme yapmayan kullanıcıları bul
        for uid, u in users_locations.items():
            last_seen = u.get("last_seen", 0)
            if now - last_seen > timeout:
                to_delete.append(uid)
        
        # Timeout olan kullanıcıları sil
        for uid in to_delete:
            del users_locations[uid]
            print(f"🧹 Otomatik silindi (timeout): {uid}")
        
        # ===== KONUM LİSTESİNİ OLUŞTUR =====
        locations = []
        
        for u in users_locations.values():
            # Bu kullanıcı bu odada değilse atla
            if u.get("roomName", "Genel") != room_name:
                continue
            
            user_id = u["userId"]
            
            # ===== GÖRÜNÜRLİK KONTROLÜ =====
            visibility = user_visibility.get(user_id, {"mode": "all", "allowed": []})
            
            visible = False
            
            if visibility["mode"] == "all":
                visible = True  # Herkese görünür
            elif visibility["mode"] == "room":
                visible = True  # Oda üyelerine görünür
            elif visibility["mode"] == "custom":
                visible = viewer_id in visibility["allowed"]  # Sadece izin verilenlere
            elif visibility["mode"] == "hidden":
                visible = False  # Kimseye görünmez
            
            # Kendine her zaman görünür
            if not visible and viewer_id != user_id:
                continue
            
            # Listeye ekle
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

# ========== ROTA GEÇMİŞİ ==========

@app.get("/get_location_history/{user_id}")
def get_location_history(user_id: str, period: str = "all"):
    """
    Kullanıcının rota geçmişini getir
    
    Dönemler:
    - "all": Tüm zamanlar
    - "day": Bugün
    - "week": Bu hafta
    - "month": Bu ay (30 gün)
    - "year": Bu yıl (365 gün)
    """
    try:
        history = location_history.get(user_id, [])
        
        # Geçmiş yok
        if not history:
            return []
        
        now = datetime.now(DEFAULT_TIMEZONE)
        filtered = []
        
        # Dönem filtreleme
        for point in history:
            try:
                # Timestamp'i parse et
                point_time_str = point["timestamp"].replace(' ', 'T')
                point_time = datetime.fromisoformat(point_time_str)
                
                # Timezone bilgisi yoksa ekle
                if point_time.tzinfo is None:
                    point_time = DEFAULT_TIMEZONE.localize(point_time)
                
                # Döneme göre filtrele
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
    """
    Kullanıcının rota geçmişini temizle
    """
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

# ========== PIN SİSTEMİ ==========

@app.post("/create_pin")
def create_pin(data: PinCreateModel):
    """
    Haritaya pin koy
    
    - Kullanıcı bir odada sadece 1 pin koyabilir
    - Pin'in konulma saati kaydedilir (Türkiye saati)
    """
    try:
        # ===== PIN SAYISI KONTROLÜ =====
        pin_count_key = f"{data.roomName}_{data.creator}"
        if user_pins_count.get(pin_count_key, 0) >= 1:
            raise HTTPException(status_code=400, detail="Zaten bir pin koydunuz!")
        
        # ===== PIN OLUŞTUR =====
        pin_id = f"{data.roomName}_{data.creator}_{int(time.time())}"  # Unique ID
        created_time = get_local_time()  # Türkiye saati
        
        pins[pin_id] = {
            "id": pin_id,
            "roomName": data.roomName,
            "creator": data.creator,
            "lat": data.lat,
            "lng": data.lng,
            "timestamp": created_time,   # Eski format için (geriye dönük uyumluluk)
            "createdAt": created_time    # Konulma saati (Türkiye saati)
        }
        
        # Pin sayacını artır
        user_pins_count[pin_count_key] = user_pins_count.get(pin_count_key, 0) + 1
        
        print(f"📍 Pin oluşturuldu: {pin_id} - Saat: {created_time}")
        return {"status": "success", "pinId": pin_id}
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get_pins/{room_name}")
def get_pins(room_name: str):
    """
    Odadaki tüm pinleri getir
    
    - Pin'in toplanma durumunu da ekle
    - Toplanan süreyi hesapla
    """
    try:
        # Odadaki pinleri filtrele
        room_pins = [
            p for p in pins.values()
            if p["roomName"] == room_name
        ]
        
        # Her pin için toplama durumu ekle
        for pin in room_pins:
            if pin["id"] in pin_collection_state:
                # Pin toplanıyor
                state = pin_collection_state[pin["id"]]
                pin["collectorId"] = state["collector"]  # Kim topluyor?
                pin["collectionTime"] = int(time.time() - state["start_time"])  # Kaç saniyedir topluyor?
            else:
                # Pin boşta
                pin["collectorId"] = None
                pin["collectionTime"] = 0
        
        return room_pins
    
    except Exception as e:
        print(f"❌ Hata: {e}")
        return []

@app.delete("/remove_pin/{pin_id}")
def remove_pin(pin_id: str, user_id: str):
    """
    Pin'i kaldır
    
    - Sadece pin'i koyan kişi silebilir
    """
    try:
        # Pin var mı?
        if pin_id not in pins:
            raise HTTPException(status_code=404, detail="Pin bulunamadı")
        
        pin_data = pins[pin_id]
        
        # Bu kullanıcının pini mi?
        if pin_data["creator"] != user_id:
            raise HTTPException(status_code=403, detail="Sadece kendi pininizi silebilirsiniz")
        
        # Pin sayacını azalt
        pin_count_key = f"{pin_data['roomName']}_{user_id}"
        if pin_count_key in user_pins_count:
            user_pins_count[pin_count_key] -= 1
        
        # Pin'i sil
        del pins[pin_id]
        
        # Toplama durumunu da sil (varsa)
        if pin_id in pin_collection_state:
            del pin_collection_state[pin_id]
        
        print(f"🗑️ Pin silindi: {pin_id}")
        return {"status": "success"}
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ========== YETKİ SİSTEMİ ==========

@app.post("/set_collector_permission/{room_name}/{user_id}")
def set_collector_permission(room_name: str, user_id: str, admin_id: str, enabled: bool):
    """
    Kullanıcıya pin toplama yetkisi ver/kaldır
    
    - Sadece admin yapabilir
    """
    try:
        # Oda var mı?
        if room_name not in room_permissions:
            raise HTTPException(status_code=404, detail="Oda bulunamadı")
        
        perms = room_permissions[room_name]
        
        # Kullanıcı admin mi?
        if perms["admin"] != admin_id:
            raise HTTPException(status_code=403, detail="Sadece admin yetki verebilir")
        
        # ===== YETKİ VER/KALDIR =====
        if enabled:
            # Yetki ver
            if user_id not in perms["collectors"]:
                perms["collectors"].append(user_id)
        else:
            # Yetki kaldır
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
    """
    Oda yetkilerini getir
    
    Döner:
    - admin: Admin kullanıcı adı
    - collectors: Pin toplayabilen kullanıcılar listesi
    """
    return room_permissions.get(room_name, {"admin": None, "collectors": []})

# ========== SKOR SİSTEMİ ==========

@app.get("/get_scores/{room_name}")
def get_scores(room_name: str):
    """
    Odadaki skorları getir (en yüksekten düşüğe sıralı)
    """
    try:
        scores = {}
        
        # Odadaki skorları filtrele
        for key, score in user_scores.items():
            if key.startswith(f"{room_name}_"):
                user_id = key.replace(f"{room_name}_", "")
                scores[user_id] = score
        
        # Sırala (yüksekten düşüğe)
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        
        # Liste formatında döndür
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
    """
    Kullanıcının toplanan pin geçmişini getir
    
    Her pin için:
    - Kim koymuş
    - Ne zaman konulmuş
    - Ne zaman toplanmış
    - Konum
    """
    try:
        history_key = f"{room_name}_{user_id}"
        history = pin_collection_history.get(history_key, [])
        
        print(f"📜 Pin geçmişi: {user_id} → {len(history)} pin")
        return history
    
    except Exception as e:
        print(f"❌ Hata: {e}")
        return []

# ========== MESAJLAŞMA ==========

@app.post("/send_message")
def send_message(data: MessageModel):
    """
    Mesaj gönder
    
    - Mesajlar iki kullanıcı arasında saklanır
    - Başlangıçta "okunmadı" olarak işaretlenir
    """
    try:
        # Konuşma key'i oluştur (alfabetik sıralı)
        key = get_conversation_key(data.fromUser, data.toUser)
        
        # Konuşma yoksa oluştur
        if key not in conversations:
            conversations[key] = []
        
        # Mesajı ekle
        conversations[key].append({
            "from": data.fromUser,
            "to": data.toUser,
            "message": data.message,
            "timestamp": get_local_time(),  # Türkiye saati
            "read": False  # Henüz okunmadı
        })
        
        print(f"💬 Mesaj: {data.fromUser} → {data.toUser}: {data.message}")
        return {"status": "success"}
    
    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get_conversation/{user1}/{user2}")
def get_conversation(user1: str, user2: str):
    """
    İki kullanıcı arasındaki tüm mesajları getir
    """
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
    """
    Mesajları "okundu" olarak işaretle
    
    - Sadece kendine gelen mesajlar okundu olur
    """
    try:
        key = get_conversation_key(reader, other_user)
        
        # Konuşma var mı?
        if key in conversations:
            # Kendine gelen tüm mesajları "okundu" yap
            for msg in conversations[key]:
                if msg["to"] == reader:
                    msg["read"] = True
        
        # Okunma zamanını kaydet
        read_timestamps[key] = get_local_time()
        
        print(f"👁️ Okundu: {reader} ← {other_user}")
        return {"status": "success"}
    
    except Exception as e:
        print(f"❌ Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get_unread_count/{user_id}")
def get_unread_count(user_id: str):
    """
    Okunmamış mesaj sayısını getir
    
    Döner: {"Ali": 3, "Veli": 5}
    """
    try:
        counts = {}
        
        # Tüm konuşmaları kontrol et
        for key, msgs in conversations.items():
            # Bu kullanıcı bu konuşmada mı?
            if user_id in key:
                # Diğer kullanıcı kim?
                other = key[1] if key[0] == user_id else key[0]
                
                # Okunmamış mesajları say
                unread = sum(
                    1 for m in msgs 
                    if m["to"] == user_id and not m.get("read", False)
                )
                
                # Varsa ekle
                if unread > 0:
                    counts[other] = unread
        
        return counts
    
    except Exception as e:
        print(f"❌ Hata: {e}")
        return {}

# ========== YÖNETİM ENDPOINTLERİ ==========

@app.post("/clear")
def clear_all():
    """
    TÜM VERİLERİ TEMİZLE (Dikkatli kullan!)
    
    - Tüm kullanıcılar
    - Tüm mesajlar
    - Tüm odalar
    - Tüm rotalar
    - Tüm pinler
    - HER ŞEY silinir!
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
    
    print("🧹 Tüm veriler temizlendi")
    return {"status": "success"}

@app.delete("/remove_user/{user_id}")
def remove_user(user_id: str):
    """
    Kullanıcıyı sistemden sil
    
    - Sadece anlık konum silinir
    - Mesajlar, rota geçmişi, vb. kalır
    """
    if user_id in users_locations:
        del users_locations[user_id]
        print(f"🗑️ Kullanıcı silindi: {user_id}")
        return {"status": "success"}
    
    raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
