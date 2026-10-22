
import 'package:flutter/material.dart';
import '../models/trail_model.dart';
import '../services/route_service.dart';

class TrackComparisonScreen extends StatefulWidget {
  final List<Trail> trails;

  const TrackComparisonScreen({super.key, required this.trails});

  @override
  State<TrackComparisonScreen> createState() =>
      _TrackComparisonScreenState();
}

class _TrackComparisonScreenState extends State<TrackComparisonScreen> {
  Trail? _trackA;
  Trail? _trackB;
  RouteComparisonResult? _result;

  late final List<Trail> _recordedTracks;

  @override
  void initState() {
    super.initState();

    _recordedTracks =
        widget.trails.where((trail) => trail.sourceFile != null).toList();

    if (_recordedTracks.isNotEmpty) {
      _trackA = _recordedTracks.first;

      final sameMountain = _recordedTracks.where(
        (trail) =>
            trail.id != _trackA!.id &&
            trail.region == _trackA!.region,
      );

      _trackB = sameMountain.isNotEmpty
          ? sameMountain.first
          : _recordedTracks.length > 1
              ? _recordedTracks[1]
              : null;
    }
  }

  List<Trail> get _availableTracks {
    if (_trackA == null) return _recordedTracks;

    return _recordedTracks
        .where((trail) =>
            trail.id != _trackA!.id &&
            trail.region == _trackA!.region)
        .toList();
  }

  void _compare() {
    if (_trackA == null || _trackB == null) return;

    try {
      final result = RouteService.compareRoutes(
        _trackA!.routePoints,
        _trackB!.routePoints,
        thresholdMetres: 50,
      );

      setState(() => _result = result);
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Could not compare tracks: $e')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0F1B12),
      appBar: AppBar(
        title: const Text('Compare GPS Tracks'),
        backgroundColor: const Color(0xFF0F1B12),
        foregroundColor: Colors.white,
      ),
      body: _recordedTracks.length < 2
          ? const Center(
              child: Padding(
                padding: EdgeInsets.all(24),
                child: Text(
                  'At least two recorded GPS tracks are needed.',
                  style: TextStyle(color: Colors.white70),
                  textAlign: TextAlign.center,
                ),
              ),
            )
          : ListView(
              padding: const EdgeInsets.all(20),
              children: [
                const Text(
                  'Route Consistency Experiment',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 21,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 8),
                const Text(
                  'Compare two recordings from the same mountain to '
                  'measure how closely their GPS paths follow each other.',
                  style: TextStyle(
                    color: Colors.white70,
                    height: 1.5,
                  ),
                ),
                const SizedBox(height: 24),
                _trackDropdown(
                  label: 'First recording',
                  selected: _trackA,
                  options: _recordedTracks,
                  onChanged: (trail) {
                    setState(() {
                      _trackA = trail;
                      final available = _availableTracks;
                      if (_trackB == null ||
                          !available.any((t) => t.id == _trackB!.id)) {
                        _trackB =
                            available.isNotEmpty ? available.first : null;
                      }
                      _result = null;
                    });
                  },
                ),
                const SizedBox(height: 16),
                _trackDropdown(
                  label: 'Second recording',
                  selected: _trackB,
                  options: _availableTracks,
                  onChanged: (trail) {
                    setState(() {
                      _trackB = trail;
                      _result = null;
                    });
                  },
                ),
                const SizedBox(height: 20),
                ElevatedButton.icon(
                  onPressed: _trackA != null && _trackB != null
                      ? _compare
                      : null,
                  icon: const Icon(Icons.compare_arrows),
                  label: const Text('Compare Tracks'),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF7DD87A),
                    foregroundColor: const Color(0xFF0F1B12),
                    padding: const EdgeInsets.symmetric(vertical: 15),
                  ),
                ),
                if (_result != null) ...[
                  const SizedBox(height: 28),
                  const Text(
                    'Comparison Results',
                    style: TextStyle(
                      color: Colors.white,
                      fontSize: 20,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  const SizedBox(height: 12),
                  _resultCard(
                    'Average deviation',
                    '${_result!.averageDeviationMetres.toStringAsFixed(1)} m',
                    'Average distance from each recorded point to the other track.',
                  ),
                  _resultCard(
                    'Maximum deviation',
                    '${_result!.maximumDeviationMetres.toStringAsFixed(1)} m',
                    'Largest point-to-track distance observed.',
                  ),
                  _resultCard(
                    'Points within 50 m',
                    '${_result!.percentWithinThreshold.toStringAsFixed(1)}%',
                    'Percentage of points across both tracks within 50 m of the other track.',
                  ),
                  _resultCard(
                    'Points compared',
                    '${_result!.pointsCompared}',
                    'Total GPS points evaluated across both recordings.',
                  ),
                  const SizedBox(height: 12),
                  const Text(
                    'Research note: these measurements indicate spatial '
                    'similarity only. GPS errors, recording coverage, and '
                    'sampling frequency can affect the results. They do not '
                    'validate a trail for safe navigation.',
                    style: TextStyle(
                      color: Colors.amber,
                      fontSize: 12,
                      height: 1.5,
                    ),
                  ),
                ],
              ],
            ),
    );
  }

  Widget _trackDropdown({
    required String label,
    required Trail? selected,
    required List<Trail> options,
    required ValueChanged<Trail?> onChanged,
  }) {
    final validSelection = selected != null &&
            options.any((trail) => trail.id == selected.id)
        ? selected
        : null;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: const TextStyle(
            color: Color(0xFF9ECBA0),
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: 8),
        DropdownButtonFormField<Trail>(
          value: validSelection,
          isExpanded: true,
          dropdownColor: const Color(0xFF1A2E1C),
          style: const TextStyle(color: Colors.white),
          decoration: InputDecoration(
            filled: true,
            fillColor: const Color(0xFF1A2E1C),
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(12),
            ),
          ),
          hint: const Text(
            'Select a recording',
            style: TextStyle(color: Colors.white54),
          ),
          items: options.map((trail) {
            return DropdownMenuItem<Trail>(
              value: trail,
              child: Text(
                '${trail.name} (${trail.waypoints.length} points)',
                overflow: TextOverflow.ellipsis,
              ),
            );
          }).toList(),
          onChanged: onChanged,
        ),
      ],
    );
  }

  Widget _resultCard(String title, String value, String description) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF1A2E1C),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: const TextStyle(color: Colors.white70)),
          const SizedBox(height: 6),
          Text(
            value,
            style: const TextStyle(
              color: Color(0xFF7DD87A),
              fontSize: 24,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            description,
            style: const TextStyle(
              color: Colors.white54,
              fontSize: 12,
              height: 1.4,
            ),
          ),
        ],
      ),
    );
  }
}
