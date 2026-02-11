import 'package:uuid/uuid.dart';
import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:geolocator/geolocator.dart';
import 'package:http/http.dart' as http;
import 'package:latlong2/latlong.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  runApp(const MyApp());
}

// =====================================================
// APP
// =====================================================
class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return const MaterialApp(
      debugShowCheckedModeBanner: false,
      home: MapPage(),
    );
  }
}

// =====================================================
// MAP PAGE
// =====================================================
class MapPage extends StatefulWidget {
  const MapPage({super.key});

  @override
  State<MapPage> createState() => _MapPageState();
}

class _MapPageState extends State<MapPage> {
  LatLng? myLocation;
  double? myAltitude;
  double mySpeedMs = 0.0; // ✅ m/s
  double mySpeedKmh = 0.0; // ✅ km/h

  List<Map<String, dynamic>> otherUsers = [];

  Timer? timer;
  Timer? _countdownTimer;

  int _countdown = 5;
  final int _updateInterval = 5;

  final String serverUrl = 'https://konum-server.onrender.com';

  // ✅ SABİT KİMLİK
  String? deviceId;

  // ✅ DEĞİŞEBİLEN GÖRÜNEN İSİM
  String? displayName;

  // cihaz tipi
  String? deviceType;

  bool _isInitialized = false;

  Map<String, int> unreadCounts = {};

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _start());
  }

  Future<void> _start() async {
    if (_isInitialized) return;
    _isInitialized = true;

    await _loadOrCreateIdentity();
    await _initLocation();
    await _sendLocation();
    await _fetchOtherUsers();
    await _fetchUnreadCounts();

    // 5 saniyede bir güncelle
    timer = Timer.periodic(const Duration(seconds: 5), (_) async {
      await _initLocation();
      await _sendLocation();
      await _fetchOtherUsers();
      await _fetchUnreadCounts();
      setState(() => _countdown = _updateInterval);
    });

    // her saniye geri sayım
    _countdownTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      setState(() {
        if (_countdown > 0) _countdown--;
      });
    });
  }

  @override
  void dispose() {
    timer?.cancel();
    _countdownTimer?.cancel();
    super.dispose();
  }

  // =====================================================
  // ✅ KİMLİK SİSTEMİ (deviceId sabit)
  // =====================================================
  Future<void> _loadOrCreateIdentity() async {
    final prefs = await SharedPreferences.getInstance();

    // 1) deviceId sabit
    deviceId = prefs.getString("deviceId");

    if (deviceId == null || deviceId!.trim().isEmpty) {
      deviceId = const Uuid().v4();
      await prefs.setString("deviceId", deviceId!);
    }

    // 2) displayName değişebilir
    displayName = prefs.getString("displayName");

    // 3) cihaz tipi
    deviceType = prefs.getString("deviceType");
    deviceType ??= "phone";

    // displayName yoksa sor
    if (displayName == null || displayName!.trim().isEmpty) {
      String? name = await _askUserNameDialog();
      if (name == null || name.trim().isEmpty) name = "Misafir";
      displayName = name.trim();

      String? chosen = await _askDeviceTypeDialog();
      deviceType = chosen ?? "phone";

      await prefs.setString("displayName", displayName!);
      await prefs.setString("deviceType", deviceType!);
    }
  }

  Future<String?> _askUserNameDialog() async {
    final controller = TextEditingController();
    return showDialog<String>(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: const Text("Kullanıcı Adın"),
        content: TextField(
          controller: controller,
          decoration: const InputDecoration(hintText: "Örn: Yuri"),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, controller.text),
            child: const Text("Kaydet"),
          ),
        ],
      ),
    );
  }

  Future<String?> _askDeviceTypeDialog() async {
    return showDialog<String>(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: const Text("Cihaz Tipi"),
        content: const Text("Bu cihaz telefonsa Telefon seç."),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, "phone"),
            child: const Text("📱 Telefon"),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, "pc"),
            child: const Text("💻 PC"),
          ),
        ],
      ),
    );
  }

  // =====================================================
  // KONUM + YÜKSEKLİK + HIZ
  // =====================================================
  Future<void> _initLocation() async {
    LocationPermission permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }
    if (permission == LocationPermission.deniedForever) return;

    Position position = await Geolocator.getCurrentPosition(
      desiredAccuracy: LocationAccuracy.high,
    );

    // speed: m/s gelir (bazı cihazlarda -1 olabilir)
    double speed = position.speed;
    if (speed.isNaN || speed < 0) speed = 0;

    setState(() {
      myLocation = LatLng(position.latitude, position.longitude);
      myAltitude = position.altitude;

      mySpeedMs = speed;
      mySpeedKmh = speed * 3.6;
    });
  }

  // =====================================================
  // SERVER'A KONUM GÖNDER
  // =====================================================
  Future<void> _sendLocation() async {
    if (myLocation == null || deviceId == null) return;

    try {
      await http.post(
        Uri.parse('$serverUrl/update_location'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'deviceId': deviceId,
          'displayName': displayName,
          'deviceType': deviceType,
          'lat': myLocation!.latitude,
          'lng': myLocation!.longitude,
          'altitude': myAltitude ?? 0,
          'speedMs': mySpeedMs,
          'speedKmh': mySpeedKmh,
        }),
      );
    } catch (e) {
      debugPrint("Konum gönderme hatası: $e");
    }
  }

  // =====================================================
  // DİĞERLERİNİ ÇEK
  // =====================================================
  Future<void> _fetchOtherUsers() async {
    try {
      final response = await http.get(Uri.parse('$serverUrl/get_locations'));

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body) as List<dynamic>;

        setState(() {
          otherUsers = data.map((e) {
            return {
              "deviceId": e["deviceId"],
              "displayName": e["displayName"] ?? "Bilinmeyen",
              "lat": e["lat"],
              "lng": e["lng"],
              "deviceType": e["deviceType"] ?? "phone",
              "altitude": (e["altitude"] as num?)?.toDouble() ?? 0.0,
              "speedKmh": (e["speedKmh"] as num?)?.toDouble() ?? 0.0,
            };
          }).toList();
        });
      }
    } catch (e) {
      debugPrint("Diğer kullanıcıları çekme hatası: $e");
    }
  }

  // =====================================================
  // MESAJLAŞMA (deviceId üzerinden)
  // =====================================================
  Future<void> _fetchUnreadCounts() async {
    if (deviceId == null) return;

    try {
      final response = await http.get(
        Uri.parse('$serverUrl/get_unread_count/$deviceId'),
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body) as Map<String, dynamic>;
        setState(() {
          unreadCounts = data.map((key, value) => MapEntry(key, value as int));
        });
      }
    } catch (e) {
      debugPrint("Okunmamış sayı çekme hatası: $e");
    }
  }

  Future<List<Map<String, dynamic>>> _fetchConversation(String otherDeviceId) async {
    if (deviceId == null) return [];

    try {
      final response = await http.get(
        Uri.parse('$serverUrl/get_conversation/$deviceId/$otherDeviceId'),
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body) as List<dynamic>;

        return data.map((e) {
          return {
            "fromDeviceId": e["fromDeviceId"],
            "toDeviceId": e["toDeviceId"],
            "fromName": e["fromName"] ?? "",
            "toName": e["toName"] ?? "",
            "message": e["message"],
            "timestamp": e["timestamp"],
            "read": e["read"] ?? false,
          };
        }).toList();
      }
    } catch (e) {
      debugPrint("Konuşma çekme hatası: $e");
    }

    return [];
  }

  Future<void> _markAsRead(String otherDeviceId) async {
    if (deviceId == null) return;

    try {
      await http.post(
        Uri.parse('$serverUrl/mark_as_read/$deviceId/$otherDeviceId'),
      );
      setState(() => unreadCounts.remove(otherDeviceId));
    } catch (e) {
      debugPrint("Okundu işaretleme hatası: $e");
    }
  }

  Future<void> _sendMessage(String toDeviceId, String message) async {
    if (deviceId == null) return;

    try {
      await http.post(
        Uri.parse('$serverUrl/send_message'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'fromDeviceId': deviceId,
          'fromName': displayName,
          'toDeviceId': toDeviceId,
          'message': message,
        }),
      );

      await _fetchUnreadCounts();
    } catch (e) {
      debugPrint("Mesaj gönderme hatası: $e");
    }
  }

  // =====================================================
  // MESAFE
  // =====================================================
  double _calculateDistance(LatLng point1, LatLng point2) {
    const Distance distance = Distance();
    return distance.as(LengthUnit.Meter, point1, point2);
  }

  String _formatDistance(double meters) {
    if (meters < 1000) return '${meters.toStringAsFixed(0)} m';
    return '${(meters / 1000).toStringAsFixed(2)} km';
  }

  // =====================================================
  // MARKER
  // =====================================================
  Widget _buildUserMarker({
    required String name,
    required String type,
    required bool isMe,
    double? distance,
    double? altitude,
    double? speedKmh,
    int unreadCount = 0,
  }) {
    IconData icon = type == "pc" ? Icons.computer : Icons.phone_android;

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Stack(
          clipBehavior: Clip.none,
          children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              decoration: BoxDecoration(
                color: isMe ? Colors.blue : Colors.black87,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Column(
                children: [
                  Text(
                    name,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 12,
                      fontWeight: FontWeight.bold,
                    ),
                  ),

                  if (distance != null && !isMe)
                    Text(
                      _formatDistance(distance),
                      style: const TextStyle(color: Colors.yellowAccent, fontSize: 10),
                    ),

                  if (altitude != null)
                    Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(Icons.terrain, color: Colors.greenAccent, size: 10),
                        const SizedBox(width: 2),
                        Text(
                          '${altitude.toStringAsFixed(0)} m',
                          style: const TextStyle(color: Colors.greenAccent, fontSize: 10),
                        ),
                      ],
                    ),

                  // ✅ hız
                  if (speedKmh != null)
                    Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(Icons.speed, color: Colors.cyanAccent, size: 10),
                        const SizedBox(width: 2),
                        Text(
                          '${speedKmh.toStringAsFixed(1)} km/h',
                          style: const TextStyle(color: Colors.cyanAccent, fontSize: 10),
                        ),
                      ],
                    ),
                ],
              ),
            ),

            if (!isMe && unreadCount > 0)
              Positioned(
                right: -6,
                top: -6,
                child: Container(
                  padding: const EdgeInsets.all(4),
                  decoration: const BoxDecoration(
                    color: Colors.red,
                    shape: BoxShape.circle,
                  ),
                  child: Text(
                    '$unreadCount',
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 10,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              ),
          ],
        ),
        const SizedBox(height: 4),
        Icon(icon, size: 40, color: isMe ? Colors.blue : Colors.red),
      ],
    );
  }

  // =====================================================
  // COUNTDOWN
  // =====================================================
  Widget _buildCountdownWidget() {
    Color color;
    if (_countdown <= 1) {
      color = Colors.red;
    } else if (_countdown <= 3) {
      color = Colors.orange;
    } else {
      color = Colors.green;
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: Colors.black.withOpacity(0.7),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          SizedBox(
            width: 18,
            height: 18,
            child: CircularProgressIndicator(
              value: _countdown / _updateInterval,
              strokeWidth: 2.5,
              color: color,
              backgroundColor: Colors.white24,
            ),
          ),
          const SizedBox(width: 8),
          Text(
            '${_countdown}s',
            style: TextStyle(
              color: color,
              fontSize: 14,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(width: 6),
          const Icon(Icons.my_location, color: Colors.white70, size: 14),
          const SizedBox(width: 4),
          const Text(
            'Güncelleniyor',
            style: TextStyle(color: Colors.white70, fontSize: 11),
          ),
        ],
      ),
    );
  }

  // =====================================================
  // INFO PANEL
  // =====================================================
  Widget _buildInfoPanel() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: Colors.black.withOpacity(0.7),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.location_on, color: Colors.blueAccent, size: 14),
              const SizedBox(width: 4),
              Text(
                myLocation != null
                    ? '${myLocation!.latitude.toStringAsFixed(5)}, ${myLocation!.longitude.toStringAsFixed(5)}'
                    : '---',
                style: const TextStyle(color: Colors.white, fontSize: 11),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.terrain, color: Colors.greenAccent, size: 14),
              const SizedBox(width: 4),
              Text(
                myAltitude != null
                    ? 'Yükseklik: ${myAltitude!.toStringAsFixed(1)} m'
                    : 'Yükseklik: ---',
                style: const TextStyle(color: Colors.greenAccent, fontSize: 11),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.speed, color: Colors.cyanAccent, size: 14),
              const SizedBox(width: 4),
              Text(
                'Hız: ${mySpeedKmh.toStringAsFixed(1)} km/h',
                style: const TextStyle(color: Colors.cyanAccent, fontSize: 11),
              ),
            ],
          ),
        ],
      ),
    );
  }

  // =====================================================
  // CHAT SCREEN OPEN
  // =====================================================
  void _showChatScreen(String otherDeviceId, String otherName) async {
    await _markAsRead(otherDeviceId);

    List<Map<String, dynamic>> conversation = await _fetchConversation(otherDeviceId);
    if (!mounted) return;

    await Navigator.push(
      context,
      MaterialPageRoute(
        builder: (context) => ChatScreen(
          myDeviceId: deviceId!,
          myName: displayName ?? "Ben",
          otherDeviceId: otherDeviceId,
          otherName: otherName,
          serverUrl: serverUrl,
          initialConversation: conversation,
          onSendMessage: (message) async {
            await _sendMessage(otherDeviceId, message);
            return await _fetchConversation(otherDeviceId);
          },
          onRead: () async {
            await _markAsRead(otherDeviceId);
            await _fetchUnreadCounts();
          },
        ),
      ),
    );

    await _fetchUnreadCounts();
  }

  // =====================================================
  // UI
  // =====================================================
  @override
  Widget build(BuildContext context) {
    int totalUnread = unreadCounts.values.fold(0, (sum, count) => sum + count);

    return Scaffold(
      appBar: AppBar(
        title: Text("Konum Takip (${displayName ?? "..."})"),
        actions: [
          if (totalUnread > 0)
            Padding(
              padding: const EdgeInsets.all(8.0),
              child: Chip(
                label: Text('$totalUnread yeni mesaj'),
                backgroundColor: Colors.red,
                labelStyle: const TextStyle(
                  color: Colors.white,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),

          // ✅ Kullanıcı adını değiştir
          IconButton(
            icon: const Icon(Icons.edit),
            onPressed: () async {
              final prefs = await SharedPreferences.getInstance();
              String? newName = await _askUserNameDialog();
              if (newName == null || newName.trim().isEmpty) return;

              setState(() => displayName = newName.trim());
              await prefs.setString("displayName", displayName!);

              // server'a hemen güncelleme gönder
              await _sendLocation();
            },
          ),

          // prefs sıfırla
          IconButton(
            icon: const Icon(Icons.delete),
            onPressed: () async {
              final prefs = await SharedPreferences.getInstance();
              await prefs.clear();
              Navigator.pushReplacement(
                context,
                MaterialPageRoute(builder: (context) => const MapPage()),
              );
            },
          ),

          // manuel yenile
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () async {
              await _initLocation();
              await _sendLocation();
              await _fetchOtherUsers();
              await _fetchUnreadCounts();
              setState(() => _countdown = _updateInterval);
            },
          ),
        ],
      ),
      body: myLocation == null
          ? const Center(child: CircularProgressIndicator())
          : Stack(
              children: [
                FlutterMap(
                  options: MapOptions(
                    initialCenter: myLocation!,
                    initialZoom: 15,
                  ),
                  children: [
                    TileLayer(
                      urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                      userAgentPackageName: 'com.example.konum_app_new',
                    ),
                    MarkerLayer(
                      markers: [
                        // BEN
                        Marker(
                          point: myLocation!,
                          width: 150,
                          height: 120,
                          child: _buildUserMarker(
                            name: displayName ?? "Ben",
                            type: deviceType ?? "phone",
                            isMe: true,
                            altitude: myAltitude,
                            speedKmh: mySpeedKmh,
                          ),
                        ),

                        // DİĞERLERİ
                        ...otherUsers
                            .where((u) => u["deviceId"] != deviceId)
                            .map((u) {
                          final userPoint = LatLng(u["lat"], u["lng"]);
                          final distance = _calculateDistance(myLocation!, userPoint);

                          final otherDeviceId = u["deviceId"];
                          final otherName = u["displayName"] ?? "Bilinmeyen";
                          final unreadCount = unreadCounts[otherDeviceId] ?? 0;

                          return Marker(
                            point: userPoint,
                            width: 150,
                            height: 120,
                            child: GestureDetector(
                              onTap: () => _showChatScreen(otherDeviceId, otherName),
                              child: _buildUserMarker(
                                name: otherName,
                                type: u["deviceType"],
                                isMe: false,
                                distance: distance,
                                altitude: (u["altitude"] as num?)?.toDouble(),
                                speedKmh: (u["speedKmh"] as num?)?.toDouble(),
                                unreadCount: unreadCount,
                              ),
                            ),
                          );
                        }).toList(),
                      ],
                    ),
                  ],
                ),

                Positioned(
                  left: 12,
                  bottom: 20,
                  child: _buildInfoPanel(),
                ),

                Positioned(
                  right: 12,
                  bottom: 20,
                  child: _buildCountdownWidget(),
                ),
              ],
            ),
    );
  }
}

// =====================================================
// CHAT SCREEN
// =====================================================
class ChatScreen extends StatefulWidget {
  final String myDeviceId;
  final String myName;

  final String otherDeviceId;
  final String otherName;

  final String serverUrl;

  final List<Map<String, dynamic>> initialConversation;

  final Future<List<Map<String, dynamic>>> Function(String) onSendMessage;
  final Future<void> Function() onRead;

  const ChatScreen({
    super.key,
    required this.myDeviceId,
    required this.myName,
    required this.otherDeviceId,
    required this.otherName,
    required this.serverUrl,
    required this.initialConversation,
    required this.onSendMessage,
    required this.onRead,
  });

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final TextEditingController _controller = TextEditingController();
  final ScrollController _scrollController = ScrollController();

  late List<Map<String, dynamic>> _messages;
  Timer? _refreshTimer;

  @override
  void initState() {
    super.initState();
    _messages = List.from(widget.initialConversation);

    WidgetsBinding.instance.addPostFrameCallback((_) => _scrollToBottom());

    _refreshTimer = Timer.periodic(const Duration(seconds: 3), (_) async {
      await _refreshMessages();
    });
  }

  @override
  void dispose() {
    _refreshTimer?.cancel();
    _controller.dispose();
    _scrollController.dispose();
    widget.onRead();
    super.dispose();
  }

  Future<void> _refreshMessages() async {
    try {
      final response = await http.get(
        Uri.parse(
          '${widget.serverUrl}/get_conversation/${widget.myDeviceId}/${widget.otherDeviceId}',
        ),
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body) as List<dynamic>;

        final newMessages = data.map((e) {
          return {
            "fromDeviceId": e["fromDeviceId"],
            "toDeviceId": e["toDeviceId"],
            "fromName": e["fromName"] ?? "",
            "toName": e["toName"] ?? "",
            "message": e["message"],
            "timestamp": e["timestamp"],
            "read": e["read"] ?? false,
          };
        }).toList();

        if (newMessages.length != _messages.length) {
          setState(() => _messages = newMessages);
          _scrollToBottom();

          await http.post(
            Uri.parse(
              '${widget.serverUrl}/mark_as_read/${widget.myDeviceId}/${widget.otherDeviceId}',
            ),
          );
        }
      }
    } catch (e) {
      debugPrint("Mesaj yenileme hatası: $e");
    }
  }

  void _scrollToBottom() {
    if (_scrollController.hasClients) {
      _scrollController.animateTo(
        _scrollController.position.maxScrollExtent,
        duration: const Duration(milliseconds: 300),
        curve: Curves.easeOut,
      );
    }
  }

  Future<void> _send() async {
    if (_controller.text.trim().isEmpty) return;

    String message = _controller.text.trim();
    _controller.clear();

    List<Map<String, dynamic>> updated = await widget.onSendMessage(message);

    setState(() => _messages = updated);
    _scrollToBottom();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Row(
          children: [
            const CircleAvatar(
              radius: 16,
              child: Icon(Icons.person, size: 18),
            ),
            const SizedBox(width: 8),
            Text(widget.otherName),
          ],
        ),
        actions: [
          Padding(
            padding: const EdgeInsets.all(8.0),
            child: Center(
              child: Text(
                '${_messages.length} mesaj',
                style: const TextStyle(fontSize: 12),
              ),
            ),
          ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: _messages.isEmpty
                ? const Center(
                    child: Text(
                      'Henüz mesaj yok.\nİlk mesajı sen gönder! 👋',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: Colors.grey),
                    ),
                  )
                : ListView.builder(
                    controller: _scrollController,
                    padding: const EdgeInsets.all(16),
                    itemCount: _messages.length,
                    itemBuilder: (context, index) {
                      final msg = _messages[index];
                      final isMe = msg['fromDeviceId'] == widget.myDeviceId;

                      return Align(
                        alignment: isMe ? Alignment.centerRight : Alignment.centerLeft,
                        child: Container(
                          margin: const EdgeInsets.symmetric(vertical: 4),
                          padding: const EdgeInsets.all(12),
                          constraints: BoxConstraints(
                            maxWidth: MediaQuery.of(context).size.width * 0.7,
                          ),
                          decoration: BoxDecoration(
                            color: isMe ? Colors.blue[100] : Colors.grey[300],
                            borderRadius: BorderRadius.only(
                              topLeft: const Radius.circular(12),
                              topRight: const Radius.circular(12),
                              bottomLeft: Radius.circular(isMe ? 12 : 0),
                              bottomRight: Radius.circular(isMe ? 0 : 12),
                            ),
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                msg['message'],
                                style: const TextStyle(fontSize: 14),
                              ),
                              const SizedBox(height: 4),
                              Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  Text(
                                    msg['timestamp'].toString().substring(11, 16),
                                    style: TextStyle(
                                      fontSize: 10,
                                      color: Colors.grey[600],
                                    ),
                                  ),
                                  if (isMe) ...[
                                    const SizedBox(width: 4),
                                    Icon(
                                      msg['read'] == true ? Icons.done_all : Icons.done,
                                      size: 12,
                                      color: msg['read'] == true ? Colors.blue : Colors.grey,
                                    ),
                                  ],
                                ],
                              ),
                            ],
                          ),
                        ),
                      );
                    },
                  ),
          ),
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: Colors.grey[100],
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withOpacity(0.1),
                  blurRadius: 4,
                ),
              ],
            ),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _controller,
                    decoration: const InputDecoration(
                      hintText: 'Mesajını yaz...',
                      border: OutlineInputBorder(),
                      contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                    ),
                    maxLines: null,
                    onSubmitted: (_) => _send(),
                    textInputAction: TextInputAction.send,
                  ),
                ),
                const SizedBox(width: 8),
                IconButton(
                  icon: const Icon(Icons.send, color: Colors.blue),
                  onPressed: _send,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
