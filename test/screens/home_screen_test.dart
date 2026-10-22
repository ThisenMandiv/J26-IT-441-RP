import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:tapropath/screens/home_screen.dart';
import 'package:tapropath/services/api_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('HomeScreen - Backend connectivity badge', () {
    testWidgets('shows "Backend Connected" when health-check returns healthy',
        (WidgetTester tester) async {
      final mockClient = MockClient((request) async {
        if (request.url.path == '/api/health') {
          return http.Response('{"status": "healthy"}', 200,
              headers: {'content-type': 'application/json'});
        }
        if (request.url.path == '/api/trails') {
          return http.Response('{"count": 0, "trails": []}', 200,
              headers: {'content-type': 'application/json'});
        }
        return http.Response('Not found', 404);
      });

      final apiService = ApiService(
        client: mockClient,
        timeout: const Duration(milliseconds: 100),
      );

      await tester.pumpWidget(
        MaterialApp(
          home: HomeScreen(apiService: apiService),
        ),
      );

      for (int i = 0; i < 10; i++) {
        await tester.pump(const Duration(milliseconds: 50));
      }

      expect(find.text('Backend Connected'), findsOneWidget);
      expect(find.text('Available Trails'), findsOneWidget);
    });

    testWidgets('shows "Offline Mode" and preserves local trails when backend fails',
        (WidgetTester tester) async {
      final mockClient = MockClient((request) async {
        throw http.ClientException('Failed to connect to 127.0.0.1:8000');
      });

      final apiService = ApiService(
        client: mockClient,
        timeout: const Duration(milliseconds: 100),
      );

      await tester.pumpWidget(
        MaterialApp(
          home: HomeScreen(apiService: apiService),
        ),
      );

      for (int i = 0; i < 10; i++) {
        await tester.pump(const Duration(milliseconds: 50));
      }

      // Backend status should show Offline Mode
      expect(find.text('Offline Mode'), findsOneWidget);
      // Available trails heading and local dataset should still be loaded
      expect(find.text('Available Trails'), findsOneWidget);
    });

    testWidgets('shows "Checking..." while health check is in progress',
        (WidgetTester tester) async {
      final completer = Completer<http.Response>();

      final mockClient = MockClient((request) async {
        if (request.url.path == '/api/health') {
          return completer.future;
        }
        return http.Response('{"count": 0, "trails": []}', 200);
      });

      final apiService = ApiService(
        client: mockClient,
        timeout: const Duration(seconds: 1),
      );

      await tester.pumpWidget(
        MaterialApp(
          home: HomeScreen(apiService: apiService),
        ),
      );

      // Pump single frame to verify the in-progress checking state
      await tester.pump();
      expect(find.text('Checking...'), findsOneWidget);

      // Now complete the health check
      completer.complete(
        http.Response('{"status": "healthy"}', 200,
            headers: {'content-type': 'application/json'}),
      );

      for (int i = 0; i < 10; i++) {
        await tester.pump(const Duration(milliseconds: 50));
      }

      expect(find.text('Backend Connected'), findsOneWidget);
      expect(find.text('Checking...'), findsNothing);
    });

    testWidgets('tapping Offline Mode retries connection and updates to Connected',
        (WidgetTester tester) async {
      bool backendIsOnline = false;

      final mockClient = MockClient((request) async {
        if (request.url.path == '/api/health') {
          if (!backendIsOnline) {
            return http.Response('Backend unavailable', 503);
          }
          return http.Response('{"status": "healthy"}', 200,
              headers: {'content-type': 'application/json'});
        }
        return http.Response('{"count": 0, "trails": []}', 200);
      });

      final apiService = ApiService(
        client: mockClient,
        timeout: const Duration(milliseconds: 100),
      );

      await tester.pumpWidget(
        MaterialApp(
          home: HomeScreen(apiService: apiService),
        ),
      );

      for (int i = 0; i < 10; i++) {
        await tester.pump(const Duration(milliseconds: 50));
      }

      // Initially offline
      expect(find.text('Offline Mode'), findsOneWidget);

      // Simulate backend coming online
      backendIsOnline = true;

      // Tap the badge to retry
      await tester.tap(find.text('Offline Mode'));
      for (int i = 0; i < 10; i++) {
        await tester.pump(const Duration(milliseconds: 50));
      }

      // Now it should be connected
      expect(find.text('Backend Connected'), findsOneWidget);
      expect(find.text('Offline Mode'), findsNothing);
    });
  });
}
