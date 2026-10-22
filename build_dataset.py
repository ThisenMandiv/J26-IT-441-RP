
import json
from pathlib import Path
from datetime import datetime, timezone

PROJECT = Path(__file__).resolve().parent
INPUT = PROJECT / "research_data" / "gpx_analysis.json"
OUTPUT = PROJECT / "assets" / "data" / "recorded_trails.json"

MOUNTAINS = {
    "track_011.gpx": ("kabaragala_01", "Kabaragala"),
    "track_012.gpx": ("kabaragala_02", "Kabaragala"),
    "track_013.gpx": ("kabaragala_03", "Kabaragala"),
    "track_021.gpx": ("maragala_01", "Maragala"),
    "track_022.gpx": ("maragala_02", "Maragala"),
}


def main():
    if not INPUT.exists():
        print(f"Input file not found: {INPUT}")
        return

    analysis = json.loads(INPUT.read_text(encoding="utf-8"))
    trails = []

    for record in analysis:
        filename = record["file"]

        if filename not in MOUNTAINS:
            print(f"Skipping unmapped file: {filename}")
            continue

        trail_id, mountain = MOUNTAINS[filename]
        points = record.get("points", [])

        # Remove consecutive duplicate coordinates only.
        clean_points = []
        for point in points:
            lat = point.get("lat")
            lng = point.get("lng")

            if lat is None or lng is None:
                continue

            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                continue

            if clean_points and (
                clean_points[-1]["lat"] == lat
                and clean_points[-1]["lng"] == lng
            ):
                continue

            clean_points.append({
                "lat": lat,
                "lng": lng,
                "timestamp": point.get("timestamp"),
            })

        if len(clean_points) < 2:
            print(f"Skipping {filename}: fewer than 2 valid points")
            continue

        trails.append({
            "id": trail_id,
            "name": f"{mountain} Recorded Track {trail_id[-2:]}",
            "mountain": mountain,
            "sourceFile": filename,
            "source": "Organic Maps GPX recording",
            "recordingType": "recorded_gps_track",
            "pointCount": len(clean_points),
            "recordedDistanceKm": record.get("distance_km"),
            "hasTimestamps": any(
                p["timestamp"] for p in clean_points
            ),
            "waypoints": clean_points,
            "verifiedForNavigation": False,
        })

    dataset = {
        "datasetName": "Tapro Path Recorded Hiking Tracks",
        "datasetVersion": "1.0",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "description": (
            "Preliminary GPS recordings from Organic Maps. "
            "Tracks are not verified for safe navigation."
        ),
        "trackCount": len(trails),
        "trails": trails,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(dataset, indent=2),
        encoding="utf-8",
    )

    print(f"Dataset created: {OUTPUT}")
    print(f"Tracks included: {len(trails)}")
    print(f"Total GPS points: {sum(t['pointCount'] for t in trails)}")

    for trail in trails:
        print(
            f"{trail['mountain']}: {trail['sourceFile']} - "
            f"{trail['pointCount']} points"
        )


if __name__ == "__main__":
    main()
