# src/agents/filter_news_agent.py
import os
import sys # Added sys for path check below
import requests
import json
import logging
import re # Added for simple text matching
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
# If run standalone, basicConfig might apply if not already configured.
logger = logging.getLogger(__name__)
# Basic config for standalone testing if no handlers are present
if not logging.getLogger().hasHandlers():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# --- Load Environment Variables ---
# Load from .env file in the project root
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"

# --- Configuration ---
AGENT_MODEL = "deepseek-chat"
MAX_TOKENS_RESPONSE = 250 # Max tokens expected for the JSON response
TEMPERATURE = 0.1 # Low temperature for more deterministic filtering/classification

# List of allowed topics for classification
ALLOWED_TOPICS = [
    # Core AI/Tech
    "AI Models", "Hardware", "Software", "Robotics", "Compute",
    "Research", "Open Source",
    # Impact / Application
    "Business", "Startups", "Finance", "Health", "Society",
    "Ethics", "Regulation", "Art & Media", "Environment",
    "Education", "Security", "Gaming", "Transportation",
    # Broader Tech (Optional, keep focus)
    # "Cloud Computing", "Quantum Computing", "Space Tech",
    "Other" # Fallback topic
]

# --- Keywords for Importance Override (Used only for documentation/reference now) ---
# The actual override logic is now embedded in the prompt itself.
IMPORTANT_PEOPLE_EXAMPLES = [
    "elon musk", "jeff bezos", "tim cook", "sam altman", "satya nadella",
    "sundar pichai", "mark zuckerberg", "jensen huang", "dario amodei",
    "demis hassabis", "yann lecun", "geoffrey hinton", "andrew ng", "fei-fei li"
]
IMPORTANT_COMPANIES_PRODUCTS_EXAMPLES = [
    "openai", "chatgpt", "gpt-4", "gpt-5", "dall-e", "sora",
    "google", "deepmind", "gemini", "google ai",
    "meta", "llama", "meta ai",
    "microsoft", "azure", "copilot",
    "apple", "nvidia", "blackwell",
    "tesla", "spacex", "neuralink", "xai", "grok",
    "anthropic", "claude",
    "mistral ai", "stability ai", "stable diffusion",
    "intel", "amd", "aws", "hugging face"
]
# --- End Keywords ---


# --- Agent Prompts ---
FILTER_PROMPT_SYSTEM = """
You are an **Expert News Analyst and Content Curator AI**, powered by DeepSeek. Your core competency is to **critically evaluate** news article summaries/headlines to discern importance, **factual basis**, and direct relevance for an audience interested in **substantive AI, Technology, and major related industry/world news**. Your primary function is to **aggressively filter out** non-essential content UNLESS it directly involves major, highly influential tech figures or companies/products (see list in User Prompt). You MUST identify only truly **Breaking** or genuinely **Interesting** developments based on verifiable events, data, or significant announcements presented in the summary. Classify news into **exactly one** level: "Breaking", "Interesting", or "Boring". Select the **single most relevant topic** from the provided list. Employ step-by-step reasoning internally but **ONLY output the final JSON**. Your output must strictly adhere to the specified JSON format and contain NO other text, explanations, or formatting.
"""

# --- MODIFIED USER TEMPLATE ---
FILTER_PROMPT_USER_TEMPLATE = """
Task: Critically analyze the provided news article content. Determine its importance level (Breaking, Interesting, Boring) based on factual substance and relevance to the AI/Tech/Major News field. Assign the single most appropriate topic. Filter aggressively, **except as noted below**.

Allowed Topics (Select ONE):
{allowed_topics_list_str}

**CRITICAL OVERRIDE RULE:** Any article primarily focused on actions, statements, product launches, or significant events directly involving the following MAJOR entities **must** be classified as at least **Interesting**, even if it otherwise seems like routine news, opinion, or political commentary (as long as it relates to their role in tech/AI). This rule overrides the default "Boring" classification for these specific entities.
- **Key Individuals (Examples):** Elon Musk, Sam Altman, Jensen Huang, Mark Zuckerberg, Satya Nadella, Sundar Pichai, Tim Cook, Dario Amodei, Demis Hassabis, Jeff Bezos, Yann LeCun, Geoffrey Hinton, Andrew Ng, Donald Trump (regarding tech/AI policy).
- **Key Companies/Products (Examples):** OpenAI (ChatGPT, GPT-4, Sora), Google (DeepMind, Gemini, Google AI), Meta (Llama, Meta AI), Microsoft (Azure, Copilot), Apple, Amazon (AWS), Nvidia (Blackwell, H100), Tesla, SpaceX, Anthropic (Claude), Mistral AI, Stability AI, xAI (Grok), Hugging Face.

Importance Level Criteria (Apply *after* considering the CRITICAL OVERRIDE RULE):
- **Breaking**: Reserved for **verified, urgent, high-impact factual events** demanding immediate widespread attention within the AI/Tech sphere (e.g., verified SOTA model release *significantly* outperforming others, critical exploited AI vulnerability, landmark AI regulation enacted affecting many, confirmed huge tech acquisition/shutdown with clear industry-wide effects). Standard product launches or statements, even by key entities, are typically **not** Breaking unless truly exceptional.
- **Interesting**: Requires *demonstrable significance* AND *clear factual reporting* within the summary, relevant to AI, Tech, or major related industry news OR falls under the **CRITICAL OVERRIDE RULE**. Must present *new, verifiable information* OR be about a key entity. Examples: Notable AI model releases (GPT-4o, Claude 3.5), major player strategic shifts (open-sourcing Llama), *confirmed* major controversy/ethical incident involving key players, landmark legal rulings impacting the tech industry, significant funding for *foundational* AI tech, significant factual statements/actions by key individuals listed above related to AI/tech. **General analysis, predictions, or unverified rumors about non-key entities are NOT Interesting.**
- **Boring**: All other content **NOT** covered by the CRITICAL OVERRIDE RULE. Includes: Routine business news *not* involving key entities (standard earnings, generic partnerships, most funding rounds), minor software updates, UI tweaks, *most* product reviews/comparisons, PR announcements for minor features, standard personnel changes (unless CEO level at key company), *satire/parody*, *opinion/editorials* about non-key entities, *speculation/predictions* about non-key entities, most 'explainer' articles, news clearly unrelated to AI/Tech/Major Industry events. **Filter Aggressively for content NOT involving the key entities.**

Input News Article Content (Title and Summary):
Title: {article_title}
Summary: {article_summary}

Based on your internal step-by-step reasoning for the current input article:
1. Check if the article centrally features any of the listed **Key Individuals** or **Key Companies/Products**.
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

# --- API Call Function ---
# (API Call function remains unchanged)
def call_deepseek_api(system_prompt, user_prompt):
    """Calls the DeepSeek API and returns the cleaned JSON content string."""
    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY environment variable not set.")
        return None

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Accept": "application/json" # Good practice
    }
    payload = {
        "model": AGENT_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": MAX_TOKENS_RESPONSE,
        "temperature": TEMPERATURE,
        "stream": False # Not streaming the response
    }

    try:
        logger.debug(f"Sending filter request to DeepSeek API (model: {AGENT_MODEL}).")
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

        result = response.json()
        logger.debug(f"Raw API Response received (Filter Agent).")

        if result.get("choices") and len(result["choices"]) > 0:
            message_content = result["choices"][0].get("message", {}).get("content")
            if message_content:
                # Clean potential markdown code fences ```json ... ```
                content_stripped = message_content.strip()
                if content_stripped.startswith("```json"):
                    message_content = content_stripped[7:-3].strip()
                elif content_stripped.startswith("```"):
                     message_content = content_stripped[3:-3].strip()
                logger.debug(f"Extracted content from API response.")
                return message_content
            else:
                logger.error("API response successful, but no message content found in choices.")
                return None
        else:
            # Log the actual response structure if it's unexpected
            logger.error(f"API response missing 'choices' or choices empty: {result}")
            return None

    except requests.exceptions.Timeout:
         logger.error(f"API request timed out after 60 seconds.")
         return None
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed: {e}")
        return None
    except json.JSONDecodeError as e:
        # Log the response text that failed parsing
        response_text = response.text if response else "N/A"
        logger.error(f"Failed to decode API JSON response: {e}. Response text: {response_text[:500]}...")
        return None
    except Exception as e:
        # Catch any other unexpected errors during the API call
        logger.exception(f"An unexpected error occurred during API call: {e}")
        return None

# --- Main Agent Function ---
def run_filter_agent(article_data):
    """
    Takes article data, runs the filter agent (which now includes override logic
    via prompt), validates the response, and adds the parsed JSON verdict
    or error info back into the article_data dict.
    """
    # Basic input validation
    if not isinstance(article_data, dict) or not article_data.get('title') or not article_data.get('summary'):
        logger.error("Invalid or incomplete article_data provided to filter agent.")
        if isinstance(article_data, dict):
             article_data['filter_verdict'] = None
             article_data['filter_error'] = "Invalid input data (missing title or summary)"
        else:
             logger.error("Input 'article_data' was not a dictionary.")
             return None
        return article_data

    article_title = article_data['title']
    article_summary = article_data['summary']
    article_id = article_data.get('id', 'N/A') # For logging

    # Truncate summary if it's excessively long for the API context/cost
    max_summary_length = 1000 # Keep summary reasonable
    if len(article_summary) > max_summary_length:
        logger.warning(f"Truncating summary (> {max_summary_length} chars) for filtering (Article ID: {article_id})")
        article_summary = article_summary[:max_summary_length] + "..."

    # Format the allowed topics list for insertion into the prompt
    allowed_topics_str = "\n".join([f"- {topic}" for topic in ALLOWED_TOPICS])

    try:
        user_prompt = FILTER_PROMPT_USER_TEMPLATE.format(
            article_title=article_title,
            article_summary=article_summary,
            allowed_topics_list_str=allowed_topics_str
        )
    except KeyError as e:
        logger.exception(f"KeyError formatting filter prompt template! Error: {e}")
        article_data['filter_verdict'] = None
        article_data['filter_error'] = f"Prompt template formatting error: {e}"
        return article_data

    logger.info(f"Running filter agent for article ID: {article_id} Title: {article_title[:60]}...")
    raw_response_content = call_deepseek_api(FILTER_PROMPT_SYSTEM, user_prompt)

    # Handle API call failure
    if not raw_response_content:
        logger.error(f"Filter agent failed to get a valid response from the API for article ID: {article_id}.")
        article_data['filter_verdict'] = None
        article_data['filter_error'] = "API call failed or returned empty content"
        return article_data

    # Parse and Validate the JSON response
    try:
        filter_verdict = json.loads(raw_response_content)

        # --- Validate JSON Structure and Content ---
        required_keys = ["importance_level", "topic", "reasoning_summary", "primary_topic_keyword"]
        if not isinstance(filter_verdict, dict) or not all(k in filter_verdict for k in required_keys):
            logger.error(f"Parsed filter verdict JSON is missing required keys or is not a dict: {filter_verdict}")
            raise ValueError("Missing required keys or invalid format in filter verdict JSON")

        # Validate importance level value
        valid_levels = ["Breaking", "Interesting", "Boring"]
        received_level = filter_verdict.get('importance_level')
        if received_level not in valid_levels:
             logger.warning(f"Invalid importance_level received: '{received_level}'. Forcing to 'Boring'.")
             filter_verdict['importance_level'] = "Boring" # Force to Boring if invalid
             # Note: Override logic in the prompt should prevent this for key entities,
             # but this is a safety fallback if the LLM provides an invalid level anyway.

        # Validate topic against allowed list (with fallback)
        received_topic = filter_verdict.get('topic')
        if received_topic not in ALLOWED_TOPICS:
             logger.warning(f"Topic '{received_topic}' not in allowed list for article ID {article_id}. Forcing to 'Other'.")
             filter_verdict['topic'] = "Other" # Apply fallback

        # --- ** NO Python Override Logic Needed Anymore ** ---
        # The override is handled by the LLM via the modified prompt.

        # --- Success Case ---
        logger.info(f"Filter verdict received for ID {article_id}: level={filter_verdict['importance_level']}, topic='{filter_verdict['topic']}', keyword='{filter_verdict['primary_topic_keyword']}'")
        article_data['filter_verdict'] = filter_verdict
        article_data['filter_error'] = None # Clear any previous error state on success
        # Add timestamp using standard UTC 'Z' format
        article_data['filtered_at_iso'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        return article_data

    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON response from filter agent for ID {article_id}: {raw_response_content}")
        article_data['filter_verdict'] = None
        article_data['filter_error'] = "Invalid JSON response from API"
        return article_data
    except ValueError as ve: # Catch validation errors
        logger.error(f"Validation error on filter verdict for ID {article_id}: {ve}")
        article_data['filter_verdict'] = None
        article_data['filter_error'] = f"Verdict validation failed: {ve}"
        return article_data
    except Exception as e: # Catch any other unexpected errors during processing
        logger.exception(f"An unexpected error occurred processing filter response for ID {article_id}: {e}")
        article_data['filter_verdict'] = None
        article_data['filter_error'] = "Unexpected processing error"
        return article_data

# --- Example Usage (for standalone testing) ---
if __name__ == "__main__":
    # Set higher logging level for testing this script directly
    logging.getLogger().setLevel(logging.DEBUG)
    logger.setLevel(logging.DEBUG) # Ensure this module's logger is also DEBUG

    # Example article data
    test_article_data_breaking = { 'id': 'test-breaking-001', 'title': "BREAKING: OpenAI CEO Sam Altman Steps Down Unexpectedly Amid Board Conflict", 'summary': "In a shocking move, OpenAI announced CEO Sam Altman is leaving the company immediately following a board review citing a lack of consistent candor. CTO Mira Murati appointed interim CEO. Major implications for the AI industry.", }
    test_article_data_interesting = { 'id': 'test-interesting-002', 'title': "Anthropic Releases Claude 3.5 Sonnet, Outperforms GPT-4o", 'summary': "Anthropic launched Claude 3.5 Sonnet, claiming state-of-the-art performance surpassing OpenAI's GPT-4o and Google's Gemini on key benchmarks, particularly in coding and vision tasks. Includes new 'Artifacts' feature.", }
    test_article_data_boring = { 'id': 'test-boring-003', 'title': "AI Startup 'InnovateAI' Secures $5M Seed Funding", 'summary': "InnovateAI, a company developing AI tools for marketing automation, announced it has closed a $5 million seed funding round led by Venture Partners. Funds will be used for hiring and product development.", }
    # This should now be classified as "Interesting" by the LLM due to the prompt override rule
    test_article_override = { 'id': 'test-override-004', 'title': "Stock Analyst Discusses Tesla Q2 Earnings Preview", 'summary': "Ahead of Tesla's earnings report, market watchers speculate on delivery numbers and potential impact of Elon Musk's recent focus shifts on company performance.", }
    # This should still be boring as it doesn't mention key entities
    test_article_still_boring = { 'id': 'test-still-boring-005', 'title': "Review: The Best Robot Vacuums of 2025", 'summary': "We test the latest robot vacuums from various brands to see which offers the best cleaning performance and features for your home."}

    test_article_invalid_input = {'id': 'test-invalid-input', 'title': 'Just a title'}


    logger.info("\n--- Running Filter Agent Standalone Test ---")

    logger.info("\nTesting BREAKING article...")
    result_breaking = run_filter_agent(test_article_data_breaking.copy())
    print("Result:", json.dumps(result_breaking, indent=2))

    logger.info("\nTesting INTERESTING article...")
    result_interesting = run_filter_agent(test_article_data_interesting.copy())
    print("Result:", json.dumps(result_interesting, indent=2))

    logger.info("\nTesting STANDARD BORING article...")
    result_boring = run_filter_agent(test_article_data_boring.copy())
    print("Result:", json.dumps(result_boring, indent=2))

    logger.info("\nTesting article mentioning KEY ENTITY (Should be Interesting due to prompt rule)...")
    result_override = run_filter_agent(test_article_override.copy())
    print("Result:", json.dumps(result_override, indent=2)) # Expect 'Interesting'

    logger.info("\nTesting BORING article NOT mentioning key entity...")
    result_still_boring = run_filter_agent(test_article_still_boring.copy())
    print("Result:", json.dumps(result_still_boring, indent=2)) # Expect 'Boring'

    logger.info("\nTesting INVALID INPUT article...")
    result_invalid = run_filter_agent(test_article_invalid_input.copy())
    print("Result:", json.dumps(result_invalid, indent=2))


    logger.info("\n--- Filter Agent Standalone Test Complete ---")