import 'package:flutter/material.dart';

import '../../app/theme/app_colors.dart';
import '../../app/theme/app_radii.dart';
import '../../app/theme/app_spacing.dart';
import '../../app/theme/app_text_styles.dart';
import '../../shared/widgets/preference_chip.dart';
import '../../shared/widgets/primary_button.dart';
import '../../shared/widgets/section_title.dart';
import 'recommendation_service.dart';
import 'recommendation_results_screen.dart';

class PlanJourneyScreen extends StatefulWidget {
  const PlanJourneyScreen({super.key});

  @override
  State<PlanJourneyScreen> createState() => _PlanJourneyScreenState();
}

class _PlanJourneyScreenState extends State<PlanJourneyScreen> {
  int _durationDays = 4;
  bool _isLoading = false;
  double _budget = 60000;

  String _travelGroup = 'Solo';
  String _travelStyle = 'Adventure';

  final Set<String> _selectedInterests = {};
  final Set<String> _selectedActivities = {};

  final List<String> _travelGroups = ['Solo', 'Couple', 'Friends', 'Family'];

  final List<String> _travelStyles = [
    'Adventure',
    'Culture',
    'Relaxation',
    'Luxury',
  ];

  final List<_PreferenceItem> _interests = const [
    _PreferenceItem(label: 'Nature', icon: Icons.landscape_outlined),
    _PreferenceItem(label: 'Hiking', icon: Icons.hiking),
    _PreferenceItem(label: 'Photography', icon: Icons.camera_alt_outlined),
    _PreferenceItem(label: 'Beaches', icon: Icons.beach_access_outlined),
    _PreferenceItem(label: 'Wildlife', icon: Icons.pets_outlined),
    _PreferenceItem(label: 'History', icon: Icons.account_balance_outlined),
    _PreferenceItem(label: 'Food', icon: Icons.restaurant_outlined),
  ];

  final List<_PreferenceItem> _activities = const [
    _PreferenceItem(label: 'Hiking', icon: Icons.hiking),
    _PreferenceItem(label: 'Waterfalls', icon: Icons.water_drop_outlined),
    _PreferenceItem(label: 'Scenic Viewing', icon: Icons.visibility_outlined),
    _PreferenceItem(
      label: 'Temple Visits',
      icon: Icons.temple_buddhist_outlined,
    ),
    _PreferenceItem(label: 'Safari', icon: Icons.directions_car_outlined),
    _PreferenceItem(label: 'Surfing', icon: Icons.surfing),
  ];

  void _toggleSelection(Set<String> selections, String value) {
    setState(() {
      if (selections.contains(value)) {
        selections.remove(value);
      } else {
        selections.add(value);
      }
    });
  }

  String _formatBudget(double value) {
    final thousands = (value / 1000).round();
    return 'LKR ${thousands}K';
  }

  Future<void> _submitPreferences() async {
    if (_isLoading) return;

    setState(() {
      _isLoading = true;
    });

    try {
      final result = await RecommendationService.getRecommendations(
        durationDays: _durationDays,
        totalBudget: _budget.round(),
        travelGroup: _travelGroup,
        travelStyle: _travelStyle,
        selectedInterests: _selectedInterests,
        selectedActivities: _selectedActivities,
      );

      if (!mounted) return;

      await Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => RecommendationResultsScreen(result: result),
        ),
      );
    } catch (error) {
      if (!mounted) return;

      final message = error.toString().replaceFirst('Exception: ', '');

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Could not load recommendations: $message'),
          duration: const Duration(seconds: 5),
        ),
      );
    } finally {
      if (mounted) {
        setState(() {
          _isLoading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Plan Your Journey')),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.xxl,
            AppSpacing.lg,
            AppSpacing.xxl,
            AppSpacing.huge,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Tell us what you love',
                style: AppTextStyles.heading1,
              ),

              const SizedBox(height: AppSpacing.sm),

              const Text(
                'We will use your preferences to find destinations that match your journey.',
                style: AppTextStyles.bodyMedium,
              ),

              const SizedBox(height: AppSpacing.xxxl),

              const SectionTitle(
                title: 'Trip duration',
                subtitle: 'How long will you be travelling?',
              ),

              const SizedBox(height: AppSpacing.lg),

              _DurationSelector(
                durationDays: _durationDays,
                onChanged: (value) {
                  setState(() {
                    _durationDays = value;
                  });
                },
              ),

              const SizedBox(height: AppSpacing.xxxl),

              const SectionTitle(
                title: 'Budget',
                subtitle: 'Estimated total budget per person',
              ),

              const SizedBox(height: AppSpacing.lg),

              Container(
                padding: const EdgeInsets.all(AppSpacing.lg),
                decoration: BoxDecoration(
                  color: AppColors.surface,
                  borderRadius: BorderRadius.circular(AppRadii.large),
                  border: Border.all(color: AppColors.border),
                ),
                child: Column(
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        const Text('Your budget', style: AppTextStyles.label),
                        Text(
                          _formatBudget(_budget),
                          style: AppTextStyles.heading3,
                        ),
                      ],
                    ),
                    Slider(
                      value: _budget,
                      min: 10000,
                      max: 200000,
                      divisions: 38,
                      activeColor: AppColors.gold,
                      onChanged: (value) {
                        setState(() {
                          _budget = value;
                        });
                      },
                    ),
                    const Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text('LKR 10K', style: AppTextStyles.bodyMedium),
                        Text('LKR 200K', style: AppTextStyles.bodyMedium),
                      ],
                    ),
                  ],
                ),
              ),

              const SizedBox(height: AppSpacing.xxxl),

              const SectionTitle(
                title: 'Travel group',
                subtitle: 'Who are you travelling with?',
              ),

              const SizedBox(height: AppSpacing.lg),

              Wrap(
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.sm,
                children: _travelGroups.map((group) {
                  return PreferenceChip(
                    label: group,
                    icon: _groupIcon(group),
                    selected: _travelGroup == group,
                    onSelected: () {
                      setState(() {
                        _travelGroup = group;
                      });
                    },
                  );
                }).toList(),
              ),

              const SizedBox(height: AppSpacing.xxxl),

              const SectionTitle(
                title: 'Travel style',
                subtitle: 'What kind of experience do you prefer?',
              ),

              const SizedBox(height: AppSpacing.lg),

              Wrap(
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.sm,
                children: _travelStyles.map((style) {
                  return PreferenceChip(
                    label: style,
                    icon: _styleIcon(style),
                    selected: _travelStyle == style,
                    onSelected: () {
                      setState(() {
                        _travelStyle = style;
                      });
                    },
                  );
                }).toList(),
              ),

              const SizedBox(height: AppSpacing.xxxl),

              const SectionTitle(
                title: 'Interests',
                subtitle: 'Select everything you enjoy',
              ),

              const SizedBox(height: AppSpacing.lg),

              Wrap(
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.sm,
                children: _interests.map((item) {
                  return PreferenceChip(
                    label: item.label,
                    icon: item.icon,
                    selected: _selectedInterests.contains(item.label),
                    onSelected: () {
                      _toggleSelection(_selectedInterests, item.label);
                    },
                  );
                }).toList(),
              ),

              const SizedBox(height: AppSpacing.xxxl),

              const SectionTitle(
                title: 'Preferred activities',
                subtitle: 'What would you like to do?',
              ),

              const SizedBox(height: AppSpacing.lg),

              Wrap(
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.sm,
                children: _activities.map((item) {
                  return PreferenceChip(
                    label: item.label,
                    icon: item.icon,
                    selected: _selectedActivities.contains(item.label),
                    onSelected: () {
                      _toggleSelection(_selectedActivities, item.label);
                    },
                  );
                }).toList(),
              ),

              const SizedBox(height: AppSpacing.huge),

              PrimaryButton(
                label: 'Get My Recommendations',
                icon: Icons.auto_awesome_rounded,
                isLoading: _isLoading,
                onPressed: _submitPreferences,
              ),
            ],
          ),
        ),
      ),
    );
  }

  IconData _groupIcon(String group) {
    switch (group) {
      case 'Couple':
        return Icons.favorite_outline_rounded;
      case 'Friends':
        return Icons.groups_outlined;
      case 'Family':
        return Icons.family_restroom_rounded;
      default:
        return Icons.person_outline_rounded;
    }
  }

  IconData _styleIcon(String style) {
    switch (style) {
      case 'Culture':
        return Icons.account_balance_outlined;
      case 'Relaxation':
        return Icons.spa_outlined;
      case 'Luxury':
        return Icons.diamond_outlined;
      default:
        return Icons.explore_outlined;
    }
  }
}

class _DurationSelector extends StatelessWidget {
  final int durationDays;
  final ValueChanged<int> onChanged;

  const _DurationSelector({
    required this.durationDays,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppRadii.large),
        border: Border.all(color: AppColors.border),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          IconButton(
            onPressed: durationDays > 1
                ? () => onChanged(durationDays - 1)
                : null,
            icon: const Icon(Icons.remove_rounded),
          ),
          Column(
            children: [
              Text('$durationDays', style: AppTextStyles.heading1),
              const Text('Days', style: AppTextStyles.bodyMedium),
            ],
          ),
          IconButton(
            onPressed: durationDays < 14
                ? () => onChanged(durationDays + 1)
                : null,
            icon: const Icon(Icons.add_rounded),
          ),
        ],
      ),
    );
  }
}

class _PreferenceItem {
  final String label;
  final IconData icon;

  const _PreferenceItem({required this.label, required this.icon});
}
