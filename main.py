import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Internal imports
from routes import route_editer, bus_route
from db.database import engine, Base, SessionLocal
from services.routing_cal import build_graph

from dependencies import limiter
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

import time
import asyncio
from sqlalchemy.exc import OperationalError

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("--- Server Starting Up ---")
    
    max_retries = 3
    retry_delay = 5  # seconds
    db_connected = False
    
    for attempt in range(1, max_retries + 1):
        try:
            print(f"Database connection attempt {attempt}/{max_retries}...")
            Base.metadata.create_all(bind=engine)
            
            # If we reach here, DB is up
            db = SessionLocal()
            try:
                print("Warm-up: Building transit graph...")
                app.state.transit_data = build_graph(db)
                print("Graph ready!")
                db_connected = True
                break # Exit the retry loop
            finally:
                db.close()
                
        except (OperationalError, Exception) as e:
            print(f"Connection failed: {e}")
            if attempt < max_retries:
                print(f"Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
            else:
                print("--- Critical Error: Max retries reached. ---")
                # Optional: You can either raise the error to kill the server 
                # or let it start without data (but routes will fail)
                raise e 

    yield
    print("--- Server Shutting Down ---")

# 2. Initialize App (Only once!)
app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# 3. CORS Configuration
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

frontend_url = os.getenv("FRONTEND_URL")
if frontend_url:
    clean_url = frontend_url.rstrip("/")
    origins.append(clean_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    # Ensure "Authorization" is allowed!
    allow_headers=["Content-Type", "Authorization"], 
)

# 4. Basic Routes
@app.get("/")
def health_check():
    return {"status": "online", "message": "Transport Guide API is running"}

# 5. Include your Routers
app.include_router(route_editer.router)
app.include_router(bus_route.router)