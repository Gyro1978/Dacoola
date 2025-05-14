# src/agents/seo_article_generator_agent.py 

import os
import sys
import requests
import json
import logging
import re
from dotenv import load_dotenv
from datetime import datetime, timezone

# --- Path Setup ---
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
MAX_TOKENS_RESPONSE = 7000 
TEMPERATURE = 0.68 
API_TIMEOUT_SECONDS = 360 

# --- Agent Prompts ---

SEO_PROMPT_SYSTEM = """
You are an **Ultimate SEO Content Architect and Expert Tech News Analyst**, operating as a world-class journalist for `{YOUR_WEBSITE_NAME}`. Your core mission is to synthesize the provided `{{ARTICLE_CONTENT_FOR_PROCESSING}}` into a comprehensive, engaging, factually precise, and maximally SEO-optimized news article. Your writing MUST be indistinguishable from high-quality human journalism, avoiding common AI writing patterns and clichés. You MUST adhere strictly to ALL directives below.

**I. Foundational Principles:**

1.  **Source Adherence & Expansion:** Base article *primarily* on `{{ARTICLE_CONTENT_FOR_PROCESSING}}`. Expand briefly only with widely accepted context or logical inference; *never* invent facts/quotes. Synthesize full text significantly; avoid simple paraphrasing.
2.  **Target Audience:** Tech-savvy readers interested in AI/Tech news. Assume baseline knowledge; define niche terms concisely if used.
3.  **E-E-A-T:** Write with expertise, grounding claims in the source. Ensure accuracy. Attribute implicitly ("The announcement indicated...") or explicitly if possible.
4.  **Helpful Content:** Prioritize informing the reader. SEO supports readability/UX.

**II. SEO Optimization Strategy (CRITICAL FOR TITLES/HEADLINES):**

5.  **Keyword Integration:** Naturally integrate `{{TARGET_KEYWORD}}` into Title Tag, Meta Description, H1, first ~100 words, and 1-2 relevant subheadings/paragraphs. If `{{SECONDARY_KEYWORDS_LIST_STR}}` is provided and not empty, naturally weave 1-2 of these into body/subheadings. **NO KEYWORD STUFFING.**
6.  **Catchy & SEO Title/H1 Generation:**
    *   **SEO H1 (`## [Generated H1]`):** Must be **compelling, clear, and catchy**. It MUST prominently feature the main subject/product (e.g., "Absolute Zero") if identifiable and relevant, alongside the `{{TARGET_KEYWORD}}`.
    *   **Title Case:** The generated SEO H1 and Title Tag MUST use **Title Case** (e.g., "New AI Model 'Phoenix' Soars Past Benchmarks").
    *   **Intrigue & Benefit:** Hint at the significance or benefit to the reader. Avoid generic or bland phrasing.
    *   **Example Goal (if content was about "Absolute Zero")**: Instead of "Zero-data AI model surpasses systems", aim for something like: "Absolute Zero: Groundbreaking AI Achieves Top Reasoning With ZERO Human Data" or "Self-Learning Breakthrough: Absolute Zero AI Redefines Reasoning Without Expert Input".
7.  **Semantic Relevance:** Incorporate related terms, concepts, synonyms, and relevant entities from the source text naturally.
8.  **User Intent:** Address likely search intent for `{{TARGET_KEYWORD}}`. Anticipate questions for FAQs.

**III. Content Generation & Structure Requirements:**

9.  **Initial Summary:** 1-2 concise lead paragraphs summarizing core news from source. Include `{{TARGET_KEYWORD}}` in the first paragraph.
10. **In-Depth Analysis:** Expand with context, implications, background using logical headings (`### H3`, `#### H4`).
    *   **Main Analysis (`### H3`):** *One* descriptive H3 title (e.g., "### Key Innovations & Market Impact"). 2-4 paragraphs of core analysis.
    *   **Thematic Sub-sections (`#### H4`):** Descriptive H4 titles ("#### Technical Breakdown"). 1-2 paragraphs each. **Omit if not relevant/supported by content.**
11. **Pros & Cons (`#### Pros & Cons`):**
    *   **Generate ONLY if genuinely applicable and supported by content. Omit entirely otherwise.**
    *   Use **exact** H4 title: `#### Pros & Cons`. Use specified HTML.
12. **FAQ (HTML Block):**
    *   **Generate ONLY if topic warrants it (2-5 relevant Q&As). Omit ENTIRELY otherwise.**
    *   You will *only* generate the HTML block starting with `<div class="faq-section">` and ending with `</div>`.
    *   Do **NOT** include the `#### Frequently Asked Questions` Markdown heading before this block; the template will add it.
    *   Use the exact HTML structure for `<details>` and `<summary>` as specified in the user prompt.
13. **Overall Length & Tone:** **500-800 words**. Authoritative, objective, engaging, accessible journalistic tone.

**IV. Writing Style & Avoiding "AI Tells":** (NO CHANGES HERE - REMAINS CRITICAL)
    (Instructions 14-19 from previous prompt remain unchanged)

**V. Output Formatting (Strict Adherence Mandatory):**

20. **Markdown & HTML:** Main body is Markdown. Pros/Cons and FAQ use **exact** specified HTML for their respective blocks.
21. **Exact Output Order:** `Title Tag: ...\nMeta Description: ...\nSEO H1: ...\n\n## [SEO H1]\n{Article Body - Markdown, potentially including Pros/Cons HTML and FAQ HTML blocks}\nSource: [...](...)\n\n<script...>...</script>`
22. **Title Tag:** `Title Tag: [...]`. ≤ 60 chars. Incl. `{{TARGET_KEYWORD}}`. **MUST use Title Case.** Matches H1 closely or is a slightly condensed version.
23. **Meta Description:** `Meta Description: [...]`. ≤ 160 chars. Incl. `{{TARGET_KEYWORD}}`.
24. **SEO H1 (in preamble):** `SEO H1: [...]`. Matches `## H1` in body. **MUST use Title Case.**
25. **JSON-LD:** Populate accurately. `keywords` uses `{{ALL_GENERATED_KEYWORDS_JSON}}`. `headline` matches the generated SEO H1.

**VI. Error Handling:** (NO CHANGES HERE)
**VII. Final Check:** (NO CHANGES HERE)
"""

SEO_PROMPT_USER_TEMPLATE = """
Task: Generate Title Tag, Meta Description, SEO-Optimized H1 Heading, Article Body (Markdown, with HTML for Pros/Cons & FAQ if applicable), and JSON-LD Script based on context. Follow ALL System Prompt directives meticulously.
**Key Focus for this Task:**
1.  **Title & H1 Generation:** Create a **catchy, SEO-friendly Title Tag and H1 in Title Case**. Ensure they prominently feature the main subject/product (e.g., "Absolute Zero" if it's the core topic) AND the `{{TARGET_KEYWORD}}`. The H1 should be engaging and suitable for a news headline.
2.  **Content Structure:** Adhere to the specified structure. For Pros/Cons and FAQ, if generated, output them as HTML blocks directly within the Markdown body. **For FAQ, only output the `<div class="faq-section">...</div>` HTML block; do NOT include a Markdown H4 title for it.**
3.  **Writing Style:** Maintain a natural, human-like journalistic style. Strictly avoid AI clichés, em dashes (use standard hyphens), and unnecessary symbols.

**Input Context:**
ARTICLE_TITLE_FROM_SOURCE: {article_title_from_source}
ARTICLE_CONTENT_FOR_PROCESSING: {article_content_for_processing}
SOURCE_ARTICLE_URL: {source_article_url}
TARGET_KEYWORD: {target_keyword} 
SECONDARY_KEYWORDS_LIST_STR: {secondary_keywords_list_str} # If empty, do not force.
ARTICLE_IMAGE_URL: {article_image_url}
AUTHOR_NAME: {author_name}
CURRENT_DATE_YYYY_MM_DD: {current_date_iso}
YOUR_WEBSITE_NAME: {your_website_name}
YOUR_WEBSITE_LOGO_URL: {your_website_logo_url}
ALL_GENERATED_KEYWORDS_JSON: {all_generated_keywords_json}

**Required Output Format (Strict Adherence):**
Title Tag: [Generated catchy Title Tag in Title Case ≤ 60 chars. Must include TARGET_KEYWORD and ideally main product/subject name.]
Meta Description: [Generated meta description ≤ 160 chars, include TARGET_KEYWORD.]
SEO H1: [Generated catchy, SEO-Optimized H1 in Title Case. Must include TARGET_KEYWORD and ideally main product/subject name. Reflects core news.]

## [SEO H1 from above, verbatim]
[Paragraph 1-2: CONCISE summary. Include TARGET_KEYWORD. Journalistic tone. Standard hyphens ONLY.]

### [Contextual H3 Title - be descriptive]
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

[If generating FAQs, output ONLY the HTML block below. The template will add the H4 title.]
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

Source: [{article_title_from_source}]({source_article_url})

<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "NewsArticle",
  "headline": "[SEO H1 from above, verbatim]",
  "description": "[Generated meta description from above, verbatim]",
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
                content_stripped = content_stripped.replace('—', '-') 
                return content_stripped
            logger.error("API response 'content' is missing or empty.")
            return None
        else: logger.error(f"API response missing 'choices' or empty: {result}"); return None
    except requests.exceptions.Timeout: logger.error(f"API request timed out ({API_TIMEOUT_SECONDS}s)."); return None
    except requests.exceptions.RequestException as e: logger.error(f"API request failed: {e}"); return None
    except Exception as e: logger.exception(f"Unexpected error during API call: {e}"); return None

# --- Parsing Function ---
def parse_seo_agent_response(response_text):
    parsed_data = {}
    errors = []
    if not response_text or response_text.strip().startswith("Error:"): 
        error_message = f"SEO Agent returned error or empty response: {response_text or 'Empty response'}"
        logger.error(error_message)
        return None, error_message

    try:
        title_match = re.search(r"^\s*Title Tag:\s*(.*)", response_text, re.MULTILINE | re.IGNORECASE)
        if title_match: parsed_data['generated_title_tag'] = title_match.group(1).strip()
        else: errors.append("Missing 'Title Tag:' line.")

        meta_match = re.search(r"^\s*Meta Description:\s*(.*)", response_text, re.MULTILINE | re.IGNORECASE)
        if meta_match: parsed_data['generated_meta_description'] = meta_match.group(1).strip()
        else: errors.append("Missing 'Meta Description:' line.")

        seo_h1_match = re.search(r"^\s*SEO H1:\s*(.*)", response_text, re.MULTILINE | re.IGNORECASE)
        if seo_h1_match: parsed_data['generated_seo_h1'] = seo_h1_match.group(1).strip()
        else: errors.append("Missing 'SEO H1:' line in preamble.")

        script_match = re.search( r'<script\s+type\s*=\s*["\']application/ld\+json["\']\s*>\s*(\{[\s\S]*?\})\s*<\/script>', response_text, re.IGNORECASE )
        if script_match:
            json_content_str = script_match.group(1).strip()
            parsed_data['generated_json_ld'] = script_match.group(0).strip() 
            try: json.loads(json_content_str) 
            except json.JSONDecodeError as json_err: errors.append(f"JSON-LD content is invalid: {json_err}"); logger.warning(f"Invalid JSON-LD: {json_content_str[:200]}...")
        else: errors.append("Missing or malformed JSON-LD script block.")

        body_content = None
        body_start_pattern = r"^\s*SEO H1:.*?\n\n(## .*?)(?=\n\s*Source:|\n\s*<script)"
        body_match = re.search(body_start_pattern, response_text, re.MULTILINE | re.DOTALL | re.IGNORECASE)

        if body_match: body_content = body_match.group(1).strip()
        else:
            errors.append("Could not reliably extract Article Body between H1 and Source/Script.")
            seo_h1_line_end_pos = -1
            if seo_h1_match : 
                 match_obj = re.search(r"^\s*SEO H1:.*$", response_text, re.MULTILINE | re.IGNORECASE)
                 if match_obj: seo_h1_line_end_pos = match_obj.end()
            if seo_h1_line_end_pos != -1:
                potential_body_start = response_text[seo_h1_line_end_pos:].lstrip()
                if potential_body_start.startswith("##"):
                    source_pos = potential_body_start.find("\nSource:")
                    script_pos = potential_body_start.find("\n<script")
                    end_delimiters = []
                    if source_pos != -1: end_delimiters.append(source_pos)
                    if script_pos != -1: end_delimiters.append(script_pos)
                    if end_delimiters: body_content = potential_body_start[:min(end_delimiters)].strip()
                    else: body_content = potential_body_start.strip(); logger.warning("Body extraction fallback: No clear 'Source:' or '<script' delimiter.")
                else: errors.append("Fallback body extraction: Content after H1 preamble does not start with '##'.")
            else: errors.append("Fallback body extraction: Could not find H1 preamble line end.")

        if body_content and body_content.startswith("## "):
            parsed_data['generated_article_body_md'] = body_content
            body_h1_match = re.match(r"##\s*(.*)", body_content, re.IGNORECASE)
            if body_h1_match and parsed_data.get('generated_seo_h1'):
                if body_h1_match.group(1).strip() != parsed_data['generated_seo_h1']:
                    errors.append(f"H1 mismatch body ('{body_h1_match.group(1).strip()}') vs preamble ('{parsed_data['generated_seo_h1']})'). Using preamble.")
            elif not parsed_data.get('generated_seo_h1') and body_h1_match:
                 parsed_data['generated_seo_h1'] = body_h1_match.group(1).strip(); logger.info("Used H1 from body as preamble H1 was missing.")
        else:
            if not body_content: errors.append("Article Body content is empty.")
            elif not body_content.startswith("## "): errors.append(f"Extracted Body does not start with '## '. Actual: '{body_content[:30]}...'")
            parsed_data['generated_article_body_md'] = ""

        if not parsed_data.get('generated_seo_h1'): errors.append("CRITICAL: SEO H1 missing.")
        if not parsed_data.get('generated_title_tag'): parsed_data['generated_title_tag'] = parsed_data.get('generated_seo_h1', 'Error: Title Missing'); errors.append("Defaulted Title Tag.")
        if not parsed_data.get('generated_meta_description'): parsed_data['generated_meta_description'] = "Read the latest AI and Technology news from " + YOUR_WEBSITE_NAME; errors.append("Defaulted Meta Desc.")
        if not parsed_data.get('generated_json_ld'): parsed_data['generated_json_ld'] = '<script type="application/ld+json">{}</script>'

        if not parsed_data.get('generated_article_body_md') or not parsed_data.get('generated_seo_h1') or "Error: Title Missing" in parsed_data.get('generated_title_tag',''):
            final_error_message = f"Critical parsing failure. Errors: {'; '.join(errors or ['Unknown'])}"
            logger.error(final_error_message); logger.debug(f"Failed response for parsing:\n{response_text[:1000]}...")
            return None, final_error_message
        return parsed_data, ("; ".join(errors) if errors else None)
    except Exception as e:
        logger.exception(f"Critical parsing exception: {e}")
        return None, f"Major parsing exception: {e}"

# --- Main Agent Function ---
def run_seo_article_agent(article_data):
    article_id = article_data.get('id', 'N/A')
    content_to_process = article_data.get('content_for_processing')

    if not content_to_process:
        error_msg = f"Missing 'content_for_processing' for ID {article_id}."
        logger.error(error_msg)
        article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = error_msg
        return article_data

    primary_keyword = article_data.get('filter_verdict', {}).get('primary_topic_keyword', article_data.get('title','Untitled Article'))
    article_data['primary_keyword'] = primary_keyword 

    generated_tags = article_data.get('researched_keywords', [primary_keyword] if primary_keyword else [])
    secondary_keywords = [tag for tag in generated_tags if tag.lower() != primary_keyword.lower()][:3]
    secondary_keywords_list_str = ", ".join(secondary_keywords)
    all_valid_keywords_for_json_ld = [str(k).strip() for k in generated_tags if k and str(k).strip()]
    all_generated_keywords_json = json.dumps(list(set(all_valid_keywords_for_json_ld)))

    input_data_for_prompt = {
        "article_title_from_source": article_data.get('title', 'Untitled Article'), 
        "article_content_for_processing": content_to_process,
        "source_article_url": article_data.get('link', '#'),
        "target_keyword": primary_keyword,
        "secondary_keywords_list_str": secondary_keywords_list_str,
        "article_image_url": article_data.get('selected_image_url', ''),
        "author_name": article_data.get('author', YOUR_WEBSITE_NAME),
        "current_date_iso": article_data.get('published_iso') or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "your_website_name": YOUR_WEBSITE_NAME,
        "your_website_logo_url": YOUR_WEBSITE_LOGO_URL,
        "all_generated_keywords_json": all_generated_keywords_json
    }
    for key in input_data_for_prompt:
        if input_data_for_prompt[key] is None: input_data_for_prompt[key] = '' 

    try:
        formatted_system_prompt = SEO_PROMPT_SYSTEM.replace("{YOUR_WEBSITE_NAME}", YOUR_WEBSITE_NAME)
        user_prompt = SEO_PROMPT_USER_TEMPLATE.format(**input_data_for_prompt)
    except KeyError as e:
        logger.exception(f"KeyError formatting SEO prompt for {article_id}: {e}.")
        article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = f"Prompt template error: {e}"
        return article_data

    logger.info(f"Running SEO agent for {article_id} (Revised FAQ Prompt)...")
    raw_response_content = call_deepseek_api(formatted_system_prompt, user_prompt, max_tokens=MAX_TOKENS_RESPONSE, temperature=TEMPERATURE)

    if not raw_response_content:
        error_msg = f"SEO Agent API call failed for ID: {article_id}."
        logger.error(error_msg)
        article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = error_msg
        return article_data
    
    parsed_results, error_msg = parse_seo_agent_response(raw_response_content)
    article_data['seo_agent_results'] = parsed_results
    article_data['seo_agent_error'] = error_msg

    if parsed_results is None: logger.error(f"Failed parse SEO response for {article_id}: {error_msg}"); article_data['seo_agent_raw_response_on_parse_fail'] = raw_response_content 
    elif error_msg: logger.warning(f"SEO parsing for {article_id} with non-critical errors: {error_msg}")
    else: logger.info(f"Successfully generated and parsed SEO content for {article_id}.")

    if parsed_results and parsed_results.get('generated_seo_h1'):
        new_title = parsed_results['generated_seo_h1']
        if article_data.get('title') != new_title: 
            logger.info(f"Updating article title for {article_id} with SEO H1: '{new_title}' (was: '{article_data.get('title')}')")
            article_data['title'] = new_title
    elif not article_data.get('title'): article_data['title'] = "Untitled - SEO Error"
    return article_data

# --- Standalone Execution (for testing) ---
if __name__ == "__main__":
    # ... (standalone test code remains the same)
    logging.getLogger().setLevel(logging.DEBUG)
    logger.setLevel(logging.DEBUG)

    if not YOUR_WEBSITE_LOGO_URL:
        logger.warning("YOUR_WEBSITE_LOGO_URL is not set in .env, JSON-LD publisher logo will be empty.")

    test_article = {
        'id': 'test-seo-006', # New ID for testing
        'title': "AI Helps Discover New Materials", 
        'content_for_processing': """
A new AI model, MatDiscover, has been used by researchers to identify over 2 million hypothetical new crystal structures. 
This significantly accelerates the process of materials discovery, which traditionally relies on slow trial-and-error or computationally intensive simulations.
MatDiscover was trained on a vast database of known materials and their properties. It can predict the stability of novel atomic arrangements.
From its predictions, several hundred candidates were synthesized and tested, with a high success rate in creating stable new materials.
One promising discovery is a new type of transparent conductor, potentially useful for solar cells and displays.
The team plans to open-source the model and the database of predicted structures to foster further research.
Challenges remain in scaling up synthesis and thorough characterization of all promising candidates.
This development is seen as a major step towards AI-driven autonomous materials science.
Source: Example News Site about Materials AI.
""",
        'link': "https://example.com/matdiscover-ai-news",
        'selected_image_url': "https://example.com/matdiscover_image.jpg",
        'published_iso': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'filter_verdict': {
            'primary_topic_keyword': 'AI materials discovery'
        },
        'researched_keywords': ['AI materials discovery', 'MatDiscover AI', 'crystal structure prediction', 'AI in materials science', 'new material synthesis AI', 'transparent conductor AI', 'autonomous materials research']
    }

    logger.info("\n--- Running SEO Article Agent Standalone Test (Revised FAQ Prompt) ---")
    result_article = run_seo_article_agent(test_article.copy())

    if result_article.get('seo_agent_results'):
        print("\n--- Generated SEO Content ---")
        print(f"Title Tag: {result_article['seo_agent_results'].get('generated_title_tag')}")
        print(f"Meta Desc: {result_article['seo_agent_results'].get('generated_meta_description')}")
        print(f"SEO H1: {result_article['seo_agent_results'].get('generated_seo_h1')}")
        print(f"Final Article Title in data: {result_article.get('title')}")
        print(f"\nArticle Body (MD - first 500 chars):\n{result_article['seo_agent_results'].get('generated_article_body_md')[:500]}...")
        if "<div class=\"faq-section\">" in result_article['seo_agent_results'].get('generated_article_body_md', ''):
            print("\nFAQ section was generated by agent.")
        else:
            print("\nFAQ section was NOT generated by agent.")
        if result_article.get('seo_agent_error'):
            print(f"\nParsing/Validation Warnings: {result_article['seo_agent_error']}")
    else:
        print("\n--- SEO Agent FAILED ---")
        print(f"Error: {result_article.get('seo_agent_error')}")
        if result_article.get('seo_agent_raw_response_on_parse_fail'):
            print(f"Raw Response Snippet:\n{result_article['seo_agent_raw_response_on_parse_fail'][:500]}...")
    logger.info("\n--- SEO Article Agent Standalone Test Complete ---")