import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;

/// Custom exception thrown when API requests fail.
class ApiException implements Exception {
  final String message;
  final int? statusCode;
  final dynamic cause;

  const ApiException(this.message, {this.statusCode, this.cause});

  @override
  String toString() {
    if (statusCode != null) {
      return 'ApiException (HTTP $statusCode): $message';
    }
    return 'ApiException: $message';
  }
}

/// Service client for communicating with the Tapro Path backend API.
class ApiService {
  static const String defaultBaseUrl = 'http://127.0.0.1:8000';
  static const Duration defaultTimeout = Duration(seconds: 5);

  final String baseUrl;
  final Duration timeout;
  final http.Client _client;

  ApiService({
    this.baseUrl = defaultBaseUrl,
    this.timeout = defaultTimeout,
    http.Client? client,
  }) : _client = client ?? http.Client();

  /// Helper to send a GET request, enforce timeout, and handle errors.
  Future<dynamic> _getJson(Uri uri) async {
    final http.Response response;
    try {
      response = await _client.get(uri).timeout(timeout);
    } on TimeoutException catch (e) {
      throw ApiException(
        'Request timed out after ${timeout.inSeconds}s for $uri',
        cause: e,
      );
    } on http.ClientException catch (e) {
      throw ApiException(
        'Network error while connecting to $uri: ${e.message}',
        cause: e,
      );
    } catch (e) {
      throw ApiException(
        'Unexpected connection error for $uri: $e',
        cause: e,
      );
    }

    if (response.statusCode != 200) {
      throw ApiException(
        'Request failed with status ${response.statusCode}: ${response.body}',
        statusCode: response.statusCode,
      );
    }

    try {
      return jsonDecode(response.body);
    } on FormatException catch (e) {
      throw ApiException(
        'Invalid JSON response received from $uri: ${e.message}',
        cause: e,
      );
    }
  }

  /// Checks whether the backend server is online and healthy.
  ///
  /// Calls GET `/api/health` and returns the health payload.
  Future<Map<String, dynamic>> checkHealth() async {
    final uri = Uri.parse('$baseUrl/api/health');
    final data = await _getJson(uri);

    if (data is Map) {
      return Map<String, dynamic>.from(data);
    }

    throw ApiException(
      'Unexpected response format from $uri: expected JSON object',
    );
  }

  /// Fetches trail summaries from the backend.
  ///
  /// Calls GET `/api/trails` and returns a list of trail summary maps.
  Future<List<Map<String, dynamic>>> getTrails() async {
    final uri = Uri.parse('$baseUrl/api/trails');
    final data = await _getJson(uri);

    List<dynamic>? list;
    if (data is Map && data['trails'] is List) {
      list = data['trails'] as List<dynamic>;
    } else if (data is List) {
      list = data;
    }

    if (list != null) {
      return list
          .whereType<Map>()
          .map((item) => Map<String, dynamic>.from(item))
          .toList();
    }

    throw ApiException(
      'Unexpected response format from $uri: expected "trails" list',
    );
  }

  /// Fetches full trail details and GPS waypoints for a specific trail by ID.
  ///
  /// Calls GET `/api/trails/{trail_id}`.
  Future<Map<String, dynamic>> getTrail(String id) async {
    if (id.trim().isEmpty) {
      throw const ApiException('Trail ID cannot be empty');
    }

    final encodedId = Uri.encodeComponent(id.trim());
    final uri = Uri.parse('$baseUrl/api/trails/$encodedId');
    final data = await _getJson(uri);

    if (data is Map) {
      return Map<String, dynamic>.from(data);
    }

    throw ApiException(
      'Unexpected response format from $uri: expected trail object',
    );
  }

  /// Closes the underlying HTTP client.
  void dispose() {
    _client.close();
  }
}