import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import 'dart:convert';

import 'package:geolocator/geolocator.dart'; // To fetch current GPS location
import 'package:flutter_map/flutter_map.dart'; // For OpenStreetMap integration
import 'package:latlong2/latlong.dart'; // To handle Latitude and Longitude coordinates
import 'package:firebase_core/firebase_core.dart'; // Core package required for Firebase integration
import 'package:cloud_firestore/cloud_firestore.dart'; // NEW: Import Firestore package

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
  runApp(const TravelSafetyApp());
}

class TravelSafetyApp extends StatelessWidget {
  const TravelSafetyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Travel Safety AI',
      debugShowCheckedModeBanner:
          false, // Hide the debug banner in the top right corner
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.teal),
        useMaterial3: true, // Use the latest Material Design 3 guidelines
        scaffoldBackgroundColor: Colors
            .grey[100], // Set a light grey background for a modern UI look
      ),
      home: const RiskAssessmentScreen(), // Set the initial screen of the app
    );
  }
}

class RiskAssessmentScreen extends StatefulWidget {
  const RiskAssessmentScreen({super.key});

  @override
  State<RiskAssessmentScreen> createState() => _RiskAssessmentScreenState();
}

class _RiskAssessmentScreenState extends State<RiskAssessmentScreen> {
  // Controller to manage the text input for the location field
  final TextEditingController _locationController = TextEditingController();

  // State variables to track the status of the safety checklists
  bool isEmergencyContactsUpdated = false;
  bool isWeatherAnalyzed = false;

  // Variables to store the results from the AI risk assessment backend
  double? riskScore; // Risk score as a percentage (e.g., 47.23)
  String riskLevel =
      "Not Assessed"; // Categorized risk level (e.g., High, Moderate, Low)
  String? apiMessage; // Additional feedback message from the API

  // Loading state flags
  bool isLoading =
      false; // Indicates if the assessment API request is in progress
  bool isFetchingLocation =
      false; // Indicates if the GPS location is currently being fetched

  // OpenStreetMap specific variables
  final MapController mapController =
      MapController(); // Controls the map view programmatically
  LatLng _currentMapPosition = const LatLng(
    6.9271,
    79.8612,
  ); // Default map coordinates set to Colombo, Sri Lanka

  @override
  void dispose() {
    // Clean up controllers when the widget is removed from the widget tree to prevent memory leaks
    _locationController.dispose();
    mapController.dispose();
    super.dispose();
  }

  // Helper function to return a specific color based on the analyzed risk level
  Color _getRiskColor(String level) {
    if (level == "High Risk") return Colors.redAccent;
    if (level == "Moderate Risk") return Colors.orange;
    if (level == "Low Risk") return Colors.green;
    return Colors.grey; // Default color before any assessment is done
  }

  // Asynchronous function to fetch the user's current GPS location
  Future<void> _getCurrentLocation() async {
    setState(() {
      isFetchingLocation = true; // Show loading indicator in the text field
    });

    bool serviceEnabled;
    LocationPermission permission;

    try {
      // Verify if location services (GPS) are enabled on the device
      serviceEnabled = await Geolocator.isLocationServiceEnabled();
      if (!serviceEnabled) {
        _showSnackBar('Location services are disabled.', Colors.red);
        return;
      }

      // Check if the app has permission to access the device's location
      permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission =
            await Geolocator.requestPermission(); // Prompt user for permission
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

      // Retrieve the highly accurate current geographical position
      Position position = await Geolocator.getCurrentPosition(
        desiredAccuracy: LocationAccuracy.high,
      );

      setState(() {
        // Update the text field with the fetched latitude and longitude
        _locationController.text =
            "${position.latitude}, ${position.longitude}";
        // Update the map position to the newly fetched coordinates
        _currentMapPosition = LatLng(position.latitude, position.longitude);
      });

      // Smoothly animate the map camera to the new location with a specific zoom level
      mapController.move(_currentMapPosition, 14.0);

      _showSnackBar('Location fetched successfully!', Colors.green);
    } catch (e) {
      _showSnackBar('Error getting location: $e', Colors.red);
    } finally {
      setState(() {
        isFetchingLocation = false; // Hide loading indicator
      });
    }
  }

  // Helper function to display floating snackbar messages at the bottom of the screen
  void _showSnackBar(String message, Color color) {
    if (mounted) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(message), backgroundColor: color));
    }
  }

  // Asynchronous function to submit user data to the Python/FastAPI backend for risk assessment
  Future<void> _submitAssessment() async {
    // Validate if the user has entered a location
    if (_locationController.text.trim().isEmpty) {
      _showSnackBar(
        'Please enter a destination location first.',
        Colors.redAccent,
      );
      return;
    }

    setState(() {
      isLoading = true; // Show a loading spinner on the submit button
      apiMessage = null; // Clear any previous API messages
    });

    try {
      // Determine whether it is Day or Night based on the local device time
      int hour = DateTime.now().hour;
      String timeOfDay = (hour >= 18 || hour < 6) ? "Night" : "Day";

      // The API endpoint URL of the Python backend (configured for localhost execution)
      final url = Uri.parse('http://127.0.0.1:8000/api/calculate-risk');

      // Construct the JSON payload containing the assessment data
      final Map<String, dynamic> requestData = {
        "location": _locationController.text.trim(),
        "emergency_contacts_updated": isEmergencyContactsUpdated,
        "weather_analyzed": isWeatherAnalyzed,
        "time_of_day": timeOfDay,
      };

      // Execute a POST request to send data to the backend server
      final response = await http.post(
        url,
        headers: {"Content-Type": "application/json"},
        body: json.encode(requestData),
      );

      // Check if the server responded with a success status code (200 OK)
      if (response.statusCode == 200) {
        final responseData = json.decode(
          response.body,
        ); // Parse the JSON response

        setState(() {
          // Update state variables with the data received from the backend
          riskScore = (responseData['risk_score'] as num).toDouble();
          riskLevel = responseData['risk_level'];
          apiMessage = responseData['message'];
        });

        // --- NEW: Save the results to Firebase Firestore ---
        try {
          await FirebaseFirestore.instance.collection('assessments').add({
            'location': _locationController.text.trim(),
            'latitude': _currentMapPosition.latitude,
            'longitude': _currentMapPosition.longitude,
            'risk_score': riskScore,
            'risk_level': riskLevel,
            'emergency_contacts_updated': isEmergencyContactsUpdated,
            'weather_analyzed': isWeatherAnalyzed,
            'time_of_day': timeOfDay,
            'timestamp':
                FieldValue.serverTimestamp(), // Saves the exact server time
          });

          _showSnackBar(
            'Assessment Complete & Saved to Database!',
            Colors.green,
          );
        } catch (dbError) {
          _showSnackBar(
            'Assessment Complete, but failed to save to DB.',
            Colors.orange,
          );
          print('Firestore Error: $dbError');
        }
        // ---------------------------------------------------
      } else {
        // Throw an exception if the server encountered an error
        throw Exception(
          "Failed to get risk score. Server error ${response.statusCode}",
        );
      }
    } catch (error) {
      setState(() {
        apiMessage = 'Error connecting to server. Is it running?';
      });
      _showSnackBar('Error connecting to the Python server', Colors.red);
    } finally {
      setState(() {
        isLoading = false; // Hide the loading spinner
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      // Top application bar
      appBar: AppBar(
        title: const Text(
          'Risk Assessment',
          style: TextStyle(fontWeight: FontWeight.bold, color: Colors.white),
        ),
        backgroundColor: Colors.teal,
        centerTitle: true,
        elevation: 0,
      ),
      // Scrollable body content
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // --- AI Safety Risk Score Display Card ---
            Card(
              elevation: 6,
              shadowColor: Colors.black26,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(20),
              ),
              child: Padding(
                padding: const EdgeInsets.symmetric(
                  vertical: 30.0,
                  horizontal: 20.0,
                ),
                child: Column(
                  children: [
                    // Card Header Row
                    Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(Icons.security, color: Colors.grey[700]),
                        const SizedBox(width: 8),
                        Text(
                          'AI Safety Risk Score',
                          style: TextStyle(
                            fontSize: 18,
                            fontWeight: FontWeight.w600,
                            color: Colors.grey[700],
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 25),

                    // Circular Progress Indicator representing the Risk Score percentage
                    Stack(
                      alignment: Alignment.center,
                      children: [
                        SizedBox(
                          height: 140,
                          width: 140,
                          child: CircularProgressIndicator(
                            // Convert percentage (0-100) to a fraction (0.0-1.0) for the indicator
                            value: riskScore != null ? (riskScore! / 100) : 0,
                            strokeWidth: 14,
                            backgroundColor: Colors.grey[200],
                            valueColor: AlwaysStoppedAnimation<Color>(
                              _getRiskColor(riskLevel),
                            ),
                          ),
                        ),
                        // Center text displaying the exact percentage
                        Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Text(
                              riskScore != null
                                  ? "${riskScore!.toStringAsFixed(1)}%"
                                  : "N/A",
                              style: TextStyle(
                                fontSize: 28,
                                fontWeight: FontWeight.bold,
                                color: _getRiskColor(riskLevel),
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                    const SizedBox(height: 20),

                    // Risk Level Label (e.g., High Risk, Low Risk)
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 16,
                        vertical: 8,
                      ),
                      decoration: BoxDecoration(
                        color: _getRiskColor(riskLevel).withOpacity(0.1),
                        borderRadius: BorderRadius.circular(30),
                      ),
                      child: Text(
                        riskLevel,
                        style: TextStyle(
                          fontSize: 22,
                          fontWeight: FontWeight.bold,
                          color: _getRiskColor(riskLevel),
                        ),
                      ),
                    ),

                    // Display optional API messages or errors below the score
                    if (apiMessage != null) ...[
                      const SizedBox(height: 15),
                      Text(
                        apiMessage!,
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          fontSize: 13,
                          fontStyle: FontStyle.italic,
                          color: riskScore == null
                              ? Colors.red
                              : Colors.grey[600],
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
            const SizedBox(height: 25),

            // --- Location Input Field with GPS Fetch Feature ---
            TextField(
              controller: _locationController,
              decoration: InputDecoration(
                filled: true,
                fillColor: Colors.white,
                labelText: 'Destination Location',
                hintText: 'Enter a city or tap GPS icon',
                prefixIcon: const Icon(Icons.location_on, color: Colors.teal),
                // Display a loading spinner if location is fetching; otherwise, display the GPS button
                suffixIcon: isFetchingLocation
                    ? const Padding(
                        padding: EdgeInsets.all(12.0),
                        child: SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.teal,
                          ),
                        ),
                      )
                    : IconButton(
                        icon: const Icon(Icons.my_location, color: Colors.teal),
                        onPressed: _getCurrentLocation,
                        tooltip: 'Get Current GPS Location',
                      ),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(15),
                  borderSide: BorderSide.none,
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(15),
                  borderSide: const BorderSide(color: Colors.teal, width: 2),
                ),
              ),
            ),
            const SizedBox(height: 25),

            // --- OpenStreetMap Integration View ---
            Container(
              height: 250,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(15),
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
                    initialCenter:
                        _currentMapPosition, // Map initial focus coordinates
                    initialZoom: 14.0, // Default zoom level
                  ),
                  children: [
                    // Map tile provider rendering the street view images
                    TileLayer(
                      urlTemplate:
                          'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                      userAgentPackageName: 'com.example.travel_safety_app',
                    ),
                    // Layer displaying a red pin marker at the selected location
                    MarkerLayer(
                      markers: [
                        Marker(
                          point: _currentMapPosition,
                          width: 40,
                          height: 40,
                          child: const Icon(
                            Icons.location_pin,
                            color: Colors.red,
                            size: 40,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 25),

            // --- Pre-Travel Safety Checklist Section ---
            Card(
              elevation: 2,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(15),
              ),
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 10.0),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Padding(
                      padding: EdgeInsets.only(
                        left: 16.0,
                        bottom: 8.0,
                        top: 8.0,
                      ),
                      child: Text(
                        'Pre-Travel Safety Checklist',
                        style: TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.bold,
                          color: Colors.black87,
                        ),
                      ),
                    ),
                    // Checkbox for updating emergency contacts
                    CheckboxListTile(
                      title: const Text('Emergency Contacts Updated'),
                      activeColor: Colors.teal,
                      value: isEmergencyContactsUpdated,
                      onChanged: (bool? value) {
                        setState(() {
                          isEmergencyContactsUpdated = value ?? false;
                        });
                      },
                    ),
                    // Checkbox for weather analysis confirmation
                    CheckboxListTile(
                      title: const Text('Weather & Location Analyzed'),
                      activeColor: Colors.teal,
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
            ),
            const SizedBox(height: 30),

            // --- Assessment Submission Button ---
            SizedBox(
              height: 55,
              child: ElevatedButton(
                // Disable button to prevent multiple submissions while an API call is ongoing
                onPressed: isLoading ? null : _submitAssessment,
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.teal,
                  foregroundColor: Colors.white,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(15),
                  ),
                  elevation: 5,
                ),
                // Show a progress indicator inside the button if isLoading is true
                child: isLoading
                    ? const SizedBox(
                        height: 24,
                        width: 24,
                        child: CircularProgressIndicator(
                          color: Colors.white,
                          strokeWidth: 3,
                        ),
                      )
                    : const Text(
                        'Submit Assessment',
                        style: TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
              ),
            ),
            const SizedBox(height: 20),
          ],
        ),
      ),
    );
  }
}
