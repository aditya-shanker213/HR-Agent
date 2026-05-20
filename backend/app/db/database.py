from pymongo import MongoClient
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Get MongoDB URI from .env
MONGO_URI = os.getenv("MONGO_URI")

# Create MongoDB client
client = MongoClient(MONGO_URI)

# Connect to database
db = client[os.getenv("DATABASE_NAME")]