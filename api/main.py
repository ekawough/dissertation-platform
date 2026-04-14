from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import os

from api.routes import clients, chapters

app = FastAPI(title="Dissertation Platform", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(clients.router, prefix="/clients", tags=["Clients"])
app.include_router(chapters.router, prefix="/chapters", tags=["Chapters"])

@app.on_event("startup")
async def startup():
    clients.upsert_mitchell()

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def serve():
    path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
    if os.path.exists(path):
        with open(path) as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>Dissertation Platform</h1>")

@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0"}
