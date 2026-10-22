import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tapropath/models/trail_model.dart';
import 'package:tapropath/services/route_service.dart';
import 'package:tapropath/widgets/back_to_trail_card.dart';

void main() {
  Widget buildTestCard({
    required OffRouteResult result,
    required double threshold,
  }) {
    return MaterialApp(
      home: Scaffold(
        body: Center(
          child: BackToTrailCard(
            result: result,
            threshold: threshold,
          ),
        ),
      ),
    );
  }

  group('BackToTrailCard widget tests', () {
    testWidgets('displays off-route warning when distance exceeds threshold', (tester) async {
      const offResult = OffRouteResult(
        distanceMetres: 145.2,
        nearestSegmentIndex: 2,
        nearestPoint: LatLng(lat: 7.123, lng: 80.456),
        returnBearingDegrees: 285.0,
        returnCompassDirection: 'WNW',
      );

      await tester.pumpWidget(buildTestCard(result: offResult, threshold: 50.0));

      // Header indicates off-route
      expect(find.text('OFF ROUTE — RETURN GUIDANCE'), findsOneWidget);
      expect(find.textContaining('deviates by more than 50 m'), findsOneWidget);

      // Distance in metres displayed
      expect(find.text('145.2 m'), findsOneWidget);

      // Bearing degrees and compass direction displayed
      expect(find.text('heading 285° WNW'), findsOneWidget);

      // Nearest segment index displayed
      expect(find.text('Straight-line return to Segment #3'), findsOneWidget);

      // Safety limitation notice is present
      expect(find.textContaining('Safety Notice: Directional assistance'), findsOneWidget);
      expect(find.textContaining('Does NOT account for terrain, cliffs'), findsOneWidget);
    });

    testWidgets('displays on-route state when distance is within threshold', (tester) async {
      const onResult = OffRouteResult(
        distanceMetres: 18.4,
        nearestSegmentIndex: 0,
        nearestPoint: LatLng(lat: 7.100, lng: 80.500),
        returnBearingDegrees: 45.0,
        returnCompassDirection: 'NE',
      );

      await tester.pumpWidget(buildTestCard(result: onResult, threshold: 50.0));

      // Header indicates on-route
      expect(find.text('ON ROUTE — PATH ALIGNED'), findsOneWidget);
      expect(find.textContaining('within the 50 m corridor'), findsOneWidget);

      // Distance displayed
      expect(find.text('18.4 m'), findsOneWidget);

      // Bearing degrees and compass direction displayed
      expect(find.text('heading 45° NE'), findsOneWidget);

      // Check-circle icon displayed instead of warning
      expect(find.byIcon(Icons.check_circle_outline), findsOneWidget);
      expect(find.byIcon(Icons.warning_amber_rounded), findsNothing);
    });
  });
}
