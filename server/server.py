from database import DatabaseConfig, DatabaseConnection
from migrations import MigrationManager
from bot.repository import FlightRepository
from service import FlightService
from fastapi import FastAPI, HTTPException
from flight import Flight

# Initialize
## DB config
db_config = DatabaseConfig(
    'flightsdb',
    '192.168.133.20',
    'postgres',
    '123Secret_a',
    5432
)
db_connection = DatabaseConnection(db_config)
## Migrations
migration_manager = MigrationManager(db_config)
migration_manager.create_tables()
# Repository and Service
repository = FlightRepository(db_connection)
service = FlightService(repository)

app = FastAPI(
    title="Flight API"
)


@app.get("/")
async def root():
    return {"message": "Hello from FastAPI"}


@app.get("/flights")
async def get_flights():
    try:
        return service.get_all()
    except Exception as e:
        return HTTPException(status_code=500, detail=f"Ошибка при получении полётов: {str(e)}")


@app.post("/flights")
async def create_flight(flight_data: dict):
    try:
        # Validation
        required_fields = ["price", "plane"]
        for field in required_fields:
            if field not in flight_data:
                raise HTTPException(status_code=400, detail=f"Отсутствует обязательное поле {field}")

        flight = Flight(
            price=flight_data['price'],
            plane=flight_data['plane']
        )

        created_flight = service.create_flight(flight)
        return created_flight

    except Exception as e:
        return HTTPException(status_code=500, detail=f"Ошибка при добавлении полёта: {str(e)}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)

