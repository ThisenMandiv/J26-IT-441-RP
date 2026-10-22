import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:tapropath/models/completed_hike_model.dart';
import 'package:tapropath/models/trail_model.dart';
import 'package:tapropath/screens/hike_history_screen.dart';
import 'package:tapropath/services/hike_history_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  Widget buildTestScreen({HikeHistoryService? service}) {
    return MaterialApp(
      home: HikeHistoryScreen(historyService: service),
    );
  }

  group('HikeHistoryScreen widget tests', () {
    testWidgets('shows empty state when no hikes are saved', (tester) async {
      SharedPreferences.setMockInitialValues({});
      const service = HikeHistoryService();

      await tester.pumpWidget(buildTestScreen(service: service));
      await tester.pumpAndSettle();

      expect(find.text('Hike History'), findsOneWidget);
      expect(find.text('No Completed Hikes Yet'), findsOneWidget);
      expect(
        find.textContaining('Start a hike on the map and tap "Finish Hike"'),
        findsOneWidget,
      );
    });

    testWidgets('renders saved hike cards with distance, duration, date, and points', (tester) async {
      SharedPreferences.setMockInitialValues({});
      const service = HikeHistoryService();

      final hike = CompletedHike(
        id: 'hike_101',
        trailId: 'knuckles-ridge',
        trailName: 'Knuckles Mountain Range',
        finishTime: DateTime(2026, 10, 21, 14, 30),
        duration: const Duration(hours: 2, minutes: 15, seconds: 40),
        distanceKm: 5.42,
        recordedPoints: const [
          LatLng(lat: 7.4520, lng: 80.8060),
          LatLng(lat: 7.4540, lng: 80.8100),
        ],
      );

      await service.saveHike(hike);

      await tester.pumpWidget(buildTestScreen(service: service));
      await tester.pumpAndSettle();

      expect(find.text('Hike History'), findsOneWidget);
      expect(find.text('Knuckles Mountain Range'), findsOneWidget);
      expect(find.text('5.42 km'), findsOneWidget);
      expect(find.text('02:15:40'), findsOneWidget);
      expect(find.text('2'), findsOneWidget); // 2 GPS points
      expect(find.text('Saved'), findsOneWidget);
      expect(find.textContaining('2026-10-21'), findsOneWidget);
    });

    testWidgets('allows clearing history via confirmation dialog', (tester) async {
      SharedPreferences.setMockInitialValues({});
      const service = HikeHistoryService();

      final hike = CompletedHike(
        id: 'hike_102',
        trailName: 'Pidurangala',
        duration: const Duration(minutes: 20),
        distanceKm: 1.1,
        recordedPoints: const [],
      );

      await service.saveHike(hike);

      await tester.pumpWidget(buildTestScreen(service: service));
      await tester.pumpAndSettle();

      expect(find.text('Pidurangala'), findsOneWidget);

      // Tap clear history icon in AppBar
      final clearIcon = find.byIcon(Icons.delete_sweep_outlined);
      expect(clearIcon, findsOneWidget);
      await tester.tap(clearIcon);
      await tester.pumpAndSettle();

      // Confirmation dialog should be visible
      expect(find.text('Clear All History?'), findsOneWidget);
      expect(find.text('Clear'), findsOneWidget);

      // Confirm clear
      await tester.tap(find.text('Clear'));
      await tester.pumpAndSettle();

      // Screen should revert to empty state
      expect(find.text('No Completed Hikes Yet'), findsOneWidget);
      expect(find.text('Pidurangala'), findsNothing);
    });
  });
}
