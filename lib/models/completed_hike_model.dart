import 'trail_model.dart';

/// Represents a completed hike record stored locally on the device/browser.
class CompletedHike {
  final String id;
  final String? trailId;
  final String? trailName;
  final DateTime? startTime;
  final DateTime? finishTime;
  final Duration duration;
  final List<LatLng> recordedPoints;
  final double distanceKm;

  const CompletedHike({
    required this.id,
    this.trailId,
    this.trailName,
    this.startTime,
    this.finishTime,
    required this.duration,
    required this.recordedPoints,
    required this.distanceKm,
  });

  Map<String, dynamic> toJson() => {
        'id': id,
        'trailId': trailId,
        'trailName': trailName,
        'startTime': startTime?.toIso8601String(),
        'finishTime': finishTime?.toIso8601String(),
        'durationSeconds': duration.inSeconds,
        'recordedPoints': recordedPoints.map((p) => p.toJson()).toList(),
        'distanceKm': distanceKm,
      };

  factory CompletedHike.fromJson(Map<String, dynamic> json) {
    final rawPoints = json['recordedPoints'] as List<dynamic>? ?? [];
    final points = rawPoints
        .map((p) => LatLng.fromJson(Map<String, dynamic>.from(p as Map)))
        .toList();

    DateTime? parseDate(dynamic v) {
      if (v is String && v.isNotEmpty) {
        return DateTime.tryParse(v);
      }
      return null;
    }

    final durationSeconds = (json['durationSeconds'] as num?)?.toInt() ?? 0;

    return CompletedHike(
      id: json['id'] as String? ?? 'hike_${DateTime.now().millisecondsSinceEpoch}',
      trailId: json['trailId'] as String?,
      trailName: json['trailName'] as String?,
      startTime: parseDate(json['startTime']),
      finishTime: parseDate(json['finishTime']),
      duration: Duration(seconds: durationSeconds),
      recordedPoints: points,
      distanceKm: (json['distanceKm'] as num?)?.toDouble() ?? 0.0,
    );
  }

  String get formattedDuration {
    final h = duration.inHours.toString().padLeft(2, '0');
    final m = (duration.inMinutes % 60).toString().padLeft(2, '0');
    final s = (duration.inSeconds % 60).toString().padLeft(2, '0');
    return '$h:$m:$s';
  }

  String get formattedDistance {
    if (distanceKm >= 1.0) {
      return '${distanceKm.toStringAsFixed(2)} km';
    }
    return '${(distanceKm * 1000).toStringAsFixed(0)} m';
  }

  String get formattedDate {
    final date = finishTime ?? startTime ?? DateTime.now();
    final y = date.year.toString();
    final m = date.month.toString().padLeft(2, '0');
    final d = date.day.toString().padLeft(2, '0');
    final hh = date.hour.toString().padLeft(2, '0');
    final mm = date.minute.toString().padLeft(2, '0');
    return '$y-$m-$d $hh:$mm';
  }
}
