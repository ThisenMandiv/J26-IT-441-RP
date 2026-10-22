
class LatLng {
  final double lat;
  final double lng;

  const LatLng({required this.lat, required this.lng});

  factory LatLng.fromJson(Map<String, dynamic> json) => LatLng(
        lat: (json['lat'] as num).toDouble(),
        lng: (json['lng'] as num).toDouble(),
      );

  Map<String, dynamic> toJson() => {'lat': lat, 'lng': lng};

  @override
  String toString() => 'LatLng($lat, $lng)';
}

class TrailWaypoint {
  final String name;
  final LatLng position;
  final String? timestamp;

  const TrailWaypoint({
    required this.name,
    required this.position,
    this.timestamp,
  });

  factory TrailWaypoint.fromJson(
    Map<String, dynamic> json, {
    String? fallbackName,
  }) {
    return TrailWaypoint(
      name: json['name'] as String? ?? fallbackName ?? 'GPS Point',
      position: LatLng.fromJson(json),
      timestamp: json['timestamp'] as String?,
    );
  }
}

class Trail {
  final String id;
  final String name;
  final String region;
  final String description;
  final String difficulty;
  final double? distanceKm;
  final double? estimatedDurationHours;
  final double? elevationStartM;
  final double? elevationPeakM;
  final String bestSeason;
  final String routeStatus;
  final List<TrailWaypoint> waypoints;

  // Additional information for recorded GPS tracks.
  final String? sourceFile;
  final String? recordingType;
  final bool verifiedForNavigation;
  final bool hasTimestamps;

  const Trail({
    required this.id,
    required this.name,
    required this.region,
    required this.description,
    required this.difficulty,
    this.distanceKm,
    this.estimatedDurationHours,
    this.elevationStartM,
    this.elevationPeakM,
    required this.bestSeason,
    required this.routeStatus,
    required this.waypoints,
    this.sourceFile,
    this.recordingType,
    this.verifiedForNavigation = false,
    this.hasTimestamps = false,
  });

  factory Trail.fromJson(Map<String, dynamic> json) {
    // Supports both the demo dataset and recorded_trails.json.
    final isRecordedTrack = json.containsKey('mountain');

    final rawWaypoints = json['waypoints'] as List<dynamic>? ?? [];

    final waypoints = rawWaypoints.asMap().entries.map((entry) {
      final waypointJson = Map<String, dynamic>.from(
        entry.value as Map,
      );

      return TrailWaypoint.fromJson(
        waypointJson,
        fallbackName: 'GPS Point ${entry.key + 1}',
      );
    }).toList();

    final verified = json['verifiedForNavigation'] as bool? ?? false;

    return Trail(
      id: json['id'] as String,
      name: json['name'] as String,
      region: (json['region'] ?? json['mountain'] ?? 'Unknown region')
          as String,
      description: (json['description'] ??
              (isRecordedTrack
                  ? 'Recorded GPS track collected for research. '
                      'This track has not yet been verified for navigation.'
                  : 'Demonstration trail data.'))
          as String,
      difficulty: (json['difficulty'] ?? 'Not assessed') as String,
      distanceKm: (json['distance_km'] as num?)?.toDouble() ??
          (json['recordedDistanceKm'] as num?)?.toDouble(),
      estimatedDurationHours:
          (json['estimated_duration_hours'] as num?)?.toDouble(),
      elevationStartM: (json['elevation_start_m'] as num?)?.toDouble(),
      elevationPeakM: (json['elevation_peak_m'] as num?)?.toDouble(),
      bestSeason: (json['best_season'] ?? 'Not specified') as String,
      routeStatus: (json['route_status'] ??
              (verified
                  ? 'Verified for navigation'
                  : 'Recorded track — not verified for navigation'))
          as String,
      waypoints: waypoints,
      sourceFile: json['sourceFile'] as String?,
      recordingType: json['recordingType'] as String?,
      verifiedForNavigation: verified,
      hasTimestamps: json['hasTimestamps'] as bool? ?? false,
    );
  }

  List<LatLng> get routePoints =>
      waypoints.map((waypoint) => waypoint.position).toList();
}
