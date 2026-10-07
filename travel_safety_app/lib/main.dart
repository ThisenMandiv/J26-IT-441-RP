import 'package:flutter/material.dart';
import 'package:http/http.dart' as http; // Importing the HTTP package

import 'dart:convert'; // For JSON encoding/decoding

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
  // Controller to capture the location input from the user
  final TextEditingController _locationController = TextEditingController();

  // Variables to track checkbox states
  bool isEmergencyContactsUpdated = false;
  bool isWeatherAnalyzed = false;

  // Variables to hold the dynamic API response data
  String riskScore = "N/A";
  String riskLevel = "Not Assessed";
  bool isLoading = false; // To show a loading indicator during API call

  // Dispose the controller when the screen is removed to prevent memory leaks
  @override
  void dispose() {
    _locationController.dispose();
    super.dispose();
  }

  // Function to submit data to the Python Backend
  Future<void> _submitAssessment() async {
    // Basic validation: Check if the location field is empty
    if (_locationController.text.trim().isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Please enter a destination location first.'),
          backgroundColor: Colors.redAccent,
        ),
      );
      return; // Stop execution if location is empty
    }

    setState(() {
      isLoading = true; // Start loading
    });

    try {
      // Define the API endpoint URL (Your local FastAPI server)
      final url = Uri.parse('http://127.0.0.1:8000/api/calculate-risk');

      // Prepare the data map using the user input from the text field
      final Map<String, dynamic> requestData = {
        "location": _locationController.text
            .trim(), // Getting the dynamic location
        "emergency_contacts_updated": isEmergencyContactsUpdated,
        "weather_analyzed": isWeatherAnalyzed,
      };

      // Make the HTTP POST request
      final response = await http.post(
        url,
        headers: {"Content-Type": "application/json"},
        body: json.encode(requestData),
      );

      // Check if the request was successful
      if (response.statusCode == 200) {
        final responseData = json.decode(response.body);

        // Update the UI with the new Risk Score and Level from the backend
        setState(() {
          riskScore = "${responseData['risk_score']}%";
          riskLevel = responseData['risk_level'];
        });

        // Show a success message
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(responseData['message']),
              backgroundColor: Colors.green,
            ),
          );
        }
      } else {
        throw Exception("Failed to get risk score.");
      }
    } catch (error) {
      // Handle any connection errors
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Error connecting to the Python server.'),
            backgroundColor: Colors.red,
          ),
        );
      }
    } finally {
      setState(() {
        isLoading = false; // Stop loading regardless of success or failure
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
                    // Displaying the dynamic risk level and score
                    Text(
                      '$riskLevel ($riskScore)',
                      style: TextStyle(
                        fontSize: 32,
                        // Change color based on risk level
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

            // New Location Input Field added here
            TextField(
              controller: _locationController,
              decoration: InputDecoration(
                labelText: 'Destination Location',
                hintText: 'Enter a city or place (e.g., Kandy)',
                prefixIcon: const Icon(Icons.location_on, color: Colors.teal),
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
            // Updated Submit Button
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
