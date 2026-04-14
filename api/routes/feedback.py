from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, List
import uuid, json, os, asyncio
from api.integrations.supabase_client import get_db
from api.agents.researcher import research_chapter
from api.agents.writer import revise_with_feedback

router = APIRouter()

# Track bulk revision jobs in memory
_bulk_jobs = {}

class FeedbackRequest(BaseModel):
    client_id: str
    feedback: str
    scope: str = "all"           # "all" or "selected"
    chapters: Optional[List[str]] = None  # if scope=selected

class FeedbackLogEntry(BaseModel):
    client_id: str

def get_client(client_id: str) -> dict:
    db = get_db()
    if db:
        try:
            r = db.table("clients").select("*").eq("id", client_id).single().execute()
            if r.data:
                return r.data
        except Exception:
            pass
    # fallback Mitchell
    if client_id == "mitchell-dba-ulv-001":
        from api.routes.clients import MITCHELL_DATA
        return MITCHELL_DATA
    return {}

def get_all_chapters(client_id: str) -> list:
    db = get_db()
    if db:
        try:
            r = db.table("chapters").select("*").eq("client_id", client_id).order("sort_order").execute()
            if r.data:
                return r.data
        except Exception:
            pass
    return []

async def run_bulk_revision(job_id: str, client_id: str, feedback: str, chapter_names: list):
    """Rewrite multiple chapters with the same feedback, maintaining dissertation coherence."""
    db = get_db()
    client = get_client(client_id)
    total = len(chapter_names)

    _bulk_jobs[job_id]["total"] = total
    _bulk_jobs[job_id]["done"] = 0
    _bulk_jobs[job_id]["status"] = "running"
    _bulk_jobs[job_id]["results"] = []

    # Build shared dissertation context for coherence
    dissertation_context = f"""
This is a {client.get('degree','doctoral')} dissertation on: {client.get('topic','')}
Field: {client.get('field','')} | Institution: {client.get('institution','')}
Citation style: {client.get('citation_style','APA 7th')}

PROFESSOR FEEDBACK TO ADDRESS IN EVERY CHAPTER:
{feedback}

IMPORTANT: These chapters must work together as one coherent dissertation.
Each chapter should be revised with awareness of the others.
Do not repeat information between chapters unnecessarily.
Build on the same theoretical framework and argument across all chapters.
"""

    errors = []
    for i, chapter_name in enumerate(chapter_names):
        _bulk_jobs[job_id]["current_chapter"] = chapter_name
        _bulk_jobs[job_id]["progress"] = int((i / total) * 90)

        try:
            # Get existing content
            existing_content = ""
            if db:
                r = db.table("chapters").select("content,id").eq("client_id", client_id).eq("chapter_name", chapter_name).execute()
                if r.data and r.data[0].get("content"):
                    existing_content = r.data[0]["content"]
                    chapter_db_id = r.data[0]["id"]
                else:
                    chapter_db_id = None
            
            if not existing_content:
                _bulk_jobs[job_id]["results"].append({
                    "chapter": chapter_name,
                    "status": "skipped",
                    "reason": "No existing draft to revise"
                })
                _bulk_jobs[job_id]["done"] += 1
                continue

            # Revise with full dissertation context
            result = await revise_with_feedback(
                existing_content=existing_content,
                professor_feedback=dissertation_context,
                topic=client.get("topic", ""),
                chapter_type=chapter_name
            )

            # Save back to Supabase
            if db and chapter_db_id:
                db.table("chapters").update({
                    "content": result["content"],
                    "word_count": result["word_count"],
                    "status": "revised",
                    "professor_feedback": feedback,
                    "version": 999  # mark as bulk-revised
                }).eq("id", chapter_db_id).execute()

            _bulk_jobs[job_id]["results"].append({
                "chapter": chapter_name,
                "status": "revised",
                "word_count": result["word_count"]
            })

        except Exception as e:
            print(f"Bulk revision error for {chapter_name}: {e}")
            errors.append(f"{chapter_name}: {str(e)[:100]}")
            _bulk_jobs[job_id]["results"].append({
                "chapter": chapter_name,
                "status": "error",
                "error": str(e)[:100]
            })

        _bulk_jobs[job_id]["done"] += 1
        await asyncio.sleep(0.5)  # small delay between chapters

    # Save feedback to log
    if db:
        try:
            db.table("feedback_log").insert({
                "id": str(uuid.uuid4()),
                "client_id": client_id,
                "feedback": feedback,
                "scope": "all" if len(chapter_names) == total else "selected",
                "chapters_affected": json.dumps(chapter_names),
                "status": "applied"
            }).execute()
        except Exception:
            pass

    _bulk_jobs[job_id]["status"] = "complete" if not errors else "complete_with_errors"
    _bulk_jobs[job_id]["errors"] = errors
    _bulk_jobs[job_id]["progress"] = 100


@router.post("/apply")
async def apply_feedback(req: FeedbackRequest, bg: BackgroundTasks):
    db = get_db()
    
    # Get chapters to revise
    if req.scope == "all" or not req.chapters:
        all_chs = get_all_chapters(req.client_id)
        # Only revise chapters that have content
        chapter_names = [
            ch["chapter_name"] 
            for ch in all_chs 
            if ch.get("content") and ch.get("status") not in ["pending_irb"]
        ]
        if not chapter_names:
            # fallback: get all chapter names even without content
            chapter_names = [ch["chapter_name"] for ch in all_chs]
    else:
        chapter_names = req.chapters

    if not chapter_names:
        return {"error": "No chapters found to revise", "job_id": None}

    job_id = str(uuid.uuid4())
    _bulk_jobs[job_id] = {
        "status": "queued",
        "progress": 0,
        "total": len(chapter_names),
        "done": 0,
        "current_chapter": "",
        "results": [],
        "errors": [],
        "chapters": chapter_names
    }

    bg.add_task(run_bulk_revision, job_id, req.client_id, req.feedback, chapter_names)
    return {"job_id": job_id, "chapters_queued": len(chapter_names)}


@router.get("/job/{job_id}")
def get_job(job_id: str):
    job = _bulk_jobs.get(job_id)
    if not job:
        return {"status": "not_found"}
    return job


@router.get("/log/{client_id}")
def get_feedback_log(client_id: str):
    db = get_db()
    if db:
        try:
            r = db.table("feedback_log").select("*").eq("client_id", client_id).order("created_at", desc=True).limit(20).execute()
            return {"entries": r.data or []}
        except Exception as e:
            print(f"Feedback log error: {e}")
    return {"entries": []}


@router.delete("/log/{entry_id}")
def delete_log_entry(entry_id: str):
    db = get_db()
    if db:
        try:
            db.table("feedback_log").delete().eq("id", entry_id).execute()
        except Exception:
            pass
    return {"status": "deleted"}
