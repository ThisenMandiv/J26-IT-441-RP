
from pathlib import Path
import xml.etree.ElementTree as ET
import math
import json

# Folder containing your five GPX files
GPX_FOLDER = Path("research_data/gpx")
OUTPUT_FILE = Path("research_data/gpx_analysis.json")


def haversine_m(lat1, lon1, lat2, lon2):
    """Calculate the distance between two GPS points in metres."""
    earth_radius = 6_371_000

    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(p1) * math.cos(p2)
        * math.sin(dlon / 2) ** 2
    )

    return 2 * earth_radius * math.asin(
        min(1.0, math.sqrt(a))
    )


def analyze_file(path):
    root = ET.parse(path).getroot()

    # GPX files commonly use a namespace.
    points = []

    for element in root.iter():
        if element.tag.split("}")[-1] not in ("trkpt", "rtept"):
            continue

        lat = element.get("lat")
        lon = element.get("lon")

        if lat is None or lon is None:
            continue

        lat = float(lat)
        lon = float(lon)

        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue

        timestamp = None

        for child in element:
            if child.tag.split("}")[-1] == "time":
                timestamp = child.text
                break

        points.append({
            "lat": lat,
            "lng": lon,
            "timestamp": timestamp,
        })

    total_distance = 0.0

    for previous, current in zip(points, points[1:]):
        total_distance += haversine_m(
            previous["lat"], previous["lng"],
            current["lat"], current["lng"]
        )

    return {
        "file": path.name,
        "point_count": len(points),
        "distance_km": round(total_distance / 1000, 3),
        "has_timestamps": any(
            p["timestamp"] for p in points
        ),
        "start": points[0] if points else None,
        "end": points[-1] if points else None,
        "points": points,
    }


def main():
    if not GPX_FOLDER.exists():
        print(f"Folder not found: {GPX_FOLDER.resolve()}")
        print("Create research_data/gpx and put your GPX files there.")
        return

    files = sorted(GPX_FOLDER.glob("*.gpx"))

    if not files:
        print("No .gpx files found in:", GPX_FOLDER.resolve())
        return

    results = []

    for path in files:
        try:
            result = analyze_file(path)
            results.append(result)

            print(f"\nFile: {result['file']}")
            print(f"GPS points: {result['point_count']}")
            print(f"Recorded distance: {result['distance_km']} km")
            print(f"Timestamps available: {result['has_timestamps']}")

        except (ET.ParseError, OSError, ValueError) as error:
            print(f"\nCould not process {path.name}: {error}")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(results, indent=2),
        encoding="utf-8"
    )

    print(f"\nAnalysis saved to: {OUTPUT_FILE.resolve()}")


if __name__ == "__main__":
    main()
