import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:tapropath/services/api_service.dart';

void main() {
  group('ApiService - checkHealth', () {
    test('returns health status map when backend returns 200', () async {
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/api/health');
        return http.Response('{"status": "healthy"}', 200,
            headers: {'content-type': 'application/json'});
      });

      final api = ApiService(client: mockClient);
      final result = await api.checkHealth();

      expect(result['status'], 'healthy');
    });

    test('throws ApiException on non-200 response', () async {
      final mockClient = MockClient((request) async {
        return http.Response('Internal Server Error', 500);
      });

      final api = ApiService(client: mockClient);
      expect(
        () => api.checkHealth(),
        throwsA(isA<ApiException>().having((e) => e.statusCode, 'statusCode', 500)),
      );
    });

    test('throws ApiException on invalid JSON', () async {
      final mockClient = MockClient((request) async {
        return http.Response('not-a-json', 200);
      });

      final api = ApiService(client: mockClient);
      expect(
        () => api.checkHealth(),
        throwsA(isA<ApiException>().having((e) => e.message, 'message', contains('Invalid JSON'))),
      );
    });
  });

  group('ApiService - getTrails', () {
    test('returns list of trail summary maps on 200', () async {
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/api/trails');
        final body = '''
        {
          "count": 2,
          "trails": [
            {"id": "kabaragala_01", "name": "Kabaragala 01", "pointCount": 19},
            {"id": "maragala_01", "name": "Maragala 01", "pointCount": 25}
          ]
        }
        ''';
        return http.Response(body, 200,
            headers: {'content-type': 'application/json'});
      });

      final api = ApiService(client: mockClient);
      final trails = await api.getTrails();

      expect(trails.length, 2);
      expect(trails[0]['id'], 'kabaragala_01');
      expect(trails[1]['name'], 'Maragala 01');
    });

    test('handles top-level list format gracefully', () async {
      final mockClient = MockClient((request) async {
        return http.Response(
            '[{"id": "trail_1", "name": "Trail 1"}]', 200);
      });

      final api = ApiService(client: mockClient);
      final trails = await api.getTrails();

      expect(trails.length, 1);
      expect(trails[0]['id'], 'trail_1');
    });

    test('throws ApiException on unexpected structure', () async {
      final mockClient = MockClient((request) async {
        return http.Response('{"trails": "not-a-list"}', 200);
      });

      final api = ApiService(client: mockClient);
      expect(
        () => api.getTrails(),
        throwsA(isA<ApiException>()),
      );
    });
  });

  group('ApiService - getTrail', () {
    test('returns full trail details with waypoints on 200', () async {
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/api/trails/kabaragala_01');
        final body = '''
        {
          "id": "kabaragala_01",
          "name": "Kabaragala Recorded Track 01",
          "mountain": "Kabaragala",
          "waypoints": [
            {"lat": 7.078361, "lng": 80.515391},
            {"lat": 7.078250, "lng": 80.515378}
          ]
        }
        ''';
        return http.Response(body, 200,
            headers: {'content-type': 'application/json'});
      });

      final api = ApiService(client: mockClient);
      final trail = await api.getTrail('kabaragala_01');

      expect(trail['id'], 'kabaragala_01');
      expect(trail['name'], 'Kabaragala Recorded Track 01');
      final waypoints = trail['waypoints'] as List;
      expect(waypoints.length, 2);
      expect(waypoints[0]['lat'], 7.078361);
    });

    test('throws ApiException on 404 when trail is not found', () async {
      final mockClient = MockClient((request) async {
        return http.Response('{"detail": "Trail not found"}', 404);
      });

      final api = ApiService(client: mockClient);
      expect(
        () => api.getTrail('non_existent_id'),
        throwsA(isA<ApiException>().having((e) => e.statusCode, 'statusCode', 404)),
      );
    });

    test('throws ApiException when id is empty', () async {
      final api = ApiService();
      expect(
        () => api.getTrail('   '),
        throwsA(isA<ApiException>().having((e) => e.message, 'message', contains('cannot be empty'))),
      );
    });
  });

  group('ApiService - network errors & timeouts', () {
    test('throws ApiException on timeout', () async {
      final mockClient = MockClient((request) async {
        await Future.delayed(const Duration(milliseconds: 50));
        return http.Response('ok', 200);
      });

      final api = ApiService(
        client: mockClient,
        timeout: const Duration(milliseconds: 10),
      );

      expect(
        () => api.checkHealth(),
        throwsA(isA<ApiException>().having((e) => e.message, 'message', contains('timed out'))),
      );
    });

    test('throws ApiException on ClientException network failure', () async {
      final mockClient = MockClient((request) async {
        throw http.ClientException('Connection refused');
      });

      final api = ApiService(client: mockClient);
      expect(
        () => api.checkHealth(),
        throwsA(isA<ApiException>().having((e) => e.message, 'message', contains('Network error'))),
      );
    });
  });
}
