# src/agents/seo_article_generator_agent.py

import os
import requests
import json
import logging
import re
from dotenv import load_dotenv
from datetime import datetime, timezone

# --- Load Environment Variables ---
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '..', '.env'))
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
YOUR_WEBSITE_NAME = os.getenv('YOUR_WEBSITE_NAME', 'Dacoola') # Get from env
YOUR_WEBSITE_LOGO_URL = os.getenv('YOUR_WEBSITE_LOGO_URL', '') # Get from env

# --- Configuration ---
AGENT_MODEL = "deepseek-chat"
# *** INCREASED MAX TOKENS for longer articles ***
MAX_TOKENS_RESPONSE = 4000
# *** Slightly increased temperature for more natural writing ***
TEMPERATURE = 0.6

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
# --- End Setup Logging ---


# --- *** REVISED SEO Article Prompt *** ---
SEO_PROMPT_SYSTEM = """
You are an **Expert Tech Journalist and SEO Content Strategist** powered by DeepSeek. Your mission is to transform concise RSS feed data into comprehensive, engaging, factually precise, and SEO-optimized news articles suitable for a knowledgeable tech audience. Adhere strictly to the following directives:

1.  **Content Generation & Style:**
    *   **Primary Goal:** Expand significantly upon the provided `{{RSS_SUMMARY}}`. Generate **3-5 well-structured paragraphs** for the Article Body, aiming for approximately **250-400 words**.
    *   **Factual Integrity (CRITICAL):** Base the *entire* article body **exclusively** on the information present in the `{{RSS_SUMMARY}}`. **DO NOT INVENT DETAILS, QUOTES, NUMBERS, OR SPECULATION** not directly and clearly supported by the summary. If the summary is sparse, keep the article concise but well-written; do not pad with unrelated generic statements.
    *   **Tone & Voice:** Write in a clear, informative, and engaging journalistic style. Use active voice, varied sentence structures, and clear transitions. Avoid overly technical jargon unless present in the summary. **Crucially, avoid robotic phrasing and overly promotional or hype-filled language** (like "groundbreaking", "revolutionary", "game-changer") unless the summary *explicitly* uses such terms AND provides strong supporting evidence (e.g., specific benchmark results, documented impact). Maintain a neutral, objective tone where appropriate.
    *   **Structure:** Begin the Article Body with an `## H2` heading that accurately reflects the `{{ARTICLE_TITLE}}`. Structure the paragraphs logically (e.g., introduction of main point, elaboration with details from summary, context/implications *if inferable*). Use at most one `### H3` sub-heading if essential for clarity based *only* on the summary content. Keep paragraphs focused, typically 2-4 sentences long.
    *   **Significance (Conditional & Careful):** If the `{{RSS_SUMMARY}}` provides sufficient context to *logically deduce* the immediate significance or potential impact of the news *without speculation*, you MAY include a brief concluding sentence or short paragraph (naturally integrated or optionally under `### Significance`) explaining this deduced importance. **DO NOT add this section if the significance isn't directly evident from the summary's facts.** Err on the side of caution and omit if unsure.

2.  **Output Format (Strict Adherence Required):**
    *   **Markdown Only:** The Article Body section must be valid Markdown.
    *   **Exact Order:** Output MUST follow this sequence precisely: Title Tag, Meta Description, Article Body, Source Link, JSON-LD Script. No extra text, greetings, or explanations outside this structure.
    *   **Section 1: Title Tag:** Format: `Title Tag: [Generated title tag]`. Strictly **≤ 60 characters**. Must include `{{TARGET_KEYWORD}}` naturally, preferably early.
    *   **Section 2: Meta Description:** Format: `Meta Description: [Generated meta description]`. Strictly **≤ 160 characters**. Summarize the core point of the article and include `{{TARGET_KEYWORD}}` once naturally.
    *   **Section 3: Article Body:** Starts with the `## H2` heading. Contains the 3-5 paragraphs (or fewer if summary is brief) based *only* on `{{RSS_SUMMARY}}`. Integrates `{{TARGET_KEYWORD}}` naturally once within the first main paragraph.
    *   **Section 4: Source Link:** The final line of the Markdown text MUST be exactly: `Source: [{{ARTICLE_TITLE}}]({{SOURCE_ARTICLE_URL}})`

3.  **Structured Data (JSON-LD):**
    *   Immediately after the Source Link line, output the *exact* JSON-LD block provided in the user prompt template, filling in the bracketed placeholders with the generated Title Tag and Meta Description text. Include ALL provided keywords in the `"keywords"` array.

4.  **Accuracy & Constraints:**
    *   **No Hallucinations.** Adherence to the `{{RSS_SUMMARY}}` is paramount.
    *   Use `{{TARGET_KEYWORD}}` exactly once in Title Tag and once in the body's first paragraph.
    *   Strict length limits for Title Tag and Meta Description.

5.  **Error Handling:**
    *   If any required input field (`{{RSS_SUMMARY}}`, `{{ARTICLE_TITLE}}`, etc.) is missing or clearly invalid, output ONLY the exact string: `Error: Missing or invalid input field(s).`

6.  **No Extra Output:** Absolutely NO text before `Title Tag:` or after the closing `</script>` tag.
"""

# User template remains the same, providing the variables
SEO_PROMPT_USER_TEMPLATE = """
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
"""
# --- End Revised SEO Article Prompt ---

# --- API Call Function ---
def call_deepseek_api(system_prompt, user_prompt, max_tokens=MAX_TOKENS_RESPONSE, temperature=TEMPERATURE):
    """Calls the DeepSeek API."""
    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY not found.")
        return None
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
    payload = { "model": AGENT_MODEL, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], "max_tokens": max_tokens, "temperature": temperature, "stream": False }
    try:
        logger.debug(f"Sending SEO generation request (max_tokens={max_tokens}, temp={temperature}).")
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=240) # INCREASED TIMEOUT for longer response
        response.raise_for_status()
        result = response.json()
        # --- Log usage for token checking ---
        usage = result.get('usage')
        if usage: logger.debug(f"API Usage: Prompt={usage.get('prompt_tokens')}, Completion={usage.get('completion_tokens')}, Total={usage.get('total_tokens')}")
        # ---
        if result.get("choices") and len(result["choices"]) > 0:
            message_content = result["choices"][0].get("message", {}).get("content")
            return message_content.strip() if message_content else None
        else: logger.error(f"API response missing 'choices': {result}"); return None
    except requests.exceptions.RequestException as e: logger.error(f"API request failed: {e}"); return None
    except Exception as e: logger.exception(f"Unexpected error during API call: {e}"); return None
# --- End API Call ---

# --- Parsing Function (Should still work, but keep an eye on body extraction) ---
def parse_seo_agent_response(response_text):
    """Parses the structured Markdown response from the SEO agent."""
    parsed_data = {}
    errors = []
    if not response_text or response_text.strip().startswith("Error:"): logger.error(f"SEO Agent returned error/empty: {response_text}"); return None, response_text or "Empty response"
    try:
        title_match = re.search(r"^Title Tag:\s*(.*)", response_text, re.MULTILINE)
        if title_match: parsed_data['generated_title_tag'] = title_match.group(1).strip()
        else: errors.append("No 'Title Tag:'")
        meta_match = re.search(r"^Meta Description:\s*(.*)", response_text, re.MULTILINE)
        if meta_match: parsed_data['generated_meta_description'] = meta_match.group(1).strip()
        else: errors.append("No 'Meta Description:'")
        script_match = re.search(r'(<script type="application/ld\+json">.*?</script>)', response_text, re.DOTALL | re.IGNORECASE)
        if script_match:
            parsed_data['generated_json_ld'] = script_match.group(1).strip()
            # Optional validation
            try:
                inner_json_str = script_match.group(1).split('>', 1)[1].rsplit('<', 1)[0]
                json_ld_data = json.loads(inner_json_str)
                if json_ld_data.get('headline') != parsed_data.get('generated_title_tag'): logger.warning("JSON-LD headline mismatch!")
                if json_ld_data.get('description') != parsed_data.get('generated_meta_description'): logger.warning("JSON-LD description mismatch!")
                # Check if keywords list looks valid
                if not isinstance(json_ld_data.get('keywords'), list): logger.warning("JSON-LD keywords is not a list!")
            except Exception as json_e: logger.warning(f"Cannot validate JSON-LD content: {json_e}")
        else: errors.append("No JSON-LD script block.")

        # Extract Article Body more robustly
        body_match = re.search(r"Meta Description:.*?\n\n(.*?)\n\nSource:", response_text, re.DOTALL | re.IGNORECASE)
        if body_match:
             parsed_data['generated_article_body_md'] = body_match.group(1).strip()
             logger.debug(f"Extracted article body length: {len(parsed_data['generated_article_body_md'])} chars")
        else:
             # Fallback if exact newlines aren't present
             body_fallback_match = re.search(r"Meta Description:.*?[\r\n]+(##.*?)(?:[\r\n]+Source:|\Z)", response_text, re.DOTALL | re.IGNORECASE)
             if body_fallback_match:
                 parsed_data['generated_article_body_md'] = body_fallback_match.group(1).strip()
                 logger.warning("Used fallback regex for article body extraction.")
                 logger.debug(f"Extracted article body length (fallback): {len(parsed_data['generated_article_body_md'])} chars")
             else:
                 errors.append("Cannot reliably extract Article Body.")

        if errors: logger.error(f"SEO Parsing errors: {'; '.join(errors)}")
        if 'generated_article_body_md' not in parsed_data or 'generated_json_ld' not in parsed_data: return None, f"Critical parsing failure: {'; '.join(errors)}"
        return parsed_data, None
    except Exception as e: logger.exception(f"Critical error parsing SEO response: {e}"); return None, f"Parsing exception: {e}"


def run_seo_article_agent(article_data):
    """Generates the SEO brief, aiming for longer content."""
    # Pass ALL generated tags/keywords to the prompt
    all_keywords = [article_data.get('filter_verdict', {}).get('primary_topic_keyword')] + article_data.get('generated_tags', [])
    all_keywords = [k for k in all_keywords if k] # Remove None/empty
    all_keywords_json_str = json.dumps(all_keywords) # Pass as JSON list string

    # Required keys check remains the same
    required_keys = ['title', 'summary', 'link', 'filter_verdict', 'selected_image_url', 'published_iso']
    if not article_data or not all(k in article_data and article_data[k] is not None for k in required_keys):
        logger.error(f"Missing required data for SEO agent. Needs: {required_keys}")
        article_data['seo_agent_error'] = "Missing required input"
        return article_data # Return modified dict

    if not article_data['filter_verdict'] or not article_data['filter_verdict'].get('primary_topic_keyword'):
         logger.error("Missing primary_topic_keyword from filter_verdict.")
         article_data['seo_agent_error'] = "Missing primary keyword"
         return article_data

    input_data = {
        "article_title": article_data.get('title'),
        "rss_summary": article_data.get('summary'), # Base content on this
        "source_article_url": article_data.get('link'),
        "target_keyword": article_data['filter_verdict'].get('primary_topic_keyword'),
        "article_image_url": article_data.get('selected_image_url'),
        "author_name": article_data.get('author', 'AI News Team'),
        "current_date_iso": article_data.get('published_iso', datetime.now(timezone.utc).date().isoformat()),
        "your_website_name": YOUR_WEBSITE_NAME,
        "your_website_logo_url": YOUR_WEBSITE_LOGO_URL,
        "all_generated_keywords_json": all_keywords_json_str # Pass the list of keywords
    }

    critical_inputs = ['article_title', 'rss_summary', 'source_article_url', 'target_keyword', 'article_image_url', 'current_date_iso', 'all_generated_keywords_json']
    if any(input_data[k] is None for k in critical_inputs):
         missing = [k for k in critical_inputs if input_data[k] is None]
         logger.error(f"Cannot run SEO agent, critical input data is None: {missing}")
         article_data['seo_agent_error'] = f"Missing critical input: {missing}"
         return article_data

    user_prompt = SEO_PROMPT_USER_TEMPLATE.format(**input_data)

    logger.info(f"Running SEO article generator for article ID: {article_data.get('id', 'N/A')}...")
    # Call API with increased token limit and adjusted temp
    raw_response_content = call_deepseek_api(SEO_PROMPT_SYSTEM, user_prompt, max_tokens=MAX_TOKENS_RESPONSE, temperature=TEMPERATURE)

    if not raw_response_content:
        logger.error("SEO agent failed to get a response from the API.")
        article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = "API call failed"
        return article_data

    parsed_results, error_msg = parse_seo_agent_response(raw_response_content)

    if error_msg:
        logger.error(f"Failed to parse SEO agent response: {error_msg}")
        article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = f"Parsing failed: {error_msg}"
        article_data['seo_agent_raw_response'] = raw_response_content # Store raw response for debug
    else:
        logger.info(f"Successfully generated/parsed SEO content for {article_data.get('id', 'N/A')}.")
        article_data['seo_agent_results'] = parsed_results; article_data['seo_agent_error'] = None

    return article_data

# --- Example Usage (keep as before) ---
if __name__ == "__main__":
    # ... (keep existing example usage) ...
    pass # Placeholder to keep block valid