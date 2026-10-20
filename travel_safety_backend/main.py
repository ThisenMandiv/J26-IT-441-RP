from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pickle
import pandas as pd

app = FastAPI(title="Travel Safety AI API")

# Configure CORS to allow requests from the Flutter app
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load the newly trained real AI Model
with open("travel_safety_model.pkl", "rb") as file:
    model = pickle.load(file)

# Data Model for the incoming request from the Flutter app 
# (Keeping the original schema to prevent 422 Unprocessable Entity errors)
class AssessmentRequest(BaseModel):
    location: str
    emergency_contacts_updated: bool
    weather_analyzed: bool
    time_of_day: str 

# API Endpoint to calculate the risk score
@app.post("/api/calculate-risk")
async def calculate_risk(data: AssessmentRequest):
    # 1. Extract Latitude and Longitude from the location string (fallback to default coordinates)
    lat = 6.9271 
    lng = 79.8612
    try:
        if "," in data.location:
            parts = data.location.split(",")
            lat = float(parts[0].strip())
            lng = float(parts[1].strip())
    except:
        pass
        
    # 2. Convert Text and Boolean data into numerical formats (1s and 0s) for the AI Model
    is_night = 1 if data.time_of_day.lower() == "night" else 0
    weather_analyzed_int = 1 if data.weather_analyzed else 0
    emergency_contacts_int = 1 if data.emergency_contacts_updated else 0

    # 3. Create a pandas DataFrame to match the AI Model's expected input features
    input_df = pd.DataFrame([{
        "latitude": lat,
        "longitude": lng,
        "is_night": is_night,
        "weather_analyzed": weather_analyzed_int,
        "emergency_contacts": emergency_contacts_int
    }])
    
    # 4. Get the Risk Score prediction from the AI Model
    prediction = model.predict(input_df)
    final_risk = max(0, min(100, round(prediction[0], 2))) # Ensure the score stays between 0 and 100
    
    # 5. Determine the Risk Level based on the calculated risk score
    risk_level = "Low Risk"
    if final_risk >= 60:
        risk_level = "High Risk"
    elif final_risk >= 30:
        risk_level = "Moderate Risk"
        
    return {
        "risk_score": final_risk,
        "risk_level": risk_level,
        "message": f"AI Assessment for '{data.location}' completed successfully."
    }

# Root endpoint to check if the server is running successfully
@app.get("/")
async def root():
    return {"message": "Travel Safety AI Backend is Running with Real ML Model!"}