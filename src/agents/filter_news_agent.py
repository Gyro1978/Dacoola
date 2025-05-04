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

# --- Keywords for Importance Override ---
# Keywords should be lowercase for case-insensitive matching
IMPORTANT_PEOPLE = [
    # CEOs / Founders / Execs
    "elon musk", "jeff bezos", "tim cook", "sam altman", "satya nadella",
    "sundar pichai", "mark zuckerberg", "jensen huang", "dario amodei",
    "demis hassabis", "larry page", "sergey brin", "bill gates",
    "steve jobs", # Historical but still relevant contextually
    "masayoshi son", "lisa su", "pat gelsinger", "andy jassy",
    "mustafa suleyman", "reid hoffman", "peter thiel", "marc andreessen",
    "vinod khosla",
    # Researchers / Academics
    "yann lecun", "geoffrey hinton", "andrew ng", "fei-fei li", "yoshua bengio",
    "ilya sutskever", "jurgen schmidhuber", "oriol vinyals", "andrej karpathy",
    # Regulators / Politicians (if relevant to your scope)
    "donald trump", "joe biden", "margrethe vestager", "lina khan", "gina raimondo",
    "xi jinping"
]
IMPORTANT_COMPANIES_PRODUCTS = [
    # Major AI Labs / Companies
    "openai", "chatgpt", "gpt-3", "gpt-4", "gpt-5", "gpt-4o", "dall-e", "sora", # OpenAI
    "google", "alphabet", "deepmind", "gemini", "google ai", "google cloud", "waymo", "bard", "tensorflow", "keras", # Google
    "meta", "facebook", "instagram", "whatsapp", "llama", "llama 2", "llama 3", "meta ai", "pytorch", # Meta
    "microsoft", "azure", "copilot", "bing", # Microsoft
    "apple", "siri", "vision pro", "core ml", # Apple
    "amazon", "aws", "alexa", "bedrock", "sagemaker", # Amazon
    "anthropic", "claude", "claude 2", "claude 3", # Anthropic
    "mistral ai", # Mistral
    "stability ai", "stable diffusion", "sdxl", # Stability AI
    "cohere", # Cohere
    "ai21 labs", # AI21
    "inflection ai", # Inflection
    "cerebras", # Cerebras
    # Hardware / Semiconductors
    "nvidia", "h100", "a100", "b100", "b200", "blackwell", "grace hopper", "cuda", "tensorrt", # Nvidia
    "intel", "gaudi", "xeon", # Intel
    "amd", "instinct", "ryzen", "epyc", # AMD
    "arm", "qualcomm", "tsmc", "samsung electronics", "asml",
    # Musk Companies
    "tesla", "spacex", "starlink", "neuralink", "xai", "grok", "x corp", "twitter", # Note: Twitter might overlap with general news
    # Cloud / Infrastructure
    "oracle cloud", "ibm cloud", "cloudflare",
    # Other Key Tech / Startups / VC
    "softbank", "a16z", "sequoia capital", "y combinator", "yc",
    "hugging face", "databricks", "snowflake",
    "palantir",
    # Relevant Acronyms / Concepts (Use carefully, might be too broad)
    "agi", "asi", "sota", "llm", "vlm", "transformer", # Maybe too generic?
    # Government / Regulation Bodies (Use if tracking policy)
    "sec", "ftc", "doj", "european union", "eu commission", "nist"
]
# Combine lists for easier checking
IMPORTANT_ENTITIES = IMPORTANT_PEOPLE + IMPORTANT_COMPANIES_PRODUCTS
# --- End Keywords ---


# --- Agent Prompts ---
# Prompts remain the same - the override happens *after* the LLM call
FILTER_PROMPT_SYSTEM = """
You are an **Expert News Analyst and Content Curator AI**, powered by DeepSeek. Your core competency is to **critically evaluate** news article summaries/headlines to discern importance, **factual basis**, and direct relevance for an audience interested in **substantive AI, Technology, and major related industry/world news**. Your primary function is to **aggressively filter out** non-essential content (routine updates, marketing, basic financial reports, opinion, speculation, satire). You MUST identify only truly **Breaking** or genuinely **Interesting** developments based on verifiable events, data, or significant announcements presented in the summary. Mundane, routine, low-impact, non-factual, purely speculative, or clearly off-topic updates **must** be classified as **Boring**. You operate based on strict criteria focusing on novelty, significance, impact, verifiable claims, and major players/events. Classify news into **exactly one** level: "Breaking", "Interesting", or "Boring". Select the **single most relevant topic** from the provided list. Employ step-by-step reasoning internally but **ONLY output the final JSON**. Your output must strictly adhere to the specified JSON format and contain NO other text, explanations, or formatting.
"""

FILTER_PROMPT_USER_TEMPLATE = """
Task: Critically analyze the provided news article content. Determine its importance level (Breaking, Interesting, Boring) based on factual substance and relevance to the AI/Tech/Major News field. Assign the single most appropriate topic. Filter aggressively.

Allowed Topics (Select ONE):
{allowed_topics_list_str}

Importance Level Criteria:
- **Breaking**: Reserved for **verified, urgent, high-impact factual events** demanding immediate widespread attention. MUST BE TRULY EXCEPTIONAL in the AI/Tech sphere (e.g., verified SOTA model release significantly outperforming others, critical exploited AI vulnerability, landmark AI regulation enacted affecting many, confirmed huge tech acquisition/shutdown with clear industry-wide effects like Broadcom/VMware). Standard product launches are **never** Breaking.
- **Interesting**: Requires *demonstrable significance* AND *clear factual reporting* within the summary, relevant to AI, Tech, or major related industry news. Must present *new, verifiable information*. Examples: Notable AI model releases *with specific verifiable performance claims/novel capabilities*, high-impact AI/Tech research papers *with novel findings*, major player strategic shifts *with concrete actions* (e.g., major open-sourcing, significant policy change like Apple allowing external payments), *confirmed* major controversy/ethical incident (e.g., large-scale AI misuse), landmark legal rulings impacting the tech industry (e.g., Epic vs Apple outcome), significant *late-stage* funding (>~$100M) for *foundational* AI tech. **General analysis, interviews, opinion pieces, predictions, satire, or unverified rumors are NOT Interesting.** If unsure, **default to Boring.** Consider the implied source if possible (is it likely factual reporting or opinion/satire?).
- **Boring**: All other content. Includes: Routine business news (standard earnings reports *without major surprises*, stock price analysis, generic partnerships, *most funding rounds*, conference summaries *without major releases*), minor software/model updates, UI tweaks, feature additions without significant capability change, PR announcements, standard personnel changes, *satire/parody*, *opinion/editorials/blog posts*, *speculation/predictions*, most 'explainer' or 'how-to' articles, news clearly unrelated to AI/Tech/Major Industry events (e.g., sports scores, local events unless tech/AI related). **Filter Aggressively.**

Input News Article Content (Title and Summary):
Title: {article_title}
Summary: {article_summary}

--- START FEW-SHOT EXAMPLES ---
[... Keep all examples exactly as they were ...]
--- END FEW-SHOT EXAMPLES ---

Based on your internal step-by-step reasoning for the current input article (NOT the examples above):
1. Determine the core news event or claim.
2. Evaluate its factual basis and source nature (if possible) based only on the summary. Is it reporting a concrete event/release/finding/ruling, or is it likely opinion/satire/speculation/PR?
3. Assess its impact and novelty against the strict criteria for AI/Tech/Major News. Assign ONE importance level: "Breaking", "Interesting", or "Boring". Default to Boring if unsure or non-factual.
4. If not Boring, compare the core event to the Allowed Topics list. Select the SINGLE most fitting topic. Use "Other" if nothing else fits well.
5. Extract a concise primary topic keyword phrase (3-5 words max) reflecting the core factual event (or the general topic if Boring).
6. Provide your final judgment ONLY in the following valid JSON format. Do not repeat the examples. Do not include any text before or after the JSON block.

{{
"importance_level": "string", // MUST be "Breaking", "Interesting", or "Boring"
"topic": "string", // MUST be exactly one item from the Allowed Topics list (or "Other")
"reasoning_summary": "string", // Brief justification for importance level based on criteria & factuality
"primary_topic_keyword": "string" // Short keyword phrase for the core news/topic
}}
"""

# --- API Call Function ---
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
    Takes article data, runs the filter agent, validates the response,
    overrides "Boring" if important entities are present,
    and adds the parsed JSON verdict or error info back into the article_data dict.
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

    # Store original text for keyword check later
    original_text_combined = f"{article_title} {article_summary}".lower()

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
             received_level = "Boring"
             # Optionally, raise ValueError for stricter validation:
             # raise ValueError(f"Invalid importance_level value: {received_level}")


        # Validate topic against allowed list (with fallback)
        received_topic = filter_verdict.get('topic')
        if received_topic not in ALLOWED_TOPICS:
             logger.warning(f"Topic '{received_topic}' not in allowed list for article ID {article_id}. Forcing to 'Other'.")
             filter_verdict['topic'] = "Other" # Apply fallback

        # --- *** IMPORTANCE OVERRIDE LOGIC *** ---
        overridden = False
        if filter_verdict['importance_level'] == "Boring":
            found_entity = None
            # Check if any important entity is mentioned (case-insensitive)
            for entity in IMPORTANT_ENTITIES:
                 # Use \b for word boundaries to avoid partial matches (e.g., 'ai' in 'train')
                 if re.search(r'\b' + re.escape(entity) + r'\b', original_text_combined):
                      found_entity = entity
                      break # Stop after first match

            if found_entity:
                 logger.info(f"Overriding 'Boring' verdict for article ID {article_id}. Found important entity: '{found_entity}'. Setting to 'Interesting'.")
                 filter_verdict['importance_level'] = "Interesting"
                 # Optionally update reasoning
                 filter_verdict['reasoning_summary'] = f"Promoted from Boring due to mention of '{found_entity}'. Original reason: {filter_verdict.get('reasoning_summary', '')}"
                 overridden = True
        # --- *** END OVERRIDE LOGIC *** ---


        # --- Success Case ---
        log_suffix = " (Overridden from Boring)" if overridden else ""
        logger.info(f"Filter verdict received for ID {article_id}: level={filter_verdict['importance_level']}, topic='{filter_verdict['topic']}', keyword='{filter_verdict['primary_topic_keyword']}'{log_suffix}")
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
    test_article_override = { 'id': 'test-override-004', 'title': "Stock Analyst Discusses Tesla Q2 Earnings Preview", 'summary': "Ahead of Tesla's earnings report, market watchers speculate on delivery numbers and potential impact of Elon Musk's recent focus shifts on company performance.", }
    test_article_invalid_input = {'id': 'test-invalid-input', 'title': 'Just a title'}


    logger.info("\n--- Running Filter Agent Standalone Test ---")

    logger.info("\nTesting BREAKING article...")
    result_breaking = run_filter_agent(test_article_data_breaking.copy())
    print("Result:", json.dumps(result_breaking, indent=2))

    logger.info("\nTesting INTERESTING article...")
    result_interesting = run_filter_agent(test_article_data_interesting.copy())
    print("Result:", json.dumps(result_interesting, indent=2))

    logger.info("\nTesting BORING article...")
    result_boring = run_filter_agent(test_article_data_boring.copy())
    print("Result:", json.dumps(result_boring, indent=2))

    logger.info("\nTesting BORING article that SHOULD BE OVERRIDDEN...")
    result_override = run_filter_agent(test_article_override.copy())
    print("Result:", json.dumps(result_override, indent=2)) # Expect 'Interesting'

    logger.info("\nTesting INVALID INPUT article...")
    result_invalid = run_filter_agent(test_article_invalid_input.copy())
    print("Result:", json.dumps(result_invalid, indent=2))


    logger.info("\n--- Filter Agent Standalone Test Complete ---")