from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import uuid, os, asyncio
from api.integrations.supabase_client import get_db
from google import genai
from google.genai import types

router = APIRouter()

class ScratchpadUpdate(BaseModel):
    client_id: str
    content: str

class SummarizeRequest(BaseModel):
    client_id: str

def get_or_create(client_id: str) -> dict:
    db = get_db()
    if db:
        try:
            r = db.table("scratchpad").select("*").eq("client_id", client_id).execute()
            if r.data:
                return r.data[0]
            # create new
            pad = {"id": str(uuid.uuid4()), "client_id": client_id, "content": "", "ai_summary": ""}
            db.table("scratchpad").insert(pad).execute()
            return pad
        except Exception as e:
            print(f"Scratchpad error: {e}")
    return {"id": str(uuid.uuid4()), "client_id": client_id, "content": "", "ai_summary": ""}

@router.get("/{client_id}")
def get_scratchpad(client_id: str):
    return get_or_create(client_id)

@router.post("/save")
def save_scratchpad(req: ScratchpadUpdate):
    db = get_db()
    pad = get_or_create(req.client_id)
    if db:
        try:
            db.table("scratchpad").update({
                "content": req.content,
                "updated_at": "NOW()"
            }).eq("id", pad["id"]).execute()
        except Exception as e:
            print(f"Save scratchpad error: {e}")
    return {"status": "saved"}

@router.post("/summarize")
async def summarize_scratchpad(req: SummarizeRequest):
    pad = get_or_create(req.client_id)
    content = pad.get("content", "").strip()
    if not content:
        return {"summary": "", "key_points": []}

    prompt = f"""You are an academic writing assistant. A doctoral student has the following notes, ideas, and research in their dissertation scratchpad.

SCRATCHPAD CONTENT:
{content[:6000]}

Please:
1. Write a concise 2-3 sentence summary of their main research ideas and key themes
2. Extract 5-8 specific key points, themes, or arguments that should inform their dissertation chapters
3. Identify any specific sources, authors, or theories mentioned

Return ONLY a JSON object:
{{
  "summary": "2-3 sentence summary here",
  "key_points": ["point 1", "point 2", "point 3", "point 4", "point 5"],
  "sources_mentioned": ["source 1", "source 2"]
}}"""

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    response = await asyncio.to_thread(
        lambda: client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(max_output_tokens=1024, temperature=0.3)
        )
    )

    import json
    text = response.text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"): text = text[4:]
        text = text.strip()

    try:
        result = json.loads(text)
    except Exception:
        result = {"summary": text[:500], "key_points": [], "sources_mentioned": []}

    # save summary back
    db = get_db()
    if db:
        try:
            db.table("scratchpad").update({"ai_summary": result.get("summary","")}).eq("id", pad["id"]).execute()
        except Exception:
            pass

    return result
