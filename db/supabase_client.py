import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv() # This loads your .env file locally

url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(url, key)