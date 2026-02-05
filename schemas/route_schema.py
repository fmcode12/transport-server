from pydantic import BaseModel, Field
from typing import List, Optional

# ====== Stops Schemas ======
class SingleStopCreate(BaseModel):
    name: str
    lat: float
    lng: float

class StopCreate(BaseModel):
    stops: List[SingleStopCreate]

class StopUpdate(BaseModel):
    id: int
    name: str
    lat: float
    lng: float

# ====== RouteStop Schemas ======
class RouteStopBase(BaseModel):
    stop_id: int
    order: int
    distance_from_start: Optional[float] = None

    class Config:
        from_attributes = True

# ====== Direction Schemas ======
class DirectionCreate(BaseModel):
    direction: str
    sub_name: Optional[str] = None
    gpx: Optional[str] = None
    stops: List[RouteStopBase] # Changed to use RouteStopBase
    distance: Optional[float] = None

class DirectionUpdate(BaseModel):
    direction: str
    sub_name: Optional[str] = None
    gpx: Optional[str] = None
    stops: List[RouteStopBase]
    distance: Optional[float] = None

# ====== Route Schemas ======
class RouteCreate(BaseModel):
    name: str
    bus_type: Optional[str]
    active_vehicles: Optional[int]
    total_vehicles: Optional[int]
    total_distance: Optional[float]
    ticket_price: Optional[int]
    directions: DirectionCreate

class RouteUpdate(BaseModel):
    name: str
    bus_type: Optional[str]
    active_vehicles: Optional[int]
    total_vehicles: Optional[int]
    total_distance: Optional[float]
    ticket_price: Optional[int]
    directions: DirectionUpdate

# ====== Output Schemas ======
class StopOut(BaseModel):
    id: int
    name: str
    lat: float
    lng: float
    
    class Config:
        from_attributes = True

class DirectionOut(BaseModel):
    id: int
    direction: str
    sub_name: Optional[str]
    gpx_path: Optional[str] # Match your model field name
    stops: List[StopOut] # This works because of your @property in models.py
    distance: Optional[float]
    
    
    class Config:
        from_attributes = True

class RouteOut(BaseModel):
    id: int
    name: str
    bus_type: Optional[str]
    active_vehicles: Optional[int]
    total_vehicles: Optional[int]
    total_distance: Optional[float]
    ticket_price: Optional[int]
    directions: List[DirectionOut]

    class Config:
        from_attributes = True