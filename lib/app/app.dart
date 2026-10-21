import 'package:flutter/material.dart';

import 'theme/app_theme.dart';
import 'routes.dart';

class TaproPathApp extends StatelessWidget {
  const TaproPathApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'TAPROPATH',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light(),
      initialRoute: AppRoutes.splash,
      routes: AppRoutes.routes,
    );
  }
}