import 'package:flutter/material.dart';

import '../../app/theme/app_colors.dart';
import '../../app/theme/app_radii.dart';

class PreferenceChip extends StatelessWidget {
  final String label;
  final IconData? icon;
  final bool selected;
  final VoidCallback? onSelected;

  const PreferenceChip({
    super.key,
    required this.label,
    this.icon,
    this.selected = false,
    this.onSelected,
  });

  @override
  Widget build(BuildContext context) {
    return FilterChip(
      selected: selected,
      onSelected: onSelected == null
          ? null
          : (_) => onSelected!(),
      avatar: icon == null
          ? null
          : Icon(
              icon,
              size: 18,
              color: selected
                  ? AppColors.dark
                  : AppColors.textSecondary,
            ),
      label: Text(label),
      labelStyle: TextStyle(
        color: selected
            ? AppColors.dark
            : AppColors.textPrimary,
        fontWeight: selected
            ? FontWeight.w700
            : FontWeight.w500,
      ),
      backgroundColor: AppColors.surface,
      selectedColor: AppColors.buttonYellow,
      checkmarkColor: AppColors.dark,
      side: BorderSide(
        color: selected
            ? AppColors.buttonYellow
            : AppColors.border,
      ),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppRadii.pill),
      ),
      padding: const EdgeInsets.symmetric(
        horizontal: 10,
        vertical: 8,
      ),
    );
  }
}