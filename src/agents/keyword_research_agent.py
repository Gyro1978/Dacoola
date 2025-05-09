# src/agents/keyword_research_agent.py (1/1) - FULL SCRIPT with YAML config loader

import os
import sys
import json
import logging
import re
from dotenv import load_dotenv

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

# --- Load Environment Variables ---
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)

# --- Configuration ---
TARGET_NUM_KEYWORDS = 5 # How many secondary keywords to aim for
MIN_RELEVANCE_SCORE = 0.5 # Simple threshold for keyword selection simulation
# Set to True to attempt live API calls, False to force dummy data for testing.
# Ensure credentials in google-ads.yaml are correct if True.
ENABLE_LIVE_ADS_API = True

# Path to the google-ads.yaml configuration file (can be overridden by env var)
DEFAULT_GOOGLE_ADS_YAML_PATH = os.path.join(PROJECT_ROOT, 'google-ads.yaml')
GOOGLE_ADS_CONFIG_PATH = os.getenv('GOOGLE_ADS_CONFIGURATION_FILE_PATH', DEFAULT_GOOGLE_ADS_YAML_PATH)


# --- Helper Function for API Interaction ---
def _fetch_keyword_ideas_from_ads_api(seed_keyword, target_url=None):
    """
    Fetches keyword ideas from Google Ads API using KeywordPlanIdeaService.
    Requires 'google-ads' library and proper authentication setup via google-ads.yaml.
    Falls back to dummy data if live API is disabled or fails.
    """
    if not ENABLE_LIVE_ADS_API:
        logger.warning("Live Google Ads API call disabled by ENABLE_LIVE_ADS_API flag. Using dummy data.")
        return _get_dummy_keyword_ideas(seed_keyword)

    logger.info(f"Attempting Google Ads API call for seed: '{seed_keyword}' using config: {GOOGLE_ADS_CONFIG_PATH}")

    if not os.path.exists(GOOGLE_ADS_CONFIG_PATH):
        logger.error(f"Google Ads YAML configuration file not found at: {GOOGLE_ADS_CONFIG_PATH}. Cannot fetch live keywords. Falling back to dummy data.")
        return _get_dummy_keyword_ideas(seed_keyword)

    try:
        from google.ads.googleads.client import GoogleAdsClient
        from google.ads.googleads.errors import GoogleAdsException

        logger.debug(f"Initializing GoogleAdsClient from storage: {GOOGLE_ADS_CONFIG_PATH}...")
        # The client will read all necessary credentials from the YAML file.
        googleads_client = GoogleAdsClient.load_from_storage(path=GOOGLE_ADS_CONFIG_PATH, version="v17")
        logger.debug("GoogleAdsClient initialized.")

        keyword_plan_idea_service = googleads_client.get_service("KeywordPlanIdeaService")
        
        # Login Customer ID is read from the YAML file by the client library
        # but we might need it for logging or if a service requires it explicitly.
        # The client object itself doesn't directly expose it easily after load_from_storage.
        # We'll assume the YAML is correctly configured.
        # For logging purposes, you could re-read it from YAML or trust it's set.
        # For now, we'll proceed as the client should handle it internally.

        # --- Build the API Request ---
        request = googleads_client.get_type("GenerateKeywordIdeasRequest")
        # request.customer_id = customer_id # The client handles this if login_customer_id is in YAML

        # Language ID for English: "1000".
        # See https://developers.google.com/google-ads/api/reference/data/codes-formats#languages
        request.language = googleads_client.service("GoogleAdsService").language_constant_path("1000")

        # Geo Target ID for United States: "2840".
        # See https://developers.google.com/google-ads/api/reference/data/geotargets
        request.geo_target_constants.append(
            googleads_client.service("GeoTargetConstantService").geo_target_constant_path("2840")
        )
        request.include_adult_keywords = False
        request.keyword_plan_network = googleads_client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH_AND_PARTNERS # Broader search

        # --- Define Seed ---
        if seed_keyword:
            request.keyword_seed.keywords.append(seed_keyword)
        if target_url: # Optionally use URL to refine ideas
             request.url_seed.url = target_url
        if not request.keyword_seed.keywords and not request.url_seed.url:
             logger.error("No seed keyword or URL provided. Cannot generate ideas via API.")
             return _get_dummy_keyword_ideas(seed_keyword)

        logger.info(f"Sending keyword ideas request to Google Ads API for seed: '{seed_keyword}'...")
        response = keyword_plan_idea_service.generate_keyword_ideas(request=request)
        logger.info("Received response from Google Ads API.")

        ideas = []
        for result in response.results:
            metrics = result.keyword_idea_metrics
            avg_searches = metrics.avg_monthly_searches if metrics and metrics.HasField("avg_monthly_searches") else None
            competition_enum_val = metrics.competition if metrics and metrics.HasField("competition") else None
            competition_level = googleads_client.enums.KeywordPlanCompetitionLevelEnum(competition_enum_val).name if competition_enum_val is not None else 'UNKNOWN'

            ideas.append({
                'text': result.text,
                'avg_monthly_searches': avg_searches,
                'competition_level': competition_level,
            })
        logger.info(f"Successfully processed {len(ideas)} keyword ideas from Google Ads API.")
        if not ideas:
            logger.warning(f"Google Ads API returned 0 keyword ideas for seed '{seed_keyword}'. Check seed or targeting.")
        return ideas

    except GoogleAdsException as ex:
        logger.error(f"Google Ads API request failed with errors:")
        for error in ex.failure.errors:
            logger.error(f"\tError code: {error.error_code.name if hasattr(error.error_code, 'name') else error.error_code}") # Access .name if it's an enum
            logger.error(f"\tMessage: {error.message}")
            if error.location:
                for field_path_element in error.location.field_path_elements:
                    logger.error(f"\t\tField: {field_path_element.field_name}, Index: {field_path_element.index if field_path_element.HasField('index') else 'N/A'}")
            if error.details: logger.error(f"\tDetails: {error.details}")
        logger.error("Falling back to dummy data due to GoogleAdsException.")
        return _get_dummy_keyword_ideas(seed_keyword)
    except ImportError:
        logger.error("Google Ads library ('google-ads') is not installed. Run 'pip install google-ads'. Falling back to dummy data.")
        return _get_dummy_keyword_ideas(seed_keyword)
    except Exception as e:
        logger.exception(f"Unexpected error during Google Ads API call: {e}. Falling back to dummy data.")
        return _get_dummy_keyword_ideas(seed_keyword)

# --- Helper Function for Dummy Data ---
def _get_dummy_keyword_ideas(seed_keyword):
    logger.warning(f"Using dummy keyword data for seed: '{seed_keyword}'")
    dummy_ideas = [
        {'text': f'{seed_keyword} trends 2025', 'avg_monthly_searches': 1500, 'competition_level': 'MEDIUM'},
        {'text': f'best {seed_keyword} platforms', 'avg_monthly_searches': 800, 'competition_level': 'HIGH'},
        {'text': f'how does {seed_keyword} work', 'avg_monthly_searches': 500, 'competition_level': 'LOW'},
        {'text': f'{seed_keyword} impact analysis', 'avg_monthly_searches': 1200, 'competition_level': 'MEDIUM'},
        {'text': f'{seed_keyword} future applications', 'avg_monthly_searches': 300, 'competition_level': 'LOW'},
        {'text': f'{seed_keyword} alternatives comparison', 'avg_monthly_searches': 600, 'competition_level': 'HIGH'},
        {'text': f'latest on {seed_keyword} advancements', 'avg_monthly_searches': 2000, 'competition_level': 'MEDIUM'},
        {'text': f'introduction to advanced {seed_keyword}', 'avg_monthly_searches': 400, 'competition_level': 'LOW'},
        {'text': 'unrelated but high volume term', 'avg_monthly_searches': 10000, 'competition_level': 'LOW'},
        {'text': f'{seed_keyword}', 'avg_monthly_searches': 5000, 'competition_level': 'MEDIUM'},
        {'text': f'ethical implications of {seed_keyword}', 'avg_monthly_searches': 150, 'competition_level': 'LOW'},
        {'text': f'top providers of {seed_keyword} solutions', 'avg_monthly_searches': 250, 'competition_level': 'MEDIUM'},
    ]
    return dummy_ideas

# --- Keyword Processing/Selection Logic ---
def _calculate_relevance(keyword_text, primary_keyword):
    primary_words = set(primary_keyword.lower().split())
    keyword_words = set(keyword_text.lower().split())
    if not primary_words: return 0.0
    common_words = primary_words.intersection(keyword_words)
    score = len(common_words) / len(primary_words)
    if primary_keyword.lower() in keyword_text.lower(): score = max(score, 0.85) # Slightly higher boost
    if len(keyword_words) > len(primary_words) + 4: score *= 0.85 # Penalize longer keywords more
    return score

def _select_best_keywords(ideas, primary_keyword, num_keywords=TARGET_NUM_KEYWORDS):
    if not ideas: return []
    selected_keywords = []
    scored_ideas = []
    for idea in ideas:
        keyword_text = idea.get('text')
        if not keyword_text or keyword_text.lower() == primary_keyword.lower(): continue
        relevance = _calculate_relevance(keyword_text, primary_keyword)
        if relevance < MIN_RELEVANCE_SCORE: logger.debug(f"Skipping '{keyword_text}': low relevance ({relevance:.2f})"); continue
        
        score = relevance * 1000 # Higher base for relevance
        volume = idea.get('avg_monthly_searches')
        if isinstance(volume, int):
            if volume > 10000: score += 10 # Very high volume
            elif volume > 1000: score += 30 # Good volume
            elif volume > 100: score += 15  # Decent volume
            else: score += 5              # Low volume
        
        competition = idea.get('competition_level')
        if competition == 'HIGH': score -= 30
        elif competition == 'MEDIUM': score -=10
        elif competition == 'LOW': score += 20
        
        if len(keyword_text.split()) == len(primary_keyword.split()) and relevance > 0.9: score *= 0.85
        scored_ideas.append({'text': keyword_text, 'score': score, 'volume': volume, 'relevance': relevance, 'competition': competition})

    scored_ideas.sort(key=lambda x: x['score'], reverse=True)
    logger.debug(f"Top scored keyword ideas for '{primary_keyword}':")
    for i, idea_info in enumerate(scored_ideas[:10]): logger.debug(f"  {i+1}. '{idea_info['text']}' (Score: {idea_info['score']:.0f}, Vol: {idea_info['volume']}, Rel: {idea_info['relevance']:.2f}, Comp: {idea_info['competition']})")

    seen = set()
    for idea in scored_ideas:
        kw = idea['text']
        if kw.lower() not in seen:
            selected_keywords.append(kw)
            seen.add(kw.lower())
            if len(selected_keywords) >= num_keywords: break
    logger.info(f"Selected {len(selected_keywords)} keywords for '{primary_keyword}'.")
    return selected_keywords

# --- Main Agent Function ---
def run_keyword_research_agent(article_data):
    article_id = article_data.get('id', 'N/A')
    logger.info(f"Running Keyword Research Agent for article ID: {article_id}...")
    primary_keyword = article_data.get('filter_verdict', {}).get('primary_topic_keyword')
    if not primary_keyword:
        logger.warning(f"No primary_topic_keyword for ID {article_id}. KW research skipped.")
        article_data['researched_keywords'] = []
        article_data['keyword_agent_error'] = "Missing primary keyword input"
        return article_data
    article_url = article_data.get('link')
    keyword_ideas = _fetch_keyword_ideas_from_ads_api(primary_keyword, target_url=article_url)
    if not keyword_ideas:
        logger.warning(f"No keyword ideas received (API or dummy) for {primary_keyword}. Using primary only.")
        selected_keywords = []
    else:
        selected_keywords = _select_best_keywords(keyword_ideas, primary_keyword, num_keywords=TARGET_NUM_KEYWORDS)

    final_keyword_list = [primary_keyword] # Always include primary
    for kw in selected_keywords: # Add unique secondary keywords
        if kw.lower() != primary_keyword.lower() and kw not in final_keyword_list :
            final_keyword_list.append(kw)

    article_data['researched_keywords'] = final_keyword_list
    article_data['keyword_agent_error'] = None
    logger.info(f"Keyword research complete for ID {article_id}. Final keywords: {final_keyword_list}")
    return article_data

# --- Standalone Execution (for testing) ---
if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO) # Set root logger to INFO for less verbose testing
    logger.setLevel(logging.DEBUG) # Keep this agent's logger at DEBUG for detailed output

    # To test with live API, ensure ENABLE_LIVE_ADS_API = True and YAML is configured
    # By default, it will attempt live and fallback to dummy if it fails or if ENABLE_LIVE_ADS_API is False.
    # ENABLE_LIVE_ADS_API = False # Force dummy data for this specific test run if needed

    test_article_data = {
        'id': 'test-kw-live-001', 'title': "New AI Chipset Accelerates Deep Learning",
        'link': "https://example.com/new-ai-chipset", # Example URL for context
        'filter_verdict': { 'primary_topic_keyword': 'AI chipset deep learning' }
    }
    logger.info("\n--- Running Keyword Research Agent Standalone Test (Live API Attempt) ---")
    result_data = run_keyword_research_agent(test_article_data.copy())
    print("\n--- Keyword Research Results ---")
    if result_data.get('keyword_agent_error'): print(f"Error: {result_data['keyword_agent_error']}")
    else: print(f"Researched Keywords: {result_data.get('researched_keywords')}")

    # Test with a different primary keyword
    test_article_data_2 = {
        'id': 'test-kw-live-002', 'title': "Future of Autonomous Driving Systems",
        'link': "https://example.com/autonomous-driving",
        'filter_verdict': { 'primary_topic_keyword': 'autonomous driving technology' }
    }
    logger.info("\n--- Running Keyword Research Agent Standalone Test 2 (Live API Attempt) ---")
    result_data_2 = run_keyword_research_agent(test_article_data_2.copy())
    print("\n--- Keyword Research Results 2 ---")
    if result_data_2.get('keyword_agent_error'): print(f"Error: {result_data_2['keyword_agent_error']}")
    else: print(f"Researched Keywords: {result_data_2.get('researched_keywords')}")

    logger.info("--- Keyword Research Agent Standalone Test Complete ---")