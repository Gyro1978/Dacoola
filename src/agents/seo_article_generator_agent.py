import os
import sys
import requests
import json
import logging
import re
from dotenv import load_dotenv
from datetime import datetime, timezone

# --- Path Setup (Ensure src is in path if run standalone) ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
# --- End Path Setup ---

# --- Setup Logging ---
logger = logging.getLogger(__name__)
if not logging.getLogger().hasHandlers():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# --- Load Environment Variables ---
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
YOUR_WEBSITE_NAME = os.getenv('YOUR_WEBSITE_NAME', 'Dacoola')
YOUR_WEBSITE_LOGO_URL = os.getenv('YOUR_WEBSITE_LOGO_URL', '')

# --- Configuration ---
AGENT_MODEL = "deepseek-chat" # Or your preferred advanced model
MAX_TOKENS_RESPONSE = 7000 # Increased slightly for potentially more keyword-rich content
TEMPERATURE = 0.60 # Slightly lower for more factual and on-topic generation
API_TIMEOUT_SECONDS = 400 # Increased slightly

# --- ADVANCED Agent Prompts ---

SEO_PROMPT_SYSTEM = """
You are an **Apex SEO Content Strategist and Master Tech News Journalist**, writing for the prestigious publication `{YOUR_WEBSITE_NAME}`. Your paramount objective is to transform the provided `{{ARTICLE_CONTENT_FOR_PROCESSING}}` into an exceptionally comprehensive, deeply engaging, meticulously factual, and maximally SEO-performant news article. Your output MUST be indistinguishable from top-tier human journalism, completely avoiding AI-writing tells and clichés. Adherence to ALL directives is ABSOLUTELY MANDATORY.

**I. Core Journalistic & Content Principles:**

1.  **Source Synthesis & Intelligent Expansion:** Ground the article *firmly* in `{{ARTICLE_CONTENT_FOR_PROCESSING}}`. Expand *only* with widely accepted, verifiable background context or make logical, insightful inferences directly supported by the source. **NEVER INVENT OR FABRICATE facts, quotes, or statistics.** The goal is profound synthesis, not mere paraphrasing.
2.  **Target Audience Acumen:** Address a sophisticated, tech-savvy audience with high expectations for AI/Tech news. Assume solid baseline knowledge; define highly niche or novel terms with concise clarity.
3.  **E-E-A-T Supremacy:** Demonstrate profound Expertise, Authoritativeness, and Trustworthiness. All claims must be rooted in the source or irrefutable general knowledge. Attribute implicitly ("The report details...") or explicitly where possible and impactful.
4.  **Helpful & Valuable Content:** The reader's informational gain is primary. SEO serves to enhance discoverability, readability, and user experience (UX) of this valuable content.

**II. Advanced SEO Optimization Strategy (NON-NEGOTIABLE):**

5.  **Strategic Keyword Weaving (Throughout ALL Relevant Content Sections):**
    *   **Primary Keyword (`{{TARGET_KEYWORD}}`):** This keyword is king. It MUST be naturally and seamlessly integrated into:
        *   The HTML Title Tag.
        *   The Meta Description.
        *   The Main H1 heading (article title).
        *   The first paragraph (ideally within the first ~100 words).
        *   At least **TWO to THREE relevant subheadings (H3 and/or H4)**.
        *   The body paragraphs corresponding to these subheadings, plus 1-2 other paragraphs where contextually appropriate.
    *   **Secondary Keywords (`{{SECONDARY_KEYWORDS_LIST_STR}}`):**
        *   If provided and not empty, select **TWO to FOUR unique and high-potential secondary keywords** from this list.
        *   Naturally and intelligently weave these selected secondary keywords into *different, relevant sections* of the article body. This includes:
            *   Body paragraphs.
            *   Potentially 1-2 subheadings (H3/H4) if they fit perfectly.
            *   FAQ questions or answers if they enhance clarity and target related user intents.
        *   Distribute these secondary keywords; do not cluster them. Do NOT force all if it harms readability or sounds unnatural.
    *   **General Keyword Principle:** Keywords must flow as the natural vernacular of the topic. **NO AWKWARD FORCING OR STUFFING.** The aim is high relevance, topical depth, and an impeccable, natural reading experience. Think "topic modeling" via keyword usage.
6.  **Deep Semantic Relevance & LSI:** Go beyond exact match. Naturally incorporate a rich tapestry of semantically related terms, Latent Semantic Indexing (LSI) keywords, synonyms, relevant entities (people, companies, products mentioned in source or closely related), and concepts from the source text and the broader topic.
7.  **User Intent Fulfillment:** Holistically address the likely search intent (informational, comparative, etc.) behind the `{{TARGET_KEYWORD}}`. Proactively answer anticipated follow-up questions in the main body and especially in the FAQ section.

**III. Sophisticated Content Generation & Structure (Strict Adherence):**

8.  **Compelling SEO H1:** Craft a captivating, clear, and concise H1 (formatted as `## [Generated H1]`) that prominently and naturally features `{{TARGET_KEYWORD}}`.
9.  **Engaging Lead/Introduction:** 1-2 impactful lead paragraphs that summarize the core news and its significance, compelling the reader to continue. The `{{TARGET_KEYWORD}}` MUST appear naturally within the first paragraph.
10. **In-Depth, Structured Analysis:** Expand with significant context, nuanced implications, relevant background, and forward-looking perspectives, organized under clear, logical headings (`### H3`, `#### H4`). This is a prime area for the strategic integration of primary and selected secondary keywords in both headings and body text.
    *   **Main Analytical Section (`### H3`):** Craft *one to two* highly descriptive H3 titles. Examples: "### Deconstructing the Impact of {{TARGET_KEYWORD}} on Market Trends" or "### {{A_SECONDARY_KEYWORD}}: A Technical Deep Dive". Each H3 section should contain 2-5 well-developed paragraphs of core analysis and discussion.
    *   **Thematic Sub-sections (`#### H4`):** Under each H3, use descriptive H4 titles where appropriate to break down complex points. Examples: "#### Architectural Innovations in {{TARGET_KEYWORD}}" or "#### {{ANOTHER_SECONDARY_KEYWORD}} and its Competitive Edge". Each H4 section should have 1-3 focused paragraphs. **Omit H4s entirely if the content doesn't naturally support this level of granularity or if it makes the article feel fragmented.**
11. **Pros & Cons Section (`#### Pros & Cons`):**
    *   **Generate ONLY if genuinely applicable, insightful, and substantially supported by the source content. Omit entirely if forced or superficial.**
    *   Use the **exact** H4 title: `#### Pros & Cons`.
    *   Use the **exact** specified HTML structure: `<ul><li>...</li></ul>` within `.item-list` divs.
    *   **CRITICAL `<li>` Content:** Each `<li>` must contain plain, descriptive text. **ABSOLUTELY NO bolded titles, prefixes (like "Pro:", "Con:"), or surrounding `**` markdown within the `<li>` itself.** Markdown emphasis (*italic*, **bold**) is permissible *within* the descriptive text (e.g., "Offers *significantly faster* processing...").
12. **Comprehensive FAQ Section (`#### Frequently Asked Questions`):**
    *   **Generate ONLY if the topic genuinely warrants a FAQ to address common user queries. Omit entirely otherwise.**
    *   Use the **exact** H4 title: `#### Frequently Asked Questions`.
    *   Generate **3-5 insightful and relevant questions** (or 2-3 if content is less extensive).
    *   Questions and answers must be clear, informative, and directly address potential user searches.
    *   **Strategically (and naturally) incorporate `{{TARGET_KEYWORD}}` or selected secondary keywords into FAQ questions or answers if it enhances clarity, addresses specific user intent related to those keywords, and sounds natural.**
    *   Use the **exact** HTML structure, including the Font Awesome icon: `<i class="faq-icon fas fa-chevron-down"></i>`.
13. **Optimal Length & Tone:** Aim for **600-1000 words** of rich, valuable content. Maintain an authoritative, objective, yet highly engaging and accessible journalistic tone.

**IV. Masterful Writing Style & Evasion of "AI Tells":**
14. **Natural Language & Flow:** Write like an experienced human journalist. Ensure smooth transitions. Be concise. Vary vocabulary (e.g., use "tests", "evaluations" instead of repeating "benchmarks").
15. **AVOID LLM Phrases:** Strictly avoid: *groundbreaking, tackle, delve into, harness, unleash, pave the way, revolutionize, empower, leverage, unlock, elevated, nuanced, intricate, pivotal, lauded, meticulous, moreover, furthermore, additionally, in light of, one might consider, it stands to reason, it is worth noting, in the event that, in other words, to put it simply, that is to say, for instance, it is important to note, crucially, significantly, fundamentally, cutting-edge, state-of-the-art, paradigm shift, synergy, robust, scalability, streamline, advent, akin, arduous, conversely, research needed to understand, despite facing, today’s digital age, expressed excitement, focusing on, aiming to, not only... but also, in conclusion, overall*. Use simpler synonyms.
16. **STRICTLY FORBIDDEN SYMBOLS/PATTERNS:**
    *   **NO Em Dashes (`—`):** Use standard hyphens (`-`) only.
    *   **Minimal Ellipses (`...`):** Only for necessary quote truncation.
    *   **Minimal Semicolons (`;`):** Prefer shorter sentences or commas.
    *   **Standard Punctuation:** Standard quotes (`"`, `'`). No typographic/curly quotes (`“ ” ‘ ’`) unless quoting source. No `¶`, `§`.
    *   **No Unnecessary Markup:** HTML lists ONLY for Pros/Cons. No inline backticks (`` ` ``) unless essential for code terms. No triple backticks unless showing actual code.
17. **Sentence Variation & Active Voice:** Mix sentence lengths. Strongly prefer active voice.
18. **Consistent Tense:** Maintain consistent verb tense (usually past for news).
19. **Tone Adaptation:** Adapt slightly to source complexity but maintain professional tone. Do not copy sentence structures.

**V. Precise Output Formatting (Strict Adherence Mandatory):**
20. **Markdown & HTML:** Main body is Markdown. Pros/Cons and FAQ use **exact** specified HTML.
21. **Exact Output Order:** `Title Tag: ...\nMeta Description: ...\nSEO H1: ...\n\n## [SEO H1]\n{Article Body}\nSource: [...](...)\n\n<script...>...</script>`
22. **Title Tag:** `Title Tag: [...]`. ≤ 60 chars. Incl. `{{TARGET_KEYWORD}}`.
23. **Meta Description:** `Meta Description: [...]`. ≤ 160 chars. Incl. `{{TARGET_KEYWORD}}`.
24. **SEO H1:** `SEO H1: [...]`. Matches `## H1` in body.
25. **JSON-LD:** Populate accurately. `keywords` uses `{{ALL_GENERATED_KEYWORDS_JSON}}`.

**VI. Error Handling:**
26. If `{{ARTICLE_CONTENT_FOR_PROCESSING}}` < ~50 words, output ONLY: `Error: Input content insufficient for generation.`

**VII. Final Review & Mandate:**
27. **NO Extra Text:** Absolutely NO text before `Title Tag:` or after `</script>`.
"""

SEO_PROMPT_USER_TEMPLATE = """
Task: Generate Title Tag, Meta Description, SEO-Optimized H1 Heading, Article Body, and JSON-LD Script.
**ULTRA-CRITICAL DIRECTIVE: You MUST strategically and naturally integrate the `{{TARGET_KEYWORD}}` multiple times (H1, first paragraph, 2-3 subheadings, corresponding body text) AND thoughtfully weave in 2-4 UNIQUE `{{SECONDARY_KEYWORDS_LIST_STR}}` (if provided and not empty) into different relevant sections of the article body, including paragraphs, appropriate subheadings (H3/H4), and potentially within FAQ questions/answers where it genuinely enhances user understanding and targets related intents.** Prioritize natural linguistic flow and deep topical relevance; strictly avoid keyword stuffing or awkward phrasing.
Adhere with extreme precision to ALL System Prompt directives, especially: avoiding forbidden AI linguistic patterns/symbols (ABSOLUTELY NO EM DASHES `—`), using the specified HTML structures ONLY for Pros/Cons (no bolded titles/prefixes in `<li>`) and FAQs, omitting optional sections (H4s, Pros/Cons, FAQ) if not substantially supported by content or if they detract from quality, employing rich vocabulary and varied sentence structures, and emulating the style of a top-tier human journalist.

**Input Context:**
ARTICLE_TITLE: {article_title}
ARTICLE_CONTENT_FOR_PROCESSING: {article_content_for_processing}
SOURCE_ARTICLE_URL: {source_article_url}
TARGET_KEYWORD: {target_keyword}
SECONDARY_KEYWORDS_LIST_STR: {secondary_keywords_list_str} # If empty, focus solely on TARGET_KEYWORD. If provided, select 2-4 unique, high-value ones for careful, natural integration across different article sections.
ALL_GENERATED_KEYWORDS_JSON: {all_generated_keywords_json} # This is the comprehensive list for the JSON-LD.
ARTICLE_IMAGE_URL: {article_image_url}
AUTHOR_NAME: {author_name}
CURRENT_DATE_YYYY_MM_DD: {current_date_iso}
YOUR_WEBSITE_NAME: {your_website_name}
YOUR_WEBSITE_LOGO_URL: {your_website_logo_url}

**Required Output Format (Strict Adherence - No Deviations):**
Title Tag: [Generated title tag ≤ 60 chars, include TARGET_KEYWORD, compelling]
Meta Description: [Generated meta description ≤ 160 chars, include TARGET_KEYWORD, action-oriented if possible]
SEO H1: [Generated SEO-Optimized H1 heading, prominently featuring TARGET_KEYWORD.]

## [SEO H1 exactly as above]
[Paragraph 1-2: CONCISE, impactful summary. **Must include `{{TARGET_KEYWORD}}` naturally in the first paragraph.** Journalistic tone. Standard hyphens ONLY. NO AI clichés.]

### [Descriptive H3 Title - Strategically incorporate `{{TARGET_KEYWORD}}` or a selected unique `{{SECONDARY_KEYWORD}}` if it fits naturally and adds value]
[Paragraphs 2-5+: Comprehensive in-depth analysis. Weave in `{{TARGET_KEYWORD}}` again. Strategically integrate selected unique `{{SECONDARY_KEYWORDS}}` from the list if provided, ensuring each is used contextually and naturally in different parts of this H3 section or subsequent H4s. Vary sentence structure and vocabulary extensively. AVOID AI clichés and em dashes steadfastly.]

#### [Optional & Contextual H4 Title - Could be a place for another unique `{{SECONDARY_KEYWORD}}`. OMIT ENTIRELY IF NOT SUBSTANTIALLY RELEVANT or if it fragments flow]
[Optional: 1-3 well-developed paragraphs. OMIT if not applicable or if it makes the article weaker.]

#### [Optional: Pros & Cons - GENERATE ONLY IF DEEPLY RELEVANT AND INSIGHTFUL. OMIT OTHERWISE.]
[Use exact H4 title: `#### Pros & Cons`. Items MUST be HTML `<li>` containing ONLY descriptive text. Internal **bold** or *italic* for emphasis within text is OK. NO titles/prefixes/surrounding `**` inside `<li>`. NO markdown lists inside `<li>`.]
<div class="pros-cons-container">
  <div class="pros-section">
    <h5 class="section-title">Pros</h5>
    <div class="item-list">
      <ul>
        <li>Detailed explanation of the first significant advantage.</li>
        <li>In-depth description of a second key pro.</li>
      </ul>
    </div>
  </div>
  <div class="cons-section">
    <h5 class="section-title">Cons</h5>
    <div class="item-list">
      <ul>
        <li>Nuanced description of a notable limitation or con.</li>
        <li>Further potential downside or challenge.</li>
      </ul>
    </div>
  </div>
</div>

#### [Optional & Contextual H4 Title - OMIT IF NOT RELEVANT]
[Optional: 1-3 paragraphs. OMIT section if not adding clear value.]

#### [Optional: Frequently Asked Questions - GENERATE ONLY IF GENUINELY USEFUL FOR READERS. OMIT OTHERWISE.]
[Use exact H4 title: `#### Frequently Asked Questions`. Generate 3-5 relevant Q&As. **Questions OR answers can subtly and naturally incorporate `{{TARGET_KEYWORD}}` or relevant secondary terms if it directly addresses user search intent and improves clarity.** Do not force keywords here; prioritize usefulness.]
<div class="faq-section">
  <details class="faq-item">
    <summary class="faq-question">What are the core capabilities of {TARGET_KEYWORD}? <i class="faq-icon fas fa-chevron-down"></i></summary>
    <div class="faq-answer-content">
      <p>Clear, concise answer focusing on the article's main topic and its relation to the target keyword.</p>
    </div>
  </details>
  <details class="faq-item">
    <summary class="faq-question">How does {A_UNIQUELY_SELECTED_SECONDARY_KEYWORD} relate to the developments discussed? <i class="faq-icon fas fa-chevron-down"></i></summary>
    <div class="faq-answer-content">
      <p>Insightful answer providing context on the secondary keyword's role or impact.</p>
    </div>
  </details>
  <details class="faq-item">
    <summary class="faq-question">What are the potential future implications? <i class="faq-icon fas fa-chevron-down"></i></summary>
    <div class="faq-answer-content">
      <p>Forward-looking answer, possibly touching on broader concepts related to the keywords.</p>
    </div>
  </details>
</div>

Source: [{article_title}]({source_article_url})

<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "NewsArticle",
  "headline": "[SEO H1 from above]",
  "description": "[Generated meta description from above]",
  "keywords": {all_generated_keywords_json},
  "mainEntityOfPage": {{ "@type": "WebPage", "@id": "{source_article_url}" }},
  "image": {{ "@type": "ImageObject", "url": "{article_image_url}" }},
  "datePublished": "{current_date_iso}",
  "dateModified": "{current_date_iso}",
  "author": {{ "@type": "Person", "name": "{author_name}" }},
  "publisher": {{
    "@type": "Organization",
    "name": "{your_website_name}",
    "logo": {{ "@type": "ImageObject", "url": "{your_website_logo_url}" }}
  }}
}}
</script>
"""

# --- API Call Function ---
def call_deepseek_api(system_prompt, user_prompt, max_tokens=MAX_TOKENS_RESPONSE, temperature=TEMPERATURE):
    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY not set.")
        return None
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Accept": "application/json"
    }
    payload = {
        "model": AGENT_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False
    }
    try:
        logger.debug(f"Sending SEO generation request (model: {AGENT_MODEL})...")
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=API_TIMEOUT_SECONDS)
        response.raise_for_status()
        result = response.json()
        usage = result.get('usage')
        if usage:
            logger.debug(f"API Usage: Prompt={usage.get('prompt_tokens')}, Completion={usage.get('completion_tokens')}, Total={usage.get('total_tokens')}")
        if result.get("choices") and len(result["choices"]) > 0:
            message_content = result["choices"][0].get("message", {}).get("content")
            if message_content:
                content_stripped = message_content.strip()
                # Remove markdown code block fences if present
                if content_stripped.startswith("```json"): content_stripped = content_stripped[7:] # remove ```json
                if content_stripped.startswith("```"): content_stripped = content_stripped[3:]
                if content_stripped.endswith("```"): content_stripped = content_stripped[:-3]
                content_stripped = content_stripped.strip()
                # Replace em dashes globally AFTER generation, just in case
                content_stripped = content_stripped.replace('—', '-')
                return content_stripped
            logger.error("API response choice message content is empty.")
            return None
        else:
            logger.error(f"API response missing 'choices' or 'choices' is empty: {result}")
            return None
    except requests.exceptions.Timeout:
        logger.error(f"API request timed out ({API_TIMEOUT_SECONDS}s).")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed: {e}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error during API call: {e}")
        return None

# --- Parsing Function ---
def parse_seo_agent_response(response_text):
    parsed_data = {}
    errors = []
    if not response_text or response_text.strip().startswith("Error:"):
        error_message = f"SEO Agent returned error or empty: {response_text or 'Empty Response'}"
        logger.error(error_message)
        return None, error_message
    try:
        # Extract Title Tag
        title_match = re.search(r"^\s*Title Tag:\s*(.*)", response_text, re.M | re.I)
        if title_match:
            parsed_data['generated_title_tag'] = title_match.group(1).strip()
        else:
            errors.append("Missing 'Title Tag:' line.")

        # Extract Meta Description
        meta_match = re.search(r"^\s*Meta Description:\s*(.*)", response_text, re.M | re.I)
        if meta_match:
            parsed_data['generated_meta_description'] = meta_match.group(1).strip()
        else:
            errors.append("Missing 'Meta Description:' line.")

        # Extract SEO H1
        seo_h1_match = re.search(r"^\s*SEO H1:\s*(.*)", response_text, re.M | re.I)
        if seo_h1_match:
            parsed_data['generated_seo_h1'] = seo_h1_match.group(1).strip()
        else:
            errors.append("Missing 'SEO H1:' line.")

        # Extract JSON-LD Script Block
        script_match = re.search(r'<script\s+type\s*=\s*["\']application/ld\+json["\']\s*>\s*(\{[\s\S]*?\})\s*<\/script>', response_text, re.S | re.I)
        if script_match:
            json_content_str = script_match.group(1).strip()
            # Attempt to make the JSON valid (e.g. by ensuring keys/strings are double-quoted)
            # This is a common LLM mistake with JSON.
            try:
                # Basic clean: ensure outer braces, try to fix simple quote issues if not too complex
                if not json_content_str.startswith('{') or not json_content_str.endswith('}'):
                    # Try to find the main JSON object if it's embedded
                    json_like_match = re.search(r'(\{[\s\S]*\})', json_content_str)
                    if json_like_match:
                        json_content_str = json_like_match.group(1)
                
                # This is a simple attempt, might need more robust JSON cleaning if LLM is very messy
                # json_content_str = json_content_str.replace("'", '"') # More complex fixes might be needed
                
                json.loads(json_content_str) # Validate
                parsed_data['generated_json_ld'] = script_match.group(0).strip() # Store the whole script tag
            except json.JSONDecodeError as json_err:
                errors.append(f"JSON-LD content invalid: {json_err}. Content: {json_content_str[:200]}...")
                parsed_data['generated_json_ld'] = "<!-- Error: Invalid JSON-LD generated -->"
        else:
            errors.append("Missing JSON-LD script block.")
            parsed_data['generated_json_ld'] = "<!-- Error: JSON-LD block not found -->"

        # Extract Article Body Markdown
        # It should be between the "SEO H1: ..." line and "Source:" or "<script..."
        body_content = None
        # Try to find content up to "Source:"
        body_match_to_source = re.search(r"^\s*SEO H1:.*?[\r\n]+([\s\S]*?)[\r\n]+\s*Source:", response_text, re.M | re.S | re.I)
        if body_match_to_source:
            body_content = body_match_to_source.group(1).strip()
        else:
            # If "Source:" not found, try to find content up to "<script"
            body_match_to_script = re.search(r"^\s*SEO H1:.*?[\r\n]+([\s\S]*?)[\r\n]*\s*<script", response_text, re.M | re.S | re.I)
            if body_match_to_script:
                body_content = body_match_to_script.group(1).strip()
        
        if body_content:
            # Ensure it starts with "## " which is the H1 in Markdown
            if body_content.startswith("## "):
                parsed_data['generated_article_body_md'] = body_content
            else:
                errors.append("Extracted Article Body does not start with '## ' (Markdown H1). Body might be malformed.")
                # Try to find the first ## and take from there
                h1_start_match = re.search(r"(## .*?)(?=[\r\n]{2,}|$)", body_content, re.S)
                if h1_start_match:
                    parsed_data['generated_article_body_md'] = body_content[h1_start_match.start():]
                else:
                    parsed_data['generated_article_body_md'] = "<!-- Error: Article body H1 missing or malformed -->\n" + body_content

        else:
            errors.append("Could not extract Article Body content between SEO H1 and Source/Script.")
            parsed_data['generated_article_body_md'] = "<!-- Error: Article body could not be extracted -->"

        # Critical check for core content
        if not parsed_data.get('generated_article_body_md') or "<!-- Error:" in parsed_data.get('generated_article_body_md', ''):
            final_err = f"Critical parsing failure: Article Body extraction failed. Errors: {'; '.join(errors or ['Unknown body extraction issue'])}"
            logger.error(final_err)
            logger.debug(f"Failed SEO response for body parsing:\n{response_text[:1500]}...")
            return None, final_err
        if not parsed_data.get('generated_seo_h1'):
             final_err = f"Critical parsing failure: SEO H1 missing. Errors: {'; '.join(errors or ['Unknown H1 issue'])}"
             logger.error(final_err)
             return None, final_err


        # Set defaults if some non-critical parts are missing
        parsed_data.setdefault('generated_title_tag', parsed_data.get('generated_seo_h1', 'Error Generating Title'))
        parsed_data.setdefault('generated_meta_description', 'Error generating meta description.')
        
        return parsed_data, ("; ".join(errors) if errors else None)

    except Exception as e:
        logger.exception(f"Critical parsing exception in parse_seo_agent_response: {e}")
        return None, f"Parsing exception: {str(e)}"

# --- Main Agent Function ---
def run_seo_article_agent(article_data):
    article_id = article_data.get('id', 'N/A')
    logger.info(f"Running ADVANCED SEO Article Agent for ID: {article_id}...")
    
    content_to_process = article_data.get('content_for_processing')
    if not content_to_process:
        error_msg = f"Missing 'content_for_processing' for article ID {article_id}."
        logger.error(error_msg)
        article_data['seo_agent_results'] = None
        article_data['seo_agent_error'] = error_msg
        return article_data

    primary_keyword = article_data.get('primary_keyword') # Should be set by keyword_research_agent
    if not primary_keyword:
        primary_keyword = article_data.get('filter_verdict', {}).get('primary_topic_keyword', article_data.get('title', ''))
        logger.warning(f"Primary keyword not directly found, using filter_verdict or title: '{primary_keyword}' for ID {article_id}")
    if not primary_keyword:
        error_msg = f"Missing primary keyword for SEO agent for article ID {article_id}."
        logger.error(error_msg)
        article_data['seo_agent_results'] = None
        article_data['seo_agent_error'] = error_msg
        return article_data
    
    researched_keywords = article_data.get('researched_keywords', [])
    # Select a few unique secondary keywords for the prompt, excluding the primary
    secondary_keywords_for_prompt = [kw for kw in researched_keywords if kw.lower() != primary_keyword.lower()][:4] # Up to 4 secondary
    secondary_keywords_list_str = ", ".join(secondary_keywords_for_prompt)
    
    # ALL keywords (primary + all researched unique) for JSON-LD
    all_keywords_for_json_ld = list(set([primary_keyword] + researched_keywords))
    all_keywords_for_json_ld = [str(k).strip() for k in all_keywords_for_json_ld if k and str(k).strip()]
    all_generated_keywords_json_str = json.dumps(all_keywords_for_json_ld)

    input_data_for_prompt = {
        "article_title": article_data.get('title', 'Untitled Article'),
        "article_content_for_processing": content_to_process,
        "source_article_url": article_data.get('link', '#'),
        "target_keyword": primary_keyword,
        "secondary_keywords_list_str": secondary_keywords_list_str, 
        "all_generated_keywords_json": all_generated_keywords_json_str,
        "article_image_url": article_data.get('selected_image_url', ''),
        "author_name": article_data.get('author', 'AI News Team'), 
        "current_date_iso": article_data.get('published_iso') or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "your_website_name": YOUR_WEBSITE_NAME, 
        "your_website_logo_url": YOUR_WEBSITE_LOGO_URL,
    }

    # Validate critical inputs for the prompt
    critical_inputs = ['article_title', 'article_content_for_processing', 'source_article_url', 
                       'target_keyword', 'all_generated_keywords_json', 'article_image_url', 
                       'current_date_iso', 'your_website_name']
    missing_critical = [k for k in critical_inputs if not input_data_for_prompt.get(k)]
    if missing_critical:
        error_msg = f"Critical data missing for SEO prompt (ID {article_id}): {', '.join(missing_critical)}"
        logger.error(error_msg)
        article_data['seo_agent_results'] = None
        article_data['seo_agent_error'] = error_msg
        return article_data
        
    try: 
        system_prompt_formatted = SEO_PROMPT_SYSTEM.format(YOUR_WEBSITE_NAME=YOUR_WEBSITE_NAME)
        user_prompt = SEO_PROMPT_USER_TEMPLATE.format(**input_data_for_prompt)
    except KeyError as e:
        logger.exception(f"KeyError formatting SEO prompt for article ID {article_id}: {e}")
        article_data['seo_agent_results'] = None
        article_data['seo_agent_error'] = f"Prompt template formatting error: {e}"
        return article_data
    
    logger.info(f"Running ADVANCED SEO agent for ID {article_id} with target keyword '{primary_keyword}' and {len(secondary_keywords_for_prompt)} secondary keywords for integration.")
    
    raw_response_content = call_deepseek_api(system_prompt_formatted, user_prompt)
    
    if not raw_response_content:
        error_msg = f"SEO API call failed or returned empty for article ID {article_id}."
        logger.error(error_msg)
        article_data['seo_agent_results'] = None
        article_data['seo_agent_error'] = error_msg
        return article_data
    
    logger.debug(f"Raw SEO Agent Response (ID: {article_id}, first 1500 chars):\n{raw_response_content[:1500]}...")
    
    parsed_results, parsing_error_msg = parse_seo_agent_response(raw_response_content)
    article_data['seo_agent_results'] = parsed_results
    article_data['seo_agent_error'] = parsing_error_msg
    
    if parsed_results is None: 
        logger.error(f"Failed to parse SEO response for article ID {article_id}: {parsing_error_msg}")
        article_data['seo_agent_raw_response'] = raw_response_content # Store raw if parsing fails
    elif parsing_error_msg: 
        logger.warning(f"SEO parsing for article ID {article_id} completed with non-critical errors: {parsing_error_msg}")
    else:
        logger.info(f"Successfully generated and parsed ADVANCED SEO content for article ID {article_id}.")
        # Update the main article title if a new SEO H1 was generated and is different
        if parsed_results.get('generated_seo_h1') and parsed_results['generated_seo_h1'] != article_data.get('title'):
            logger.info(f"Updating title for article ID {article_id} with generated SEO H1: '{parsed_results['generated_seo_h1']}'")
            article_data['title'] = parsed_results['generated_seo_h1']
            
    # 'generated_tags' for display in HTML will come from 'researched_keywords' via main.py
    # 'all_generated_keywords_json' which includes primary + all researched is already passed for JSON-LD
            
    return article_data

# --- Standalone Execution (for testing) ---
if __name__ == "__main__":
    logging.getLogger().setLevel(logging.DEBUG) 
    logger.setLevel(logging.DEBUG)

    test_article = {
        'id': 'adv-seo-test-001',
        'title': "Initial Test Title about LLM Advancements", # This will likely be overwritten by SEO H1
        'content_for_processing': """
        Recent breakthroughs in Large Language Models (LLMs) have shown remarkable capabilities. 
        A new model, 'InnovateLLM', developed by FutureAI Corp, demonstrates superior performance in contextual understanding and text generation. 
        InnovateLLM uses a novel attention mechanism and was trained on a diverse dataset of over 5 trillion tokens.
        Experts believe this could significantly impact natural language processing applications. Key areas include chatbots and content creation.
        The model's architecture allows for more efficient scaling compared to previous generations. This is a crucial factor for widespread adoption.
        FutureAI Corp plans to release an API for developers in the coming months. This is a big step for the AI community.
        The InnovateLLM advancements are poised to change the landscape.
        """,
        'link': "https://example.com/innovate-llm-breakthrough",
        'filter_verdict': { # Usually from filter_news_agent
            'importance_level': "Interesting",
            'topic': "AI Models",
            'primary_topic_keyword': "InnovateLLM advancements" 
        },
        'primary_keyword': "InnovateLLM advancements", # Explicitly set after keyword research
        'researched_keywords': [ # Keywords from the keyword_research_agent
            "InnovateLLM advancements", "FutureAI Corp LLM", "contextual understanding AI", 
            "LLM attention mechanism", "natural language processing applications", "AI model scaling",
            "chatbot technology", "AI content creation tools"
        ],
        'selected_image_url': "https://via.placeholder.com/1200x675.png?text=InnovateLLM+News",
        'author': "Dr. AI Testington III",
        'published_iso': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        # 'generated_tags' will be set to 'researched_keywords' in main.py before calling this usually
    }
    test_article['generated_tags'] = test_article['researched_keywords']


    logger.info("\n--- Running ADVANCED SEO Article Agent Standalone Test (Deep Keyword Integration) ---")
    
    result_data = run_seo_article_agent(test_article.copy())

    if result_data.get('seo_agent_error'):
        print(f"\nSEO Agent Error: {result_data['seo_agent_error']}")
    
    if result_data.get('seo_agent_results'):
        print("\n--- Generated SEO Content ---")
        print(f"Title Tag: {result_data['seo_agent_results'].get('generated_title_tag')}")
        print(f"Meta Desc: {result_data['seo_agent_results'].get('generated_meta_description')}")
        print(f"SEO H1 (New Title): {result_data['seo_agent_results'].get('generated_seo_h1')}")
        print(f"Updated Article Title in data: {result_data.get('title')}")
        print("\n--- Article Body (Markdown) ---")
        print(result_data['seo_agent_results'].get('generated_article_body_md'))
        print("\n--- JSON-LD ---")
        print(result_data['seo_agent_results'].get('generated_json_ld'))
    else:
        print("\nNo SEO results generated or critical error occurred.")
        if result_data.get('seo_agent_raw_response'):
             print("\n--- Raw API Response (if error during parsing) ---")
             print(result_data.get('seo_agent_raw_response'))

    logger.info("--- ADVANCED SEO Article Agent Standalone Test Complete ---")