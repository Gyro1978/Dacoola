# src/agents/keyword_research_agent.py (LLM-based Keyword Generation)

import os
import sys
import json
import logging
import re
import time
from dotenv import load_dotenv
import requests # For calling the LLM API

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

# --- Load Environment Variables & LLM Config ---
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)

DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
LLM_AGENT_MODEL = "deepseek-chat" # Or "deepseek-coder" if it performs better for this
LLM_MAX_TOKENS_RESPONSE = 500 # Enough for a list of keywords
LLM_TEMPERATURE = 0.6 # Allow some creativity but keep it relevant
LLM_API_TIMEOUT_SECONDS = 60

# --- Configuration ---
TARGET_NUM_KEYWORDS_LLM = 12 # Aim for a good number of keywords from LLM
MIN_KEYWORD_LENGTH = 2 # Minimum characters for a keyword phrase to be considered
MIN_REQUIRED_KEYWORDS = 5 # If LLM fails badly, we'll try to have at least this many basic ones

# --- LLM Prompts for Keyword Generation ---
KEYWORD_GENERATION_SYSTEM_PROMPT = """
You are an **Expert SEO Keyword Strategist and Content Analyst**. Your task is to generate a highly relevant and comprehensive list of search keywords for the provided news article content. These keywords should reflect what users would realistically type into a search engine like Google to find this specific article.

Focus on:
1.  **Core Subject & Entities:** Identify the main topic, products, people, or organizations discussed.
2.  **User Intent:** Consider different intents (informational, investigational). What questions might the article answer?
3.  **Specificity:** Include a mix of broader category keywords and more specific long-tail keywords (3-5 word phrases).
4.  **Relevance:** All keywords MUST be directly and highly relevant to the provided article text. Do not invent topics.
5.  **Natural Language:** Keywords should be in natural language, not just single terms if longer phrases are more representative.
6.  **Action Verbs/Problem/Solution (if applicable):** If the article discusses a problem, solution, or action, try to capture that.
7.  **Uniqueness:** Provide a diverse set of keywords covering different angles of the article.

Your output MUST be a clean JSON list of strings, containing {TARGET_NUM_KEYWORDS_LLM} keywords. For example:
["keyword phrase 1", "long-tail keyword phrase example", "specific entity mentioned", "main topic variant"]
Do NOT include any other text, explanations, or formatting outside the JSON list.
"""

KEYWORD_GENERATION_USER_TEMPLATE = """
Based on the following article information, generate a JSON list of exactly {TARGET_NUM_KEYWORDS_LLM} high-quality SEO keywords.

**Article Title:** {article_title}
**Primary Topic Keyword (from initial filter):** {primary_topic_keyword}
**Article Summary/Content Snippet (for context):**
{article_summary_snippet}

Generate the JSON list of keywords now.
"""

# --- LLM API Call Function ---
def call_llm_for_keywords(system_prompt, user_prompt):
    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY not set. Cannot call LLM for keywords.")
        return None
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Accept": "application/json"
    }
    payload = {
        "model": LLM_AGENT_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": LLM_MAX_TOKENS_RESPONSE,
        "temperature": LLM_TEMPERATURE,
        "stream": False,
        "response_format": {"type": "json_object"} # Request JSON output if model supports
    }
    try:
        logger.debug(f"Sending keyword generation request to LLM (model: {LLM_AGENT_MODEL}).")
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=LLM_API_TIMEOUT_SECONDS)
        response.raise_for_status()
        result = response.json()

        if result.get("choices") and result["choices"][0].get("message"):
            content = result["choices"][0]["message"].get("content", "").strip()
            # Attempt to parse the content as JSON directly
            # The LLM should ideally return just the JSON string {"keywords": ["kw1", "kw2"]} or just ["kw1", "kw2"]
            logger.debug(f"Raw LLM response for keywords: {content}")
            try:
                # First, try to parse the whole string as JSON (might be a list or a dict)
                parsed_json = json.loads(content)
                if isinstance(parsed_json, list):
                    return parsed_json # It directly returned a list of keywords
                if isinstance(parsed_json, dict) and "keywords" in parsed_json and isinstance(parsed_json["keywords"], list):
                    return parsed_json["keywords"] # It returned a dict like {"keywords": [...]}
                
                logger.warning(f"LLM returned JSON, but not in expected list or {{'keywords': list}} format: {content}")
                return None # Or try to extract if it's embedded differently

            except json.JSONDecodeError:
                logger.error(f"Failed to parse JSON from LLM keyword response: {content}")
                # Fallback: Try to extract a list if it's embedded in text like ```json [...] ```
                match = re.search(r'```json\s*(\[.*?\])\s*```', content, re.DOTALL)
                if match:
                    try:
                        return json.loads(match.group(1))
                    except json.JSONDecodeError:
                        logger.error(f"Failed to parse extracted JSON list from LLM: {match.group(1)}")
                return None
        logger.error(f"LLM API response missing 'choices' or message content for keywords: {result}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"LLM API call for keywords failed: {e}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error during LLM API call for keywords: {e}")
        return None

# --- Main Agent Function ---
def run_keyword_research_agent(article_data):
    article_id = article_data.get('id', 'N/A')
    logger.info(f"Running LLM-based Keyword Research for article ID: {article_id}...")

    article_title = article_data.get('title', "No Title Provided")
    # Use content_for_processing, which should be the most complete text available
    content_for_context = article_data.get('content_for_processing', article_data.get('summary', ''))
    
    # Limit snippet length for the prompt to avoid excessive token usage
    max_snippet_length = 1500 # Characters
    summary_snippet = content_for_context
    if len(content_for_context) > max_snippet_length:
        summary_snippet = content_for_context[:max_snippet_length] + "..."
        logger.debug(f"Truncated article content snippet for LLM keyword prompt (ID: {article_id})")

    primary_topic_keyword = article_data.get('filter_verdict', {}).get('primary_topic_keyword', article_title) # Fallback to title
    if not primary_topic_keyword: # Ensure it's not empty
        primary_topic_keyword = article_title

    # Prepare prompts
    system_prompt_formatted = KEYWORD_GENERATION_SYSTEM_PROMPT.format(TARGET_NUM_KEYWORDS_LLM=TARGET_NUM_KEYWORDS_LLM)
    user_prompt_formatted = KEYWORD_GENERATION_USER_TEMPLATE.format(
        article_title=article_title,
        primary_topic_keyword=primary_topic_keyword,
        article_summary_snippet=summary_snippet,
        TARGET_NUM_KEYWORDS_LLM=TARGET_NUM_KEYWORDS_LLM
    )

    generated_keywords_from_llm = call_llm_for_keywords(system_prompt_formatted, user_prompt_formatted)
    final_keyword_list = []

    if generated_keywords_from_llm and isinstance(generated_keywords_from_llm, list):
        logger.info(f"LLM generated {len(generated_keywords_from_llm)} keywords for article ID {article_id}.")
        # Clean and validate keywords
        for kw in generated_keywords_from_llm:
            if isinstance(kw, str):
                cleaned_kw = kw.strip()
                if len(cleaned_kw) >= MIN_KEYWORD_LENGTH and cleaned_kw.lower() not in (k.lower() for k in final_keyword_list):
                    final_keyword_list.append(cleaned_kw)
            if len(final_keyword_list) >= TARGET_NUM_KEYWORDS_LLM: # Stop if we hit target
                break
        article_data['keyword_agent_error'] = None
    else:
        logger.warning(f"LLM keyword generation failed or returned invalid format for article ID {article_id}.")
        article_data['keyword_agent_error'] = "LLM keyword generation failed"

    # Ensure primary_topic_keyword is at the start if not already included by LLM in a similar form
    if primary_topic_keyword:
        ptk_lower = primary_topic_keyword.lower()
        if not any(fk.lower() == ptk_lower for fk in final_keyword_list):
            final_keyword_list.insert(0, primary_topic_keyword.strip())

    # Fallback: if LLM fails badly, try to derive some basic keywords
    if len(final_keyword_list) < MIN_REQUIRED_KEYWORDS:
        logger.warning(f"LLM yielded too few keywords ({len(final_keyword_list)}). Attempting basic fallback for article ID {article_id}.")
        if primary_topic_keyword and primary_topic_keyword.strip().lower() not in (k.lower() for k in final_keyword_list):
            final_keyword_list.append(primary_topic_keyword.strip())
        
        # Add some words from title if still not enough
        title_words = re.findall(r'\b[a-zA-Z]{3,}\b', article_title.lower()) # Words with 3+ letters
        for word in title_words:
            if len(final_keyword_list) >= MIN_REQUIRED_KEYWORDS: break
            if word not in (k.lower() for k in final_keyword_list):
                final_keyword_list.append(word.capitalize()) # Capitalize for consistency if single word

    # Deduplicate again and ensure final count
    final_keyword_list = list(dict.fromkeys(final_keyword_list)) # Deduplicate while preserving order somewhat
    article_data['researched_keywords'] = final_keyword_list[:TARGET_NUM_KEYWORDS_LLM] # Trim to target

    logger.info(f"Keyword research complete for ID {article_id}. Final keywords ({len(article_data['researched_keywords'])}): {article_data['researched_keywords']}")
    return article_data

# --- Standalone Execution (for testing) ---
if __name__ == "__main__":
    logging.getLogger().setLevel(logging.DEBUG)
    logger.setLevel(logging.DEBUG)

    if not DEEPSEEK_API_KEY:
        logger.error("CRITICAL FOR STANDALONE TEST: DEEPSEEK_API_KEY env var not set.")
        sys.exit(1)

    test_article_data = {
        'id': 'test-kw-llm-001',
        'title': "Pope Francis Warns G7 Leaders About AI's 'Ethical Deterioration' and Impact on Humanity",
        # 'summary': "Pope Francis addressed the G7 summit, highlighting the dual nature of artificial intelligence as both a powerful tool and a significant risk. He urged world leaders to prioritize human dignity and ethical considerations in AI development and deployment, warning against unchecked technological advancement that could lead to a 'genuine ethical deterioration.' The Pope emphasized the need for political action to ensure AI serves humanity positively, particularly in areas like peace, labor, and avoiding algorithmic bias.",
        'content_for_processing': """
Pope Francis took his call for artificial intelligence to be developed and used ethically to the Group of Seven industrialized nations Friday, telling leaders that AI must never be allowed to get the upper hand over humans. He also renewed his warning about its use in warfare.
Francis became the first pope to address a G7 summit. He was invited by host Italy to speak at a special session on the perils and promises of AI.
He told leaders of the U.S., Britain, Canada, France, Germany, Japan and Italy that AI is an “exciting” and “frightening” tool that requires urgent political action to ensure it remains human-centric.
“We would condemn humanity to a future without hope if we took away people’s ability to make decisions about themselves and their lives, by dooming them to depend on the choices of machines,” Francis said. “We need to ensure and safeguard a space for proper human control over the choices made by artificial intelligence programs: Human dignity itself depends on it.”
The pope has spoken about AI multiple times. He believes it offers great potential for good, but also risks exacerbating inequalities and could have a devastating impact if its development isn’t guided by ethics and a sense of the common good.
He brought those concerns to the G7, where he also warned against AI's use in the military. “No machine should ever choose to take the life of a human being,” he said, adding that people must never let algorithms decide such fundamental questions.
He urged politicians to take the lead in making AI human-centric, so that “decision-making, even when it comes to the different and oftentimes complex choices that this entails, always remains with the human person.”
His remarks came as G7 leaders pledged to coordinate their approaches to governing AI to make sure it is "human-centered, trustworthy, and responsible."
The pope was also expected to raise the issue of AI's impact on the Global South, where developing countries often bear the brunt of environmental damage caused by resource extraction needed for tech manufacturing, and where algorithms can perpetuate biases.
        """,
        'filter_verdict': {'primary_topic_keyword': 'Pope AI ethics warning'}
    }
    logger.info("\n--- Running LLM-based Keyword Research Agent Standalone Test ---")
    result_data = run_keyword_research_agent(test_article_data.copy())

    print("\n--- LLM Keyword Research Results ---")
    if result_data.get('keyword_agent_error'):
        print(f"Error: {result_data['keyword_agent_error']}")
    print(f"Researched Keywords ({len(result_data.get('researched_keywords', []))}): {result_data.get('researched_keywords')}")

    logger.info("--- LLM Keyword Research Agent Standalone Test Complete ---")