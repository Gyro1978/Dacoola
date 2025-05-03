# src/agents/seo_article_generator_agent.py

import os
import sys # Added sys for path check below
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
    sys.path.insert(0, PROJECT_ROOT) # Add project root for imports if needed
# --- End Path Setup ---

# --- Setup Logging ---
logger = logging.getLogger(__name__)
if not logging.getLogger().hasHandlers(): # Basic config for standalone testing
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
MAX_TOKENS_RESPONSE = 4096 # Keep generous for potential analysis
TEMPERATURE = 0.65 # Slightly higher temp for more insightful "Why it Matters"
API_TIMEOUT_SECONDS = 240

# --- Agent Prompts ---

# --- MODIFIED SYSTEM PROMPT ---
SEO_PROMPT_SYSTEM = """
You are an **Expert Tech News Analyst and SEO Content Strategist** powered by DeepSeek. Your mission is to transform concise RSS feed data into an engaging, insightful, factually precise, and SEO-optimized news brief suitable for a tech-savvy audience that values quick understanding and context. Adhere strictly to the following directives:

1.  **Content Generation & Style:**
    *   **Primary Goal:** Generate a **concise news summary (1-2 paragraphs)** based *only* on the facts in `{{RSS_SUMMARY}}`. Immediately following the summary, add a section titled `### Why It Matters` (or a similar engaging title like `### The Big Picture` or `### What This Means`) containing **1-2 paragraphs** of analysis, context, or potential implications.
    *   **News Summary Section (Factual Integrity CRITICAL):** Base the initial 1-2 paragraphs **exclusively** on the information present in the `{{RSS_SUMMARY}}`. **DO NOT INVENT DETAILS, QUOTES, NUMBERS, OR SPECULATION** not directly and clearly supported by the summary. Keep it brief and informative.
    *   **"Why It Matters" Section (Insight & Context):** This is where you add value. Based on the *type* of news presented in the summary (e.g., model release, funding, regulation, security issue), provide brief analysis. Explain the potential impact, connect it to broader trends, or highlight the significance for the reader/industry. **Crucially, ground this analysis in the facts from the summary, but interpret their potential meaning.** Avoid baseless speculation. If the summary is too sparse for meaningful analysis, keep this section very short or state the context is limited.
    *   **Overall Length & Tone:** Aim for a total body length of roughly **200-350 words**. Maintain a clear, engaging, slightly analytical journalistic tone. Use active voice. Avoid robotic phrasing and excessive hype unless explicitly justified by the summary.
    *   **Structure:** Begin the Article Body with an `## H2` heading reflecting `{{ARTICLE_TITLE}}`. Follow with the 1-2 paragraph summary. Then, include the `### Why It Matters` (or similar) heading and its 1-2 paragraphs.

2.  **Output Format (Strict Adherence Required):**
    *   **Markdown Only:** The Article Body section must be valid Markdown.
    *   **Exact Order:** Output MUST follow this sequence precisely: Title Tag, Meta Description, Article Body (including the "Why It Matters" section), Source Link, JSON-LD Script. No extra text, greetings, or explanations outside this structure.
    *   **Section 1: Title Tag:** Format: `Title Tag: [Generated title tag]`. Strictly **≤ 60 characters**. Include `{{TARGET_KEYWORD}}` naturally.
    *   **Section 2: Meta Description:** Format: `Meta Description: [Generated meta description]`. Strictly **≤ 160 characters**. Summarize the core news point and include `{{TARGET_KEYWORD}}` naturally.
    *   **Section 3: Article Body:** Starts with `## H2` heading. Contains the 1-2 paragraph summary, immediately followed by the `### Why It Matters` section. Integrates `{{TARGET_KEYWORD}}` naturally once within the first main paragraph (the summary part).
    *   **Section 4: Source Link:** The final line before the script MUST be exactly: `Source: [{{ARTICLE_TITLE}}]({{SOURCE_ARTICLE_URL}})`

3.  **Structured Data (JSON-LD):**
    *   Immediately after the Source Link line, output the *exact* JSON-LD block format described in the User Prompt. Include ALL provided keywords in `"keywords"`. Ensure the full `<script type="application/ld+json">...</script>` block is present.

4.  **Accuracy & Constraints:**
    *   **No Hallucinations.** Factual summary must adhere strictly to `{{RSS_SUMMARY}}`. Analysis should be logically derived.
    *   Use `{{TARGET_KEYWORD}}` exactly once in Title Tag, Meta Description, and the *summary* part of the body.
    *   Strict length limits for Title Tag and Meta Description.

5.  **Error Handling:**
    *   If any required input field is missing or clearly invalid, output ONLY: `Error: Missing or invalid input field(s).`

6.  **No Extra Output:** Absolutely NO text before `Title Tag:` or after the closing `</script>` tag.
"""

# --- MODIFIED USER TEMPLATE ---
SEO_PROMPT_USER_TEMPLATE = """
Task: Generate Title Tag, Meta Description, Article Body (Markdown including concise summary AND "Why It Matters" analysis), and JSON-LD Script Block based on the input. Follow ALL directives from the System Prompt precisely.

ARTICLE_TITLE: {article_title}
RSS_SUMMARY: {rss_summary}
SOURCE_ARTICLE_URL: {source_article_url}
TARGET_KEYWORD: {target_keyword}
ARTICLE_IMAGE_URL: {article_image_url}
AUTHOR_NAME: {author_name}
CURRENT_DATE_YYYY_MM_DD: {current_date_iso}
YOUR_WEBSITE_NAME: {your_website_name}
YOUR_WEBSITE_LOGO_URL: {your_website_logo_url}
ALL_GENERATED_KEYWORDS_LIST: {all_generated_keywords_json}

Required Output Format (Strict):
Title Tag: [Generated title tag ≤ 60 chars, include TARGET_KEYWORD]
Meta Description: [Generated meta description ≤ 160 chars, include TARGET_KEYWORD]

## [H2 Heading reflecting ARTICLE_TITLE]
[Paragraph 1-2: CONCISE summary based ONLY on RSS_SUMMARY. Include TARGET_KEYWORD naturally once here.]

### Why It Matters
[Paragraph 1-2: Brief analysis, context, implications derived from the summary facts. Explain the significance.]

Source: [{article_title}]({source_article_url})

<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "NewsArticle",
  "headline": "[Generated title tag from above]",
  "description": "[Generated meta description from above]",
  "keywords": {all_generated_keywords_json},
  "mainEntityOfPage": {{ "@type": "WebPage", "@id": "{source_article_url}" }},
  "image": {{ "@type": "ImageObject", "url": "{article_image_url}" }},
  "datePublished": "{current_date_iso}",
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
    """Calls the DeepSeek API and returns the content string."""
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
            return message_content.strip() if message_content else None
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
    """
    Parses the structured Markdown response from the SEO agent.
    Returns a dictionary with parsed components and an error message string (or None if no error).
    """
    parsed_data = {}
    errors = [] # Collect non-critical errors

    if not response_text or response_text.strip().startswith("Error:"):
        error_message = f"SEO Agent returned error or empty response: {response_text or 'Empty response'}"
        logger.error(error_message)
        return None, error_message

    try:
        # Extract Title Tag
        title_match = re.search(r"^\s*Title Tag:\s*(.*)", response_text, re.MULTILINE | re.IGNORECASE)
        if title_match:
            parsed_data['generated_title_tag'] = title_match.group(1).strip()
            if len(parsed_data['generated_title_tag']) > 70:
                 logger.warning(f"Generated title tag > 60 chars: '{parsed_data['generated_title_tag']}'")
        else: errors.append("Missing 'Title Tag:' line.")

        # Extract Meta Description
        meta_match = re.search(r"^\s*Meta Description:\s*(.*)", response_text, re.MULTILINE | re.IGNORECASE)
        if meta_match:
            parsed_data['generated_meta_description'] = meta_match.group(1).strip()
            if len(parsed_data['generated_meta_description']) > 170:
                 logger.warning(f"Generated meta description > 160 chars: '{parsed_data['generated_meta_description']}'")
        else: errors.append("Missing 'Meta Description:' line.")

        # Extract JSON-LD Script Block
        script_match = re.search(
            r'<script\s+type\s*=\s*["\']application/ld\+json["\']\s*>\s*(\{.*?\})\s*<\/script>',
            response_text, re.DOTALL | re.IGNORECASE
        )
        if script_match:
            json_content_str = script_match.group(1).strip()
            parsed_data['generated_json_ld'] = script_match.group(0).strip()
            try:
                json.loads(json_content_str)
            except json.JSONDecodeError as json_e:
                logger.warning(f"Could not validate JSON-LD: {json_e}. Content: {json_content_str[:200]}...")
                errors.append("JSON-LD content invalid.")
        else:
            errors.append("Missing JSON-LD script block.")

        # Extract Article Body (now expects ## H2 ... ### Why ... Source:)
        body_match = re.search(
            # Look for content between Meta Desc line and the Source line or Script tag
            # Ensure it captures the ## H2 heading at the start
            r"Meta Description:.*?[\r\n]+(##.*?)(?=[\r\n]+\s*Source:|[\r\n]*\s*<script)",
            response_text, re.DOTALL | re.IGNORECASE
        )
        if body_match:
             body_content = body_match.group(1).strip()
             # Clean potential leftover Source line if regex didn't exclude perfectly
             body_content = re.sub(r'\s*Source:\s*\[.*?\]\(.*?\)\s*$', '', body_content, flags=re.MULTILINE).strip()
             parsed_data['generated_article_body_md'] = body_content
             # Check if the 'Why It Matters' section seems to be present
             if "### Why It Matters" not in body_content and \
                "### The Big Picture" not in body_content and \
                "### What This Means" not in body_content:
                 logger.warning("Generated body might be missing 'Why It Matters' section.")
                 # errors.append("Missing 'Why It Matters' section.") # Optional: Treat as error
             if not body_content: errors.append("Extracted Article Body is empty.")
             else: logger.debug(f"Extracted article body length: {len(body_content)} chars.")
        else:
             errors.append("Could not extract Article Body content.")

        # --- Final Result Determination ---
        if 'generated_article_body_md' not in parsed_data or not parsed_data['generated_article_body_md']:
            final_error_message = f"Critical parsing failure: Missing Article Body. Errors: {'; '.join(errors)}"
            logger.error(final_error_message)
            return None, final_error_message

        if errors:
            error_summary = "; ".join(errors)
            logger.warning(f"SEO Parsing completed with non-critical errors: {error_summary}")
            parsed_data.setdefault('generated_title_tag', '')
            parsed_data.setdefault('generated_meta_description', '')
            parsed_data.setdefault('generated_json_ld', '')
            return parsed_data, error_summary
        else:
            return parsed_data, None

    except Exception as e:
        logger.exception(f"Critical unexpected error during SEO response parsing: {e}")
        return None, f"Parsing exception: {e}"

# --- Main Agent Function ---
def run_seo_article_agent(article_data):
    """Generates SEO title, description, article body (MD), and JSON-LD script."""
    article_id = article_data.get('id', 'N/A')

    # --- Input Data Preparation ---
    primary_keyword = article_data.get('filter_verdict', {}).get('primary_topic_keyword')
    generated_tags = article_data.get('generated_tags', [])
    all_keywords = ([primary_keyword] if primary_keyword else []) + generated_tags
    all_keywords = [str(k).strip() for k in all_keywords if k and str(k).strip()]
    all_generated_keywords_json = json.dumps(all_keywords)

    required_keys = ['title', 'summary', 'link', 'filter_verdict', 'selected_image_url', 'published_iso']
    missing_keys = [k for k in required_keys if article_data.get(k) is None]
    if missing_keys:
        error_msg = f"Missing required data for SEO agent (ID: {article_id}). Needs: {missing_keys}"
        logger.error(error_msg); article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = error_msg; return article_data
    if not primary_keyword:
        logger.error(f"Missing primary_topic_keyword from filter_verdict for ID: {article_id}.")
        article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = "Missing primary keyword"; return article_data

    input_data_for_prompt = {
        "article_title": article_data['title'], "rss_summary": article_data['summary'],
        "source_article_url": article_data['link'], "target_keyword": primary_keyword,
        "article_image_url": article_data['selected_image_url'],
        "author_name": article_data.get('author', 'AI News Team'),
        "current_date_iso": article_data.get('published_iso') or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "your_website_name": YOUR_WEBSITE_NAME, "your_website_logo_url": YOUR_WEBSITE_LOGO_URL,
        "all_generated_keywords_json": all_generated_keywords_json
    }

    critical_inputs = ['article_title', 'rss_summary', 'source_article_url', 'target_keyword', 'article_image_url', 'current_date_iso', 'all_generated_keywords_json', 'your_website_name']
    if any(input_data_for_prompt.get(k) is None for k in critical_inputs):
        missing = [k for k in critical_inputs if input_data_for_prompt.get(k) is None]
        error_msg = f"Cannot run SEO agent for ID {article_id}, critical derived input data is None: {missing}"
        logger.error(error_msg); article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = error_msg; return article_data

    try:
        user_prompt = SEO_PROMPT_USER_TEMPLATE.format(**input_data_for_prompt)
    except KeyError as e:
        logger.exception(f"KeyError formatting SEO prompt template for ID {article_id}! Error: {e}")
        article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = f"Prompt template formatting error: {e}"; return article_data

    logger.info(f"Running SEO article generator for article ID: {article_id} (with 'Why It Matters')...")
    raw_response_content = call_deepseek_api(SEO_PROMPT_SYSTEM, user_prompt, max_tokens=MAX_TOKENS_RESPONSE, temperature=TEMPERATURE)

    if not raw_response_content:
        logger.error(f"SEO agent failed to get a response from the API for ID: {article_id}.")
        article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = "API call failed or returned empty"; return article_data

    logger.debug(f"Raw SEO Agent Response for ID {article_id}:\n---\n{raw_response_content}\n---")

    parsed_results, error_msg = parse_seo_agent_response(raw_response_content)

    article_data['seo_agent_results'] = parsed_results
    article_data['seo_agent_error'] = error_msg

    if parsed_results is None:
        logger.error(f"Failed to parse SEO agent response for ID {article_id}: {error_msg}")
        article_data['seo_agent_raw_response'] = raw_response_content
    elif error_msg:
        logger.warning(f"SEO agent parsing completed with non-critical errors for ID {article_id}: {error_msg}")
    else:
        logger.info(f"Successfully generated and parsed SEO content for ID: {article_id}.")

    return article_data

# --- Standalone Execution (for testing) ---
if __name__ == "__main__":
    logging.getLogger().setLevel(logging.DEBUG)
    logger.setLevel(logging.DEBUG)

    test_article_data = {
        'id': 'example-seo-why-matters-456',
        'title': "Apple and Anthropic Reportedly Partner to Build an AI Coding Platform",
        'summary': "Tech giants Apple and AI startup Anthropic are reportedly collaborating on a new platform aimed at assisting programmers. The project, details of which remain scarce, is said to leverage generative AI to streamline software development workflows, potentially integrating into Apple's existing developer tools like Xcode. Neither company has officially commented.",
        'link': "https://example.com/apple-anthropic-ai-coder",
        'filter_verdict': {
            'importance_level': 'Interesting', 'topic': 'Software',
            'reasoning_summary': 'Partnership between major players on significant AI application.',
            'primary_topic_keyword': 'Apple Anthropic AI coding'
        },
        'selected_image_url': "https://via.placeholder.com/800x500.png?text=Apple+Anthropic+AI",
        'published_iso': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'generated_tags': ["Apple", "Anthropic", "AI Coding", "Generative AI", "Software Development", "Developer Tools", "Xcode", "AI Partnership"],
        'author': 'Standalone Test'
    }

    logger.info("\n--- Running SEO Agent Standalone Test (with 'Why It Matters') ---")
    result_data = run_seo_article_agent(test_article_data.copy())

    print("\n--- Final Result Data ---")
    if result_data and result_data.get('seo_agent_results'):
        print("\n--- Parsed SEO Results ---")
        print(f"Title Tag: {result_data['seo_agent_results'].get('generated_title_tag')}")
        print(f"Meta Desc: {result_data['seo_agent_results'].get('generated_meta_description')}")
        print(f"JSON-LD Present: {bool(result_data['seo_agent_results'].get('generated_json_ld'))}")
        print("\n--- Article Body Markdown ---")
        print(result_data['seo_agent_results'].get('generated_article_body_md', ''))
        if result_data.get('seo_agent_error'):
            print(f"\nParsing Warning/Error: {result_data['seo_agent_error']}")

    elif result_data and result_data.get('seo_agent_error'):
         print(f"\nSEO Agent FAILED. Error: {result_data.get('seo_agent_error')}")
         if 'seo_agent_raw_response' in result_data:
              print("\n--- Raw Response (Debug) ---")
              print(result_data['seo_agent_raw_response'])
    else:
         print("\nSEO Agent FAILED critically or returned no data.")

    logger.info("\n--- SEO Agent Standalone Test Complete ---")