from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import random

app = FastAPI(title="Travel Safety AI API")

# Configure CORS to allow requests from the Flutter Web app
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
    # Generate a random base risk between 40% and 70% 
    # (This is a placeholder until we connect the actual AI/ML model)
    base_risk = random.randint(40, 70)
    
    # Reduce risk score if the user has completed safety checklist items
    if data.emergency_contacts_updated:
        base_risk -= 15
    if data.weather_analyzed:
        base_risk -= 20
        
    # Determine the risk level based on the final calculated risk score
    risk_level = "Low Risk"
    if base_risk >= 50:
        risk_level = "High Risk"
    elif base_risk >= 30:
        risk_level = "Moderate Risk"
        
    return {
        "risk_score": base_risk,
        "risk_level": risk_level,
        "message": f"Risk assessment for '{data.location}' was successful."
    }

# Root endpoint to check if the server is running successfully
@app.get("/")
async def root():
    return {"message": "Travel Safety AI Backend is Running!"}