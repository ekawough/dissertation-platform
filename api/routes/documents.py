from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import JSONResponse
import uuid, os, asyncio, json, traceback
from api.integrations.supabase_client import get_db

router = APIRouter()


async def _extract_style(text: str, filename: str) -> dict:
    """Gemini extracts voice/style from a writing sample. Never raises."""
    try:
        from google import genai
        from google.genai import types
        prompt = f"""Analyze this writing sample and extract the author's style profile for a doctoral dissertation.

Document: {filename}
Content:
{text[:3500]}

Return ONLY valid JSON, no markdown, no backticks:
{{
  "voice_traits": ["specific trait 1", "specific trait 2", "specific trait 3"],
  "sentence_style": "short description of sentence length and rhythm",
  "vocabulary_level": "description of vocabulary complexity",
  "tone": "academic tone description",
  "style_summary": "2-3 sentences instructing AI how to match this writer's voice exactly"
}}"""

        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        response = await asyncio.to_thread(
            lambda: client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(max_output_tokens=600, temperature=0.2)
            )
        )
        raw = response.text.strip()
        # strip markdown fences if present
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception as e:
        print(f"Style extract error: {e}")
        return {
            "voice_traits": [],
            "tone": "academic",
            "style_summary": f"Writing sample uploaded from {filename}. Match the academic tone and vocabulary level found in this document."
        }


async def _rebuild_voice(client_id: str, db) -> None:
    """Rebuild master voice summary from all docs. Never raises."""
    try:
        r = db.table("client_documents").select("extracted_style,filename").eq("client_id", client_id).execute()
        summaries = []
        for doc in (r.data or []):
            try:
                s = json.loads(doc.get("extracted_style") or "{}")
                summary = s.get("style_summary", "")
                if summary:
                    summaries.append(f"[{doc['filename']}]: {summary}")
            except Exception:
                pass
        voice = "\n".join(summaries)[:3000]
        db.table("clients").update({"voice_summary": voice}).eq("id", client_id).execute()
    except Exception as e:
        print(f"Rebuild voice error: {e}")


@router.get("/{client_id}")
def list_documents(client_id: str):
    try:
        db = get_db()
        if db:
            r = db.table("client_documents") \
                .select("id,filename,file_type,doc_type,word_count,extracted_style,created_at") \
                .eq("client_id", client_id) \
                .order("created_at", desc=True) \
                .execute()
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
    try:
        raw_bytes = await file.read()

        # decode bytes to text
        content_text = ""
        for enc in ["utf-8", "latin-1", "cp1252"]:
            try:
                content_text = raw_bytes.decode(enc)
                break
            except Exception:
                continue
        if not content_text:
            content_text = raw_bytes.decode("utf-8", errors="ignore")

        # strip null bytes
        content_text = content_text.replace("\x00", "")
        word_count = len(content_text.split())
        doc_id = str(uuid.uuid4())

        # extract style (never fails)
        style_data = await _extract_style(content_text, file.filename or "document")

        db = get_db()
        doc_row = {
            "id": doc_id,
            "client_id": client_id,
            "filename": file.filename or "unnamed",
            "file_type": file.content_type or "text/plain",
            "content": content_text[:50000],
            "doc_type": doc_type,
            "extracted_style": json.dumps(style_data),
            "word_count": word_count,
        }

        if db:
            db.table("client_documents").insert(doc_row).execute()
            await _rebuild_voice(client_id, db)

        return JSONResponse({
            "doc_id": doc_id,
            "filename": file.filename,
            "word_count": word_count,
            "style": style_data,
            "status": "ok"
        })

    except Exception as e:
        tb = traceback.format_exc()
        print(f"UPLOAD ERROR:\n{tb}")
        return JSONResponse(
            status_code=500,
            content={"detail": str(e), "status": "error"}
        )


@router.delete("/{doc_id}")
async def delete_document(doc_id: str):
    try:
        db = get_db()
        if db:
            r = db.table("client_documents").select("client_id").eq("id", doc_id).execute()
            client_id = r.data[0]["client_id"] if r.data else None
            db.table("client_documents").delete().eq("id", doc_id).execute()
            if client_id:
                await _rebuild_voice(client_id, db)
        return {"status": "deleted"}
    except Exception as e:
        print(f"Delete doc error: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})


@router.get("/voice/{client_id}")
def get_voice(client_id: str):
    try:
        db = get_db()
        if db:
            r = db.table("clients").select("voice_summary").eq("id", client_id).execute()
            if r.data:
                return {"voice_summary": r.data[0].get("voice_summary") or ""}
    except Exception as e:
        print(f"Get voice error: {e}")
    return {"voice_summary": ""}
