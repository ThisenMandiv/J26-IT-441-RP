import 'package:flutter/material.dart';

import '../../app/routes.dart';
import '../../app/theme/app_colors.dart';
import '../../app/theme/app_spacing.dart';
import '../../app/theme/app_text_styles.dart';
import '../../shared/widgets/primary_button.dart';

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text(
          'TAPROPATH',
          style: TextStyle(fontWeight: FontWeight.w800, letterSpacing: 1.2),
        ),
        actions: [
          IconButton(
            tooltip: 'Notifications',
            constraints: const BoxConstraints(minWidth: 40, minHeight: 40),
            padding: EdgeInsets.zero,
            onPressed: () {},
            icon: const Icon(Icons.notifications_none_rounded),
          ),
          const SizedBox(width: 8),
        ],
      ),

      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(AppSpacing.xxl),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('Explore Sri Lanka', style: AppTextStyles.heading1),

              const SizedBox(height: AppSpacing.sm),

              const Text(
                'Plan your next adventure with personalized AI recommendations.',
                style: AppTextStyles.bodyMedium,
              ),

              const SizedBox(height: AppSpacing.xxxl),

              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(AppSpacing.xxl),
                decoration: BoxDecoration(
                  color: AppColors.dark,
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(
                      Icons.auto_awesome,
                      color: AppColors.gold,
                      size: 32,
                    ),

                    const SizedBox(height: AppSpacing.lg),

                    const Text(
                      'Plan your perfect trip',
                      style: TextStyle(
                        color: Colors.white,
                        fontSize: 22,
                        fontWeight: FontWeight.w700,
                      ),
                    ),

                    const SizedBox(height: AppSpacing.sm),

                    Text(
                      'Tell us what you love and TAPROPATH will find destinations that match your preferences.',
                      style: TextStyle(
                        color: Colors.white.withValues(alpha: 0.75),
                        fontSize: 14,
                        height: 1.5,
                      ),
                    ),

                    const SizedBox(height: AppSpacing.xxl),

                    PrimaryButton(
                      label: 'Start Planning',
                      icon: Icons.arrow_forward_rounded,
                      onPressed: () {
                        Navigator.pushNamed(context, AppRoutes.plan);
                      },
                    ),
                  ],
                ),
              ),

              const SizedBox(height: AppSpacing.xxxl),

              const Text('Discover', style: AppTextStyles.heading2),

              const SizedBox(height: AppSpacing.lg),

              Row(
                children: [
                  Expanded(
                    child: _DiscoverCard(
                      icon: Icons.landscape_outlined,
                      title: 'Nature',
                    ),
                  ),

                  const SizedBox(width: AppSpacing.md),

                  Expanded(
                    child: _DiscoverCard(
                      icon: Icons.beach_access_outlined,
                      title: 'Beaches',
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),

      bottomNavigationBar: NavigationBar(
        selectedIndex: 0,
        onDestinationSelected: (_) {},
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.home_outlined),
            selectedIcon: Icon(Icons.home),
            label: 'Home',
          ),
          NavigationDestination(
            icon: Icon(Icons.explore_outlined),
            selectedIcon: Icon(Icons.explore),
            label: 'Explore',
          ),
          NavigationDestination(
            icon: Icon(Icons.luggage_outlined),
            selectedIcon: Icon(Icons.luggage),
            label: 'Trips',
          ),
          NavigationDestination(
            icon: Icon(Icons.navigation_outlined),
            selectedIcon: Icon(Icons.navigation),
            label: 'Navigate',
          ),
          NavigationDestination(
            icon: Icon(Icons.person_outline),
            selectedIcon: Icon(Icons.person),
            label: 'Profile',
          ),
        ],
      ),
    );
  }
}

class _DiscoverCard extends StatelessWidget {
  final IconData icon;
  final String title;

  const _DiscoverCard({required this.icon, required this.title});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 28, color: AppColors.gold),

          const SizedBox(height: AppSpacing.lg),

          Text(title, style: AppTextStyles.label),
        ],
      ),
    );
  }
}
