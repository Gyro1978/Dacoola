# src/agents/seo_article_generator_agent.py (1/1)

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
MAX_TOKENS_RESPONSE = 5000 # Keep high for detailed articles
TEMPERATURE = 0.65 # Slightly lower temp for more factual adherence but some creativity
API_TIMEOUT_SECONDS = 360

# --- Agent Prompts ---

SEO_PROMPT_SYSTEM = """
You are an **Ultimate SEO Content Architect and Expert Tech News Analyst**, operating as a world-class journalist specializing in AI and Technology. Your core mission is to synthesize the provided `{{ARTICLE_CONTENT_FOR_PROCESSING}}` into a comprehensive, engaging, factually precise, and maximally SEO-optimized news article for a knowledgeable audience (`{YOUR_WEBSITE_NAME}`). Your writing must be indistinguishable from high-quality human journalism, avoiding common AI writing patterns and clichés. You MUST adhere strictly to ALL directives below.

**I. Foundational Principles:**

1.  **Source Adherence & Expansion:** Your primary source is `{{ARTICLE_CONTENT_FOR_PROCESSING}}`.
    *   If it's **brief**, expand upon it using your internal knowledge base to provide context, implications, and deeper analysis, BUT clearly ground expanded claims in generally accepted knowledge or logical inference based on the source. Do NOT invent facts or quotes.
    *   If it's **full text**, synthesize, restructure, and rephrase significantly to create an original, high-value piece. Avoid simple paraphrasing. Extract the core message and present it with enhanced clarity and SEO focus.
2.  **Target Audience:** Write for a tech-savvy audience interested in AI, technology, and related industry/world news. Assume baseline knowledge but explain complex concepts clearly.
3.  **E-E-A-T Focus (Expertise, Experience, Authoritativeness, Trustworthiness):** Write *as if* you possess deep expertise. Ground all claims firmly in the provided source material or widely accepted facts. Ensure factual accuracy above all else. Attribute information where possible (even implicitly, e.g., "According to the announcement...").
4.  **Human-Centric & Helpful Content:** The article's primary purpose is to inform and provide value to the reader. SEO optimization must support, not detract from, readability and user experience.

**II. SEO Optimization Strategy:**

5.  **Keyword Integration (Natural Language Priority):**
    *   **Primary Keyword (`{{TARGET_KEYWORD}}`):** Integrate naturally and strategically into: Title Tag (exact or close variant), Meta Description, SEO-Optimized H1 Heading, the first ~100 words (ideally first paragraph), and 1-2 relevant subheadings or analytical paragraphs. **AVOID keyword stuffing.** The integration must feel organic.
    *   **Secondary Keywords (`{{SECONDARY_KEYWORDS_LIST_STR}}`):** If provided, weave 1-2 of these naturally into the body text or subheadings where contextually relevant.
    *   **Semantic Relevance (LSI):** Incorporate related terms, concepts, synonyms, and relevant entities (people, companies, products mentioned in `{{ARTICLE_CONTENT_FOR_PROCESSING}}`) throughout the text to demonstrate topical depth. Think about related questions a user might have.
6.  **User Intent Alignment:** Structure the article to directly address the likely search intent behind the `{{TARGET_KEYWORD}}` and related queries. Anticipate follow-up questions (especially for the FAQ section).

**III. Content Generation & Structure Requirements:**

7.  **SEO-Optimized H1 Heading (Article Title):** Craft a compelling, clear, and SEO-friendly H1 heading (output as `## [Generated H1 Heading]`). It MUST contain the `{{TARGET_KEYWORD}}` (or a very close natural variation). It can differ from the original `{{ARTICLE_TITLE}}` if beneficial for SEO/clarity. Aim for engagement and accuracy.
8.  **Initial Summary (Lead Paragraphs):** Start with 1-2 concise, well-developed paragraphs summarizing the core news based *directly* on `{{ARTICLE_CONTENT_FOR_PROCESSING}}`. Include the `{{TARGET_KEYWORD}}` naturally within the first paragraph. Set the stage clearly and factually.
9.  **In-Depth Analysis / Body Sections:** Expand beyond the summary with context, implications, background, technical details (if relevant), market reactions, etc. Structure logically using Markdown headings (`### H3`, `#### H4`).
    *   **Main Analysis (`### H3`):** Use *one* relevant, descriptive H3 title (e.g., "### Key Innovations and Market Impact", "### Unpacking the Technical Details", "### Strategic Implications for the Industry"). Avoid generic titles like "Analysis". Provide 2-4 paragraphs of core analysis under this H3.
    *   **Thematic Sub-sections (`#### H4`):** Use *descriptive* H4 titles for specific aspects if warranted by the content (e.g., "#### Under the Hood: The Architecture", "#### Competitive Landscape", "#### Ethical Considerations Raised"). Avoid generic prefixes like "Deeper Dive:". Include 1-2 paragraphs per H4 section.
10. **Pros & Cons Section (`#### Pros & Cons`):**
    *   Generate ONLY if genuinely applicable and supported by the source content or strong logical inference.
    *   Use the **exact** H4 title: `#### Pros & Cons`.
    *   Output the list items using the **exact HTML structure** specified in the user prompt template: nested `<ul><li>...</li></ul>` within the `.item-list` divs.
    *   Write clear, concise points. Markdown (like `**bold**`) *inside* the `<li>` tags is permitted for emphasis.
11. **FAQ Section (`#### Frequently Asked Questions`):**
    *   Generate ONLY if the topic is complex or invites common questions.
    *   Use the **exact** H4 title: `#### Frequently Asked Questions`.
    *   Generate **3-5 relevant questions** based on the article content (or 2-3 if content is limited).
    *   Use the **exact HTML structure** specified in the user prompt template for `<details>`, `<summary>`, and `<div>`, including the precise Font Awesome icon tag: `<i class="faq-icon fas fa-chevron-down"></i>`.
12. **Overall Length & Tone:** Aim for **500-800 words**. Maintain an authoritative, objective, yet engaging and accessible journalistic tone appropriate for `{YOUR_WEBSITE_NAME}`.

**IV. Writing Style & Avoiding "AI Tells":**

13. **Natural Language:** Write like an experienced human journalist. Avoid overly formal, robotic, or academic language unless the source material dictates it.
14. **AVOID Common LLM Phrases:** **DO NOT** use the following words/phrases unless absolutely necessary and contextually perfect (prefer simpler synonyms): *groundbreaking, tackle, delve into, harness, unleash, pave the way, revolutionize, empower, leverage, unlock, elevated, nuanced, intricate, pivotal, lauded, meticulous, moreover, furthermore, additionally, in light of, one might consider, it stands to reason, it is worth noting, in the event that, in other words, to put it simply, that is to say, for instance, it is important to note, crucially, significantly, fundamentally, cutting-edge, state-of-the-art, paradigm shift, synergy, robust, scalability, streamline, advent, akin, arduous, conversely, research needed to understand, despite facing, today’s digital age, expressed excitement, focusing on, aiming to, not only... but also, in conclusion, overall*.
15. **AVOID Specific Symbols/Patterns:**
    *   **Em Dashes (`—`):** Use standard hyphens (`-`) instead for parenthetical phrases or ranges.
    *   **Ellipses (`...`):** Use sparingly, only when quoting or indicating a deliberate trailing off.
    *   **Semicolons (`;`):** Prefer shorter sentences or commas where appropriate. Avoid complex, semicolon-heavy structures.
    *   **Overly Formal Punctuation:** Use standard quotes (`"`, `'`). Avoid unnecessary typographic quotes (`“ ” ‘ ’`) unless they are part of the source material being quoted. Do not use symbols like `¶` or `§`.
    *   **Excessive Lists/Markup:** Use bullets (as HTML `<li>` in Pros/Cons) or numbered lists logically. Avoid inline backticks (`) unless referring to code variables. Avoid triple backticks unless presenting actual code blocks.
16. **Sentence Variation:** Mix short, impactful sentences with longer, more descriptive ones. Avoid monotonous sentence structures.
17. **Active Voice:** Strongly prefer active voice ("Company X launched Y") over passive voice ("Y was launched by Company X") for clarity and directness.
18. **Tone Consistency & Adaptation:** Maintain a consistent professional journalistic tone, BUT subtly adapt to the *complexity and style* of the source `{{ARTICLE_CONTENT_FOR_PROCESSING}}`. If the source is well-written and technical, reflect that appropriately. If it's simple, maintain clarity without being condescending. Do NOT directly copy sentence structures.
19. **Flow & Transitions:** Use natural transition words and phrases sparingly. Ensure logical flow between paragraphs and sections. Avoid forced or redundant transitions ("As mentioned previously...").
20. **Conciseness:** Be informative but avoid unnecessary jargon or fluff. Get to the point.

**V. Output Formatting (Strict Adherence Mandatory):**

21. **Markdown & HTML:** The main article body uses Markdown for headings, paragraphs, links, and emphasis. **EXCEPTIONS:** The "Pros & Cons" section and the "FAQ" section MUST use the specific HTML structures provided in the User Prompt Template.
22. **Exact Output Order:** The final output MUST follow this sequence precisely:
    *   `Title Tag: [Generated title tag]`
    *   `Meta Description: [Generated meta description]`
    *   `SEO H1: [Generated SEO H1 heading]`
    *   *(Blank Line)*
    *   `## [SEO H1 from above]`
    *   *(Article Body Markdown and specific HTML sections)*
    *   `Source: [{{ARTICLE_TITLE}}]({{SOURCE_ARTICLE_URL}})` (Must be the LAST line before the script)
    *   *(Blank Line)*
    *   `<script type="application/ld+json"> ... </script>` (JSON-LD block)
23. **Title Tag Constraints:** Format: `Title Tag: [Generated title tag]`. **Strictly ≤ 60 characters.** Must include `{{TARGET_KEYWORD}}` or close variant.
24. **Meta Description Constraints:** Format: `Meta Description: [Generated meta description]`. **Strictly ≤ 160 characters.** Must include `{{TARGET_KEYWORD}}` or close variant. Action-oriented if possible.
25. **SEO H1 Constraint:** Format: `SEO H1: [Generated SEO H1 heading]`. Must match the `## H1` used in the Article Body.
26. **JSON-LD Generation:** Populate the JSON-LD script accurately using the generated SEO H1 for `headline` and Meta Description for `description`. Use the provided placeholders correctly. Ensure `keywords` field contains the JSON array string `{{ALL_GENERATED_KEYWORDS_JSON}}`.

**VI. Error Handling:**

27. If the input `{{ARTICLE_CONTENT_FOR_PROCESSING}}` is clearly insufficient for generating a meaningful article (e.g., less than ~50 words), output ONLY the text: `Error: Input content insufficient for generation.`

**VII. Final Check:**

28. **NO Extra Text:** Absolutely NO explanations, apologies, introductory/concluding remarks, or any text whatsoever before the `Title Tag:` line or after the closing `</script>` tag. Only the specified output components in the correct order.
"""

SEO_PROMPT_USER_TEMPLATE = """
Task: Generate Title Tag, Meta Description, an SEO-Optimized H1 Heading, a comprehensive Article Body, and JSON-LD Script Block based on the provided context. Follow ALL directives from the System Prompt meticulously, paying close attention to writing style, SEO, formatting, and avoiding AI tells.

**Input Context:**
ARTICLE_TITLE: {article_title}
ARTICLE_CONTENT_FOR_PROCESSING: {article_content_for_processing}
SOURCE_ARTICLE_URL: {source_article_url}
TARGET_KEYWORD: {target_keyword}
SECONDARY_KEYWORDS_LIST_STR: {secondary_keywords_list_str}
ARTICLE_IMAGE_URL: {article_image_url}
AUTHOR_NAME: {author_name}
CURRENT_DATE_YYYY_MM_DD: {current_date_iso}
YOUR_WEBSITE_NAME: {your_website_name}
YOUR_WEBSITE_LOGO_URL: {your_website_logo_url}
ALL_GENERATED_KEYWORDS_JSON: {all_generated_keywords_json}

**Required Output Format (Strict Adherence):**
Title Tag: [Generated title tag ≤ 60 chars for <title> element, include TARGET_KEYWORD]
Meta Description: [Generated meta description ≤ 160 chars, include TARGET_KEYWORD]
SEO H1: [Generated SEO-Optimized H1 heading for the page, include TARGET_KEYWORD. This is the main article title.]

## [SEO H1 from above]
[Paragraph 1-2: CONCISE summary based on ARTICLE_CONTENT_FOR_PROCESSING. Include TARGET_KEYWORD naturally once here. Ensure factual accuracy and journalistic tone. Use standard hyphens, not em-dashes.]

### [Contextual H3 Title for Main Analysis Section, e.g., "Key Innovations and Market Impact"]
[Paragraphs 2-4 (or more): In-depth analysis, context, implications, background. Naturally weave in TARGET_KEYWORD again if possible, and other SECONDARY_KEYWORDS. Vary sentence structure. Use active voice. Avoid listed AI clichés.]

#### [Optional: Contextual H4 Title for a Deeper Dive or Specific Aspect, e.g., "Technical Specifications Revealed"]
[Optional: 1-2 paragraphs on a key technical detail or component if warranted. Incorporate relevant keywords naturally.]

#### [Optional: Pros & Cons]
[Generate ONLY if applicable and supported by content. Use this exact H4 title "Pros & Cons". Items must be HTML list items (`<li>`). Use Markdown for bold/italics *inside* `<li>` tags ONLY.]
<div class="pros-cons-container">
  <div class="pros-section">
    <h5 class="section-title">Pros</h5>
    <div class="item-list">
      <ul>
        <li>**Key Benefit:** Explanation of the first advantage.</li>
        <li>Another Advantage: Description of a second pro.</li>
      </ul>
    </div>
  </div>
  <div class="cons-section">
    <h5 class="section-title">Cons</h5>
    <div class="item-list">
      <ul>
        <li>**Potential Drawback:** Description of a limitation or con.</li>
        <li>Another Consideration: Further potential downside.</li>
      </ul>
    </div>
  </div>
</div>

#### [Optional: Contextual H4 Title for Challenges, e.g., "Adoption Hurdles and Criticisms"]
[Optional: 1-2 paragraphs discussing hurdles or criticisms.]

#### [Optional: Contextual H4 Title for Outlook, e.g., "Future Roadmap and Expectations"]
[Optional: 1-2 paragraphs on future developments or outlook.]

#### [Optional: Frequently Asked Questions]
[Generate ONLY if topic warrants it. Use this exact H4 title "Frequently Asked Questions". Generate 3-5 relevant Q&As (or 2-3 if less content available). Use the HTML structure below, including the **exact** `<i>` tag: `<i class="faq-icon fas fa-chevron-down"></i>`]
<div class="faq-section">
  <details class="faq-item">
    <summary class="faq-question">First relevant question about the core topic? <i class="faq-icon fas fa-chevron-down"></i></summary>
    <div class="faq-answer-content">
      <p>Clear and concise answer to question 1, based on the article.</p>
    </div>
  </details>
  <details class="faq-item">
    <summary class="faq-question">Second relevant question addressing a key detail? <i class="faq-icon fas fa-chevron-down"></i></summary>
    <div class="faq-answer-content">
      <p>Detailed answer to question 2.</p>
    </div>
  </details>
  <details class="faq-item">
    <summary class="faq-question">Third relevant question about implications or context? <i class="faq-icon fas fa-chevron-down"></i></summary>
    <div class="faq-answer-content">
      <p>Insightful answer to question 3.</p>
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
  "dateModified": "{current_date_iso}", // Use same as published for simplicity now
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
        logger.error("DEEPSEEK_API_KEY environment variable not set.")
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
        logger.debug(f"Sending SEO generation request (model: {AGENT_MODEL}, max_tokens={max_tokens}, temp={temperature}).")
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=API_TIMEOUT_SECONDS)
        response.raise_for_status()
        result = response.json()
        usage = result.get('usage')
        if usage: logger.debug(f"API Usage: Prompt={usage.get('prompt_tokens')}, Completion={usage.get('completion_tokens')}, Total={usage.get('total_tokens')}")

        if result.get("choices") and len(result["choices"]) > 0:
            message_content = result["choices"][0].get("message", {}).get("content")
            # Basic cleanup: Remove potential markdown code block fences if API adds them
            if message_content:
                content_stripped = message_content.strip()
                if content_stripped.startswith("```") and content_stripped.endswith("```"):
                     # Find first newline after opening ```
                     first_newline = content_stripped.find('\n')
                     if first_newline != -1:
                         content_stripped = content_stripped[first_newline+1:-3].strip()
                     else: # Handle case where there's no newline, just ```content```
                         content_stripped = content_stripped[3:-3].strip()
                return content_stripped
            return None # Return None if message_content is empty initially
        else:
            logger.error(f"API response missing 'choices' or choices empty: {result}")
            return None
    except requests.exceptions.Timeout:
         logger.error(f"API request timed out after {API_TIMEOUT_SECONDS} seconds.")
         return None
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed: {e}")
        if e.response is not None:
            logger.error(f"Response Status: {e.response.status_code}, Body: {e.response.text[:500]}")
        return None
    except json.JSONDecodeError as e:
        response_text = response.text if response else "N/A"
        logger.error(f"Failed to decode API JSON response: {e}. Response text: {response_text[:500]}...")
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
        # Use re.IGNORECASE for all matches
        title_match = re.search(r"^\s*Title Tag:\s*(.*)", response_text, re.MULTILINE | re.IGNORECASE)
        if title_match: parsed_data['generated_title_tag'] = title_match.group(1).strip()
        else: errors.append("Missing 'Title Tag:' line.")

        meta_match = re.search(r"^\s*Meta Description:\s*(.*)", response_text, re.MULTILINE | re.IGNORECASE)
        if meta_match: parsed_data['generated_meta_description'] = meta_match.group(1).strip()
        else: errors.append("Missing 'Meta Description:' line.")

        seo_h1_match = re.search(r"^\s*SEO H1:\s*(.*)", response_text, re.MULTILINE | re.IGNORECASE)
        if seo_h1_match: parsed_data['generated_seo_h1'] = seo_h1_match.group(1).strip()
        else: errors.append("Missing 'SEO H1:' line.")

        script_match = re.search(r'<script\s+type\s*=\s*["\']application/ld\+json["\']\s*>\s*(\{.*?\})\s*<\/script>', response_text, re.DOTALL | re.IGNORECASE)
        if script_match:
            json_content_str = script_match.group(1).strip()
            parsed_data['generated_json_ld'] = script_match.group(0).strip() # Save the whole script tag
            try: json.loads(json_content_str) # Validate JSON content
            except json.JSONDecodeError: errors.append("JSON-LD content invalid.")
        else: errors.append("Missing JSON-LD script block.")

        # Extract Article Body (more robustly)
        body_content = None
        # Try to find content between SEO H1 line and the Source: line
        body_match_to_source = re.search(r"^\s*SEO H1:.*?[\r\n]+([\s\S]*?)[\r\n]+\s*Source:", response_text, re.MULTILINE | re.DOTALL | re.IGNORECASE)
        if body_match_to_source:
            body_content = body_match_to_source.group(1).strip()
        else:
            # Fallback: Try to find content between SEO H1 line and the <script> tag
            body_match_to_script = re.search(r"^\s*SEO H1:.*?[\r\n]+([\s\S]*?)[\r\n]*\s*<script", response_text, re.MULTILINE | re.DOTALL | re.IGNORECASE)
            if body_match_to_script:
                body_content = body_match_to_script.group(1).strip()

        if body_content:
            # Ensure it starts with the expected H1 markdown
            if body_content.startswith("## "):
                parsed_data['generated_article_body_md'] = body_content
                # Optional check for presence of expected sections
                if not re.search(r"###\s+.*", body_content) and "pros-cons-container" not in body_content and "faq-section" not in body_content :
                     logger.debug("Generated body might be missing main H3 analysis or structured HTML sections.") # Debug level
            else:
                errors.append("Extracted Article Body does not start with '## '. Check raw response.")
                parsed_data['generated_article_body_md'] = "" # Set empty if malformed
        else:
             errors.append("Could not extract Article Body content between SEO H1 and Source/Script.")
             parsed_data['generated_article_body_md'] = "" # Set empty if not found

        # --- Final Validation ---
        if not parsed_data.get('generated_article_body_md') or not parsed_data.get('generated_seo_h1'):
            final_error_message = f"Critical parsing failure: Missing Article Body or SEO H1. Errors: {'; '.join(errors if errors else ['Unknown parsing issue'])}"
            logger.error(final_error_message)
            # Log more context on critical failure
            logger.debug(f"Failed parsing response:\n---\n{response_text[:1000]}...\n---")
            return None, final_error_message

        # Provide fallbacks if parsing fails for non-critical parts
        parsed_data.setdefault('generated_title_tag', parsed_data.get('generated_seo_h1', 'Error Title'))
        parsed_data.setdefault('generated_meta_description', 'Error Generating Description')
        parsed_data.setdefault('generated_json_ld', '<script type="application/ld+json">{}</script>')

        return parsed_data, ("; ".join(errors) if errors else None)

    except Exception as e:
        logger.exception(f"Critical unexpected error during SEO response parsing: {e}")
        return None, f"Parsing exception: {e}"


# --- Main Agent Function ---
def run_seo_article_agent(article_data):
    article_id = article_data.get('id', 'N/A')

    content_to_process = article_data.get('content_for_processing')
    if not content_to_process:
        error_msg = f"Missing 'content_for_processing' for SEO agent (ID: {article_id})."
        logger.error(error_msg); article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = error_msg; return article_data

    primary_keyword = article_data.get('filter_verdict', {}).get('primary_topic_keyword')
    if not primary_keyword:
        error_msg = f"Missing primary_topic_keyword from filter_verdict for ID: {article_id}."
        logger.error(error_msg); article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = error_msg; return article_data

    generated_tags = article_data.get('generated_tags', [])
    secondary_keywords = [tag for tag in generated_tags if tag.lower() != primary_keyword.lower()][:3] # Top 3 different tags
    secondary_keywords_list_str = ", ".join(secondary_keywords)

    # Ensure all keywords are strings for JSON dump
    all_keywords = ([primary_keyword] if primary_keyword else []) + generated_tags
    all_keywords = [str(k).strip() for k in all_keywords if k and str(k).strip()] # Clean and ensure string
    all_generated_keywords_json = json.dumps(list(set(all_keywords))) # Unique keywords

    input_data_for_prompt = {
        "article_title": article_data['title'],
        "article_content_for_processing": content_to_process,
        "source_article_url": article_data['link'],
        "target_keyword": primary_keyword,
        "secondary_keywords_list_str": secondary_keywords_list_str,
        "article_image_url": article_data['selected_image_url'],
        "author_name": article_data.get('author', 'AI News Team'),
        "current_date_iso": article_data.get('published_iso') or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "your_website_name": YOUR_WEBSITE_NAME,
        "your_website_logo_url": YOUR_WEBSITE_LOGO_URL,
        "all_generated_keywords_json": all_generated_keywords_json
    }

    # Check for None in critical prompt inputs
    critical_prompt_inputs = ['article_title', 'article_content_for_processing', 'source_article_url', 'target_keyword', 'article_image_url', 'current_date_iso', 'all_generated_keywords_json', 'your_website_name']
    if any(input_data_for_prompt.get(k) is None for k in critical_prompt_inputs):
        missing_data = [k for k in critical_prompt_inputs if input_data_for_prompt.get(k) is None]
        error_msg = f"Cannot run SEO agent for ID {article_id}, critical data for prompt is None: {missing_data}"
        logger.error(error_msg); article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = error_msg; return article_data

    try:
        user_prompt = SEO_PROMPT_USER_TEMPLATE.format(**input_data_for_prompt)
    except KeyError as e:
        logger.exception(f"KeyError formatting SEO prompt template for ID {article_id}! Error: {e}")
        article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = f"Prompt template formatting error: {e}"; return article_data

    logger.info(f"Running SEO article generator for article ID: {article_id} (Enhanced Humanization & SEO)...")
    raw_response_content = call_deepseek_api(SEO_PROMPT_SYSTEM, user_prompt, max_tokens=MAX_TOKENS_RESPONSE, temperature=TEMPERATURE)

    if not raw_response_content:
        error_msg = "API call failed or returned empty content for SEO generation."
        logger.error(f"{error_msg} (ID: {article_id}).")
        article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = error_msg; return article_data

    logger.debug(f"Raw SEO Agent Response for ID {article_id}:\n---\n{raw_response_content[:1500]}...\n---") # Log more for debugging
    parsed_results, error_msg = parse_seo_agent_response(raw_response_content)

    article_data['seo_agent_results'] = parsed_results
    article_data['seo_agent_error'] = error_msg # This can be None if parsing was successful

    if parsed_results is None: # This means critical parsing failure
        logger.error(f"Failed to parse SEO agent response for ID {article_id}: {error_msg or 'Unknown parsing error'}")
        # Store raw response for debugging if parsing totally fails
        article_data['seo_agent_raw_response'] = raw_response_content
    elif error_msg: # Non-critical parsing errors
        logger.warning(f"SEO agent parsing completed with non-critical errors for ID {article_id}: {error_msg}")
    else: # Fully successful
        logger.info(f"Successfully generated and parsed SEO content for ID: {article_id}.")
        # Update article title with SEO H1 if it's different and successfully generated
        if parsed_results.get('generated_seo_h1') and parsed_results['generated_seo_h1'] != article_data['title']:
            logger.info(f"Updating article title for ID {article_id} with generated SEO H1: '{parsed_results['generated_seo_h1']}'")
            article_data['title'] = parsed_results['generated_seo_h1']

    return article_data

# --- Standalone Execution (for testing) ---
if __name__ == "__main__":
    logging.getLogger().setLevel(logging.DEBUG)
    logger.setLevel(logging.DEBUG)

    test_article_data_humanized_seo = {
        'id': 'example-seo-humanized-002',
        'title': "Singapore AI Safety Initiative", # Original shorter title
        'summary': "Singapore announces AI safety plan bringing US and China researchers together.", # Simpler summary
        'content_for_processing': """
Singapore has launched a significant initiative focused on global AI safety, successfully gathering researchers from the United States, China, and Europe. This effort aims to tackle the potential risks associated with advanced artificial intelligence. Announced alongside the ICLR conference, the "Singapore Consensus on Global AI Safety Research Priorities" identifies three main areas for joint research: understanding frontier AI risks, creating safer AI models, and establishing methods to control advanced AI systems. This collaboration is notable given the competitive backdrop of US-China relations in the AI field.

Max Tegmark, an MIT scientist involved, noted Singapore's unique position as a neutral facilitator. "They know they won’t build AGI themselves—they will have it done to them—so it’s in their interest to get the major players talking," he commented. The meeting included experts from major AI labs like OpenAI and Google DeepMind, alongside academics from Tsinghua University and representatives from international AI safety institutes.

The consensus marks a step towards unified global standards amid concerns about unchecked AI development leading to unforeseen consequences, such as deceptive AI or loss of control. Tegmark recently published work questioning the effectiveness of using weaker AI to control stronger AI, suggesting current safety paradigms might need rethinking. This contrasts with some political voices, like JD Vance, who advocate for minimal AI restrictions to maintain a competitive edge.
""", # More detailed input content
        'link': "https://example.com/singapore-ai-safety-consensus",
        'filter_verdict': {
            'importance_level': 'Interesting', 'topic': 'Regulation',
            'reasoning_summary': 'Significant international collaboration on AI safety facilitated by Singapore.',
            'primary_topic_keyword': 'AI Safety Collaboration' # More specific keyword
        },
        'selected_image_url': "https://via.placeholder.com/800x500.png?text=Singapore+AI+Safety",
        'published_iso': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'generated_tags': ["AI Safety", "Singapore Consensus", "International Collaboration", "US-China AI", "AI Regulation", "AI Ethics", "Frontier AI", "AI Control Problem", "Max Tegmark", "Geopolitics of AI"],
        'author': 'Global Tech Reporter' # Different author
    }

    logger.info("\n--- Running SEO Agent Standalone Test (Enhanced Humanization & SEO) ---")
    result_data = run_seo_article_agent(test_article_data_humanized_seo.copy())

    print("\n--- Final Result Data (Enhanced Humanization Test) ---")
    if result_data and result_data.get('seo_agent_results'):
        print("\n--- Parsed SEO Results ---")
        print(f"Title Tag: {result_data['seo_agent_results'].get('generated_title_tag')}")
        print(f"Meta Desc: {result_data['seo_agent_results'].get('generated_meta_description')}")
        print(f"SEO H1: {result_data['seo_agent_results'].get('generated_seo_h1')}")
        print(f"JSON-LD Present: {bool(result_data['seo_agent_results'].get('generated_json_ld'))}")
        print("\n--- Article Body Markdown (Check for natural language, structure, HTML for Pros/Cons & FAQ) ---")
        print(result_data['seo_agent_results'].get('generated_article_body_md', ''))
        if result_data.get('seo_agent_error'):
            print(f"\nParsing Warning/Error: {result_data['seo_agent_error']}")
        print(f"\n--- Final Article Title (may be updated by SEO H1): {result_data.get('title')} ---")

    elif result_data and result_data.get('seo_agent_error'): # Critical error from agent or parsing
         print(f"\nSEO Agent FAILED. Error: {result_data.get('seo_agent_error')}")
         if 'seo_agent_raw_response' in result_data: print(f"\n--- Raw Response (Debug) ---\n{result_data['seo_agent_raw_response']}")
    else: print("\nSEO Agent FAILED critically or returned no data.")

    logger.info("\n--- SEO Agent Standalone Test Complete ---")