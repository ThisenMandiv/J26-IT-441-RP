import 'package:flutter/material.dart';

import '../models/trail_model.dart';
import '../services/api_service.dart';
import '../services/trail_data_service.dart';
import 'trail_detail_screen.dart';
import 'track_comparison_screen.dart';
import 'hike_history_screen.dart';

class HomeScreen extends StatefulWidget {
  final ApiService? apiService;

  const HomeScreen({super.key, this.apiService});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  late final ApiService _apiService;
  late final bool _ownsApiService;
  late Future<List<Trail>> _trailsFuture;
  BackendStatus _backendStatus = BackendStatus.checking;

  @override
  void initState() {
    super.initState();
    if (widget.apiService != null) {
      _apiService = widget.apiService!;
      _ownsApiService = false;
    } else {
      _apiService = ApiService();
      _ownsApiService = true;
    }
    _trailsFuture = TrailDataService.loadTrails(apiService: _apiService);
    _checkBackendConnectivity();
  }

  @override
  void dispose() {
    if (_ownsApiService) {
      _apiService.dispose();
    }
    super.dispose();
  }

  Future<void> _checkBackendConnectivity() async {
    if (!mounted) return;
    setState(() {
      _backendStatus = BackendStatus.checking;
    });

    try {
      final health = await _apiService.checkHealth();
      if (!mounted) return;
      if (health['status'] == 'healthy' || health['status'] == 'ok') {
        setState(() {
          _backendStatus = BackendStatus.connected;
        });
      } else {
        setState(() {
          _backendStatus = BackendStatus.offline;
        });
      }
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _backendStatus = BackendStatus.offline;
      });
    }
  }

  Future<void> _retryConnection() async {
    await _checkBackendConnectivity();
    if (mounted && _backendStatus == BackendStatus.connected) {
      setState(() {
        _trailsFuture = TrailDataService.loadTrails(apiService: _apiService);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0F1B12),
      body: CustomScrollView(
        slivers: [
          SliverAppBar(
            expandedHeight: 240,
            pinned: true,
            backgroundColor: const Color(0xFF0F1B12),
            actions: [
              IconButton(
                icon: const Icon(Icons.history, color: Color(0xFF7DD87A)),
                tooltip: 'Hike History',
                onPressed: () => Navigator.push(
                  context,
                  MaterialPageRoute(builder: (_) => const HikeHistoryScreen()),
                ),
              ),
              Padding(
                padding: const EdgeInsets.only(right: 16),
                child: Center(
                  child: _BackendStatusBadge(
                    status: _backendStatus,
                    onRetry: _retryConnection,
                  ),
                ),
              ),
            ],
            flexibleSpace: FlexibleSpaceBar(
              collapseMode: CollapseMode.parallax,
              background: Stack(
                fit: StackFit.expand,
                children: [
                  // Gradient hero background
                  Container(
                    decoration: const BoxDecoration(
                      gradient: LinearGradient(
                        begin: Alignment.topLeft,
                        end: Alignment.bottomRight,
                        colors: [
                          Color(0xFF1B3A20),
                          Color(0xFF2D5A27),
                          Color(0xFF1A4A2E),
                        ],
                      ),
                    ),
                  ),
                  // Decorative topographic lines (SVG-free — painted circles)
                  Positioned.fill(child: _TopoDecoration()),
                  // App branding
                  const Padding(
                    padding: EdgeInsets.fromLTRB(24, 80, 24, 24),
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.end,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Icon(
                              Icons.terrain,
                              color: Color(0xFF7DD87A),
                              size: 32,
                            ),
                            SizedBox(width: 10),
                            Text(
                              'Tapro Path',
                              style: TextStyle(
                                color: Colors.white,
                                fontSize: 32,
                                fontWeight: FontWeight.w800,
                                letterSpacing: -0.5,
                              ),
                            ),
                          ],
                        ),
                        SizedBox(height: 8),
                        Text(
                          'Offline Hiking Navigation · Sri Lankan Trails',
                          style: TextStyle(
                            color: Color(0xFF9ECBA0),
                            fontSize: 14,
                            fontWeight: FontWeight.w400,
                          ),
                        ),
                        SizedBox(height: 6),
                        _DataBadge(),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(20, 20, 20, 8),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'Available Trails',
                    style: TextStyle(
                      color: Colors.white,
                      fontSize: 20,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    'Tap a trail to view details and route preview',
                    style: TextStyle(
                      color: Colors.white.withValues(alpha: 0.5),
                      fontSize: 13,
                    ),
                  ),
                ],
              ),
            ),
          ),
          FutureBuilder<List<Trail>>(
            future: _trailsFuture,
            builder: (context, snapshot) {
              if (snapshot.connectionState == ConnectionState.waiting) {
                return const SliverFillRemaining(
                  child: Center(
                    child: CircularProgressIndicator(color: Color(0xFF7DD87A)),
                  ),
                );
              }
              if (snapshot.hasError || !snapshot.hasData) {
                return const SliverFillRemaining(
                  child: Center(
                    child: Text(
                      'Failed to load trail data.',
                      style: TextStyle(color: Colors.redAccent),
                    ),
                  ),
                );
              }
              final trails = snapshot.data!;
              if (trails.isEmpty) {
                return const SliverFillRemaining(
                  child: Center(
                    child: Text(
                      'No trails found in dataset.',
                      style: TextStyle(color: Colors.white54),
                    ),
                  ),
                );
              }

              return SliverList(
                delegate: SliverChildBuilderDelegate((context, index) {
                  if (index == 0) {
                    return Padding(
                      padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
                      child: Column(
                        children: [
                          SizedBox(
                            width: double.infinity,
                            child: OutlinedButton.icon(
                              onPressed: () => Navigator.push(
                                context,
                                MaterialPageRoute(
                                  builder: (_) => const HikeHistoryScreen(),
                                ),
                              ),
                              icon: const Icon(Icons.history, color: Color(0xFF7DD87A)),
                              label: const Text('View Completed Hike History'),
                              style: OutlinedButton.styleFrom(
                                foregroundColor: Colors.white,
                                side: BorderSide(
                                  color: const Color(0xFF7DD87A).withValues(alpha: 0.5),
                                ),
                                padding: const EdgeInsets.symmetric(vertical: 14),
                              ),
                            ),
                          ),
                          const SizedBox(height: 10),
                          SizedBox(
                            width: double.infinity,
                            child: ElevatedButton.icon(
                              onPressed: () => Navigator.push(
                                context,
                                MaterialPageRoute(
                                  builder: (_) =>
                                      TrackComparisonScreen(trails: trails),
                                ),
                              ),
                              icon: const Icon(Icons.compare_arrows),
                              label: const Text('Compare Recorded GPS Tracks'),
                              style: ElevatedButton.styleFrom(
                                backgroundColor: const Color(0xFF7DD87A),
                                foregroundColor: const Color(0xFF0F1B12),
                                padding: const EdgeInsets.symmetric(vertical: 14),
                              ),
                            ),
                          ),
                        ],
                      ),
                    );
                  }

                  final trail = trails[index - 1];

                  return _TrailCard(
                    trail: trail,
                    onTap: () => Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (_) => TrailDetailScreen(trail: trail),
                      ),
                    ),
                  );
                }, childCount: trails.length + 1),
              );
            },
          ),
          // Bottom padding
          const SliverToBoxAdapter(child: SizedBox(height: 32)),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Sub-widgets
// ---------------------------------------------------------------------------

/// Connectivity status with the FastAPI backend.
enum BackendStatus { checking, connected, offline }

/// Subtle connectivity badge displayed in the app bar.
class _BackendStatusBadge extends StatelessWidget {
  final BackendStatus status;
  final VoidCallback onRetry;

  const _BackendStatusBadge({
    required this.status,
    required this.onRetry,
  });

  @override
  Widget build(BuildContext context) {
    final Color color;
    final String label;
    final Widget leading;

    switch (status) {
      case BackendStatus.connected:
        color = const Color(0xFF7DD87A);
        label = 'Backend Connected';
        leading = Container(
          width: 8,
          height: 8,
          decoration: BoxDecoration(
            color: color,
            shape: BoxShape.circle,
            boxShadow: [
              BoxShadow(
                color: color.withValues(alpha: 0.5),
                blurRadius: 4,
                spreadRadius: 1,
              ),
            ],
          ),
        );
        break;
      case BackendStatus.offline:
        color = const Color(0xFFFFB74D);
        label = 'Offline Mode';
        leading = Container(
          width: 8,
          height: 8,
          decoration: BoxDecoration(
            color: color,
            shape: BoxShape.circle,
          ),
        );
        break;
      case BackendStatus.checking:
        color = Colors.white70;
        label = 'Checking...';
        leading = SizedBox(
          width: 9,
          height: 9,
          child: CircularProgressIndicator(
            strokeWidth: 1.5,
            color: color,
          ),
        );
        break;
    }

    return Tooltip(
      message: status == BackendStatus.connected
          ? 'FastAPI Backend online (http://127.0.0.1:8000)\nTap to refresh'
          : status == BackendStatus.offline
              ? 'Backend unavailable · Using offline datasets\nTap to retry connection'
              : 'Checking backend connectivity...',
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: onRetry,
          borderRadius: BorderRadius.circular(16),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(16),
              border: Border.all(
                color: color.withValues(alpha: 0.35),
                width: 1,
              ),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                leading,
                const SizedBox(width: 6),
                Text(
                  label,
                  style: TextStyle(
                    color: color,
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                if (status == BackendStatus.offline) ...[
                  const SizedBox(width: 4),
                  Icon(Icons.refresh, size: 12, color: color),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// Small badge communicating data provenance.
class _DataBadge extends StatelessWidget {
  const _DataBadge();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: const Color(0xFF7DD87A).withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(
          color: const Color(0xFF7DD87A).withValues(alpha: 0.4),
        ),
      ),
      child: const Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.offline_bolt, color: Color(0xFF7DD87A), size: 12),
          SizedBox(width: 5),
          Text(
            'Local dataset · No internet required',
            style: TextStyle(
              color: Color(0xFF7DD87A),
              fontSize: 11,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}

/// Decorative topographic-style concentric arcs painted on canvas.
class _TopoDecoration extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return CustomPaint(painter: _TopoPainter());
  }
}

class _TopoPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = Colors.white.withValues(alpha: 0.04)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.2;
    final center = Offset(size.width * 0.85, size.height * 0.3);
    for (double r = 40; r < 220; r += 30) {
      canvas.drawCircle(center, r, paint);
    }
    final paint2 = Paint()
      ..color = Colors.white.withValues(alpha: 0.025)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.0;
    final center2 = Offset(size.width * 0.1, size.height * 0.9);
    for (double r = 30; r < 150; r += 25) {
      canvas.drawCircle(center2, r, paint2);
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

/// Trail list card widget.
class _TrailCard extends StatelessWidget {
  final Trail trail;
  final VoidCallback onTap;

  const _TrailCard({required this.trail, required this.onTap});

  Color get _difficultyColor {
    switch (trail.difficulty.toLowerCase()) {
      case 'easy':
      case 'easy–moderate':
        return const Color(0xFF7DD87A);
      case 'moderate':
        return const Color(0xFFFFD166);
      case 'strenuous':
        return const Color(0xFFFF6B6B);
      default:
        return const Color(0xFF9ECBA0);
    }
  }

  IconData get _trailIcon {
    switch (trail.id) {
      case 'knuckles-main-trail':
        return Icons.filter_hdr;
      case 'adams-peak-pilgrims-path':
        return Icons.church;
      case 'horton-plains-loop':
        return Icons.landscape;
      default:
        return Icons.terrain;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(16),
          child: Container(
            decoration: BoxDecoration(
              color: const Color(0xFF1A2E1C),
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
            ),
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                // Icon container
                Container(
                  width: 52,
                  height: 52,
                  decoration: BoxDecoration(
                    color: _difficultyColor.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(
                      color: _difficultyColor.withValues(alpha: 0.3),
                    ),
                  ),
                  child: Icon(_trailIcon, color: _difficultyColor, size: 26),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        trail.name,
                        style: const TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.w700,
                          fontSize: 15,
                        ),
                      ),
                      const SizedBox(height: 3),
                      Text(
                        trail.region,
                        style: TextStyle(
                          color: Colors.white.withValues(alpha: 0.5),
                          fontSize: 12,
                        ),
                      ),
                      const SizedBox(height: 8),
                      Row(
                        children: [
                          _Chip(
                            label: trail.difficulty,
                            color: _difficultyColor,
                          ),
                          const SizedBox(width: 6),
                          if (trail.distanceKm != null)
                            _Chip(
                              label: '${trail.distanceKm} km',
                              color: const Color(0xFF6EC6E6),
                            ),
                          const SizedBox(width: 6),
                          _Chip(
                            label: '${trail.waypoints.length} pts',
                            color: Colors.white54,
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
                const Icon(
                  Icons.chevron_right,
                  color: Colors.white24,
                  size: 22,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _Chip extends StatelessWidget {
  final String label;
  final Color color;

  const _Chip({required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: color,
          fontSize: 11,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}
