import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart' as ll;

import 'dart:async';

import 'package:geolocator/geolocator.dart';

import '../models/trail_model.dart';
import '../models/completed_hike_model.dart';
import '../services/route_service.dart';
import '../services/hike_history_service.dart';
import '../widgets/back_to_trail_card.dart';
import 'hike_history_screen.dart';

class NavigationMapScreen extends StatefulWidget {
  final Trail trail;

  const NavigationMapScreen({super.key, required this.trail});

  @override
  State<NavigationMapScreen> createState() => _NavigationMapScreenState();
}

class _NavigationMapScreenState extends State<NavigationMapScreen> {
  final MapController _mapController = MapController();

  static const Color _green = Color(0xFF7DD87A);
  Position? _currentGpsPosition;
  StreamSubscription<Position>? _positionSubscription;
  String _locationStatus = 'Waiting for location permission...';
  double? _distanceFromRoute;
  OffRouteResult? _lastRouteResult;
  bool _isOffRoute = false;
  bool _isTracking = false;
  bool _isPaused = false;
  bool _hasFinishedHike = false;
  DateTime? _hikeStartTime;

  final List<ll.LatLng> _recordedPoints = [];
  final Stopwatch _hikeStopwatch = Stopwatch();
  Timer? _elapsedTimer;
  @override
  void initState() {
    super.initState();
    _startLocationUpdates();
  }

  Future<void> _startLocationUpdates() async {
    try {
      final serviceEnabled = await Geolocator.isLocationServiceEnabled();

      if (!serviceEnabled) {
        if (mounted) {
          setState(() {
            _locationStatus = 'Please enable location services.';
          });
        }
        return;
      }

      LocationPermission permission = await Geolocator.checkPermission();

      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }

      if (permission == LocationPermission.denied ||
          permission == LocationPermission.deniedForever) {
        if (mounted) {
          setState(() {
            _locationStatus = 'Location permission was not granted.';
          });
        }
        return;
      }

      const settings = LocationSettings(
        accuracy: LocationAccuracy.high,
        distanceFilter: 5,
      );

      _positionSubscription =
          Geolocator.getPositionStream(locationSettings: settings).listen(
            (position) {
              if (!mounted) return;

              final currentPoint = LatLng(
                lat: position.latitude,
                lng: position.longitude,
              );

              final routePoints = widget.trail.routePoints;

              final result = RouteService.distanceToNearestRouteSegment(
                currentPoint,
                routePoints,
              );

              setState(() {
                _currentGpsPosition = position;
                _distanceFromRoute = result.distanceMetres;
                _lastRouteResult = result;
                _isOffRoute = result.isOffRoute();
                _locationStatus = _isOffRoute
                    ? 'OFF ROUTE — Please check your position!'
                    : 'On route — monitoring your location';
                if (_isTracking && !_isPaused) {
                  final newPoint = ll.LatLng(
                    position.latitude,
                    position.longitude,
                  );

                  if (_recordedPoints.isEmpty ||
                      Geolocator.distanceBetween(
                            _recordedPoints.last.latitude,
                            _recordedPoints.last.longitude,
                            newPoint.latitude,
                            newPoint.longitude,
                          ) >=
                          3) {
                    _recordedPoints.add(newPoint);
                  }
                }
              });
            },
            onError: (error) {
              if (!mounted) return;
              setState(() {
                _locationStatus = 'Unable to receive GPS updates.';
              });
            },
          );
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _locationStatus = 'Could not access your location.';
      });
    }
  }

  void _startHike() {
    setState(() {
      if (_hasFinishedHike) {
        _recordedPoints.clear();
        _hikeStopwatch.reset();
        _hasFinishedHike = false;
      }

      _hikeStartTime = DateTime.now();
      _isTracking = true;
      _isPaused = false;

      // Record the starting position if GPS is available.
      if (_recordedPoints.isEmpty && _currentGpsPosition != null) {
        _recordedPoints.add(
          ll.LatLng(
            _currentGpsPosition!.latitude,
            _currentGpsPosition!.longitude,
          ),
        );
      }
    });

    _hikeStopwatch.start();

    _elapsedTimer?.cancel();
    _elapsedTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted && _isTracking && !_isPaused) {
        setState(() {});
      }
    });
  }

  void _togglePause() {
    setState(() {
      if (_isPaused) {
        _isPaused = false;
        _hikeStopwatch.start();
      } else {
        _isPaused = true;
        _hikeStopwatch.stop();
      }
    });
  }

  double get _recordedDistanceMetres {
    double total = 0;

    for (int i = 1; i < _recordedPoints.length; i++) {
      total += Geolocator.distanceBetween(
        _recordedPoints[i - 1].latitude,
        _recordedPoints[i - 1].longitude,
        _recordedPoints[i].latitude,
        _recordedPoints[i].longitude,
      );
    }

    return total;
  }

  String _formatDuration(Duration duration) {
    final hours = duration.inHours.toString().padLeft(2, '0');
    final minutes = (duration.inMinutes % 60).toString().padLeft(2, '0');
    final seconds = (duration.inSeconds % 60).toString().padLeft(2, '0');

    return '$hours:$minutes:$seconds';
  }

  Future<void> _finishHike() async {
    _hikeStopwatch.stop();
    _elapsedTimer?.cancel();

    final finishTime = DateTime.now();
    final distanceKm = _recordedDistanceMetres / 1000;
    final duration = _formatDuration(_hikeStopwatch.elapsed);
    final pointCount = _recordedPoints.length;

    setState(() {
      _isTracking = false;
      _isPaused = false;
      _hasFinishedHike = true;
    });

    // Save completed hike locally to persistent history
    final completedRecord = CompletedHike(
      id: 'hike_${finishTime.millisecondsSinceEpoch}',
      trailId: widget.trail.id,
      trailName: widget.trail.name,
      startTime: _hikeStartTime,
      finishTime: finishTime,
      duration: _hikeStopwatch.elapsed,
      recordedPoints: _recordedPoints
          .map((p) => LatLng(lat: p.latitude, lng: p.longitude))
          .toList(),
      distanceKm: distanceKm,
    );
    await HikeHistoryService.save(completedRecord);

    if (!mounted) return;

    await showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: const Color(0xFF1A2E1C),
        title: const Text('Hike completed!', style: TextStyle(color: Colors.white)),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Distance recorded: ${distanceKm.toStringAsFixed(2)} km',
                style: const TextStyle(color: Colors.white70)),
            const SizedBox(height: 8),
            Text('Duration: $duration',
                style: const TextStyle(color: Colors.white70)),
            const SizedBox(height: 8),
            Text('GPS points: $pointCount',
                style: const TextStyle(color: Colors.white70)),
            const SizedBox(height: 12),
            const Row(
              children: [
                Icon(Icons.check_circle, color: _green, size: 16),
                SizedBox(width: 6),
                Text(
                  'Saved to local Hike History',
                  style: TextStyle(
                    color: _green,
                    fontSize: 12,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ],
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('Back to map', style: TextStyle(color: Colors.white54)),
          ),
          ElevatedButton.icon(
            style: ElevatedButton.styleFrom(
              backgroundColor: _green,
              foregroundColor: const Color(0xFF0F1B12),
            ),
            onPressed: () {
              Navigator.pop(dialogContext);
              Navigator.push(
                context,
                MaterialPageRoute(builder: (_) => const HikeHistoryScreen()),
              );
            },
            icon: const Icon(Icons.history, size: 18),
            label: const Text('View History'),
          ),
        ],
      ),
    );
  }

  @override
void dispose() {
  _elapsedTimer?.cancel();
  _positionSubscription?.cancel();
  _mapController.dispose();
  super.dispose();
}

  @override
  Widget build(BuildContext context) {
    final points = widget.trail.routePoints
        .map((point) => ll.LatLng(point.lat, point.lng))
        .toList();

    final center = points.isNotEmpty
        ? points[points.length ~/ 2]
        : const ll.LatLng(7.8731, 80.7718);

    return Scaffold(
      backgroundColor: const Color(0xFF0F1B12),
      appBar: AppBar(
        title: Text(widget.trail.name),
        backgroundColor: const Color(0xFF0F1B12),
        foregroundColor: Colors.white,
        actions: [
          IconButton(
            icon: const Icon(Icons.history, color: _green),
            tooltip: 'Hike History',
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute(builder: (_) => const HikeHistoryScreen()),
            ),
          ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: FlutterMap(
              mapController: _mapController,
              options: MapOptions(
                initialCenter: center,
                initialZoom: 15,
                minZoom: 5,
                maxZoom: 18,
              ),
              children: [
                TileLayer(
                  urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                  userAgentPackageName: 'com.tapro.path',
                ),
                if (points.length >= 2)
                  PolylineLayer(
                    polylines: [
                      Polyline(points: points, strokeWidth: 5, color: _green),
                    ],
                  ),
                if (_recordedPoints.length >= 2)
                  PolylineLayer(
                    polylines: [
                      Polyline(
                        points: List<ll.LatLng>.unmodifiable(_recordedPoints),
                        strokeWidth: 5,
                        color: Colors.orangeAccent,
                      ),
                    ],
                  ),
                if (points.isNotEmpty)
                  MarkerLayer(
                    markers: [
                      Marker(
                        point: points.first,
                        width: 44,
                        height: 44,
                        child: const Icon(
                          Icons.trip_origin,
                          color: Colors.green,
                          size: 32,
                        ),
                      ),
                      Marker(
                        point: points.last,
                        width: 44,
                        height: 44,
                        child: const Icon(
                          Icons.flag,
                          color: Colors.redAccent,
                          size: 32,
                        ),
                      ),
                    ],
                  ),
                if (_isOffRoute &&
                    _lastRouteResult?.nearestPoint != null &&
                    _currentGpsPosition != null)
                  PolylineLayer(
                    polylines: [
                      Polyline(
                        points: [
                          ll.LatLng(
                            _currentGpsPosition!.latitude,
                            _currentGpsPosition!.longitude,
                          ),
                          ll.LatLng(
                            _lastRouteResult!.nearestPoint!.lat,
                            _lastRouteResult!.nearestPoint!.lng,
                          ),
                        ],
                        strokeWidth: 3,
                        color: const Color(0xFFFF6B6B),
                      ),
                    ],
                  ),
                if (_isOffRoute && _lastRouteResult?.nearestPoint != null)
                  MarkerLayer(
                    markers: [
                      Marker(
                        point: ll.LatLng(
                          _lastRouteResult!.nearestPoint!.lat,
                          _lastRouteResult!.nearestPoint!.lng,
                        ),
                        width: 32,
                        height: 32,
                        child: Container(
                          decoration: BoxDecoration(
                            color: const Color(0xFF7DD87A),
                            shape: BoxShape.circle,
                            border: Border.all(color: Colors.white, width: 2),
                          ),
                          child: const Icon(
                            Icons.place,
                            color: Color(0xFF0F1B12),
                            size: 18,
                          ),
                        ),
                      ),
                    ],
                  ),
                if (_currentGpsPosition != null)
                  MarkerLayer(
                    markers: [
                      Marker(
                        point: ll.LatLng(
                          _currentGpsPosition!.latitude,
                          _currentGpsPosition!.longitude,
                        ),
                        width: 48,
                        height: 48,
                        child: Container(
                          decoration: BoxDecoration(
                            color: Colors.blue.withValues(alpha: 0.2),
                            shape: BoxShape.circle,
                          ),
                          child: const Icon(
                            Icons.my_location,
                            color: Colors.blue,
                            size: 30,
                          ),
                        ),
                      ),
                    ],
                  ),
              ],
            ),
          ),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(16),
            color: const Color(0xFF1A2E1C),
            child: ConstrainedBox(
              constraints: BoxConstraints(
                maxHeight: MediaQuery.of(context).size.height * 0.45,
              ),
              child: SingleChildScrollView(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Recorded route preview',
                      style: TextStyle(
                        color: Colors.white,
                        fontSize: 17,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      _locationStatus,
                      style: TextStyle(
                        color: _currentGpsPosition == null
                            ? Colors.amber
                            : _isOffRoute
                            ? Colors.redAccent
                            : _green,
                        fontSize: 14,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    if (_distanceFromRoute != null) ...[
                      const SizedBox(height: 6),
                      Text(
                        'Distance from trail: '
                        '${_distanceFromRoute! >= 1000 ? '${(_distanceFromRoute! / 1000).toStringAsFixed(2)} km' : '${_distanceFromRoute!.toStringAsFixed(1)} m'}',
                        style: const TextStyle(color: Colors.white, fontSize: 13),
                      ),
                    ],
                    if (_lastRouteResult != null) ...[
                      const SizedBox(height: 10),
                      BackToTrailCard(
                        result: _lastRouteResult!,
                        threshold: RouteService.defaultOffRouteThresholdMetres,
                      ),
                    ],
                    const SizedBox(height: 10),
                    const Text(
                      'Green line: saved GPS track. '
                      'Red line: straight return vector. Red flag: end.',
                      style: TextStyle(color: _green, fontSize: 12),
                    ),
                    const SizedBox(height: 12),
                    Text(
                      'Recorded distance: '
                      '${_recordedDistanceMetres >= 1000 ? '${(_recordedDistanceMetres / 1000).toStringAsFixed(2)} km' : '${_recordedDistanceMetres.toStringAsFixed(0)} m'}',
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 14,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    if (_isTracking || _hasFinishedHike) ...[
                      const SizedBox(height: 5),
                      Text(
                        'Hike time: ${_formatDuration(_hikeStopwatch.elapsed)}',
                        style: const TextStyle(color: Colors.white70),
                      ),
                    ],
                    const SizedBox(height: 14),
                    if (!_isTracking)
                      SizedBox(
                        width: double.infinity,
                        child: ElevatedButton.icon(
                          onPressed: _startHike,
                          icon: const Icon(Icons.play_arrow),
                          label: Text(
                            _hasFinishedHike ? 'Start New Hike' : 'Start Hike',
                          ),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: _green,
                            foregroundColor: const Color(0xFF0F1B12),
                            padding: const EdgeInsets.symmetric(vertical: 14),
                          ),
                        ),
                      )
                    else ...[
                      Row(
                        children: [
                          Expanded(
                            child: OutlinedButton.icon(
                              onPressed: _togglePause,
                              icon: Icon(
                                _isPaused ? Icons.play_arrow : Icons.pause,
                              ),
                              label: Text(_isPaused ? 'Resume' : 'Pause'),
                              style: OutlinedButton.styleFrom(
                                foregroundColor: Colors.white,
                                padding: const EdgeInsets.symmetric(vertical: 12),
                              ),
                            ),
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: ElevatedButton.icon(
                              onPressed: _finishHike,
                              icon: const Icon(Icons.flag),
                              label: const Text('Finish Hike'),
                              style: ElevatedButton.styleFrom(
                                backgroundColor: Colors.redAccent,
                                foregroundColor: Colors.white,
                                padding: const EdgeInsets.symmetric(vertical: 12),
                              ),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton(
        backgroundColor: _green,
        foregroundColor: const Color(0xFF0F1B12),
        onPressed: () {
          if (points.isNotEmpty) {
            _mapController.move(center, 15);
          }
        },
        child: const Icon(Icons.center_focus_strong),
      ),
    );
  }
}
