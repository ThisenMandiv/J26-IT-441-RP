import 'package:flutter/material.dart';

import 'dart:math' as math;

import '../models/trail_model.dart';
import '../services/route_service.dart';
import 'tracking_screen.dart';
import 'navigation_map_screen.dart';

/// Trail Detail Screen — shows metadata, route status, and a canvas polyline preview.
/// No external map tiles are used; the route preview is a custom-painted widget.
class TrailDetailScreen extends StatelessWidget {
  final Trail trail;

  const TrailDetailScreen({super.key, required this.trail});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0F1B12),
      body: CustomScrollView(
        slivers: [
          SliverAppBar(
            pinned: true,
            backgroundColor: const Color(0xFF0F1B12),
            foregroundColor: Colors.white,
            title: Text(
              trail.name,
              style: const TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w700,
                color: Colors.white,
              ),
              overflow: TextOverflow.ellipsis,
            ),
            actions: [
              TextButton.icon(
                onPressed: () => Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder: (_) => TrackingScreen(trail: trail),
                  ),
                ),
                icon: const Icon(
                  Icons.play_arrow,
                  color: Color(0xFF7DD87A),
                  size: 18,
                ),
                label: const Text(
                  'Track',
                  style: TextStyle(color: Color(0xFF7DD87A)),
                ),
              ),
            ],
          ),
          SliverToBoxAdapter(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Route preview map

                _RoutePreviewCanvas(trail: trail),

                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
                  child: SizedBox(
                    width: double.infinity,
                    child: ElevatedButton.icon(
                      onPressed: () {
                        Navigator.push(
                          context,
                          MaterialPageRoute(
                            builder: (_) => NavigationMapScreen(trail: trail),
                          ),
                        );
                      },
                      icon: const Icon(Icons.map_outlined),
                      label: const Text('Open Map'),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: const Color(0xFF7DD87A),
                        foregroundColor: const Color(0xFF0F1B12),
                        padding: const EdgeInsets.symmetric(vertical: 14),
                      ),
                    ),
                  ),
                ),

                // Metadata section
                Padding(
                  padding: const EdgeInsets.all(20),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      // Route status warning banner
                      _RouteStatusBanner(status: trail.routeStatus),
                      const SizedBox(height: 20),
                      // Stats grid
                      _StatsGrid(trail: trail),
                      const SizedBox(height: 20),
                      // Description
                      const Text(
                        'About This Trail',
                        style: TextStyle(
                          color: Colors.white,
                          fontSize: 16,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        trail.description,
                        style: TextStyle(
                          color: Colors.white.withValues(alpha: 0.7),
                          fontSize: 14,
                          height: 1.6,
                        ),
                      ),
                      const SizedBox(height: 24),
                      // Waypoints list
                      const Text(
                        'Route Waypoints',
                        style: TextStyle(
                          color: Colors.white,
                          fontSize: 16,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        trail.sourceFile != null
                            ? 'Recorded GPS data — not yet verified for navigation'
                            : 'Approximate coordinates — demonstration data only',
                        style: TextStyle(
                          color: Colors.amber.withValues(alpha: 0.7),
                          fontSize: 12,
                        ),
                      ),
                      const SizedBox(height: 12),
                      ...trail.waypoints.asMap().entries.map(
                        (entry) => _WaypointRow(
                          index: entry.key,
                          waypoint: entry.value,
                          isLast: entry.key == trail.waypoints.length - 1,
                        ),
                      ),
                      const SizedBox(height: 24),
                      // Computed route length
                      _ComputedRouteInfo(trail: trail),
                      const SizedBox(height: 32),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Route preview canvas
// ---------------------------------------------------------------------------

class _RoutePreviewCanvas extends StatelessWidget {
  final Trail trail;

  const _RoutePreviewCanvas({required this.trail});

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 280,
      margin: const EdgeInsets.fromLTRB(16, 8, 16, 0),
      decoration: BoxDecoration(
        color: const Color(0xFF152518),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(20),
        child: Stack(
          children: [
            // Canvas route
            CustomPaint(
              painter: _RoutePainter(routePoints: trail.routePoints),
              child: const SizedBox.expand(),
            ),
            // Label overlay
            Positioned(
              top: 12,
              left: 12,
              child: Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 10,
                  vertical: 5,
                ),
                decoration: BoxDecoration(
                  color: Colors.black.withValues(alpha: 0.55),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      Icons.map_outlined,
                      color: Color(0xFF7DD87A),
                      size: 13,
                    ),
                    SizedBox(width: 5),
                    Text(
                      trail.sourceFile != null
                          ? 'Recorded GPS Track'
                          : 'Route Preview — Demo Coordinates',
                      style: TextStyle(color: Colors.white70, fontSize: 11),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _RoutePainter extends CustomPainter {
  final List<LatLng> routePoints;

  _RoutePainter({required this.routePoints});

  @override
  void paint(Canvas canvas, Size size) {
    if (routePoints.length < 2) return;

    // Determine bounding box
    double minLat = routePoints.first.lat;
    double maxLat = routePoints.first.lat;
    double minLng = routePoints.first.lng;
    double maxLng = routePoints.first.lng;
    for (final p in routePoints) {
      if (p.lat < minLat) minLat = p.lat;
      if (p.lat > maxLat) maxLat = p.lat;
      if (p.lng < minLng) minLng = p.lng;
      if (p.lng > maxLng) maxLng = p.lng;
    }

    final padding = size.width * 0.12;
    final drawW = size.width - padding * 2;
    final drawH = size.height - padding * 2;
    final latRange = maxLat - minLat;
    final lngRange = maxLng - minLng;
    final scale = math.min(
      drawW / (lngRange == 0 ? 1 : lngRange),
      drawH / (latRange == 0 ? 1 : latRange),
    );

    Offset toCanvas(LatLng p) {
      final x = padding + (p.lng - minLng) * scale;
      // Invert Y: higher lat = higher on screen
      final y = padding + drawH - (p.lat - minLat) * scale;
      return Offset(x, y);
    }

    // Background grid
    final gridPaint = Paint()
      ..color = Colors.white.withValues(alpha: 0.05)
      ..strokeWidth = 0.5;
    for (int i = 1; i <= 5; i++) {
      final x = size.width / 6 * i;
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), gridPaint);
      final y = size.height / 6 * i;
      canvas.drawLine(Offset(0, y), Offset(size.width, y), gridPaint);
    }

    // Shadow / glow line
    final glowPaint = Paint()
      ..color = const Color(0xFF7DD87A).withValues(alpha: 0.15)
      ..strokeWidth = 10
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round
      ..style = PaintingStyle.stroke;

    final path = Path();
    path.moveTo(toCanvas(routePoints.first).dx, toCanvas(routePoints.first).dy);
    for (final p in routePoints.skip(1)) {
      final o = toCanvas(p);
      path.lineTo(o.dx, o.dy);
    }
    canvas.drawPath(path, glowPaint);

    // Main route line
    final linePaint = Paint()
      ..color = const Color(0xFF7DD87A)
      ..strokeWidth = 3
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round
      ..style = PaintingStyle.stroke;
    canvas.drawPath(path, linePaint);

    // Direction arrows on segments
    final arrowPaint = Paint()
      ..color = const Color(0xFF7DD87A).withValues(alpha: 0.6)
      ..strokeWidth = 1.5
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round;
    for (int i = 0; i < routePoints.length - 1; i++) {
      final a = toCanvas(routePoints[i]);
      final b = toCanvas(routePoints[i + 1]);
      final mid = Offset((a.dx + b.dx) / 2, (a.dy + b.dy) / 2);
      final angle = math.atan2(b.dy - a.dy, b.dx - a.dx);
      const arrowSize = 6.0;
      canvas.drawLine(
        mid,
        Offset(
          mid.dx - arrowSize * math.cos(angle - 0.4),
          mid.dy - arrowSize * math.sin(angle - 0.4),
        ),
        arrowPaint,
      );
      canvas.drawLine(
        mid,
        Offset(
          mid.dx - arrowSize * math.cos(angle + 0.4),
          mid.dy - arrowSize * math.sin(angle + 0.4),
        ),
        arrowPaint,
      );
    }

    // Waypoint dots
    final dotPaint = Paint()..style = PaintingStyle.fill;
    for (int i = 0; i < routePoints.length; i++) {
      final o = toCanvas(routePoints[i]);
      final isFirst = i == 0;
      final isLast = i == routePoints.length - 1;
      dotPaint.color = isFirst
          ? const Color(0xFF7DD87A)
          : isLast
          ? const Color(0xFFFF6B6B)
          : Colors.white.withValues(alpha: 0.6);
      canvas.drawCircle(o, isFirst || isLast ? 6 : 3, dotPaint);
      // White border
      canvas.drawCircle(
        o,
        isFirst || isLast ? 6 : 3,
        Paint()
          ..color = Colors.white.withValues(alpha: 0.3)
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.5,
      );
    }
  }

  @override
  bool shouldRepaint(covariant _RoutePainter old) =>
      old.routePoints != routePoints;
}

// ---------------------------------------------------------------------------
// Metadata widgets
// ---------------------------------------------------------------------------

class _RouteStatusBanner extends StatelessWidget {
  final String status;

  const _RouteStatusBanner({required this.status});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.amber.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: Colors.amber.withValues(alpha: 0.35)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(
            Icons.warning_amber_rounded,
            color: Colors.amber,
            size: 18,
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              status,
              style: const TextStyle(
                color: Colors.amber,
                fontSize: 12,
                height: 1.4,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _StatsGrid extends StatelessWidget {
  final Trail trail;

  const _StatsGrid({required this.trail});

  @override
  Widget build(BuildContext context) {
    return GridView.count(
      crossAxisCount: 2,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      crossAxisSpacing: 10,
      mainAxisSpacing: 10,
      childAspectRatio: 2.4,
      children: [
        _StatCell(
          icon: Icons.straighten,
          label: 'Distance',
          value: trail.distanceKm != null
              ? '${trail.distanceKm} km'
              : 'Not specified',
          color: const Color(0xFF6EC6E6),
        ),
        _StatCell(
          icon: Icons.schedule,
          label: 'Est. Duration',
          value: trail.estimatedDurationHours != null
              ? '${trail.estimatedDurationHours!.toStringAsFixed(0)} hrs'
              : 'N/A',
          color: const Color(0xFFFFD166),
        ),
        _StatCell(
          icon: Icons.vertical_align_bottom,
          label: 'Start Elevation',
          value: trail.elevationStartM != null
              ? '${trail.elevationStartM!.toStringAsFixed(0)} m'
              : 'N/A',
          color: const Color(0xFF9ECBA0),
        ),
        _StatCell(
          icon: Icons.arrow_upward,
          label: 'Peak Elevation',
          value: trail.elevationPeakM != null
              ? '${trail.elevationPeakM!.toStringAsFixed(0)} m'
              : 'N/A',
          color: const Color(0xFFFF6B6B),
        ),
      ],
    );
  }
}

class _StatCell extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;
  final Color color;

  const _StatCell({
    required this.icon,
    required this.label,
    required this.value,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: const Color(0xFF1A2E1C),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white.withValues(alpha: 0.07)),
      ),
      child: Row(
        children: [
          Icon(icon, color: color, size: 20),
          const SizedBox(width: 10),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Text(
                label,
                style: TextStyle(
                  color: Colors.white.withValues(alpha: 0.5),
                  fontSize: 10,
                ),
              ),
              Text(
                value,
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _WaypointRow extends StatelessWidget {
  final int index;
  final TrailWaypoint waypoint;
  final bool isLast;

  const _WaypointRow({
    required this.index,
    required this.waypoint,
    required this.isLast,
  });

  @override
  Widget build(BuildContext context) {
    final isFirst = index == 0;
    final dotColor = isFirst
        ? const Color(0xFF7DD87A)
        : isLast
        ? const Color(0xFFFF6B6B)
        : Colors.white38;

    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 24,
            child: Column(
              children: [
                Container(
                  width: 12,
                  height: 12,
                  decoration: BoxDecoration(
                    color: dotColor,
                    shape: BoxShape.circle,
                  ),
                ),
                if (!isLast)
                  Expanded(
                    child: Container(
                      width: 1.5,
                      color: Colors.white12,
                      margin: const EdgeInsets.symmetric(vertical: 2),
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    waypoint.name,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    '${waypoint.position.lat.toStringAsFixed(4)}°N, '
                    '${waypoint.position.lng.toStringAsFixed(4)}°E',
                    style: TextStyle(
                      color: Colors.white.withValues(alpha: 0.4),
                      fontSize: 11,
                      fontFamily: 'monospace',
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ComputedRouteInfo extends StatelessWidget {
  final Trail trail;

  const _ComputedRouteInfo({required this.trail});

  @override
  Widget build(BuildContext context) {
    final computedLength = RouteService.totalRouteLengthMetres(
      trail.routePoints,
    );
    final lengthStr = computedLength >= 1000
        ? '${(computedLength / 1000).toStringAsFixed(2)} km'
        : '${computedLength.toStringAsFixed(0)} m';

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFF1A2E1C),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: const Color(0xFF7DD87A).withValues(alpha: 0.2),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(
                Icons.calculate_outlined,
                color: Color(0xFF7DD87A),
                size: 16,
              ),
              SizedBox(width: 8),
              Text(
                'Computed Route Statistics',
                style: TextStyle(
                  color: Colors.white,
                  fontWeight: FontWeight.w700,
                  fontSize: 13,
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          _InfoRow(label: 'Polyline length (Haversine)', value: lengthStr),
          _InfoRow(label: 'Waypoint count', value: '${trail.waypoints.length}'),

          if (trail.sourceFile != null)
            _InfoRow(label: 'Source GPX file', value: trail.sourceFile!),
          _InfoRow(
            label: 'GPS timestamps',
            value: trail.hasTimestamps ? 'Available' : 'Unavailable',
          ),
          _InfoRow(
            label: 'Navigation verification',
            value: trail.verifiedForNavigation ? 'Verified' : 'Not verified',
          ),

          _InfoRow(
            label: 'Off-route threshold',
            value:
                '${RouteService.defaultOffRouteThresholdMetres.toStringAsFixed(0)} m (default)',
          ),
          _InfoRow(label: 'Season', value: trail.bestSeason),
        ],
      ),
    );
  }
}

class _InfoRow extends StatelessWidget {
  final String label;
  final String value;

  const _InfoRow({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Expanded(
            child: Text(
              label,
              style: TextStyle(
                color: Colors.white.withValues(alpha: 0.5),
                fontSize: 12,
              ),
            ),
          ),
          Text(
            value,
            style: const TextStyle(
              color: Colors.white,
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}
