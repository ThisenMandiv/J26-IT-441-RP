from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import torch
import torch.nn.functional as F
from torch_geometric.nn import GCNConv
from torch_geometric.data import Data
import requests
from datetime import datetime

app = FastAPI(title="Travel Safety AI - Dynamic Destination & Explainable Risk Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SpatialSafetyGNN(torch.nn.Module):
    def __init__(self, num_node_features, num_classes):
        super(SpatialSafetyGNN, self).__init__()
        self.conv1 = GCNConv(num_node_features, 16)
        self.conv2 = GCNConv(16, num_classes)

    def forward(self, data):
        x, edge_index = data.x, data.edge_index
        x = self.conv1(x, edge_index)
        x = F.relu(x)
        x = self.conv2(x, edge_index)
        return F.log_softmax(x, dim=1)

model = SpatialSafetyGNN(num_node_features=3, num_classes=3)
try:
    model.load_state_dict(torch.load("travel_safety_gnn_model.pth", weights_only=True))
    model.eval()
except Exception as e:
    print(f"Error loading model: {e}")

class AssessmentRequest(BaseModel):
    location: str # User can type any city/destination name or lat,lng coordinates
    emergency_contacts_updated: bool
    weather_analyzed: bool
    time_of_day: str 

# Helper: Dynamically Resolve any Destination Name or Coordinates using OpenStreetMap Geocoding API
def resolve_location(loc_str: str):
    loc_clean = loc_str.strip()
    
    # 1. Try parsing as comma-separated coordinates (lat, lng) first
    try:
        if "," in loc_clean:
            parts = loc_clean.split(",")
            return float(parts[0].strip()), float(parts[1].strip())
    except:
        pass
        
    # 2. Use OpenStreetMap Nominatim API to dynamically resolve any city or location name typed by the user
    try:
        url = f"https://nominatim.openstreetmap.org/search?q={loc_clean}, Sri Lanka&format=json&limit=1"
        headers = {'User-Agent': 'TravelSafetyAI/1.0'}
        response = requests.get(url, headers=headers, timeout=5).json()
        if response and len(response) > 0:
            lat = float(response[0]['lat'])
            lng = float(response[0]['lon'])
            return lat, lng
    except Exception as e:
        print(f"Geocoding API error: {e}")
        
    # 3. Fallback static dictionary if API fails or offline
    destinations = {
        "nuwara eliya": (6.9497, 80.7891),
        "kandy": (7.2906, 80.6337),
        "ella": (6.8667, 81.0466),
        "bopath ella": (6.7583, 80.3550),
        "galle": (6.0535, 80.2210),
        "colombo": (6.9271, 79.8612),
        "malabe": (6.9155, 79.9739),
        "sigiriya": (7.9570, 80.7603),
        "trincomalee": (8.5874, 81.2152),
        "arugam bay": (6.8456, 81.8364),
        "mirissa": (5.9482, 80.4553),
        "gregory lake": (6.9580, 80.7770)
    }
    
    for key, coords in destinations.items():
        if key in loc_clean.lower():
            return coords[0], coords[1]
            
    # Default fallback to Malabe if nothing matches
    return 6.9155, 79.9739

# 1. Fetch Real Weather & Temperature for Destination
def get_real_weather(lat, lng):
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lng}&current_weather=true"
        response = requests.get(url, timeout=5).json()
        current = response.get("current_weather", {})
        weather_code = current.get("weathercode", 0)
        temp = current.get("temperature", 28.0)
        
        if weather_code >= 50: return 0.8, weather_code, temp
        elif weather_code >= 45: return 0.4, weather_code, temp
        else: return 0.1, weather_code, temp
    except:
        return 0.3, 0, 28.0

def get_location_risk(lat, lng):
    if 6.90 <= lat <= 6.93 and 79.95 <= lng <= 79.99:
        return 0.1 
    else:
        return 0.4 

def is_deep_water_zone(location_str, lat, lng):
    water_keywords = ['lake', 'waterfall', 'beach', 'river', 'sea', 'oya', 'ganga', 'pool', 'fall', 'ella', 'wawa', 'wewa', 'dam', 'bopath']
    if any(k in location_str.lower() for k in water_keywords):
        return True
    if (6.88 <= lat <= 6.91 and 79.90 <= lng <= 79.93) or (6.95 <= lat <= 6.97 and 80.76 <= lng <= 80.79) or (6.75 <= lat <= 6.77 and 80.35 <= lng <= 80.37):
        return True
    return False

# 2. Temporal Forecasting Algorithm
def temporal_forecasting_algorithm(current_gnn_risk, lat, lng, time_of_day):
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lng}&hourly=weathercode,temperature_2m&forecast_days=1"
        response = requests.get(url, timeout=5).json()
        
        current_hour = datetime.now().hour
        hourly = response.get("hourly", {})
        upcoming_weather = hourly.get("weathercode", [])[current_hour+1 : current_hour+4]
        upcoming_temps = hourly.get("temperature_2m", [])[current_hour+1 : current_hour+4]
        
        risk_modifier = 0
        for code in upcoming_weather:
            if code >= 50: 
                risk_modifier += 15.0
                break
            elif code >= 45: 
                risk_modifier += 5.0
                
        if time_of_day.lower() == "night" or current_hour >= 18:
            risk_modifier += 10.0
            
        forecasted_risk = min(100.0, round(current_gnn_risk + risk_modifier, 2))
        return forecasted_risk, upcoming_weather, upcoming_temps
        
    except Exception:
        return current_gnn_risk, [], []

# 3. Explainable AI (XAI) Causes & Recommendations
def analyze_causes_and_recommendations(location_str, lat, lng, current_code, upcoming_codes, temp, upcoming_temps, time_of_day, contacts_updated):
    causes = []
    recommendations = []
    risk_boost = 0.0

    if current_code >= 50 or any(c >= 50 for c in upcoming_codes):
        causes.append("Heavy Rain or Storm Conditions at Destination")
        recommendations.append("🌧️ Rain is expected at your destination. Carry a raincoat or umbrella and watch out for slippery roads.")
    elif current_code >= 45 or any(c >= 45 for c in upcoming_codes):
        causes.append("Foggy Weather / Low Visibility at Destination")
        recommendations.append("🌫️ Visibility may drop at destination. Use vehicle fog lights and drive carefully.")

    min_upcoming_temp = min(upcoming_temps) if upcoming_temps else temp
    effective_temp = min(temp, min_upcoming_temp)
    if effective_temp <= 22.0 or "nuwara eliya" in location_str.lower() or "ella" in location_str.lower():
        causes.append(f"Cold Weather Conditions at Destination ({effective_temp}°C)")
        recommendations.append("🧥 This destination is cold. Pack a warm jersey or heavy jacket to stay protected.")
        risk_boost += 10.0

    if is_deep_water_zone(location_str, lat, lng):
        causes.append("Proximity to Deep Water Body / Bathing Spot at Destination")
        recommendations.append("🛟 Destination has water hazards. Always wear a certified life jacket and avoid swimming in unauthorized zones.")
        risk_boost += 20.0

    if time_of_day.lower() == "night" or datetime.now().hour >= 18:
        causes.append("Night-Time Arrival & Low Ambient Lighting")
        recommendations.append("🔦 Arriving at night. Avoid unlit routes and keep a flashlight ready.")

    if not contacts_updated:
        causes.append("Unverified Emergency Contact Information")
        recommendations.append("📱 Update your emergency contacts in the app before starting your trip.")

    if not causes:
        causes.append("Normal & Safe Environmental Conditions")
        recommendations.append("✅ Destination conditions are clear. Have a safe and pleasant journey!")

    return causes, recommendations, risk_boost

@app.post("/api/calculate-risk")
async def calculate_risk(data: AssessmentRequest):
    # Resolve destination name dynamically via Geocoding API or coordinates
    lat, lng = resolve_location(data.location)

    bad_weather_risk, current_weather_code, temp = get_real_weather(lat, lng) if data.weather_analyzed else (0.5, 0, 28.0)
    crime_rate = get_location_risk(lat, lng)
    poor_lighting = 0.7 if data.time_of_day.lower() == "night" else 0.1

    if not data.emergency_contacts_updated:
        crime_rate = min(1.0, crime_rate + 0.2)

    # GNN Model Execution
    x = torch.tensor([
        [crime_rate, poor_lighting, bad_weather_risk],
        [0.3, 0.2, 0.4], [0.1, 0.5, 0.2], 
        [0.6, 0.1, 0.1], [0.4, 0.3, 0.3]
    ], dtype=torch.float)

    edge_index = torch.tensor([[0, 1, 1, 3, 0, 2, 2, 4, 1, 4], [1, 0, 3, 1, 2, 0, 4, 2, 4, 1]], dtype=torch.long)
    graph_data = Data(x=x, edge_index=edge_index)

    with torch.no_grad():
        out = model(graph_data)
        probabilities = torch.exp(out[0]) 

    p_moderate = probabilities[1].item()
    p_high = probabilities[2].item()
    gnn_base_risk = max(0, min(100, round((p_moderate * 50) + (p_high * 100), 2)))

    # Temporal Forecasting
    forecasted_risk, upcoming_weather, upcoming_temps = temporal_forecasting_algorithm(gnn_base_risk, lat, lng, data.time_of_day)

    # Causes & Recommendations
    causes, recommendations, hazard_boost = analyze_causes_and_recommendations(
        location_str=data.location,
        lat=lat,
        lng=lng,
        current_code=current_weather_code,
        upcoming_codes=upcoming_weather,
        temp=temp,
        upcoming_temps=upcoming_temps,
        time_of_day=data.time_of_day,
        contacts_updated=data.emergency_contacts_updated
    )

    final_risk = min(100.0, round(forecasted_risk + hazard_boost, 2))

    risk_level = "Low Risk"
    if final_risk >= 60:
        risk_level = "High Risk"
    elif final_risk >= 30:
        risk_level = "Moderate Risk"

    reasons_text = " | ".join(causes)
    recs_text = " ".join(recommendations)
    combined_message = f"Destination: {data.location}\nReason: {reasons_text}\n\nRecommendation: {recs_text}"
        
    return {
        "risk_score": final_risk,
        "risk_level": risk_level,
        "gnn_base_score": gnn_base_risk,
        "message": combined_message,
        "risk_causes": causes,
        "recommendations": recommendations
    }

@app.get("/")
async def root():
    return {"message": "Travel Safety AI Backend is Running!"}