import psycopg2
from psycopg2.extras import Json
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

env_vars = ROOT_PATH = Path(__file__).parent.parent
load_dotenv(env_vars / ".env")
load_dotenv(env_vars / ".env.secrets")

def get_connection():
    """Create and return a psycopg2 connection using env variables."""
    conn = psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", 5432),
        dbname=os.getenv("POSTGRES_DB", "PoliSense_dev"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )
    return conn
