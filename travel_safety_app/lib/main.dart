import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import 'dart:convert';

import 'package:geolocator/geolocator.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:cloud_firestore/cloud_firestore.dart';

Future<void> main() async {
  // Ensure that the Flutter engine is fully initialized before using Firebase plugins
  WidgetsFlutterBinding.ensureInitialized();

  // Initialize Firebase with the specific Web App configuration keys
  await Firebase.initializeApp(
    options: const FirebaseOptions(
      apiKey: "AIzaSyAq5sy-RUCnrqcBYv2xEhCFA1QJ4MikfM8",
      authDomain: "travelsafetyai-96476.firebaseapp.com",
      projectId: "travelsafetyai-96476",
      storageBucket: "travelsafetyai-96476.firebasestorage.app",
      messagingSenderId: "71692905601",
      appId: "1:71692905601:web:6462c65e403be86d7e7180",
    ),
  );

  // Run the main Flutter application
  runApp(const TapropathApp());
}

class TapropathApp extends StatelessWidget {
  const TapropathApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Tapropath',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFFF5C945),
          primary: const Color(0xFF1C1C1E),
          secondary: const Color(0xFFD4AF37),
        ),
        useMaterial3: true,
        scaffoldBackgroundColor: const Color(
          0xFFFAF8F5,
        ), // Warm off-white/beige background
        fontFamily: 'Roboto',
      ),
      home: const RiskAssessmentScreen(),
    );
  }
}

class RiskAssessmentScreen extends StatefulWidget {
  const RiskAssessmentScreen({super.key});

  @override
  State<RiskAssessmentScreen> createState() => _RiskAssessmentScreenState();
}

class _RiskAssessmentScreenState extends State<RiskAssessmentScreen> {
  // Controller to manage the text input for the destination location field
  final TextEditingController _locationController = TextEditingController();
  final ScrollController _scrollController = ScrollController();

  // Bottom Navigation selected index
  int _selectedIndex = 0;

  // State variables to track the status of the safety checklists
  bool isEmergencyContactsUpdated = false;
  bool isWeatherAnalyzed = false;

  // Variables to store the results from the AI risk assessment backend
  double? riskScore;
  String riskLevel = "Not Assessed";

  // Lists to store Explainable AI causes and recommendations separately
  List<dynamic> riskCauses = [];
  List<dynamic> recommendations = [];

  // Loading state flags
  bool isLoading = false;
  bool isFetchingLocation = false;

  // OpenStreetMap specific variables
  final MapController mapController = MapController();
  LatLng _currentMapPosition = const LatLng(
    6.9271,
    79.8612,
  ); // Default: Colombo, Sri Lanka

  // Brand Colors matching the new UI design
  static const Color kBgBeige = Color(0xFFFAF8F5);
  static const Color kDarkCard = Color(0xFF1C1C1E);
  static const Color kGoldButton = Color(0xFFF5C945);
  static const Color kGoldIcon = Color(0xFFD4AF37);
  static const Color kNavBarBg = Color(0xFFF5EFE6);
  static const Color kNavIndicator = Color(0xFFEBE3D5);
  static const Color kBorderColor = Color(0xFFEAE6DF);

  @override
  void dispose() {
    _locationController.dispose();
    _scrollController.dispose();
    mapController.dispose();
    super.dispose();
  }

  // Helper function to return a specific color based on the analyzed risk level
  Color _getRiskColor(String level) {
    if (level == "High Risk") return Colors.redAccent;
    if (level == "Moderate Risk") return Colors.orange;
    if (level == "Low Risk") return Colors.green;
    return const Color(0xFFD4AF37); // Gold accent before assessment
  }

  // Asynchronous function to search location using Nominatim API
  Future<void> _searchLocation(String query) async {
    if (query.trim().isEmpty) return;

    setState(() {
      isFetchingLocation = true; // Show loading indicator
    });

    try {
      // OpenStreetMap Nominatim API geocoding request
      final url = Uri.parse(
        'https://nominatim.openstreetmap.org/search?q=$query&format=json&limit=1',
      );
      final response = await http.get(
        url,
        headers: {
          'User-Agent': 'TapropathApp_PP1', // Required by Nominatim policy
        },
      );

      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        if (data.isNotEmpty) {
          final lat = double.parse(data[0]['lat']);
          final lon = double.parse(data[0]['lon']);

          setState(() {
            _currentMapPosition = LatLng(lat, lon);
          });

          // Move the map camera to the searched location
          mapController.move(_currentMapPosition, 14.0);
          _showSnackBar('Location found!', kDarkCard);
        } else {
          _showSnackBar(
            'Location not found. Try a different name.',
            Colors.orange,
          );
        }
      } else {
        _showSnackBar('Server error fetching location.', Colors.red);
      }
    } catch (e) {
      _showSnackBar('Network error: $e', Colors.red);
    } finally {
      setState(() {
        isFetchingLocation = false;
      });
    }
  }

  // Asynchronous function to fetch the user's current GPS location
  Future<void> _getCurrentLocation() async {
    setState(() {
      isFetchingLocation = true;
    });

    bool serviceEnabled;
    LocationPermission permission;

    try {
      serviceEnabled = await Geolocator.isLocationServiceEnabled();
      if (!serviceEnabled) {
        _showSnackBar('Location services are disabled.', Colors.red);
        return;
      }

      permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
        if (permission == LocationPermission.denied) {
          _showSnackBar('Location permissions denied.', Colors.red);
          return;
        }
      }

      if (permission == LocationPermission.deniedForever) {
        _showSnackBar(
          'Location permissions are permanently denied.',
          Colors.red,
        );
        return;
      }

      Position position = await Geolocator.getCurrentPosition(
        desiredAccuracy: LocationAccuracy.high,
      );

      setState(() {
        _locationController.text =
            "${position.latitude}, ${position.longitude}";
        _currentMapPosition = LatLng(position.latitude, position.longitude);
      });

      mapController.move(_currentMapPosition, 14.0);
      _showSnackBar('Location fetched successfully!', kDarkCard);
    } catch (e) {
      _showSnackBar('Error getting location: $e', Colors.red);
    } finally {
      setState(() {
        isFetchingLocation = false;
      });
    }
  }

  // Helper function to display floating snackbar messages at the bottom of the screen
  void _showSnackBar(String message, Color color) {
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(message, style: const TextStyle(color: Colors.white)),
          backgroundColor: color,
          behavior: SnackBarBehavior.floating,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(10),
          ),
        ),
      );
    }
  }

  // Helper to scroll down to the interactive risk planner section
  void _scrollToAssessment() {
    _scrollController.animateTo(
      420,
      duration: const Duration(milliseconds: 500),
      curve: Curves.easeInOut,
    );
  }

  // Asynchronous function to submit user data to the Python/FastAPI backend for risk assessment
  Future<void> _submitAssessment() async {
    if (_locationController.text.trim().isEmpty) {
      _showSnackBar(
        'Please enter a destination location or coordinates first.',
        Colors.redAccent,
      );
      return;
    }

    setState(() {
      isLoading = true;
      riskCauses.clear();
      recommendations.clear();
    });

    try {
      int hour = DateTime.now().hour;
      String timeOfDay = (hour >= 18 || hour < 6) ? "Night" : "Day";

      final url = Uri.parse('http://127.0.0.1:8000/api/calculate-risk');

      final Map<String, dynamic> requestData = {
        "location": _locationController.text.trim(),
        "emergency_contacts_updated": isEmergencyContactsUpdated,
        "weather_analyzed": isWeatherAnalyzed,
        "time_of_day": timeOfDay,
      };

      final response = await http.post(
        url,
        headers: {"Content-Type": "application/json"},
        body: json.encode(requestData),
      );

      if (response.statusCode == 200) {
        final responseData = json.decode(response.body);

        setState(() {
          riskScore = (responseData['risk_score'] as num).toDouble();
          riskLevel = responseData['risk_level'];
          riskCauses = List<dynamic>.from(responseData['risk_causes'] ?? []);
          recommendations = List<dynamic>.from(
            responseData['recommendations'] ?? [],
          );
        });

        // --- Save the results to Firebase Firestore ---
        try {
          await FirebaseFirestore.instance.collection('assessments').add({
            'location': _locationController.text.trim(),
            'latitude': _currentMapPosition.latitude,
            'longitude': _currentMapPosition.longitude,
            'risk_score': riskScore,
            'risk_level': riskLevel,
            'risk_causes': riskCauses,
            'recommendations': recommendations,
            'emergency_contacts_updated': isEmergencyContactsUpdated,
            'weather_analyzed': isWeatherAnalyzed,
            'time_of_day': timeOfDay,
            'timestamp': FieldValue.serverTimestamp(),
          });

          _showSnackBar(
            'Assessment Complete & Saved to Database!',
            Colors.green[700]!,
          );
        } catch (dbError) {
          _showSnackBar(
            'Assessment Complete, but failed to save to DB.',
            Colors.orange[800]!,
          );
          print('Firestore Error: $dbError');
        }
      } else {
        throw Exception(
          "Failed to get risk score. Server error ${response.statusCode}",
        );
      }
    } catch (error) {
      _showSnackBar('Error connecting to the Python server', Colors.red);
    } finally {
      setState(() {
        isLoading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: kBgBeige,
      // --- Top Application Bar matching TAPROPATH UI ---
      appBar: AppBar(
        backgroundColor: kBgBeige,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        centerTitle: false,
        title: const Padding(
          padding: EdgeInsets.only(left: 8.0),
          child: Text(
            'TAPROPATH',
            style: TextStyle(
              fontWeight: FontWeight.w800,
              fontSize: 18,
              letterSpacing: 2.0,
              color: kDarkCard,
            ),
          ),
        ),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 12.0),
            child: IconButton(
              icon: const Icon(
                Icons.notifications_none_outlined,
                color: kDarkCard,
                size: 24,
              ),
              onPressed: () {
                _showSnackBar('No new safety alerts right now.', kDarkCard);
              },
              tooltip: 'Notifications',
            ),
          ),
        ],
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(1.0),
          child: Container(color: kBorderColor, height: 1.0),
        ),
      ),

      // --- Scrollable Body Content ---
      body: SingleChildScrollView(
        controller: _scrollController,
        padding: const EdgeInsets.symmetric(horizontal: 24.0, vertical: 24.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // --- Header Section: Explore Sri Lanka ---
            const Text(
              'Explore Sri Lanka',
              style: TextStyle(
                fontSize: 28,
                fontWeight: FontWeight.bold,
                color: kDarkCard,
                letterSpacing: -0.5,
              ),
            ),
            const SizedBox(height: 6),
            Text(
              'Plan your next adventure with personalized AI recommendations.',
              style: TextStyle(fontSize: 14, color: Colors.grey[600]),
            ),
            const SizedBox(height: 24),

            // --- Dark Hero Card: Plan your perfect trip ---
            Container(
              decoration: BoxDecoration(
                color: kDarkCard,
                borderRadius: BorderRadius.circular(18),
                boxShadow: const [
                  BoxShadow(
                    color: Colors.black12,
                    blurRadius: 10,
                    offset: Offset(0, 4),
                  ),
                ],
              ),
              padding: const EdgeInsets.all(24.0),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Icon(
                    Icons.auto_awesome_outlined,
                    color: kGoldButton,
                    size: 30,
                  ),
                  const SizedBox(height: 16),
                  const Text(
                    'Plan your perfect trip',
                    style: TextStyle(
                      fontSize: 20,
                      fontWeight: FontWeight.bold,
                      color: Colors.white,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    'Tell us what you love and TAPROPATH will find destinations that match your preferences.',
                    style: TextStyle(fontSize: 13.5, color: Colors.grey[350]),
                  ),
                  const SizedBox(height: 22),
                  SizedBox(
                    width: double.infinity,
                    height: 48,
                    child: ElevatedButton(
                      onPressed: _scrollToAssessment,
                      style: ElevatedButton.styleFrom(
                        backgroundColor: kGoldButton,
                        foregroundColor: kDarkCard,
                        elevation: 0,
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(10),
                        ),
                      ),
                      child: const Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Text(
                            'Start Planning',
                            style: TextStyle(
                              fontSize: 14.5,
                              fontWeight: FontWeight.w700,
                              color: kDarkCard,
                            ),
                          ),
                          SizedBox(width: 8),
                          Icon(Icons.arrow_forward, size: 18, color: kDarkCard),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 28),

            // --- Discover Section (Nature & Beaches Cards) ---
            const Text(
              'Discover',
              style: TextStyle(
                fontSize: 20,
                fontWeight: FontWeight.bold,
                color: kDarkCard,
              ),
            ),
            const SizedBox(height: 14),
            Row(
              children: [
                Expanded(
                  child: _buildDiscoverCard(
                    icon: Icons.terrain_outlined,
                    title: 'Nature',
                    onTap: () {
                      setState(() {
                        _locationController.text = "Ella";
                        _currentMapPosition = const LatLng(6.8667, 81.0466);
                      });
                      mapController.move(_currentMapPosition, 13.0);
                      _scrollToAssessment();
                    },
                  ),
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: _buildDiscoverCard(
                    icon: Icons.beach_access_outlined,
                    title: 'Beaches',
                    onTap: () {
                      setState(() {
                        _locationController.text = "Mirissa";
                        _currentMapPosition = const LatLng(5.9483, 80.4716);
                      });
                      mapController.move(_currentMapPosition, 13.0);
                      _scrollToAssessment();
                    },
                  ),
                ),
              ],
            ),
            const SizedBox(height: 32),

            // --- Section Header for Destination Assessment ---
            Row(
              children: [
                const Icon(Icons.shield_outlined, color: kGoldIcon, size: 22),
                const SizedBox(width: 8),
                const Text(
                  'Tapropath - Destination Assessment',
                  style: TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                    color: kDarkCard,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),

            // --- Destination Location Input Field ---
            TextField(
              controller: _locationController,
              onSubmitted: (value) =>
                  _searchLocation(value), // Added mapping for Enter key
              decoration: InputDecoration(
                filled: true,
                fillColor: Colors.white,
                labelText: 'Destination Location (e.g., Nuwara Eliya, Kandy, or tap map)',
                labelStyle: TextStyle(color: Colors.grey[700], fontSize: 14),
                hintText: 'Enter city name, coordinates, or tap map',
                prefixIcon: const Icon(
                  Icons.location_on_outlined,
                  color: kGoldIcon,
                ),
                suffixIcon: isFetchingLocation
                    ? const Padding(
                        padding: EdgeInsets.all(12.0),
                        child: SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: kGoldIcon,
                          ),
                        ),
                      )
                    : IconButton(
                        icon: const Icon(Icons.my_location, color: kDarkCard),
                        onPressed: _getCurrentLocation,
                        tooltip: 'Get Current GPS Location',
                      ),
                enabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(14),
                  borderSide: const BorderSide(color: kBorderColor, width: 1.5),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(14),
                  borderSide: const BorderSide(color: kGoldIcon, width: 2),
                ),
              ),
            ),
            const SizedBox(height: 20),

            // --- OpenStreetMap Integration View with Tap-to-Select ---
            Container(
              height: 260,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(16),
                border: Border.all(color: kBorderColor, width: 1.5),
                boxShadow: const [
                  BoxShadow(
                    color: Colors.black12,
                    blurRadius: 6,
                    spreadRadius: 1,
                  ),
                ],
              ),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(15),
                child: FlutterMap(
                  mapController: mapController,
                  options: MapOptions(
                    initialCenter: _currentMapPosition,
                    initialZoom: 14.0,
                    onTap: (tapPosition, latLng) {
                      setState(() {
                        _currentMapPosition = latLng;
                        _locationController.text =
                            "${latLng.latitude}, ${latLng.longitude}";
                      });
                      _showSnackBar('Location selected from map!', kDarkCard);
                    },
                  ),
                  children: [
                    TileLayer(
                      urlTemplate:
                          'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                      userAgentPackageName: 'com.example.travel_safety_app',
                    ),
                    MarkerLayer(
                      markers: [
                        Marker(
                          point: _currentMapPosition,
                          width: 44,
                          height: 44,
                          child: const Icon(
                            Icons.location_pin,
                            color: kDarkCard,
                            size: 42,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 20),

            // --- Pre-Travel Safety Checklist Section ---
            Container(
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(16),
                border: Border.all(color: kBorderColor, width: 1.5),
              ),
              padding: const EdgeInsets.symmetric(vertical: 10.0),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Padding(
                    padding: EdgeInsets.only(left: 16.0, bottom: 4.0, top: 8.0),
                    child: Text(
                      'Pre-Travel Safety Checklist',
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.bold,
                        color: kDarkCard,
                      ),
                    ),
                  ),
                  CheckboxListTile(
                    title: const Text(
                      'Emergency Contacts Updated',
                      style: TextStyle(fontSize: 14.5, color: kDarkCard),
                    ),
                    activeColor: kDarkCard,
                    checkColor: kGoldButton,
                    value: isEmergencyContactsUpdated,
                    onChanged: (bool? value) {
                      setState(() {
                        isEmergencyContactsUpdated = value ?? false;
                      });
                    },
                  ),
                  CheckboxListTile(
                    title: const Text(
                      'Weather & Location Analyzed',
                      style: TextStyle(fontSize: 14.5, color: kDarkCard),
                    ),
                    activeColor: kDarkCard,
                    checkColor: kGoldButton,
                    value: isWeatherAnalyzed,
                    onChanged: (bool? value) {
                      setState(() {
                        isWeatherAnalyzed = value ?? false;
                      });
                    },
                  ),
                ],
              ),
            ),
            const SizedBox(height: 24),

            // --- Assessment Submission Button (Golden Theme) ---
            SizedBox(
              height: 52,
              child: ElevatedButton(
                onPressed: isLoading ? null : _submitAssessment,
                style: ElevatedButton.styleFrom(
                  backgroundColor: kGoldButton,
                  foregroundColor: kDarkCard,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(12),
                  ),
                  elevation: 0,
                ),
                child: isLoading
                    ? const SizedBox(
                        height: 24,
                        width: 24,
                        child: CircularProgressIndicator(
                          color: kDarkCard,
                          strokeWidth: 2.5,
                        ),
                      )
                    : const Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Text(
                            'Check Destination Risk',
                            style: TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.bold,
                              color: kDarkCard,
                            ),
                          ),
                          SizedBox(width: 8),
                          Icon(Icons.arrow_forward, size: 18, color: kDarkCard),
                        ],
                      ),
              ),
            ),
            const SizedBox(height: 28),

            // --- AI Safety Risk Score Display Card ---
            Container(
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(18),
                border: Border.all(color: kBorderColor, width: 1.5),
              ),
              padding: const EdgeInsets.symmetric(
                vertical: 28.0,
                horizontal: 20.0,
              ),
              child: Column(
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      const Icon(Icons.security, color: kGoldIcon),
                      const SizedBox(width: 8),
                      const Text(
                        'Destination AI Safety Risk Score',
                        style: TextStyle(
                          fontSize: 17,
                          fontWeight: FontWeight.bold,
                          color: kDarkCard,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 24),
                  Stack(
                    alignment: Alignment.center,
                    children: [
                      SizedBox(
                        height: 130,
                        width: 130,
                        child: CircularProgressIndicator(
                          value: riskScore != null ? (riskScore! / 100) : 0,
                          strokeWidth: 12,
                          backgroundColor: kNavBarBg,
                          valueColor: AlwaysStoppedAnimation<Color>(
                            _getRiskColor(riskLevel),
                          ),
                        ),
                      ),
                      Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Text(
                            riskScore != null
                                ? "${riskScore!.toStringAsFixed(1)}%"
                                : "N/A",
                            style: TextStyle(
                              fontSize: 26,
                              fontWeight: FontWeight.bold,
                              color: kDarkCard,
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                  const SizedBox(height: 18),
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 18,
                      vertical: 8,
                    ),
                    decoration: BoxDecoration(
                      color: _getRiskColor(riskLevel).withOpacity(0.12),
                      borderRadius: BorderRadius.circular(30),
                    ),
                    child: Text(
                      riskLevel,
                      style: TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.bold,
                        color: _getRiskColor(riskLevel),
                      ),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 20),

            // --- Explainable AI Causes & Recommendations Display Cards ---
            if (riskCauses.isNotEmpty || recommendations.isNotEmpty) ...[
              Container(
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: kBorderColor, width: 1.5),
                ),
                padding: const EdgeInsets.all(18.0),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Row(
                      children: [
                        Icon(Icons.warning_amber_rounded, color: Colors.orange),
                        SizedBox(width: 8),
                        Text(
                          "Identified Risk Factors (Causes):",
                          style: TextStyle(
                            fontWeight: FontWeight.bold,
                            fontSize: 15.5,
                            color: kDarkCard,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 10),
                    ...riskCauses.map(
                      (cause) => Padding(
                        padding: const EdgeInsets.symmetric(vertical: 4.0),
                        child: Text(
                          "• $cause",
                          style: const TextStyle(
                            fontSize: 14,
                            color: Colors.black87,
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 16),
              Container(
                decoration: BoxDecoration(
                  color: kDarkCard,
                  borderRadius: BorderRadius.circular(16),
                ),
                padding: const EdgeInsets.all(18.0),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Row(
                      children: [
                        Icon(Icons.auto_awesome, color: kGoldButton, size: 20),
                        SizedBox(width: 8),
                        Text(
                          "Actionable Recommendations:",
                          style: TextStyle(
                            fontWeight: FontWeight.bold,
                            fontSize: 15.5,
                            color: kGoldButton,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 10),
                    ...recommendations.map(
                      (rec) => Padding(
                        padding: const EdgeInsets.symmetric(vertical: 4.0),
                        child: Text(
                          "• $rec",
                          style: const TextStyle(
                            fontSize: 14,
                            color: Colors.white,
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
            const SizedBox(height: 24),
          ],
        ),
      ),

      // --- Bottom Navigation Bar matching the UI Screenshot ---
      bottomNavigationBar: NavigationBarTheme(
        data: NavigationBarThemeData(
          labelTextStyle: WidgetStateProperty.resolveWith((states) {
            if (states.contains(WidgetState.selected)) {
              return const TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w600,
                color: kDarkCard,
              );
            }
            return TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.normal,
              color: Colors.grey[700],
            );
          }),
        ),
        child: NavigationBar(
          height: 68,
          backgroundColor: kNavBarBg,
          indicatorColor: kNavIndicator,
          selectedIndex: _selectedIndex,
          onDestinationSelected: (int index) {
            setState(() {
              _selectedIndex = index;
            });
            if (index == 1 || index == 3) {
              _scrollToAssessment();
            }
          },
          destinations: const [
            NavigationDestination(
              icon: Icon(Icons.home_outlined, color: kDarkCard),
              selectedIcon: Icon(Icons.home, color: kDarkCard),
              label: 'Home',
            ),
            NavigationDestination(
              icon: Icon(Icons.explore_outlined, color: kDarkCard),
              selectedIcon: Icon(Icons.explore, color: kDarkCard),
              label: 'Explore',
            ),
            NavigationDestination(
              icon: Icon(Icons.luggage_outlined, color: kDarkCard),
              selectedIcon: Icon(Icons.luggage, color: kDarkCard),
              label: 'Trips',
            ),
            NavigationDestination(
              icon: Icon(Icons.navigation_outlined, color: kDarkCard),
              selectedIcon: Icon(Icons.navigation, color: kDarkCard),
              label: 'Navigate',
            ),
            NavigationDestination(
              icon: Icon(Icons.person_outline, color: kDarkCard),
              selectedIcon: Icon(Icons.person, color: kDarkCard),
              label: 'Profile',
            ),
          ],
        ),
      ),
    );
  }

  // Helper widget to build the "Nature" and "Beaches" cards under Discover
  Widget _buildDiscoverCard({
    required IconData icon,
    required String title,
    required VoidCallback onTap,
  }) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(14),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 20.0, vertical: 22.0),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: kBorderColor, width: 1.5),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: kGoldIcon, size: 28),
            const SizedBox(height: 14),
            Text(
              title,
              style: const TextStyle(
                fontSize: 15,
                fontWeight: FontWeight.bold,
                color: kDarkCard,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
