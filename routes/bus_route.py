from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from schemas.bus_schema import RouteRequest, FindRouteResponse
from services.routing_cal import dijkstra, rebuild_path, find_nearby_stops, haversine
from db.database import get_db
from dependencies import limiter

router = APIRouter()

@router.post("/find-route", response_model=FindRouteResponse)
@limiter.limit("5/minute")
def find_route(payload: RouteRequest, request: Request, db: Session = Depends(get_db)):
    # --- Configuration Constants ---
    WALK_WEIGHT = 1.5
    MAX_CANDIDATES = 3
    WALK_SPEED_MIN_KM = 10.0
    TRANSIT_SPEED_MIN_KM = 2.0
    STOP_PENALTY_MIN = 0.3
    DEFAULT_TICKET_PRICE = 0.0

    # ✅ USE DOT NOTATION (because of Pydantic)
    from_lat, from_lng = payload.from_location.lat, payload.from_location.lng
    to_lat, to_lng = payload.to_location.lat, payload.to_location.lng

    # Sanity Check: Is the trip distance over 200km?
    rough_dist = haversine(from_lat, from_lng, to_lat, to_lng)
    if rough_dist > 200:
        raise HTTPException(400, "Distance too far for local transit search.")

    start_candidates = find_nearby_stops(db, from_lat, from_lng, max_walk_km=0.7)[:MAX_CANDIDATES]
    end_candidates = find_nearby_stops(db, to_lat, to_lng, max_walk_km=0.7)[:MAX_CANDIDATES]

    if not start_candidates or not end_candidates:
        raise HTTPException(404, "Could not find stops near your location.")

    # Build Graph
    graph, route_stops, rs_map = request.app.state.transit_data

    # Map Start Candidates to RouteStops
    start_rs_costs = {}
    for stop, walk_d in start_candidates:
        for rs in route_stops:
            if rs.stop_id == stop.id:
                start_rs_costs[rs.id] = min(
                    start_rs_costs.get(rs.id, float("inf")),
                    walk_d * WALK_WEIGHT
                )

    if not start_rs_costs:
        raise HTTPException(404, "No bus routes available from these stops.")

    # Dijkstra Search
    end_stop_costs = {stop.id: walk_d * WALK_WEIGHT for stop, walk_d in end_candidates}
    end_rs_id, prev = dijkstra(graph, start_rs_costs, end_stop_costs, rs_map)

    if not end_rs_id:
        raise HTTPException(404, "No path found between these locations.")

    path_ids = rebuild_path(end_rs_id, prev)

    # Group into Segments (Logic for the response)
    segments = []
    current = []
    for rs_id in path_ids:
        rs = rs_map[rs_id]
        if not current or current[-1].direction_id == rs.direction_id:
            current.append(rs)
        else:
            segments.append(current)
            current = [rs]
    segments.append(current)

    # Final Response Calculation
    total_duration_mins = 0.0
    total_cost = 0.0
    total_dist_km = 0.0
    route_segments_data = []

    for i, seg in enumerate(segments):
        # Basic Segment Stats
        seg_dist = abs(seg[-1].distance_from_start - seg[0].distance_from_start)
        seg_duration = (seg_dist * TRANSIT_SPEED_MIN_KM) + (len(seg) * STOP_PENALTY_MIN)
        seg_cost = float(seg[0].direction.route.ticket_price or DEFAULT_TICKET_PRICE)
        
        total_duration_mins += seg_duration
        total_cost += seg_cost
        total_dist_km += seg_dist

        # --- New: Transfer Logic ---
        transfer_info = None
        if i > 0:
            prev_stop = segments[i-1][-1].stop
            curr_stop = seg[0].stop
            
            # Calculate distance between the drop-off and next pick-up
            t_dist_km = haversine(prev_stop.lat, prev_stop.lng, curr_stop.lat, curr_stop.lng)
            t_duration = round(t_dist_km * WALK_SPEED_MIN_KM, 1)
            
            # Add this internal walk to the total time
            total_duration_mins += t_duration
            total_dist_km += t_dist_km

            transfer_info = {
                "from_stop": prev_stop,
                "to_stop": curr_stop,
                "walk_dist_km": round(t_dist_km, 3),
                "walk_duration_mins": t_duration,
                "is_same_stop": prev_stop.id == curr_stop.id
            }

        route_segments_data.append({
            "transfer_from_previous": transfer_info, # This tells the user how to get to THIS bus
            "route": {
                "name": seg[0].direction.route.name,
                "bus_type": seg[0].direction.route.bus_type,
                "ticket_price": seg_cost,
                },
            "direction": {
                "direction": seg[0].direction.direction,
                "sub_name": seg[0].direction.sub_name,     
                "segment_distance_km": round(seg_dist, 2),
                "segment_duration_mins": round(seg_duration, 1),
            },
            "stops": [{"id": rs.stop.id, "name": rs.stop.name, "lat": rs.stop.lat, "lng": rs.stop.lng} for rs in seg]
        })

    # --- Summary logic ---
    first_rs = rs_map[path_ids[0]]
    last_rs = rs_map[path_ids[-1]]
    walk_start_km = next((d for s, d in start_candidates if s.id == first_rs.stop_id), 0.0)
    walk_end_km = next((d for s, d in end_candidates if s.id == last_rs.stop_id), 0.0)
    
    initial_walk_duration = walk_start_km * WALK_SPEED_MIN_KM
    final_walk_duration = walk_end_km * WALK_SPEED_MIN_KM
    
    # Final total includes: first walk + all transit + all internal transfers + last walk
    grand_total_duration = total_duration_mins + initial_walk_duration + final_walk_duration
    return {
            "summary": {
                "total_duration_mins": round(grand_total_duration, 0),
                "total_cost": total_cost,
                "total_walking_distance_km": round(walk_start_km + walk_end_km, 2),
                "walking_duration_mins": round(initial_walk_duration + final_walk_duration, 0), # Ensure this is here
                "from_stop": {"id": first_rs.stop.id, "name": first_rs.stop.name, "lat": first_rs.stop.lat, "lng": first_rs.stop.lng},
                "to_stop": {"id": last_rs.stop.id, "name": last_rs.stop.name, "lat": last_rs.stop.lat, "lng": last_rs.stop.lng},
                "walking_distance_to_start_km": round(walk_start_km, 3), # Ensure this is here
                "walking_distance_to_end_km": round(walk_end_km, 3),     # Ensure this is here
            },
            "route_segments": route_segments_data
        }