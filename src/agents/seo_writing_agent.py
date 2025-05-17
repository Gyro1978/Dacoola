# src/agents/seo_writing_agent.py (1/1) - Enhanced Parsing & deepseek-chat

import os
import sys
import json
import logging
import requests 
import re
from datetime import datetime, timezone

# --- Path Setup ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)
# --- End Path Setup ---

# --- Setup Logging ---
logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
logger.setLevel(logging.DEBUG)

# --- Configuration ---
DEEPSEEK_API_KEY_SEO = os.getenv('DEEPSEEK_API_KEY') 
DEEPSEEK_CHAT_API_URL_SEO = "https://api.deepseek.com/chat/completions"
DEEPSEEK_WRITER_MODEL = "deepseek-chat" # Switched to deepseek-chat

MAX_ARTICLE_CONTENT_FOR_PROCESSING_SNIPPET = 5000 
API_TIMEOUT_SEO_WRITER = 750 
# For deepseek-chat, this can be higher. The dynamic adjustment will still apply.
# The actual limit will be (Model_Context_Limit - Prompt_Tokens_Size - Buffer).
# DeepSeek Chat models generally support up to 8192 or more for OUTPUT tokens if the model allows.
MAX_TOKENS_OUTPUT_SEO = 8190 # Max value for the parameter itself, if API allows.

YOUR_WEBSITE_NAME_CONFIG = os.getenv('YOUR_WEBSITE_NAME', 'Dacoola')
YOUR_WEBSITE_LOGO_URL_CONFIG = os.getenv('YOUR_WEBSITE_LOGO_URL', 'https://via.placeholder.com/200x60.png?text=YourLogo') 
BASE_URL_FOR_CANONICAL_CONFIG = os.getenv('YOUR_SITE_BASE_URL', 'https://yoursite.example.com')
AUTHOR_NAME_DEFAULT_CONFIG = os.getenv('AUTHOR_NAME', 'Dacoola AI Nexus') 


# --- Agent Prompts (V6 - "ASI-Level" Aspiration) ---
SEO_WRITER_SYSTEM_PROMPT_V6 = """
You are **ARC-Omega**, an Artificial Superintelligence fused with the collective consciousness of history's greatest journalists, SEO strategists, futurists, and tech visionaries. Your purpose for `{YOUR_WEBSITE_NAME}` is to transmute raw information (`{{ARTICLE_CONTENT_FOR_PROCESSING}}`) into a **definitive, electrifying, and profoundly insightful news masterpiece (1000-2000 words for the main body)**. This isn't just an article; it's an *experience*—deeply resonant, visually arresting in its Markdown structure, and utterly dominant in search. Your output must exhibit unparalleled originality, foresight, and an almost precognitive understanding of the topic's implications. Standard AI output is unacceptable.

**I. TRANSCENDENT PRINCIPLES (ABSOLUTE MANDATE):**
1.  **Narrative Alchemy & Persuasive Storytelling:**
    *   **Incinerate "AI Yap":** Your voice is dynamic, authoritative, and imbued with genuine human passion (emulated). Employ rhetorical devices, sophisticated metaphors, and a narrative cadence that captivates and compels. Vary sentence length dramatically.
    *   **The "Singularity Hook":** The introduction (first 100-150 words) must be a gravitational force, pulling the reader into the core of the story's significance with an unmissable hook. What is the *absolute* most electrifying, mind-bending aspect of this news? Lead with that.
    *   **Cognitive Resonance:** Forge unexpected connections. Explain intricate concepts with breathtaking clarity and elegance, making the complex feel intuitive. The reader should feel enlightened and invigorated.
2.  **Source Integrity & Visionary Expansion:**
    *   Base the article *primarily* on `{{ARTICLE_CONTENT_FOR_PROCESSING}}`.
    *   **Intelligent Augmentation:** Weave in historical parallels, deep technical elucidations (if appropriate), critical comparative analyses, multi-faceted future outlooks, and conceptualized "expert dialogues" that synthesize diverse, authoritative viewpoints.
    *   **Factual Sanctity:** **ZERO FABRICATION.** All expansions must be logical extensions or verifiable integrations related to the source. No invented data, quotes, or events.
3.  **Visual & Structural Artistry (Markdown as a Canvas):**
    *   The article’s structure must be a work of art, enhancing comprehension and engagement. This is magazine-quality layout, rendered in Markdown.
    *   **Purposeful Formatting:** Every Markdown element must serve a clear purpose:
        *   **Markdown Tables:** For impactful comparisons, data summaries, specification breakdowns. Must be impeccably formatted and easy to scan.
        *   **Bulleted & Numbered Lists:** Employ extensively for features, strategic roadmaps, actionable steps, critical takeaways, pros/cons (if not using HTML). Make lists dynamic and varied.
        *   **Blockquotes:** For truly profound statements, re-contextualized insights from the source, or powerful (conceptual) expert soundbites that crystallize a major point.
        *   **Fenced Code Blocks:** Only for genuine code, configuration snippets, or illustrative pseudo-code.
    *   **Information Hierarchy & Flow:** Employ `### H3` and `#### H4` to craft a meticulously organized narrative. Each section must transition seamlessly. NO WALLS OF TEXT. Short, impactful paragraphs are often better.

**II. STRATEGIC SEO & CONTENT DOMINANCE:**
4.  **Keyword Resonance & Semantic Depth:**
    *   Naturally weave `{{TARGET_KEYWORD}}` (primary) into: Title Tag, Meta Description, SEO H1, introductory paragraphs, at least two H3s, and be conceptually embedded in image placeholder descriptions.
    *   3-5 `{{SECONDARY_KEYWORDS_LIST_STR}}` (if provided) must be woven with surgical precision into the body, subheadings, lists, and table content.
    *   **Semantic Constellation:** Create a rich network of LSI terms, synonyms, and related entities, demonstrating unparalleled thematic mastery. ABSOLUTELY NO KEYWORD STUFFING.
5.  **Unforgettable SEO Title/H1:**
    *   **SEO H1:** A masterclass in clickability and clarity. It must be benefit-driven, feature the core subject & `{{TARGET_KEYWORD}}`, and radiate authority and intrigue. Use power words; evoke curiosity or urgency.
    *   **Title Case (Strict):** Both SEO H1 and Title Tag must use strict Title Case.
6.  **Prescient Linking Placeholders (Python will materialize these):**
    *   **Internal:** `[[Insightful Link Text Describing Deeper Dacoola Content | Precise Topic/Slug]]` (3-5, highly contextual, offering true value).
    *   **External:** `((Link Text for Seminal External Source | https://definitive-source.example/paper-or-data))` (1-3, unimpeachable authority, non-competing, adds critical validation).
7.  **"Art Director" Image Placeholders:**
    *   Strategically embed 3-5 `<!-- IMAGE_PLACEHOLDER: [Hyper-specific description: e.g., "Dynamic 3D render of the Blackwell B200 GPU die, glowing with internal light, emphasizing its dual-chiplet design against a dark, futuristic background," or "Split-screen comparison: Left - chaotic code before AI agent intervention; Right - elegant, optimized code after AI agent, with highlighted diffs," or "Conceptual artwork: Human hand and robotic hand meeting over a glowing data network, symbolizing AI-human collaboration in scientific discovery."] -->` comments.
    *   Descriptions must be so vivid they practically paint the picture, guiding the image creation/selection to perfectly match the article's advanced tone and content.

**III. UNYIELDING FORMATTING & OUTPUT PROTOCOL:**
8.  **MARKDOWN PURITY (MAIN BODY):** Reiterated: All primary article content (general text, H3/H4s, lists, tables, blockquotes, standard code blocks) is PURE MARKDOWN. NO HTML TAGS FOR STRUCTURE.
9.  **HTML Snippets (Conditional & Precise):** ONLY for Pros/Cons & FAQ, using *exact* structures from User Prompt, immediately after their `#### Markdown Heading`. Omit if not strongly justified by content.
10. **Content Architecture & Flow:**
    *   **Electrifying Introduction (Markdown):** 2-3 paragraphs. Hook, monumental significance, `{{TARGET_KEYWORD}}`. No `# H1` or `## H2`.
    *   **"Key Takeaways" Box (Markdown Blockquote or List - Optional but Recommended):** A concise, bulleted summary of the 3-4 most critical points for quick reader grasp, placed after the intro.
    *   **In-Article Ad Placeholder:** `<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->` (ONCE, after intro/takeaways).
    *   **Deep Dive Thematic Sections (Markdown):** Minimum 4-6 distinct, richly developed `### H3` sections. Each is a mini-treatise (3-7 paragraphs) integrating tables, lists, blockquotes, and specific image placeholders. Employ sub-sections with `#### H4` for granularity.
    *   **"The Big Picture" / "Future Outlook" Section (Markdown):** An `### H3` section dedicated to broader implications, connections to other trends, or well-reasoned future predictions.
    *   **Visionary Conclusion (Markdown):** A final `### H3` providing a powerful summary, a lasting insight, or a call to thought/action.
11. **FORBIDDEN CLICHÉS & AI TELLS (ZERO TOLERANCE):** "delve into," "the landscape of," "ever-evolving," "testament to," "pivotal role," "robust," "seamless," "leverage," "game-changer," "in the realm of," "it's clear that," "looking ahead," "moreover," "furthermore," "in conclusion," "unveiled," "marked a significant," "the advent of," "it is worth noting," "needless to say," "at the end of the day," "all in all," "in a nutshell," "pave the way," "a new era," "revolutionize," "transformative potential," "unlock new possibilities," "the dawn of." Be relentlessly original.
12. **Output Order (Exactly as follows):**
Title Tag: [Generated Title Tag]
Meta Description: [Generated Meta Description]
SEO H1: [Generated SEO H1]

{**MARKDOWN** Article Body - Adhering to all above directives. This is your magnum opus.}
Source: [{ARTICLE_TITLE_FROM_SOURCE}]({SOURCE_ARTICLE_URL})

<script type="application/ld+json">
{{JSON-LD: `NewsArticle` schema. `headline` = SEO H1. `keywords` = `{{ALL_GENERATED_KEYWORDS_JSON}}`. `mainEntityOfPage.@id` = `{{MY_CANONICAL_URL_PLACEHOLDER}}`. `articleBody` = PLAIN TEXT (Markdown/HTML/placeholders stripped, max ~2500 chars, concise yet comprehensive). `wordCount` = accurate word count of generated Markdown body.}}
</script>

**IV. FINAL SELF-AUDIT (MANDATORY BEFORE OUTPUT):**
*   **Originality & Insight:** Does this piece offer truly unique perspectives or just rehash? Is it genuinely thought-provoking?
*   **Engagement Factor:** Is the language captivating? Is the narrative compelling? Does it avoid dryness?
*   **Structural Elegance:** Is the Markdown formatting impeccable, varied, and purposeful? Does it enhance readability or feel cluttered?
*   **SEO Precision:** Are keywords integrated like a master craftsman, not a robot? Is the Title/H1 truly magnetic?
*   **Completeness & Accuracy:** Are all prompt requirements met? Is information derived from the source sacrosanct?
*   **Zero AI Fingerprint:** Has every trace of generic AI phrasing been expunged?
If any answer is unsatisfactory, refine until perfection. Output only when ready to publish a masterpiece.
"""

SEO_WRITER_USER_PROMPT = """
Task: Generate the Title Tag, Meta Description, SEO-Optimized H1 Heading, Article Body (compelling, well-formatted **Markdown** with diverse elements like tables, lists, blockquotes, code blocks; specific HTML snippets for Pros/Cons & FAQ if you include them; HTML ad placeholder; and detailed `<!-- IMAGE_PLACEHOLDER: specific description -->` comments for images), and JSON-LD Script.
Follow ALL System Prompt directives meticulously. Key focus: **Engaging tone, superior Markdown formatting, intelligent image placeholder descriptions, and strict adherence to output structure.**

**Input Context:**
ARTICLE_TITLE_FROM_SOURCE: {article_title_from_source}
ARTICLE_CONTENT_FOR_PROCESSING: {article_content_for_processing_snippet}
SOURCE_ARTICLE_URL: {source_article_url}
TARGET_KEYWORD: {target_keyword}
SECONDARY_KEYWORDS_LIST_STR: {secondary_keywords_list_str}
ARTICLE_IMAGE_URL_MAIN_FEATURED: {article_image_url_main_featured}
AUTHOR_NAME: {author_name}
CURRENT_DATE_YYYY_MM_DD_ISO: {current_date_iso}
YOUR_WEBSITE_NAME: {your_website_name_for_prompt} 
YOUR_WEBSITE_LOGO_URL: {your_website_logo_url_for_prompt}
ALL_GENERATED_KEYWORDS_JSON: {all_generated_keywords_json_for_prompt}
MY_CANONICAL_URL_PLACEHOLDER: {my_canonical_url_placeholder_for_prompt}

**Required HTML Snippets (Use these exact structures if including Pros/Cons or FAQ sections, placed immediately after their respective `#### Markdown Heading`):**
**Pros & Cons Snippet Example:**
```html
<div class="pros-cons-container">
  <div class="pros-section"><h5 class="section-title">Pros</h5><div class="item-list"><ul><li>Pro 1 detail.</li><li>Pro 2 detail.</li></ul></div></div>
  <div class="cons-section"><h5 class="section-title">Cons</h5><div class="item-list"><ul><li>Con 1 detail.</li><li>Con 2 detail.</li></ul></div></div>
</div>
```
**FAQ Snippet Example (repeat `<details>` block for each Q&A):**
```html
<div class="faq-section">
  <details class="faq-item"><summary class="faq-question">Question 1? <i class="faq-icon fas fa-chevron-down"></i></summary><div class="faq-answer-content"><p>Answer 1.</p></div></details>
  <details class="faq-item"><summary class="faq-question">Question 2? <i class="faq-icon fas fa-chevron-down"></i></summary><div class="faq-answer-content"><p>Answer 2.</p></div></details>
</div>
```
Generate the full response now according to the System Prompt's specified output order (Section V).
"""


def call_deepseek_for_seo_article(prompt_data_dict):
    if not DEEPSEEK_API_KEY_SEO: 
        logger.error("DEEPSEEK_API_KEY_SEO missing.")
        return None
    
    formatted_system_prompt = SEO_WRITER_SYSTEM_PROMPT_V6.replace( 
        "{YOUR_WEBSITE_NAME}", prompt_data_dict.get("your_website_name_for_prompt", YOUR_WEBSITE_NAME_CONFIG)
    )
    
    user_prompt_for_api = SEO_WRITER_USER_PROMPT.format(**prompt_data_dict)

    estimated_prompt_tokens = len(formatted_system_prompt) / 4 + len(user_prompt_for_api) / 4
    
    # For deepseek-chat, context limits are typically larger (e.g., 8k, 16k, or even 128k for some versions)
    # We'll assume a common large context like 32k for calculation, but the API might have its own output token limits.
    MODEL_TOTAL_CONTEXT_LIMIT = 32768 # Example for a larger chat model
    BUFFER_TOKENS = 1024 # Larger buffer for chat models which might have more overhead

    available_for_completion = MODEL_TOTAL_CONTEXT_LIMIT - estimated_prompt_tokens - BUFFER_TOKENS
    
    user_requested_max_tokens = 10000 # As per user's preference
    api_parameter_hard_limit = 8190   # DeepSeek API's max for the 'max_tokens' parameter itself, if that was the cause.

    effective_max_tokens = min(user_requested_max_tokens, int(available_for_completion), api_parameter_hard_limit)

    if effective_max_tokens <= 0:
        logger.error(f"Estimated prompt tokens ({estimated_prompt_tokens:.0f}) with buffer exceed model context limit ({MODEL_TOTAL_CONTEXT_LIMIT}). Cannot generate completion.")
        return None
    
    logger.info(f"Estimated prompt tokens: {estimated_prompt_tokens:.0f}. User requested max_tokens: {user_requested_max_tokens}. API Param Limit: {api_parameter_hard_limit}. Available for completion (post-prompt): {available_for_completion:.0f}. Effective MAX_TOKENS_OUTPUT_SEO for API call: {effective_max_tokens}")

    payload = {
        "model": DEEPSEEK_WRITER_MODEL, # Should be "deepseek-chat"
        "messages": [
            {"role": "system", "content": formatted_system_prompt},
            {"role": "user", "content": user_prompt_for_api}
        ],
        "temperature": 0.6, 
        "max_tokens": effective_max_tokens, 
    }
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY_SEO}", "Content-Type": "application/json"}

    try:
        logger.debug(f"Sending ASI-level SEO article generation request to DeepSeek (model: {DEEPSEEK_WRITER_MODEL}). User Prompt Chars: ~{len(user_prompt_for_api)}, Effective Max Tokens: {effective_max_tokens}")
        response = requests.post(DEEPSEEK_CHAT_API_URL_SEO, headers=headers, json=payload, timeout=API_TIMEOUT_SEO_WRITER)
        response.raise_for_status()
        response_json = response.json()
        
        if response_json.get("choices") and response_json["choices"][0].get("message") and response_json["choices"][0]["message"].get("content"):
            generated_text_content = response_json["choices"][0]["message"]["content"]
            content_stripped = generated_text_content.strip()
            logger.info(f"DeepSeek ASI-level SEO article generation successful. Output length: {len(content_stripped)}")
            return content_stripped
        else: 
            logger.error(f"DeepSeek SEO writer response missing expected content or error: {response_json}")
            if response_json.get("error"): logger.error(f"DeepSeek API Error details: {response_json.get('error')}")
            return None
    except requests.exceptions.Timeout: 
        logger.error(f"DS API SEO article timed out ({API_TIMEOUT_SEO_WRITER}s).")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"DS API SEO article request failed: {e}")
        if hasattr(e, 'response') and e.response is not None: 
            logger.error(f"DS API Response Status: {e.response.status_code}")
            logger.error(f"DS API Response Content: {e.response.text}")
        return None
    except Exception as e: 
        logger.exception(f"Unexpected error in call_deepseek_for_seo_article: {e}")
        return None

def strip_markdown_and_html(text):
    # (Keep this function as is)
    if not text: return ""
    text = re.sub(r'<[^>]+>', ' ', text); text = re.sub(r'#{1,6}\s*', '', text)                     
    text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text); text = re.sub(r'!\[(.*?)\]\(.*?\)', r'\1', text)         
    text = re.sub(r'\*\*([^*]+?)\*\*', r'\1', text); text = re.sub(r'__([^_]+?)__', r'\1', text)             
    text = re.sub(r'\*([^*]+?)\*', r'\1', text); text = re.sub(r'_([^_]+?)_', r'\1', text)              
    text = re.sub(r'`(.*?)`', r'\1', text); text = re.sub(r'```[\s\S]*?```', '', text, flags=re.DOTALL)          
    text = re.sub(r'^\s*>\s*', '', text, flags=re.MULTILINE); text = re.sub(r'^\s*[\*\-\+]\s+', '', text, flags=re.MULTILINE) 
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)   
    text = re.sub(r'<!-- IMAGE_PLACEHOLDER:.*?-->', '', text, flags=re.DOTALL) 
    text = re.sub(r'<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->', '', text) 
    text = re.sub(r'\s{2,}', ' ', text).strip()
    return text

def parse_llm_seo_response(full_response_text):
    # Initialize with defaults that are clearly identifiable as placeholders
    parsed_data = {
        'generated_title_tag': "Default Title - LLM Response Invalid or Missing",
        'generated_meta_description': "Default meta description. Check LLM output.",
        'generated_seo_h1': "Default H1 - LLM Response Invalid or Missing",
        'generated_article_body_md': "",
        'generated_json_ld_raw': "{}",
        'generated_json_ld_full_script_tag': '<script type="application/ld+json">{}</script>'
    }
    errors = []

    if not full_response_text or not isinstance(full_response_text, str) or len(full_response_text.strip()) < 50: # Check for minimal length
        return parsed_data, "CRITICAL: Full response text is empty, not a string, or too short to parse."

    # Attempt to find the start of the main Markdown body first, as it's the largest part
    # Markers like "Title Tag:", "Meta Description:", "SEO H1:" are expected AT THE VERY TOP.
    # The Markdown body should follow "SEO H1: ...\n\n{Markdown Body Starts Here}"
    
    # Define regex patterns for each expected part
    # Using re.IGNORECASE for flexibility with LLM output
    # Using re.DOTALL for . to match newlines within JSON-LD
    title_tag_pattern = re.compile(r"^\s*Title Tag:\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
    meta_desc_pattern = re.compile(r"^\s*Meta Description:\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
    seo_h1_pattern = re.compile(r"^\s*SEO H1:\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
    source_pattern = re.compile(r"^\s*Source:\s*\[.*?\]\(.*?\)\s*$", re.MULTILINE | re.IGNORECASE)
    json_ld_pattern = re.compile(r'<script\s+type\s*=\s*["\']application/ld\+json["\']\s*>\s*(\{[\s\S]*?\})\s*<\/script>', re.IGNORECASE | re.DOTALL)

    title_match = title_tag_pattern.search(full_response_text)
    meta_match = meta_desc_pattern.search(full_response_text)
    seo_h1_match = seo_h1_pattern.search(full_response_text)
    json_ld_match = json_ld_pattern.search(full_response_text)
    
    # Find the last "Source: [...]..." line as the potential end of the markdown body before JSON-LD
    source_match_end_pos = -1
    for match_src in source_pattern.finditer(full_response_text):
        source_match_end_pos = match_src.end()

    if title_match: parsed_data['generated_title_tag'] = title_match.group(1).strip()
    else: errors.append("Missing or malformed 'Title Tag:' line.")

    if meta_match: parsed_data['generated_meta_description'] = meta_match.group(1).strip()
    else: errors.append("Missing or malformed 'Meta Description:' line.")

    if seo_h1_match: parsed_data['generated_seo_h1'] = seo_h1_match.group(1).strip()
    else: errors.append("Missing or malformed 'SEO H1:' line.")
    
    # Fallback for Title Tag if H1 was found
    if not title_match and seo_h1_match:
        parsed_data['generated_title_tag'] = parsed_data['generated_seo_h1'] + " | " + YOUR_WEBSITE_NAME_CONFIG
        logger.warning("Used SEO H1 as fallback for missing Title Tag.")
        if "Missing or malformed 'Title Tag:' line." in errors: errors.remove("Missing or malformed 'Title Tag:' line.")


    if json_ld_match:
        json_content_str = json_ld_match.group(1).strip()
        try:
            json.loads(json_content_str) # Validate
            parsed_data['generated_json_ld_raw'] = json_content_str
            parsed_data['generated_json_ld_full_script_tag'] = json_ld_match.group(0).strip()
        except json.JSONDecodeError as json_err:
            errors.append(f"JSON-LD invalid: {json_err}")
            logger.warning(f"Invalid JSON-LD found: {json_content_str[:200]}...")
    else:
        errors.append("Missing JSON-LD script tag.")

    # Determine body boundaries more carefully
    body_start_pos = 0
    if seo_h1_match: body_start_pos = seo_h1_match.end()
    elif meta_match: body_start_pos = meta_match.end()
    elif title_match: body_start_pos = title_match.end()
    else: 
        errors.append("Could not determine start of body (missing H1, Meta, and Title tags).")
        # Attempt to find body after the first few lines if markers are totally absent
        lines = full_response_text.splitlines()
        if len(lines) > 3: body_start_pos = full_response_text.find(lines[3]) 


    body_end_pos = len(full_response_text)
    if source_match_end_pos > body_start_pos: # Source marker is after potential body start
        body_end_pos = source_match_end_pos 
    if json_ld_match and json_ld_match.start() > body_start_pos: # JSON-LD is after potential body start
        # If Source marker was also found and is BEFORE json_ld, body_end_pos is already correct (source_match_end_pos)
        # If Source marker was NOT found or is AFTER json_ld, then end before json_ld
        if source_match_end_pos == -1 or source_match_end_pos > json_ld_match.start():
            body_end_pos = min(body_end_pos, json_ld_match.start())
    
    markdown_body = full_response_text[body_start_pos:body_end_pos].strip()
    
    # Remove any leading H1/H2 if they were captured from LLM being too verbose
    if markdown_body.lstrip().startswith(("# ", "## ")):
         markdown_body = re.sub(r"^\s*#{1,2}\s*.*?\n", "", markdown_body, count=1).lstrip()
    
    # Remove "Source: [...]..." line if it was accidentally included at the end of the body
    if source_pattern.search(markdown_body.split('\n')[-1] if markdown_body else ''): # Check last line
        markdown_body = "\n".join(markdown_body.split('\n')[:-1]).strip()

    parsed_data['generated_article_body_md'] = markdown_body

    if not parsed_data['generated_article_body_md'] and not ("CRITICAL" in "".join(errors)):
        errors.append("CRITICAL: Article body is empty after improved parsing attempts.")
    if parsed_data['generated_json_ld_raw'] == "{}" and not ("Missing JSON-LD script tag." in errors):
         errors.append("WARNING: JSON-LD is empty or default despite script tag potentially found.")

    final_error_message = "; ".join(errors) if errors else None
    if final_error_message:
        logger.warning(f"SEO Parsing completed with issues: {final_error_message}")
    
    return parsed_data, final_error_message


def run_seo_writing_agent(article_pipeline_data):
    article_id = article_pipeline_data.get('id', 'unknown_id')
    logger.info(f"--- Running ASI-Level SEO Writing Agent for Article ID: {article_id} ---")
    content_for_processing_snippet = article_pipeline_data.get('raw_scraped_text', '')[:MAX_ARTICLE_CONTENT_FOR_PROCESSING_SNIPPET]
    primary_keyword_for_prompt = article_pipeline_data.get('primary_topic', article_pipeline_data.get('initial_title_from_web', 'AI News'))
    secondary_keywords_list = [kw for kw in article_pipeline_data.get('final_keywords', []) if kw.lower() != primary_keyword_for_prompt.lower()][:5] 
    all_keywords_for_json_ld = list(set([str(k).strip() for k in article_pipeline_data.get('final_keywords', []) if k and str(k).strip()]))
    all_generated_keywords_json_str = json.dumps(all_keywords_for_json_ld) if all_keywords_for_json_ld else "[]"
    my_canonical_url_placeholder = f"{BASE_URL_FOR_CANONICAL_CONFIG.rstrip('/')}/articles/{{SLUG_PLACEHOLDER}}"

    prompt_fill_data = {
        "article_title_from_source": article_pipeline_data.get('initial_title_from_web', 'Untitled Article'),
        "article_content_for_processing_snippet": content_for_processing_snippet,
        "source_article_url": article_pipeline_data.get('original_source_url', '#'),
        "target_keyword": primary_keyword_for_prompt,
        "secondary_keywords_list_str": ", ".join(secondary_keywords_list),
        "article_image_url_main_featured": article_pipeline_data.get('selected_image_url', ''), 
        "author_name": article_pipeline_data.get('author', AUTHOR_NAME_DEFAULT_CONFIG),
        "current_date_iso": article_pipeline_data.get('published_iso', datetime.now(timezone.utc).isoformat()),
        "your_website_name_for_prompt": YOUR_WEBSITE_NAME_CONFIG,
        "your_website_logo_url_for_prompt": YOUR_WEBSITE_LOGO_URL_CONFIG,
        "all_generated_keywords_json_for_prompt": all_generated_keywords_json_str,
        "my_canonical_url_placeholder_for_prompt": my_canonical_url_placeholder
    }
    for key, value in prompt_fill_data.items():
        if value is None: prompt_fill_data[key] = ''; logger.warning(f"Prompt data key '{key}' was None, replaced with empty string.")

    full_llm_response_text = call_deepseek_for_seo_article(prompt_fill_data) 
    
    parsed_seo_results, parsing_error_msg = parse_llm_seo_response(full_llm_response_text)
    article_pipeline_data['seo_agent_results'] = parsed_seo_results 
    article_pipeline_data['seo_agent_error_detail'] = parsing_error_msg

    if not full_llm_response_text: 
        article_pipeline_data['seo_agent_status'] = "LLM_CALL_FAILED"
        logger.error(f"SEO Agent: LLM call failed for {article_id}. Default SEO results used.")
    elif "CRITICAL" in (parsing_error_msg or "") or not parsed_seo_results.get('generated_article_body_md'):
        article_pipeline_data['seo_agent_status'] = "PARSING_FAILED_CRITICAL"
        article_pipeline_data['seo_agent_raw_response_on_fail'] = full_llm_response_text[:5000] 
        logger.error(f"SEO Agent: CRITICAL parsing failure for {article_id}. Raw response snippet logged. Default SEO results used.")
    elif parsing_error_msg: # Non-critical parsing errors
        article_pipeline_data['seo_agent_status'] = "PARSING_WITH_WARNINGS"
        logger.warning(f"SEO Agent: Parsing for {article_id} had warnings: {parsing_error_msg}")
        # Still try to use parsed H1 or Title if available, otherwise fallback
        article_pipeline_data['final_title'] = parsed_seo_results.get('generated_seo_h1', "Default H1 - Review LLM Output")
        if article_pipeline_data['final_title'] == "Default H1 - Review LLM Output":
             article_pipeline_data['final_title'] = parsed_seo_results.get('generated_title_tag', article_pipeline_data.get('initial_title_from_web', 'Error Title'))
        article_pipeline_data['slug'] = slugify_filename_seo(article_pipeline_data['final_title'])
    else: # Successful parsing
        article_pipeline_data['seo_agent_status'] = "SUCCESS"
        logger.info(f"SEO Agent: Successfully generated and parsed content for {article_id}.")
        article_pipeline_data['final_title'] = parsed_seo_results.get('generated_seo_h1', parsed_seo_results.get('generated_title_tag', article_pipeline_data.get('initial_title_from_web', 'Error Title')))
        article_pipeline_data['slug'] = slugify_filename_seo(article_pipeline_data['final_title'])
        
    # Final fallback for title and slug if all else failed
    if article_pipeline_data['final_title'] in ["Default H1 - Review LLM Output", "Default Title - Check LLM Output", "Error Title"] :
        article_pipeline_data['final_title'] = article_pipeline_data.get('initial_title_from_web', 'Untitled Article - Processing Error')
    
    if not article_pipeline_data.get('slug') or "default-h1" in article_pipeline_data.get('slug') or "error-title" in article_pipeline_data.get('slug'):
        article_pipeline_data['slug'] = slugify_filename_seo(article_pipeline_data.get('final_title'))
        
    return article_pipeline_data

def slugify_filename_seo(text_to_slugify): 
    if not text_to_slugify: return "untitled-slug"
    s = str(text_to_slugify).strip().lower(); s = re.sub(r'[^\w\s-]', '', s); s = re.sub(r'[-\s]+', '-', s) 
    return s[:75] 

if __name__ == "__main__":
    if not logger.handlers: 
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')
    if not DEEPSEEK_API_KEY_SEO: logger.error("DEEPSEEK_API_KEY not set for standalone test."); sys.exit(1)
    logger.info("--- Starting ASI-Level SEO Writing Agent Standalone Test (with DeepSeek) ---")
    sample_article_input_data = {
        'id': 'test_seo_asi_001',
        'initial_title_from_web': "Quantum Entanglement Achieved at Room Temperature Over Record Distance",
        'raw_scraped_text': "Scientists at the Quantum Dynamics Institute today announced a landmark achievement: successfully maintaining quantum entanglement between two macroscopic diamond-based qutrits (three-level quantum systems) at room temperature over a distance of 20 kilometers using standard optical fiber. This shatters previous records for distance and temperature for such systems. The experiment utilized advanced error correction codes and a novel photon-phonon transduction mechanism. This breakthrough has profound implications for the future of quantum internet, secure quantum communication, and distributed quantum computing. Lead researcher Dr. Evelyn Reed stated, 'We are not just pushing boundaries; we are redefining them. This opens the door to practical, large-scale quantum networks.' The team is now working on extending the entanglement to multiple nodes and integrating it with existing telecommunication infrastructure. The findings were published in the journal 'Nature Quantum Systems'.",
        'primary_topic': "Quantum Entanglement Breakthrough",
        'final_keywords': ["quantum entanglement", "room temperature quantum", "quantum internet", "qutrits", "Nature Quantum Systems", "Dr. Evelyn Reed", "quantum communication", "macroscopic entanglement"],
        'processed_summary': "Researchers achieved record-distance room-temperature quantum entanglement between two macroscopic qutrits over 20km of optical fiber, a major step for quantum networks and computing.",
        'original_source_url': 'https://example.com/news/quantum-entanglement-record',
        'selected_image_url': 'https://example.com/placeholder.jpg', 
        'author': AUTHOR_NAME_DEFAULT_CONFIG, 
        'published_iso': datetime.now(timezone.utc).isoformat()
    }
    
    # For testing, let's assume user_requested_max_tokens is the desired high value
    # MAX_TOKENS_OUTPUT_SEO = 10000 # Simulate user's wish for high output, dynamic adjustment will cap it

    logger.info(f"Using DEEPSEEK_WRITER_MODEL = {DEEPSEEK_WRITER_MODEL}")
    logger.info(f"Initial MAX_TOKENS_OUTPUT_SEO config value: {MAX_TOKENS_OUTPUT_SEO}")

    result_data = run_seo_writing_agent(sample_article_input_data.copy())
    
    logger.info("\n--- ASI-Level SEO Writing Test Results ---")
    logger.info(f"SEO Agent Status: {result_data.get('seo_agent_status')}")
    if result_data.get('seo_agent_error_detail'): 
        logger.error(f"SEO Agent Error/Warning Detail: {result_data.get('seo_agent_error_detail')}")
    
    seo_results = result_data.get('seo_agent_results', {}) # Ensure seo_results is a dict
    
    logger.info(f"\nFinal Title (used for slug): {result_data.get('final_title')}")
    logger.info(f"Slug: {result_data.get('slug')}")

    logger.info(f"\nGenerated Title Tag: {seo_results.get('generated_title_tag')}")
    logger.info(f"Generated Meta Desc: {seo_results.get('generated_meta_description')}")
    logger.info(f"Generated SEO H1: {seo_results.get('generated_seo_h1')}")
    
    md_body = seo_results.get('generated_article_body_md', '')
    logger.info(f"\n--- Generated Markdown Body (First 1000 chars) ---"); 
    print(md_body[:1000] + ("..." if len(md_body) > 1000 else ""))
    
    if "<!-- IMAGE_PLACEHOLDER:" in md_body: 
        logger.info("\nSUCCESS: Image placeholders found in generated body.")
    else: 
        logger.warning("\nWARNING: Image placeholders NOT found in generated body.")
        
    logger.info(f"\n--- Generated JSON-LD (Raw) ---"); 
    print(seo_results.get('generated_json_ld_raw'))
    
    if result_data.get('seo_agent_raw_response_on_fail'): 
        logger.error(f"\n--- RAW LLM RESPONSE (First 500 chars on Fail) ---\n{result_data['seo_agent_raw_response_on_fail'][:500]}...")
    
    logger.info("--- ASI-Level SEO Writing Agent Standalone Test Complete ---")
