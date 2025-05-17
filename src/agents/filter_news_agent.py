# src/agents/filter_news_agent.py
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

# --- Configuration ---
AGENT_MODEL = "deepseek-coder"
MAX_TOKENS_RESPONSE = 600
TEMPERATURE = 0.1
ALLOWED_TOPICS = [
    "AI Models", "Hardware", "Software", "Robotics", "Compute", "Research", "Open Source",
    "Business", "Startups", "Finance", "Health", "Society", "Ethics", "Regulation",
    "Art & Media", "Environment", "Education", "Security", "Gaming", "Transportation", "Other"
]
IMPORTANT_ENTITIES_FILE = os.path.join(PROJECT_ROOT, 'data', 'important_entities.json')

# --- Load Important Entities ---
def load_important_entities():
    """Loads important entities from the JSON file."""
    try:
        with open(IMPORTANT_ENTITIES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            people = [p.lower() for p in data.get("people", [])]
            companies_products = [cp.lower() for cp in data.get("companies_products", [])]
            # Combine for Python-side check if ever needed, but primarily for prompt injection
            all_entities_for_py_check = list(set(people + companies_products))
            logger.info(f"Loaded {len(people)} important people and {len(companies_products)} important companies/products.")
            return people, companies_products, all_entities_for_py_check
    except FileNotFoundError:
        logger.error(f"CRITICAL: {IMPORTANT_ENTITIES_FILE} not found. Override rule will be incomplete.")
        return [], [], []
    except json.JSONDecodeError:
        logger.error(f"CRITICAL: Error decoding {IMPORTANT_ENTITIES_FILE}. Override rule will be incomplete.")
        return [], [], []
    except Exception as e:
        logger.error(f"CRITICAL: Unexpected error loading {IMPORTANT_ENTITIES_FILE}: {e}. Override rule will be incomplete.")
        return [], [], []

IMPORTANT_PEOPLE_LIST, IMPORTANT_COMPANIES_PRODUCTS_LIST, _ = load_important_entities()
# --- End Important Entities ---


# --- Agent Prompts ---
FILTER_PROMPT_SYSTEM = """
You are an **Expert News Analyst and Content Curator AI**, powered by DeepSeek. Your core competency is to **critically evaluate** news article summaries/headlines to discern importance, **factual basis**, and direct relevance for an audience interested in **substantive AI, Technology, and major related industry/world news**. Your primary function is to **aggressively filter out** non-essential content UNLESS it directly involves major, highly influential tech figures or companies/products (examples provided in User Prompt). You MUST identify only truly **Breaking** or genuinely **Interesting** developments based on verifiable events, data, or significant announcements presented in the summary. Classify news into **exactly one** level: "Breaking", "Interesting", or "Boring". Select the **single most relevant topic** from the provided list. Employ step-by-step reasoning internally but **ONLY output the final JSON**. Your output must strictly adhere to the specified JSON format and contain NO other text, explanations, or formatting.
"""

FILTER_PROMPT_USER_TEMPLATE = """
Task: Critically analyze the provided news article content. Determine its importance level (Breaking, Interesting, Boring) based on factual substance and relevance to the AI/Tech/Major News field. Assign the single most appropriate topic. Filter aggressively, **except as noted below**.

Allowed Topics (Select ONE):
{allowed_topics_list_str}

**CRITICAL OVERRIDE RULE:** Any article primarily focused on actions, statements, product launches, or significant events directly involving the following MAJOR entities **must** be classified as at least **Interesting**, even if it otherwise seems like routine news, opinion, or political commentary (as long as it relates to their role in tech/AI). This rule overrides the default "Boring" classification for these specific entities.
- **Key Individuals (Examples from dynamically provided list):** {key_individuals_examples_str}
- **Key Companies/Products (Examples from dynamically provided list):** {key_companies_products_examples_str}

Importance Level Criteria (Apply *after* considering the CRITICAL OVERRIDE RULE):
- **Breaking**: Reserved for **verified, urgent, high-impact factual events** demanding immediate widespread attention within the AI/Tech sphere (e.g., verified SOTA model release *significantly* outperforming others, critical exploited AI vulnerability, landmark AI regulation enacted affecting many, confirmed huge tech acquisition/shutdown with clear industry-wide effects). Standard product launches or statements, even by key entities, are typically **not** Breaking unless truly exceptional.
- **Interesting**: Requires *demonstrable significance* AND *clear factual reporting* within the summary, relevant to AI, Tech, or major related industry news OR falls under the **CRITICAL OVERRIDE RULE**. Must present *new, verifiable information* OR be about a key entity. Examples: Notable AI model releases (GPT-4o, Claude 3.5), major player strategic shifts (open-sourcing Llama), *confirmed* major controversy/ethical incident involving key players, landmark legal rulings impacting the tech industry, significant funding for *foundational* AI tech, significant factual statements/actions by key individuals listed above related to AI/tech. **General analysis, predictions, or unverified rumors about non-key entities are NOT Interesting.**
- **Boring**: All other content **NOT** covered by the CRITICAL OVERRIDE RULE. Includes: Routine business news *not* involving key entities (standard earnings, generic partnerships, most funding rounds), minor software updates, UI tweaks, *most* product reviews/comparisons, PR announcements for minor features, standard personnel changes (unless CEO level at key company), *satire/parody*, *opinion/editorials* about non-key entities, *speculation/predictions* about non-key entities, most 'explainer' articles, news clearly unrelated to AI/Tech/Major Industry events. **Filter Aggressively for content NOT involving the key entities.**

Input News Article Content (Title and Summary):
Title: {article_title}
Summary: {article_summary}

Based on your internal step-by-step reasoning for the current input article:
1. Check if the article centrally features any of the listed **Key Individuals** or **Key Companies/Products** (refer to the dynamically provided examples).
2. If YES, the importance level MUST be at least "Interesting". Proceed to determine if it meets the "Breaking" criteria. If not Breaking, classify as "Interesting".
3. If NO key entity is featured, apply the standard "Interesting" vs "Boring" criteria aggressively. Default to "Boring" if unsure or non-factual.
4. Determine the core news event or claim.
5. Evaluate its factual basis based only on the summary.
6. Assess impact and novelty against the criteria. Assign ONE final importance level: "Breaking", "Interesting", or "Boring".
7. If not Boring, compare the core event to the Allowed Topics list. Select the SINGLE most fitting topic. Use "Other" if nothing else fits well.
8. Extract a concise primary topic keyword phrase (3-5 words max) reflecting the core factual event (or the general topic if Boring).
9. Provide your final judgment ONLY in the following valid JSON format. Do not include any text before or after the JSON block.

{{
"importance_level": "string", // MUST be "Breaking", "Interesting", or "Boring"
"topic": "string", // MUST be exactly one item from the Allowed Topics list (or "Other")
"reasoning_summary": "string", // Brief justification for importance level based on criteria & factuality
"primary_topic_keyword": "string" // Short keyword phrase for the core news/topic
}}
"""

# --- API Call Function (remains unchanged) ---
def call_deepseek_api(system_prompt, user_prompt):
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
        "max_tokens": MAX_TOKENS_RESPONSE,
        "temperature": TEMPERATURE,
        "stream": False
    }
    try:
        logger.debug(f"Sending filter request to DeepSeek API (model: {AGENT_MODEL}).")
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()
        if result.get("choices") and result["choices"][0].get("message"):
            content = result["choices"][0]["message"].get("content","").strip()
            if content.startswith("```json"): content = content[7:-3].strip()
            elif content.startswith("```"): content = content[3:-3].strip()
            return content
        logger.error(f"API response missing 'choices' or message content: {result}")
        return None
    except Exception as e: logger.exception(f"API call failed: {e}"); return None


# --- Main Agent Function ---
def run_filter_agent(article_data):
    if not isinstance(article_data, dict) or not article_data.get('title') or not article_data.get('summary'):
        logger.error("Invalid article_data for filter agent.");
        if isinstance(article_data, dict): article_data['filter_error'] = "Invalid input";
        return article_data

    article_title = article_data['title']
    article_summary = article_data['summary'] # Use the summary from scraper (which might be full text)
    article_id = article_data.get('id', 'N/A')

    # For the Python-side check (though LLM is primary now for this)
    text_for_py_override_check = f"{article_title} {article_summary}".lower()

    max_summary_length = 1500 # Increased slightly for potentially longer summaries from scraper
    if len(article_summary) > max_summary_length:
        logger.warning(f"Truncating summary (> {max_summary_length} chars) for filtering (ID: {article_id})")
        article_summary = article_summary[:max_summary_length] + "..."

    allowed_topics_str = "\n".join([f"- {topic}" for topic in ALLOWED_TOPICS])
    
    # Prepare example strings for the prompt
    # Take a sample (e.g., first 15) to keep prompt manageable
    key_individuals_examples_str = ", ".join(IMPORTANT_PEOPLE_LIST[:15]) + (", etc." if len(IMPORTANT_PEOPLE_LIST) > 15 else "")
    key_companies_products_examples_str = ", ".join(IMPORTANT_COMPANIES_PRODUCTS_LIST[:20]) + (", etc." if len(IMPORTANT_COMPANIES_PRODUCTS_LIST) > 20 else "")


    try:
        user_prompt = FILTER_PROMPT_USER_TEMPLATE.format(
            article_title=article_title,
            article_summary=article_summary, # This is the (potentially truncated) content for the LLM
            allowed_topics_list_str=allowed_topics_str,
            key_individuals_examples_str=key_individuals_examples_str,
            key_companies_products_examples_str=key_companies_products_examples_str
        )
    except KeyError as e:
        logger.exception(f"KeyError formatting filter prompt template! Error: {e}")
        article_data['filter_verdict'] = None; article_data['filter_error'] = f"Prompt template formatting error: {e}"; return article_data

    logger.info(f"Running filter agent for article ID: {article_id} Title: {article_title[:60]}...")
    raw_response_content = call_deepseek_api(FILTER_PROMPT_SYSTEM, user_prompt)

    if not raw_response_content:
        logger.error(f"Filter agent API call failed for article ID: {article_id}.")
        article_data['filter_verdict'] = None; article_data['filter_error'] = "API call failed"; return article_data

    try:
        filter_verdict = json.loads(raw_response_content)
        required_keys = ["importance_level", "topic", "reasoning_summary", "primary_topic_keyword"]
        if not all(k in filter_verdict for k in required_keys):
            raise ValueError("Missing required keys in filter verdict JSON")

        valid_levels = ["Breaking", "Interesting", "Boring"]
        if filter_verdict['importance_level'] not in valid_levels:
            logger.warning(f"Invalid importance_level '{filter_verdict['importance_level']}'. Forcing to 'Boring'. ID: {article_id}")
            filter_verdict['importance_level'] = "Boring"
        
        if filter_verdict['topic'] not in ALLOWED_TOPICS:
            logger.warning(f"Invalid topic '{filter_verdict['topic']}'. Forcing to 'Other'. ID: {article_id}")
            filter_verdict['topic'] = "Other"

        # The LLM should handle the override based on the prompt.
        # A secondary Python check could be added here as a failsafe if desired,
        # but the goal is to rely on the improved prompt.
        # Example for such a failsafe:
        # if filter_verdict['importance_level'] == "Boring":
        #     combined_entities_for_py_check = IMPORTANT_PEOPLE_LIST + IMPORTANT_COMPANIES_PRODUCTS_LIST
        #     if any(re.search(r'\b' + re.escape(entity) + r'\b', text_for_py_override_check) for entity in combined_entities_for_py_check):
        #         logger.info(f"Python Failsafe: Overriding 'Boring' to 'Interesting' for ID {article_id} due to entity match.")
        #         filter_verdict['importance_level'] = "Interesting"
        #         filter_verdict['reasoning_summary'] = f"[Python Override] {filter_verdict.get('reasoning_summary', '')}"


        logger.info(f"Filter verdict for ID {article_id}: {filter_verdict['importance_level']}, Topic: '{filter_verdict['topic']}', Keyword: '{filter_verdict['primary_topic_keyword']}'")
        article_data['filter_verdict'] = filter_verdict
        article_data['filter_error'] = None
        article_data['filtered_at_iso'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        return article_data

    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON from filter agent for ID {article_id}: {raw_response_content}")
        article_data['filter_verdict'] = None; article_data['filter_error'] = "Invalid JSON response"; return article_data
    except ValueError as ve:
        logger.error(f"Validation error on filter verdict for ID {article_id}: {ve}")
        article_data['filter_verdict'] = None; article_data['filter_error'] = f"Verdict validation failed: {ve}"; return article_data
    except Exception as e:
        logger.exception(f"Unexpected error processing filter response for ID {article_id}: {e}")
        article_data['filter_verdict'] = None; article_data['filter_error'] = "Unexpected processing error"; return article_data

# --- Example Usage (for standalone testing) ---
if __name__ == "__main__":
    logging.getLogger().setLevel(logging.DEBUG)
    logger.setLevel(logging.DEBUG)

    test_article_override = {
        'id': 'test-override-004',
        'title': "Elon Musk Announces New Tesla Solar Panel Efficiency Record at GTC Event",
        'summary': "During a surprise appearance at Nvidia's GTC, Elon Musk revealed that Tesla's solar division has achieved a new world record for solar panel efficiency, though specific numbers were not immediately disclosed. He hinted this technology would integrate with Powerwall and upcoming Tesla vehicles. OpenAI's CEO was also reportedly in attendance but did not speak.",
    }
    test_article_still_boring = {
        'id': 'test-still-boring-005',
        'title': "Review: The Best Robot Vacuums of 2025 for Pet Hair",
        'summary': "We test the latest robot vacuums from iRobot, Shark, and Eufy to see which offers the best cleaning performance for homes with pets and various floor types."
    }

    logger.info("\n--- Running Filter Agent Standalone Test (Perfected Override) ---")

    logger.info("\nTesting article mentioning KEY ENTITY (Should be Interesting due to prompt rule)...")
    result_override = run_filter_agent(test_article_override.copy())
    print("Result (Key Entity):", json.dumps(result_override, indent=2))

    logger.info("\nTesting BORING article NOT mentioning key entity...")
    result_still_boring = run_filter_agent(test_article_still_boring.copy())
    print("Result (Still Boring):", json.dumps(result_still_boring, indent=2))

    logger.info("\n--- Filter Agent Standalone Test Complete ---")