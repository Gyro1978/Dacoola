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
# Get logger. If main.py configured root logger, this will use that config.
logger = logging.getLogger(__name__)
if not logging.getLogger().hasHandlers(): # Basic config for standalone testing
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# --- Load Environment Variables ---
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
# Load site config needed for the JSON-LD schema
YOUR_WEBSITE_NAME = os.getenv('YOUR_WEBSITE_NAME', 'Dacoola')
YOUR_WEBSITE_LOGO_URL = os.getenv('YOUR_WEBSITE_LOGO_URL', '')

# --- Configuration ---
AGENT_MODEL = "deepseek-chat"
MAX_TOKENS_RESPONSE = 4096 # Reduced slightly, 5k might be excessive for this task length
TEMPERATURE = 0.6 # Moderate temperature for creative but factual expansion
API_TIMEOUT_SECONDS = 240 # Generous timeout for potentially longer generation

# --- Agent Prompts ---
# (Keep prompts exactly as they were - they are detailed and specific)
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
    *   Immediately after the Source Link line, output the *exact* JSON-LD block format described in the User Prompt (filling in placeholders). Include ALL provided keywords in the `"keywords"` array. CRITICAL: Ensure the full `<script type="application/ld+json">...</script>` block is present at the very end.

4.  **Accuracy & Constraints:**
    *   **No Hallucinations.** Adherence to the `{{RSS_SUMMARY}}` is paramount.
    *   Use `{{TARGET_KEYWORD}}` exactly once in Title Tag and once in the body's first paragraph.
    *   Strict length limits for Title Tag and Meta Description.

5.  **Error Handling:**
    *   If any required input field (`{{RSS_SUMMARY}}`, `{{ARTICLE_TITLE}}`, etc.) is missing or clearly invalid, output ONLY the exact string: `Error: Missing or invalid input field(s).`

6.  **No Extra Output:** Absolutely NO text before `Title Tag:` or after the closing `</script>` tag.
"""

SEO_PROMPT_USER_TEMPLATE = """
Task: Generate Title Tag, Meta Description, Article Body (Markdown), and JSON-LD Script Block based on the input. Follow ALL directives from the System Prompt precisely.

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
[Paragraph 1: Expand on summary, include TARGET_KEYWORD naturally. ~2-4 sentences]

[Paragraph 2: Further details from summary. ~2-4 sentences]

[Paragraph 3-5: Continue elaborating ONLY on summary details. Add ### H3 if needed for clarity based ONLY on summary.]

[Optional: ### Significance paragraph ONLY IF directly derivable from summary without speculation.]

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
    # (Keeping this function duplicated for now)
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

    # Basic check for empty or error response from API
    if not response_text or response_text.strip().startswith("Error:"):
        error_message = f"SEO Agent returned error or empty response: {response_text or 'Empty response'}"
        logger.error(error_message)
        return None, error_message # Return None for data, indicating critical failure

    try:
        # Extract Title Tag using regex, allowing for slight variations
        title_match = re.search(r"^\s*Title Tag:\s*(.*)", response_text, re.MULTILINE | re.IGNORECASE)
        if title_match:
            parsed_data['generated_title_tag'] = title_match.group(1).strip()
            if len(parsed_data['generated_title_tag']) > 70: # Slightly more lenient warning
                 logger.warning(f"Generated title tag > 60 chars: '{parsed_data['generated_title_tag']}'")
        else: errors.append("Missing 'Title Tag:' line.")

        # Extract Meta Description
        meta_match = re.search(r"^\s*Meta Description:\s*(.*)", response_text, re.MULTILINE | re.IGNORECASE)
        if meta_match:
            parsed_data['generated_meta_description'] = meta_match.group(1).strip()
            if len(parsed_data['generated_meta_description']) > 170: # Slightly more lenient warning
                 logger.warning(f"Generated meta description > 160 chars: '{parsed_data['generated_meta_description']}'")
        else: errors.append("Missing 'Meta Description:' line.")

        # Extract JSON-LD Script Block (Improved Regex for robustness)
        script_match = re.search(
            r'<script\s+type\s*=\s*["\']application/ld\+json["\']\s*>\s*(\{.*?\})\s*<\/script>',
            response_text,
            re.DOTALL | re.IGNORECASE # DOTALL allows '.' to match newlines, IGNORECASE handles case variations
        )
        if script_match:
            # Extract only the JSON part for validation, store the full script tag
            json_content_str = script_match.group(1).strip()
            parsed_data['generated_json_ld'] = script_match.group(0).strip() # Store the full <script>...</script>
            try:
                # Attempt to validate the extracted JSON content
                json.loads(json_content_str)
                logger.debug("JSON-LD content validated successfully.")
            except json.JSONDecodeError as json_e:
                logger.warning(f"Could not validate JSON-LD content within script tag: {json_e}. Raw content: {json_content_str[:200]}...")
                errors.append("JSON-LD content invalid.")
        else:
            errors.append("Missing JSON-LD script block.")
            if "<script" in response_text: logger.warning("Found '<script' but regex failed to match full JSON-LD block.")


        # Extract Article Body (between Meta Description and Source/Script)
        # This regex assumes the body starts immediately after the Meta Description line(s)
        # and ends just before the "Source:" line or the JSON-LD script starts.
        body_match = re.search(
            r"Meta Description:.*?[\r\n]+(##.*?)(?=[\r\n]+\s*Source:|[\r\n]*\s*<script)",
            response_text,
            re.DOTALL | re.IGNORECASE
            )
        if body_match:
             body_content = body_match.group(1).strip()
             # Optional: Further clean potential leftover markers if needed
             body_content = re.sub(r'\s*Source:\s*\[.*?\]\(.*?\)\s*$', '', body_content, flags=re.MULTILINE).strip()
             parsed_data['generated_article_body_md'] = body_content
             if not body_content: errors.append("Extracted Article Body is empty.")
             else: logger.debug(f"Extracted article body length: {len(body_content)} chars.")
        else:
             errors.append("Missing Article Body content.")


        # --- Final Result Determination ---
        # Check for critical failures (missing body)
        if 'generated_article_body_md' not in parsed_data or not parsed_data['generated_article_body_md']:
            final_error_message = f"Critical parsing failure: Missing Article Body. Errors: {'; '.join(errors)}"
            logger.error(final_error_message)
            return None, final_error_message # Return None data

        # If body is present, return parsed data along with any non-critical errors
        if errors:
            error_summary = "; ".join(errors)
            logger.warning(f"SEO Parsing completed with non-critical errors: {error_summary}")
            # Ensure all expected keys exist, even if empty, before returning
            parsed_data.setdefault('generated_title_tag', '')
            parsed_data.setdefault('generated_meta_description', '')
            parsed_data.setdefault('generated_json_ld', '') # Provide empty string if missing
            return parsed_data, error_summary # Return partial data and error string
        else:
            # All parts parsed successfully
            return parsed_data, None # Return data, None for error

    except Exception as e:
        logger.exception(f"Critical unexpected error during SEO response parsing: {e}")
        return None, f"Parsing exception: {e}" # Return None data


# --- Main Agent Function ---
def run_seo_article_agent(article_data):
    """Generates SEO title, description, article body (MD), and JSON-LD script."""
    article_id = article_data.get('id', 'N/A') # For logging

    # --- Input Data Preparation ---
    # Combine primary keyword and generated tags for the prompt context
    primary_keyword = article_data.get('filter_verdict', {}).get('primary_topic_keyword')
    generated_tags = article_data.get('generated_tags', []) # Default to empty list
    all_keywords = ([primary_keyword] if primary_keyword else []) + generated_tags
    all_keywords = [str(k).strip() for k in all_keywords if k and str(k).strip()] # Clean and ensure strings
    all_generated_keywords_json = json.dumps(all_keywords) # Format as JSON array string for the prompt

    # Validate required inputs from previous steps
    required_keys = ['title', 'summary', 'link', 'filter_verdict', 'selected_image_url', 'published_iso']
    missing_keys = [k for k in required_keys if article_data.get(k) is None] # Find missing keys
    if missing_keys:
        error_msg = f"Missing required data for SEO agent (ID: {article_id}). Needs: {missing_keys}"
        logger.error(error_msg)
        article_data['seo_agent_results'] = None # Ensure key exists
        article_data['seo_agent_error'] = error_msg
        return article_data

    if not primary_keyword: # Check specifically for primary keyword
         logger.error(f"Missing primary_topic_keyword from filter_verdict for ID: {article_id}.")
         article_data['seo_agent_results'] = None
         article_data['seo_agent_error'] = "Missing primary keyword"
         return article_data

    # Prepare data dictionary for prompt formatting
    input_data_for_prompt = {
        "article_title": article_data['title'],
        "rss_summary": article_data['summary'],
        "source_article_url": article_data['link'],
        "target_keyword": primary_keyword,
        "article_image_url": article_data['selected_image_url'],
        "author_name": article_data.get('author', 'AI News Team'), # Use default author if needed
        # Ensure date is ISO format, fallback to current date if missing/invalid
        "current_date_iso": article_data.get('published_iso') or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "your_website_name": YOUR_WEBSITE_NAME,
        "your_website_logo_url": YOUR_WEBSITE_LOGO_URL,
        "all_generated_keywords_json": all_generated_keywords_json
    }

    # Final check for any None values in critical inputs (should not happen after initial check, but safety)
    critical_inputs = ['article_title', 'rss_summary', 'source_article_url', 'target_keyword', 'article_image_url', 'current_date_iso', 'all_generated_keywords_json', 'your_website_name']
    if any(input_data_for_prompt.get(k) is None for k in critical_inputs):
         missing = [k for k in critical_inputs if input_data_for_prompt.get(k) is None]
         error_msg = f"Cannot run SEO agent for ID {article_id}, critical derived input data is None: {missing}"
         logger.error(error_msg)
         article_data['seo_agent_results'] = None
         article_data['seo_agent_error'] = error_msg
         return article_data

    # --- API Call and Parsing ---
    try:
        user_prompt = SEO_PROMPT_USER_TEMPLATE.format(**input_data_for_prompt)
    except KeyError as e:
        logger.exception(f"KeyError formatting SEO prompt template for ID {article_id}! Error: {e}")
        article_data['seo_agent_results'] = None
        article_data['seo_agent_error'] = f"Prompt template formatting error: {e}"
        return article_data


    logger.info(f"Running SEO article generator for article ID: {article_id}...")
    raw_response_content = call_deepseek_api(SEO_PROMPT_SYSTEM, user_prompt, max_tokens=MAX_TOKENS_RESPONSE, temperature=TEMPERATURE)

    if not raw_response_content:
        logger.error(f"SEO agent failed to get a response from the API for ID: {article_id}.")
        article_data['seo_agent_results'] = None
        article_data['seo_agent_error'] = "API call failed or returned empty"
        return article_data

    # Log raw response for debugging if needed (especially during development)
    logger.debug(f"Raw SEO Agent Response for ID {article_id}:\n---\n{raw_response_content}\n---")

    parsed_results, error_msg = parse_seo_agent_response(raw_response_content)

    # --- Update article_data with results or errors ---
    article_data['seo_agent_results'] = parsed_results # Will be None if parsing failed critically
    article_data['seo_agent_error'] = error_msg # Will be error string or None

    if parsed_results is None:
        logger.error(f"Failed to parse SEO agent response for ID {article_id}: {error_msg}")
        # Store raw response for debugging if parsing failed critically
        article_data['seo_agent_raw_response'] = raw_response_content
    elif error_msg: # Parsed successfully but with non-critical errors
        logger.warning(f"SEO agent parsing completed with non-critical errors for ID {article_id}: {error_msg}")
    else: # Success
        logger.info(f"Successfully generated and parsed SEO content for ID: {article_id}.")

    return article_data

# --- Standalone Execution (for testing) ---
if __name__ == "__main__":
    # Set higher logging level for testing this script directly
    logging.getLogger().setLevel(logging.DEBUG)
    logger.setLevel(logging.DEBUG)

    # Example article data setup
    test_article_data = {
        'id': 'example-seo-123',
        'title': "DeepSeek Unveils Powerful New Coding Assistant 'CodeSeeker'",
        'summary': "Artificial intelligence research lab DeepSeek AI today announced the release of CodeSeeker, its latest large language model specifically trained for code generation, completion, and explanation across multiple programming languages. Early benchmarks shared by the company suggest CodeSeeker significantly outperforms existing models like GitHub Copilot and Amazon CodeWhisperer on complex coding challenges and bug detection tasks. The model is accessible via a dedicated API starting today.",
        'link': "https://example.com/deepseek-codeseeker-release",
        'filter_verdict': {
            'importance_level': 'Interesting',
            'topic': 'AI Models',
            'reasoning_summary': 'Significant model release from known AI lab with specific performance claims.',
            'primary_topic_keyword': 'DeepSeek CodeSeeker release'
        },
        'selected_image_url': "https://via.placeholder.com/800x500.png?text=CodeSeeker+AI",
        'published_iso': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), # Use Z format
        'generated_tags': ["DeepSeek", "CodeSeeker", "AI Coding Assistant", "Code Generation", "LLM", "API", "Developer Tools", "GitHub Copilot"],
        'author': 'Dev Team Tester'
    }

    logger.info("\n--- Running SEO Agent Standalone Test ---")
    result_data = run_seo_article_agent(test_article_data.copy())

    print("\n--- Final Result Data ---")
    # print(json.dumps(result_data, indent=2)) # Print full result dict

    if result_data and result_data.get('seo_agent_results'):
        print("\n--- Parsed SEO Results ---")
        print(f"Title Tag: {result_data['seo_agent_results'].get('generated_title_tag')}")
        print(f"Meta Desc: {result_data['seo_agent_results'].get('generated_meta_description')}")
        print(f"Body MD Length: {len(result_data['seo_agent_results'].get('generated_article_body_md', ''))} chars")
        print(f"JSON-LD Present: {bool(result_data['seo_agent_results'].get('generated_json_ld'))}")
        if result_data.get('seo_agent_error'):
            print(f"Parsing Warning/Error: {result_data['seo_agent_error']}")
        # print("\nBody Markdown Preview:")
        # print(result_data['seo_agent_results'].get('generated_article_body_md', '')[:500] + "...")
        # print("\nJSON-LD Preview:")
        # print(result_data['seo_agent_results'].get('generated_json_ld', '')[:500] + "...")

    elif result_data and result_data.get('seo_agent_error'):
         print(f"\nSEO Agent FAILED. Error: {result_data.get('seo_agent_error')}")
         if 'seo_agent_raw_response' in result_data:
              print("\n--- Raw Response (Debug) ---")
              print(result_data['seo_agent_raw_response'])
    else:
         print("\nSEO Agent FAILED critically or returned no data.")

    logger.info("\n--- SEO Agent Standalone Test Complete ---")