import os
from supabase import create_client, Client

_client = None

def get_db() -> Client:
    global _client
    if _client is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_KEY")
        if url and key:
            _client = create_client(url, key)
    return _client
