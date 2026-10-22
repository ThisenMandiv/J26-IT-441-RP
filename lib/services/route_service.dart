import 'dart:math' as math;
import '../models/trail_model.dart';

/// RouteService — pure Dart service for offline route calculations.
/// No external packages required. All math uses the Haversine formula.
class RouteService {
  /// Earth's mean radius in metres.
  static const double _earthRadiusMetres = 6371000.0;

  /// Default warning threshold in metres. Configurable per call.
  static const double defaultOffRouteThresholdMetres = 50.0;

  // ---------------------------------------------------------------------------
  // Core geodesic math
  // ---------------------------------------------------------------------------

  /// Haversine distance between two GPS positions (in metres).
  static double haversineDistanceMetres(LatLng a, LatLng b) {
    final dLat = _toRad(b.lat - a.lat);
    final dLng = _toRad(b.lng - a.lng);
    final sinDLat = math.sin(dLat / 2);
    final sinDLng = math.sin(dLng / 2);
    final h = sinDLat * sinDLat +
        math.cos(_toRad(a.lat)) * math.cos(_toRad(b.lat)) * sinDLng * sinDLng;
    return 2 * _earthRadiusMetres * math.asin(math.sqrt(h));
  }

  static double _toRad(double deg) => deg * math.pi / 180.0;

  // ---------------------------------------------------------------------------
  // Off-route detection
  // ---------------------------------------------------------------------------

  /// Calculates the perpendicular distance (in metres) from [testPosition]
  /// to the nearest segment of the route defined by [routePoints], as well as
  /// the exact nearest point on that segment and the return bearing.
  ///
  /// Returns a [OffRouteResult] containing distance, nearest segment index,
  /// nearest point coordinates, return bearing, and compass direction.
  ///
  /// The route must have at least 2 waypoints; otherwise returns max distance.
  static OffRouteResult distanceToNearestRouteSegment(
    LatLng testPosition,
    List<LatLng> routePoints,
  ) {
    if (routePoints.isEmpty) {
      return const OffRouteResult(
        distanceMetres: double.infinity,
        nearestSegmentIndex: -1,
      );
    }
    if (routePoints.length == 1) {
      final target = routePoints.first;
      final dist = haversineDistanceMetres(testPosition, target);
      final bearing = bearingDegrees(testPosition, target);
      return OffRouteResult(
        distanceMetres: dist,
        nearestSegmentIndex: 0,
        nearestPoint: target,
        returnBearingDegrees: bearing,
        returnCompassDirection: compassDirection(bearing),
      );
    }

    double minDistance = double.infinity;
    int nearestIdx = 0;
    LatLng nearestPt = routePoints.first;

    for (int i = 0; i < routePoints.length - 1; i++) {
      final projection = _closestPointOnSegment(
        testPosition,
        routePoints[i],
        routePoints[i + 1],
      );
      if (projection.distanceMetres < minDistance) {
        minDistance = projection.distanceMetres;
        nearestIdx = i;
        nearestPt = projection.point;
      }
    }

    final bearing = bearingDegrees(testPosition, nearestPt);

    return OffRouteResult(
      distanceMetres: minDistance,
      nearestSegmentIndex: nearestIdx,
      nearestPoint: nearestPt,
      returnBearingDegrees: bearing,
      returnCompassDirection: compassDirection(bearing),
    );
  }

  /// Checks whether [testPosition] is off the route by more than [thresholdMetres].
  ///
  /// [thresholdMetres] defaults to [defaultOffRouteThresholdMetres].
  static bool isOffRoute(
    LatLng testPosition,
    List<LatLng> routePoints, {
    double thresholdMetres = defaultOffRouteThresholdMetres,
  }) {
    final result = distanceToNearestRouteSegment(testPosition, routePoints);
    return result.distanceMetres > thresholdMetres;
  }

  // ---------------------------------------------------------------------------
  // Segment perpendicular projection & closest point
  // ---------------------------------------------------------------------------

  /// Calculates the closest point on segment [a]→[b] to point [p], and the Haversine distance in metres.
  /// Uses flat-earth projection for short hiking segments (<50 km).
  static _SegmentProjection _closestPointOnSegment(LatLng p, LatLng a, LatLng b) {
    final double cosLat = math.cos(_toRad(a.lat));
    const double metresPerDeg = 111320.0;

    final double ax = 0.0, ay = 0.0;
    final double bx = (b.lng - a.lng) * metresPerDeg * cosLat;
    final double by = (b.lat - a.lat) * metresPerDeg;
    final double px = (p.lng - a.lng) * metresPerDeg * cosLat;
    final double py = (p.lat - a.lat) * metresPerDeg;

    final double abx = bx - ax, aby = by - ay;
    final double segLenSq = abx * abx + aby * aby;

    if (segLenSq == 0.0) {
      final dist = haversineDistanceMetres(p, a);
      return _SegmentProjection(point: a, distanceMetres: dist);
    }

    final double t = ((px - ax) * abx + (py - ay) * aby) / segLenSq;
    final double tc = t.clamp(0.0, 1.0);

    final double closestLat = a.lat + tc * (b.lat - a.lat);
    final double closestLng = a.lng + tc * (b.lng - a.lng);
    final closestPoint = LatLng(lat: closestLat, lng: closestLng);

    final dist = haversineDistanceMetres(p, closestPoint);
    return _SegmentProjection(point: closestPoint, distanceMetres: dist);
  }

  /// Perpendicular distance from point [p] to segment [a]→[b] in metres.
  static double distanceToSegmentMetres(LatLng p, LatLng a, LatLng b) =>
      _closestPointOnSegment(p, a, b).distanceMetres;

  /// Converts a bearing in degrees (0–360°) to a 16-point cardinal compass string.
  static String compassDirection(double bearingDegrees) {
    const directions = [
      'N', 'NNE', 'NE', 'ENE',
      'E', 'ESE', 'SE', 'SSE',
      'S', 'SSW', 'SW', 'WSW',
      'W', 'WNW', 'NW', 'NNW'
    ];
    final normalized = (bearingDegrees % 360.0 + 360.0) % 360.0;
    final index = ((normalized + 11.25) / 22.5).floor() % 16;
    return directions[index];
  }

  // ---------------------------------------------------------------------------
  // Route statistics
  // ---------------------------------------------------------------------------

  /// Total polyline length in metres from an ordered list of route points.
  static double totalRouteLengthMetres(List<LatLng> routePoints) {
    double total = 0.0;
    for (int i = 0; i < routePoints.length - 1; i++) {
      total += haversineDistanceMetres(routePoints[i], routePoints[i + 1]);
    }
    return total;
  }

  /// Compares two recorded routes using point-to-route distances.
  /// Both routes must contain at least two GPS points.
  static RouteComparisonResult compareRoutes(
    List<LatLng> routeA,
    List<LatLng> routeB, {
    double thresholdMetres = defaultOffRouteThresholdMetres,
  }) {
    if (routeA.length < 2 || routeB.length < 2) {
      throw ArgumentError(
        'Both routes must contain at least two GPS points.',
      );
    }

    double totalDeviation = 0;
    double maximumDeviation = 0;
    int pointsWithinThreshold = 0;
    int pointsCompared = 0;

    // Compare every point in A against route B,
    // then every point in B against route A.
    void compareDirection(
      List<LatLng> points,
      List<LatLng> referenceRoute,
    ) {
      for (final point in points) {
        final result = distanceToNearestRouteSegment(
          point,
          referenceRoute,
        );

        final distance = result.distanceMetres;
        totalDeviation += distance;

        if (distance > maximumDeviation) {
          maximumDeviation = distance;
        }

        if (distance <= thresholdMetres) {
          pointsWithinThreshold++;
        }

        pointsCompared++;
      }
    }

    compareDirection(routeA, routeB);
    compareDirection(routeB, routeA);

    return RouteComparisonResult(
      averageDeviationMetres: totalDeviation / pointsCompared,
      maximumDeviationMetres: maximumDeviation,
      percentWithinThreshold:
          pointsWithinThreshold / pointsCompared * 100,
      thresholdMetres: thresholdMetres,
      pointsCompared: pointsCompared,
    );
  }

  /// Normalised bearing (0–360°) from [a] to [b].
  static double bearingDegrees(LatLng a, LatLng b) {
    final dLng = _toRad(b.lng - a.lng);
    final lat1 = _toRad(a.lat);
    final lat2 = _toRad(b.lat);
    final y = math.sin(dLng) * math.cos(lat2);
    final x =
        math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dLng);
    return (math.atan2(y, x) * 180.0 / math.pi + 360.0) % 360.0;
  }
}

/// Result of an off-route distance calculation including directional return guidance.
class OffRouteResult {
  final double distanceMetres;
  final int nearestSegmentIndex;
  final LatLng? nearestPoint;
  final double? returnBearingDegrees;
  final String? returnCompassDirection;

  const OffRouteResult({
    required this.distanceMetres,
    required this.nearestSegmentIndex,
    this.nearestPoint,
    this.returnBearingDegrees,
    this.returnCompassDirection,
  });

  bool isOffRoute({double thresholdMetres = RouteService.defaultOffRouteThresholdMetres}) =>
      distanceMetres > thresholdMetres;

  String get formattedDistance {
    if (distanceMetres.isInfinite) return '∞';
    if (distanceMetres >= 1000) {
      return '${(distanceMetres / 1000).toStringAsFixed(2)} km';
    }
    return '${distanceMetres.toStringAsFixed(1)} m';
  }

  String get formattedBearing {
    if (returnBearingDegrees == null || returnCompassDirection == null) {
      return 'N/A';
    }
    return '${returnBearingDegrees!.toStringAsFixed(0)}° $returnCompassDirection';
  }
}

class _SegmentProjection {
  final LatLng point;
  final double distanceMetres;

  const _SegmentProjection({required this.point, required this.distanceMetres});
}

/// Summary of a comparison between two GPS tracks.
class RouteComparisonResult {
  final double averageDeviationMetres;
  final double maximumDeviationMetres;
  final double percentWithinThreshold;
  final double thresholdMetres;
  final int pointsCompared;

  const RouteComparisonResult({
    required this.averageDeviationMetres,
    required this.maximumDeviationMetres,
    required this.percentWithinThreshold,
    required this.thresholdMetres,
    required this.pointsCompared,
  });
}

