from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import random

app = FastAPI(title="Travel Safety AI API")

# Configure CORS to allow requests from the Flutter app
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Data Model for the incoming request from the Flutter app
class AssessmentRequest(BaseModel):
    location: str
    emergency_contacts_updated: bool
    weather_analyzed: bool

# API Endpoint to calculate the risk score
@app.post("/api/calculate-risk")
async def calculate_risk(data: AssessmentRequest):
    # Generate a random base risk between 40% and 90% 
    # (Placeholder until the actual AI/ML model like ResNet/CNN is integrated)
    base_risk = random.randint(40, 90)
    
    # Reduce risk score if the user has completed safety checklist items
    if data.emergency_contacts_updated:
        base_risk -= 15
    if data.weather_analyzed:
        base_risk -= 20
        
    # Ensure the risk score doesn't drop below 0
    final_risk = max(0, base_risk)
        
    # Determine the risk level based on the final calculated risk score
    risk_level = "Low Risk"
    if final_risk >= 60:
        risk_level = "High Risk"
    elif final_risk >= 30:
        risk_level = "Moderate Risk"
        
    # The data.location will now contain either the typed city or the GPS Lat/Lng coordinates
    return {
        "risk_score": final_risk,
        "risk_level": risk_level,
        "message": f"Assessment for '{data.location}' completed successfully."
    }

# Root endpoint to check if the server is running successfully
@app.get("/")
async def root():
    return {"message": "Travel Safety AI Backend is Running!"}