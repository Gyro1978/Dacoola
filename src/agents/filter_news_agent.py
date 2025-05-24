# src/agents/filter_news_agent.py
import os
import sys
import modal
import json
import logging
import re
from dotenv import load_dotenv
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional, TypedDict, Union
import time

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

# --- API and Model Configuration from .env ---
AGENT_MODEL = os.getenv('FILTER_AGENT_MODEL', "deepseek-R1") # Updated model name, actual model is in Modal class

MODAL_APP_NAME = "deepseek-gpu-inference-app" # Updated: Name of the Modal app
MODAL_CLASS_NAME = "DeepSeekModel" # Name of the class in the Modal app

# --- General Configuration (can be static or from .env) ---
MAX_TOKENS_RESPONSE = 800  # Or int(os.getenv('FILTER_MAX_TOKENS_RESPONSE', 800))
TEMPERATURE = 0.05       # Or float(os.getenv('FILTER_TEMPERATURE', 0.05)) # Modal class may handle this

# --- Retry, Length, and Scale Configuration from .env ---
MAX_RETRIES_API = int(os.getenv('MAX_RETRIES_API', 3)) # Retained for application-level retries with Modal
BASE_RETRY_DELAY = int(os.getenv('BASE_RETRY_DELAY', 1)) # Retained for application-level retries with Modal
MAX_RETRY_DELAY = int(os.getenv('MAX_RETRY_DELAY', 60))
MAX_SUMMARY_LENGTH = int(os.getenv('MAX_SUMMARY_LENGTH', 2000))
CONFIDENCE_SCALE_MIN = float(os.getenv('CONFIDENCE_SCALE_MIN', 0.0))
CONFIDENCE_SCALE_MAX = float(os.getenv('CONFIDENCE_SCALE_MAX', 1.0))

# --- Static Configuration ---
ALLOWED_TOPICS = [
    "AI Models", "Hardware", "Software", "Robotics", "Compute", "Research", "Open Source",
    "Business", "Startups", "Finance", "Health", "Society", "Ethics", "Regulation",
    "Art & Media", "Environment", "Education", "Security", "Gaming", "Transportation", "Other"
]
IMPORTANT_ENTITIES_FILE = os.path.join(PROJECT_ROOT, 'data', 'important_entities.json')


# --- Type Definitions ---
class AnalysisContentSignals(TypedDict): # More specific for content_signals
    breaking_score: int
    technical_score: int
    hype_score: int
    length_score: float
    entity_matches: List[Dict[str, Union[str, List[str]]]]

class AnalysisMetadata(TypedDict):
    content_signals: AnalysisContentSignals
    entity_categories_matched: int
    processing_timestamp: str

class FilterVerdict(TypedDict):
    importance_level: str
    topic: str
    reasoning_summary: str
    primary_topic_keyword: str
    confidence_score: Optional[Union[int, float]]
    entity_influence_factor: Optional[str]
    factual_basis_score: Optional[Union[int, float]]
    analysis_metadata: AnalysisMetadata

# --- Enhanced Entity Loading with Validation ---
def load_important_entities() -> Tuple[List[str], List[str], List[str], Dict[str, List[str]]]:
    """Loads and validates important entities from the JSON file."""
    try:
        with open(IMPORTANT_ENTITIES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)

        required_keys = ["people", "companies_products"]
        for key in required_keys:
            if key not in data or not isinstance(data[key], list):
                logger.error(f"Invalid structure in {IMPORTANT_ENTITIES_FILE}: missing or invalid '{key}' field")
                return [], [], [], {}

        people = [p.strip().lower() for p in data.get("people", []) if p.strip()]
        companies_products = [cp.strip().lower() for cp in data.get("companies_products", []) if cp.strip()]

        entity_categories = {
            "top_tier_people": [p for p in people if any(name in p for name in ["elon musk", "sam altman", "satya nadella", "jensen huang", "sundar pichai"])],
            "top_tier_companies": [c for c in companies_products if any(name in c for name in ["openai", "google", "microsoft", "nvidia", "tesla", "meta", "apple", "amazon"])],
            "ai_companies": [c for c in companies_products if any(term in c for term in ["ai", "anthropic", "deepmind", "stability"])],
            "all_people": people,
            "all_companies": companies_products
        }

        all_entities = list(set(people + companies_products))
        logger.info(f"Loaded {len(people)} people, {len(companies_products)} companies/products. Top tier: {len(entity_categories['top_tier_people'])} people, {len(entity_categories['top_tier_companies'])} companies.")
        return people, companies_products, all_entities, entity_categories

    except FileNotFoundError:
        logger.error(f"CRITICAL: {IMPORTANT_ENTITIES_FILE} not found. Entity-based filtering will fail.")
        return [], [], [], {}
    except json.JSONDecodeError as e:
        logger.error(f"CRITICAL: JSON decode error in {IMPORTANT_ENTITIES_FILE}: {e}")
        return [], [], [], {}
    except Exception as e:
        logger.error(f"CRITICAL: Unexpected error loading {IMPORTANT_ENTITIES_FILE}: {e}")
        return [], [], [], {}

IMPORTANT_PEOPLE_LIST, IMPORTANT_COMPANIES_PRODUCTS_LIST, ALL_ENTITIES, ENTITY_CATEGORIES = load_important_entities()

# --- Enhanced Content Analysis ---
def analyze_content_signals(title: str, summary: str) -> AnalysisContentSignals:
    """Analyzes content for various signals that indicate importance."""
    combined_text = f"{title} {summary}".lower()

    breaking_indicators = [
        "breaking", "urgent", "just in", "announced", "launches", "releases",
        "reveals", "unveils", "breakthrough", "first", "record", "largest",
        "acquisition", "merger", "ipo", "funding round", "lawsuit", "regulation"
    ]
    technical_indicators = [
        "algorithm", "model", "architecture", "benchmark", "performance",
        "efficiency", "optimization", "training", "inference", "parameters",
        "dataset", "api", "framework", "library", "paper", "research"
    ]
    hype_indicators = [
        "could", "might", "may", "potentially", "rumored", "speculated",
        "opinion", "think", "believe", "predict", "future", "trend",
        "analysis", "review", "comparison", "guide", "tips"
    ]

    signals: AnalysisContentSignals = {
        "breaking_score": sum(1 for indicator in breaking_indicators if indicator in combined_text),
        "technical_score": sum(1 for indicator in technical_indicators if indicator in combined_text),
        "hype_score": sum(1 for indicator in hype_indicators if indicator in combined_text),
        "length_score": min(len(summary) / 500.0, 2.0),
        "entity_matches": []
    }

    for category, entities in ENTITY_CATEGORIES.items():
        matches = []
        for entity in entities:
            pattern = r'\b' + re.escape(entity) + r'\b'
            if re.search(pattern, combined_text):
                matches.append(entity)
        if matches:
            signals["entity_matches"].append({"category": category, "entities": matches})
    return signals

# --- Enhanced Prompts ---
FILTER_PROMPT_SYSTEM = """
You are an **Elite AI News Analyst** with ASI-level judgment capabilities. Your mission is to evaluate news with the precision and insight of a world-class technology analyst, venture capitalist, and AI researcher combined.

**CORE PRINCIPLES:**
1. **Factual Substance Over Hype**: Distinguish verified facts from speculation, opinions, and marketing
2. **Strategic Importance**: Evaluate potential industry impact and strategic significance
3. **Technical Merit**: Assess genuine technical advancement vs incremental updates
4. **Entity Significance**: Weight coverage based on the influence and track record of involved entities
5. **Temporal Relevance**: Consider timing and market context

**CLASSIFICATION HIERARCHY:**
- **Breaking**: Urgent, verified, high-impact events requiring immediate attention
- **Interesting**: Significant developments with clear factual basis and strategic importance
- **Boring**: Everything else, including speculation, routine updates, and low-impact news

**OUTPUT FORMAT**: Provide ONLY valid JSON with no additional text or formatting.
"""

FILTER_PROMPT_USER_TEMPLATE = """
**ANALYSIS TASK**: Evaluate this news article with ASI-level precision.

**ALLOWED TOPICS**: {allowed_topics_list_str}

**CRITICAL ENTITY OVERRIDE RULES**:
**Top-Tier Entities** (Auto-promote to at least "Interesting" if substantive):
- **Key Individuals**: {top_tier_people_str}
- **Key Companies**: {top_tier_companies_str}

**All Important Entities** (Consider for upgrade):
- **People**: {key_individuals_examples_str}
- **Companies/Products**: {key_companies_products_examples_str}

**CLASSIFICATION CRITERIA**:

**Breaking** (Reserved for exceptional events):
- Verified major AI model releases with significant capability jumps
- Critical security vulnerabilities with immediate impact
- Major regulatory decisions affecting the industry
- Large-scale acquisitions/shutdowns with industry-wide implications
- Breakthrough research with immediate practical applications
- Major platform/service outages affecting millions

**Interesting** (Substantive developments):
- Notable product launches from key entities
- Significant funding rounds (>$50M or strategic importance)
- Important research publications with novel findings
- Strategic partnerships between major players
- Regulatory developments affecting specific companies
- Technical achievements with clear advancement
- Key personnel changes at major companies
- Verified performance improvements or benchmarks

**Boring** (Filter out aggressively):
- Speculation, predictions, and opinion pieces
- Routine business updates (earnings, minor partnerships)
- Product reviews and comparisons
- Tutorial/guide content
- Minor feature updates or UI changes
- Unverified rumors or leaks
- Generic industry analysis without specific insights

**CONTENT ANALYSIS SIGNALS**:
{content_signals}

**ARTICLE TO ANALYZE**:
Title: {article_title}
Summary: {article_summary}

**REASONING PROCESS**:
1. **Entity Check**: Does this involve top-tier or important entities? What's their role?
2. **Factual Assessment**: What are the verified facts vs speculation?
3. **Impact Analysis**: What's the potential industry/strategic significance?
4. **Technical Merit**: Is there genuine technical advancement or novelty?
5. **Temporal Context**: Is this time-sensitive or strategically timed?
6. **Final Classification**: Based on the above, what's the appropriate level?

**REQUIRED OUTPUT** (JSON only, confidence_score as float 0.0-1.0, factual_basis_score as float 0.0-1.0):
{{
"importance_level": "string",
"topic": "string",
"reasoning_summary": "string",
"primary_topic_keyword": "string",
"confidence_score": "float",
"entity_influence_factor": "string",
"factual_basis_score": "float"
}}
"""

# --- Enhanced API Call with Exponential Backoff ---
def call_deepseek_api(system_prompt: str, user_prompt: str) -> Optional[str]:
    """Enhanced API call using Modal with exponential backoff retry logic."""
    messages_for_modal = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    for attempt in range(MAX_RETRIES_API):
        try:
            logger.debug(f"Modal API call attempt {attempt + 1}/{MAX_RETRIES_API} for filter agent")
            
            ModelClass = modal.Function.lookup(MODAL_APP_NAME, MODAL_CLASS_NAME)
            if not ModelClass:
                logger.error(f"CRITICAL: Could not look up Modal function {MODAL_APP_NAME}/{MODAL_CLASS_NAME} on attempt {attempt + 1}/{MAX_RETRIES_API}. Ensure it's deployed and names are correct.")
                if attempt == MAX_RETRIES_API - 1:
                    logger.error(f"Modal function lookup failed on final attempt for {MODAL_APP_NAME}/{MODAL_CLASS_NAME}. Returning None.")
                    return None # Explicit return on final attempt after logging
            else:
                model_instance = ModelClass() # Only create instance if lookup succeeded
            
            result = model_instance.generate.remote(
                messages=messages_for_modal,
                max_new_tokens=MAX_TOKENS_RESPONSE,
                temperature=TEMPERATURE, # Pass temperature
                model=AGENT_MODEL # Pass model name
            )
            logger.debug(f"Raw result from Modal for filter agent (attempt {attempt + 1}/{MAX_RETRIES_API}): {str(result)[:1000]}")
            if result and result.get("choices") and result["choices"].get("message") and \
               isinstance(result["choices"]["message"].get("content"), str):
                content = result["choices"]["message"]["content"].strip()
                # The existing logic for stripping markdown fences for JSON
                if content.startswith("```json"):
                    content = content[7:-3].strip()
                elif content.startswith("```"): # More general case
                    content = content[3:-3].strip()
                logger.info(f"Modal call successful for filter agent (Attempt {attempt+1}/{MAX_RETRIES_API})")
                return content
            else:
                logger.error(f"Modal API response missing content or malformed (attempt {attempt + 1}/{MAX_RETRIES_API}): {str(result)[:500]}")
                # Allow retry for malformed content unless it's the last attempt
                if attempt == MAX_RETRIES_API - 1: return None

        except Exception as e:
            logger.exception(f"Error during Modal API call (attempt {attempt + 1}/{MAX_RETRIES_API}): {e}")
            if attempt == MAX_RETRIES_API - 1:
                logger.error("All Modal API attempts failed due to errors.")
                return None
        
        # Common retry delay logic for all handled failures before next attempt
        delay = min(BASE_RETRY_DELAY * (2 ** attempt), MAX_RETRY_DELAY)
        logger.warning(f"Modal API call failed or returned unexpected data (attempt {attempt+1}/{MAX_RETRIES_API}). Retrying in {delay}s.")
        time.sleep(delay)

    logger.error("All Modal API retry attempts exhausted or unrecoverable error.")
    return None

# --- Enhanced Main Agent Function ---
def run_filter_agent(article_data: Dict) -> Dict:
    """Enhanced filter agent with comprehensive analysis."""
    if not isinstance(article_data, dict):
        logger.error("Invalid article_data: not a dictionary")
        return {"filter_error": "Invalid input: not a dictionary", "filter_verdict": None}

    title = article_data.get('title')
    summary = article_data.get('summary')

    if not title or not summary:
        logger.error("Invalid article_data: missing title or summary")
        return {"filter_error": "Invalid input: missing title or summary", "filter_verdict": None, **article_data}


    article_title = str(title).strip()
    article_summary = str(summary).strip()
    article_id = article_data.get('id', 'N/A')

    if len(article_summary) > MAX_SUMMARY_LENGTH:
        logger.warning(f"Truncating summary ({len(article_summary)} > {MAX_SUMMARY_LENGTH} chars) for ID: {article_id}")
        article_summary = article_summary[:MAX_SUMMARY_LENGTH] + "..."

    content_signals = analyze_content_signals(article_title, article_summary)

    allowed_topics_str = "\n".join([f"- {topic}" for topic in ALLOWED_TOPICS])
    top_tier_people_str = ", ".join(ENTITY_CATEGORIES.get("top_tier_people", [])[:10])
    top_tier_companies_str = ", ".join(ENTITY_CATEGORIES.get("top_tier_companies", [])[:15])
    key_individuals_examples_str = ", ".join(IMPORTANT_PEOPLE_LIST[:20]) + (", etc." if len(IMPORTANT_PEOPLE_LIST) > 20 else "")
    key_companies_products_examples_str = ", ".join(IMPORTANT_COMPANIES_PRODUCTS_LIST[:25]) + (", etc." if len(IMPORTANT_COMPANIES_PRODUCTS_LIST) > 25 else "")

    signals_str_list = [
        f"- Breaking indicators: {content_signals['breaking_score']}",
        f"- Technical depth: {content_signals['technical_score']}",
        f"- Hype/speculation signals: {content_signals['hype_score']}",
        f"- Content length score: {content_signals['length_score']:.1f}",
        f"- Entity matches: {len(content_signals['entity_matches'])} categories"
    ]
    signals_str = "\n".join(signals_str_list)


    try:
        user_prompt = FILTER_PROMPT_USER_TEMPLATE.format(
            article_title=article_title,
            article_summary=article_summary,
            allowed_topics_list_str=allowed_topics_str,
            top_tier_people_str=top_tier_people_str,
            top_tier_companies_str=top_tier_companies_str,
            key_individuals_examples_str=key_individuals_examples_str,
            key_companies_products_examples_str=key_companies_products_examples_str,
            content_signals=signals_str
        )
    except KeyError as e:
        logger.exception(f"Prompt template formatting error: {e}")
        article_data['filter_verdict'] = None
        article_data['filter_error'] = f"Prompt template error: {e}"
        return article_data

    logger.info(f"Analyzing article ID: {article_id} | Title: {article_title[:80]}...")
    raw_response = call_deepseek_api(FILTER_PROMPT_SYSTEM, user_prompt)

    if not raw_response:
        logger.error(f"Filter agent API call failed for ID: {article_id}")
        article_data['filter_verdict'] = None
        article_data['filter_error'] = "API call failed"
        return article_data

    try:
        # Explicitly cast to FilterVerdict after loading. Relies on LLM adhering to structure.
        parsed_verdict = json.loads(raw_response)
        filter_verdict: FilterVerdict = parsed_verdict # type: ignore

        required_keys = ["importance_level", "topic", "reasoning_summary", "primary_topic_keyword"]
        if not all(k in filter_verdict for k in required_keys): # Fix: Changed 'required_verdict' to 'required_keys'
            missing_keys = [k for k in required_keys if k not in filter_verdict]
            raise ValueError(f"Missing required keys: {missing_keys}")

        valid_levels = ["Breaking", "Interesting", "Boring"]
        if filter_verdict['importance_level'] not in valid_levels:
            logger.warning(f"Invalid importance_level '{filter_verdict['importance_level']}' for ID {article_id}. Defaulting to 'Boring'.")
            filter_verdict['importance_level'] = "Boring"
        
        if filter_verdict['topic'] not in ALLOWED_TOPICS:
            logger.warning(f"Invalid topic '{filter_verdict['topic']}' for ID {article_id}. Defaulting to 'Other'.")
            filter_verdict['topic'] = "Other"


        # Validate and normalize confidence score
        raw_confidence = filter_verdict.get('confidence_score')
        if raw_confidence is not None:
            try:
                confidence = float(raw_confidence)
                if not (CONFIDENCE_SCALE_MIN <= confidence <= CONFIDENCE_SCALE_MAX):
                     # Attempt normalization if it looks like a 1-10 scale was used
                    if CONFIDENCE_SCALE_MIN < confidence <= CONFIDENCE_SCALE_MAX * 10:
                        confidence = confidence / 10.0
                        logger.warning(f"Normalized confidence score from {raw_confidence} to {confidence:.2f} for ID {article_id}")
                    else: # Out of expected range even for 1-10, clamp it
                        logger.warning(f"Confidence score {raw_confidence} out of expected range [0-1] or [0-10]. Clamping.")
                filter_verdict['confidence_score'] = max(CONFIDENCE_SCALE_MIN, min(confidence, CONFIDENCE_SCALE_MAX))
            except (ValueError, TypeError):
                logger.warning(f"Invalid confidence_score '{raw_confidence}' for ID {article_id}. Setting to None.")
                filter_verdict['confidence_score'] = None
        
        # Validate and normalize factual_basis_score
        raw_factual_score = filter_verdict.get('factual_basis_score')
        if raw_factual_score is not None:
            try:
                factual_score = float(raw_factual_score)
                if not (CONFIDENCE_SCALE_MIN <= factual_score <= CONFIDENCE_SCALE_MAX):
                    if CONFIDENCE_SCALE_MIN < factual_score <= CONFIDENCE_SCALE_MAX * 10:
                        factual_score = factual_score / 10.0
                        logger.warning(f"Normalized factual_basis_score from {raw_factual_score} to {factual_score:.2f} for ID {article_id}")
                    else:
                        logger.warning(f"Factual_basis_score {raw_factual_score} out of expected range [0-1] or [0-10]. Clamping.")
                filter_verdict['factual_basis_score'] = max(CONFIDENCE_SCALE_MIN, min(factual_score, CONFIDENCE_SCALE_MAX))
            except (ValueError, TypeError):
                logger.warning(f"Invalid factual_basis_score '{raw_factual_score}' for ID {article_id}. Setting to None.")
                filter_verdict['factual_basis_score'] = None

        # Ensure analysis_metadata structure is present if not provided by LLM
        # and then populate it.
        if 'analysis_metadata' not in filter_verdict or not isinstance(filter_verdict.get('analysis_metadata'), dict):
             filter_verdict['analysis_metadata'] = {} # type: ignore

        filter_verdict['analysis_metadata']['content_signals'] = content_signals
        filter_verdict['analysis_metadata']['entity_categories_matched'] = len(content_signals['entity_matches'])
        filter_verdict['analysis_metadata']['processing_timestamp'] = datetime.now(timezone.utc).isoformat()


        logger.info(f"Filter result for ID {article_id}: {filter_verdict['importance_level']} | "
                   f"Topic: {filter_verdict['topic']} | Confidence: {filter_verdict.get('confidence_score', 'N/A')}")

        article_data['filter_verdict'] = filter_verdict
        article_data['filter_error'] = None
        article_data['filtered_at_iso'] = datetime.now(timezone.utc).isoformat()
        return article_data

    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error for ID {article_id}: {e}")
        logger.debug(f"Raw response: {raw_response}")
        article_data['filter_verdict'] = None
        article_data['filter_error'] = "Invalid JSON response"
        return article_data
    except ValueError as e: # Catches missing keys from our validation
        logger.error(f"Validation error for ID {article_id}: {e}")
        logger.debug(f"Parsed verdict that failed validation: {parsed_verdict if 'parsed_verdict' in locals() else 'N/A'}")
        article_data['filter_verdict'] = None
        article_data['filter_error'] = f"Response validation failed: {e}"
        return article_data
    except Exception as e:
        logger.exception(f"Unexpected error processing response for ID {article_id}: {e}")
        article_data['filter_verdict'] = None
        article_data['filter_error'] = f"Processing error: {str(e)}"
        return article_data

# --- Enhanced Testing ---
if __name__ == "__main__":
    logging.getLogger().setLevel(logging.DEBUG) # Global logger level
    logger.setLevel(logging.DEBUG) # This specific module's logger level

    test_cases = [
        {
            'id': 'test-breaking-001',
            'title': "OpenAI Releases GPT-5 with Unprecedented 10x Performance Improvement",
            'summary': "OpenAI today officially launched GPT-5, demonstrating significant improvements across all benchmarks with 90% accuracy on complex reasoning tasks. The model features a new architecture achieving 10x efficiency gains. CEO Sam Altman confirmed commercial availability within 30 days.",
        },
        {
            'id': 'test-interesting-002',
            'title': "Elon Musk Announces Tesla's New Neural Network Chip for Autonomous Driving",
            'summary': "At Tesla's AI Day, Elon Musk unveiled the D1 chip, claiming 3x performance improvement over current hardware. The chip will power the next generation of Tesla's Full Self-Driving capabilities with rollout planned for Q4 2025.",
        },
        {
            'id': 'test-boring-003',
            'title': "Best Productivity Apps for Remote Workers in 2025",
            'summary': "A comprehensive review of the top productivity applications including Notion, Microsoft Teams, and Slack. We tested each app's features and provide recommendations for different workflow needs.",
        },
        {
            'id': 'test-edge-case-004', # Skeptical claims
            'title': "Meta AI Researcher Claims Breakthrough in Quantum Computing for ML",
            'summary': "A researcher at Meta's AI lab published a paper suggesting potential quantum advantages for machine learning, though the work has not been peer-reviewed and other experts express skepticism about the claims. The paper details a novel qubit stabilization technique.",
        },
        {
            'id': 'test-short-summary-005',
            'title': "Google announces minor update to Search algorithm",
            'summary': "Google confirmed a small tweak. Impact unknown.",
        },
        {
            'id': 'test-no-entities-006',
            'title': "New Open Source LLM Framework Released by Independent Devs",
            'summary': "A group of independent developers today released 'OpenLLMFramework', a new Python library designed to simplify LLM training and deployment. It is available on GitHub and aims to rival existing proprietary solutions.",
        }
    ]

    logger.info("\n=== ENHANCED FILTER AGENT TEST SUITE ===")

    for i, test_case in enumerate(test_cases, 1):
        logger.info(f"\n--- Test Case {i}: {test_case['id']} ---")
        # Create a copy to avoid modifying the original test_case dict if run_filter_agent modifies it
        result_data = run_filter_agent(test_case.copy())

        if result_data.get('filter_verdict'):
            verdict = result_data['filter_verdict']
            print(f"VERDICT: {verdict.get('importance_level')} | TOPIC: {verdict.get('topic')}")
            print(f"REASONING: {verdict.get('reasoning_summary')}")
            print(f"CONFIDENCE: {verdict.get('confidence_score', 'N/A')}")
            print(f"FACTUAL BASIS: {verdict.get('factual_basis_score', 'N/A')}")
            if verdict.get('analysis_metadata'):
                print(f"ENTITY MATCHES: {verdict['analysis_metadata'].get('entity_categories_matched')}")
        else:
            print(f"ERROR: {result_data.get('filter_error', 'Unknown error')}")

        print("-" * 60)

    logger.info("\n=== TEST SUITE COMPLETE ===")