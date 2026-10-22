// Widget tests for Tapro Path.
//
// Pumps the real TaproPathApp root widget and verifies that the home screen
// renders the expected title and section heading. The trail list is loaded
// from a Flutter asset (assets/data/trails.json) which is available in tests
// because the asset bundle is included in the test environment.

import 'package:flutter_test/flutter_test.dart';

import 'package:tapropath/main.dart';

void main() {
  testWidgets('Home screen renders app title and trail list heading',
      (WidgetTester tester) async {
    // Build the Tapro Path app.
    await tester.pumpWidget(const TaproPathApp());

    // Allow async FutureBuilder (trail asset loading) to complete.
    await tester.pumpAndSettle();

    // The SliverAppBar hero displays the app name.
    expect(find.text('Tapro Path'), findsWidgets);

    // The home screen shows the "Available Trails" section heading.
    expect(find.text('Available Trails'), findsOneWidget);
  });
}
