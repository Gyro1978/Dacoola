# src/agents/keyword_research_agent.py (1/1) - FULL SCRIPT (No Dummy Data Fallback)

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
TARGET_NUM_KEYWORDS = 5
MIN_RELEVANCE_SCORE = 0.5
ENABLE_LIVE_ADS_API = True # This now effectively means: try live, or fail (no dummy)

DEFAULT_GOOGLE_ADS_YAML_PATH = os.path.join(PROJECT_ROOT, 'google-ads.yaml')
GOOGLE_ADS_CONFIG_PATH = os.getenv('GOOGLE_ADS_CONFIGURATION_FILE_PATH', DEFAULT_GOOGLE_ADS_YAML_PATH)


# --- Helper Function for API Interaction ---
def _fetch_keyword_ideas_from_ads_api(seed_keyword, target_url=None):
    """
    Fetches keyword ideas from Google Ads API.
    Returns a list of keyword ideas or None/empty list on failure.
    """
    if not ENABLE_LIVE_ADS_API:
        logger.warning("Live Google Ads API call disabled by ENABLE_LIVE_ADS_API flag. No keywords will be fetched.")
        return [] # Return empty list instead of dummy data

    logger.info(f"Attempting Google Ads API call for seed: '{seed_keyword}' using config: {GOOGLE_ADS_CONFIG_PATH}")

    if not os.path.exists(GOOGLE_ADS_CONFIG_PATH):
        logger.error(f"Google Ads YAML configuration file not found at: {GOOGLE_ADS_CONFIG_PATH}. Cannot fetch live keywords.")
        return [] # Return empty list

    try:
        from google.ads.googleads.client import GoogleAdsClient
        from google.ads.googleads.errors import GoogleAdsException

        logger.debug(f"Initializing GoogleAdsClient from storage: {GOOGLE_ADS_CONFIG_PATH}...")
        googleads_client = GoogleAdsClient.load_from_storage(path=GOOGLE_ADS_CONFIG_PATH, version="v17")
        logger.debug("GoogleAdsClient initialized.")

        keyword_plan_idea_service = googleads_client.get_service("KeywordPlanIdeaService")

        request = googleads_client.get_type("GenerateKeywordIdeasRequest")
        request.language = googleads_client.service("GoogleAdsService").language_constant_path("1000") # English
        request.geo_target_constants.append(
            googleads_client.service("GeoTargetConstantService").geo_target_constant_path("2840") # United States
        )
        request.include_adult_keywords = False
        request.keyword_plan_network = googleads_client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH_AND_PARTNERS

        if seed_keyword:
            request.keyword_seed.keywords.append(seed_keyword)
        if target_url:
             request.url_seed.url = target_url
        if not request.keyword_seed.keywords and not request.url_seed.url:
             logger.error("No seed keyword or URL provided. Cannot generate ideas via API.")
             return [] # Return empty list

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
            logger.warning(f"Google Ads API returned 0 keyword ideas for seed '{seed_keyword}'.")
        return ideas

    except GoogleAdsException as ex:
        logger.error(f"Google Ads API request failed with errors:")
        for error in ex.failure.errors:
            logger.error(f"\tError code: {error.error_code.name if hasattr(error.error_code, 'name') else error.error_code}")
            logger.error(f"\tMessage: {error.message}")
            # ... (rest of error logging)
        logger.error("No keywords fetched due to GoogleAdsException.")
        return [] # Return empty list on API exception
    except ImportError:
        logger.error("Google Ads library ('google-ads') is not installed. Run 'pip install google-ads'. No keywords fetched.")
        return [] # Return empty list
    except Exception as e:
        logger.exception(f"Unexpected error during Google Ads API call: {e}. No keywords fetched.")
        return [] # Return empty list on other exceptions

# --- Keyword Processing/Selection Logic ---
def _calculate_relevance(keyword_text, primary_keyword):
    primary_words = set(primary_keyword.lower().split())
    keyword_words = set(keyword_text.lower().split())
    if not primary_words: return 0.0
    common_words = primary_words.intersection(keyword_words)
    score = len(common_words) / len(primary_words)
    if primary_keyword.lower() in keyword_text.lower(): score = max(score, 0.85)
    if len(keyword_words) > len(primary_words) + 4: score *= 0.85
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
        
        score = relevance * 1000
        volume = idea.get('avg_monthly_searches')
        if isinstance(volume, int):
            if volume > 10000: score += 10
            elif volume > 1000: score += 30
            elif volume > 100: score += 15
            else: score += 5
        
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
    logger.info(f"Selected {len(selected_keywords)} secondary keywords for '{primary_keyword}'.")
    return selected_keywords

# --- Main Agent Function ---
def run_keyword_research_agent(article_data):
    article_id = article_data.get('id', 'N/A')
    logger.info(f"Running Keyword Research Agent for article ID: {article_id}...")
    primary_keyword = article_data.get('filter_verdict', {}).get('primary_topic_keyword')

    if not primary_keyword:
        logger.warning(f"No primary_topic_keyword for ID {article_id}. Keyword research skipped.")
        article_data['researched_keywords'] = [] # Ensure it's an empty list
        article_data['keyword_agent_error'] = "Missing primary keyword input"
        return article_data

    article_url = article_data.get('link') # This is the original source URL
    keyword_ideas = _fetch_keyword_ideas_from_ads_api(primary_keyword, target_url=article_url)

    if not keyword_ideas: # This now means API failed or returned no relevant ideas
        logger.warning(f"No keyword ideas received from API for '{primary_keyword}'. Using only primary keyword.")
        selected_secondary_keywords = []
    else:
        selected_secondary_keywords = _select_best_keywords(keyword_ideas, primary_keyword, num_keywords=TARGET_NUM_KEYWORDS)

    final_keyword_list = [primary_keyword] # Always include primary
    for kw in selected_secondary_keywords: # Add unique secondary keywords
        if kw.lower() != primary_keyword.lower() and kw not in final_keyword_list :
            final_keyword_list.append(kw)

    article_data['researched_keywords'] = final_keyword_list
    article_data['keyword_agent_error'] = None if keyword_ideas else "Keyword API call failed or returned no ideas" # More specific error if API failed
    logger.info(f"Keyword research complete for ID {article_id}. Final keywords: {final_keyword_list}")
    return article_data

# --- Standalone Execution (for testing) ---
if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)
    logger.setLevel(logging.DEBUG)

    # Test scenario: ENABLE_LIVE_ADS_API = True and YAML is configured correctly
    # If API fails or no YAML, it should now log errors and return an empty list for 'researched_keywords' (or just primary)

    test_article_data_live_attempt = {
        'id': 'test-kw-no-dummy-001', 'title': "Innovations in Quantum Computing Chips",
        'link': "https://example.com/quantum-innovations",
        'filter_verdict': { 'primary_topic_keyword': 'quantum computing chips' }
    }
    logger.info("\n--- Running Keyword Research Agent Standalone Test (NO Dummy Data Fallback) ---")
    result_data_live = run_keyword_research_agent(test_article_data_live_attempt.copy())
    print("\n--- Keyword Research Results (Live Attempt) ---")
    if result_data_live.get('keyword_agent_error'):
        print(f"Error: {result_data_live['keyword_agent_error']}")
    print(f"Researched Keywords: {result_data_live.get('researched_keywords')}")

    # Test scenario: Missing primary keyword
    test_article_data_no_primary = {
        'id': 'test-kw-no-primary-002', 'title': "Some News Article",
        'link': "https://example.com/some-news",
        'filter_verdict': { 'primary_topic_keyword': None } # Simulating missing primary
    }
    logger.info("\n--- Running Keyword Research Agent Test (Missing Primary Keyword) ---")
    result_data_no_primary = run_keyword_research_agent(test_article_data_no_primary.copy())
    print("\n--- Keyword Research Results (Missing Primary) ---")
    if result_data_no_primary.get('keyword_agent_error'):
        print(f"Error: {result_data_no_primary['keyword_agent_error']}")
    print(f"Researched Keywords: {result_data_no_primary.get('researched_keywords')}")


    logger.info("--- Keyword Research Agent Standalone Test Complete ---")