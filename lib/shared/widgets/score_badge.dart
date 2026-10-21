import 'package:flutter/material.dart';

import '../../app/theme/app_colors.dart';
import '../../app/theme/app_radii.dart';

class ScoreBadge extends StatelessWidget {
  final double score;

  const ScoreBadge({
    super.key,
    required this.score,
  });

  @override
  Widget build(BuildContext context) {
    final percentage = (score * 100).round();

    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: 10,
        vertical: 6,
      ),
      decoration: BoxDecoration(
        color: AppColors.buttonYellow,
        borderRadius: BorderRadius.circular(AppRadii.pill),
      ),
      child: Text(
        '$percentage% Match',
        style: const TextStyle(
          color: AppColors.dark,
          fontSize: 12,
          fontWeight: FontWeight.w800,
        ),
      ),
    );
  }
}