from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List
from db.database import get_db
from db.models import Route, Direction, Stop, RouteStop
from db.supabase_client import supabase
from schemas.route_schema import RouteCreate, RouteOut, StopOut, StopCreate, StopUpdate, RouteUpdate
from sqlalchemy import func, update

from dependencies import validate_admin

router = APIRouter(prefix="/api", dependencies=[Depends(validate_admin)])

# --- STORAGE HELPERS ---
def save_gpx_to_supabase(route_id: int, direction_id: int, gpx_content: str):
    """Uses IDs for the filename to ensure it is always valid and safe."""
    if not gpx_content:
        return None
    # Filename will look like: route_2_dir_5.gpx
    file_name = f"route_{route_id}_dir_{direction_id}.gpx"
    content_bytes = gpx_content.encode("utf-8")
    supabase.storage.from_("gpx_files").upload(
        path=file_name,
        file=content_bytes,
        file_options={"content-type": "application/gpx+xml", "upsert": "true"}
    ) 
    return supabase.storage.from_("gpx_files").get_public_url(file_name)

def delete_gpx_from_supabase(file_url: str):
    """Extracts filename from URL and deletes from storage"""
    if not file_url:
        return
    try:
        # URL usually ends in /gpx_files/filename.gpx
        file_name = file_url.split("/")[-1]
        supabase.storage.from_("gpx_files").remove([file_name])
    except Exception as e:
        print(f"⚠️ Storage delete error: {e}")

# --- STOP ENDPOINTS ---
@router.get("/stop", response_model=List[StopOut])
def get_stops(db: Session = Depends(get_db), is_admin: bool = Depends(validate_admin)):
    stops = db.query(Stop).all()
    if not stops:
        raise HTTPException(status_code=404, detail="No stops")
    return stops

@router.post("/stop", response_model=List[StopOut])
def create_stops(data: StopCreate, db: Session = Depends(get_db)):
    # Fix: Access pydantic attribute directly
    stops_data = data.stops 
    new_stops = []
    for stop_item in stops_data:
        # Create the stop object
        new_stop = Stop(
            name=stop_item.name,
            lat=stop_item.lat,
            lng=stop_item.lng,
            # ✅ Sync the PostGIS geography column!
            location=func.ST_GeographyFromText(f'POINT({stop_item.lng} {stop_item.lat})')
        )
        db.add(new_stop)
        new_stops.append(new_stop)
    db.commit()
    for s in new_stops:
        db.refresh(s)
    return new_stops

@router.put("/stop", response_model=StopOut)
def edit_stop(stop_data: StopUpdate, db: Session = Depends(get_db)):   
    query = db.query(Stop).filter(Stop.id == stop_data.id)
    stop_exists = query.first()
    if not stop_exists:
        raise HTTPException(status_code=404, detail="Stop not found")
    query.update({
        "name": stop_data.name,
        "lat": float(stop_data.lat),
        "lng": float(stop_data.lng)
    }, synchronize_session="fetch")
    db.commit()
    db.expire_all()
    updated_stop = db.query(Stop).filter(Stop.id == stop_data.id).first()
    return updated_stop

@router.delete("/stop/{stop_id}")
def delete_stop(stop_id: int, db: Session = Depends(get_db)):
    stop = db.query(Stop).filter(Stop.id == stop_id).first()
    if not stop:
        raise HTTPException(status_code=404, detail="The stop does not exist!")

    linked = db.query(RouteStop).filter(RouteStop.stop_id == stop_id).first()
    if linked:
        raise HTTPException(
            status_code=400,
            detail="Stop is used in a direction and cannot be deleted."
        )

    db.delete(stop)
    db.commit()

    return {"message": "Stop deleted successfully."}

# --- ROUTE ENDPOINTS ---
@router.get("/route", response_model=List[RouteOut])
def get_routes(db: Session = Depends(get_db)):
    routes = (
        db.query(Route)
        .options(
            joinedload(Route.directions)
            .joinedload(Direction.route_stops)
            .joinedload(RouteStop.stop)
        )
        .all()
    )
    return routes

@router.post("/route", response_model=RouteOut)
def create_route(route_data: RouteCreate, db: Session = Depends(get_db)):
    # 1. Handle Route Existence
    db_route = db.query(Route).filter(Route.name == route_data.name).first()
    dir_data = route_data.directions
    if db_route:
        db_direction = (
            db.query(Direction)
            .filter(
                Direction.route_id == db_route.id,
                Direction.direction == dir_data.direction,
                Direction.sub_name == dir_data.sub_name,
            )
            .first()
        )
        if db_direction:
            raise HTTPException(status_code=400, detail="Route direction already exists")
    else:
        db_route = Route(
            name=route_data.name,
            bus_type=route_data.bus_type,
            ticket_price=route_data.ticket_price,
            active_vehicles=route_data.active_vehicles,
            total_vehicles=route_data.total_vehicles,
            total_distance=route_data.total_distance,
        )
        db.add(db_route)
        db.commit()
        db.refresh(db_route)

    # 2. Create Direction first (with gpx_path=None or empty)
    db_direction = Direction(
        direction=dir_data.direction,
        sub_name=dir_data.sub_name,
        gpx=dir_data.gpx,
        gpx_path=None,  # Temporarily None because we need db_direction.id first
        distance=dir_data.distance,
        route_id=db_route.id
    )
    db.add(db_direction)
    db.commit()
    db.refresh(db_direction)

    # 3. NOW call the storage function (Now that we have both IDs)
    storage_url = save_gpx_to_supabase(
        db_route.id, db_direction.id, dir_data.gpx
    )
    # 4. Update the direction with the actual URL
    db_direction.gpx_path = storage_url
    db.commit() 
    # 5. Insert ordered stops
    for index, stop in enumerate(dir_data.stops):
        db_route_stop = RouteStop(
            direction_id=db_direction.id,
            stop_id=stop.stop_id,
            order=index + 1,
            distance_from_start=stop.distance_from_start
        )
        db.add(db_route_stop)
    
    db.commit()
    db.refresh(db_route)

    return db_route

@router.put("/route/{route_id}/{direction_id}", response_model=RouteOut)
def update_route(route_id: int, direction_id: int, route_data: RouteUpdate, db: Session = Depends(get_db)):
    # 1. Find the existing route and direction
    db_route = db.query(Route).filter(Route.id == route_id).first()
    if not db_route:
        raise HTTPException(status_code=404, detail="Route not found")

    db_direction = db.query(Direction).filter(
        Direction.id == direction_id, 
        Direction.route_id == route_id
    ).first()
    
    if not db_direction:
        raise HTTPException(status_code=404, detail="Direction not found")
    # 2. DELETE OLD GPX IF FILENAME MIGHT CHANGE
    # If the name or direction changed, the old URL is now invalid/orphaned
    if db_direction.gpx_path:
        delete_gpx_from_supabase(db_direction.gpx_path)
    # 3. Update Route Basic Info
    db_route.name = route_data.name
    db_route.bus_type = route_data.bus_type
    db_route.ticket_price = route_data.ticket_price
    db_route.active_vehicles = route_data.active_vehicles
    db_route.total_vehicles = route_data.total_vehicles
    db_route.total_distance = route_data.total_distance
    
    dir_data = route_data.directions
    # 4. Save New GPX
    storage_url = save_gpx_to_supabase(
    route_id, direction_id, dir_data.gpx
    )
    # 5. Update Direction Info
    db_direction.direction = dir_data.direction
    db_direction.sub_name = dir_data.sub_name
    db_direction.gpx = dir_data.gpx
    db_direction.gpx_path = storage_url
    db_direction.distance = dir_data.distance

    # 6. Re-sync Stops (Delete and Re-add)
    db.query(RouteStop).filter(RouteStop.direction_id == direction_id).delete()
    
    # We use flush to ensure deletes happen before inserts if there are constraints
    db.flush() 

    for index, stop in enumerate(dir_data.stops):
        db_route_stop = RouteStop(
            direction_id=direction_id,
            stop_id=stop.stop_id,
            order=index + 1,
            distance_from_start=stop.distance_from_start
        )
        db.add(db_route_stop)

    db.commit()
    db.refresh(db_route)
    return db_route

@router.delete("/route/{route_id}/{direction_id}")
def delete_direction(route_id: int, direction_id: int, db: Session = Depends(get_db)):
    # Get route (must use .first())
    route = db.query(Route).filter(Route.id == route_id).first()
    if not route:
        raise HTTPException(status_code=404, detail="The route does not exist!")

    # Get direction
    direction = db.query(Direction).filter(Direction.id == direction_id, Direction.route_id == route_id).first()
    if not direction:
        raise HTTPException(status_code=404, detail="Direction not found")

    # Delete GPX from Supabase Storage
    delete_gpx_from_supabase(direction.gpx_path)

    # Delete direction
    db.delete(direction)
    db.commit()
    print(f"🗑️ Deleted direction: {direction.direction}")

    # Now check if route has any directions left
    remaining_directions = db.query(Direction).filter(Direction.route_id == route_id).all()

    if len(remaining_directions) == 0:
        # No directions left → delete the route
        db.delete(route)
        db.commit()
        print(f"🗑️ Route '{route.name}' deleted because it has no more directions.")

        return {"message": "Direction deleted, and route deleted (no directions left)."}

    return {"message": "Direction deleted successfully."}

#----extra if need it-----
@router.get("/route/{route_id}", response_model=RouteOut)
def get_route(route_id: int, db: Session = Depends(get_db)):
    route = (
        db.query(Route)
        .options(
            joinedload(Route.directions)
            .joinedload(Direction.route_stops)
            .joinedload(RouteStop.stop)
        )
        .filter(Route.id == route_id)
        .first()
    )
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    return route

