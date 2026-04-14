from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional
import uuid, json
from api.integrations.supabase_client import get_db
from api.agents.researcher import research_chapter
from api.agents.writer import write_chapter, revise_with_feedback
from api.agents.exporter import export_chapter_docx, export_full_dissertation_docx
from api.integrations.notion_client import log_to_notion

router = APIRouter()
_jobs = {}  # in-memory job tracker

class GenerateRequest(BaseModel):
    client_id: str
    chapter_name: str
    additional_instructions: Optional[str] = None
    existing_draft: Optional[str] = None
    professor_feedback: Optional[str] = None

class ReviseRequest(BaseModel):
    client_id: str
    chapter_id: str
    professor_feedback: str

class SaveDraftRequest(BaseModel):
    client_id: str
    chapter_name: str
    content: str
    notes: Optional[str] = None

def get_client_data(client_id: str) -> dict:
    db = get_db()
    if db:
        try:
            r = db.table("clients").select("*").eq("id", client_id).single().execute()
            if r.data:
                return r.data
        except Exception:
            pass
    from api.routes.clients import MITCHELL_DATA
    if client_id == MITCHELL_DATA["id"]:
        return MITCHELL_DATA
    return {}

async def run_generation(job_id: str, req: GenerateRequest):
    try:
        _jobs[job_id]["status"] = "researching"
        _jobs[job_id]["progress"] = 20

        client = get_client_data(req.client_id)
        if not client:
            raise Exception("Client not found")

        # Research
        research = await research_chapter(
            topic=client["topic"],
            chapter_type=req.chapter_name,
            existing_context=req.existing_draft or ""
        )
        _jobs[job_id]["source_count"] = research["source_count"]
        _jobs[job_id]["sources"] = json.dumps(research["sources"])
        _jobs[job_id]["status"] = "writing"
        _jobs[job_id]["progress"] = 55

        # Write
        result = await write_chapter(
            topic=client["topic"],
            degree=client.get("degree", "PhD"),
            field=client.get("field", ""),
            chapter_type=req.chapter_name,
            research_context=research["context"],
            additional_instructions=req.additional_instructions or "",
            existing_draft=req.existing_draft or "",
            professor_feedback=req.professor_feedback or "",
            citation_style=client.get("citation_style", "APA 7th"),
            institution=client.get("institution", ""),
            custom_formatting=client.get("formatting_notes", "")
        )

        # Save to Supabase
        chapter_id = str(uuid.uuid4())
        db = get_db()
        chapter_data = {
            "id": chapter_id,
            "client_id": req.client_id,
            "chapter_name": req.chapter_name,
            "content": result["content"],
            "word_count": result["word_count"],
            "sources": json.dumps(research["sources"]),
            "source_count": research["source_count"],
            "status": "draft",
            "notes": req.additional_instructions or "",
            "version": 1
        }
        if db:
            try:
                # upsert — update if exists for this client+chapter
                existing = db.table("chapters").select("id,version").eq("client_id", req.client_id).eq("chapter_name", req.chapter_name).execute()
                if existing.data:
                    old_id = existing.data[0]["id"]
                    old_ver = existing.data[0].get("version", 1)
                    chapter_id = old_id
                    chapter_data["id"] = old_id
                    chapter_data["version"] = old_ver + 1
                    db.table("chapters").update(chapter_data).eq("id", old_id).execute()
                else:
                    db.table("chapters").insert(chapter_data).execute()
            except Exception as e:
                print(f"Chapter save error: {e}")

        _jobs[job_id]["status"] = "complete"
        _jobs[job_id]["progress"] = 100
        _jobs[job_id]["chapter_id"] = chapter_id
        _jobs[job_id]["word_count"] = result["word_count"]
        _jobs[job_id]["content"] = result["content"]
        _jobs[job_id]["sources"] = json.dumps(research["sources"])

        # Log to Notion
        await log_to_notion(
            client_name=client.get("name", "Client"),
            chapter=req.chapter_name,
            status="Draft Complete",
            notes=f"{result['word_count']} words | {research['source_count']} sources"
        )

    except Exception as e:
        print(f"Generation error: {e}")
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = str(e)

@router.post("/generate")
async def generate_chapter(req: GenerateRequest, bg: BackgroundTasks):
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "queued", "progress": 5, "source_count": 0}
    bg.add_task(run_generation, job_id, req)
    return {"job_id": job_id, "status": "queued"}

@router.get("/job/{job_id}")
def job_status(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    result = dict(job)
    if "sources" in result and isinstance(result["sources"], str):
        try:
            result["sources"] = json.loads(result["sources"])
        except Exception:
            result["sources"] = []
    return result

@router.post("/revise")
async def revise_chapter(req: ReviseRequest):
    db = get_db()
    chapter = None
    if db:
        try:
            r = db.table("chapters").select("*").eq("id", req.chapter_id).single().execute()
            chapter = r.data
        except Exception:
            pass
    if not chapter:
        raise HTTPException(404, "Chapter not found")

    result = await revise_with_feedback(
        existing_content=chapter["content"],
        professor_feedback=req.professor_feedback,
        topic=get_client_data(req.client_id).get("topic", ""),
        chapter_type=chapter["chapter_name"]
    )
    if db:
        try:
            db.table("chapters").update({
                "content": result["content"],
                "word_count": result["word_count"],
                "status": "revised",
                "version": (chapter.get("version") or 1) + 1,
                "professor_feedback": req.professor_feedback
            }).eq("id", req.chapter_id).execute()
        except Exception as e:
            print(f"Revision save error: {e}")
    return {"content": result["content"], "word_count": result["word_count"], "status": "revised"}

@router.post("/save")
def save_draft(req: SaveDraftRequest):
    db = get_db()
    if db:
        try:
            existing = db.table("chapters").select("id,version").eq("client_id", req.client_id).eq("chapter_name", req.chapter_name).execute()
            if existing.data:
                db.table("chapters").update({
                    "content": req.content,
                    "word_count": len(req.content.split()),
                    "notes": req.notes or "",
                    "status": "draft"
                }).eq("id", existing.data[0]["id"]).execute()
            else:
                db.table("chapters").insert({
                    "id": str(uuid.uuid4()),
                    "client_id": req.client_id,
                    "chapter_name": req.chapter_name,
                    "content": req.content,
                    "word_count": len(req.content.split()),
                    "notes": req.notes or "",
                    "status": "draft",
                    "version": 1
                }).execute()
        except Exception as e:
            print(f"Save draft error: {e}")
            return {"status": "error", "message": str(e)}
    return {"status": "saved"}

@router.get("/{client_id}/{chapter_name}")
def get_chapter_content(client_id: str, chapter_name: str):
    db = get_db()
    if db:
        try:
            r = db.table("chapters").select("*").eq("client_id", client_id).eq("chapter_name", chapter_name).execute()
            if r.data:
                ch = r.data[0]
                if isinstance(ch.get("sources"), str):
                    try: ch["sources"] = json.loads(ch["sources"])
                    except: ch["sources"] = []
                return ch
        except Exception as e:
            print(f"Get chapter error: {e}")
    return {"content": "", "word_count": 0, "status": "not_started", "sources": []}

@router.get("/{client_id}/export/full")
def export_full(client_id: str):
    client = get_client_data(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    db = get_db()
    chapters = []
    if db:
        try:
            r = db.table("chapters").select("*").eq("client_id", client_id).execute()
            chapters = r.data or []
        except Exception:
            pass
    docx_bytes = export_full_dissertation_docx(
        client_name=client.get("name", ""),
        institution=client.get("institution", ""),
        topic=client.get("topic", ""),
        chapters=chapters
    )
    safe_name = client.get("name", "dissertation").replace(" ", "_").lower()
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}_dissertation.docx"'}
    )

@router.get("/{client_id}/export/{chapter_name}")
def export_chapter(client_id: str, chapter_name: str):
    client = get_client_data(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    db = get_db()
    content = ""
    if db:
        try:
            r = db.table("chapters").select("content").eq("client_id", client_id).eq("chapter_name", chapter_name).execute()
            if r.data:
                content = r.data[0]["content"]
        except Exception:
            pass
    if not content:
        raise HTTPException(404, "No content for this chapter yet")
    docx_bytes = export_chapter_docx(
        title=chapter_name,
        content=content,
        client_name=client.get("name", ""),
        institution=client.get("institution", "")
    )
    safe = chapter_name.replace(":", "").replace(" ", "_").lower()
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{safe}.docx"'}
    )
