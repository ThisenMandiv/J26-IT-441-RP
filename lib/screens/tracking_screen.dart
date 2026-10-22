import 'package:flutter/material.dart';
import 'dart:async';
import '../models/trail_model.dart';
import '../models/completed_hike_model.dart';
import '../services/route_service.dart';
import '../services/hike_history_service.dart';
import '../widgets/back_to_trail_card.dart';
import 'hike_history_screen.dart';

/// Tracking Screen — simulation mode + start/pause/stop controls.
///
/// ⚠ IMPORTANT: This screen uses SIMULATED positions only.
/// Real GPS tracking requires platform location permissions and
/// a device GPS implementation (e.g., geolocator package) that
/// has been tested on target hardware. This prototype does NOT
/// claim live tracking capability.
class TrackingScreen extends StatefulWidget {
  final Trail trail;

  const TrackingScreen({super.key, required this.trail});

  @override
  State<TrackingScreen> createState() => _TrackingScreenState();
}

enum TrackingState { idle, running, paused }

/// A simulated GPS position with a label.
class _SimPosition {
  final String label;
  final LatLng position;
  final bool isOnRoute;

  const _SimPosition({
    required this.label,
    required this.position,
    required this.isOnRoute,
  });
}

class _TrackingScreenState extends State<TrackingScreen>
    with TickerProviderStateMixin {
  TrackingState _state = TrackingState.idle;
  Timer? _timer;
  int _elapsedSeconds = 0;
  int _simPositionIndex = 0;
  DateTime? _simStartTime;
  final List<LatLng> _visitedPositions = [];
  late List<_SimPosition> _simPositions;
  OffRouteResult? _currentOffRouteResult;
  late AnimationController _pulseController;

  // Configurable off-route threshold (metres)
  double _thresholdMetres = RouteService.defaultOffRouteThresholdMetres;

  @override
  void initState() {
    super.initState();
    _buildSimPositions();
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 1),
    )..repeat(reverse: true);
  }

  /// Builds simulated positions: some on-route, some off-route.
  void _buildSimPositions() {
    final route = widget.trail.routePoints;
    if (route.isEmpty) {
      _simPositions = [];
      return;
    }

    // On-route positions: interpolate on actual waypoints
    final List<_SimPosition> positions = [];

    for (int i = 0; i < route.length; i++) {
      positions.add(_SimPosition(
        label: widget.trail.waypoints[i].name,
        position: route[i],
        isOnRoute: true,
      ));
    }

    // Off-route positions: offset 0.001 degrees (~111 m) from mid-route
    if (route.length >= 2) {
      final mid = route[route.length ~/ 2];
      positions.add(_SimPosition(
        label: '[SIM] Off-route — 111 m east',
        position: LatLng(lat: mid.lat, lng: mid.lng + 0.001),
        isOnRoute: false,
      ));
      positions.add(_SimPosition(
        label: '[SIM] Off-route — 222 m north',
        position: LatLng(lat: mid.lat + 0.002, lng: mid.lng),
        isOnRoute: false,
      ));
      positions.add(_SimPosition(
        label: '[SIM] Off-route — 500 m away',
        position: LatLng(lat: mid.lat + 0.003, lng: mid.lng + 0.003),
        isOnRoute: false,
      ));
    }

    _simPositions = positions;
    _evaluateCurrentPosition();
  }

  void _evaluateCurrentPosition() {
    if (_simPositions.isEmpty) return;
    final pos = _simPositions[_simPositionIndex % _simPositions.length];
    final result = RouteService.distanceToNearestRouteSegment(
      pos.position,
      widget.trail.routePoints,
    );
    setState(() => _currentOffRouteResult = result);
  }

  void _start() {
    _simStartTime ??= DateTime.now();
    if (_visitedPositions.isEmpty && _simPositions.isNotEmpty) {
      _visitedPositions.add(_simPositions[_simPositionIndex].position);
    }
    setState(() => _state = TrackingState.running);
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      setState(() {
        _elapsedSeconds++;
        // Auto-advance simulated position every 5 seconds
        if (_elapsedSeconds % 5 == 0) {
          _simPositionIndex =
              (_simPositionIndex + 1) % _simPositions.length;
          final pos = _simPositions[_simPositionIndex].position;
          if (_visitedPositions.isEmpty || _visitedPositions.last != pos) {
            _visitedPositions.add(pos);
          }
          _evaluateCurrentPosition();
        }
      });
    });
  }

  void _pause() {
    _timer?.cancel();
    setState(() => _state = TrackingState.paused);
  }

  void _resume() => _start();

  Future<void> _stop() async {
    _timer?.cancel();
    if (_elapsedSeconds == 0) {
      _resetTracking();
      return;
    }

    setState(() => _state = TrackingState.paused);

    final shouldSave = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF1A2E1C),
        title: const Text('Finish Simulated Hike?', style: TextStyle(color: Colors.white)),
        content: Text(
          'Duration: $_elapsedFormatted\n'
          'Would you like to save this completed hike to local history, or reset without saving?',
          style: const TextStyle(color: Colors.white70),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Discard / Reset', style: TextStyle(color: Colors.white54)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFF7DD87A),
              foregroundColor: const Color(0xFF0F1B12),
            ),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Save to History'),
          ),
        ],
      ),
    );

    if (shouldSave == true) {
      double totalDistMetres = 0;
      for (int i = 1; i < _visitedPositions.length; i++) {
        totalDistMetres += RouteService.haversineDistanceMetres(
          _visitedPositions[i - 1],
          _visitedPositions[i],
        );
      }
      final finishTime = DateTime.now();
      final completed = CompletedHike(
        id: 'hike_${finishTime.millisecondsSinceEpoch}',
        trailId: widget.trail.id,
        trailName: widget.trail.name,
        startTime: _simStartTime,
        finishTime: finishTime,
        duration: Duration(seconds: _elapsedSeconds),
        recordedPoints: List.from(_visitedPositions),
        distanceKm: totalDistMetres / 1000,
      );
      await HikeHistoryService.save(completed);

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            backgroundColor: const Color(0xFF1A2E1C),
            content: const Text('Simulated hike saved to local history!'),
            action: SnackBarAction(
              textColor: const Color(0xFF7DD87A),
              label: 'View',
              onPressed: () => Navigator.push(
                context,
                MaterialPageRoute(builder: (_) => const HikeHistoryScreen()),
              ),
            ),
          ),
        );
      }
    }

    _resetTracking();
  }

  void _resetTracking() {
    _timer?.cancel();
    setState(() {
      _state = TrackingState.idle;
      _elapsedSeconds = 0;
      _simPositionIndex = 0;
      _simStartTime = null;
      _visitedPositions.clear();
      _evaluateCurrentPosition();
    });
  }

  void _jumpToPosition(int index) {
    setState(() => _simPositionIndex = index);
    _evaluateCurrentPosition();
  }

  @override
  void dispose() {
    _timer?.cancel();
    _pulseController.dispose();
    super.dispose();
  }

  String get _elapsedFormatted {
    final h = _elapsedSeconds ~/ 3600;
    final m = (_elapsedSeconds % 3600) ~/ 60;
    final s = _elapsedSeconds % 60;
    return '${h.toString().padLeft(2, '0')}:${m.toString().padLeft(2, '0')}:${s.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    final offRoute = _currentOffRouteResult != null &&
        _currentOffRouteResult!.isOffRoute(thresholdMetres: _thresholdMetres);

    return Scaffold(
      backgroundColor: const Color(0xFF0F1B12),
      appBar: AppBar(
        backgroundColor: const Color(0xFF0F1B12),
        foregroundColor: Colors.white,
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Tracking',
                style: TextStyle(
                    color: Colors.white,
                    fontSize: 16,
                    fontWeight: FontWeight.w700)),
            Text(
              widget.trail.name,
              style: TextStyle(
                  color: Colors.white.withOpacity(0.5), fontSize: 11),
              overflow: TextOverflow.ellipsis,
            ),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.history, color: Color(0xFF7DD87A)),
            tooltip: 'Hike History',
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute(builder: (_) => const HikeHistoryScreen()),
            ),
          ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Prototype warning
            _ProtoWarningBanner(),
            const SizedBox(height: 16),

            // Status card
            _StatusCard(
              state: _state,
              elapsed: _elapsedFormatted,
              offRoute: offRoute,
              offRouteResult: _currentOffRouteResult,
              threshold: _thresholdMetres,
              pulseController: _pulseController,
            ),
            const SizedBox(height: 16),

            // Back-to-Trail directional guidance card
            if (_currentOffRouteResult != null) ...[
              BackToTrailCard(
                result: _currentOffRouteResult!,
                threshold: _thresholdMetres,
              ),
              const SizedBox(height: 16),
            ],

            // Controls
            _ControlBar(
              state: _state,
              onStart: _start,
              onPause: _pause,
              onResume: _resume,
              onStop: _stop,
            ),
            const SizedBox(height: 20),

            // Threshold slider
            _ThresholdControl(
              value: _thresholdMetres,
              onChanged: (v) {
                setState(() => _thresholdMetres = v);
                _evaluateCurrentPosition();
              },
            ),
            const SizedBox(height: 20),

            // Simulated position picker
            if (_simPositions.isNotEmpty) ...[
              const _SectionTitle('Simulation Mode — Test Positions'),
              const SizedBox(height: 4),
              Text(
                'Select a position below to test on-route and off-route detection. '
                'All positions are SIMULATED — no real GPS is used.',
                style: TextStyle(
                    color: Colors.white.withOpacity(0.45), fontSize: 12),
              ),
              const SizedBox(height: 12),
              ..._simPositions.asMap().entries.map(
                    (entry) => _SimPositionTile(
                      index: entry.key,
                      sim: entry.value,
                      isSelected:
                          entry.key == _simPositionIndex % _simPositions.length,
                      routePoints: widget.trail.routePoints,
                      threshold: _thresholdMetres,
                      onTap: () => _jumpToPosition(entry.key),
                    ),
                  ),
            ],
            const SizedBox(height: 32),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Sub-widgets
// ---------------------------------------------------------------------------

class _ProtoWarningBanner extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFF6EC6E6).withOpacity(0.08),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: const Color(0xFF6EC6E6).withOpacity(0.3)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.info_outline, color: Color(0xFF6EC6E6), size: 16),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              'PROTOTYPE — Simulation Mode Only\n'
              'Live GPS tracking is not implemented in this build. '
              'Real location permissions and a device GPS library must be '
              'integrated and field-tested before claiming real-time navigation.',
              style: TextStyle(
                color: const Color(0xFF6EC6E6).withOpacity(0.85),
                fontSize: 11.5,
                height: 1.5,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _StatusCard extends StatelessWidget {
  final TrackingState state;
  final String elapsed;
  final bool offRoute;
  final OffRouteResult? offRouteResult;
  final double threshold;
  final AnimationController pulseController;

  const _StatusCard({
    required this.state,
    required this.elapsed,
    required this.offRoute,
    required this.offRouteResult,
    required this.threshold,
    required this.pulseController,
  });

  @override
  Widget build(BuildContext context) {
    final statusColor = state == TrackingState.idle
        ? Colors.white38
        : state == TrackingState.paused
            ? const Color(0xFFFFD166)
            : const Color(0xFF7DD87A);

    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: const Color(0xFF1A2E1C),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: offRoute
              ? const Color(0xFFFF6B6B).withOpacity(0.5)
              : statusColor.withOpacity(0.2),
          width: 1.5,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              AnimatedBuilder(
                animation: pulseController,
                builder: (_, __) {
                  final opacity = state == TrackingState.running
                      ? 0.4 + pulseController.value * 0.6
                      : 1.0;
                  return Opacity(
                    opacity: opacity,
                    child: Container(
                      width: 10,
                      height: 10,
                      decoration: BoxDecoration(
                        color: statusColor,
                        shape: BoxShape.circle,
                      ),
                    ),
                  );
                },
              ),
              const SizedBox(width: 8),
              Text(
                state == TrackingState.idle
                    ? 'IDLE'
                    : state == TrackingState.paused
                        ? 'PAUSED'
                        : 'SIMULATING',
                style: TextStyle(
                  color: statusColor,
                  fontSize: 13,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 1.2,
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          Center(
            child: Text(
              elapsed,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 42,
                fontWeight: FontWeight.w200,
                fontFamily: 'monospace',
                letterSpacing: 4,
              ),
            ),
          ),
          const SizedBox(height: 16),
          if (offRouteResult != null) ...[
            const Divider(color: Colors.white10),
            const SizedBox(height: 12),
            Row(
              children: [
                Icon(
                  offRoute ? Icons.warning_amber_rounded : Icons.check_circle,
                  color: offRoute
                      ? const Color(0xFFFF6B6B)
                      : const Color(0xFF7DD87A),
                  size: 20,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        offRoute ? 'OFF ROUTE' : 'ON ROUTE',
                        style: TextStyle(
                          color: offRoute
                              ? const Color(0xFFFF6B6B)
                              : const Color(0xFF7DD87A),
                          fontWeight: FontWeight.w700,
                          fontSize: 13,
                          letterSpacing: 0.8,
                        ),
                      ),
                      Text(
                        'Distance to route: ${offRouteResult!.formattedDistance} '
                        '(threshold: ${threshold.toStringAsFixed(0)} m)',
                        style: TextStyle(
                          color: Colors.white.withOpacity(0.5),
                          fontSize: 11,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

class _ControlBar extends StatelessWidget {
  final TrackingState state;
  final VoidCallback onStart;
  final VoidCallback onPause;
  final VoidCallback onResume;
  final VoidCallback onStop;

  const _ControlBar({
    required this.state,
    required this.onStart,
    required this.onPause,
    required this.onResume,
    required this.onStop,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        if (state == TrackingState.idle) ...[
          Expanded(
            child: _CtrlButton(
              label: 'Start Simulation',
              icon: Icons.play_arrow,
              color: const Color(0xFF7DD87A),
              onTap: onStart,
            ),
          ),
        ] else if (state == TrackingState.running) ...[
          Expanded(
            child: _CtrlButton(
              label: 'Pause',
              icon: Icons.pause,
              color: const Color(0xFFFFD166),
              onTap: onPause,
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: _CtrlButton(
              label: 'Stop',
              icon: Icons.stop,
              color: const Color(0xFFFF6B6B),
              onTap: onStop,
            ),
          ),
        ] else ...[
          Expanded(
            child: _CtrlButton(
              label: 'Resume',
              icon: Icons.play_arrow,
              color: const Color(0xFF7DD87A),
              onTap: onResume,
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: _CtrlButton(
              label: 'Stop',
              icon: Icons.stop,
              color: const Color(0xFFFF6B6B),
              onTap: onStop,
            ),
          ),
        ],
      ],
    );
  }
}

class _CtrlButton extends StatelessWidget {
  final String label;
  final IconData icon;
  final Color color;
  final VoidCallback onTap;

  const _CtrlButton({
    required this.label,
    required this.icon,
    required this.color,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: color.withOpacity(0.12),
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 14),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: color.withOpacity(0.4)),
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(icon, color: color, size: 20),
              const SizedBox(width: 8),
              Text(
                label,
                style: TextStyle(
                  color: color,
                  fontWeight: FontWeight.w700,
                  fontSize: 14,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ThresholdControl extends StatelessWidget {
  final double value;
  final ValueChanged<double> onChanged;

  const _ThresholdControl({required this.value, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFF1A2E1C),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white.withOpacity(0.07)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Text(
                'Off-Route Threshold',
                style: TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.w600,
                    fontSize: 13),
              ),
              Text(
                '${value.toStringAsFixed(0)} m',
                style: const TextStyle(
                  color: Color(0xFF7DD87A),
                  fontWeight: FontWeight.w700,
                  fontSize: 13,
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            'Alert triggers when distance to nearest route segment exceeds this value.',
            style:
                TextStyle(color: Colors.white.withOpacity(0.4), fontSize: 11),
          ),
          SliderTheme(
            data: SliderTheme.of(context).copyWith(
              activeTrackColor: const Color(0xFF7DD87A),
              inactiveTrackColor: Colors.white12,
              thumbColor: const Color(0xFF7DD87A),
              overlayColor: const Color(0xFF7DD87A).withOpacity(0.15),
            ),
            child: Slider(
              min: 10,
              max: 500,
              divisions: 49,
              value: value,
              onChanged: onChanged,
            ),
          ),
        ],
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  final String text;

  const _SectionTitle(this.text);

  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      style: const TextStyle(
        color: Colors.white,
        fontSize: 15,
        fontWeight: FontWeight.w700,
      ),
    );
  }
}

class _SimPositionTile extends StatelessWidget {
  final int index;
  final _SimPosition sim;
  final bool isSelected;
  final List<LatLng> routePoints;
  final double threshold;
  final VoidCallback onTap;

  const _SimPositionTile({
    required this.index,
    required this.sim,
    required this.isSelected,
    required this.routePoints,
    required this.threshold,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final result =
        RouteService.distanceToNearestRouteSegment(sim.position, routePoints);
    final offRoute = result.isOffRoute(thresholdMetres: threshold);
    final statusColor =
        offRoute ? const Color(0xFFFF6B6B) : const Color(0xFF7DD87A);

    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(10),
          child: Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: isSelected
                  ? statusColor.withOpacity(0.1)
                  : const Color(0xFF1A2E1C),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(
                color: isSelected
                    ? statusColor.withOpacity(0.5)
                    : Colors.white.withOpacity(0.07),
                width: isSelected ? 1.5 : 1,
              ),
            ),
            child: Row(
              children: [
                Icon(
                  offRoute ? Icons.location_off : Icons.my_location,
                  color: statusColor,
                  size: 18,
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        sim.label,
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        '${sim.position.lat.toStringAsFixed(4)}°N, '
                        '${sim.position.lng.toStringAsFixed(4)}°E  ·  '
                        '${result.formattedDistance} from route',
                        style: TextStyle(
                          color: Colors.white.withOpacity(0.4),
                          fontSize: 11,
                        ),
                      ),
                    ],
                  ),
                ),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: statusColor.withOpacity(0.12),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    offRoute ? 'OFF' : 'ON',
                    style: TextStyle(
                      color: statusColor,
                      fontSize: 10,
                      fontWeight: FontWeight.w800,
                      letterSpacing: 0.5,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
