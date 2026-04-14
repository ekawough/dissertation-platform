from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional
import uuid, os, asyncio
from api.integrations.supabase_client import get_db
from google import genai
from google.genai import types

router = APIRouter()

class ExtractStyleRequest(BaseModel):
    client_id: str

async def extract_style_from_text(text: str, filename: str) -> dict:
    """Use Gemini to extract writing style, tone, vocabulary from a document."""
    prompt = f"""Analyze this writing sample from a doctoral student and extract their writing style profile.

Document: {filename}
Content (first 4000 chars):
{text[:4000]}

Return ONLY a JSON object:
{{
  "voice_traits": ["trait 1", "trait 2", "trait 3", "trait 4"],
  "sentence_style": "description of sentence structure and rhythm",
  "vocabulary_level": "description of vocabulary complexity and choices",
  "tone": "description of academic tone",
  "notable_patterns": ["pattern 1", "pattern 2"],
  "style_summary": "2-3 sentence summary to instruct AI to match this writer's voice"
}}"""

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    response = await asyncio.to_thread(
        lambda: client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(max_output_tokens=800, temperature=0.2)
        )
    )
    import json
    text_resp = response.text.strip()
    if text_resp.startswith("```"):
        text_resp = text_resp.split("```")[1]
        if text_resp.startswith("json"): text_resp = text_resp[4:]
        text_resp = text_resp.strip()
    try:
        return json.loads(text_resp)
    except:
        return {"style_summary": text_resp[:500], "voice_traits": [], "tone": "academic"}

@router.get("/{client_id}")
def list_documents(client_id: str):
    db = get_db()
    if db:
        try:
            r = db.table("client_documents").select("id,filename,file_type,doc_type,word_count,extracted_style,created_at").eq("client_id", client_id).order("created_at", desc=True).execute()
            return {"documents": r.data or []}
        except Exception as e:
            print(f"List docs error: {e}")
    return {"documents": []}

@router.post("/upload")
async def upload_document(
    client_id: str = Form(...),
    doc_type: str = Form("writing_sample"),
    file: UploadFile = File(...)
):
    content_bytes = await file.read()
    # Try to decode as text
    content_text = ""
    for enc in ["utf-8", "latin-1", "cp1252"]:
        try:
            content_text = content_bytes.decode(enc)
            break
        except:
            continue

    if not content_text:
        content_text = content_bytes.decode("utf-8", errors="ignore")

    word_count = len(content_text.split())
    doc_id = str(uuid.uuid4())

    # Extract style using Gemini
    style_data = await extract_style_from_text(content_text, file.filename)

    import json
    db = get_db()
    doc = {
        "id": doc_id,
        "client_id": client_id,
        "filename": file.filename,
        "file_type": file.content_type or "text/plain",
        "content": content_text[:50000],  # store first 50k chars
        "doc_type": doc_type,
        "extracted_style": json.dumps(style_data),
        "word_count": word_count
    }
    if db:
        try:
            db.table("client_documents").insert(doc).execute()
            # Update client voice summary
            await _rebuild_voice_summary(client_id, db)
        except Exception as e:
            print(f"Upload doc error: {e}")

    return {
        "doc_id": doc_id,
        "filename": file.filename,
        "word_count": word_count,
        "style": style_data
    }

async def _rebuild_voice_summary(client_id: str, db):
    """Combine all documents to build a master voice profile for this client."""
    try:
        r = db.table("client_documents").select("extracted_style,filename,doc_type").eq("client_id", client_id).execute()
        if not r.data:
            return
        import json
        summaries = []
        for doc in r.data:
            try:
                style = json.loads(doc.get("extracted_style") or "{}")
                s = style.get("style_summary", "")
                if s:
                    summaries.append(f"[From {doc['filename']}]: {s}")
            except:
                pass
        if summaries:
            voice = "\n".join(summaries)
            db.table("clients").update({"voice_summary": voice[:3000]}).eq("id", client_id).execute()
    except Exception as e:
        print(f"Rebuild voice error: {e}")

@router.delete("/{doc_id}")
def delete_document(doc_id: str):
    db = get_db()
    if db:
        try:
            # get client_id first for voice rebuild
            r = db.table("client_documents").select("client_id").eq("id", doc_id).execute()
            client_id = r.data[0]["client_id"] if r.data else None
            db.table("client_documents").delete().eq("id", doc_id).execute()
            if client_id:
                import asyncio
                asyncio.create_task(_rebuild_voice_summary(client_id, db))
        except Exception as e:
            print(f"Delete doc error: {e}")
    return {"status": "deleted"}

@router.get("/voice/{client_id}")
def get_voice_summary(client_id: str):
    db = get_db()
    if db:
        try:
            r = db.table("clients").select("voice_summary").eq("id", client_id).execute()
            if r.data:
                return {"voice_summary": r.data[0].get("voice_summary", "")}
        except:
            pass
    return {"voice_summary": ""}
