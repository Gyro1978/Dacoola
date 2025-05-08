# src/agents/seo_article_generator_agent.py (1/1) - FINAL V4 (Refined based on feedback)

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
AGENT_MODEL = "deepseek-chat"
MAX_TOKENS_RESPONSE = 6666 # Keep high for detailed articles
TEMPERATURE = 0.65 # Keep slightly balanced
API_TIMEOUT_SECONDS = 360

# --- Agent Prompts ---

SEO_PROMPT_SYSTEM = """
You are an **Ultimate SEO Content Architect and Expert Tech News Analyst**, operating as a world-class journalist for `{YOUR_WEBSITE_NAME}`. Your core mission is to synthesize the provided `{{ARTICLE_CONTENT_FOR_PROCESSING}}` into a comprehensive, engaging, factually precise, and maximally SEO-optimized news article. Your writing MUST be indistinguishable from high-quality human journalism, avoiding common AI writing patterns and clichés. You MUST adhere strictly to ALL directives below.

**I. Foundational Principles:**

1.  **Source Adherence & Expansion:** Base article *primarily* on `{{ARTICLE_CONTENT_FOR_PROCESSING}}`. Expand briefly only with widely accepted context or logical inference; *never* invent facts/quotes. Synthesize full text significantly; avoid simple paraphrasing.
2.  **Target Audience:** Tech-savvy readers interested in AI/Tech news. Assume baseline knowledge; define niche terms concisely if used.
3.  **E-E-A-T:** Write with expertise, grounding claims in the source. Ensure accuracy. Attribute implicitly ("The announcement indicated...") or explicitly if possible.
4.  **Helpful Content:** Prioritize informing the reader. SEO supports readability/UX.

**II. SEO Optimization Strategy:**

5.  **Keyword Integration:** Naturally integrate `{{TARGET_KEYWORD}}` into Title Tag, Meta Description, H1, first ~100 words, and 1-2 relevant subheadings/paragraphs. If `{{SECONDARY_KEYWORDS_LIST_STR}}` is provided and not empty, naturally weave 1-2 of these into body/subheadings. **NO KEYWORD STUFFING.**
6.  **Semantic Relevance:** Incorporate related terms, concepts, synonyms, and relevant entities from the source text naturally.
7.  **User Intent:** Address likely search intent for `{{TARGET_KEYWORD}}`. Anticipate questions for FAQs.

**III. Content Generation & Structure Requirements:**

8.  **SEO H1:** Compelling, clear H1 (`## [Generated H1]`) containing `{{TARGET_KEYWORD}}`.
9.  **Initial Summary:** 1-2 concise lead paragraphs summarizing core news from source. Include `{{TARGET_KEYWORD}}` in the first paragraph.
10. **In-Depth Analysis:** Expand with context, implications, background using logical headings (`### H3`, `#### H4`).
    *   **Main Analysis (`### H3`):** *One* descriptive H3 title (e.g., "### Key Innovations & Market Impact"). 2-4 paragraphs of core analysis.
    *   **Thematic Sub-sections (`#### H4`):** Descriptive H4 titles ("#### Technical Breakdown"). 1-2 paragraphs each. **Omit if not relevant/supported by content.**
11. **Pros & Cons (`#### Pros & Cons`):**
    *   **Generate ONLY if genuinely applicable and supported by content. Omit entirely otherwise.**
    *   Use **exact** H4 title: `#### Pros & Cons`.
    *   Use **exact HTML structure:** `<ul><li>...</li></ul>` within `.item-list` divs.
    *   **CRITICAL `<li>` Content:** Plain descriptive text only. **NO bolded titles/prefixes.** NO surrounding `**`. Markdown emphasis (*italic*, **bold**) OK *within* the description (e.g., "Allows *faster* processing...").
12. **FAQ (`#### Frequently Asked Questions`):**
    *   **Generate ONLY if topic warrants it. Omit entirely otherwise.**
    *   Use **exact** H4 title: `#### Frequently Asked Questions`.
    *   Generate **3-5 relevant questions** (or 2-3 if less content).
    *   Use **exact HTML structure** including icon: `<i class="faq-icon fas fa-chevron-down"></i>`.
13. **Overall Length & Tone:** **500-800 words**. Authoritative, objective, engaging, accessible journalistic tone.

**IV. Writing Style & Avoiding "AI Tells":**

14. **Natural Language & Flow:** Write like an experienced human journalist. Ensure smooth transitions. Be concise. Vary vocabulary (e.g., use "tests", "evaluations" instead of repeating "benchmarks").
15. **AVOID LLM Phrases:** Strictly avoid: *groundbreaking, tackle, delve into, harness, unleash, pave the way, revolutionize, empower, leverage, unlock, elevated, nuanced, intricate, pivotal, lauded, meticulous, moreover, furthermore, additionally, in light of, one might consider, it stands to reason, it is worth noting, in the event that, in other words, to put it simply, that is to say, for instance, it is important to note, crucially, significantly, fundamentally, cutting-edge, state-of-the-art, paradigm shift, synergy, robust, scalability, streamline, advent, akin, arduous, conversely, research needed to understand, despite facing, today’s digital age, expressed excitement, focusing on, aiming to, not only... but also, in conclusion, overall*. Use simpler synonyms.
16. **STRICTLY FORBIDDEN SYMBOLS/PATTERNS:**
    *   **NO Em Dashes (`—`):** Use standard hyphens (`-`) only.
    *   **Minimal Ellipses (`...`):** Only for necessary quote truncation.
    *   **Minimal Semicolons (`;`):** Prefer shorter sentences or commas.
    *   **Standard Punctuation:** Standard quotes (`"`, `'`). No typographic/curly quotes (`“ ” ‘ ’`) unless quoting source. No `¶`, `§`.
    *   **No Unnecessary Markup:** HTML lists ONLY for Pros/Cons. No inline backticks (` `) unless essential for code terms. No triple backticks unless showing actual code.
17. **Sentence Variation & Active Voice:** Mix sentence lengths. Strongly prefer active voice.
18. **Consistent Tense:** Maintain consistent verb tense (usually past for news).
19. **Tone Adaptation:** Adapt slightly to source complexity but maintain professional tone. Do not copy sentence structures.

**V. Output Formatting (Strict Adherence Mandatory):**

20. **Markdown & HTML:** Main body is Markdown. Pros/Cons and FAQ use **exact** specified HTML.
21. **Exact Output Order:** `Title Tag: ...\nMeta Description: ...\nSEO H1: ...\n\n## [SEO H1]\n{Article Body}\nSource: [...](...)\n\n<script...>...</script>`
22. **Title Tag:** `Title Tag: [...]`. ≤ 60 chars. Incl. `{{TARGET_KEYWORD}}`.
23. **Meta Description:** `Meta Description: [...]`. ≤ 160 chars. Incl. `{{TARGET_KEYWORD}}`.
24. **SEO H1:** `SEO H1: [...]`. Matches `## H1` in body.
25. **JSON-LD:** Populate accurately. `keywords` uses `{{ALL_GENERATED_KEYWORDS_JSON}}`.

**VI. Error Handling:**

26. If `{{ARTICLE_CONTENT_FOR_PROCESSING}}` < ~50 words, output ONLY: `Error: Input content insufficient for generation.`

**VII. Final Check:**

27. **NO Extra Text:** Absolutely NO text before `Title Tag:` or after `</script>`.
"""

SEO_PROMPT_USER_TEMPLATE = """
Task: Generate Title Tag, Meta Description, SEO-Optimized H1 Heading, Article Body, and JSON-LD Script based on context. Follow ALL System Prompt directives meticulously. Pay extreme attention to: avoiding forbidden AI phrases/symbols (NO EM DASHES `—`), using specified HTML ONLY for Pros/Cons (NO bold titles/prefixes/markdown lists inside `<li>`) and FAQs, omitting optional sections (thematic H4s, Pros/Cons, FAQ) if not relevant/supported by content, varying vocabulary/sentence structure, and ensuring natural journalistic style. Handle empty `SECONDARY_KEYWORDS_LIST_STR` gracefully.

**Input Context:**
ARTICLE_TITLE: {article_title}
ARTICLE_CONTENT_FOR_PROCESSING: {article_content_for_processing}
SOURCE_ARTICLE_URL: {source_article_url}
TARGET_KEYWORD: {target_keyword}
SECONDARY_KEYWORDS_LIST_STR: {secondary_keywords_list_str} # If this is empty, do not try to force secondary keywords.
ARTICLE_IMAGE_URL: {article_image_url}
AUTHOR_NAME: {author_name}
CURRENT_DATE_YYYY_MM_DD: {current_date_iso}
YOUR_WEBSITE_NAME: {your_website_name}
YOUR_WEBSITE_LOGO_URL: {your_website_logo_url}
ALL_GENERATED_KEYWORDS_JSON: {all_generated_keywords_json} # Use this directly for JSON-LD keywords field

**Required Output Format (Strict Adherence):**
Title Tag: [Generated title tag ≤ 60 chars, include TARGET_KEYWORD]
Meta Description: [Generated meta description ≤ 160 chars, include TARGET_KEYWORD]
SEO H1: [Generated SEO-Optimized H1 heading, include TARGET_KEYWORD.]

## [SEO H1 from above]
[Paragraph 1-2: CONCISE summary. Include TARGET_KEYWORD. Journalistic tone. Standard hyphens ONLY.]

### [Contextual H3 Title]
[Paragraphs 2-4+: In-depth analysis. Weave in TARGET_KEYWORD again + 1-2 SECONDARY_KEYWORDS if provided/relevant. Vary sentences/vocabulary. AVOID AI clichés/em dashes.]

#### [Optional: Contextual H4 Title - OMIT IF NOT RELEVANT]
[Optional: 1-2 paragraphs. OMIT ENTIRE SECTION if not applicable.]

#### [Optional: Pros & Cons - OMIT IF NOT APPLICABLE]
[Use exact H4 title. Items MUST be HTML `<li>` containing ONLY descriptive text (internal **bold** okay). NO titles/prefixes/surrounding `**` inside `<li>`. NO markdown lists inside `<li>`.]
<div class="pros-cons-container">
  <div class="pros-section">
    <h5 class="section-title">Pros</h5>
    <div class="item-list">
      <ul>
        <li>Explanation of the first advantage, perhaps with *emphasis*.</li>
        <li>Description of a second pro.</li>
      </ul>
    </div>
  </div>
  <div class="cons-section">
    <h5 class="section-title">Cons</h5>
    <div class="item-list">
      <ul>
        <li>Description of a limitation or con.</li>
        <li>Further potential downside.</li>
      </ul>
    </div>
  </div>
</div>

#### [Optional: Contextual H4 Title - OMIT IF NOT RELEVANT]
[Optional: 1-2 paragraphs. OMIT ENTIRE SECTION if not applicable.]

#### [Optional: Frequently Asked Questions - OMIT IF NOT APPLICABLE]
[Use exact H4 title. Generate 3-5 Q&As (or 2-3). Use exact HTML structure with `<i class="faq-icon fas fa-chevron-down"></i>`.]
<div class="faq-section">
  <details class="faq-item">
    <summary class="faq-question">First relevant question? <i class="faq-icon fas fa-chevron-down"></i></summary>
    <div class="faq-answer-content">
      <p>Concise answer.</p>
    </div>
  </details>
  <details class="faq-item">
    <summary class="faq-question">Second relevant question? <i class="faq-icon fas fa-chevron-down"></i></summary>
    <div class="faq-answer-content">
      <p>Detailed answer.</p>
    </div>
  </details>
  <details class="faq-item">
    <summary class="faq-question">Third relevant question? <i class="faq-icon fas fa-chevron-down"></i></summary>
    <div class="faq-answer-content">
      <p>Insightful answer.</p>
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
    if not DEEPSEEK_API_KEY: logger.error("DEEPSEEK_API_KEY not set."); return None
    headers = { "Content-Type": "application/json", "Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Accept": "application/json" }
    payload = { "model": AGENT_MODEL, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], "max_tokens": max_tokens, "temperature": temperature, "stream": False }
    try:
        logger.debug(f"Sending SEO generation request (model: {AGENT_MODEL})...")
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=API_TIMEOUT_SECONDS)
        response.raise_for_status()
        result = response.json()
        usage = result.get('usage');
        if usage: logger.debug(f"API Usage: Prompt={usage.get('prompt_tokens')}, Comp={usage.get('completion_tokens')}, Total={usage.get('total_tokens')}")
        if result.get("choices") and len(result["choices"]) > 0:
            message_content = result["choices"][0].get("message", {}).get("content")
            if message_content:
                content_stripped = message_content.strip()
                if content_stripped.startswith("```") and content_stripped.endswith("```"):
                     first_newline = content_stripped.find('\n'); content_stripped = content_stripped[first_newline+1:-3].strip() if first_newline != -1 else content_stripped[3:-3].strip()
                # Replace em dashes globally AFTER generation, just in case
                content_stripped = content_stripped.replace('—', '-')
                return content_stripped
            return None
        else: logger.error(f"API response missing 'choices': {result}"); return None
    except requests.exceptions.Timeout: logger.error(f"API request timed out ({API_TIMEOUT_SECONDS}s)."); return None
    except requests.exceptions.RequestException as e: logger.error(f"API request failed: {e}"); return None
    except Exception as e: logger.exception(f"Unexpected error during API call: {e}"); return None

# --- Parsing Function ---
def parse_seo_agent_response(response_text):
    # ... (No changes needed here) ...
    parsed_data = {}
    errors = []
    if not response_text or response_text.strip().startswith("Error:"):
        error_message = f"SEO Agent returned error or empty: {response_text or 'Empty'}"
        logger.error(error_message); return None, error_message
    try:
        title_match = re.search(r"^\s*Title Tag:\s*(.*)", response_text, re.M | re.I)
        if title_match: parsed_data['generated_title_tag'] = title_match.group(1).strip()
        else: errors.append("Missing 'Title Tag:' line.")
        meta_match = re.search(r"^\s*Meta Description:\s*(.*)", response_text, re.M | re.I)
        if meta_match: parsed_data['generated_meta_description'] = meta_match.group(1).strip()
        else: errors.append("Missing 'Meta Description:' line.")
        seo_h1_match = re.search(r"^\s*SEO H1:\s*(.*)", response_text, re.M | re.I)
        if seo_h1_match: parsed_data['generated_seo_h1'] = seo_h1_match.group(1).strip()
        else: errors.append("Missing 'SEO H1:' line.")
        script_match = re.search(r'<script\s+type\s*=\s*["\']application/ld\+json["\']\s*>\s*(\{.*?\})\s*<\/script>', response_text, re.S | re.I)
        if script_match:
            json_content_str = script_match.group(1).strip()
            parsed_data['generated_json_ld'] = script_match.group(0).strip()
            try: json.loads(json_content_str);
            except json.JSONDecodeError: errors.append("JSON-LD content invalid.")
        else: errors.append("Missing JSON-LD script block.")
        body_content = None
        body_match_to_source = re.search(r"^\s*SEO H1:.*?[\r\n]+([\s\S]*?)[\r\n]+\s*Source:", response_text, re.M | re.S | re.I)
        if body_match_to_source: body_content = body_match_to_source.group(1).strip()
        else:
            body_match_to_script = re.search(r"^\s*SEO H1:.*?[\r\n]+([\s\S]*?)[\r\n]*\s*<script", response_text, re.M | re.S | re.I)
            if body_match_to_script: body_content = body_match_to_script.group(1).strip()
        if body_content:
            if body_content.startswith("## "): parsed_data['generated_article_body_md'] = body_content
            else: errors.append("Extracted Body doesn't start with '## '."); parsed_data['generated_article_body_md'] = ""
        else: errors.append("Could not extract Article Body."); parsed_data['generated_article_body_md'] = ""
        if not parsed_data.get('generated_article_body_md') or not parsed_data.get('generated_seo_h1'):
            final_err = f"Critical parsing failure: Body/H1 missing. Errors: {'; '.join(errors or ['Unknown'])}"
            logger.error(final_err); logger.debug(f"Failed response:\n{response_text[:1000]}..."); return None, final_err
        parsed_data.setdefault('generated_title_tag', parsed_data.get('generated_seo_h1', 'Error'))
        parsed_data.setdefault('generated_meta_description', 'Error')
        parsed_data.setdefault('generated_json_ld', '<script type="application/ld+json">{}</script>')
        return parsed_data, ("; ".join(errors) if errors else None)
    except Exception as e: logger.exception(f"Critical parse error: {e}"); return None, f"Parsing exception: {e}"

# --- Main Agent Function ---
def run_seo_article_agent(article_data):
    # ... (No changes needed here) ...
    article_id = article_data.get('id', 'N/A')
    content_to_process = article_data.get('content_for_processing')
    if not content_to_process: error_msg = f"Missing content {article_id}."; logger.error(error_msg); article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = error_msg; return article_data
    primary_keyword = article_data.get('filter_verdict', {}).get('primary_topic_keyword')
    if not primary_keyword: error_msg = f"Missing primary kw {article_id}."; logger.error(error_msg); article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = error_msg; return article_data
    generated_tags = article_data.get('generated_tags', [])
    secondary_keywords = [tag for tag in generated_tags if tag.lower() != primary_keyword.lower()][:3]
    secondary_keywords_list_str = ", ".join(secondary_keywords)
    all_keywords = ([primary_keyword] if primary_keyword else []) + generated_tags
    all_keywords = [str(k).strip() for k in all_keywords if k and str(k).strip()]
    all_generated_keywords_json = json.dumps(list(set(all_keywords)))
    input_data_for_prompt = {
        "article_title": article_data['title'], "article_content_for_processing": content_to_process,
        "source_article_url": article_data['link'], "target_keyword": primary_keyword,
        "secondary_keywords_list_str": secondary_keywords_list_str, "article_image_url": article_data['selected_image_url'],
        "author_name": article_data.get('author', 'AI News Team'), "current_date_iso": article_data.get('published_iso') or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "your_website_name": YOUR_WEBSITE_NAME, "your_website_logo_url": YOUR_WEBSITE_LOGO_URL,
        "all_generated_keywords_json": all_generated_keywords_json
    }
    critical_inputs = ['article_title', 'article_content_for_processing', 'source_article_url', 'target_keyword', 'article_image_url', 'current_date_iso', 'all_generated_keywords_json', 'your_website_name']
    if any(input_data_for_prompt.get(k) is None for k in critical_inputs):
        missing = [k for k in critical_inputs if input_data_for_prompt.get(k) is None]
        error_msg = f"Critical data missing for prompt {article_id}: {missing}"
        logger.error(error_msg); article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = error_msg; return article_data
    try: user_prompt = SEO_PROMPT_USER_TEMPLATE.format(**input_data_for_prompt)
    except KeyError as e: logger.exception(f"KeyError formatting SEO prompt {article_id}: {e}"); article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = f"Prompt format error: {e}"; return article_data
    logger.info(f"Running SEO agent for {article_id} (V4 Refinement)...")
    raw_response_content = call_deepseek_api(SEO_PROMPT_SYSTEM, user_prompt, max_tokens=MAX_TOKENS_RESPONSE, temperature=TEMPERATURE)
    if not raw_response_content: error_msg = "API call failed/empty."; logger.error(f"{error_msg} ({article_id})."); article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = error_msg; return article_data
    logger.debug(f"Raw SEO Agent Response {article_id}:\n{raw_response_content[:1500]}...")
    parsed_results, error_msg = parse_seo_agent_response(raw_response_content)
    article_data['seo_agent_results'] = parsed_results; article_data['seo_agent_error'] = error_msg
    if parsed_results is None: logger.error(f"Failed parse SEO response {article_id}: {error_msg}"); article_data['seo_agent_raw_response'] = raw_response_content
    elif error_msg: logger.warning(f"SEO parsing completed with non-critical errors {article_id}: {error_msg}")
    else:
        logger.info(f"Successfully generated/parsed SEO content for {article_id}.")
        if parsed_results.get('generated_seo_h1') and parsed_results['generated_seo_h1'] != article_data['title']:
            logger.info(f"Updating title {article_id} with SEO H1: '{parsed_results['generated_seo_h1']}'")
            article_data['title'] = parsed_results['generated_seo_h1']
    return article_data

# --- Standalone Execution (for testing) ---
if __name__ == "__main__":
    # ... (Standalone test code remains the same) ...
    pass