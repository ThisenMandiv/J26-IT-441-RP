import 'dart:convert';

import 'package:http/http.dart' as http;

class RecommendationService {
  // For Flutter Web running in Chrome on the same computer as FastAPI.
  static const String _baseUrl = 'http://127.0.0.1:8000';

  static const Map<String, String> _interestKeys = {
    'Nature': 'nature_score',
    'Hiking': 'hiking_score',
    'Photography': 'photography_score',
    'Beaches': 'beach_score',
    'Wildlife': 'wildlife_score',
    'History': 'heritage_score',
    'Food': 'food_score',
  };

  static const Map<String, String> _activityKeys = {
    'Hiking': 'trekking',
    'Waterfalls': 'waterfall_visit',
    'Scenic Viewing': 'scenic_viewing',
    'Temple Visits': 'temple_visit',
    'Safari': 'safari',
    'Surfing': 'surfing',
  };

  static const Map<String, String> _styleKeys = {
    'Adventure': 'adventurer_score',
    'Culture': 'cultural_traveler_score',
    'Relaxation': 'relaxer_score',
    'Luxury': 'luxury_traveler_score',
  };

  static Map<String, double> _buildScores(
    Map<String, String> supportedKeys,
    Set<String> selectedLabels,
  ) {
    return {
      for (final entry in supportedKeys.entries)
        entry.value: selectedLabels.contains(entry.key) ? 5.0 : 0.0,
    };
  }

  static Future<Map<String, dynamic>> getRecommendations({
    required int durationDays,
    required int totalBudget,
    required String travelGroup,
    required String travelStyle,
    required Set<String> selectedInterests,
    required Set<String> selectedActivities,
    int topN = 5,
  }) async {
    final body = <String, dynamic>{
      'user_id': 'flutter_user',
      'interests': _buildScores(_interestKeys, selectedInterests),
      'activities': _buildScores(_activityKeys, selectedActivities),
      'travel_styles': _buildScores(_styleKeys, {travelStyle}),
      'trip_duration_days': durationDays,
      'total_budget_per_person': totalBudget,
      'travel_group': travelGroup.toLowerCase(),
      'family_only': travelGroup.toLowerCase() == 'family',
    };

    final uri = Uri.parse(
      '$_baseUrl/api/v1/recommend',
    ).replace(queryParameters: {'top_n': '$topN'});

    final response = await http
        .post(
          uri,
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode(body),
        )
        .timeout(const Duration(seconds: 30));

    final dynamic decoded;
    try {
      decoded = jsonDecode(response.body);
    } on FormatException {
      throw Exception(
        'The recommendation server returned an invalid response '
        '(HTTP ${response.statusCode}).',
      );
    }

    if (response.statusCode < 200 || response.statusCode >= 300) {
      final detail = decoded is Map<String, dynamic>
          ? decoded['detail']?.toString()
          : null;

      throw Exception(
        detail ??
            'Recommendation request failed '
                '(HTTP ${response.statusCode}).',
      );
    }

    if (decoded is! Map<String, dynamic>) {
      throw Exception('Unexpected recommendation response format.');
    }

    return decoded;
  }
}
