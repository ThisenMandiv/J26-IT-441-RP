import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../models/completed_hike_model.dart';

/// Lightweight local persistence service for completed hikes.
/// Compatible with Flutter Web (localStorage) and mobile (SharedPreferences/NSUserDefaults).
class HikeHistoryService {
  static const String storageKey = 'tapropath_completed_hikes';

  final SharedPreferences? _prefs;

  const HikeHistoryService({SharedPreferences? preferences}) : _prefs = preferences;

  Future<SharedPreferences> _getPrefs() async {
    return _prefs ?? await SharedPreferences.getInstance();
  }

  /// Loads all saved hikes from local storage, sorted most recent first.
  /// Handles empty storage or corrupted records gracefully.
  Future<List<CompletedHike>> loadHikes() async {
    try {
      final prefs = await _getPrefs();
      final rawJson = prefs.getString(storageKey);
      if (rawJson == null || rawJson.trim().isEmpty) {
        return [];
      }

      final decoded = jsonDecode(rawJson);
      if (decoded is! List) {
        return [];
      }

      final hikes = <CompletedHike>[];
      for (final item in decoded) {
        if (item is Map) {
          try {
            hikes.add(CompletedHike.fromJson(Map<String, dynamic>.from(item)));
          } catch (e) {
            debugPrint('HikeHistoryService: Skipping corrupted hike record: $e');
          }
        }
      }

      // Sort by finish time or start time descending (most recent first)
      hikes.sort((a, b) {
        final timeA = a.finishTime ?? a.startTime ?? DateTime.fromMillisecondsSinceEpoch(0);
        final timeB = b.finishTime ?? b.startTime ?? DateTime.fromMillisecondsSinceEpoch(0);
        return timeB.compareTo(timeA);
      });

      return hikes;
    } catch (e) {
      debugPrint('HikeHistoryService: Error loading hikes: $e');
      return [];
    }
  }

  /// Saves a completed hike to local storage.
  /// Prepends new hike, ensuring no duplicate hike IDs.
  Future<bool> saveHike(CompletedHike hike) async {
    try {
      final prefs = await _getPrefs();
      final currentHikes = await loadHikes();

      // Avoid duplicate IDs
      final updatedHikes = [
        hike,
        ...currentHikes.where((h) => h.id != hike.id),
      ];

      final jsonString = jsonEncode(updatedHikes.map((h) => h.toJson()).toList());
      return await prefs.setString(storageKey, jsonString);
    } catch (e) {
      debugPrint('HikeHistoryService: Error saving hike: $e');
      return false;
    }
  }

  /// Clears all recorded completed hikes from local storage.
  Future<bool> clearHistory() async {
    try {
      final prefs = await _getPrefs();
      return await prefs.remove(storageKey);
    } catch (e) {
      debugPrint('HikeHistoryService: Error clearing history: $e');
      return false;
    }
  }

  // ---------------------------------------------------------------------------
  // Static convenience methods for simple one-line calls across the app
  // ---------------------------------------------------------------------------

  static Future<List<CompletedHike>> load() => const HikeHistoryService().loadHikes();

  static Future<bool> save(CompletedHike hike) => const HikeHistoryService().saveHike(hike);

  static Future<bool> clear() => const HikeHistoryService().clearHistory();
}
