import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart' show AssetBundle, rootBundle;

import '../models/trail_model.dart';
import 'api_service.dart';

/// Loads hiking trails using an offline-first strategy:
/// combines local bundled datasets with fresh summaries from the backend API.
class TrailDataService {
  static const String _demoAssetPath = 'assets/data/trails.json';
  static const String _recordedAssetPath =
      'assets/data/recorded_trails.json';

  final ApiService apiService;
  final AssetBundle _bundle;

  TrailDataService({
    ApiService? apiService,
    AssetBundle? bundle,
  })  : apiService = apiService ?? ApiService(),
        _bundle = bundle ?? rootBundle;

  /// Loads both demo trails and recorded GPS tracks bundled with the app.
  Future<List<Trail>> loadLocalTrails() async {
    final List<Trail> allTrails = [];

    // Load demonstration trails.
    try {
      final String raw = await _bundle.loadString(_demoAssetPath);
      final Map<String, dynamic> json =
          jsonDecode(raw) as Map<String, dynamic>;
      final List<dynamic> trailsJson = json['trails'] as List<dynamic>;

      allTrails.addAll(
        trailsJson.map(
          (item) => Trail.fromJson(
            Map<String, dynamic>.from(item as Map),
          ),
        ),
      );
    } catch (e) {
      debugPrint('Could not load demo trails: $e');
    }

    // Load recorded GPX tracks.
    try {
      final String raw = await _bundle.loadString(_recordedAssetPath);
      final Map<String, dynamic> json =
          jsonDecode(raw) as Map<String, dynamic>;
      final List<dynamic> trailsJson = json['trails'] as List<dynamic>;

      allTrails.addAll(
        trailsJson.map(
          (item) => Trail.fromJson(
            Map<String, dynamic>.from(item as Map),
          ),
        ),
      );
    } catch (e) {
      debugPrint('Could not load recorded GPS tracks: $e');
    }

    return allTrails;
  }

  /// Merges local trails with API summaries.
  ///
  /// Precedence rules:
  /// - Stable ID matching: matches records by [Trail.id].
  /// - Metadata: values provided by the API override local values.
  /// - Waypoints: local GPS waypoints are preserved unless the API
  ///   explicitly provides non-empty waypoints.
  /// - Non-overlapping records: local trails not in the API response
  ///   are preserved (never discarded).
  /// - New API records: trails present in API but not local are appended.
  /// - Duplicates: duplicate IDs in the API response overwrite previous
  ///   entries under the same ID instead of duplicating the trail card.
  static List<Trail> mergeTrails(
    List<Trail> localTrails,
    List<Map<String, dynamic>> apiSummaries,
  ) {
    final Map<String, Trail> trailMap = {};
    for (final trail in localTrails) {
      trailMap[trail.id] = trail;
    }

    for (final api in apiSummaries) {
      final id = api['id']?.toString().trim();
      if (id == null || id.isEmpty) continue;

      final local = trailMap[id];
      if (local != null) {
        // Merge with existing local trail, preserving waypoints.
        final List<TrailWaypoint> waypoints;
        final rawWp = api['waypoints'];
        if (rawWp is List && rawWp.isNotEmpty) {
          waypoints = rawWp.asMap().entries.map((entry) {
            return TrailWaypoint.fromJson(
              Map<String, dynamic>.from(entry.value as Map),
              fallbackName: 'GPS Point ${entry.key + 1}',
            );
          }).toList();
        } else {
          waypoints = local.waypoints;
        }

        final verified = api['verifiedForNavigation'] as bool? ??
            local.verifiedForNavigation;

        trailMap[id] = Trail(
          id: id,
          name: api['name'] as String? ?? local.name,
          region: (api['region'] ?? api['mountain'] ?? local.region) as String,
          description: api['description'] as String? ?? local.description,
          difficulty: api['difficulty'] as String? ?? local.difficulty,
          distanceKm: (api['distance_km'] as num?)?.toDouble() ??
              (api['recordedDistanceKm'] as num?)?.toDouble() ??
              local.distanceKm,
          estimatedDurationHours:
              (api['estimated_duration_hours'] as num?)?.toDouble() ??
                  local.estimatedDurationHours,
          elevationStartM: (api['elevation_start_m'] as num?)?.toDouble() ??
              local.elevationStartM,
          elevationPeakM: (api['elevation_peak_m'] as num?)?.toDouble() ??
              local.elevationPeakM,
          bestSeason: api['best_season'] as String? ?? local.bestSeason,
          routeStatus: api['route_status'] as String? ??
              (api['verifiedForNavigation'] == true
                  ? 'Verified for navigation'
                  : local.routeStatus),
          waypoints: waypoints,
          sourceFile: api['sourceFile'] as String? ?? local.sourceFile,
          recordingType:
              api['recordingType'] as String? ?? local.recordingType,
          verifiedForNavigation: verified,
          hasTimestamps: (api['hasTimestamps'] as bool?) ?? local.hasTimestamps,
        );
      } else {
        // Brand-new trail from backend API.
        trailMap[id] = Trail.fromJson(api);
      }
    }

    return trailMap.values.toList();
  }

  /// Retrieves trails using an offline-first strategy:
  /// 1. Loads bundled local trails as the guaranteed offline baseline.
  /// 2. Attempts to fetch fresh trail summaries from [ApiService].
  /// 3. If the backend is unreachable or fails, falls back to local trails.
  /// 4. If backend succeeds, merges metadata while preserving local waypoints.
  Future<List<Trail>> getTrails() async {
    final localTrails = await loadLocalTrails();

    try {
      final apiSummaries = await apiService.getTrails();
      if (apiSummaries.isEmpty) {
        return localTrails;
      }
      return mergeTrails(localTrails, apiSummaries);
    } catch (e) {
      debugPrint('Backend unavailable, falling back to local trails: $e');
      return localTrails;
    }
  }

  /// Static convenience method matching existing caller in home_screen.dart.
  static Future<List<Trail>> loadTrails({
    ApiService? apiService,
    AssetBundle? bundle,
  }) async {
    final service = TrailDataService(
      apiService: apiService,
      bundle: bundle,
    );
    return service.getTrails();
  }
}

