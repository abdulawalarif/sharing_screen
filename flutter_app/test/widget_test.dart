import 'package:flutter_test/flutter_test.dart';

import 'package:sharing_screen/main.dart';

void main() {
  testWidgets('App loads connect screen', (WidgetTester tester) async {
    await tester.pumpWidget(const ScreenShareApp());
    expect(find.text('Screen Share'), findsOneWidget);
    expect(find.text('Connect'), findsOneWidget);
  });
}
