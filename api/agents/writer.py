import os, asyncio
from typing import Optional
from google import genai
from google.genai import types

CHAPTER_PROMPTS = {
    "Chapter I: Introduction": """Write Chapter I: INTRODUCTION of a doctoral dissertation.
Required sections: Background of the Problem, Statement of the Problem, Purpose of the Study,
Research Questions, Hypotheses (H1/H0 pairs), Significance of the Study, Delimitations,
Definition of Terms, Organization of the Study.""",

    "Chapter II: Literature Review": """Write Chapter II: REVIEW OF THE LITERATURE of a doctoral dissertation.
This chapter MUST be comprehensive. Include: theoretical frameworks, key empirical studies,
meta-analyses, moderating/mediating variables, gaps in the literature, and synthesis of findings.
Minimum 8-10 major themes with multiple citations each.""",

    "Chapter III: Methodology": """Write Chapter III: METHODOLOGY of a doctoral dissertation.
Required sections: Research Design, Research Questions restated, Population and Sample,
Instrumentation (with reliability/validity), Data Collection Procedures, Data Analysis Plan,
Ethical Considerations/IRB, Assumptions, Limitations.""",

    "Chapter IV: Results": """Write Chapter IV: RESULTS of a doctoral dissertation.
Present findings systematically. Include: Descriptive Statistics, Reliability Analysis,
Hypothesis Testing results (accept/reject for each H1/H0 pair), Tables and Figures references,
Summary of Findings. Note: Mark as PENDING IRB if data not yet collected.""",

    "Chapter V: Discussion": """Write Chapter V: SUMMARY, CONCLUSIONS, AND RECOMMENDATIONS of a doctoral dissertation.
Required sections: Summary of the Study, Discussion of Findings (tied back to literature),
Conclusions, Implications for Practice, Recommendations for Future Research, Limitations.""",

    "Abstract": """Write a doctoral dissertation Abstract.
Format: 4 paragraphs covering Purpose, Theoretical Framework/Methodology, Findings, Conclusions.
Maximum 350 words. No citations. Third person.""",

    "Literature Review Section": """Write an expanded literature review section for a doctoral dissertation chapter.
Be comprehensive, synthesize multiple sources, identify themes, gaps, and theoretical connections.""",

    "Custom Section": """Write the requested section of a doctoral dissertation at doctoral level quality."""
}

FORMATTING_RULES = """
CRITICAL FORMATTING RULES — FOLLOW EXACTLY:
- Writing style: ~75% quality — solid doctoral work but reads like a committed student, not a ghost-written perfect document
- Paragraph alignment: LEFT-ALIGNED with ragged right margin (NOT justified)
- Font: Times New Roman, 12pt, double-spaced (note this in content structure)
- Chapter titles: ALL CAPS, centered (e.g., CHAPTER I, then INTRODUCTION on next line)
- APA 7th edition citations throughout
- Heading levels: Level 1 = bold centered, Level 2 = bold left-aligned, Level 3 = bold italic left-aligned
- No extra blank lines between headings and paragraph text
- References: APA 7th hanging indent format
- Write in third person academic voice
- NO plagiarism — all prose is originally composed
- DO NOT write "As an AI" or any AI disclosure language
"""

async def write_chapter(
    topic: str,
    degree: str,
    field: str,
    chapter_type: str,
    research_context: str,
    additional_instructions: str = "",
    existing_draft: str = "",
    professor_feedback: str = "",
    citation_style: str = "APA 7th",
    institution: str = "",
    custom_formatting: str = ""
) -> dict:

    chapter_prompt = CHAPTER_PROMPTS.get(chapter_type, CHAPTER_PROMPTS["Custom Section"])
    institution_note = f"Institution: {institution}. " if institution else ""
    formatting = custom_formatting if custom_formatting else FORMATTING_RULES

    revision_block = ""
    if professor_feedback:
        revision_block = f"""
PROFESSOR FEEDBACK TO ADDRESS:
{professor_feedback}

Address EVERY point of feedback above in this revision.
"""

    draft_block = ""
    if existing_draft:
        draft_block = f"""
EXISTING DRAFT TO IMPROVE/REVISE:
{existing_draft[:4000]}

Improve and expand this draft. Keep the voice consistent.
"""

    prompt = f"""You are a doctoral-level academic writer producing a {degree} dissertation chapter.

{institution_note}Field: {field}
Research Topic: {topic}
Citation Style: {citation_style}

{chapter_prompt}

{formatting}

RESEARCH SOURCES TO CITE (use these real verified sources):
{research_context}

{revision_block}
{draft_block}

Additional Instructions: {additional_instructions}

Now write the full {chapter_type}. Use proper APA 7th in-text citations throughout.
Include a References section at the end with all cited sources in APA 7th format.
"""

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    response = await asyncio.to_thread(
        lambda: client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=8192,
                temperature=0.72
            )
        )
    )

    content = response.text or ""
    word_count = len(content.split())

    return {
        "content": content,
        "word_count": word_count,
        "chapter_type": chapter_type,
        "model_used": "gemini-2.5-flash"
    }

async def revise_with_feedback(
    existing_content: str,
    professor_feedback: str,
    topic: str,
    chapter_type: str
) -> dict:
    prompt = f"""You are a doctoral-level academic editor revising a dissertation chapter based on professor feedback.

Chapter: {chapter_type}
Topic: {topic}

PROFESSOR FEEDBACK — ADDRESS EVERY POINT:
{professor_feedback}

CURRENT CHAPTER CONTENT:
{existing_content[:5000]}

Revise the chapter to fully address all professor feedback.
Keep the same general structure but improve weak areas.
Maintain ~75% quality (solid student work, not perfect).
Use APA 7th citations throughout.
Write in academic third person.
"""

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    response = await asyncio.to_thread(
        lambda: client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(max_output_tokens=8192, temperature=0.7)
        )
    )
    content = response.text or ""
    return {"content": content, "word_count": len(content.split()), "model_used": "gemini-2.5-flash"}

async def write_chapter_with_scratchpad(
    topic: str, degree: str, field: str, chapter_type: str,
    research_context: str, scratchpad_content: str = "",
    scratchpad_summary: str = "", additional_instructions: str = "",
    existing_draft: str = "", professor_feedback: str = "",
    citation_style: str = "APA 7th", institution: str = "",
    custom_formatting: str = ""
) -> dict:
    """Same as write_chapter but injects scratchpad context."""
    combined_instructions = additional_instructions or ""
    if scratchpad_summary:
        combined_instructions += f"\n\nKey themes and ideas from the researcher's notes: {scratchpad_summary}"
    if scratchpad_content and len(scratchpad_content) > 50:
        combined_instructions += f"\n\nResearcher's raw notes to incorporate where relevant:\n{scratchpad_content[:2000]}"

    return await write_chapter(
        topic=topic, degree=degree, field=field, chapter_type=chapter_type,
        research_context=research_context,
        additional_instructions=combined_instructions.strip(),
        existing_draft=existing_draft, professor_feedback=professor_feedback,
        citation_style=citation_style, institution=institution,
        custom_formatting=custom_formatting
    )
