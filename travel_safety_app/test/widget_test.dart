// This is a basic Flutter widget test for the Tapropath App.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:travel_safety_app/main.dart'; // Make sure this matches your pubspec.yaml name

void main() {
  testWidgets('Tapropath App smoke test', (WidgetTester tester) async {
    // Build our app and trigger a frame using the new TapropathApp class.
    await tester.pumpWidget(const TapropathApp());

    // Verify that our Risk Assessment screen loads properly.
    // We check for specific text that we know exists in our new Tapropath UI.
    expect(find.text('Tapropath - Destination Assessment'), findsWidgets);
    expect(find.text('Destination AI Safety Risk Score'), findsOneWidget);
    expect(find.text('Check Destination Risk'), findsOneWidget);

    // Verify the counter app elements are definitely gone.
    expect(find.byIcon(Icons.add), findsNothing);
  });
}
