import os, asyncio
from datetime import datetime

async def log_to_notion(client_name: str, chapter: str, status: str, notes: str = ""):
    try:
        token = os.getenv("NOTION_TOKEN")
        db_id = os.getenv("NOTION_DATABASE_ID")
        if not token or not db_id:
            return None
        from notion_client import AsyncClient
        notion = AsyncClient(auth=token)
        page = await notion.pages.create(
            parent={"database_id": db_id},
            properties={
                "Name": {"title": [{"text": {"content": f"{client_name} — {chapter}"}}]},
                "Status": {"select": {"name": status}},
                "Notes": {"rich_text": [{"text": {"content": notes[:2000]}}]},
                "Date": {"date": {"start": datetime.now().isoformat()}},
            }
        )
        return page.get("url")
    except Exception as e:
        print(f"Notion log error: {e}")
        return None
