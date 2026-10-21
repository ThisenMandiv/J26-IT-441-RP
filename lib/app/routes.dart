import 'package:flutter/material.dart';

import '../features/home/home_screen.dart';
import '../features/onboarding/onboarding_screen.dart';
import '../features/onboarding/splash_screen.dart';
import '../features/recommendations/plan_journey_screen.dart';

abstract final class AppRoutes {
  static const splash = '/';
  static const onboarding = '/onboarding';
  static const home = '/home';
  static const plan = '/plan';

  static final routes = <String, WidgetBuilder>{
  splash: (_) => const SplashScreen(),
  onboarding: (_) => const OnboardingScreen(),
  home: (_) => const HomeScreen(),
  plan: (_) => const PlanJourneyScreen(),
};
}