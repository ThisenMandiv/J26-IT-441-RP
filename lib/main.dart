import 'package:flutter/material.dart';
import 'screens/home_screen.dart';

void main() {
  runApp(const TaproPathApp());
}

class TaproPathApp extends StatelessWidget {
  const TaproPathApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Tapro Path',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: const Color(0xFF0F1B12),
        colorScheme: ColorScheme.dark(
          primary: const Color(0xFF7DD87A),
          secondary: const Color(0xFF6EC6E6),
          surface: const Color(0xFF1A2E1C),
          onPrimary: const Color(0xFF0F1B12),
          onSurface: Colors.white,
        ),
        appBarTheme: const AppBarTheme(
          backgroundColor: Color(0xFF0F1B12),
          foregroundColor: Colors.white,
          elevation: 0,
          centerTitle: false,
        ),
        textTheme: const TextTheme(
          bodyMedium: TextStyle(color: Colors.white),
          bodySmall: TextStyle(color: Colors.white70),
        ),
        useMaterial3: true,
      ),
      home: const HomeScreen(),
    );
  }
}
