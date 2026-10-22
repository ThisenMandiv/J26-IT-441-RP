import 'package:flutter/material.dart';
import '../models/completed_hike_model.dart';
import '../services/hike_history_service.dart';

/// Screen displaying the history of completed hikes saved locally.
class HikeHistoryScreen extends StatefulWidget {
  final HikeHistoryService? historyService;

  const HikeHistoryScreen({super.key, this.historyService});

  @override
  State<HikeHistoryScreen> createState() => _HikeHistoryScreenState();
}

class _HikeHistoryScreenState extends State<HikeHistoryScreen> {
  late final HikeHistoryService _service;
  bool _isLoading = true;
  String? _errorMessage;
  List<CompletedHike> _hikes = [];

  @override
  void initState() {
    super.initState();
    _service = widget.historyService ?? const HikeHistoryService();
    _loadHistory();
  }

  Future<void> _loadHistory() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final list = await _service.loadHikes();
      if (!mounted) return;
      setState(() {
        _hikes = list;
        _isLoading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _errorMessage = 'Could not load hike history.';
        _isLoading = false;
      });
    }
  }

  Future<void> _confirmClear() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF1A2E1C),
        title: const Text('Clear All History?', style: TextStyle(color: Colors.white)),
        content: const Text(
          'This will permanently remove all completed hike records from local storage.',
          style: TextStyle(color: Colors.white70),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel', style: TextStyle(color: Colors.white54)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFFFF6B6B),
              foregroundColor: Colors.white,
            ),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Clear'),
          ),
        ],
      ),
    );

    if (confirmed == true) {
      await _service.clearHistory();
      await _loadHistory();
    }
  }

  @override
  Widget build(BuildContext context) {
    const bgDark = Color(0xFF0F1B12);
    const accentGreen = Color(0xFF7DD87A);

    return Scaffold(
      backgroundColor: bgDark,
      appBar: AppBar(
        backgroundColor: bgDark,
        foregroundColor: Colors.white,
        title: Row(
          children: [
            const Text(
              'Hike History',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
            ),
            if (!_isLoading && _hikes.isNotEmpty) ...[
              const SizedBox(width: 8),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                  color: accentGreen.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: accentGreen.withValues(alpha: 0.3)),
                ),
                child: Text(
                  '${_hikes.length}',
                  style: const TextStyle(
                    color: accentGreen,
                    fontSize: 12,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
            ],
          ],
        ),
        actions: [
          if (_hikes.isNotEmpty)
            IconButton(
              icon: const Icon(Icons.delete_sweep_outlined, color: Colors.white70),
              tooltip: 'Clear History',
              onPressed: _confirmClear,
            ),
          IconButton(
            icon: const Icon(Icons.refresh, color: Colors.white70),
            tooltip: 'Refresh',
            onPressed: _loadHistory,
          ),
        ],
      ),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_isLoading) {
      return const Center(
        child: CircularProgressIndicator(color: Color(0xFF7DD87A)),
      );
    }

    if (_errorMessage != null) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.error_outline, color: Color(0xFFFF6B6B), size: 48),
            const SizedBox(height: 12),
            Text(
              _errorMessage!,
              style: const TextStyle(color: Colors.white70, fontSize: 15),
            ),
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: _loadHistory,
              style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFF7DD87A),
                foregroundColor: const Color(0xFF0F1B12),
              ),
              child: const Text('Retry'),
            ),
          ],
        ),
      );
    }

    if (_hikes.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Container(
                width: 80,
                height: 80,
                decoration: BoxDecoration(
                  color: const Color(0xFF1A2E1C),
                  shape: BoxShape.circle,
                  border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
                ),
                child: const Icon(
                  Icons.history_toggle_off,
                  color: Color(0xFF7DD87A),
                  size: 40,
                ),
              ),
              const SizedBox(height: 20),
              const Text(
                'No Completed Hikes Yet',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 18,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(height: 8),
              const Text(
                'Start a hike on the map and tap "Finish Hike" when done. '
                'Your recorded track, distance, and duration will be saved here offline.',
                textAlign: TextAlign.center,
                style: TextStyle(color: Colors.white60, fontSize: 13, height: 1.4),
              ),
            ],
          ),
        ),
      );
    }

    return ListView.separated(
      padding: const EdgeInsets.all(16),
      itemCount: _hikes.length,
      separatorBuilder: (context, index) => const SizedBox(height: 12),
      itemBuilder: (context, index) {
        final hike = _hikes[index];
        return _HikeCard(hike: hike);
      },
    );
  }
}

class _HikeCard extends StatelessWidget {
  final CompletedHike hike;

  const _HikeCard({required this.hike});

  @override
  Widget build(BuildContext context) {
    const accentGreen = Color(0xFF7DD87A);

    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFF1A2E1C),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
      ),
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header: Trail name + Date
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 36,
                height: 36,
                decoration: BoxDecoration(
                  color: accentGreen.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: const Icon(Icons.terrain, color: accentGreen, size: 20),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      hike.trailName ?? 'Completed Hike',
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      hike.formattedDate,
                      style: const TextStyle(color: Colors.white54, fontSize: 12),
                    ),
                  ],
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: Colors.black.withValues(alpha: 0.3),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.check_circle, color: accentGreen, size: 14),
                    const SizedBox(width: 4),
                    const Text(
                      'Saved',
                      style: TextStyle(
                        color: accentGreen,
                        fontSize: 11,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),

          // Metric Badges Row
          Row(
            children: [
              Expanded(
                child: _MetricBadge(
                  icon: Icons.straighten,
                  label: 'Distance',
                  value: hike.formattedDistance,
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: _MetricBadge(
                  icon: Icons.timer_outlined,
                  label: 'Duration',
                  value: hike.formattedDuration,
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: _MetricBadge(
                  icon: Icons.location_on_outlined,
                  label: 'GPS Points',
                  value: '${hike.recordedPoints.length}',
                ),
              ),
            ],
          ),

          if (hike.recordedPoints.isNotEmpty) ...[
            const SizedBox(height: 10),
            Text(
              'Initial point: ${hike.recordedPoints.first.lat.toStringAsFixed(4)}°N, '
              '${hike.recordedPoints.first.lng.toStringAsFixed(4)}°E',
              style: const TextStyle(color: Colors.white38, fontSize: 11),
            ),
          ],
        ],
      ),
    );
  }
}

class _MetricBadge extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;

  const _MetricBadge({
    required this.icon,
    required this.label,
    required this.value,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: Colors.black.withValues(alpha: 0.25),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: Colors.white.withValues(alpha: 0.05)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 13, color: const Color(0xFF7DD87A)),
              const SizedBox(width: 4),
              Text(
                label,
                style: const TextStyle(color: Colors.white54, fontSize: 10),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            value,
            style: const TextStyle(
              color: Colors.white,
              fontSize: 13,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }
}
