from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import uuid, json
from api.integrations.supabase_client import get_db

router = APIRouter()

# ── Degree chapter templates ─────────────────────────────────────────────────
DEGREE_TEMPLATES = {
    "dba": [
        {"chapter": "Abstract", "status": "not_started", "notes": "", "sort_order": 0},
        {"chapter": "Chapter I: Introduction", "status": "not_started", "notes": "", "sort_order": 1},
        {"chapter": "Chapter II: Literature Review", "status": "not_started", "notes": "", "sort_order": 2},
        {"chapter": "Chapter III: Methodology", "status": "not_started", "notes": "", "sort_order": 3},
        {"chapter": "Chapter IV: Results", "status": "not_started", "notes": "", "sort_order": 4},
        {"chapter": "Chapter V: Discussion", "status": "not_started", "notes": "", "sort_order": 5},
    ],
    "phd": [
        {"chapter": "Abstract", "status": "not_started", "notes": "", "sort_order": 0},
        {"chapter": "Chapter I: Introduction", "status": "not_started", "notes": "", "sort_order": 1},
        {"chapter": "Chapter II: Literature Review", "status": "not_started", "notes": "", "sort_order": 2},
        {"chapter": "Chapter III: Methodology", "status": "not_started", "notes": "", "sort_order": 3},
        {"chapter": "Chapter IV: Results", "status": "not_started", "notes": "", "sort_order": 4},
        {"chapter": "Chapter V: Discussion", "status": "not_started", "notes": "", "sort_order": 5},
        {"chapter": "Chapter VI: Conclusions", "status": "not_started", "notes": "", "sort_order": 6},
        {"chapter": "References", "status": "not_started", "notes": "", "sort_order": 7},
    ],
    "edd": [
        {"chapter": "Abstract", "status": "not_started", "notes": "", "sort_order": 0},
        {"chapter": "Chapter I: Introduction to the Study", "status": "not_started", "notes": "", "sort_order": 1},
        {"chapter": "Chapter II: Review of the Literature", "status": "not_started", "notes": "", "sort_order": 2},
        {"chapter": "Chapter III: Research Methodology", "status": "not_started", "notes": "", "sort_order": 3},
        {"chapter": "Chapter IV: Findings", "status": "not_started", "notes": "", "sort_order": 4},
        {"chapter": "Chapter V: Summary and Recommendations", "status": "not_started", "notes": "", "sort_order": 5},
    ],
    "masters": [
        {"chapter": "Abstract", "status": "not_started", "notes": "", "sort_order": 0},
        {"chapter": "Introduction", "status": "not_started", "notes": "", "sort_order": 1},
        {"chapter": "Literature Review", "status": "not_started", "notes": "", "sort_order": 2},
        {"chapter": "Methodology", "status": "not_started", "notes": "", "sort_order": 3},
        {"chapter": "Results", "status": "not_started", "notes": "", "sort_order": 4},
        {"chapter": "Discussion and Conclusion", "status": "not_started", "notes": "", "sort_order": 5},
    ],
    "custom": [
        {"chapter": "Abstract", "status": "not_started", "notes": "", "sort_order": 0},
        {"chapter": "Introduction", "status": "not_started", "notes": "", "sort_order": 1},
        {"chapter": "Body", "status": "not_started", "notes": "", "sort_order": 2},
        {"chapter": "Conclusion", "status": "not_started", "notes": "", "sort_order": 3},
    ]
}

# ── Mitchell pre-load ────────────────────────────────────────────────────────
MITCHELL_CHAPTERS = [
    {"chapter": "Abstract", "status": "complete", "notes": "Completed v2", "sort_order": 0},
    {"chapter": "Chapter I: Introduction", "status": "complete", "notes": "Completed v2 — all required sections present", "sort_order": 1},
    {"chapter": "Chapter II: Literature Review", "status": "complete", "notes": "Expanded — 10+ empirical studies, Meyer & Allen, Social Exchange Theory", "sort_order": 2},
    {"chapter": "Chapter III: Methodology", "status": "complete", "notes": "Completed v2 — IRB ethics statement included", "sort_order": 3},
    {"chapter": "Chapter IV: Results", "status": "pending_irb", "notes": "Awaiting IRB approval before data collection", "sort_order": 4},
    {"chapter": "Chapter V: Discussion", "status": "pending_irb", "notes": "Awaiting IRB approval", "sort_order": 5},
]

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
    "chapter_template": "dba",
    "formatting_notes": "Left-aligned ragged right, Times New Roman 12pt double-spaced. Chapter titles ALL CAPS centered. Chapter II titled REVIEW OF THE LITERATURE. APA 7th heading levels. No extra blank lines between headings and text.",
    "chapter_structure": json.dumps(MITCHELL_CHAPTERS),
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
    chapter_template: str = "dba"
    custom_chapters: Optional[list] = None  # override template

class ChapterAdd(BaseModel):
    client_id: str
    chapter_name: str

class ChapterUpdate(BaseModel):
    chapter_id: str
    status: Optional[str] = None
    notes: Optional[str] = None

def upsert_mitchell():
    db = get_db()
    if not db:
        return
    try:
        existing = db.table("clients").select("id").eq("id", MITCHELL_DATA["id"]).execute()
        if not existing.data:
            db.table("clients").insert(MITCHELL_DATA).execute()
            print("Mitchell pre-loaded")
            for ch in MITCHELL_CHAPTERS:
                db.table("chapters").upsert({
                    "id": f"mitchell-ch-{ch['sort_order']}",
                    "client_id": MITCHELL_DATA["id"],
                    "chapter_name": ch["chapter"],
                    "status": ch["status"],
                    "notes": ch["notes"],
                    "sort_order": ch["sort_order"],
                    "word_count": 0, "version": 1
                }).execute()
    except Exception as e:
        print(f"Mitchell pre-load error: {e}")

# ── Routes ───────────────────────────────────────────────────────────────────

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
    if MITCHELL_DATA["id"] not in [c["id"] for c in clients]:
        clients = [MITCHELL_DATA] + clients
    return {"clients": clients}

@router.get("/templates")
def get_templates():
    return {
        "templates": {
            "dba": {"label": "DBA — Doctor of Business Administration", "chapters": [c["chapter"] for c in DEGREE_TEMPLATES["dba"]]},
            "phd": {"label": "PhD — Doctor of Philosophy", "chapters": [c["chapter"] for c in DEGREE_TEMPLATES["phd"]]},
            "edd": {"label": "EdD — Doctor of Education", "chapters": [c["chapter"] for c in DEGREE_TEMPLATES["edd"]]},
            "masters": {"label": "Masters (MS/MA/MBA)", "chapters": [c["chapter"] for c in DEGREE_TEMPLATES["masters"]]},
            "custom": {"label": "Custom Structure", "chapters": [c["chapter"] for c in DEGREE_TEMPLATES["custom"]]},
        }
    }

@router.get("/{client_id}")
def get_client(client_id: str):
    db = get_db()
    if db:
        try:
            r = db.table("clients").select("*").eq("id", client_id).single().execute()
            if r.data: return r.data
        except Exception: pass
    if client_id == MITCHELL_DATA["id"]: return MITCHELL_DATA
    raise HTTPException(404, "Client not found")

@router.post("/")
def create_client(req: ClientCreate):
    client_id = str(uuid.uuid4())
    template_key = req.chapter_template.lower().replace("-","").replace(" ","")
    if template_key not in DEGREE_TEMPLATES:
        template_key = "dba"

    chapters = req.custom_chapters if req.custom_chapters else DEGREE_TEMPLATES[template_key]

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
        "chapter_template": template_key,
        "chapter_structure": json.dumps(chapters),
    }
    db = get_db()
    if db:
        try:
            db.table("clients").insert(data).execute()
            for i, ch in enumerate(chapters):
                db.table("chapters").insert({
                    "id": str(uuid.uuid4()),
                    "client_id": client_id,
                    "chapter_name": ch.get("chapter", ch) if isinstance(ch, dict) else ch,
                    "status": ch.get("status", "not_started") if isinstance(ch, dict) else "not_started",
                    "notes": ch.get("notes", "") if isinstance(ch, dict) else "",
                    "sort_order": i,
                    "word_count": 0, "version": 1
                }).execute()
        except Exception as e:
            print(f"Create client error: {e}")
    return {"client_id": client_id, "message": "Client created"}

@router.delete("/{client_id}")
def delete_client(client_id: str):
    if client_id == MITCHELL_DATA["id"]:
        raise HTTPException(400, "Cannot delete Mitchell")
    db = get_db()
    if db:
        try:
            db.table("chapters").delete().eq("client_id", client_id).execute()
            db.table("scratchpad").delete().eq("client_id", client_id).execute()
            db.table("clients").delete().eq("id", client_id).execute()
        except Exception as e:
            print(f"Delete client error: {e}")
    return {"status": "deleted"}

@router.get("/{client_id}/chapters")
def get_chapters(client_id: str):
    db = get_db()
    if db:
        try:
            r = db.table("chapters").select("*").eq("client_id", client_id).order("sort_order").execute()
            if r.data: return {"chapters": r.data}
        except Exception as e:
            print(f"Get chapters error: {e}")
    if client_id == MITCHELL_DATA["id"]:
        return {"chapters": MITCHELL_CHAPTERS}
    return {"chapters": []}

@router.post("/{client_id}/chapters/add")
def add_chapter(client_id: str, req: ChapterAdd):
    db = get_db()
    if db:
        try:
            existing = db.table("chapters").select("sort_order").eq("client_id", client_id).order("sort_order", desc=True).limit(1).execute()
            max_order = existing.data[0]["sort_order"] + 1 if existing.data else 0
            db.table("chapters").insert({
                "id": str(uuid.uuid4()),
                "client_id": client_id,
                "chapter_name": req.chapter_name,
                "status": "not_started",
                "sort_order": max_order,
                "word_count": 0, "version": 1
            }).execute()
        except Exception as e:
            print(f"Add chapter error: {e}")
    return {"status": "added"}

@router.delete("/{client_id}/chapters/{chapter_name}")
def remove_chapter(client_id: str, chapter_name: str):
    db = get_db()
    if db:
        try:
            db.table("chapters").delete().eq("client_id", client_id).eq("chapter_name", chapter_name).execute()
        except Exception as e:
            print(f"Remove chapter error: {e}")
    return {"status": "removed"}

class ClientUpdate(BaseModel):
    name: Optional[str] = None
    degree: Optional[str] = None
    field: Optional[str] = None
    institution: Optional[str] = None
    topic: Optional[str] = None
    advisor: Optional[str] = None
    citation_style: Optional[str] = None
    quality_target: Optional[int] = None
    formatting_notes: Optional[str] = None

@router.put("/{client_id}")
def update_client(client_id: str, req: ClientUpdate):
    updates = {k: v for k, v in req.dict().items() if v is not None}
    if not updates:
        return {"status": "no changes"}
    # Always allow updating Mitchell too
    db = get_db()
    if db:
        try:
            db.table("clients").update(updates).eq("id", client_id).execute()
        except Exception as e:
            print(f"Update client error: {e}")
    # If Mitchell, update in-memory data too
    if client_id == MITCHELL_DATA["id"]:
        MITCHELL_DATA.update(updates)
    return {"status": "updated"}

class ChapterStatusUpdate(BaseModel):
    status: str
    notes: Optional[str] = None

@router.put("/{client_id}/chapters/{chapter_name}/status")
def update_chapter_status(client_id: str, chapter_name: str, req: ChapterStatusUpdate):
    db = get_db()
    if db:
        try:
            db.table("chapters").update({
                "status": req.status,
                "notes": req.notes or ""
            }).eq("client_id", client_id).eq("chapter_name", chapter_name).execute()
        except Exception as e:
            print(f"Update chapter status error: {e}")
    return {"status": "updated"}
