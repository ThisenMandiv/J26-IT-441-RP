import 'package:flutter_test/flutter_test.dart';
import 'package:tapropath/models/trail_model.dart';
import 'package:tapropath/services/route_service.dart';

void main() {
  group('RouteService - Compass Directions', () {
    test('maps standard degrees to 16-point cardinal compass string', () {
      expect(RouteService.compassDirection(0.0), 'N');
      expect(RouteService.compassDirection(360.0), 'N');
      expect(RouteService.compassDirection(22.5), 'NNE');
      expect(RouteService.compassDirection(45.0), 'NE');
      expect(RouteService.compassDirection(90.0), 'E');
      expect(RouteService.compassDirection(135.0), 'SE');
      expect(RouteService.compassDirection(180.0), 'S');
      expect(RouteService.compassDirection(225.0), 'SW');
      expect(RouteService.compassDirection(270.0), 'W');
      expect(RouteService.compassDirection(292.5), 'WNW');
      expect(RouteService.compassDirection(315.0), 'NW');
      expect(RouteService.compassDirection(350.0), 'N');
    });

    test('handles negative and wrap-around angles', () {
      expect(RouteService.compassDirection(-90.0), 'W');
      expect(RouteService.compassDirection(450.0), 'E');
    });
  });

  group('RouteService - Nearest Point on Segment & Return Bearing', () {
    // Vertical North-South trail segment:
    // a = (7.100, 80.500) -> b = (7.110, 80.500)
    const p1 = LatLng(lat: 7.100, lng: 80.500);
    const p2 = LatLng(lat: 7.110, lng: 80.500);
    final route = [p1, p2];

    test('projects hiker off to the East onto segment midpoint with West return bearing', () {
      // Hiker is at lat 7.105, lng 80.503 (approx 330 m directly East of the segment midpoint)
      const hikerPos = LatLng(lat: 7.105, lng: 80.503);

      final result = RouteService.distanceToNearestRouteSegment(hikerPos, route);

      expect(result.nearestSegmentIndex, 0);
      expect(result.nearestPoint, isNotNull);

      // Projected nearest point should be close to (7.105, 80.500)
      expect(result.nearestPoint!.lat, closeTo(7.105, 0.0001));
      expect(result.nearestPoint!.lng, closeTo(80.500, 0.0001));

      // Distance should be ~330 m
      expect(result.distanceMetres, greaterThan(300));
      expect(result.distanceMetres, lessThan(360));

      // Hiker is East of trail, so return bearing to trail must point West (around 270°)
      expect(result.returnBearingDegrees, isNotNull);
      expect(result.returnBearingDegrees!, closeTo(270.0, 5.0));
      expect(result.returnCompassDirection, 'W');

      // Exceeds 50m threshold -> isOffRoute true
      expect(result.isOffRoute(thresholdMetres: 50), isTrue);
    });

    test('reports on-route state when within threshold', () {
      // Hiker is within 10 m of the route
      const hikerOnRoute = LatLng(lat: 7.105, lng: 80.50005);

      final result = RouteService.distanceToNearestRouteSegment(hikerOnRoute, route);

      expect(result.distanceMetres, lessThan(20));
      expect(result.isOffRoute(thresholdMetres: 50), isFalse);
    });

    test('clamps closest point to segment endpoints when perpendicular projection falls outside', () {
      // Hiker is south of the segment start (lat 7.095, lng 80.500)
      const hikerSouth = LatLng(lat: 7.095, lng: 80.500);

      final result = RouteService.distanceToNearestRouteSegment(hikerSouth, route);

      expect(result.nearestPoint!.lat, closeTo(p1.lat, 0.00001));
      expect(result.nearestPoint!.lng, closeTo(p1.lng, 0.00001));

      // Return bearing should point North (0°)
      expect(result.returnBearingDegrees!, closeTo(0.0, 2.0));
      expect(result.returnCompassDirection, 'N');
    });

    test('handles single-point route gracefully', () {
      final singlePointRoute = [const LatLng(lat: 7.0, lng: 80.0)];
      const hiker = LatLng(lat: 7.01, lng: 80.0);

      final result = RouteService.distanceToNearestRouteSegment(hiker, singlePointRoute);

      expect(result.nearestSegmentIndex, 0);
      expect(result.nearestPoint, singlePointRoute.first);
      // Hiker is North of point, heading back South (180°)
      expect(result.returnBearingDegrees!, closeTo(180.0, 2.0));
      expect(result.returnCompassDirection, 'S');
    });
  });
}
