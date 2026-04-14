from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
import uuid, os, asyncio
from api.integrations.supabase_client import get_db
from google import genai
from google.genai import types

router = APIRouter()
_jobs = {}


def get_client_data(client_id: str) -> dict:
    db = get_db()
    if db:
        try:
            r = db.table("clients").select("*").eq("id", client_id).single().execute()
            if r.data: return r.data
        except: pass
    if client_id == "mitchell-dba-ulv-001":
        from api.routes.clients import MITCHELL_DATA
        return MITCHELL_DATA
    return {}


def get_scratch(client_id: str) -> str:
    db = get_db()
    if db:
        try:
            r = db.table("scratchpad").select("content,ai_summary").eq("client_id", client_id).execute()
            if r.data:
                return r.data[0].get("ai_summary") or r.data[0].get("content","")[:800]
        except: pass
    return ""


async def save_full_doc(client_id: str, content: str):
    db = get_db()
    if not db: return
    try:
        word_count = len(content.split())
        existing = db.table("chapters").select("id").eq("client_id", client_id).eq("chapter_name","__full_doc__").execute()
        if existing.data:
            db.table("chapters").update({"content": content, "word_count": word_count, "status": "draft"}).eq("id", existing.data[0]["id"]).execute()
        else:
            db.table("chapters").insert({
                "id": str(uuid.uuid4()), "client_id": client_id,
                "chapter_name": "__full_doc__", "content": content,
                "word_count": word_count, "status": "draft", "sort_order": 999, "version": 1
            }).execute()
    except Exception as e:
        print(f"Save doc error: {e}")


async def run_job(job_id: str, client_id: str, instruction: str, current_doc: str):
    client_data = get_client_data(client_id)
    scratch = get_scratch(client_id)
    voice = client_data.get("voice_summary","")
    topic = client_data.get("topic","")
    degree = client_data.get("degree","doctoral")
    field = client_data.get("field","")
    institution = client_data.get("institution","")
    citation = client_data.get("citation_style","APA 7th")
    formatting = client_data.get("formatting_notes","")
    intake = client_data.get("intake_context","")

    is_empty = not current_doc.strip() or len(current_doc.strip()) < 100

    if is_empty:
        # GENERATE mode — write from scratch
        prompt = f"""You are a doctoral-level academic ghostwriter. Write a complete {degree} dissertation.

CLIENT INFO:
Name context: {degree} student at {institution}
Field: {field}
Research Topic: {topic}
Citation Style: {citation}
{f"Formatting requirements: {formatting}" if formatting else ""}
{f"Additional context: {intake}" if intake else ""}
{f"Research notes from student: {scratch}" if scratch else ""}
{f"Write to match this voice profile: {voice[:400]}" if voice else ""}

USER REQUEST: {instruction}

Write the complete dissertation now. Include all chapters: Abstract, Chapter I through V, and References.
Use proper {citation} citations with real academic sources.
Format chapter titles clearly (e.g. CHAPTER I, CHAPTER II).
Write at doctoral quality — rigorous, cited, academic.
Do NOT include any preamble or meta-commentary. Just the dissertation."""
    else:
        # EDIT mode — modify existing doc
        prompt = f"""You are editing a {degree} dissertation on: {topic}
Field: {field} | Institution: {institution} | Citation: {citation}
{f"Student's research notes: {scratch}" if scratch else ""}
{f"Voice profile (match this style): {voice[:300]}" if voice else ""}

USER INSTRUCTION: {instruction}

FULL DISSERTATION (current version):
{current_doc[:14000]}

Apply the instruction precisely:
- Only change what was asked
- Keep everything else EXACTLY as-is  
- Maintain {citation} format throughout
- Return the COMPLETE dissertation from start to finish
- No commentary, no preamble — just the full updated dissertation"""

    try:
        _jobs[job_id]["status"] = "working"
        gc = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        response = await asyncio.to_thread(
            lambda: gc.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=16000,
                    temperature=0.7
                )
            )
        )
        content = response.text or ""
        word_count = len(content.split())
        await save_full_doc(client_id, content)
        _jobs[job_id].update({"status":"complete","content":content,"word_count":word_count})
    except Exception as e:
        print(f"Job error: {e}")
        _jobs[job_id].update({"status":"failed","error":str(e)})


class DocChatReq(BaseModel):
    client_id: str
    instruction: str
    current_doc: str
    mode: str = "auto"

class SaveDocReq(BaseModel):
    client_id: str
    content: str

class IntakeUpdateReq(BaseModel):
    client_id: str
    intake_context: str


@router.post("/edit")
async def doc_edit(req: DocChatReq, bg: BackgroundTasks):
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status":"queued","content":"","word_count":0}
    bg.add_task(run_job, job_id, req.client_id, req.instruction, req.current_doc)
    return {"job_id": job_id}


@router.get("/job/{job_id}")
def get_job(job_id: str):
    j = _jobs.get(job_id)
    if not j: return {"status":"not_found"}
    return j


@router.post("/save")
async def save_doc(req: SaveDocReq):
    await save_full_doc(req.client_id, req.content)
    return {"status":"saved"}


@router.post("/intake")
async def update_intake(req: IntakeUpdateReq):
    """Save intake context (rubric, assignment type, etc) to client record."""
    db = get_db()
    if db:
        try:
            db.table("clients").update({"formatting_notes": req.intake_context}).eq("id", req.client_id).execute()
        except Exception as e:
            print(f"Intake update error: {e}")
    return {"status":"saved"}


@router.get("/load/{client_id}")
async def load_doc(client_id: str):
    db = get_db()
    if db:
        try:
            # Try full doc first
            r = db.table("chapters").select("content,word_count").eq("client_id", client_id).eq("chapter_name","__full_doc__").execute()
            if r.data and r.data[0].get("content"):
                return {"content": r.data[0]["content"], "word_count": r.data[0]["word_count"] or 0, "source":"full_doc"}
            # Stitch from individual chapters that have content
            r2 = db.table("chapters").select("chapter_name,content,sort_order").eq("client_id", client_id).neq("chapter_name","__full_doc__").order("sort_order").execute()
            if r2.data:
                parts = []
                for ch in r2.data:
                    c = ch.get("content","").strip()
                    if c and len(c) > 50:
                        parts.append(f"# {ch['chapter_name']}\n\n{c}")
                if parts:
                    full = "\n\n---\n\n".join(parts)
                    # auto-save stitched version
                    await save_full_doc(client_id, full)
                    return {"content": full, "word_count": len(full.split()), "source":"stitched"}
        except Exception as e:
            print(f"Load doc error: {e}")
    return {"content":"","word_count":0,"source":"empty"}
