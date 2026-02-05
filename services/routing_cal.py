import math
from db.models import Stop, Direction, RouteStop
from collections import defaultdict
from sqlalchemy import func
import heapq
from sqlalchemy.orm import joinedload

def haversine(lat1, lng1, lat2, lng2):
    R = 6371
    lat1, lng1, lat2, lng2 = map(math.radians, [lat1, lng1, lat2, lng2])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlng/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def find_nearby_stops(db, lat, lng, max_walk_km=0.7):
    # Create the point from user input
    user_location = func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326)
    
    # Since Stop.location is already 'geography', ST_Distance returns meters
    results = (
        db.query(
            Stop, 
            func.ST_Distance(Stop.location, user_location).label("distance")
        )
        .filter(func.ST_DWithin(Stop.location, user_location, max_walk_km * 1000))
        .order_by("distance")
        .all()
    )

    return [(stop, dist / 1000.0) for stop, dist in results]

# services/routing_cal.py
from sqlalchemy import text

# Global variables to act as our "Cache"
CACHED_GRAPH = None
CACHED_ROUTE_STOPS = None
CACHED_RS_MAP = None

def build_graph(db):
    global CACHED_GRAPH, CACHED_ROUTE_STOPS, CACHED_RS_MAP
    
    # If already built, return the cache
    if CACHED_GRAPH is not None:
        return CACHED_GRAPH, CACHED_ROUTE_STOPS, CACHED_RS_MAP

    print("--- Building Global Transit Graph (This may take a few seconds)... ---")
    graph = defaultdict(list)
    WALK_WEIGHT = 3.0
    TRANSFER_PENALTY = 0.6
    MAX_WALK_TRANSFER_METERS = 300 

    route_stops = (
            db.query(RouteStop)
            .options(
                joinedload(RouteStop.direction).joinedload(Direction.route),
                joinedload(RouteStop.stop)
            )
            .all()
        )

    rs_by_dir = defaultdict(list)
    rs_by_stop = defaultdict(list)
    
    for rs in route_stops:
        rs_by_dir[rs.direction_id].append(rs)
        rs_by_stop[rs.stop_id].append(rs)

    # 1. Ride edges (within the same bus line)
    for dir_id, stops in rs_by_dir.items():
        stops.sort(key=lambda x: x.order)
        for i in range(len(stops) - 1):
            a, b = stops[i], stops[i + 1]
            if a.distance_from_start is not None and b.distance_from_start is not None:
                w = b.distance_from_start - a.distance_from_start
                graph[a.id].append((b.id, w))

    # 2. Optimized Walking Transfers (ONE QUERY for all stops)
    # This finds all pairs of stops within 300m using PostGIS
    query = text("""
        SELECT a.id as stop_a, b.id as stop_b, ST_Distance(a.location, b.location) / 1000.0 as dist_km
        FROM stops a, stops b
        WHERE ST_DWithin(a.location, b.location, :dist)
        AND a.id != b.id
    """)
    
    nearby_pairs = db.execute(query, {"dist": MAX_WALK_TRANSFER_METERS}).fetchall()

    for stop_a_id, stop_b_id, dist_km in nearby_pairs:
        for rs_a in rs_by_stop[stop_a_id]:
            for rs_b in rs_by_stop[stop_b_id]:
                if rs_a.direction_id != rs_b.direction_id:
                    weight = (dist_km * WALK_WEIGHT) + TRANSFER_PENALTY
                    graph[rs_a.id].append((rs_b.id, weight))

    # 3. Same-stop transfers (0 distance walking)
    for stop_id, rs_list in rs_by_stop.items():
        for a in rs_list:
            for b in rs_list:
                if a.direction_id != b.direction_id:
                    graph[a.id].append((b.id, TRANSFER_PENALTY))

    # Store in Cache
    CACHED_GRAPH = graph
    CACHED_ROUTE_STOPS = route_stops
    CACHED_RS_MAP = {rs.id: rs for rs in route_stops}
    
    return CACHED_GRAPH, CACHED_ROUTE_STOPS, CACHED_RS_MAP

def dijkstra(graph, start_rs_costs, end_stop_costs, rs_map):
    dist = {}
    prev = {}
    pq = []

    # init
    for rs_id, cost in start_rs_costs.items():
        dist[rs_id] = cost
        heapq.heappush(pq, (cost, rs_id))

    best_end = None
    best_dist = float("inf")

    while pq:
        cur_dist, cur = heapq.heappop(pq)

        if cur_dist > dist.get(cur, float("inf")):
            continue

        rs = rs_map[cur]

        # reached any destination stop
        if rs.stop_id in end_stop_costs:
            total = cur_dist + end_stop_costs[rs.stop_id]
            if total < best_dist:
                best_dist = total
                best_end = cur

        for nxt, w in graph[cur]:
            nd = cur_dist + w
            if nd < dist.get(nxt, float("inf")):
                dist[nxt] = nd
                prev[nxt] = cur
                heapq.heappush(pq, (nd, nxt))

    return best_end, prev

def rebuild_path(end_id, prev):
    path = [end_id]
    while end_id in prev:
        end_id = prev[end_id]
        path.append(end_id)
    return list(reversed(path))

