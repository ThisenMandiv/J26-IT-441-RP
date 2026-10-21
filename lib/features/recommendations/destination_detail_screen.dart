
import 'package:flutter/material.dart';

import '../../app/theme/app_colors.dart';
import '../../app/theme/app_radii.dart';
import '../../app/theme/app_spacing.dart';
import '../../app/theme/app_text_styles.dart';

class DestinationDetailScreen extends StatelessWidget {
  final Map<String, dynamic> destination;
  final int rank;
  final String imageUrl;
  final bool isAdded;
  final String Function(dynamic) moneyFormatter;
  final VoidCallback onToggleTrip;

  const DestinationDetailScreen({
    super.key,
    required this.destination,
    required this.rank,
    required this.imageUrl,
    required this.isAdded,
    required this.moneyFormatter,
    required this.onToggleTrip,
  });

  @override
  Widget build(BuildContext context) {
    final rawScore = destination['compatibility_score'] ??
        destination['match_score'] ??
        0;
    final score = (rawScore as num).toDouble().clamp(0.0, 1.0);
    final percentage = (score * 100).round();

    final name =
        destination['name']?.toString() ?? 'Unnamed destination';
    final district = destination['district']?.toString() ?? '';
    final province = destination['province']?.toString() ?? '';
    final type = destination['destination_type']
            ?.toString()
            .replaceAll('_', ' ') ??
        '';

    final description =
        destination['description']?.toString() ?? '';
    final bestSeason =
        destination['best_season']?.toString() ?? '';
    final duration = destination['average_visit_duration_hours'];
    final reasons = (destination['reasons'] as List?)
            ?.map((reason) => reason.toString())
            .toList() ??
        [];

    final location = [district, province]
        .where((part) => part.trim().isNotEmpty)
        .join(', ');

    return Scaffold(
      appBar: AppBar(
        title: const Text('Destination Details'),
      ),
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: ListView(
                padding: const EdgeInsets.only(bottom: AppSpacing.lg),
                children: [
                  Stack(
                    children: [
                      SizedBox(
                        width: double.infinity,
                        height: 260,
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
                                size: 64,
                                color: AppColors.gold,
                              ),
                            );
                          },
                        ),
                      ),
                      Positioned(
                        left: AppSpacing.lg,
                        top: AppSpacing.lg,
                        child: _InfoBadge(label: '#$rank Recommended'),
                      ),
                      Positioned(
                        right: AppSpacing.lg,
                        top: AppSpacing.lg,
                        child: _InfoBadge(label: '$percentage% Match'),
                      ),
                    ],
                  ),
                  Padding(
                    padding: const EdgeInsets.all(AppSpacing.lg),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(name, style: AppTextStyles.heading1),
                        if (location.isNotEmpty) ...[
                          const SizedBox(height: AppSpacing.sm),
                          Row(
                            children: [
                              const Icon(
                                Icons.location_on_outlined,
                                color: AppColors.gold,
                                size: 20,
                              ),
                              const SizedBox(width: AppSpacing.xs),
                              Expanded(
                                child: Text(
                                  location,
                                  style: AppTextStyles.bodyMedium,
                                ),
                              ),
                            ],
                          ),
                        ],
                        if (type.isNotEmpty) ...[
                          const SizedBox(height: AppSpacing.md),
                          Chip(
                            avatar: const Icon(
                              Icons.explore_outlined,
                              size: 18,
                            ),
                            label: Text(type),
                          ),
                        ],
                        const SizedBox(height: AppSpacing.xl),
                        const Text(
                          'About this destination',
                          style: AppTextStyles.heading3,
                        ),
                        const SizedBox(height: AppSpacing.sm),
                        Text(
                          description.isNotEmpty
                              ? description
                              : 'No description is available for this destination yet.',
                          style: AppTextStyles.bodyMedium,
                        ),
                        const SizedBox(height: AppSpacing.xl),
                        const Text(
                          'Your trip at a glance',
                          style: AppTextStyles.heading3,
                        ),
                        const SizedBox(height: AppSpacing.md),
                        Row(
                          children: [
                            Expanded(
                              child: _DetailMetric(
                                icon: Icons.account_balance_wallet_outlined,
                                label: 'Estimated per day',
                                value: moneyFormatter(
                                  destination['estimated_daily_cost'],
                                ),
                              ),
                            ),
                            const SizedBox(width: AppSpacing.md),
                            Expanded(
                              child: _DetailMetric(
                                icon: Icons.schedule_rounded,
                                label: 'Visit duration',
                                value: duration is num
                                    ? '${duration.toStringAsFixed(1)} hours'
                                    : 'Not specified',
                              ),
                            ),
                          ],
                        ),
                        if (bestSeason.isNotEmpty) ...[
                          const SizedBox(height: AppSpacing.md),
                          _DetailMetric(
                            icon: Icons.wb_sunny_outlined,
                            label: 'Best season',
                            value: bestSeason,
                          ),
                        ],
                        const SizedBox(height: AppSpacing.xl),
                        const Text(
                          'Why this destination matches you',
                          style: AppTextStyles.heading3,
                        ),
                        const SizedBox(height: AppSpacing.md),
                        if (reasons.isEmpty)
                          Text(
                            'No specific recommendation reasons were provided.',
                            style: AppTextStyles.bodyMedium,
                          )
                        else
                          ...reasons.map(
                            (reason) => Padding(
                              padding: const EdgeInsets.only(
                                bottom: AppSpacing.md,
                              ),
                              child: Row(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  const Icon(
                                    Icons.check_circle_rounded,
                                    color: AppColors.gold,
                                    size: 20,
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
                        const SizedBox(height: AppSpacing.md),
                        Container(
                          padding: const EdgeInsets.all(AppSpacing.lg),
                          decoration: BoxDecoration(
                            color: AppColors.gold.withValues(alpha: 0.09),
                            borderRadius:
                                BorderRadius.circular(AppRadii.large),
                            border: Border.all(
                              color: AppColors.border,
                            ),
                          ),
                          child: Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const Icon(
                                Icons.lightbulb_outline_rounded,
                                color: AppColors.gold,
                              ),
                              const SizedBox(width: AppSpacing.md),
                              Expanded(
                                child: Text(
                                  'Use the estimated cost and visit duration '
                                  'as planning guides. Actual costs and '
                                  'conditions may vary.',
                                  style: AppTextStyles.bodyMedium,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(AppSpacing.lg),
              child: SizedBox(
                width: double.infinity,
                child: FilledButton.icon(
                  onPressed: () {
                    onToggleTrip();
                    Navigator.of(context).pop();
                  },
                  icon: Icon(
                    isAdded
                        ? Icons.remove_circle_outline
                        : Icons.add_location_alt_outlined,
                  ),
                  label: Text(
                    isAdded ? 'Remove from Trip' : 'Add to Trip',
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _InfoBadge extends StatelessWidget {
  final String label;

  const _InfoBadge({required this.label});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.md,
        vertical: AppSpacing.sm,
      ),
      decoration: BoxDecoration(
        color: Colors.black.withValues(alpha: 0.70),
        borderRadius: BorderRadius.circular(AppRadii.medium),
      ),
      child: Text(
        label,
        style: const TextStyle(
          color: Colors.white,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}

class _DetailMetric extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;

  const _DetailMetric({
    required this.icon,
    required this.label,
    required this.value,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppRadii.medium),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: AppColors.gold, size: 23),
          const SizedBox(height: AppSpacing.sm),
          Text(label, style: AppTextStyles.label),
          const SizedBox(height: AppSpacing.xs),
          Text(
            value,
            style: AppTextStyles.bodyMedium,
          ),
        ],
      ),
    );
  }
}
