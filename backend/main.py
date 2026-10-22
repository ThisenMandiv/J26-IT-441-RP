
import json
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware

from fastapi import FastAPI, HTTPException

app = FastAPI(
    title="Tapro Path API",
    description="Backend API for offline hiking navigation",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_FILE = (
    Path(__file__).resolve().parent.parent
    / "assets"
    / "data"
    / "recorded_trails.json"
)


def load_trails():
    if not DATA_FILE.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Trail dataset not found: {DATA_FILE}",
        )

    try:
        with DATA_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=500,
            detail=f"Could not read trail dataset: {error}",
        ) from error

    # Accept either a JSON list or an object containing a list.
    if isinstance(data, dict):
        data = data.get("trails", data.get("records", []))

    if not isinstance(data, list):
        raise HTTPException(
            status_code=500,
            detail="Trail dataset must contain a list of records.",
        )

    return data


@app.get("/")
def home():
    return {"message": "Tapro Path backend is working!"}


@app.get("/api/health")
def health_check():
    return {"status": "healthy"}


@app.get("/api/trails")
def get_trails():
    trails = load_trails()

    # Return trail summaries without all GPS points.
    summaries = []

    for trail in trails:
        summaries.append({
            key: trail[key]
            for key in (
                "id",
                "name",
                "mountain",
                "recordingType",
                "pointCount",
                "recordedDistanceKm",
                "hasTimestamps",
                "verifiedForNavigation",
            )
            if key in trail
        })

    return {
        "count": len(summaries),
        "trails": summaries,
    }


@app.get("/api/trails/{trail_id}")
def get_trail(trail_id: str):
    trails = load_trails()

    for trail in trails:
        if str(trail.get("id")) == trail_id:
            return trail

    raise HTTPException(
        status_code=404,
        detail=f"Trail '{trail_id}' was not found.",
    )
