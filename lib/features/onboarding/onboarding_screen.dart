import 'package:flutter/material.dart';

import '../../app/routes.dart';
import '../../app/theme/app_colors.dart';
import '../../app/theme/app_spacing.dart';
import '../../app/theme/app_text_styles.dart';
import '../../shared/widgets/primary_button.dart';

class OnboardingScreen extends StatefulWidget {
  const OnboardingScreen({super.key});

  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<OnboardingScreen> {
  final PageController _pageController = PageController();

  int _currentPage = 0;

  final List<_OnboardingPageData> _pages = const [
    _OnboardingPageData(
      icon: Icons.auto_awesome_rounded,
      title: 'Travel made personal',
      description:
          'Discover destinations that match your interests, travel style, and budget.',
    ),
    _OnboardingPageData(
      icon: Icons.map_rounded,
      title: 'Explore with confidence',
      description:
          'Get meaningful recommendations and plan your journey across Sri Lanka.',
    ),
    _OnboardingPageData(
      icon: Icons.luggage_rounded,
      title: 'Your perfect trip starts here',
      description:
          'Choose your destinations and create a trip that feels truly yours.',
    ),
  ];

  @override
  void dispose() {
    _pageController.dispose();
    super.dispose();
  }

  void _nextPage() {
    if (_currentPage == _pages.length - 1) {
      Navigator.pushReplacementNamed(
        context,
        AppRoutes.home,
      );
      return;
    }

    _pageController.nextPage(
      duration: const Duration(milliseconds: 300),
      curve: Curves.easeInOut,
    );
  }

  @override
  Widget build(BuildContext context) {
  

    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.xxl),
          child: Column(
            children: [
              Align(
                alignment: Alignment.centerRight,
                child: TextButton(
                  onPressed: () {
                    Navigator.pushReplacementNamed(
                      context,
                      AppRoutes.home,
                    );
                  },
                  child: const Text('Skip'),
                ),
              ),

              Expanded(
                child: PageView.builder(
                  controller: _pageController,
                  itemCount: _pages.length,
                  onPageChanged: (index) {
                    setState(() {
                      _currentPage = index;
                    });
                  },
                  itemBuilder: (context, index) {
                    final item = _pages[index];

                    return _OnboardingContent(
                      data: item,
                    );
                  },
                ),
              ),

              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: List.generate(
                  _pages.length,
                  (index) {
                    final isActive = index == _currentPage;

                    return AnimatedContainer(
                      duration: const Duration(milliseconds: 200),
                      margin: const EdgeInsets.symmetric(horizontal: 4),
                      width: isActive ? 28 : 8,
                      height: 8,
                      decoration: BoxDecoration(
                        color: isActive
                            ? AppColors.gold
                            : AppColors.border,
                        borderRadius: BorderRadius.circular(999),
                      ),
                    );
                  },
                ),
              ),

              const SizedBox(height: AppSpacing.xxl),

              PrimaryButton(
                label: _currentPage == _pages.length - 1
                    ? 'Get Started'
                    : 'Continue',
                icon: _currentPage == _pages.length - 1
                    ? Icons.arrow_forward_rounded
                    : Icons.chevron_right_rounded,
                onPressed: _nextPage,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _OnboardingContent extends StatelessWidget {
  final _OnboardingPageData data;

  const _OnboardingContent({
    required this.data,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Container(
          width: 180,
          height: 180,
          decoration: BoxDecoration(
            color: AppColors.softSurface,
            borderRadius: BorderRadius.circular(48),
          ),
          child: Icon(
            data.icon,
            size: 88,
            color: AppColors.gold,
          ),
        ),

        const SizedBox(height: AppSpacing.huge),

        Text(
          data.title,
          textAlign: TextAlign.center,
          style: AppTextStyles.heading1,
        ),

        const SizedBox(height: AppSpacing.lg),

        Text(
          data.description,
          textAlign: TextAlign.center,
          style: AppTextStyles.bodyLarge.copyWith(
            color: AppColors.textSecondary,
            height: 1.5,
          ),
        ),
      ],
    );
  }
}

class _OnboardingPageData {
  final IconData icon;
  final String title;
  final String description;

  const _OnboardingPageData({
    required this.icon,
    required this.title,
    required this.description,
  });
}