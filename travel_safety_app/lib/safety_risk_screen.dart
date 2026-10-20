import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:http/http.dart' as http; // To make API calls

import 'dart:convert'; // To handle JSON data

class SafetyRiskScreen extends StatefulWidget {
  @override
  _SafetyRiskScreenState createState() => _SafetyRiskScreenState();
}

class _SafetyRiskScreenState extends State<SafetyRiskScreen> {
  String _locationMessage = "Location not yet retrieved";
  bool _isLoading = false;

  // Variables to store data received from the backend (Changed to double for ML model accuracy)
  double? _riskScore;
  String? _riskLevel;
  String? _apiMessage;

  // Variables for dynamic Checkboxes
  bool _emergencyContactsUpdated = false;
  bool _weatherAnalyzed = false;

  // Function to determine the color based on the Risk Level
  Color _getRiskColor(String level) {
    if (level == "High Risk") return Colors.redAccent;
    if (level == "Moderate Risk") return Colors.orange;
    return Colors.green; // Low Risk
  }

  // Function to fetch location and send it to the backend API
  Future<void> _checkRiskAndLocation() async {
    setState(() {
      _isLoading = true;
      _riskScore = null;
      _riskLevel = null;
      _apiMessage = null;
    });

    bool serviceEnabled;
    LocationPermission permission;

    // Check if location services are enabled
    serviceEnabled = await Geolocator.isLocationServiceEnabled();
    if (!serviceEnabled) {
      setState(() {
        _locationMessage = "Location services are disabled.";
        _isLoading = false;
      });
      return;
    }

    // Check location permissions
    permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
      if (permission == LocationPermission.denied) {
        setState(() {
          _locationMessage = "Location permissions denied.";
          _isLoading = false;
        });
        return;
      }
    }

    if (permission == LocationPermission.deniedForever) {
      setState(() {
        _locationMessage = "Location permissions are permanently denied.";
        _isLoading = false;
      });
      return;
    }

    try {
      // 1. Get the current position (Latitude and Longitude)
      Position position = await Geolocator.getCurrentPosition(
        desiredAccuracy: LocationAccuracy.high,
      );

      String currentLocation = "${position.latitude}, ${position.longitude}";

      setState(() {
        _locationMessage = currentLocation;
      });

      // Determine if it is Day or Night based on the phone's current time
      int hour = DateTime.now().hour;
      String timeOfDay = (hour >= 18 || hour < 6) ? "Night" : "Day";

      // 2. Call the backend API (Using Localhost for Web/Emulator Testing)
      final String apiUrl = 'http://127.0.0.1:8000/api/calculate-risk';

      final response = await http.post(
        Uri.parse(apiUrl),
        headers: {"Content-Type": "application/json"},
        body: jsonEncode({
          "location": currentLocation,
          "emergency_contacts_updated":
              _emergencyContactsUpdated, // Dynamically getting UI values
          "weather_analyzed": _weatherAnalyzed, // Dynamically getting UI values
          "time_of_day": timeOfDay,
        }),
      );

      // 3. Handle the response from the backend
      if (response.statusCode == 200) {
        final responseData = jsonDecode(response.body);
        setState(() {
          // Convert safely to double to avoid type errors
          _riskScore = (responseData['risk_score'] as num).toDouble();
          _riskLevel = responseData['risk_level'];
          _apiMessage = responseData['message'];
        });
      } else {
        setState(() {
          _apiMessage =
              "Error: Server responded with status code ${response.statusCode}";
        });
      }
    } catch (e) {
      setState(() {
        _apiMessage =
            "Error connecting to backend. Make sure the server is running. Details: $e";
      });
    } finally {
      setState(() {
        _isLoading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.grey[100], // Light grey background for the screen
      appBar: AppBar(
        title: Text(
          "Risk Assessment",
          style: TextStyle(fontWeight: FontWeight.bold),
        ),
        backgroundColor: Colors.teal,
        elevation: 0,
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(16.0),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              // Display the retrieved location with an Icon inside a styled container
              Container(
                padding: EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: Colors.grey.shade300),
                ),
                child: Row(
                  children: [
                    Icon(Icons.location_on, color: Colors.teal),
                    SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        _locationMessage,
                        style: TextStyle(fontSize: 16, color: Colors.black87),
                      ),
                    ),
                    Icon(Icons.my_location, color: Colors.teal),
                  ],
                ),
              ),
              SizedBox(height: 25),

              // UI container to display the AI Risk Score dynamically
              if (_riskScore != null && _riskLevel != null) ...[
                Card(
                  elevation: 8, // Adds a nice shadow effect to the card
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
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        // Header Row for the Risk Score Section
                        Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Icon(Icons.security, color: Colors.grey[600]),
                            SizedBox(width: 8),
                            Text(
                              "AI Safety Risk Score",
                              style: TextStyle(
                                fontSize: 18,
                                color: Colors.grey[600],
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          ],
                        ),
                        SizedBox(height: 25),

                        // Circular Progress Indicator for visual risk representation
                        Stack(
                          alignment: Alignment.center,
                          children: [
                            SizedBox(
                              height: 140,
                              width: 140,
                              child: CircularProgressIndicator(
                                value: _riskScore! / 100, // Converts percentage to a 0.0 - 1.0 scale
                                strokeWidth: 14,
                                backgroundColor: Colors.grey[200],
                                valueColor: AlwaysStoppedAnimation<Color>(
                                  _getRiskColor(_riskLevel!),
                                ),
                              ),
                            ),
                            Column(
                              children: [
                                Text(
                                  "${_riskScore!.toStringAsFixed(1)}%",
                                  style: TextStyle(
                                    fontSize: 28,
                                    fontWeight: FontWeight.bold,
                                    color: _getRiskColor(_riskLevel!),
                                  ),
                                ),
                              ],
                            ),
                          ],
                        ),
                        SizedBox(height: 20),

                        // Formatted container to display the Risk Level text
                        Container(
                          padding: EdgeInsets.symmetric(
                            horizontal: 16,
                            vertical: 8,
                          ),
                          decoration: BoxDecoration(
                            color: _getRiskColor(_riskLevel!).withOpacity(0.1),
                            borderRadius: BorderRadius.circular(30),
                          ),
                          child: Text(
                            _riskLevel!,
                            style: TextStyle(
                              fontSize: 22,
                              fontWeight: FontWeight.bold,
                              color: _getRiskColor(_riskLevel!),
                            ),
                          ),
                        ),
                        SizedBox(height: 15),

                        // Optional API success or additional message
                        Text(
                          _apiMessage ?? "",
                          textAlign: TextAlign.center,
                          style: TextStyle(fontSize: 13, color: Colors.grey),
                        ),
                      ],
                    ),
                  ),
                ),
                SizedBox(height: 30),
              ] else if (_apiMessage != null) ...[
                // Display error message if any error occurs during API call
                Text(
                  _apiMessage!,
                  style: TextStyle(color: Colors.red),
                  textAlign: TextAlign.center,
                ),
                SizedBox(height: 30),
              ],

              // Checklists Section for user input regarding safety
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
                      Padding(
                        padding: const EdgeInsets.only(
                          left: 16.0,
                          bottom: 8.0,
                          top: 8.0,
                        ),
                        child: Text(
                          "Pre-Travel Safety Checklist",
                          style: TextStyle(
                            fontSize: 18,
                            fontWeight: FontWeight.bold,
                            color: Colors.black87,
                          ),
                        ),
                      ),
                      CheckboxListTile(
                        title: Text("Emergency Contacts Updated"),
                        activeColor: Colors.teal,
                        value: _emergencyContactsUpdated,
                        onChanged: (bool? value) {
                          setState(() {
                            _emergencyContactsUpdated = value ?? false;
                          });
                        },
                      ),
                      CheckboxListTile(
                        title: Text("Weather & Location Analyzed"),
                        activeColor: Colors.teal,
                        value: _weatherAnalyzed,
                        onChanged: (bool? value) {
                          setState(() {
                            _weatherAnalyzed = value ?? false;
                          });
                        },
                      ),
                    ],
                  ),
                ),
              ),
              SizedBox(height: 30),

              // Action Button to submit the assessment
              _isLoading
                  ? CircularProgressIndicator(
                      color: Colors.teal,
                    ) // Show loader while fetching data
                  : SizedBox(
                      width: double.infinity, // Button spans the full width of the screen
                      child: ElevatedButton(
                        onPressed: _checkRiskAndLocation,
                        child: Text(
                          "Submit Assessment",
                          style: TextStyle(
                            fontSize: 18,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                        style: ElevatedButton.styleFrom(
                          backgroundColor:
                              Colors.teal, // Modern Teal theme color
                          foregroundColor: Colors.white, // Text color
                          padding: EdgeInsets.symmetric(vertical: 16),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(10),
                          ),
                          elevation: 5,
                        ),
                      ),
                    ),
              SizedBox(height: 20),
            ],
          ),
        ),
      ),
    );
  }
}
