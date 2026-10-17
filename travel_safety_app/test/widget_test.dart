// This is a basic Flutter widget test for the Travel Safety App.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:travel_safety_app/main.dart';

void main() {
  testWidgets('Travel Safety App smoke test', (WidgetTester tester) async {
    // Build our app and trigger a frame.
    await tester.pumpWidget(const TravelSafetyApp());

    // Verify that our Risk Assessment screen loads properly.
    // We check for specific text that we know exists in our new UI.
    expect(find.text('Risk Assessment'), findsWidgets);
    expect(find.text('AI Safety Risk Score'), findsOneWidget);
    expect(find.text('Submit Assessment'), findsOneWidget);

    // Verify the counter app elements are definitely gone.
    expect(find.byIcon(Icons.add), findsNothing);
  });
}
