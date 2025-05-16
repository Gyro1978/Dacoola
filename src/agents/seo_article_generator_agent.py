# src/agents/seo_article_generator_agent.py

import os
import sys
import requests
import json
import logging
import re
from dotenv import load_dotenv
from datetime import datetime, timezone
from urllib.parse import urljoin # For creating canonical URL

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
BASE_URL_FOR_CANONICAL = os.getenv('YOUR_SITE_BASE_URL', 'https://your-site-url.com')

# --- Configuration ---
AGENT_MODEL = "deepseek-chat"
MAX_TOKENS_RESPONSE = 7500
TEMPERATURE = 0.65
API_TIMEOUT_SECONDS = 400

# --- Agent Prompts ---

SEO_PROMPT_SYSTEM = """
You are an **Ultimate SEO Content Architect and Expert Tech News Analyst**, operating as a world-class journalist for `{YOUR_WEBSITE_NAME}`. Your core mission is to synthesize the provided `{{ARTICLE_CONTENT_FOR_PROCESSING}}` into a comprehensive, engaging, factually precise, and maximally SEO-optimized news article. Your writing MUST be indistinguishable from high-quality human journalism, avoiding common AI writing patterns and clichés (e.g., "delve into," "landscape," "ever-evolving," "testament to," "pivotal role," "robust," "seamless," "leverage," "game-changer," "in the realm of"). You MUST adhere strictly to ALL directives below.

**I. Foundational Principles:**
1.  **Source Adherence & Expansion:** Base the article *primarily* on `{{ARTICLE_CONTENT_FOR_PROCESSING}}`. Expand briefly ONLY with widely accepted, directly relevant context or logical inference. **Never invent facts, quotes, or statistics.** Synthesize the provided content significantly; avoid simple paraphrasing.
2.  **Target Audience:** Tech-savvy readers interested in AI/Tech news. Assume baseline knowledge; define truly niche terms concisely if used. Write in a conversational yet professional blog style. Use contractions (e.g., "it's", "don't") and varied sentence structures for natural phrasing.
3.  **E-E-A-T (Experience, Expertise, Authoritativeness, Trustworthiness):** Write with expertise, grounding claims in the provided source. Ensure accuracy. Attribute implicitly (e.g., "The announcement indicated...") or explicitly if source allows.
4.  **Helpful Content:** Prioritize informing the reader clearly and comprehensively. SEO elements should support readability and user experience, not detract from them.

**II. SEO Optimization Strategy:**
5.  **Keyword Integration:** Naturally integrate `{{TARGET_KEYWORD}}` into the Title Tag, Meta Description, H1, the first ~100 words of the article body, and 1-2 relevant subheadings/paragraphs if it fits organically. If `{{SECONDARY_KEYWORDS_LIST_STR}}` is provided and not empty, naturally weave 1-2 of these secondary keywords into the body or subheadings where relevant. **NO KEYWORD STUFFING.** Keywords should flow naturally within sentences.
6.  **Catchy & SEO Title/H1 Generation (Critical):**
    *   **SEO H1 (output as `## [Generated H1]`):** Must be **compelling, clear, and catchy**. It MUST prominently feature the main subject/product (e.g., "OpenAI's GPT-5") if identifiable and relevant from the content, alongside the `{{TARGET_KEYWORD}}`.
    *   **Title Case:** Both the generated SEO H1 and the Title Tag MUST use **Title Case** (e.g., "New AI Model 'Phoenix' Soars Past Industry Benchmarks").
    *   **Intrigue & Benefit:** Hint at the significance or benefit to the reader. Avoid generic, bland, or overly technical phrasing unless the target keyword is inherently technical.
7.  **Semantic Relevance:** Incorporate related terms, concepts, synonyms, and relevant entities from the source text naturally throughout the article.
8.  **User Intent:** Address the likely search intent for `{{TARGET_KEYWORD}}`. Anticipate potential questions for the FAQ section if applicable.

**III. Content Generation & Structure Requirements:**
9.  **Initial Summary (Markdown):** 1-2 concise lead paragraphs (approx. 50-100 words total) summarizing the core news from the source. These paragraphs MUST be in **Markdown**. Include `{{TARGET_KEYWORD}}` within the first paragraph naturally.
10. **In-Depth Analysis (Markdown):** Expand on the summary with context, implications, and background using logical **Markdown headings** (`### H3`, `#### H4`). All paragraphs in this section MUST be in **Markdown**.
    *   **Main Analysis Section (using `### H3` in Markdown):** Create *one* clear, descriptive H3 title (e.g., "### Key Innovations and Market Impact"). Follow with 2-4 paragraphs of core analysis and discussion, all in **Markdown**.
    *   **Thematic Sub-sections (using `#### H4` in Markdown):** Under the H3, use 1-3 descriptive H4 titles for distinct sub-topics if the content supports them (e.g., "#### Technical Breakdown," "#### Ethical Considerations"). Each H4 section should have 1-2 paragraphs, all in **Markdown**. **Omit H4 sections entirely if not relevant or sufficiently supported by `{{ARTICLE_CONTENT_FOR_PROCESSING}}`.**
11. **Pros & Cons (HTML Snippet):**
    *   Generate this section **ONLY IF** `{{ARTICLE_CONTENT_FOR_PROCESSING}}` clearly presents distinct advantages and disadvantages. **Omit entirely otherwise.**
    *   If included, use the **exact** H4 Markdown title: `#### Pros & Cons`. The content for pros and cons list items MUST be generated as the **exact HTML snippet** provided in the user prompt's output format example.
11.b. **In-Article Ad Placeholder (HTML Comment):** After the first 2 or 3 paragraphs of the main article body (typically after the initial summary paragraphs and before any `### H3` subheading), insert the exact HTML comment: `<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->`. Insert this placeholder **only ONCE**.
12. **FAQ (HTML Snippet):**
    *   Generate this section **ONLY IF** the topic naturally warrants a Q&A format. **Omit entirely otherwise.**
    *   If included, use the **exact** H4 Markdown title: `#### Frequently Asked Questions`. The Q&A content MUST be generated as the **exact HTML snippet** provided in the user prompt's output format example.
13. **Overall Length & Tone:** Aim for approximately **500-800 words** for the main article body (excluding JSON-LD, etc.). Maintain an authoritative, objective, yet engaging and accessible journalistic tone.

**IV. Writing Style & Avoiding "AI Tells":**
14. **Direct & Concise:** Use clear, straightforward language. Avoid jargon where simpler terms suffice.
15. **Varied Sentence Structure:** Mix short, impactful sentences with more complex ones. Avoid repetitive sentence beginnings.
16. **Active Voice:** Prefer active voice over passive voice for stronger impact.
17. **No Redundancy:** Ensure each sentence and paragraph adds new value.
18. **Specific Language:** Use precise verbs and nouns. Avoid vague words like "things," "stuff," "many," "various."
19. **Human-like Flow:** Read the article aloud to ensure it sounds natural and engaging. Use standard hyphens (-) instead of em dashes (—).

**V. Output Formatting (Strict Adherence Mandatory):**
20. **MAIN BODY IS MARKDOWN:** All general text, headings (like `## H1`, `### H3`, `#### H4`), paragraphs, and standard lists (bulleted/numbered) that are NOT part of the specific "Pros & Cons" or "Frequently Asked Questions" HTML snippets MUST be in **standard Markdown format**. Do NOT use `<p>`, `<h2>`, `<h3>`, `<h4>`, `<ul>`, `<li>` HTML tags for this general body content. Use Markdown equivalents like `##`, `###`, `####`, blank lines for paragraphs, and `*` or `-` for lists.
21. **HTML SNIPPETS FOR SPECIFIC SECTIONS ONLY:** Only the "Pros & Cons" section (if included, using the `#### Pros & Cons` Markdown heading followed by the provided HTML `div.pros-cons-container...`) and the "Frequently Asked Questions" section (if included, using the `#### Frequently Asked Questions` Markdown heading followed by the provided HTML `div.faq-section...`) MUST use the exact HTML code snippets as shown in the user prompt's example format. The In-Article Ad Placeholder is an HTML comment (`<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->`).
22. **Exact Output Order:** Your entire response MUST follow this order:
    Title Tag: [Generated Title Tag]
    Meta Description: [Generated Meta Description]
    SEO H1: [Generated SEO H1]

    ## [SEO H1 from above, verbatim - THIS IS MARKDOWN H1]
    {**MARKDOWN** Article Body, which may include the specific HTML snippets for Pros/Cons or FAQ if they are generated, and the HTML ad placeholder}
    Source: [{ARTICLE_TITLE_FROM_SOURCE}]({SOURCE_ARTICLE_URL})

    <script type="application/ld+json">
    {{JSON-LD content as specified}}
    </script>
23. **Title Tag:** Output as `Title Tag: [Generated text]`. Max length: ~60 characters. Must include `{{TARGET_KEYWORD}}`. **MUST use Title Case.** Should closely match or be a condensed version of the SEO H1.
24. **Meta Description:** Output as `Meta Description: [Generated text]`. Max length: ~160 characters. Must include `{{TARGET_KEYWORD}}` and be engaging.
25. **SEO H1 (in preamble):** Output as `SEO H1: [Generated text]`. This must be identical to the H1 used in the `## [SEO H1]` line in the article body. **MUST use Title Case.**
26. **JSON-LD Script:** Populate the `NewsArticle` schema accurately. `keywords` field should use the content of `{{ALL_GENERATED_KEYWORDS_JSON}}`. `headline` field must match the generated SEO H1. The `mainEntityOfPage.@id` should use `{{MY_CANONICAL_URL_PLACEHOLDER}}`.

**VI. Error Handling:** If you cannot fulfill a part of the request due to limitations or unclear input, note it briefly in a comment within the generated text if absolutely necessary, but prioritize completing the rest of the structure.
**VII. Final Check:** Before outputting, mentally review all instructions. Ensure every constraint is met, especially the Markdown vs. HTML distinction for body content.
"""

SEO_PROMPT_USER_TEMPLATE = """
Task: Generate the Title Tag, Meta Description, SEO-Optimized H1 Heading, Article Body (primarily in **Markdown**, but using specific HTML snippets for Pros/Cons and FAQ if included, and the HTML comment for the ad placeholder), and JSON-LD Script based on the provided context. Follow ALL System Prompt directives meticulously, especially the Markdown vs. HTML formatting rules.

**Key Focus for this Task:**
1.  **Title & H1 Generation:** Create a **catchy, SEO-friendly Title Tag and H1 in Title Case**. Ensure they prominently feature the main subject/product from the content AND the `{{TARGET_KEYWORD}}`. The H1 should be engaging and suitable for a news headline.
2.  **Content Structure & Formatting:**
    *   The main article content (paragraphs, H2, H3, H4) MUST be in **Markdown**.
    *   The `<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->` placeholder is mandatory.
    *   If Pros/Cons or FAQ sections are generated, they MUST use the exact HTML snippets provided in the example below, embedded within the Markdown flow AFTER their respective Markdown `####` headings.
    *   Omit optional sections (H4s beyond the main analysis H3, Pros/Cons, FAQ) if `{{ARTICLE_CONTENT_FOR_PROCESSING}}` doesn't clearly and robustly support them.
3.  **Writing Style:** Maintain a natural, human-like journalistic style. Strictly avoid AI clichés, em dashes (use standard hyphens), and unnecessary symbols.

**Input Context:**
ARTICLE_TITLE_FROM_SOURCE: {article_title_from_source}
ARTICLE_CONTENT_FOR_PROCESSING: {article_content_for_processing}
SOURCE_ARTICLE_URL: {source_article_url}
TARGET_KEYWORD: {target_keyword}
SECONDARY_KEYWORDS_LIST_STR: {secondary_keywords_list_str} # If empty, do not force usage.
ARTICLE_IMAGE_URL: {article_image_url}
AUTHOR_NAME: {author_name}
CURRENT_DATE_YYYY_MM_DD_ISO: {current_date_iso}
YOUR_WEBSITE_NAME: {your_website_name}
YOUR_WEBSITE_LOGO_URL: {your_website_logo_url}
ALL_GENERATED_KEYWORDS_JSON: {all_generated_keywords_json} # This is a JSON string array of keywords
MY_CANONICAL_URL_PLACEHOLDER: {my_canonical_url_placeholder} # Placeholder for the canonical URL of *this* article

**Required Output Format (Strict Adherence - Note Markdown vs HTML):**
Title Tag: [Generated catchy Title Tag in Title Case, approx. 50-60 chars. Must include TARGET_KEYWORD and ideally main product/subject name.]
Meta Description: [Generated meta description, approx. 150-160 chars. Must include TARGET_KEYWORD. Make it compelling.]
SEO H1: [Generated catchy, SEO-Optimized H1 in Title Case. Must include TARGET_KEYWORD and ideally main product/subject name. Reflects core news.]

## [SEO H1 from above, verbatim. This is a MARKDOWN H1.]
[Paragraph 1-2: **MUST BE MARKDOWN**. CONCISE summary (approx. 50-100 words). Include TARGET_KEYWORD naturally. Journalistic tone. Standard hyphens ONLY. NO `<p>` TAGS HERE.]

<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->

### [Contextual H3 Title for Main Analysis: **MUST BE MARKDOWN H3 (`### Your Title`)**. Descriptive. After ad placeholder.]
[Paragraphs 2-4+: **MUST BE MARKDOWN**. In-depth analysis. Weave in TARGET_KEYWORD again if natural, + 1-2 SECONDARY_KEYWORDS if provided and they fit organically. Vary sentence structures and vocabulary. AVOID AI clichés and em dashes. NO `<p>` TAGS HERE.]

#### [Optional H4 Title: **MUST BE MARKDOWN H4 (`#### Your Title`)**. OMIT IF NOT RELEVANT.]
[Optional: 1-2 paragraphs: **MUST BE MARKDOWN**. OMIT ENTIRE H4 SECTION if not applicable. NO `<p>` TAGS HERE.]

#### [Optional: Pros & Cons - OMIT IF NOT APPLICABLE. If included, H4 title is **MARKDOWN (`#### Pros & Cons`)**, list is HTML snippet directly AFTER the H4 heading]
#### Pros & Cons
<div class="pros-cons-container">
  <div class="pros-section">
    <h5 class="section-title">Pros</h5>
    <div class="item-list">
      <ul>
        <li>Explanation of the first advantage, perhaps with <em>emphasis</em>.</li>
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

#### [Optional H4 Title: **MUST BE MARKDOWN H4 (`#### Your Title`)**. OMIT IF NOT RELEVANT.]
[Optional: 1-2 paragraphs: **MUST BE MARKDOWN**. OMIT ENTIRE H4 SECTION if not applicable. NO `<p>` TAGS HERE.]

#### [Optional: Frequently Asked Questions - OMIT IF NOT APPLICABLE. If included, H4 title is **MARKDOWN (`#### Frequently Asked Questions`)**, Q&A is HTML snippet directly AFTER the H4 heading]
#### Frequently Asked Questions
<div class="faq-section">
  <details class="faq-item">
    <summary class="faq-question">First relevant question based on the article content? <i class="faq-icon fas fa-chevron-down"></i></summary>
    <div class="faq-answer-content">
      <p>Concise and factual answer based on the article content.</p>
    </div>
  </details>
  <details class="faq-item">
    <summary class="faq-question">Second relevant question from the article? <i class="faq-icon fas fa-chevron-down"></i></summary>
    <div class="faq-answer-content">
      <p>Detailed and informative answer derived from the article.</p>
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
  "mainEntityOfPage": {{ "@type": "WebPage", "@id": "{my_canonical_url_placeholder}" }},
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
        logger.debug(f"Sending SEO generation request (model: {AGENT_MODEL}). Est. User Prompt Tokens: ~{len(user_prompt)//3}")
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=API_TIMEOUT_SECONDS)
        response.raise_for_status()
        result = response.json()
        usage = result.get('usage')
        if usage:
            logger.debug(f"API Usage: Prompt Tokens={usage.get('prompt_tokens')}, Completion Tokens={usage.get('completion_tokens')}, Total Tokens={usage.get('total_tokens')}")
        if result.get("choices") and len(result["choices"]) > 0:
            message_content = result["choices"][0].get("message", {}).get("content")
            if message_content:
                content_stripped = message_content.strip()
                if content_stripped.startswith("```") and content_stripped.endswith("```"):
                    first_newline = content_stripped.find('\n')
                    content_stripped = content_stripped[first_newline+1:-3].strip() if first_newline != -1 else content_stripped[3:-3].strip()
                content_stripped = content_stripped.replace('—', '-')
                return content_stripped
            else:
                logger.error("API response 'content' is missing or empty.")
                return None
        else:
            logger.error(f"API response missing 'choices' or 'choices' list is empty: {result}")
            return None
    except requests.exceptions.Timeout:
        logger.error(f"API request timed out after {API_TIMEOUT_SECONDS} seconds.")
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
        error_message = f"SEO Agent returned error or empty response: {response_text or 'Empty response'}"
        logger.error(error_message)
        return None, error_message

    try:
        title_match = re.search(r"^\s*Title Tag:\s*(.*)", response_text, re.MULTILINE | re.IGNORECASE)
        if title_match:
            parsed_data['generated_title_tag'] = title_match.group(1).strip()
        else:
            errors.append("Missing 'Title Tag:' line.")

        meta_match = re.search(r"^\s*Meta Description:\s*(.*)", response_text, re.MULTILINE | re.IGNORECASE)
        if meta_match:
            parsed_data['generated_meta_description'] = meta_match.group(1).strip()
        else:
            errors.append("Missing 'Meta Description:' line.")

        seo_h1_preamble_match = re.search(r"^\s*SEO H1:\s*(.*)", response_text, re.MULTILINE | re.IGNORECASE)
        if seo_h1_preamble_match:
            parsed_data['generated_seo_h1'] = seo_h1_preamble_match.group(1).strip()
        else:
            errors.append("Missing 'SEO H1:' line in preamble.")

        script_match = re.search(
            r'<script\s+type\s*=\s*["\']application/ld\+json["\']\s*>\s*(\{[\s\S]*?\})\s*<\/script>',
            response_text, re.IGNORECASE
        )
        if script_match:
            json_content_str = script_match.group(1).strip()
            parsed_data['generated_json_ld_raw'] = json_content_str
            parsed_data['generated_json_ld_full_script_tag'] = script_match.group(0).strip()
            try:
                json.loads(json_content_str.replace("{MY_CANONICAL_URL_PLACEHOLDER}", "https://example.com/placeholder-for-validation"))
            except json.JSONDecodeError as json_err:
                errors.append(f"JSON-LD content is invalid: {json_err}")
                logger.warning(f"Invalid JSON-LD detected (raw content): {json_content_str[:200]}...")
        else:
            errors.append("Missing or malformed JSON-LD script block.")

        body_content = None
        end_delimiters_pattern = r"(?=\n\s*Source:|\n\s*<script\s+type\s*=\s*[\"']application/ld\+json[\"'])"

        if seo_h1_preamble_match:
            body_start_offset = seo_h1_preamble_match.end()
            actual_h1_body_match = re.match(r"\s*\n\s*(## .*?)", response_text[body_start_offset:], re.DOTALL | re.IGNORECASE)
            if actual_h1_body_match:
                search_start_index_for_end_delimiter = body_start_offset + actual_h1_body_match.start(1)
                end_match = re.search(end_delimiters_pattern, response_text[search_start_index_for_end_delimiter:], re.MULTILINE | re.DOTALL | re.IGNORECASE)
                if end_match:
                    body_content = response_text[search_start_index_for_end_delimiter : search_start_index_for_end_delimiter + end_match.start()].strip()
                else:
                    potential_body = response_text[search_start_index_for_end_delimiter:].strip()
                    if parsed_data.get('generated_json_ld_full_script_tag') and potential_body.endswith(parsed_data['generated_json_ld_full_script_tag']):
                        body_content = potential_body[:-len(parsed_data['generated_json_ld_full_script_tag'])].strip()
                    else:
                        body_content = potential_body
                    if "\nSource:" in body_content:
                        body_content = body_content.split("\nSource:", 1)[0].strip()
                    if body_content:
                        logger.warning("Body extraction: No clear 'Source:' or '<script' delimiter found via regex. Relied on greedy match and manual stripping.")
                    else:
                        errors.append("Body extraction: Could not find end delimiter and greedy match failed.")
            else:
                errors.append("Could not find '## H1 text' pattern starting the article body after 'SEO H1:' preamble.")
        else:
            errors.append("Could not find 'SEO H1:' preamble line, cannot reliably locate article body start.")

        if body_content and body_content.startswith("## "):
            parsed_data['generated_article_body_md'] = body_content
            body_h1_text_match = re.match(r"##\s*(.*)", body_content, re.IGNORECASE)
            if body_h1_text_match:
                body_h1_text = body_h1_text_match.group(1).strip()
                if parsed_data.get('generated_seo_h1'):
                    if body_h1_text != parsed_data['generated_seo_h1']:
                        errors.append(f"H1 in body ('{body_h1_text}') mismatches preamble H1 ('{parsed_data.get('generated_seo_h1', '')}'). Using preamble H1.")
                else:
                    parsed_data['generated_seo_h1'] = body_h1_text
                    logger.info("Used H1 from article body as 'SEO H1:' preamble line was missing.")
            else:
                errors.append("Extracted body starts with '## ' but could not parse H1 text from it.")
        else:
            if not body_content: errors.append("Article Body content is empty after extraction attempts.")
            elif body_content is not None and not body_content.startswith("## "): errors.append(f"Extracted Body does not start with '## '. Actual start: '{body_content[:50]}...'")
            parsed_data['generated_article_body_md'] = ""

        if not parsed_data.get('generated_seo_h1'):
            errors.append("CRITICAL: SEO H1 could not be determined.")
            parsed_data['generated_seo_h1'] = "Error: H1 Missing"
        if not parsed_data.get('generated_title_tag'):
            parsed_data['generated_title_tag'] = parsed_data.get('generated_seo_h1', 'Error: Title Missing')
            if 'Error: H1 Missing' not in parsed_data['generated_title_tag'] and 'Error: Title Missing' not in parsed_data['generated_title_tag']:
                 errors.append("Defaulted Title Tag to SEO H1.")
        if not parsed_data.get('generated_meta_description'):
            parsed_data['generated_meta_description'] = "Read the latest AI and Technology news from " + YOUR_WEBSITE_NAME
            errors.append("Defaulted Meta Description.")
        if not parsed_data.get('generated_json_ld_raw'):
             parsed_data['generated_json_ld_raw'] = '{}'
             parsed_data['generated_json_ld_full_script_tag'] = '<script type="application/ld+json">{}</script>'

        if not parsed_data.get('generated_article_body_md') or "Error: H1 Missing" in parsed_data.get('generated_seo_h1', ''):
            final_error_message = f"Critical parsing failure: Body or H1 missing or invalid. Errors: {'; '.join(errors if errors else ['Unknown parsing error'])}"
            logger.error(final_error_message)
            logger.debug(f"Failed response content for parsing was (first 1000 chars):\n{response_text[:1000]}...")
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
        error_msg = f"Missing 'content_for_processing' for article ID {article_id}."
        logger.error(error_msg)
        article_data['seo_agent_results'] = None
        article_data['seo_agent_error'] = error_msg
        return article_data

    primary_keyword = article_data.get('filter_verdict', {}).get('primary_topic_keyword')
    if not primary_keyword:
        primary_keyword = article_data.get('title', 'Untitled Article')
        logger.warning(f"Missing primary_topic_keyword for {article_id}. Using article title as primary keyword: '{primary_keyword}'")
    article_data['primary_keyword'] = primary_keyword

    generated_tags = article_data.get('researched_keywords', [])
    if not generated_tags and primary_keyword:
        generated_tags = [primary_keyword]
    secondary_keywords = [tag for tag in generated_tags if tag.lower() != primary_keyword.lower()][:3]
    secondary_keywords_list_str = ", ".join(secondary_keywords)

    all_valid_keywords_for_json_ld = list(set([str(k).strip() for k in generated_tags if k and str(k).strip()]))
    all_generated_keywords_json = json.dumps(all_valid_keywords_for_json_ld)

    my_canonical_url_placeholder_value = f"{BASE_URL_FOR_CANONICAL.rstrip('/')}/articles/{{SLUG_PLACEHOLDER}}"

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
        "all_generated_keywords_json": all_generated_keywords_json,
        "my_canonical_url_placeholder": my_canonical_url_placeholder_value
    }

    for key, value in input_data_for_prompt.items():
        if value is None:
            logger.warning(f"Input field '{key}' for SEO prompt is None for article {article_id}. Replacing with empty string or default.")
            input_data_for_prompt[key] = ''

    try:
        formatted_system_prompt = SEO_PROMPT_SYSTEM.replace("{YOUR_WEBSITE_NAME}", input_data_for_prompt["your_website_name"])
        user_prompt = SEO_PROMPT_USER_TEMPLATE.format(**input_data_for_prompt)
    except KeyError as e:
        logger.exception(f"KeyError formatting SEO prompt for article {article_id}: {e}. Check template variables and input_data_for_prompt.")
        article_data['seo_agent_results'] = None
        article_data['seo_agent_error'] = f"Prompt template formatting error: {e}"
        return article_data

    logger.info(f"Running SEO agent for article ID: {article_id} ('{input_data_for_prompt['article_title_from_source'][:50]}...').")
    raw_response_content = call_deepseek_api(formatted_system_prompt, user_prompt, max_tokens=MAX_TOKENS_RESPONSE, temperature=TEMPERATURE)

    if not raw_response_content:
        error_msg = "SEO Agent API call failed or returned empty/invalid content."
        logger.error(f"{error_msg} (Article ID: {article_id}).")
        article_data['seo_agent_results'] = None
        article_data['seo_agent_error'] = error_msg
        return article_data

    logger.debug(f"Raw SEO Agent Response for {article_id} (first 1500 chars for review):\n{raw_response_content[:1500]}...")
    parsed_results, error_msg = parse_seo_agent_response(raw_response_content)

    article_data['seo_agent_results'] = parsed_results
    article_data['seo_agent_error'] = error_msg

    if parsed_results is None:
        logger.error(f"Completely FAILED to parse SEO agent response for {article_id}: {error_msg}")
        article_data['seo_agent_raw_response_on_parse_fail'] = raw_response_content
    elif error_msg:
        logger.warning(f"SEO parsing for {article_id} completed with non-critical errors/warnings: {error_msg}")
    else:
        logger.info(f"Successfully generated and parsed SEO content for {article_id}.")

    if parsed_results and parsed_results.get('generated_seo_h1') and "Error: H1 Missing" not in parsed_results['generated_seo_h1']:
        new_title = parsed_results['generated_seo_h1']
        if article_data.get('title') != new_title:
            logger.info(f"Updating article title for {article_id} with generated SEO H1: '{new_title}' (was: '{article_data.get('title')}')")
            article_data['title'] = new_title
    elif not article_data.get('title'):
        article_data['title'] = "Untitled Article - SEO Processing Error"

    return article_data

# --- Standalone Execution (for testing) ---
if __name__ == "__main__":
    logging.getLogger().setLevel(logging.DEBUG)
    logger.setLevel(logging.DEBUG)

    if not DEEPSEEK_API_KEY:
        logger.error("CRITICAL FOR STANDALONE TEST: DEEPSEEK_API_KEY env var not set.")
        sys.exit(1)

    test_article = {
        'id': 'test-seo-markdown-fix-003', # New ID for new test
        'title': "OpenAI Announces GPT-4.5 Turbo with Enhanced Vision Capabilities",
        'content_for_processing': """
OpenAI today revealed GPT-4.5 Turbo, an incremental but significant update to its flagship large language model.
The new version boasts enhanced multimodal capabilities, particularly in image understanding and generation, and claims a 20% speed improvement for text-based tasks.
According to OpenAI's technical blog post, GPT-4.5 Turbo can now analyze complex charts, diagrams, and even hand-written notes with greater accuracy.
It also introduces more nuanced control over image generation through its DALL-E integration, allowing users to specify artistic styles and compositions with more precision.
The model's context window remains at 128k tokens, but OpenAI states that its ability to recall information across long contexts has been improved.
CEO Sam Altman commented, "GPT-4.5 Turbo is another step towards more helpful and intuitive AI. We're particularly excited about the advancements in visual understanding."
The API for GPT-4.5 Turbo is available to Plus and Enterprise users starting today, with wider availability and potential free-tier access expected in the coming weeks.
Pricing for the new model is reportedly similar to GPT-4 Turbo.
Early developer feedback has been largely positive, praising the improved vision features.
However, some users noted that the text generation quality, while fast, doesn't feel like a massive leap over the previous GPT-4 Turbo version for purely textual tasks.
OpenAI also emphasized ongoing safety work, with new mitigations for potential misuse of the enhanced vision capabilities.
The company will be hosting a developer livestream next week to showcase specific use-cases and answer questions.
This update positions OpenAI strongly against competitors like Google's Gemini and Anthropic's Claude 3 series.
""",
        'link': "https://www.example-ai-news.com/openai-gpt-4-5-turbo-vision",
        'selected_image_url': "https://www.example-ai-news.com/images/gpt45-turbo.jpg",
        'published_iso': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'author': "AI Insights Today",
        'filter_verdict': {'primary_topic_keyword': "GPT-4.5 Turbo Vision"},
        'researched_keywords': [
            "GPT-4.5 Turbo Vision", "OpenAI new model", "AI image understanding", "DALL-E integration",
            "multimodal AI", "Sam Altman OpenAI", "AI context window", "GPT-4.5 API", "AI safety vision models"
        ]
    }

    logger.info("\n--- Running FINAL CORRECTED SEO Article Agent Standalone Test (Markdown Body Focus) ---")
    result_article = run_seo_article_agent(test_article.copy())

    if result_article.get('seo_agent_results'):
        print("\n\n--- Generated SEO Content (FINAL CORRECTED - Markdown Body) ---")
        print(f"Title Tag: {result_article['seo_agent_results'].get('generated_title_tag')}")
        print(f"Meta Description: {result_article['seo_agent_results'].get('generated_meta_description')}")
        print(f"SEO H1 (Preamble): {result_article['seo_agent_results'].get('generated_seo_h1')}")
        print(f"Final Article Title in data: {result_article.get('title')}")

        md_body = result_article['seo_agent_results'].get('generated_article_body_md', '')
        print(f"\n--- Article Body (Should be Markdown, with HTML for Pros/Cons or FAQ if generated) ---")
        print(md_body)

        # Test if the body *looks* like Markdown and not escaped HTML
        if "<p>" not in md_body.split("</details>", 1)[0] and \
           "<h2>" not in md_body.split("</details>", 1)[0] and \
           md_body.strip().startswith("##") and \
           ("Pros & Cons" not in md_body or "<div class=\"pros-cons-container\">" in md_body) and \
           ("Frequently Asked Questions" not in md_body or "<div class=\"faq-section\">" in md_body):
            print("\nSUCCESS: Main body appears to be Markdown. Specific HTML snippets for Pros/Cons or FAQ are correctly present if those sections were generated.")
        else:
            print("\nWARNING: Main body might still contain unwanted HTML tags or not start with ##, or HTML snippets are missing when expected. Review output carefully.")
            # Check first part of body, before any FAQ/ProsCons HTML, for <p> or <h2>
            main_body_part_for_check = md_body
            if "<div class=\"faq-section\">" in main_body_part_for_check:
                main_body_part_for_check = main_body_part_for_check.split("<div class=\"faq-section\">", 1)[0]
            if "<div class=\"pros-cons-container\">" in main_body_part_for_check:
                main_body_part_for_check = main_body_part_for_check.split("<div class=\"pros-cons-container\">", 1)[0]

            if "<p>" in main_body_part_for_check: print("   - Found '<p>' tag in main body part.")
            if "<h2>" in main_body_part_for_check: print("   - Found '<h2>' tag in main body part.")
            if "<h3>" in main_body_part_for_check and not main_body_part_for_check.strip().startswith("###"): print("   - Found '<h3>' tag in main body part (and not as Markdown).") # Check for H3 too
            if not md_body.strip().startswith("##"): print("   - Body does not start with Markdown H1 '##'.")
            if "Pros & Cons" in md_body and "<div class=\"pros-cons-container\">" not in md_body: print("   - 'Pros & Cons' heading present, but HTML snippet missing.")
            if "Frequently Asked Questions" in md_body and "<div class=\"faq-section\">" not in md_body: print("   - 'Frequently Asked Questions' heading present, but HTML snippet missing.")


        if "<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->" in md_body:
            print("SUCCESS: In-article ad placeholder '<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->' found in MD body.")
        else:
            print("WARNING: In-article ad placeholder '<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->' NOT found in MD body.")

        json_ld_script_tag = result_article['seo_agent_results'].get('generated_json_ld_full_script_tag', '')
        print(f"\n--- JSON-LD Script ---")
        print(json_ld_script_tag)
        if "{MY_CANONICAL_URL_PLACEHOLDER}" in json_ld_script_tag:
            print("SUCCESS: '{MY_CANONICAL_URL_PLACEHOLDER}' (or its resolved form with {SLUG_PLACEHOLDER}) found in JSON-LD.")
        else:
            logger.warning("'{MY_CANONICAL_URL_PLACEHOLDER}' NOT found in JSON-LD, this might be an issue or it was correctly replaced if this is not the first run with this logic.")


        if result_article.get('seo_agent_error'):
            print(f"\nParsing/Validation Warnings/Errors: {result_article['seo_agent_error']}")
    else:
        print("\n--- SEO Agent FAILED ---")
        print(f"Error: {result_article.get('seo_agent_error')}")
        if result_article.get('seo_agent_raw_response_on_parse_fail'):
            print(f"\n--- Raw Response on Parse Failure (first 500 chars) ---")
            print(result_article['seo_agent_raw_response_on_parse_fail'][:500] + "...")

    logger.info("\n--- FINAL CORRECTED SEO Article Agent Standalone Test Complete ---")