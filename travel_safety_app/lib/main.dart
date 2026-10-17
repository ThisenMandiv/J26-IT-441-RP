import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import 'dart:convert';

import 'package:geolocator/geolocator.dart'; // Add Geolocator package

void main() {
  runApp(const TravelSafetyApp());
}

class TravelSafetyApp extends StatelessWidget {
  const TravelSafetyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Travel Safety AI',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.teal),
        useMaterial3: true,
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
  final TextEditingController _locationController = TextEditingController();

  bool isEmergencyContactsUpdated = false;
  bool isWeatherAnalyzed = false;

  String riskScore = "N/A";
  String riskLevel = "Not Assessed";
  bool isLoading = false;
  bool isFetchingLocation = false; // To show loading when fetching GPS

  @override
  void dispose() {
    _locationController.dispose();
    super.dispose();
  }

  // --- Function to get the current location ---
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

      // Set Lat and Lng values to the text box
      setState(() {
        _locationController.text =
            "${position.latitude}, ${position.longitude}";
      });
      _showSnackBar('Location fetched successfully!', Colors.green);
    } catch (e) {
      _showSnackBar('Error getting location: $e', Colors.red);
    } finally {
      setState(() {
        isFetchingLocation = false;
      });
    }
  }

  void _showSnackBar(String message, Color color) {
    if (mounted) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(message), backgroundColor: color));
    }
  }

  // --- Function to submit data to the Backend ---
  Future<void> _submitAssessment() async {
    if (_locationController.text.trim().isEmpty) {
      _showSnackBar(
        'Please enter a destination location first.',
        Colors.redAccent,
      );
      return;
    }

    setState(() {
      isLoading = true;
    });

    try {
      // URL of your Python Backend
      final url = Uri.parse('http://127.0.0.1:8000/api/calculate-risk');

      final Map<String, dynamic> requestData = {
        "location": _locationController.text.trim(),
        "emergency_contacts_updated": isEmergencyContactsUpdated,
        "weather_analyzed": isWeatherAnalyzed,
      };

      final response = await http.post(
        url,
        headers: {"Content-Type": "application/json"},
        body: json.encode(requestData),
      );

      if (response.statusCode == 200) {
        final responseData = json.decode(response.body);

        setState(() {
          riskScore = "${responseData['risk_score']}%";
          riskLevel = responseData['risk_level'];
        });

        _showSnackBar(responseData['message'], Colors.green);
      } else {
        throw Exception("Failed to get risk score.");
      }
    } catch (error) {
      _showSnackBar('Error connecting to the Python server.', Colors.red);
    } finally {
      setState(() {
        isLoading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text(
          'Risk Assessment',
          style: TextStyle(fontWeight: FontWeight.bold),
        ),
        backgroundColor: Theme.of(context).colorScheme.inversePrimary,
        centerTitle: true,
      ),
      body: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Card(
              elevation: 4,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(15),
              ),
              child: Padding(
                padding: const EdgeInsets.all(24.0),
                child: Column(
                  children: [
                    const Text(
                      'AI Safety Risk Score',
                      style: TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.w500,
                        color: Colors.black54,
                      ),
                    ),
                    const SizedBox(height: 10),
                    Text(
                      '$riskLevel ($riskScore)',
                      style: TextStyle(
                        fontSize: 32,
                        color: riskLevel == "High Risk"
                            ? Colors.red
                            : (riskLevel == "Moderate Risk"
                                  ? Colors.orange
                                  : Colors.green),
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 20),

            // Location Text Field with GPS Icon
            TextField(
              controller: _locationController,
              decoration: InputDecoration(
                labelText: 'Destination Location',
                hintText: 'Enter a city or tap GPS icon',
                prefixIcon: const Icon(Icons.location_on, color: Colors.teal),
                // --- New GPS Button ---
                suffixIcon: isFetchingLocation
                    ? const Padding(
                        padding: EdgeInsets.all(12.0),
                        child: SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        ),
                      )
                    : IconButton(
                        icon: const Icon(Icons.my_location, color: Colors.teal),
                        onPressed: _getCurrentLocation,
                        tooltip: 'Get Current GPS Location',
                      ),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(10),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(10),
                  borderSide: const BorderSide(color: Colors.teal, width: 2),
                ),
              ),
            ),
            const SizedBox(height: 20),

            const Text(
              'Pre-Travel Safety Checklist',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 10),
            Expanded(
              child: ListView(
                children: [
                  CheckboxListTile(
                    title: const Text('Emergency Contacts Updated'),
                    value: isEmergencyContactsUpdated,
                    onChanged: (bool? value) {
                      setState(() {
                        isEmergencyContactsUpdated = value ?? false;
                      });
                    },
                  ),
                  CheckboxListTile(
                    title: const Text('Weather & Location Analyzed'),
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

            ElevatedButton(
              onPressed: isLoading ? null : _submitAssessment,
              style: ElevatedButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 16),
                backgroundColor: Theme.of(context).colorScheme.primary,
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(10),
                ),
              ),
              child: isLoading
                  ? const SizedBox(
                      height: 20,
                      width: 20,
                      child: CircularProgressIndicator(
                        color: Colors.white,
                        strokeWidth: 2,
                      ),
                    )
                  : const Text(
                      'Submit Assessment',
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
            ),
            const SizedBox(height: 10),
          ],
        ),
      ),
    );
  }
}
