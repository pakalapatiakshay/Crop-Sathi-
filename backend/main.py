from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import crop, disease, sync, weather
from core.config import CORS_ORIGINS
from services import ml_service, soil_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    ml_service.load_models()
    soil_service.load_soil_profiles()
    import asyncio
    from services import market_service
    asyncio.create_task(market_service.start_periodic_market_fetcher())
    yield


app = FastAPI(
    title="Crop-Sathi ML Server",
    description="Jharkhand-tuned crop recommendation and plant disease detection, "
                 "adapted from the Crop-AI ML core for SIH25030.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from api.routes import crop, disease, sync, weather, market, schemes, soil, voice

app.include_router(crop.router)
app.include_router(disease.router)
app.include_router(soil.router)
app.include_router(voice.router)
app.include_router(sync.router)
app.include_router(weather.router)
app.include_router(market.router)
app.include_router(schemes.router)


@app.get("/", tags=["Root"])
async def root():
    return {"message": "Crop-Sathi ML Server is running"}


@app.get("/health", tags=["Root"])
async def health():
    return {"status": "ok"}
