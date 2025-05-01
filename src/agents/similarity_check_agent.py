# src/agents/similarity_check_agent.py

import os
import requests
import json
import logging
from dotenv import load_dotenv
from datetime import datetime, timezone

# --- Load Environment Variables ---
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '..', '.env'))
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"

# --- Configuration ---
AGENT_MODEL = "deepseek-chat"
MAX_TOKENS_RESPONSE = 100  # Expecting short JSON response + reasoning
TEMPERATURE = 0.0          # Max determinism for YES/NO check
MAX_RECENT_ARTICLES_TO_COMPARE = 15  # Limit context size
MAX_CHARS_PER_RECENT_SUMMARY = 300  # Limit length of each comparison item

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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

def call_deepseek_api(system_prompt, user_prompt, max_tokens=MAX_TOKENS_RESPONSE, temperature=TEMPERATURE):
    """Calls the DeepSeek API."""
    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY not found.")
        return None

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
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
        logger.debug("Sending similarity check request to DeepSeek API...")
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=90)
        response.raise_for_status()
        result = response.json()

        if result.get("choices") and len(result["choices"]) > 0:
            message_content = result["choices"][0].get("message", {}).get("content")
            if message_content:
                content_stripped = message_content.strip()
                if content_stripped.startswith("```json"):
                    message_content = content_stripped[7:-3].strip()
                elif content_stripped.startswith("```"):
                    message_content = content_stripped[3:-3].strip()
                return message_content
            else:
                logger.error("No message content.")
                return None
        else:
            logger.error(f"No choices structure: {result}")
            return None

    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed: {e}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode JSON: {e}")
        raw_text = response.text if response else "N/A"
        logger.error(f"Response text: {raw_text[:500]}")
        return None
    except Exception as e:
        logger.exception(f"API call error: {e}")
        return None

def format_recent_articles_for_prompt(recent_articles_data):
    """Formats the list of recent articles for the prompt, limiting length."""
    formatted_list = []
    # Take the most recent N articles
    for i, article in enumerate(recent_articles_data[:MAX_RECENT_ARTICLES_TO_COMPARE]):
        title = article.get('title', 'No Title')
        summary = article.get('summary_short', article.get('summary', ''))  # Prefer short summary if available
        # Truncate summary
        summary = summary[:MAX_CHARS_PER_RECENT_SUMMARY] + ('...' if len(summary) > MAX_CHARS_PER_RECENT_SUMMARY else '')
        formatted_list.append(f"{i+1}. Title: {title}\n Summary: {summary}")
    return "\n".join(formatted_list) if formatted_list else "None provided."

def run_similarity_check_agent(new_article_data, recent_articles_data):
    """
    Compares a new article against recent articles to detect semantic duplicates.

    Args:
        new_article_data (dict): Dict containing 'title' and 'summary' of the new article.
        recent_articles_data (list): List of dicts, each containing 'title' and 'summary'/'summary_short'
                                   of recently published articles.

    Returns:
        dict: Parsed JSON verdict {'is_semantic_duplicate': bool, 'reasoning': str} or None if error.
    """
    if not new_article_data or 'title' not in new_article_data or 'summary' not in new_article_data:
        logger.error("Invalid new_article_data provided to similarity agent.")
        return None
    if recent_articles_data is None:  # Allow empty list, but not None
        recent_articles_data = []

    new_title = new_article_data.get('title')
    new_summary = new_article_data.get('summary')

    # Truncate new summary if excessively long
    if len(new_summary) > 1000:  # Apply a limit here too
        new_summary = new_summary[:1000] + "..."

    recent_formatted = format_recent_articles_for_prompt(recent_articles_data)

    # Check if there are even any recent articles to compare against
    if not recent_articles_data:
        logger.info("No recent articles provided for comparison. Assuming not a duplicate.")
        return {"is_semantic_duplicate": False, "reasoning": "No recent articles to compare against."}

    try:
        user_prompt = SIMILARITY_CHECK_USER_TEMPLATE.format(
            new_article_title=new_title,
            new_article_summary=new_summary,
            recent_articles_formatted_list=recent_formatted
        )
    except KeyError as e:
        logger.exception(f"CRITICAL KeyError formatting similarity prompt! Error: {e}")
        return None

    logger.info(f"Running similarity check for article: {new_title[:60]}...")
    raw_response_content = call_deepseek_api(SIMILARITY_CHECK_SYSTEM_PROMPT, user_prompt)

    if not raw_response_content:
        logger.error("Similarity agent failed to get a response from the API.")
        return None

    try:
        similarity_verdict = json.loads(raw_response_content)
        required_keys = ["is_semantic_duplicate", "reasoning"]
        if not isinstance(similarity_verdict, dict) or not all(k in similarity_verdict for k in required_keys):
            logger.error(f"Parsed similarity verdict JSON is missing keys or wrong format: {similarity_verdict}")
            raise ValueError("Missing keys or wrong format in similarity verdict JSON")

        logger.info(f"Similarity check result: is_duplicate={similarity_verdict['is_semantic_duplicate']}. Reason: {similarity_verdict['reasoning']}")
        return similarity_verdict

    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON response from similarity agent: {raw_response_content}")
        return None
    except ValueError as ve:
        logger.error(f"Validation error on parsed similarity JSON: {ve}")
        return None
    except Exception as e:
        logger.exception(f"An unexpected error occurred processing similarity response: {e}")
        return None


if __name__ == "__main__":
    # Sample recent articles (from site_data.json usually)
    sample_recent = [
        {'id': 'a1', 'title': "OpenAI Addresses GPT-4o Sycophancy Issue", 
         'summary_short': "OpenAI explains issues with GPT-4o being too agreeable after user feedback."},
        {'id': 'b2', 'title': "Meta Launches Llama 3.1 - New Capabilities", 
         'summary_short': "Meta AI releases Llama 3.1 model with enhanced coding and reasoning skills."},
        {'id': 'c3', 'title': "Google DeepMind Presents AlphaFold 3", 
         'summary_short': "DeepMind's new AlphaFold model predicts structures of proteins, DNA, RNA."}
    ]

    # New article that IS a duplicate
    new_duplicate = {
        'title': "ChatGPT Sycophancy Problem Explained by OpenAI",
        'summary': "Following user complaints about ChatGPT giving overly positive responses after the GPT-4o integration, OpenAI released a statement explaining the sycophancy tendency and their mitigation efforts."
    }

    # New article that is related but NOT a duplicate
    new_not_duplicate = {
        'title': "OpenAI Previews GPT-5 Multimodal Features",
        'summary': "OpenAI offered a sneak peek at potential GPT-5 capabilities, demonstrating advanced video and audio understanding in internal demos."
    }

    # New article with no relation
    new_unrelated = {
        'title': "Apple Announces New M4 Chip Details",
        'summary': "Apple shared technical specifications for its upcoming M4 processor, highlighting performance gains for MacBooks."
    }

    logger.info("\n--- Running Similarity Check Agent Test ---")

    logger.info("\nTesting DUPLICATE article...")
    result1 = run_similarity_check_agent(new_duplicate, sample_recent)
    print(json.dumps(result1, indent=2) if result1 else "FAILED")

    logger.info("\nTesting RELATED BUT DISTINCT article...")
    result2 = run_similarity_check_agent(new_not_duplicate, sample_recent)
    print(json.dumps(result2, indent=2) if result2 else "FAILED")

    logger.info("\nTesting UNRELATED article...")
    result3 = run_similarity_check_agent(new_unrelated, sample_recent)
    print(json.dumps(result3, indent=2) if result3 else "FAILED")

    logger.info("\n--- Similarity Check Agent Test Complete ---")
