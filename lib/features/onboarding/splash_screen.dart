import 'dart:async';

import 'package:flutter/material.dart';

import '../../app/routes.dart';
import '../../app/theme/app_colors.dart';
import '../../app/theme/app_spacing.dart';

class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> {
  Timer? _navigationTimer;

  @override
  void initState() {
    super.initState();

    _navigationTimer = Timer(
      const Duration(seconds: 5),
      () {
        if (!mounted) return;

        Navigator.pushReplacementNamed(
          context,
          AppRoutes.onboarding,
        );
      },
    );
  }

  @override
  void dispose() {
    _navigationTimer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.dark,
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.xxl),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Container(
                width: 96,
                height: 96,
                decoration: BoxDecoration(
                  color: AppColors.gold,
                  borderRadius: BorderRadius.circular(28),
                ),
                child: const Icon(
                  Icons.explore_rounded,
                  size: 56,
                  color: AppColors.dark,
                ),
              ),
              const SizedBox(height: AppSpacing.xxl),
              const Text(
                'TAPROPATH',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 30,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 2,
                ),
              ),
              const SizedBox(height: AppSpacing.sm),
              Text(
                'Your journey. Your path.',
                style: TextStyle(
                  color: Colors.white.withValues(alpha: 0.7),
                  fontSize: 15,
                ),
              ),
              const SizedBox(height: AppSpacing.huge),
              const SizedBox(
                width: 24,
                height: 24,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  color: AppColors.gold,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}