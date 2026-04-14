import asyncio, os, httpx
from typing import List, Dict

HEADERS = {"User-Agent": "DissertationPlatform/1.0 (academic research)"}

async def search_crossref(query: str, rows: int = 8) -> List[str]:
    try:
        url = f"https://api.crossref.org/works?query={query}&rows={rows}&select=title,author,published,DOI,container-title"
        async with httpx.AsyncClient(timeout=12) as c:
            r = await c.get(url, headers=HEADERS)
            items = r.json().get("message", {}).get("items", [])
            results = []
            for item in items:
                title = (item.get("title") or [""])[0]
                authors = item.get("author", [])
                author_str = authors[0].get("family", "") if authors else "Unknown"
                year = (item.get("published", {}).get("date-parts") or [[""]])[0][0]
                journal = (item.get("container-title") or [""])[0]
                doi = item.get("DOI", "")
                results.append(f"{author_str} ({year}). {title}. {journal}. https://doi.org/{doi}")
            return results
    except Exception as e:
        print(f"CrossRef error: {e}")
        return []

async def search_openalex(query: str, per_page: int = 8) -> List[str]:
    try:
        url = f"https://api.openalex.org/works?search={query}&per-page={per_page}&select=title,authorships,publication_year,primary_location,doi"
        async with httpx.AsyncClient(timeout=12) as c:
            r = await c.get(url, headers=HEADERS)
            items = r.json().get("results", [])
            results = []
            for item in items:
                title = item.get("title", "")
                authors = item.get("authorships", [])
                author_str = authors[0].get("author", {}).get("display_name", "Unknown") if authors else "Unknown"
                year = item.get("publication_year", "")
                loc = item.get("primary_location") or {}
                source = (loc.get("source") or {}).get("display_name", "")
                doi = item.get("doi", "") or ""
                results.append(f"{author_str} ({year}). {title}. {source}. {doi}")
            return results
    except Exception as e:
        print(f"OpenAlex error: {e}")
        return []

async def search_semantic_scholar(query: str, limit: int = 8) -> List[str]:
    try:
        url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={query}&limit={limit}&fields=title,authors,year,venue,externalIds"
        async with httpx.AsyncClient(timeout=12) as c:
            r = await c.get(url, headers=HEADERS)
            items = r.json().get("data", [])
            results = []
            for item in items:
                title = item.get("title", "")
                authors = item.get("authors", [])
                author_str = authors[0].get("name", "Unknown") if authors else "Unknown"
                year = item.get("year", "")
                venue = item.get("venue", "")
                doi = (item.get("externalIds") or {}).get("DOI", "")
                results.append(f"{author_str} ({year}). {title}. {venue}. {'https://doi.org/'+doi if doi else ''}")
            return results
    except Exception as e:
        print(f"Semantic Scholar error: {e}")
        return []

async def research_chapter(topic: str, chapter_type: str, existing_context: str = "") -> Dict:
    query = f"{topic} {chapter_type}"
    cr, oa, ss = await asyncio.gather(
        search_crossref(query, 10),
        search_openalex(query, 10),
        search_semantic_scholar(query, 10)
    )
    all_sources = list({s for s in cr + oa + ss if s.strip()})
    context = f"Topic: {topic}\nChapter: {chapter_type}\n"
    if existing_context:
        context += f"\nExisting work context:\n{existing_context[:2000]}\n"
    context += f"\nVerified academic sources ({len(all_sources)} found):\n" + "\n".join(all_sources[:20])
    return {
        "sources": all_sources[:20],
        "source_count": len(all_sources),
        "context": context,
        "method": "crossref+openalex+semanticscholar"
    }
