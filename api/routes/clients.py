from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import uuid, json
from api.integrations.supabase_client import get_db

router = APIRouter()

# ── Mitchell pre-loaded ──────────────────────────────────────────────────────
MITCHELL_DATA = {
    "id": "mitchell-dba-ulv-001",
    "name": "Mitchell",
    "degree": "DBA",
    "field": "Human Resources",
    "institution": "University of La Verne",
    "topic": "The Relationship Between Organizational Commitment and Employee Turnover Intentions",
    "advisor": "Professor Zhang",
    "citation_style": "APA 7th",
    "quality_target": 75,
    "formatting_notes": "Left-aligned ragged right, Times New Roman 12pt double-spaced. Chapter titles ALL CAPS centered. Chapter II titled REVIEW OF THE LITERATURE. APA 7th heading levels. No extra blank lines between headings and text.",
    "chapter_structure": json.dumps([
        {"chapter": "Abstract", "status": "complete", "notes": "Completed v2"},
        {"chapter": "Chapter I: Introduction", "status": "complete", "notes": "Completed v2 — all required sections present"},
        {"chapter": "Chapter II: Literature Review", "status": "complete", "notes": "Expanded lit review — 10+ empirical studies, Meyer & Allen framework, Social Exchange Theory"},
        {"chapter": "Chapter III: Methodology", "status": "complete", "notes": "Completed v2 — IRB ethics statement included"},
        {"chapter": "Chapter IV: Results", "status": "pending_irb", "notes": "Awaiting IRB approval before data collection"},
        {"chapter": "Chapter V: Discussion", "status": "pending_irb", "notes": "Awaiting IRB approval"}
    ]),
    "created_at": "2026-03-03T00:00:00+00:00"
}

class ClientCreate(BaseModel):
    name: str
    degree: str
    field: str
    institution: str
    topic: str
    advisor: Optional[str] = None
    citation_style: str = "APA 7th"
    quality_target: int = 75
    formatting_notes: Optional[str] = None

def upsert_mitchell():
    db = get_db()
    if not db:
        return
    try:
        existing = db.table("clients").select("id").eq("id", MITCHELL_DATA["id"]).execute()
        if not existing.data:
            db.table("clients").insert(MITCHELL_DATA).execute()
            print("Mitchell pre-loaded into Supabase")
            # Pre-load chapters
            chapters = json.loads(MITCHELL_DATA["chapter_structure"])
            for i, ch in enumerate(chapters):
                db.table("chapters").upsert({
                    "id": f"mitchell-ch-{i}",
                    "client_id": MITCHELL_DATA["id"],
                    "chapter_name": ch["chapter"],
                    "status": ch["status"],
                    "notes": ch["notes"],
                    "word_count": 0,
                    "version": 1
                }).execute()
    except Exception as e:
        print(f"Mitchell pre-load error: {e}")

@router.get("/")
def list_clients():
    db = get_db()
    clients = []
    if db:
        try:
            r = db.table("clients").select("*").order("created_at", desc=True).execute()
            clients = r.data or []
        except Exception as e:
            print(f"List clients error: {e}")
    # Always ensure Mitchell is in the list
    mitchell_ids = [c["id"] for c in clients]
    if MITCHELL_DATA["id"] not in mitchell_ids:
        clients = [MITCHELL_DATA] + clients
    return {"clients": clients}

@router.get("/{client_id}")
def get_client(client_id: str):
    db = get_db()
    if db:
        try:
            r = db.table("clients").select("*").eq("id", client_id).single().execute()
            if r.data:
                return r.data
        except Exception:
            pass
    if client_id == MITCHELL_DATA["id"]:
        return MITCHELL_DATA
    raise HTTPException(404, "Client not found")

@router.post("/")
def create_client(req: ClientCreate):
    client_id = str(uuid.uuid4())
    data = {
        "id": client_id,
        "name": req.name,
        "degree": req.degree,
        "field": req.field,
        "institution": req.institution,
        "topic": req.topic,
        "advisor": req.advisor,
        "citation_style": req.citation_style,
        "quality_target": req.quality_target,
        "formatting_notes": req.formatting_notes,
        "chapter_structure": json.dumps([
            {"chapter": "Abstract", "status": "not_started", "notes": ""},
            {"chapter": "Chapter I: Introduction", "status": "not_started", "notes": ""},
            {"chapter": "Chapter II: Literature Review", "status": "not_started", "notes": ""},
            {"chapter": "Chapter III: Methodology", "status": "not_started", "notes": ""},
            {"chapter": "Chapter IV: Results", "status": "not_started", "notes": ""},
            {"chapter": "Chapter V: Discussion", "status": "not_started", "notes": ""},
        ])
    }
    db = get_db()
    if db:
        try:
            db.table("clients").insert(data).execute()
            # create chapter rows
            chapters = json.loads(data["chapter_structure"])
            for i, ch in enumerate(chapters):
                db.table("chapters").insert({
                    "id": str(uuid.uuid4()),
                    "client_id": client_id,
                    "chapter_name": ch["chapter"],
                    "status": "not_started",
                    "notes": "",
                    "word_count": 0,
                    "version": 1
                }).execute()
        except Exception as e:
            print(f"Create client error: {e}")
    return {"client_id": client_id, "message": "Client created"}

@router.get("/{client_id}/chapters")
def get_chapters(client_id: str):
    db = get_db()
    if db:
        try:
            r = db.table("chapters").select("*").eq("client_id", client_id).order("chapter_name").execute()
            return {"chapters": r.data or []}
        except Exception as e:
            print(f"Get chapters error: {e}")
    # fallback for Mitchell
    if client_id == MITCHELL_DATA["id"]:
        return {"chapters": json.loads(MITCHELL_DATA["chapter_structure"])}
    return {"chapters": []}
