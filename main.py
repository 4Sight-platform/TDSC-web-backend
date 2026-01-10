from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from config import CORS_ORIGINS
from database import initialize_collections, get_mongo_client
from routes import auth, engagement
from tracing import RequestIdMiddleware

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown events"""
    # Startup - initialize MongoDB
    logger.info("Initializing MongoDB collections...")
    try:
        initialize_collections()
        logger.info("MongoDB collections initialized successfully!")
        logger.info("TDSC Backend started successfully!")
    except Exception as e:
        logger.error(f"Failed to initialize MongoDB: {e}")
        raise
    
    yield
    
    # Shutdown
    logger.info("Shutting down TDSC Backend...")


# Create FastAPI app
app = FastAPI(
    title="TDSC Blog Backend",
    description="Backend API for TDSC New Approach - User authentication and blog engagement",
    version="1.0.0",
    lifespan=lifespan
)

# Add request ID tracing middleware (must be first)
app.add_middleware(RequestIdMiddleware)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
app.include_router(engagement.router)


@app.get("/")
def root():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "TDSC Blog Backend",
        "version": "1.0.0",
        "database": "MongoDB Atlas"
    }


@app.get("/health")
def health():
    """Health check endpoint"""
    return {"status": "ok"}
