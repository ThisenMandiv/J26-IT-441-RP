import 'dart:math' as math;
import 'package:flutter/material.dart';
import '../services/route_service.dart';

/// Guidance card showing directional assistance and straight-line distance
/// to the nearest point on the planned trail.
class BackToTrailCard extends StatelessWidget {
  final OffRouteResult result;
  final double threshold;

  const BackToTrailCard({
    super.key,
    required this.result,
    required this.threshold,
  });

  @override
  Widget build(BuildContext context) {
    final isOff = result.isOffRoute(thresholdMetres: threshold);
    final accentColor = isOff ? const Color(0xFFFF6B6B) : const Color(0xFF7DD87A);
    final bearingDeg = result.returnBearingDegrees ?? 0.0;
    final bearingRad = bearingDeg * math.pi / 180.0;

    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFF1A2E1C),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: accentColor.withValues(alpha: isOff ? 0.6 : 0.25),
          width: 1.5,
        ),
      ),
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header Status Badge
          Row(
            children: [
              Icon(
                isOff ? Icons.warning_amber_rounded : Icons.check_circle_outline,
                color: accentColor,
                size: 20,
              ),
              const SizedBox(width: 8),
              Text(
                isOff ? 'OFF ROUTE — RETURN GUIDANCE' : 'ON ROUTE — PATH ALIGNED',
                style: TextStyle(
                  color: accentColor,
                  fontSize: 13,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 0.8,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            isOff
                ? 'Position deviates by more than ${threshold.toStringAsFixed(0)} m from trail.'
                : 'Current position is within the ${threshold.toStringAsFixed(0)} m corridor.',
            style: const TextStyle(color: Colors.white70, fontSize: 12),
          ),
          const SizedBox(height: 14),

          // Primary Metrics: Distance + Bearing Vector
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            decoration: BoxDecoration(
              color: Colors.black.withValues(alpha: 0.25),
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: Colors.white.withValues(alpha: 0.06)),
            ),
            child: Row(
              children: [
                // Directional Compass Arrow
                Container(
                  width: 44,
                  height: 44,
                  decoration: BoxDecoration(
                    color: accentColor.withValues(alpha: 0.12),
                    shape: BoxShape.circle,
                    border: Border.all(color: accentColor.withValues(alpha: 0.3)),
                  ),
                  child: Center(
                    child: Transform.rotate(
                      angle: bearingRad,
                      child: Icon(
                        Icons.navigation,
                        color: accentColor,
                        size: 22,
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 14),

                // Metrics readout
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        crossAxisAlignment: CrossAxisAlignment.baseline,
                        textBaseline: TextBaseline.alphabetic,
                        children: [
                          Text(
                            result.formattedDistance,
                            style: const TextStyle(
                              color: Colors.white,
                              fontSize: 22,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                          const SizedBox(width: 8),
                          Text(
                            'heading ${result.formattedBearing}',
                            style: TextStyle(
                              color: accentColor,
                              fontSize: 13,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 3),
                      Text(
                        'Straight-line return to Segment #${result.nearestSegmentIndex + 1}',
                        style: const TextStyle(
                          color: Colors.white54,
                          fontSize: 11,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),

          // Safety Limitation Notice
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
            decoration: BoxDecoration(
              color: const Color(0xFFFFD166).withValues(alpha: 0.08),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(
                color: const Color(0xFFFFD166).withValues(alpha: 0.25),
              ),
            ),
            child: const Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(
                  Icons.shield_outlined,
                  size: 14,
                  color: Color(0xFFFFD166),
                ),
                SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Safety Notice: Directional assistance to nearest recorded trail segment only. '
                    'Does NOT account for terrain, cliffs, rivers, thick bush, or private property.',
                    style: TextStyle(
                      color: Color(0xFFFFD166),
                      fontSize: 10.5,
                      height: 1.35,
                    ),
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
