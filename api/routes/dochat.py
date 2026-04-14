from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
import uuid, os, asyncio, json
from api.integrations.supabase_client import get_db
from google import genai
from google.genai import types

router = APIRouter()
_jobs = {}

class DocChatRequest(BaseModel):
    client_id: str
    instruction: str          # user's chat message e.g. "fix the intro" or "chapter 3 is too thin"
    current_doc: str          # the full document text as it stands
    mode: str = "edit"        # "edit" | "generate" | "ask"

class SaveDocRequest(BaseModel):
    client_id: str
    content: str
    chapter_map: Optional[dict] = None  # maps chapter name -> char position

async def run_doc_edit(job_id: str, client_id: str, instruction: str, current_doc: str):
    db = get_db()
    client_data = {}
    try:
        if db:
            r = db.table("clients").select("*").eq("id", client_id).single().execute()
            if r.data: client_data = r.data
    except: pass

    # Get scratchpad context
    scratch = ""
    try:
        if db:
            r = db.table("scratchpad").select("content,ai_summary").eq("client_id", client_id).execute()
            if r.data:
                scratch = r.data[0].get("ai_summary") or r.data[0].get("content","")[:500]
    except: pass

    voice = client_data.get("voice_summary","")
    topic = client_data.get("topic","")
    degree = client_data.get("degree","doctoral")
    citation = client_data.get("citation_style","APA 7th")

    prompt = f"""You are editing a {degree} dissertation on: {topic}
Citation style: {citation}
{f"Researcher's notes/context: {scratch}" if scratch else ""}
{f"Writing voice profile: {voice[:400]}" if voice else ""}

USER INSTRUCTION: {instruction}

CURRENT DISSERTATION (full document):
{current_doc[:15000]}

Task: Apply the user's instruction to the dissertation. 
- If they say "fix the intro" — rewrite the introduction section
- If they say "chapter 2 is too thin" — expand chapter 2 with more depth and sources
- If they say "make it sound more human" — adjust tone throughout
- If they say "the methodology needs more detail" — expand that section
- If they say "add more citations" — weave in more academic references
- Keep ALL sections that aren't being edited EXACTLY as they are
- Only change what the instruction asks for
- Maintain APA 7th citation format throughout
- Return the COMPLETE dissertation with the edit applied — every section, start to finish
- Do not add commentary, just return the full edited document"""

    try:
        _jobs[job_id]["status"] = "thinking"
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        response = await asyncio.to_thread(
            lambda: client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=16000,
                    temperature=0.68
                )
            )
        )
        content = response.text or ""
        word_count = len(content.split())

        # Save to supabase as a single "full_doc" chapter
        if db:
            try:
                existing = db.table("chapters").select("id").eq("client_id", client_id).eq("chapter_name", "__full_doc__").execute()
                if existing.data:
                    db.table("chapters").update({
                        "content": content,
                        "word_count": word_count,
                        "status": "draft"
                    }).eq("id", existing.data[0]["id"]).execute()
                else:
                    db.table("chapters").insert({
                        "id": str(uuid.uuid4()),
                        "client_id": client_id,
                        "chapter_name": "__full_doc__",
                        "content": content,
                        "word_count": word_count,
                        "status": "draft",
                        "sort_order": 999,
                        "version": 1
                    }).execute()
            except Exception as e:
                print(f"Save full doc error: {e}")

        _jobs[job_id]["status"] = "complete"
        _jobs[job_id]["content"] = content
        _jobs[job_id]["word_count"] = word_count

    except Exception as e:
        print(f"DocChat error: {e}")
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = str(e)


@router.post("/edit")
async def doc_edit(req: DocChatRequest, bg: BackgroundTasks):
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "queued", "content": "", "word_count": 0}
    bg.add_task(run_doc_edit, job_id, req.client_id, req.instruction, req.current_doc)
    return {"job_id": job_id}


@router.get("/job/{job_id}")
def get_job(job_id: str):
    j = _jobs.get(job_id)
    if not j: return {"status": "not_found"}
    return j


@router.post("/save")
async def save_doc(req: SaveDocRequest):
    db = get_db()
    if db:
        try:
            word_count = len(req.content.split())
            existing = db.table("chapters").select("id").eq("client_id", req.client_id).eq("chapter_name", "__full_doc__").execute()
            if existing.data:
                db.table("chapters").update({
                    "content": req.content,
                    "word_count": word_count,
                    "status": "draft"
                }).eq("id", existing.data[0]["id"]).execute()
            else:
                db.table("chapters").insert({
                    "id": str(uuid.uuid4()),
                    "client_id": req.client_id,
                    "chapter_name": "__full_doc__",
                    "content": req.content,
                    "word_count": word_count,
                    "status": "draft",
                    "sort_order": 999,
                    "version": 1
                }).execute()
        except Exception as e:
            print(f"Save doc error: {e}")
            return {"status": "error", "message": str(e)}
    return {"status": "saved"}


@router.get("/load/{client_id}")
async def load_doc(client_id: str):
    db = get_db()
    if db:
        try:
            # Try full doc first
            r = db.table("chapters").select("content,word_count,updated_at").eq("client_id", client_id).eq("chapter_name", "__full_doc__").execute()
            if r.data and r.data[0].get("content"):
                return {"content": r.data[0]["content"], "word_count": r.data[0]["word_count"], "source": "full_doc"}
            # Otherwise stitch chapters together
            r2 = db.table("chapters").select("chapter_name,content,sort_order").eq("client_id", client_id).neq("chapter_name","__full_doc__").order("sort_order").execute()
            if r2.data:
                parts = []
                for ch in r2.data:
                    if ch.get("content"):
                        parts.append(f"# {ch['chapter_name']}\n\n{ch['content']}")
                if parts:
                    full = "\n\n---\n\n".join(parts)
                    return {"content": full, "word_count": len(full.split()), "source": "stitched"}
        except Exception as e:
            print(f"Load doc error: {e}")
    return {"content": "", "word_count": 0, "source": "empty"}
