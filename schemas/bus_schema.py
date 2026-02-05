from typing import List, Optional
from pydantic import BaseModel, Field

# --- Input Schemas ---
class Location(BaseModel):
    # ge = Greater than or Equal to | le = Less than or Equal to
    lat: float = Field(..., ge=-90, le=90, description="Latitude must be between -90 and 90")
    lng: float = Field(..., ge=-180, le=180, description="Longitude must be between -180 and 180")

class RouteRequest(BaseModel):
    from_location: Location
    to_location: Location

# --- Output Schemas (Response) ---
class StopInfo(BaseModel):
    id: int
    name: str
    lat: float
    lng: float
    
    class Config:
        from_attributes = True

class RouteSummary(BaseModel):
    name: str
    bus_type: str
    ticket_price: float

class DirectionSummary(BaseModel):
    direction: str
    sub_name: Optional[str]
    segment_distance_km: float
    segment_duration_mins: float

class TransferInfo(BaseModel):
    from_stop: StopInfo
    to_stop: StopInfo
    walk_dist_km: float
    walk_duration_mins: float
    is_same_stop: bool

class RouteSegment(BaseModel):
    # Added the transfer field here
    transfer_from_previous: Optional[TransferInfo] = None 
    route: RouteSummary
    direction: DirectionSummary
    stops: List[StopInfo]

class TripSummary(BaseModel):
    total_duration_mins: float
    total_cost: float
    total_walking_distance_km: float
    walking_duration_mins: float
    walking_distance_to_start_km: float
    walking_distance_to_end_km: float
    
    from_stop: StopInfo 
    to_stop: StopInfo

    class Config:
        from_attributes = True

class FindRouteResponse(BaseModel):
    summary: TripSummary
    route_segments: List[RouteSegment]

    class Config:
        from_attributes = True