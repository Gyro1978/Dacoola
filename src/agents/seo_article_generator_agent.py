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
MAX_TOKENS_RESPONSE = 5000
TEMPERATURE = 0.6

# --- Setup Logging ---
# Use root logger configured in main.py if possible, otherwise basic config
logger = logging.getLogger(__name__)
if not logging.getLogger().handlers: # Basic config if no handlers exist
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# --- End Setup Logging ---


# --- *** REVISED SEO Article Prompt *** ---
# Keep SEO_PROMPT_SYSTEM and SEO_PROMPT_USER_TEMPLATE exactly as they were in your last version.
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
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=240) # Increased timeout
        response.raise_for_status()
        result = response.json()
        usage = result.get('usage')
        if usage: logger.debug(f"API Usage: Prompt={usage.get('prompt_tokens')}, Completion={usage.get('completion_tokens')}, Total={usage.get('total_tokens')}")
        if result.get("choices") and len(result["choices"]) > 0:
            message_content = result["choices"][0].get("message", {}).get("content")
            return message_content.strip() if message_content else None
        else: logger.error(f"API response missing 'choices': {result}"); return None
    except requests.exceptions.RequestException as e: logger.error(f"API request failed: {e}"); return None
    except Exception as e: logger.exception(f"Unexpected error during API call: {e}"); return None
# --- End API Call ---

# --- Parsing Function (Improved Robustness) ---
def parse_seo_agent_response(response_text):
    """Parses the structured Markdown response from the SEO agent."""
    parsed_data = {}
    errors = []
    if not response_text or response_text.strip().startswith("Error:"):
        logger.error(f"SEO Agent returned error or empty response: {response_text}")
        return None, response_text or "Empty response"

    try:
        # Extract Title Tag
        title_match = re.search(r"^Title Tag:\s*(.*)", response_text, re.MULTILINE)
        if title_match:
            parsed_data['generated_title_tag'] = title_match.group(1).strip()
            if len(parsed_data['generated_title_tag']) > 65: # Check length slightly more generously
                 logger.warning(f"Generated title tag exceeds 60 chars: '{parsed_data['generated_title_tag']}'")
        else: errors.append("No 'Title Tag:'")

        # Extract Meta Description
        meta_match = re.search(r"^Meta Description:\s*(.*)", response_text, re.MULTILINE)
        if meta_match:
            parsed_data['generated_meta_description'] = meta_match.group(1).strip()
            if len(parsed_data['generated_meta_description']) > 165: # Check length slightly more generously
                 logger.warning(f"Generated meta description exceeds 160 chars: '{parsed_data['generated_meta_description']}'")
        else: errors.append("No 'Meta Description:'")

        # --- Extract JSON-LD Script Block (More Flexible Regex) ---
        script_match = re.search(
            r'(<script\s+type\s*=\s*["\']application/ld\+json["\']\s*>\s*\{.*?\s*\}\s*<\/script>)',
            response_text,
            re.DOTALL | re.IGNORECASE
        )
        if script_match:
            parsed_data['generated_json_ld'] = script_match.group(1).strip()
            # Optional validation (keep as before)
            try:
                inner_json_str = script_match.group(1).split('>', 1)[1].rsplit('<', 1)[0]
                json_ld_data = json.loads(inner_json_str)
                # Add checks if needed
            except Exception as json_e: logger.warning(f"Cannot validate JSON-LD content: {json_e}")
        else:
            errors.append("No JSON-LD script block.")
            # Try to find where it *might* have been cut off
            if "<script" in response_text:
                 logger.warning("Found '<script' tag but regex failed to match full JSON-LD block. Response might be truncated or malformed.")
            else:
                 logger.warning("Did not find '<script' tag start for JSON-LD block.")


        # --- Extract Article Body ---
        # Look for content between Meta Description and Source link more robustly
        # Allow for varying newlines and potentially the JSON-LD appearing before Source
        body_match = re.search(
            r"Meta Description:.*?[\r\n]+(##.*?)(?:[\r\n]+\s*Source:|<script)",
            response_text,
            re.DOTALL | re.IGNORECASE
            )
        if body_match:
             body_content = body_match.group(1).strip()
             # Remove trailing Source line if accidentally captured
             body_content = re.sub(r'\s*Source:\s*\[.*?\]\(.*?\)\s*$', '', body_content, flags=re.MULTILINE).strip()
             parsed_data['generated_article_body_md'] = body_content
             logger.debug(f"Extracted article body length: {len(body_content)} chars")
        else:
             errors.append("Cannot reliably extract Article Body.")


        # --- Final Error Check and Return ---
        if errors:
            logger.error(f"SEO Parsing errors: {'; '.join(errors)}")
            # Check if critical components (body) are missing
            if 'generated_article_body_md' not in parsed_data:
                 return None, f"Critical parsing failure: Missing Article Body. Errors: {'; '.join(errors)}"
            # If body is present, but JSON-LD is missing, log warning but return results
            elif 'No JSON-LD script block.' in errors:
                 logger.warning("JSON-LD block missing, but returning other parsed data.")
                 parsed_data['generated_json_ld'] = '' # Provide empty string
                 # Return the partial data, but signal the specific error
                 return parsed_data, "Missing JSON-LD script block"
            # Else, some other non-critical error occurred, but body is present
            else:
                 # Treat other missing parts (like title/meta) as non-critical for now if body exists
                 logger.warning(f"Non-critical parsing errors encountered: {'; '.join(errors)}. Returning partial data.")
                 # Ensure missing keys exist
                 parsed_data.setdefault('generated_title_tag', '')
                 parsed_data.setdefault('generated_meta_description', '')
                 parsed_data.setdefault('generated_json_ld', '')
                 return parsed_data, "; ".join(errors) # Return combined non-critical errors


        # If we reach here, no errors were recorded
        # Final check to ensure essential parts are present before declaring success
        if 'generated_article_body_md' not in parsed_data or 'generated_json_ld' not in parsed_data:
             logger.error("Inconsistent parsing state: No errors logged, but critical data missing.")
             return None, "Inconsistent parsing state"

        return parsed_data, None # Success

    except Exception as e:
        logger.exception(f"Critical error during SEO response parsing: {e}")
        return None, f"Parsing exception: {e}"


def run_seo_article_agent(article_data):
    """Generates the SEO brief, aiming for longer content."""
    all_keywords = [article_data.get('filter_verdict', {}).get('primary_topic_keyword')] + article_data.get('generated_tags', [])
    all_keywords = [str(k) for k in all_keywords if k] # Ensure all are strings, remove None/empty
    # Ensure the result is a valid JSON list representation
    all_generated_keywords_json = json.dumps(all_keywords) # Pass as JSON list string

    required_keys = ['title', 'summary', 'link', 'filter_verdict', 'selected_image_url', 'published_iso']
    if not article_data or not all(k in article_data and article_data[k] is not None for k in required_keys):
        missing_keys = [k for k in required_keys if not (k in article_data and article_data[k] is not None)]
        logger.error(f"Missing required data for SEO agent. Needs: {missing_keys}")
        article_data['seo_agent_error'] = f"Missing required input: {missing_keys}"
        return article_data

    if not article_data['filter_verdict'] or not article_data['filter_verdict'].get('primary_topic_keyword'):
         logger.error("Missing primary_topic_keyword from filter_verdict.")
         article_data['seo_agent_error'] = "Missing primary keyword"
         return article_data

    input_data = {
        "article_title": article_data.get('title'),
        "rss_summary": article_data.get('summary'),
        "source_article_url": article_data.get('link'),
        "target_keyword": article_data['filter_verdict'].get('primary_topic_keyword'),
        "article_image_url": article_data.get('selected_image_url'),
        "author_name": article_data.get('author', 'AI News Team'),
        "current_date_iso": article_data.get('published_iso', datetime.now(timezone.utc).date().isoformat()),
        "your_website_name": YOUR_WEBSITE_NAME,
        "your_website_logo_url": YOUR_WEBSITE_LOGO_URL,
        "all_generated_keywords_json": all_generated_keywords_json # Corrected variable name
    }

    critical_inputs = ['article_title', 'rss_summary', 'source_article_url', 'target_keyword', 'article_image_url', 'current_date_iso', 'all_generated_keywords_json']
    if any(input_data[k] is None for k in critical_inputs):
         missing = [k for k in critical_inputs if input_data[k] is None]
         logger.error(f"Cannot run SEO agent, critical input data is None: {missing}")
         article_data['seo_agent_error'] = f"Missing critical input: {missing}"
         return article_data

    user_prompt = SEO_PROMPT_USER_TEMPLATE.format(**input_data)

    logger.info(f"Running SEO article generator for article ID: {article_data.get('id', 'N/A')}...")
    raw_response_content = call_deepseek_api(SEO_PROMPT_SYSTEM, user_prompt, max_tokens=MAX_TOKENS_RESPONSE, temperature=TEMPERATURE)

    if not raw_response_content:
        logger.error("SEO agent failed to get a response from the API.")
        article_data['seo_agent_results'] = None
        article_data['seo_agent_error'] = "API call failed"
        return article_data

    # --- Log Raw Output for Debugging ---
    logger.debug(f"Raw SEO Agent Response for {article_data.get('id', 'N/A')}:\n---\n{raw_response_content}\n---")
    # ------------------------------------

    parsed_results, error_msg = parse_seo_agent_response(raw_response_content)

    # Check if parsing completely failed (returned None for results)
    if parsed_results is None:
        logger.error(f"Failed to parse SEO agent response: {error_msg}")
        article_data['seo_agent_results'] = None
        article_data['seo_agent_error'] = f"Parsing failed: {error_msg}"
        # Store raw response for debug if None results
        article_data['seo_agent_raw_response'] = raw_response_content
    else:
        # Parsing succeeded, results are available (even if JSON-LD was missing)
        logger.info(f"Successfully parsed SEO content for {article_data.get('id', 'N/A')}.")
        article_data['seo_agent_results'] = parsed_results
        # Record the specific error if one occurred (like missing JSON-LD), otherwise clear error
        article_data['seo_agent_error'] = error_msg if error_msg else None
        if error_msg == "Missing JSON-LD script block":
             logger.warning(f"Proceeding without JSON-LD for {article_data.get('id', 'N/A')}")


    return article_data

# --- Example Usage (keep as before) ---
if __name__ == "__main__":
    # Example article data setup (replace with actual data structure)
    test_article_data = {
        'id': 'example-123',
        'title': "DeepSeek Releases New Code Model",
        'summary': "DeepSeek AI announced the release of its latest coding model, claiming improved performance on complex benchmarks and natural language understanding for code generation tasks. The model is available via API.",
        'link': "https://example.com/deepseek-code-release",
        'filter_verdict': {
            'importance_level': 'Interesting',
            'topic': 'AI Models',
            'primary_topic_keyword': 'DeepSeek code model'
        },
        'selected_image_url': "https://via.placeholder.com/600x400.png?text=DeepSeek+Code",
        'published_iso': datetime.now(timezone.utc).isoformat(),
        'generated_tags': ["DeepSeek", "AI Coding Model", "Code Generation", "LLM", "API"],
        'author': 'Test Author'
    }

    logger.info("\n--- Running SEO Agent Test ---")
    result_data = run_seo_article_agent(test_article_data.copy())

    if result_data and result_data.get('seo_agent_results'):
        print("\n--- Parsed SEO Results ---")
        print(f"Title Tag: {result_data['seo_agent_results'].get('generated_title_tag')}")
        print(f"Meta Desc: {result_data['seo_agent_results'].get('generated_meta_description')}")
        print(f"Body MD Length: {len(result_data['seo_agent_results'].get('generated_article_body_md', ''))}")
        print(f"JSON-LD Present: {bool(result_data['seo_agent_results'].get('generated_json_ld'))}")
        if result_data.get('seo_agent_error'):
            print(f"Parsing Warning/Error: {result_data['seo_agent_error']}")
        # print("\nBody Markdown Preview:")
        # print(result_data['seo_agent_results'].get('generated_article_body_md', '')[:500] + "...")
        # print("\nJSON-LD Preview:")
        # print(result_data['seo_agent_results'].get('generated_json_ld', '')[:500] + "...")

    elif result_data:
         print(f"\nSEO Agent FAILED. Error: {result_data.get('seo_agent_error')}")
         if 'seo_agent_raw_response' in result_data:
              print("\n--- Raw Response (Debug) ---")
              print(result_data['seo_agent_raw_response'])
    else:
         print("\nSEO Agent FAILED critically.")

    logger.info("--- SEO Agent Test Complete ---")