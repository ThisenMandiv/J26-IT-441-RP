import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:tapropath/models/trail_model.dart';
import 'package:tapropath/services/api_service.dart';
import 'package:tapropath/services/trail_data_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('TrailDataService - mergeTrails logic', () {
    final localSampleTrails = [
      const Trail(
        id: 'trail_local_1',
        name: 'Local Trail 1',
        region: 'Central',
        description: 'Local description',
        difficulty: 'Moderate',
        distanceKm: 5.0,
        bestSeason: 'Jan-Mar',
        routeStatus: 'Recorded track — not verified for navigation',
        waypoints: [
          TrailWaypoint(
            name: 'Point 1',
            position: LatLng(lat: 7.1, lng: 80.1),
          ),
          TrailWaypoint(
            name: 'Point 2',
            position: LatLng(lat: 7.2, lng: 80.2),
          ),
        ],
        verifiedForNavigation: false,
      ),
      const Trail(
        id: 'trail_local_2',
        name: 'Local Trail 2',
        region: 'Western',
        description: 'Demo trail',
        difficulty: 'Easy',
        distanceKm: 3.5,
        bestSeason: 'Year-round',
        routeStatus: 'Verified for navigation',
        waypoints: [
          TrailWaypoint(
            name: 'Start',
            position: LatLng(lat: 6.9, lng: 79.9),
          ),
        ],
        verifiedForNavigation: true,
      ),
    ];

    test('updates metadata while preserving local waypoints', () {
      final apiSummaries = [
        {
          'id': 'trail_local_1',
          'name': 'Updated Trail 1 Name',
          'verifiedForNavigation': true,
          'difficulty': 'Strenuous',
        }
      ];

      final merged = TrailDataService.mergeTrails(localSampleTrails, apiSummaries);

      final trail1 = merged.firstWhere((t) => t.id == 'trail_local_1');
      expect(trail1.name, 'Updated Trail 1 Name');
      expect(trail1.difficulty, 'Strenuous');
      expect(trail1.verifiedForNavigation, true);
      expect(trail1.routeStatus, 'Verified for navigation');
      // Waypoints must be preserved from local data!
      expect(trail1.waypoints.length, 2);
      expect(trail1.waypoints[0].position.lat, 7.1);
    });

    test('preserves local trails when API returns fewer records', () {
      final apiSummaries = [
        {
          'id': 'trail_local_1',
          'name': 'Updated Trail 1',
        }
      ];

      final merged = TrailDataService.mergeTrails(localSampleTrails, apiSummaries);

      // Both trails should still exist
      expect(merged.length, 2);
      expect(merged.any((t) => t.id == 'trail_local_2'), isTrue);
      final trail2 = merged.firstWhere((t) => t.id == 'trail_local_2');
      expect(trail2.name, 'Local Trail 2');
      expect(trail2.waypoints.length, 1);
    });

    test('handles duplicate IDs in API response correctly', () {
      final apiSummaries = [
        {
          'id': 'trail_local_1',
          'name': 'Version A',
        },
        {
          'id': 'trail_local_1',
          'name': 'Version B',
        },
      ];

      final merged = TrailDataService.mergeTrails(localSampleTrails, apiSummaries);

      final matching = merged.where((t) => t.id == 'trail_local_1').toList();
      expect(matching.length, 1, reason: 'Duplicate ID should not produce duplicate records');
      expect(matching.first.name, 'Version B', reason: 'Later update takes precedence');
    });

    test('adds brand-new trails from API response', () {
      final apiSummaries = [
        {
          'id': 'trail_remote_new',
          'name': 'Brand New Remote Trail',
          'mountain': 'Knuckles',
          'recordedDistanceKm': 8.2,
          'waypoints': [
            {'lat': 7.5, 'lng': 80.8}
          ]
        }
      ];

      final merged = TrailDataService.mergeTrails(localSampleTrails, apiSummaries);

      expect(merged.length, 3);
      final newTrail = merged.firstWhere((t) => t.id == 'trail_remote_new');
      expect(newTrail.name, 'Brand New Remote Trail');
      expect(newTrail.region, 'Knuckles');
      expect(newTrail.waypoints.length, 1);
    });
  });

  group('TrailDataService - offline-first integration with ApiService', () {
    test('successfully retrieves and merges trails when backend is online', () async {
      final mockClient = MockClient((request) async {
        if (request.url.path == '/api/trails') {
          return http.Response('''
          {
            "count": 1,
            "trails": [
              {
                "id": "kabaragala_01",
                "name": "Kabaragala Verified Track",
                "verifiedForNavigation": true
              }
            ]
          }
          ''', 200, headers: {'content-type': 'application/json'});
        }
        return http.Response('Not found', 404);
      });

      final apiService = ApiService(client: mockClient);
      final service = TrailDataService(apiService: apiService);

      final trails = await service.getTrails();

      // Local datasets have 8 trails (3 demo + 5 recorded).
      expect(trails.length, 8);

      // kabaragala_01 should have updated metadata from backend
      final kabaragala = trails.firstWhere((t) => t.id == 'kabaragala_01');
      expect(kabaragala.name, 'Kabaragala Verified Track');
      expect(kabaragala.verifiedForNavigation, true);
      // But its 19 local waypoints are preserved!
      expect(kabaragala.waypoints.length, 19);

      // Local demo trails like knuckles-main-trail must still exist!
      expect(trails.any((t) => t.id == 'knuckles-main-trail'), isTrue);
    });

    test('falls back to local bundled assets when backend is unavailable', () async {
      final mockClient = MockClient((request) async {
        throw http.ClientException('Connection refused to backend');
      });

      final apiService = ApiService(client: mockClient);
      final service = TrailDataService(apiService: apiService);

      final trails = await service.getTrails();

      // All 8 local trails must still load successfully!
      expect(trails.length, 8);
      expect(trails.any((t) => t.id == 'knuckles-main-trail'), isTrue);
      expect(trails.any((t) => t.id == 'kabaragala_01'), isTrue);

      final kabaragala = trails.firstWhere((t) => t.id == 'kabaragala_01');
      expect(kabaragala.waypoints.length, 19);
    });

    test('falls back to local bundled assets on backend timeout', () async {
      final mockClient = MockClient((request) async {
        await Future.delayed(const Duration(milliseconds: 50));
        return http.Response('ok', 200);
      });

      final apiService = ApiService(
        client: mockClient,
        timeout: const Duration(milliseconds: 10),
      );
      final service = TrailDataService(apiService: apiService);

      final trails = await service.getTrails();

      expect(trails.length, 8);
      expect(trails.any((t) => t.id == 'knuckles-main-trail'), isTrue);
    });

    test('falls back to local bundled assets on invalid API response', () async {
      final mockClient = MockClient((request) async {
        return http.Response('<html><body>Internal 500 Server Error</body></html>', 500);
      });

      final apiService = ApiService(client: mockClient);
      final service = TrailDataService(apiService: apiService);

      final trails = await service.getTrails();

      expect(trails.length, 8);
      expect(trails.any((t) => t.id == 'knuckles-main-trail'), isTrue);
    });
  });
}
