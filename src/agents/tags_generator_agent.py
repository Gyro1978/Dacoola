# src/agents/tags_generator_agent.py

import os
import sys # Added sys for path check below
import requests
import json
import logging
from dotenv import load_dotenv
# from datetime import datetime, timezone # Not directly used here

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

# --- Configuration ---
AGENT_MODEL = "deepseek-chat"
MAX_TOKENS_RESPONSE = 150 # Expecting a relatively short list of tags
TEMPERATURE = 0.2         # Lower temperature for more focused/relevant tags
API_TIMEOUT_SECONDS = 60  # Standard timeout should be fine

# --- Tags Generator Prompt ---
TAGS_PROMPT_SYSTEM = """
You are an expert AI SEO Analyst and Taxonomist, powered by DeepSeek. Your core function is to meticulously analyze the provided article text to identify the most salient entities, concepts, themes, and related topics that are highly relevant for search engine optimization (SEO) and content discovery. You must distill the essence of the article into a concise list of 5-10 SEO-appropriate tags. Your output must be strictly a valid JSON array of strings, containing NO other text, explanations, or formatting.
"""

TAGS_PROMPT_USER_TEMPLATE = """
Task: Read the following article text thoroughly. Generate a list of 5-10 highly relevant SEO tags (related topics) that accurately represent the main subjects and key themes discussed.

Internal Analysis Process (Simulated):
1. Identify Core Subject(s).
2. Extract Key Entities (Companies, Products, People, Tech).
3. Determine Underlying Themes (Ethics, Competition, Impact, Trends).
4. Select 5-10 SEO-Relevant Tags: Specific, descriptive, include key entities/concepts, reflect core themes, user search intent. Avoid overly generic tags unless essential (e.g., "Artificial Intelligence" might be okay if the article is very broad, but prefer specifics like "Large Language Models" or "Computer Vision"). Prefer phrases over single words where appropriate (e.g., "AI Regulation" instead of just "Regulation").

Input Article Text:
{full_article_text}

Required Output Format (Strict JSON Array ONLY):
Output only a valid JSON array containing 5-10 generated string tags. Do not include any text before or after the JSON array.
Example: ["AI Model Release", "OpenAI", "GPT-5 Speculation", "Large Language Models", "AI Safety Concerns", "AI Ethics", "Tech Industry Trends"]

(Error Handling): If the input text is clearly insufficient (e.g., less than ~50 words), output only the following exact JSON array: ["Error: Input text missing or insufficient"]
"""

# --- API Call Function ---
# (Assume call_deepseek_api is defined similarly to other agents or imported)
# (Keeping this function duplicated for now)
def call_deepseek_api(system_prompt, user_prompt, max_tokens=MAX_TOKENS_RESPONSE, temperature=TEMPERATURE):
    """Calls the DeepSeek API and returns the cleaned JSON content string."""
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
        logger.debug(f"Sending tags generation request (model: {AGENT_MODEL}).")
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=API_TIMEOUT_SECONDS)
        response.raise_for_status()
        result = response.json()
        logger.debug("Raw API Response received (Tags Agent).")

        if result.get("choices") and len(result["choices"]) > 0:
            message_content = result["choices"][0].get("message", {}).get("content")
            if message_content:
                # Clean potential markdown ```json ... ``` markers
                content_stripped = message_content.strip()
                if content_stripped.startswith("```json"):
                    message_content = content_stripped[7:-3].strip()
                elif content_stripped.startswith("```"):
                    message_content = content_stripped[3:-3].strip()
                return message_content.strip()
            else:
                logger.error("API response successful, but no message content found.")
                return None
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
        logger.exception(f"An unexpected error occurred during API call: {e}")
        return None

# --- Main Agent Function ---
def run_tags_generator_agent(article_data):
    """
    Generates SEO tags based on the article body markdown.

    Args:
        article_data (dict): Dictionary containing processed article info,
                             must include ['seo_agent_results']['generated_article_body_md'].

    Returns:
        dict: The updated article_data dictionary with 'generated_tags' list
              and potentially 'tags_agent_error' string.
    """
    article_id = article_data.get('id', 'N/A') # For logging

    # --- Input Validation ---
    if not isinstance(article_data, dict):
         logger.error(f"Invalid input: article_data is not a dictionary for ID {article_id}.")
         # Cannot update article_data if it's not a dict
         return article_data # Or handle error differently

    seo_results = article_data.get('seo_agent_results')
    article_body_md = seo_results.get('generated_article_body_md') if isinstance(seo_results, dict) else None

    if not article_body_md:
        error_msg = "Missing 'generated_article_body_md' for tags agent."
        logger.error(f"{error_msg} (ID: {article_id})")
        article_data['generated_tags'] = [] # Ensure key exists, empty list
        article_data['tags_agent_error'] = error_msg
        return article_data

    # Check for minimum content length to avoid pointless API calls
    min_body_length = 50
    if len(article_body_md) < min_body_length:
         warning_msg = f"Article body too short ({len(article_body_md)} < {min_body_length} chars) for meaningful tag generation. Skipping tags agent."
         logger.warning(f"{warning_msg} (ID: {article_id})")
         article_data['generated_tags'] = [] # Return empty list for short content
         article_data['tags_agent_error'] = "Input text too short"
         return article_data

    # --- API Call ---
    try:
        user_prompt = TAGS_PROMPT_USER_TEMPLATE.format(full_article_text=article_body_md)
    except KeyError as e:
        logger.exception(f"KeyError formatting tags prompt template for ID {article_id}! Error: {e}")
        article_data['generated_tags'] = None # Indicate failure state
        article_data['tags_agent_error'] = f"Prompt template formatting error: {e}"
        return article_data

    logger.info(f"Running tags generator agent for article ID: {article_id}...")
    raw_response_content = call_deepseek_api(TAGS_PROMPT_SYSTEM, user_prompt)

    if not raw_response_content:
        logger.error(f"Tags agent failed to get a response from the API for ID: {article_id}.")
        article_data['generated_tags'] = None # Indicate failure state
        article_data['tags_agent_error'] = "API call failed or returned empty"
        return article_data

    # --- Response Parsing and Validation ---
    try:
        generated_tags = json.loads(raw_response_content)

        # Validate response type and check for explicit error message from prompt
        if isinstance(generated_tags, list):
             if generated_tags == ["Error: Input text missing or insufficient"]:
                  logger.error(f"Tags agent returned error message (insufficient input) for ID: {article_id}.")
                  article_data['generated_tags'] = [] # Treat as empty list
                  article_data['tags_agent_error'] = "Agent reported insufficient input"
             else:
                  # Filter out non-strings or empty strings, ensure clean tags
                  cleaned_tags = [str(tag).strip() for tag in generated_tags if isinstance(tag, str) and str(tag).strip()]
                  logger.info(f"Successfully generated {len(cleaned_tags)} tags for article ID: {article_id}")
                  article_data['generated_tags'] = cleaned_tags
                  article_data['tags_agent_error'] = None # Clear previous error on success
        else:
             # If the response wasn't a list as expected
             logger.error(f"Tags agent response was not a JSON list for ID {article_id}: {raw_response_content}")
             raise ValueError("Response is not a JSON list.")

        return article_data

    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON response from tags agent for ID {article_id}: {raw_response_content}")
        article_data['generated_tags'] = None # Indicate failure state
        article_data['tags_agent_error'] = "Invalid JSON response from API"
        return article_data
    except ValueError as ve: # Catch explicit validation errors
         logger.error(f"Validation error on tags response for ID {article_id}: {ve}")
         article_data['generated_tags'] = None
         article_data['tags_agent_error'] = str(ve)
         return article_data
    except Exception as e: # Catch any other unexpected errors
        logger.exception(f"An unexpected error occurred processing tags response for ID {article_id}: {e}")
        article_data['generated_tags'] = None
        article_data['tags_agent_error'] = "Unexpected processing error"
        return article_data

# --- Standalone Execution (for testing) ---
if __name__ == "__main__":
    # Set higher logging level for testing this script directly
    logging.getLogger().setLevel(logging.DEBUG)
    logger.setLevel(logging.DEBUG)

    # Example data AFTER SEO agent has run
    test_article_data_good = {
        'id': 'test-tags-good-001',
        'seo_agent_results': {
            'generated_article_body_md': """## OpenAI Unveils GPT-5 Model with Advanced Reasoning

OpenAI today announced the much-anticipated **OpenAI GPT-5 release**, its next-generation large language model. The company highlights significant progress in logical reasoning and complex problem-solving abilities compared to GPT-4.

Early benchmarks shared internally indicate GPT-5 surpasses existing models, including Google's Gemini and Anthropic's Claude 3, on various demanding tasks like advanced mathematics and scientific literature analysis. This represents a major step forward in artificial intelligence capabilities, potentially impacting fields from software development to drug discovery.

Further details on public availability, API access, and pricing are expected in the coming weeks. Concerns about AI safety and potential misuse were briefly addressed, with OpenAI stating enhanced safety protocols are built into the model's architecture. The focus remains on responsible deployment.
""",
            # other seo_agent_results fields...
        }
    }
    test_article_data_short = {
         'id': 'test-tags-short-002',
         'seo_agent_results': { 'generated_article_body_md': "## Short News\n\nSomething happened."}
    }
    test_article_data_missing = { 'id': 'test-tags-missing-003', 'seo_agent_results': {}}


    logger.info("\n--- Running Tags Generator Agent Standalone Test ---")

    logger.info("\nTesting GOOD article body...")
    result_good = run_tags_generator_agent(test_article_data_good.copy())
    print("Result (Good):", json.dumps(result_good.get('generated_tags', 'ERROR'), indent=2))
    if result_good.get('tags_agent_error'): print(f"Error: {result_good['tags_agent_error']}")

    logger.info("\nTesting SHORT article body...")
    result_short = run_tags_generator_agent(test_article_data_short.copy())
    print("Result (Short):", json.dumps(result_short.get('generated_tags', 'ERROR'), indent=2))
    if result_short.get('tags_agent_error'): print(f"Error: {result_short['tags_agent_error']}")

    logger.info("\nTesting MISSING article body...")
    result_missing = run_tags_generator_agent(test_article_data_missing.copy())
    print("Result (Missing):", json.dumps(result_missing.get('generated_tags', 'ERROR'), indent=2))
    if result_missing.get('tags_agent_error'): print(f"Error: {result_missing['tags_agent_error']}")


    logger.info("\n--- Tags Generator Agent Standalone Test Complete ---")