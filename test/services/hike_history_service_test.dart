import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:tapropath/models/completed_hike_model.dart';
import 'package:tapropath/models/trail_model.dart';
import 'package:tapropath/services/hike_history_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('HikeHistoryService tests', () {
    setUp(() {
      SharedPreferences.setMockInitialValues({});
    });

    test('loadHikes returns empty list when no history exists', () async {
      final service = const HikeHistoryService();
      final hikes = await service.loadHikes();

      expect(hikes, isEmpty);
    });

    test('saveHike persists completed hike and loadHikes retrieves it with full fidelity', () async {
      final service = const HikeHistoryService();

      final startTime = DateTime(2026, 10, 21, 10, 30, 0);
      final finishTime = DateTime(2026, 10, 21, 11, 45, 0);

      final hike = CompletedHike(
        id: 'hike_test_1',
        trailId: 'pidurangala-rock',
        trailName: 'Pidurangala Rock',
        startTime: startTime,
        finishTime: finishTime,
        duration: const Duration(hours: 1, minutes: 15),
        recordedPoints: const [
          LatLng(lat: 7.9570, lng: 80.7600),
          LatLng(lat: 7.9580, lng: 80.7610),
          LatLng(lat: 7.9590, lng: 80.7620),
        ],
        distanceKm: 2.35,
      );

      final saved = await service.saveHike(hike);
      expect(saved, isTrue);

      final loaded = await service.loadHikes();
      expect(loaded.length, 1);

      final first = loaded.first;
      expect(first.id, 'hike_test_1');
      expect(first.trailId, 'pidurangala-rock');
      expect(first.trailName, 'Pidurangala Rock');
      expect(first.startTime, startTime);
      expect(first.finishTime, finishTime);
      expect(first.duration.inMinutes, 75);
      expect(first.formattedDuration, '01:15:00');
      expect(first.distanceKm, 2.35);
      expect(first.formattedDistance, '2.35 km');
      expect(first.recordedPoints.length, 3);
      expect(first.recordedPoints[0].lat, 7.9570);
      expect(first.recordedPoints[0].lng, 80.7600);
    });

    test('saveHike prepends subsequent hikes and avoids duplicate IDs', () async {
      final service = const HikeHistoryService();

      final hike1 = CompletedHike(
        id: 'hike_1',
        trailName: 'Trail 1',
        finishTime: DateTime(2026, 10, 20, 12, 0),
        duration: const Duration(minutes: 30),
        recordedPoints: const [],
        distanceKm: 1.0,
      );

      final hike2 = CompletedHike(
        id: 'hike_2',
        trailName: 'Trail 2',
        finishTime: DateTime(2026, 10, 21, 14, 0),
        duration: const Duration(minutes: 45),
        recordedPoints: const [],
        distanceKm: 2.0,
      );

      await service.saveHike(hike1);
      await service.saveHike(hike2);

      final loaded = await service.loadHikes();
      expect(loaded.length, 2);
      // Most recent first
      expect(loaded.first.id, 'hike_2');
      expect(loaded.last.id, 'hike_1');

      // Re-saving hike2 updates without duplicating
      await service.saveHike(hike2);
      final reloaded = await service.loadHikes();
      expect(reloaded.length, 2);
    });

    test('clearHistory removes all saved hikes', () async {
      final service = const HikeHistoryService();

      final hike = CompletedHike(
        id: 'hike_to_clear',
        duration: const Duration(minutes: 10),
        recordedPoints: const [],
        distanceKm: 0.5,
      );

      await service.saveHike(hike);
      expect((await service.loadHikes()).length, 1);

      final cleared = await service.clearHistory();
      expect(cleared, isTrue);

      final afterClear = await service.loadHikes();
      expect(afterClear, isEmpty);
    });

    test('loadHikes handles corrupted or invalid JSON in storage gracefully', () async {
      SharedPreferences.setMockInitialValues({
        HikeHistoryService.storageKey: '{not a valid json list}',
      });

      final service = const HikeHistoryService();
      final hikes = await service.loadHikes();

      // Graceful fallback: returns empty list without throwing exception
      expect(hikes, isEmpty);
    });

    test('loadHikes skips individually corrupted items in list gracefully', () async {
      SharedPreferences.setMockInitialValues({
        HikeHistoryService.storageKey: '[{"id": "valid_hike", "durationSeconds": 60, "distanceKm": 0.1, "recordedPoints": []}, "corrupted_string_item"]',
      });

      final service = const HikeHistoryService();
      final hikes = await service.loadHikes();

      expect(hikes.length, 1);
      expect(hikes.first.id, 'valid_hike');
    });
  });
}
