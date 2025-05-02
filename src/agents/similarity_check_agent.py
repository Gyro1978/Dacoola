# src/agents/similarity_check_agent.py

import os
import sys # Added sys for path check below
import requests
import json
import logging
from dotenv import load_dotenv
from datetime import datetime, timezone # Keep timezone import (though not directly used here)

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
MAX_TOKENS_RESPONSE = 100  # Expecting short JSON response + reasoning
TEMPERATURE = 0.0          # Max determinism for YES/NO check
MAX_RECENT_ARTICLES_TO_COMPARE = 15  # How many past articles to check against
MAX_CHARS_PER_RECENT_SUMMARY = 300  # Limit length of summaries sent to API

# --- Similarity Check Prompt ---
SIMILARITY_CHECK_SYSTEM_PROMPT = """
You are an expert News Deduplication Analyst AI. Your task is to determine if a **New Candidate Article** reports on the **exact same core event, announcement, or specific update** as any *single* article within a provided list of **Recently Published Articles**. Focus *only* on whether the central news item is identical, not just related topics or shared keywords. Be extremely precise and conservative; only flag as a duplicate if the core news is fundamentally the same.

**Crucial Distinction:**
- **Duplicate:** Reports the *same specific action/event* (e.g., both report OpenAI launching Model X *today*, both report CEO Y resigning *due to reason Z*).
- **NOT Duplicate:** Related follow-up, different angle on same broad topic, similar tech but different news event (e.g., one article on GPT-4o launch, another on GPT-4o sycophancy; one on AI regulation bill introduction, another on its passage).

Output MUST be ONLY the JSON object specified below. NO explanations outside the JSON.
"""

SIMILARITY_CHECK_USER_TEMPLATE = """
Task: Compare the **New Candidate Article** against each **Recently Published Article**. Determine if the *core news event* reported in the New Candidate Article is substantively identical to the core news event reported in *any single one* of the Recently Published Articles.

**New Candidate Article:**
Title: {new_article_title}
Summary: {new_article_summary}

**Recently Published Articles (Titles & Summaries):**
{recent_articles_formatted_list}

**Analysis Steps (Internal - Do NOT output):**
1. Identify the single, specific core event/announcement in the New Candidate Article.
2. For each Recently Published Article, identify its single, specific core event/announcement.
3. Compare the core event of the New Candidate to EACH recent core event. Is there an exact match in substance (the specific news)?
4. If an exact match is found with *any* single recent article, conclude it's a duplicate. Otherwise, it's not.

**Final Output (Strict JSON format ONLY):**
Provide ONLY the following valid JSON object.

{{
  "is_semantic_duplicate": boolean,  // true ONLY if the core news event is IDENTICAL to any single recent article, false otherwise.
  "reasoning": "string"  // Brief explanation (1 sentence) justifying the true/false decision
}}
"""

# --- API Call Function ---
def call_deepseek_api(system_prompt, user_prompt, max_tokens=MAX_TOKENS_RESPONSE, temperature=TEMPERATURE):
    """Calls the DeepSeek API and returns the cleaned JSON content string."""
    # (Keeping this function duplicated for now, but could be moved to a util file)
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
        logger.debug(f"Sending similarity check request to DeepSeek API (model: {AGENT_MODEL})...")
        # Increased timeout for potentially longer comparison context
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=90)
        response.raise_for_status()
        result = response.json()
        logger.debug(f"Raw API Response received (Similarity Agent).")

        if result.get("choices") and len(result["choices"]) > 0:
            message_content = result["choices"][0].get("message", {}).get("content")
            if message_content:
                # Clean potential markdown code fences
                content_stripped = message_content.strip()
                if content_stripped.startswith("```json"):
                    message_content = content_stripped[7:-3].strip()
                elif content_stripped.startswith("```"):
                    message_content = content_stripped[3:-3].strip()
                return message_content
            else:
                logger.error("API response successful, but no message content found.")
                return None
        else:
            logger.error(f"API response missing 'choices' or choices empty: {result}")
            return None

    except requests.exceptions.Timeout:
         logger.error(f"API request timed out after 90 seconds.")
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

# --- Helper Function ---
def format_recent_articles_for_prompt(recent_articles_data):
    """Formats the list of recent articles for the prompt, limiting count and summary length."""
    formatted_list = []
    # Take the most recent N articles based on config
    articles_to_format = recent_articles_data[:MAX_RECENT_ARTICLES_TO_COMPARE]

    for i, article in enumerate(articles_to_format):
        # Ensure article is a dict and has a title before processing
        if not isinstance(article, dict) or not article.get('title'):
            logger.warning(f"Skipping invalid recent article entry in context: {article}")
            continue

        title = article['title']
        # Prefer short summary if available, otherwise use full summary (truncated)
        summary = article.get('summary_short', article.get('summary', ''))
        # Truncate summary to configured length
        summary = summary[:MAX_CHARS_PER_RECENT_SUMMARY] + ('...' if len(summary) > MAX_CHARS_PER_RECENT_SUMMARY else '')
        formatted_list.append(f"{i+1}. Title: {title}\n   Summary: {summary}") # Indent summary slightly

    return "\n\n".join(formatted_list) if formatted_list else "None provided." # Add space between entries


# --- Main Agent Function ---
def run_similarity_check_agent(new_article_data, recent_articles_data):
    """
    Compares a new article against recent articles to detect semantic duplicates.

    Args:
        new_article_data (dict): Dict containing 'title' and 'summary' of the new article.
        recent_articles_data (list): List of dicts, each with 'title' and 'summary'/'summary_short'.

    Returns:
        dict: Parsed JSON verdict {'is_semantic_duplicate': bool, 'reasoning': str} or None if error.
              Returns default False if no recent articles are provided.
    """
    # Validate input
    if not isinstance(new_article_data, dict) or not new_article_data.get('title') or not new_article_data.get('summary'):
        logger.error("Invalid or incomplete new_article_data provided to similarity agent.")
        return None # Indicate failure
    if recent_articles_data is None: # Handle None case, allow empty list
        logger.warning("recent_articles_data is None, treating as empty list.")
        recent_articles_data = []
    if not isinstance(recent_articles_data, list):
        logger.error("Invalid recent_articles_data: expected a list.")
        return None # Indicate failure

    new_title = new_article_data['title']
    new_summary = new_article_data['summary']
    article_id = new_article_data.get('id', 'N/A') # For logging

    # Truncate new summary if excessively long
    if len(new_summary) > 1000:
        logger.warning(f"Truncating new article summary (> 1000 chars) for similarity check (ID: {article_id})")
        new_summary = new_summary[:1000] + "..."

    # Handle the case where there are no recent articles to compare against
    if not recent_articles_data:
        logger.info(f"No recent articles provided for comparison for article ID: {article_id}. Assuming not a duplicate.")
        return {"is_semantic_duplicate": False, "reasoning": "No recent articles to compare against."}

    # Format context for the prompt
    recent_formatted = format_recent_articles_for_prompt(recent_articles_data)

    try:
        user_prompt = SIMILARITY_CHECK_USER_TEMPLATE.format(
            new_article_title=new_title,
            new_article_summary=new_summary,
            recent_articles_formatted_list=recent_formatted
        )
    except KeyError as e:
        logger.exception(f"CRITICAL KeyError formatting similarity prompt! Error: {e}")
        return None # Indicate failure

    logger.info(f"Running similarity check for article ID: {article_id} Title: {new_title[:60]}...")
    raw_response_content = call_deepseek_api(SIMILARITY_CHECK_SYSTEM_PROMPT, user_prompt)

    if not raw_response_content:
        logger.error(f"Similarity agent failed to get a valid response from the API for ID: {article_id}.")
        return None # Indicate failure

    # Parse and Validate the JSON response
    try:
        similarity_verdict = json.loads(raw_response_content)
        required_keys = ["is_semantic_duplicate", "reasoning"]
        # Check structure and types
        if not isinstance(similarity_verdict, dict) \
           or not all(k in similarity_verdict for k in required_keys) \
           or not isinstance(similarity_verdict.get("is_semantic_duplicate"), bool) \
           or not isinstance(similarity_verdict.get("reasoning"), str):
            logger.error(f"Parsed similarity verdict JSON has missing keys, wrong format, or wrong types for ID {article_id}: {similarity_verdict}")
            raise ValueError("Invalid format or missing keys/types in similarity verdict JSON")

        logger.info(f"Similarity check result for ID {article_id}: is_duplicate={similarity_verdict['is_semantic_duplicate']}. Reason: {similarity_verdict['reasoning']}")
        return similarity_verdict

    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON response from similarity agent for ID {article_id}: {raw_response_content}")
        return None # Indicate failure
    except ValueError as ve:
        logger.error(f"Validation error on parsed similarity JSON for ID {article_id}: {ve}")
        return None # Indicate failure
    except Exception as e:
        logger.exception(f"An unexpected error occurred processing similarity response for ID {article_id}: {e}")
        return None # Indicate failure

# --- Standalone Execution (for testing) ---
if __name__ == "__main__":
    # Set higher logging level for testing this script directly
    logging.getLogger().setLevel(logging.DEBUG)
    logger.setLevel(logging.DEBUG)

    # Sample recent articles
    sample_recent = [
        {'id': 'a1', 'title': "OpenAI Addresses GPT-4o Sycophancy Issue", 'summary_short': "OpenAI explains issues with GPT-4o being too agreeable after user feedback."},
        {'id': 'b2', 'title': "Meta Launches Llama 3.1 - New Capabilities", 'summary_short': "Meta AI releases Llama 3.1 model with enhanced coding and reasoning skills."},
        {'id': 'c3', 'title': "Google DeepMind Presents AlphaFold 3", 'summary_short': "DeepMind's new AlphaFold model predicts structures of proteins, DNA, RNA."}
    ]
    # New article candidates
    new_duplicate = {'id': 'd4', 'title': "ChatGPT Sycophancy Problem Explained by OpenAI", 'summary': "Following user complaints about ChatGPT giving overly positive responses after the GPT-4o integration, OpenAI released a statement explaining the sycophancy tendency and their mitigation efforts."}
    new_not_duplicate = {'id': 'e5', 'title': "OpenAI Previews GPT-5 Multimodal Features", 'summary': "OpenAI offered a sneak peek at potential GPT-5 capabilities, demonstrating advanced video and audio understanding in internal demos."}
    new_unrelated = {'id': 'f6', 'title': "Apple Announces New M4 Chip Details", 'summary': "Apple shared technical specifications for its upcoming M4 processor, highlighting performance gains for MacBooks."}

    logger.info("\n--- Running Similarity Check Agent Standalone Test ---")

    logger.info("\nTesting DUPLICATE article...")
    result1 = run_similarity_check_agent(new_duplicate, sample_recent)
    print("Result (Duplicate):", json.dumps(result1, indent=2) if result1 else "FAILED")

    logger.info("\nTesting RELATED BUT DISTINCT article...")
    result2 = run_similarity_check_agent(new_not_duplicate, sample_recent)
    print("Result (Distinct):", json.dumps(result2, indent=2) if result2 else "FAILED")

    logger.info("\nTesting UNRELATED article...")
    result3 = run_similarity_check_agent(new_unrelated, sample_recent)
    print("Result (Unrelated):", json.dumps(result3, indent=2) if result3 else "FAILED")

    logger.info("\nTesting with NO RECENT articles...")
    result4 = run_similarity_check_agent(new_unrelated, []) # Empty list
    print("Result (No Recent):", json.dumps(result4, indent=2) if result4 else "FAILED")

    logger.info("\n--- Similarity Check Agent Standalone Test Complete ---")