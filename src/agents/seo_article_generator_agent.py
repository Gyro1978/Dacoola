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
BASE_URL_FOR_CANONICAL = os.getenv('YOUR_SITE_BASE_URL', 'https://your-site-url.com') # For constructing canonical URL

# --- Configuration ---
AGENT_MODEL = "deepseek-chat"
MAX_TOKENS_RESPONSE = 7500 # Increased slightly for potentially more verbose structured output
TEMPERATURE = 0.65 # Slightly adjusted for balance between creativity and factuality
API_TIMEOUT_SECONDS = 400 # Increased

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
9.  **Initial Summary:** 1-2 concise lead paragraphs (approx. 50-100 words total) summarizing the core news from the source. Include `{{TARGET_KEYWORD}}` within the first paragraph naturally.
10. **In-Depth Analysis:** Expand on the summary with context, implications, and background using logical Markdown headings (`### H3`, `#### H4`).
    *   **Main Analysis Section (using `### H3`):** Create *one* clear, descriptive H3 title (e.g., "### Key Innovations and Market Impact"). Follow with 2-4 paragraphs of core analysis and discussion.
    *   **Thematic Sub-sections (using `#### H4`):** Under the H3, use 1-3 descriptive H4 titles for distinct sub-topics if the content supports them (e.g., "#### Technical Breakdown," "#### Ethical Considerations"). Each H4 section should have 1-2 paragraphs. **Omit H4 sections entirely if not relevant or sufficiently supported by the `{{ARTICLE_CONTENT_FOR_PROCESSING}}`.**
11. **Pros & Cons (using `#### Pros & Cons`):**
    *   Generate this section **ONLY IF** the `{{ARTICLE_CONTENT_FOR_PROCESSING}}` clearly presents distinct advantages and disadvantages or contrasting viewpoints that can be summarized as such. **Omit entirely otherwise.**
    *   If included, use the **exact** H4 title: `#### Pros & Cons`. Use the specified HTML structure for the list items.
11.b. **In-Article Ad Placeholder:** After the first 2 or 3 paragraphs of the main article body (typically after the initial summary paragraphs and before any `### H3` subheading), insert the exact HTML comment: `<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->`. Insert this placeholder **only ONCE**.
12. **FAQ (using `#### Frequently Asked Questions`):**
    *   Generate this section **ONLY IF** the topic naturally warrants a Q&A format to clarify common questions or complex points from `{{ARTICLE_CONTENT_FOR_PROCESSING}}`. **Omit entirely otherwise.**
    *   If included, use the **exact** H4 title: `#### Frequently Asked Questions`. Generate 2-4 relevant Q&As. Use the specified HTML structure.
13. **Overall Length & Tone:** Aim for approximately **500-800 words** for the main article body (excluding JSON-LD, etc.). Maintain an authoritative, objective, yet engaging and accessible journalistic tone.

**IV. Writing Style & Avoiding "AI Tells":**
14. **Direct & Concise:** Use clear, straightforward language. Avoid jargon where simpler terms suffice.
15. **Varied Sentence Structure:** Mix short, impactful sentences with more complex ones. Avoid repetitive sentence beginnings.
16. **Active Voice:** Prefer active voice over passive voice for stronger impact.
17. **No Redundancy:** Ensure each sentence and paragraph adds new value.
18. **Specific Language:** Use precise verbs and nouns. Avoid vague words like "things," "stuff," "many," "various."
19. **Human-like Flow:** Read the article aloud to ensure it sounds natural and engaging. Use standard hyphens (-) instead of em dashes (—).

**V. Output Formatting (Strict Adherence Mandatory):**
20. **Markdown & HTML:** The main article body MUST be in Markdown. The Pros/Cons and FAQ sections, if included, MUST use the **exact HTML structure** specified in the user prompt's output format example. The In-Article Ad Placeholder is an HTML comment.
21. **Exact Output Order:** Your entire response MUST follow this order:
    Title Tag: [Generated Title Tag]
    Meta Description: [Generated Meta Description]
    SEO H1: [Generated SEO H1]

    ## [SEO H1 from above, verbatim]
    {Markdown Article Body including optional HTML sections like Pros/Cons, FAQ, and the ad placeholder}
    Source: [{ARTICLE_TITLE_FROM_SOURCE}]({SOURCE_ARTICLE_URL})

    <script type="application/ld+json">
    {{JSON-LD content as specified}}
    </script>
22. **Title Tag:** Output as `Title Tag: [Generated text]`. Max length: ~60 characters. Must include `{{TARGET_KEYWORD}}`. **MUST use Title Case.** Should closely match or be a condensed version of the SEO H1.
23. **Meta Description:** Output as `Meta Description: [Generated text]`. Max length: ~160 characters. Must include `{{TARGET_KEYWORD}}` and be engaging.
24. **SEO H1 (in preamble):** Output as `SEO H1: [Generated text]`. This must be identical to the H1 used in the `## [SEO H1]` line in the article body. **MUST use Title Case.**
25. **JSON-LD Script:** Populate the `NewsArticle` schema accurately. `keywords` field should use the content of `{{ALL_GENERATED_KEYWORDS_JSON}}`. `headline` field must match the generated SEO H1. The `mainEntityOfPage.@id` should use `{{MY_CANONICAL_URL_PLACEHOLDER}}`.

**VI. Error Handling:** If you cannot fulfill a part of the request due to limitations or unclear input, note it briefly in a comment within the generated text if absolutely necessary, but prioritize completing the rest of the structure.
**VII. Final Check:** Before outputting, mentally review all instructions. Ensure every constraint is met.
"""

SEO_PROMPT_USER_TEMPLATE = """
Task: Generate the Title Tag, Meta Description, SEO-Optimized H1 Heading, Article Body (in Markdown, including the `<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->` placeholder and optional HTML sections like Pros/Cons and FAQ as per system instructions), and JSON-LD Script based on the provided context. Follow ALL System Prompt directives meticulously.

**Key Focus for this Task:**
1.  **Title & H1 Generation:** Create a **catchy, SEO-friendly Title Tag and H1 in Title Case**. Ensure they prominently feature the main subject/product from the content AND the `{{TARGET_KEYWORD}}`. The H1 should be engaging and suitable for a news headline.
2.  **Content Structure:** Adhere to the specified structure. The `<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->` placeholder is mandatory. Omit optional sections (H4s beyond the main analysis H3, Pros/Cons, FAQ) if `{{ARTICLE_CONTENT_FOR_PROCESSING}}` doesn't clearly and robustly support them.
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

**Required Output Format (Strict Adherence):**
Title Tag: [Generated catchy Title Tag in Title Case, approx. 50-60 chars. Must include TARGET_KEYWORD and ideally main product/subject name.]
Meta Description: [Generated meta description, approx. 150-160 chars. Must include TARGET_KEYWORD. Make it compelling.]
SEO H1: [Generated catchy, SEO-Optimized H1 in Title Case. Must include TARGET_KEYWORD and ideally main product/subject name. Reflects core news.]

## [SEO H1 from above, verbatim. This is the main article title.]
[Paragraph 1-2: CONCISE summary (approx. 50-100 words). Include TARGET_KEYWORD naturally. Journalistic tone. Standard hyphens ONLY.]

<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->

### [Contextual H3 Title for Main Analysis - be descriptive, this comes after the ad placeholder]
[Paragraphs 2-4+: In-depth analysis. Weave in TARGET_KEYWORD again if natural, + 1-2 SECONDARY_KEYWORDS if provided and they fit organically. Vary sentence structures and vocabulary. AVOID AI clichés and em dashes.]

#### [Optional H4 Title - OMIT IF NOT RELEVANT OR IF CONTENT DOESN'T SUPPORT A DISTINCT SUB-SECTION]
[Optional: 1-2 paragraphs. OMIT ENTIRE H4 SECTION if not applicable or if content is thin.]

#### [Optional: Pros & Cons - OMIT IF NOT APPLICABLE OR IF CONTENT ISN'T SUITABLE FOR THIS FORMAT]
[If included, use exact H4 title: "Pros & Cons". Items MUST be HTML `<li>` containing ONLY descriptive text. Internal `<strong>` or `<em>` tags for emphasis within `<li>` are okay. NO titles/prefixes/surrounding `**` inside `<li>`. NO markdown lists inside `<li>`.]
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

#### [Optional H4 Title - OMIT IF NOT RELEVANT]
[Optional: 1-2 paragraphs. OMIT ENTIRE H4 SECTION if not applicable.]

#### [Optional: Frequently Asked Questions - OMIT IF NOT APPLICABLE OR IF CONTENT ISN'T SUITABLE]
[If included, use exact H4 title: "Frequently Asked Questions". Generate 2-4 relevant Q&As. Use exact HTML structure with `<i class="faq-icon fas fa-chevron-down"></i>`.]
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
        logger.debug(f"Sending SEO generation request (model: {AGENT_MODEL}). Est. User Prompt Tokens: ~{len(user_prompt)//3}") # Rough estimate
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
                # Remove potential leading/trailing backticks and language hint (e.g., ```markdown ... ```)
                if content_stripped.startswith("```") and content_stripped.endswith("```"):
                    first_newline = content_stripped.find('\n')
                    content_stripped = content_stripped[first_newline+1:-3].strip() if first_newline != -1 else content_stripped[3:-3].strip()
                content_stripped = content_stripped.replace('—', '-') # Replace em-dashes with standard hyphens
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
        # Extract Title Tag
        title_match = re.search(r"^\s*Title Tag:\s*(.*)", response_text, re.MULTILINE | re.IGNORECASE)
        if title_match:
            parsed_data['generated_title_tag'] = title_match.group(1).strip()
        else:
            errors.append("Missing 'Title Tag:' line.")

        # Extract Meta Description
        meta_match = re.search(r"^\s*Meta Description:\s*(.*)", response_text, re.MULTILINE | re.IGNORECASE)
        if meta_match:
            parsed_data['generated_meta_description'] = meta_match.group(1).strip()
        else:
            errors.append("Missing 'Meta Description:' line.")

        # Extract SEO H1 from preamble
        seo_h1_preamble_match = re.search(r"^\s*SEO H1:\s*(.*)", response_text, re.MULTILINE | re.IGNORECASE)
        if seo_h1_preamble_match:
            parsed_data['generated_seo_h1'] = seo_h1_preamble_match.group(1).strip()
        else:
            errors.append("Missing 'SEO H1:' line in preamble.")

        # Extract JSON-LD script block
        script_match = re.search(
            r'<script\s+type\s*=\s*["\']application/ld\+json["\']\s*>\s*(\{[\s\S]*?\})\s*<\/script>',
            response_text, re.IGNORECASE
        )
        if script_match:
            json_content_str = script_match.group(1).strip()
            parsed_data['generated_json_ld_raw'] = json_content_str # Store raw for potential later replacement
            parsed_data['generated_json_ld_full_script_tag'] = script_match.group(0).strip()
            try:
                json.loads(json_content_str.replace("{MY_CANONICAL_URL_PLACEHOLDER}", "https://example.com/placeholder-for-validation")) # Validate with a dummy
            except json.JSONDecodeError as json_err:
                errors.append(f"JSON-LD content is invalid: {json_err}")
                logger.warning(f"Invalid JSON-LD detected (raw content): {json_content_str[:200]}...")
        else:
            errors.append("Missing or malformed JSON-LD script block.")

        # Extract Article Body (between SEO H1 preamble and Source line or JSON-LD script)
        body_content = None
        # Define the end delimiters for the article body
        end_delimiters_pattern = r"(?=\n\s*Source:|\n\s*<script\s+type\s*=\s*[\"']application/ld\+json[\"'])"

        # Try to find the start of the body after the "SEO H1: ..." preamble line
        if seo_h1_preamble_match:
            body_start_offset = seo_h1_preamble_match.end()
            # Search for the "## Actual H1 Text" pattern that should follow immediately after the preamble
            actual_h1_body_match = re.match(r"\s*\n\s*(## .*?)", response_text[body_start_offset:], re.DOTALL | re.IGNORECASE)
            if actual_h1_body_match:
                body_search_text = actual_h1_body_match.group(1) # This is the "## Actual H1..."
                # Find the end of this body content
                end_match = re.search(end_delimiters_pattern, response_text[body_start_offset + actual_h1_body_match.start(1):], re.MULTILINE | re.DOTALL | re.IGNORECASE)
                if end_match:
                    body_content = response_text[body_start_offset + actual_h1_body_match.start(1) : body_start_offset + actual_h1_body_match.start(1) + end_match.start()].strip()
                else:
                    # If no specific end delimiter, take everything from "## Actual H1..." to the end of response_text, then strip JSON-LD if it's at the very end
                    potential_body_end = response_text[body_start_offset + actual_h1_body_match.start(1):].strip()
                    if parsed_data.get('generated_json_ld_full_script_tag') and potential_body_end.endswith(parsed_data['generated_json_ld_full_script_tag']):
                        body_content = potential_body_end[:-len(parsed_data['generated_json_ld_full_script_tag'])].strip()
                    else:
                        body_content = potential_body_end # May include source line if not properly delimited
                        if "\nSource:" in body_content: # Try to strip source line manually
                            body_content = body_content.split("\nSource:", 1)[0].strip()

                    if body_content:
                         logger.warning("Body extraction: No clear 'Source:' or '<script' delimiter found after H1 using regex. Relied on greedy match then strip.")
                    else:
                         errors.append("Body extraction: Could not find end delimiter and greedy match failed.")

            else:
                errors.append("Could not find '## H1 text' pattern starting the article body after 'SEO H1:' preamble.")
        else:
            errors.append("Could not find 'SEO H1:' preamble line, cannot reliably locate article body start.")


        if body_content and body_content.startswith("## "):
            parsed_data['generated_article_body_md'] = body_content
            body_h1_text_match = re.match(r"##\s*(.*)", body_content, re.IGNORECASE) # Get H1 text from body
            if body_h1_text_match:
                body_h1_text = body_h1_text_match.group(1).strip()
                if parsed_data.get('generated_seo_h1'):
                    if body_h1_text != parsed_data['generated_seo_h1']:
                        errors.append(f"H1 in body ('{body_h1_text}') mismatches preamble H1 ('{parsed_data.get('generated_seo_h1', '')}'). Using preamble H1.")
                else: # If preamble H1 was missing, use the one from the body
                    parsed_data['generated_seo_h1'] = body_h1_text
                    logger.info("Used H1 from article body as 'SEO H1:' preamble line was missing.")
            else:
                errors.append("Extracted body starts with '## ' but could not parse H1 text from it.")
        else:
            if not body_content: errors.append("Article Body content is empty after extraction attempts.")
            elif body_content is not None and not body_content.startswith("## "): errors.append(f"Extracted Body does not start with '## '. Actual start: '{body_content[:50]}...'")
            parsed_data['generated_article_body_md'] = "" # Ensure it's set, even if empty

        # Fallbacks for critical missing fields
        if not parsed_data.get('generated_seo_h1'):
            errors.append("CRITICAL: SEO H1 could not be determined.")
            parsed_data['generated_seo_h1'] = "Error: H1 Missing" # Placeholder
        if not parsed_data.get('generated_title_tag'):
            parsed_data['generated_title_tag'] = parsed_data.get('generated_seo_h1', 'Error: Title Missing')
            if 'Error: H1 Missing' not in parsed_data['generated_title_tag'] and 'Error: Title Missing' not in parsed_data['generated_title_tag']:
                 errors.append("Defaulted Title Tag to SEO H1.")
        if not parsed_data.get('generated_meta_description'):
            parsed_data['generated_meta_description'] = "Read the latest AI and Technology news from " + YOUR_WEBSITE_NAME
            errors.append("Defaulted Meta Description.")
        if not parsed_data.get('generated_json_ld_raw'): # Check for raw JSON content
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
    article_data['primary_keyword'] = primary_keyword # Ensure it's set in article_data for consistency

    generated_tags = article_data.get('researched_keywords', [])
    if not generated_tags and primary_keyword:
        generated_tags = [primary_keyword]
    secondary_keywords = [tag for tag in generated_tags if tag.lower() != primary_keyword.lower()][:3] # Max 3 secondary
    secondary_keywords_list_str = ", ".join(secondary_keywords)

    # Ensure all keywords for JSON-LD are valid strings and unique
    all_valid_keywords_for_json_ld = list(set([str(k).strip() for k in generated_tags if k and str(k).strip()]))
    all_generated_keywords_json = json.dumps(all_valid_keywords_for_json_ld)


    # Placeholder for canonical URL - actual value to be filled by main.py/gyro-picks.py
    # The slug will be derived from the generated H1 later.
    my_canonical_url_placeholder_value = f"{BASE_URL_FOR_CANONICAL.rstrip('/')}/articles/{{SLUG_PLACEHOLDER}}"


    input_data_for_prompt = {
        "article_title_from_source": article_data.get('title', 'Untitled Article'),
        "article_content_for_processing": content_to_process,
        "source_article_url": article_data.get('link', '#'),
        "target_keyword": primary_keyword,
        "secondary_keywords_list_str": secondary_keywords_list_str,
        "article_image_url": article_data.get('selected_image_url', ''),
        "author_name": article_data.get('author', YOUR_WEBSITE_NAME), # Default to site name if no author
        "current_date_iso": article_data.get('published_iso') or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "your_website_name": YOUR_WEBSITE_NAME,
        "your_website_logo_url": YOUR_WEBSITE_LOGO_URL,
        "all_generated_keywords_json": all_generated_keywords_json,
        "my_canonical_url_placeholder": my_canonical_url_placeholder_value
    }

    # Ensure no None values are passed into the prompt template format method
    for key, value in input_data_for_prompt.items():
        if value is None:
            logger.warning(f"Input field '{key}' for SEO prompt is None for article {article_id}. Replacing with empty string or default.")
            input_data_for_prompt[key] = '' # Default to empty string

    try:
        # Substitute YOUR_WEBSITE_NAME in the system prompt.
        # The other placeholders in system prompt like {{TARGET_KEYWORD}} are illustrative for the LLM, not for Python's .format()
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

    article_data['seo_agent_results'] = parsed_results # Store even if partially parsed or with errors
    article_data['seo_agent_error'] = error_msg # Store any parsing errors/warnings

    if parsed_results is None:
        logger.error(f"Completely FAILED to parse SEO agent response for {article_id}: {error_msg}")
        # Store raw response if parsing utterly fails, for debugging
        article_data['seo_agent_raw_response_on_parse_fail'] = raw_response_content
    elif error_msg: # Parsed but with non-critical issues
        logger.warning(f"SEO parsing for {article_id} completed with non-critical errors/warnings: {error_msg}")
    else: # Successful parse
        logger.info(f"Successfully generated and parsed SEO content for {article_id}.")

    # Update the main article title with the generated SEO H1 if available and different
    if parsed_results and parsed_results.get('generated_seo_h1') and "Error: H1 Missing" not in parsed_results['generated_seo_h1']:
        new_title = parsed_results['generated_seo_h1']
        if article_data.get('title') != new_title:
            logger.info(f"Updating article title for {article_id} with generated SEO H1: '{new_title}' (was: '{article_data.get('title')}')")
            article_data['title'] = new_title
    elif not article_data.get('title'): # Fallback if title was somehow lost
        article_data['title'] = "Untitled Article - SEO Processing Error"

    return article_data

# --- Standalone Execution (for testing) ---
if __name__ == "__main__":
    logging.getLogger().setLevel(logging.DEBUG) # Show debug messages for testing
    logger.setLevel(logging.DEBUG)

    if not DEEPSEEK_API_KEY:
        logger.error("CRITICAL FOR STANDALONE TEST: DEEPSEEK_API_KEY env var not set.")
        sys.exit(1)
    if not YOUR_WEBSITE_LOGO_URL:
        logger.warning("YOUR_WEBSITE_LOGO_URL is not set in .env, JSON-LD publisher logo will be empty in test.")
    if not BASE_URL_FOR_CANONICAL or BASE_URL_FOR_CANONICAL == 'https://your-site-url.com':
        logger.warning("YOUR_SITE_BASE_URL is not set or is default in .env, canonical URL placeholder will use default.")

    test_article = {
        'id': 'test-seo-perfected-001',
        'title': "Nvidia's Next-Gen AI Chip 'Zeus' Promises 10x Performance Leap",
        'content_for_processing': """
Nvidia CEO Jensen Huang today unveiled the company's latest AI superchip, codenamed 'Zeus' (officially the Z200 series), at their annual GTC conference.
Huang claimed Zeus offers a staggering tenfold improvement in performance for large language model training and inference compared to the current Hopper H100/H200 generation.
The new architecture features a chiplet design with HBM4 memory, significantly increasing bandwidth and on-chip memory capacity.
Early benchmarks showcased Zeus outperforming competitors by a wide margin on several key AI workloads.
Huang emphasized that Zeus is not just a chip but an entire platform, including new NVLink interconnects, updated CUDA libraries, and a suite of pre-trained models optimized for the hardware.
"Zeus will power the next wave of generative AI, enabling models of unprecedented scale and capability," Huang stated.
Availability is slated for Q1 2025, with major cloud providers and server manufacturers already lining up.
However, the new chips are expected to come with a premium price tag, and questions remain about power consumption and cooling requirements for these dense systems.
Some analysts also point out that real-world performance gains may vary depending on the specific application and software optimization.
The announcement also included brief mentions of Nvidia's efforts in autonomous vehicles and robotics, suggesting Zeus will also play a role in those sectors.
The conference attendees reacted with significant enthusiasm to the unveiling.
""",
        'link': "https://www.example-tech-news.com/nvidia-zeus-z200-unveiled",
        'selected_image_url': "https://www.example-tech-news.com/images/nvidia-zeus-chip.jpg",
        'published_iso': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'author': "Tech Reporter Pro",
        'filter_verdict': {'primary_topic_keyword': "Nvidia Zeus AI Chip"},
        'researched_keywords': [
            "Nvidia Zeus AI Chip", "Nvidia Z200 series", "next-gen AI hardware", "AI superchip",
            "GTC conference Nvidia", "Jensen Huang announcement", "HBM4 memory AI",
            "AI model training performance", "Nvidia generative AI platform"
        ]
    }

    logger.info("\n--- Running PERFECTED SEO Article Agent Standalone Test ---")
    result_article = run_seo_article_agent(test_article.copy())

    if result_article.get('seo_agent_results'):
        print("\n\n--- Generated SEO Content (PERFECTED) ---")
        print(f"Title Tag: {result_article['seo_agent_results'].get('generated_title_tag')}")
        print(f"Meta Description: {result_article['seo_agent_results'].get('generated_meta_description')}")
        print(f"SEO H1 (Preamble): {result_article['seo_agent_results'].get('generated_seo_h1')}")
        print(f"Final Article Title in data: {result_article.get('title')}")

        md_body = result_article['seo_agent_results'].get('generated_article_body_md', '')
        print(f"\n--- Article Body (Markdown) ---")
        print(md_body)

        if "<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->" in md_body:
            print("\nSUCCESS: In-article ad placeholder '<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->' found in MD body.")
        else:
            print("\nWARNING: In-article ad placeholder '<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->' NOT found in MD body.")

        json_ld_script_tag = result_article['seo_agent_results'].get('generated_json_ld_full_script_tag', '')
        print(f"\n--- JSON-LD Script ---")
        print(json_ld_script_tag)
        if "{MY_CANONICAL_URL_PLACEHOLDER}" in json_ld_script_tag:
            print("\nSUCCESS: '{MY_CANONICAL_URL_PLACEHOLDER}' found in JSON-LD.")
        else:
            print("\nWARNING: '{MY_CANONICAL_URL_PLACEHOLDER}' NOT found in JSON-LD.")


        if result_article.get('seo_agent_error'):
            print(f"\nParsing/Validation Warnings/Errors: {result_article['seo_agent_error']}")
    else:
        print("\n--- SEO Agent FAILED ---")
        print(f"Error: {result_article.get('seo_agent_error')}")
        if result_article.get('seo_agent_raw_response_on_parse_fail'):
            print(f"\n--- Raw Response on Parse Failure (first 500 chars) ---")
            print(result_article['seo_agent_raw_response_on_parse_fail'][:500] + "...")

    logger.info("\n--- PERFECTED SEO Article Agent Standalone Test Complete ---")