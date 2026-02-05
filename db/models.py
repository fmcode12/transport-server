from sqlalchemy import Column, Integer, String, Float, ForeignKey, Text
from sqlalchemy.orm import relationship
from geoalchemy2 import Geography
from db.database import Base


class Route(Base):
    __tablename__ = "routes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    bus_type = Column(String, nullable=True)
    ticket_price = Column(Integer, nullable=True)
    total_distance = Column(Float, nullable=True)
    total_vehicles = Column(Integer, nullable=True)
    active_vehicles = Column(Integer, nullable=True)


    # 🧭 One route can have multiple directions
    directions = relationship("Direction", back_populates="route", cascade="all, delete")


class Direction(Base):
    __tablename__ = "directions"

    id = Column(Integer, primary_key=True, index=True)
    direction = Column(String, nullable=False)
    sub_name = Column(String, nullable=True)
    distance = Column(Float, nullable=True)  
    gpx = Column(String, nullable=True)
    gpx_path = Column(String, nullable=True)
    route_id = Column(Integer, ForeignKey("routes.id"))

    route = relationship("Route", back_populates="directions")
    route_stops = relationship(
        "RouteStop",
        back_populates="direction",
        cascade="all, delete-orphan",
        order_by="RouteStop.order"
    )

    @property
    def stops(self):
        # This returns list of Stop objects in correct order
        return [rs.stop for rs in self.route_stops]

class Stop(Base):
    __tablename__ = "stops"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)

    location = Column(Geography(geometry_type='POINT', srid=4326))
    route_assignments = relationship("RouteStop", back_populates="stop")

class RouteStop(Base):
    __tablename__ = "route_stops"

    id = Column(Integer, primary_key=True, index=True)
    direction_id = Column(Integer, ForeignKey("directions.id"))
    stop_id = Column(Integer, ForeignKey("stops.id"))
    order = Column(Integer, nullable=False)  # stop position in the route
    distance_from_start = Column(Float, nullable=True)

    direction = relationship("Direction", back_populates="route_stops")
    stop = relationship("Stop")

