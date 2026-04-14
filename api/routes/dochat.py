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
                return r.data[0].get("ai_summary") or r.data[0].get("content","")[:1000]
        except: pass
    return ""


async def save_full_doc(client_id: str, content: str):
    db = get_db()
    if not db: return
    try:
        wc = len(content.split())
        ex = db.table("chapters").select("id").eq("client_id", client_id).eq("chapter_name","__full_doc__").execute()
        if ex.data:
            db.table("chapters").update({"content": content, "word_count": wc, "status": "draft"}).eq("id", ex.data[0]["id"]).execute()
        else:
            db.table("chapters").insert({
                "id": str(uuid.uuid4()), "client_id": client_id,
                "chapter_name": "__full_doc__", "content": content,
                "word_count": wc, "status": "draft", "sort_order": 999, "version": 1
            }).execute()
    except Exception as e:
        print(f"Save doc error: {e}")


async def run_job(job_id: str, client_id: str, instruction: str, current_doc: str):
    c = get_client_data(client_id)
    scratch = get_scratch(client_id)
    voice = c.get("voice_summary","")
    topic = c.get("topic","")
    degree = c.get("degree","DBA")
    field = c.get("field","")
    institution = c.get("institution","")
    citation = c.get("citation_style","APA 7th")
    formatting = c.get("formatting_notes","")  # also stores intake/rubric
    advisor = c.get("advisor","")
    quality = c.get("quality_target", 75)

    is_empty = not current_doc or len(current_doc.strip()) < 50

    context_block = f"""CLIENT PROFILE:
Degree: {degree} | Field: {field} | Institution: {institution}
Topic: {topic}
Advisor: {advisor or 'Not specified'}
Citation Style: {citation}
Quality Target: {quality}% (write at human doctoral student level, not perfect)
{f"Formatting/Rubric/Requirements:{chr(10)}{formatting}" if formatting else ""}
{f"Research notes from student:{chr(10)}{scratch}" if scratch else ""}
{f"Voice profile (match this writing style):{chr(10)}{voice[:600]}" if voice else ""}"""

    if is_empty:
        prompt = f"""You are a doctoral-level academic ghostwriter. Write a complete {degree} dissertation.

{context_block}

USER REQUEST: {instruction}

Write the full dissertation now. Structure:
- ABSTRACT (250-350 words)
- CHAPTER I: INTRODUCTION (Background, Problem Statement, Purpose, Research Questions, Hypotheses, Significance, Delimitations, Definitions)
- CHAPTER II: REVIEW OF THE LITERATURE (comprehensive, 15+ sources, theoretical frameworks, empirical studies, gaps)
- CHAPTER III: METHODOLOGY (Research Design, Population & Sample, Instrumentation, Data Collection, Analysis Plan, Ethics/IRB)
- CHAPTER IV: RESULTS (present findings, tables, hypothesis testing - mark PENDING IRB if needed)
- CHAPTER V: SUMMARY, CONCLUSIONS, AND RECOMMENDATIONS
- REFERENCES (APA 7th format, 20+ sources)

Use {citation} citations throughout. Write at doctoral quality.
Left-align text. Chapter titles in ALL CAPS. Double-spaced feel.
DO NOT include meta-commentary. Just write the dissertation."""

    else:
        prompt = f"""You are editing a {degree} dissertation.

{context_block}

USER INSTRUCTION: "{instruction}"

CURRENT DISSERTATION:
{current_doc[:14000]}

Apply the instruction. Rules:
- Only change what was asked — keep everything else identical
- Maintain {citation} format throughout  
- Return the COMPLETE dissertation start to finish
- No commentary or preamble — just the updated dissertation"""

    try:
        _jobs[job_id]["status"] = "working"
        gc = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        resp = await asyncio.to_thread(
            lambda: gc.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(max_output_tokens=16000, temperature=0.7)
            )
        )
        content = resp.text or ""
        await save_full_doc(client_id, content)
        _jobs[job_id].update({"status":"complete","content":content,"word_count":len(content.split())})
    except Exception as e:
        print(f"Job error: {e}")
        _jobs[job_id].update({"status":"failed","error":str(e)})


class DocReq(BaseModel):
    client_id: str
    instruction: str
    current_doc: str
    mode: str = "auto"

class SaveReq(BaseModel):
    client_id: str
    content: str

class IntakeReq(BaseModel):
    client_id: str
    intake_context: str


@router.post("/edit")
async def doc_edit(req: DocReq, bg: BackgroundTasks):
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status":"queued","content":"","word_count":0}
    bg.add_task(run_job, job_id, req.client_id, req.instruction, req.current_doc)
    return {"job_id": job_id}


@router.get("/job/{job_id}")
def get_job(job_id: str):
    return _jobs.get(job_id) or {"status":"not_found"}


@router.post("/save")
async def save_doc(req: SaveReq):
    await save_full_doc(req.client_id, req.content)
    return {"status":"saved"}


@router.post("/intake")
async def update_intake(req: IntakeReq):
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
            # Try full_doc first
            r = db.table("chapters").select("content,word_count").eq("client_id", client_id).eq("chapter_name","__full_doc__").execute()
            if r.data and r.data[0].get("content","").strip():
                d = r.data[0]
                return {"content": d["content"], "word_count": d.get("word_count",0) or len(d["content"].split()), "source":"full_doc"}
            # Stitch individual chapters
            r2 = db.table("chapters").select("chapter_name,content,sort_order").eq("client_id", client_id).neq("chapter_name","__full_doc__").order("sort_order").execute()
            if r2.data:
                parts = [f"# {ch['chapter_name']}\n\n{ch['content'].strip()}" for ch in r2.data if (ch.get("content") or "").strip()]
                if parts:
                    full = "\n\n---\n\n".join(parts)
                    await save_full_doc(client_id, full)
                    return {"content": full, "word_count": len(full.split()), "source":"stitched"}
        except Exception as e:
            print(f"Load error: {e}")
    return {"content":"","word_count":0,"source":"empty"}
