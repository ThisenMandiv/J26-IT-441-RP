import 'package:flutter/material.dart';

import '../../app/theme/app_colors.dart';
import '../../app/theme/app_radii.dart';
import '../../app/theme/app_spacing.dart';
import '../../app/theme/app_text_styles.dart';
import 'destination_detail_screen.dart';

class RecommendationResultsScreen extends StatefulWidget {
  final Map<String, dynamic> result;

  const RecommendationResultsScreen({super.key, required this.result});

  @override
  State<RecommendationResultsScreen> createState() =>
      _RecommendationResultsScreenState();
}

class _RecommendationResultsScreenState
    extends State<RecommendationResultsScreen> {
  final Set<String> _addedDestinations = {};

  List<Map<String, dynamic>> get _recommendations {
    final items = widget.result['recommendations'];
    if (items is! List) return [];

    return items
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .toList();
  }

  String _money(dynamic value) {
    final amount = (value as num?)?.round() ?? 0;
    final digits = amount.toString();
    final buffer = StringBuffer();

    for (var i = 0; i < digits.length; i++) {
      if (i > 0 && (digits.length - i) % 3 == 0) {
        buffer.write(',');
      }
      buffer.write(digits[i]);
    }

    return 'LKR ${buffer.toString()}';
  }

  String _destinationKey(Map<String, dynamic> destination) {
    return (destination['destination_id'] ??
            destination['id'] ??
            destination['name'] ??
            'unknown')
        .toString();
  }

  String _imageFor(Map<String, dynamic> destination) {
    final name = (destination['name'] ?? '').toString().toLowerCase();
    final type = (destination['destination_type'] ?? '')
        .toString()
        .toLowerCase();

    if (name.contains('beach') ||
        name.contains('surf') ||
        name.contains('mirissa') ||
        name.contains('unawatuna') ||
        name.contains('hikkaduwa')) {
      return 'https://images.unsplash.com/photo-1500375592092-40eb2168fd21'
          '?auto=format&fit=crop&w=1200&q=85';
    }

    if (name.contains('ella') ||
        name.contains('nuwara eliya') ||
        name.contains('hill') ||
        name.contains('hiking') ||
        type.contains('mountain')) {
      return 'https://images.unsplash.com/photo-1464822759023-fed622ff2c3b'
          '?auto=format&fit=crop&w=1200&q=85';
    }

    if (name.contains('safari') ||
        name.contains('yala') ||
        name.contains('minneriya') ||
        name.contains('wildlife') ||
        type.contains('wildlife')) {
      return 'https://images.unsplash.com/photo-1516426122078-c23e76319801'
          '?auto=format&fit=crop&w=1200&q=85';
    }

    if (name.contains('temple') ||
        name.contains('heritage') ||
        name.contains('sigiriya') ||
        name.contains('polonnaruwa') ||
        name.contains('anuradhapura') ||
        type.contains('cultural')) {
      return 'https://images.unsplash.com/photo-1606293926075-69a00dbfde81'
          '?auto=format&fit=crop&w=1200&q=85';
    }

    if (type.contains('waterfall') || name.contains('waterfall')) {
      return 'https://images.unsplash.com/photo-1432405972618-c60b0225b8f9'
          '?auto=format&fit=crop&w=1200&q=85';
    }

    return 'https://images.unsplash.com/photo-1470770841072-f978cf4d019e'
        '?auto=format&fit=crop&w=1200&q=85';
  }

  @override
  Widget build(BuildContext context) {
    final recommendations = _recommendations;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Your Recommendations'),
        centerTitle: false,
      ),
      body: SafeArea(
        child: recommendations.isEmpty
            ? _buildEmptyState(context)
            : ListView(
                padding: const EdgeInsets.all(AppSpacing.lg),
                children: [
                  const Text(
                    'Your next adventure starts here',
                    style: AppTextStyles.heading1,
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  Text(
                    '${widget.result['returned_count'] ?? recommendations.length} '
                    'destinations matched your trip preferences.',
                    style: AppTextStyles.bodyMedium,
                  ),
                  const SizedBox(height: AppSpacing.lg),
                  ...recommendations.asMap().entries.map((entry) {
                    return Padding(
                      padding: const EdgeInsets.only(bottom: AppSpacing.lg),
                      child: _DestinationCard(
                        destination: entry.value,
                        rank: entry.key + 1,
                        moneyFormatter: _money,
                        imageUrl: _imageFor(entry.value),
                        isAdded: _addedDestinations.contains(
                          _destinationKey(entry.value),
                        ),
                        onToggleTrip: () {
                          final key = _destinationKey(entry.value);

                          setState(() {
                            if (_addedDestinations.contains(key)) {
                              _addedDestinations.remove(key);
                            } else {
                              _addedDestinations.add(key);
                            }
                          });
                        },
                        onViewDetails: () {
  Navigator.of(context).push(
    MaterialPageRoute(
      builder: (_) => DestinationDetailScreen(
        destination: entry.value,
        rank: entry.key + 1,
        imageUrl: _imageFor(entry.value),
        isAdded: _addedDestinations.contains(
          _destinationKey(entry.value),
        ),
        moneyFormatter: _money,
        onToggleTrip: () {
          final key = _destinationKey(entry.value);

          setState(() {
            if (_addedDestinations.contains(key)) {
              _addedDestinations.remove(key);
            } else {
              _addedDestinations.add(key);
            }
          });
        },
      ),
    ),
  );
},
                      ),
                    );
                  }),
                  if (_addedDestinations.isNotEmpty) ...[
                    const SizedBox(height: AppSpacing.sm),
                    Container(
                      padding: const EdgeInsets.all(AppSpacing.lg),
                      decoration: BoxDecoration(
                        color: AppColors.surface,
                        borderRadius: BorderRadius.circular(AppRadii.large),
                        border: Border.all(color: AppColors.border),
                      ),
                      child: Row(
                        children: [
                          const Icon(
                            Icons.luggage_outlined,
                            color: AppColors.gold,
                            size: 28,
                          ),
                          const SizedBox(width: AppSpacing.md),
                          Expanded(
                            child: Text(
                              '${_addedDestinations.length} destination(s) '
                              'added to your trip selection.',
                              style: AppTextStyles.bodyMedium,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ],
              ),
      ),
    );
  }

  Widget _buildEmptyState(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.xxl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(
              Icons.travel_explore_rounded,
              size: 56,
              color: AppColors.gold,
            ),
            const SizedBox(height: AppSpacing.lg),
            const Text(
              'No matching destinations found',
              style: AppTextStyles.heading3,
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: AppSpacing.sm),
            const Text(
              'Try changing your budget, travel duration, or preferences.',
              style: AppTextStyles.bodyMedium,
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: AppSpacing.xl),
            FilledButton.icon(
              onPressed: () => Navigator.of(context).pop(),
              icon: const Icon(Icons.edit_outlined),
              label: const Text('Adjust Preferences'),
            ),
          ],
        ),
      ),
    );
  }
}

class _DestinationCard extends StatelessWidget {
  final Map<String, dynamic> destination;
  final int rank;
  final String Function(dynamic) moneyFormatter;
  final String imageUrl;
  final bool isAdded;
  final VoidCallback onToggleTrip;
  final VoidCallback onViewDetails;

  const _DestinationCard({
    required this.destination,
    required this.rank,
    required this.moneyFormatter,
    required this.imageUrl,
    required this.isAdded,
    required this.onToggleTrip,
    required this.onViewDetails,
  });

  @override
  Widget build(BuildContext context) {
    final rawScore =
        destination['compatibility_score'] ?? destination['match_score'] ?? 0;

    final score = ((rawScore as num).toDouble()).clamp(0.0, 1.0);
    final percentage = (score * 100).round();

    final name = destination['name']?.toString() ?? 'Unnamed destination';
    final district = destination['district']?.toString() ?? '';
    final province = destination['province']?.toString() ?? '';
    final type = destination['destination_type']?.toString() ?? '';
    final description = destination['description']?.toString() ?? '';

    final reasons =
        (destination['reasons'] as List?)
            ?.map((reason) => reason.toString())
            .toList() ??
        [];

    final duration = destination['average_visit_duration_hours'];

    final bestSeason = destination['best_season']?.toString() ?? '';

    final location = [
      district,
      province,
    ].where((part) => part.trim().isNotEmpty).join(', ');

    return Container(
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppRadii.large),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Stack(
            children: [
              SizedBox(
                width: double.infinity,
                height: 190,
                child: Image.network(
                  imageUrl,
                  fit: BoxFit.cover,
                  loadingBuilder: (context, child, progress) {
                    if (progress == null) return child;

                    return Container(
                      color: AppColors.gold.withValues(alpha: 0.10),
                      alignment: Alignment.center,
                      child: const CircularProgressIndicator(),
                    );
                  },
                  errorBuilder: (context, error, stackTrace) {
                    return Container(
                      color: AppColors.gold.withValues(alpha: 0.12),
                      alignment: Alignment.center,
                      child: const Icon(
                        Icons.landscape_rounded,
                        size: 54,
                        color: AppColors.gold,
                      ),
                    );
                  },
                ),
              ),
              Positioned(
                top: AppSpacing.md,
                left: AppSpacing.md,
                child: Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: AppSpacing.md,
                    vertical: AppSpacing.sm,
                  ),
                  decoration: BoxDecoration(
                    color: Colors.black.withValues(alpha: 0.65),
                    borderRadius: BorderRadius.circular(AppRadii.medium),
                  ),
                  child: Text(
                    '#$rank Recommended',
                    style: const TextStyle(
                      color: Colors.white,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ),
              Positioned(
                top: AppSpacing.md,
                right: AppSpacing.md,
                child: Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: AppSpacing.md,
                    vertical: AppSpacing.sm,
                  ),
                  decoration: BoxDecoration(
                    color: AppColors.surface,
                    borderRadius: BorderRadius.circular(AppRadii.medium),
                  ),
                  child: Text('$percentage% Match', style: AppTextStyles.label),
                ),
              ),
            ],
          ),
          Padding(
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(name, style: AppTextStyles.heading3),
                if (location.isNotEmpty) ...[
                  const SizedBox(height: AppSpacing.xs),
                  Row(
                    children: [
                      const Icon(
                        Icons.location_on_outlined,
                        size: 18,
                        color: AppColors.gold,
                      ),
                      const SizedBox(width: AppSpacing.xs),
                      Expanded(
                        child: Text(location, style: AppTextStyles.bodyMedium),
                      ),
                    ],
                  ),
                ],
                if (type.isNotEmpty) ...[
                  const SizedBox(height: AppSpacing.sm),
                  Wrap(
                    spacing: AppSpacing.sm,
                    children: [
                      Chip(
                        visualDensity: VisualDensity.compact,
                        label: Text(type.replaceAll('_', ' ')),
                      ),
                    ],
                  ),
                ],
                if (description.isNotEmpty) ...[
                  const SizedBox(height: AppSpacing.md),
                  Text(
                    description,
                    maxLines: 3,
                    overflow: TextOverflow.ellipsis,
                    style: AppTextStyles.bodyMedium,
                  ),
                ],
                const SizedBox(height: AppSpacing.lg),
                Container(
                  padding: const EdgeInsets.all(AppSpacing.md),
                  decoration: BoxDecoration(
                    color: AppColors.gold.withValues(alpha: 0.09),
                    borderRadius: BorderRadius.circular(AppRadii.medium),
                  ),
                  child: Row(
                    children: [
                      const Icon(
                        Icons.account_balance_wallet_outlined,
                        color: AppColors.gold,
                        size: 25,
                      ),
                      const SizedBox(width: AppSpacing.md),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'Estimated daily cost',
                              style: AppTextStyles.label,
                            ),
                            const SizedBox(height: AppSpacing.xs),
                            Text(
                              moneyFormatter(
                                destination['estimated_daily_cost'],
                              ),
                              style: AppTextStyles.heading3,
                            ),
                          ],
                        ),
                      ),
                      if (duration is num) ...[
                        const SizedBox(width: AppSpacing.sm),
                        Column(
                          crossAxisAlignment: CrossAxisAlignment.end,
                          children: [
                            const Icon(
                              Icons.schedule_rounded,
                              color: AppColors.gold,
                            ),
                            Text(
                              '${duration.toStringAsFixed(1)} hrs',
                              style: AppTextStyles.label,
                            ),
                          ],
                        ),
                      ],
                    ],
                  ),
                ),
                if (bestSeason.isNotEmpty) ...[
                  const SizedBox(height: AppSpacing.md),
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Icon(
                        Icons.wb_sunny_outlined,
                        size: 19,
                        color: AppColors.gold,
                      ),
                      const SizedBox(width: AppSpacing.sm),
                      Expanded(
                        child: Text(
                          'Best season: $bestSeason',
                          style: AppTextStyles.bodyMedium,
                        ),
                      ),
                    ],
                  ),
                ],
                if (reasons.isNotEmpty) ...[
                  const SizedBox(height: AppSpacing.lg),
                  Text('Why this matches you', style: AppTextStyles.label),
                  const SizedBox(height: AppSpacing.sm),
                  ...reasons
                      .take(3)
                      .map(
                        (reason) => Padding(
                          padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                          child: Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const Icon(
                                Icons.check_circle_outline_rounded,
                                size: 18,
                                color: AppColors.gold,
                              ),
                              const SizedBox(width: AppSpacing.sm),
                              Expanded(
                                child: Text(
                                  reason,
                                  style: AppTextStyles.bodyMedium,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                ],
                const SizedBox(height: AppSpacing.lg),
                Row(
                  children: [
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed: onViewDetails,
                        icon: const Icon(Icons.visibility_outlined),
                        label: const Text('View Details'),
                      ),
                    ),
                    const SizedBox(width: AppSpacing.sm),
                    Expanded(
                      child: FilledButton.icon(
                        onPressed: onToggleTrip,
                        icon: Icon(
                          isAdded
                              ? Icons.check_circle_rounded
                              : Icons.add_rounded,
                        ),
                        label: Text(isAdded ? 'Added' : 'Add to Trip'),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
  