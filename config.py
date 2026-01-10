import os
from dotenv import load_dotenv

load_dotenv()

# MongoDB Configuration
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb+srv://4sightplatform_db_user:2005@cluster0.1hybwum.mongodb.net/?appName=Cluster0")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "TDSC")

# JWT Configuration
JWT_SECRET = os.getenv("JWT_SECRET", "tdsc_super_secret_key_change_in_production_2024")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

# CORS Origins (allow all for now, restrict in production)
CORS_ORIGINS = ["*"]
