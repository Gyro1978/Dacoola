# src/agents/keyword_research_agent.py (1/1) - With Real API Integration (Requires Setup!)

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

# --- Google Ads API Credentials & Config (MUST BE SET IN .env or google-ads.yaml) ---
# Standard names often used by the library when loading from environment:
GOOGLE_ADS_DEVELOPER_TOKEN = os.getenv('GOOGLE_ADS_DEVELOPER_TOKEN')
GOOGLE_ADS_LOGIN_CUSTOMER_ID = os.getenv('GOOGLE_ADS_LOGIN_CUSTOMER_ID') # Account ID *without* hyphens
GOOGLE_ADS_CLIENT_ID = os.getenv('GOOGLE_ADS_CLIENT_ID') # Your OAuth Client ID
GOOGLE_ADS_CLIENT_SECRET = os.getenv('GOOGLE_ADS_CLIENT_SECRET') # Your OAuth Client Secret
GOOGLE_ADS_REFRESH_TOKEN = os.getenv('GOOGLE_ADS_REFRESH_TOKEN') # Your OAuth Refresh Token
# OR set GOOGLE_ADS_YAML_FILE path in .env if using YAML config

# --- Configuration ---
TARGET_NUM_KEYWORDS = 5 # How many secondary keywords to aim for
MIN_RELEVANCE_SCORE = 0.5 # Simple threshold for keyword selection simulation
ENABLE_LIVE_ADS_API = True # Set to False to force dummy data for testing

# --- Helper Function for API Interaction ---
def _fetch_keyword_ideas_from_ads_api(seed_keyword, target_url=None):
    """
    Fetches keyword ideas from Google Ads API using KeywordPlanIdeaService.
    Requires 'google-ads' library and proper authentication setup.
    Falls back to dummy data if live API is disabled or fails.
    """
    if not ENABLE_LIVE_ADS_API:
        logger.warning("Live Google Ads API call disabled by ENABLE_LIVE_ADS_API flag. Using dummy data.")
        return _get_dummy_keyword_ideas(seed_keyword)

    logger.info(f"Attempting Google Ads API call for seed: '{seed_keyword}'")

    # Check for essential configuration
    if not all([GOOGLE_ADS_DEVELOPER_TOKEN, GOOGLE_ADS_LOGIN_CUSTOMER_ID,
                GOOGLE_ADS_CLIENT_ID, GOOGLE_ADS_CLIENT_SECRET, GOOGLE_ADS_REFRESH_TOKEN]):
        logger.error("Google Ads API credentials (Dev Token, Login Customer ID, OAuth credentials) missing in environment. Falling back to dummy data.")
        return _get_dummy_keyword_ideas(seed_keyword)

    try:
        # --- Attempt to import and use the google-ads library ---
        from google.ads.googleads.client import GoogleAdsClient
        from google.ads.googleads.errors import GoogleAdsException

        # Configure client using environment variables. Ensure variable names match what the library expects
        # or use a google-ads.yaml file pointed to by GOOGLE_ADS_YAML_FILE env var.
        # Example env vars the library looks for:
        # GOOGLE_ADS_DEVELOPER_TOKEN, GOOGLE_ADS_LOGIN_CUSTOMER_ID, GOOGLE_ADS_CLIENT_ID,
        # GOOGLE_ADS_CLIENT_SECRET, GOOGLE_ADS_REFRESH_TOKEN
        # Make sure these names are used in your .env file!
        logger.debug("Initializing GoogleAdsClient from environment...")
        googleads_client = GoogleAdsClient.load_from_env(version="v17") # Ensure you use a current API version
        logger.debug("GoogleAdsClient initialized.")

        keyword_plan_idea_service = googleads_client.get_service("KeywordPlanIdeaService") # Removed version=, uses client's version
        customer_id = str(GOOGLE_ADS_LOGIN_CUSTOMER_ID).replace('-', '') # Ensure no hyphens

        # --- Build the API Request ---
        request = googleads_client.get_type("GenerateKeywordIdeasRequest")
        request.customer_id = customer_id
        # Language ID for English: 1000. Find others here: https://developers.google.com/google-ads/api/reference/data/codes-formats#languages
        request.language_id = 1000
        # Geo Target ID for United States: 2840. Find others here: https://developers.google.com/google-ads/api/reference/data/geotargets
        request.geo_target_constants.append("geoTargetConstants/2840") # Example: Target US
        request.include_adult_keywords = False
        request.keyword_plan_network = googleads_client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH # Target Google Search

        # --- Define Seed ---
        # Prioritize keyword seed, optionally add URL seed
        if seed_keyword:
            request.keyword_seed.keywords.append(seed_keyword)
        # if target_url: # Add URL seed if a relevant article URL is available
        #     request.url_seed.url = target_url
        if not request.keyword_seed.keywords and not request.url_seed.url:
             logger.error("No seed keyword or URL provided. Cannot generate ideas.")
             return _get_dummy_keyword_ideas(seed_keyword) # Fallback

        # --- Make the API Call ---
        logger.info(f"Sending keyword ideas request to Google Ads API (Customer ID: {customer_id})...")
        response = keyword_plan_idea_service.generate_keyword_ideas(request=request)
        logger.info("Received response from Google Ads API.")

        # --- Process Results ---
        ideas = []
        for result in response.results:
            metrics = result.keyword_idea_metrics
            # Extract metrics carefully, checking for existence
            avg_searches = metrics.avg_monthly_searches if metrics and metrics.HasField("avg_monthly_searches") else None
            competition_enum = metrics.competition if metrics and metrics.HasField("competition") else None
            competition_level = googleads_client.enums.KeywordPlanCompetitionLevelEnum(competition_enum).name if competition_enum is not None else 'UNKNOWN'

            ideas.append({
                'text': result.text,
                'avg_monthly_searches': avg_searches,
                'competition_level': competition_level,
            })
        logger.info(f"Successfully processed {len(ideas)} keyword ideas from Google Ads API.")
        return ideas

    except GoogleAdsException as ex:
        logger.error(f"Google Ads API request failed with errors:")
        for error in ex.failure.errors:
            logger.error(f"\tError code: {error.error_code}")
            logger.error(f"\tMessage: {error.message}")
            # Log specific details if available
            if error.location:
                for field_path_element in error.location.field_path_elements:
                    logger.error(f"\t\tField: {field_path_element.field_name}, Index: {field_path_element.index if field_path_element.HasField('index') else 'N/A'}")
            if error.details:
                 logger.error(f"\tDetails: {error.details}")
        logger.error("Falling back to dummy data.")
        return _get_dummy_keyword_ideas(seed_keyword)
    except ImportError:
        logger.error("Google Ads library ('google-ads') is not installed. Run 'pip install google-ads'. Falling back to dummy data.")
        return _get_dummy_keyword_ideas(seed_keyword)
    except Exception as e:
        logger.exception(f"Unexpected error during Google Ads API call: {e}. Falling back to dummy data.")
        return _get_dummy_keyword_ideas(seed_keyword)

# --- Helper Function for Dummy Data ---
def _get_dummy_keyword_ideas(seed_keyword):
    """Returns dummy data when live API call is disabled or fails."""
    logger.warning(f"Using dummy keyword data for seed: '{seed_keyword}'")
    dummy_ideas = [
        {'text': f'{seed_keyword} trends 2025', 'avg_monthly_searches': 1500, 'competition_level': 'MEDIUM'},
        {'text': f'best {seed_keyword} platforms', 'avg_monthly_searches': 800, 'competition_level': 'HIGH'},
        {'text': f'how does {seed_keyword} work', 'avg_monthly_searches': 500, 'competition_level': 'LOW'},
        {'text': f'{seed_keyword} impact', 'avg_monthly_searches': 1200, 'competition_level': 'MEDIUM'},
        {'text': f'{seed_keyword} future applications', 'avg_monthly_searches': 300, 'competition_level': 'LOW'},
        {'text': f'{seed_keyword} alternatives', 'avg_monthly_searches': 600, 'competition_level': 'HIGH'},
        {'text': f'latest news on {seed_keyword}', 'avg_monthly_searches': 2000, 'competition_level': 'MEDIUM'},
        {'text': f'introduction to {seed_keyword} technology', 'avg_monthly_searches': 400, 'competition_level': 'LOW'},
        {'text': 'unrelated popular term', 'avg_monthly_searches': 10000, 'competition_level': 'LOW'},
        {'text': f'{seed_keyword}', 'avg_monthly_searches': 5000, 'competition_level': 'MEDIUM'},
    ]
    # Simulate adding some longer tail keywords
    dummy_ideas.append({'text': f'ethical implications of {seed_keyword}', 'avg_monthly_searches': 150, 'competition_level': 'LOW'})
    dummy_ideas.append({'text': f'comparing {seed_keyword} providers', 'avg_monthly_searches': 250, 'competition_level': 'MEDIUM'})
    return dummy_ideas


# --- Keyword Processing/Selection Logic (Remains the Same) ---
def _calculate_relevance(keyword_text, primary_keyword):
    """Simple relevance calculation based on word overlap."""
    primary_words = set(primary_keyword.lower().split())
    keyword_words = set(keyword_text.lower().split())
    if not primary_words: return 0.0
    common_words = primary_words.intersection(keyword_words)
    score = len(common_words) / len(primary_words)
    if primary_keyword.lower() in keyword_text.lower(): score = max(score, 0.8)
    if len(keyword_words) > len(primary_words) + 3: score *= 0.9
    return score

def _select_best_keywords(ideas, primary_keyword, num_keywords=TARGET_NUM_KEYWORDS):
    """Selects the best keywords based on relevance and metrics."""
    if not ideas: return []
    selected_keywords = []
    scored_ideas = []
    for idea in ideas:
        keyword_text = idea.get('text')
        if not keyword_text or keyword_text.lower() == primary_keyword.lower(): continue
        relevance = _calculate_relevance(keyword_text, primary_keyword)
        if relevance < MIN_RELEVANCE_SCORE: logger.debug(f"Skipping keyword '{keyword_text}' due to low relevance ({relevance:.2f})"); continue
        score = relevance * 100
        volume = idea.get('avg_monthly_searches')
        if isinstance(volume, int):
            if 1000 <= volume <= 10000: score += 20
            elif volume < 1000: score += 10
        competition = idea.get('competition_level')
        if competition == 'HIGH': score -= 15
        elif competition == 'LOW': score += 5
        if len(keyword_text.split()) == len(primary_keyword.split()) and relevance > 0.9: score *= 0.8
        scored_ideas.append({'text': keyword_text, 'score': score})
    scored_ideas.sort(key=lambda x: x['score'], reverse=True)
    seen = set()
    for idea in scored_ideas:
        kw = idea['text']
        if kw.lower() not in seen:
            selected_keywords.append(kw)
            seen.add(kw.lower())
            if len(selected_keywords) >= num_keywords: break
    logger.info(f"Selected {len(selected_keywords)} keywords based on relevance/metrics.")
    logger.debug(f"Selected keywords: {selected_keywords}")
    return selected_keywords

# --- Main Agent Function ---
def run_keyword_research_agent(article_data):
    """Main function for the keyword research agent."""
    article_id = article_data.get('id', 'N/A')
    logger.info(f"Running Keyword Research Agent for article ID: {article_id}...")
    primary_keyword = article_data.get('filter_verdict', {}).get('primary_topic_keyword')
    if not primary_keyword:
        logger.warning(f"No primary_topic_keyword found for ID {article_id}. Cannot perform keyword research.")
        article_data['researched_keywords'] = []
        article_data['keyword_agent_error'] = "Missing primary keyword input"
        return article_data
    article_url = article_data.get('link')
    keyword_ideas = _fetch_keyword_ideas_from_ads_api(primary_keyword, target_url=article_url)
    selected_keywords = _select_best_keywords(keyword_ideas, primary_keyword, num_keywords=TARGET_NUM_KEYWORDS)
    final_keyword_list = list(set([primary_keyword] + selected_keywords))
    article_data['researched_keywords'] = final_keyword_list
    article_data['keyword_agent_error'] = None
    logger.info(f"Keyword research complete for ID {article_id}. Found {len(final_keyword_list)} total keywords.")
    logger.debug(f"Final keywords for {article_id}: {final_keyword_list}")
    return article_data

# --- Standalone Execution (for testing) ---
if __name__ == "__main__":
    logging.getLogger().setLevel(logging.DEBUG)
    logger.setLevel(logging.DEBUG)
    test_article_data = { # Using previous example
        'id': 'test-kw-001', 'title': "Singapore AI Safety Collaboration Bridges US-China Divide",
        'link': "https://example.com/singapore-ai-safety",
        'filter_verdict': { 'primary_topic_keyword': 'AI Safety Collaboration' }
    }
    logger.info("\n--- Running Keyword Research Agent Standalone Test (with API placeholder/fallback) ---")
    result_data = run_keyword_research_agent(test_article_data.copy())
    print("\n--- Keyword Research Results ---")
    if result_data.get('keyword_agent_error'): print(f"Error: {result_data['keyword_agent_error']}")
    else: print(f"Researched Keywords: {result_data.get('researched_keywords')}")
    logger.info("--- Keyword Research Agent Standalone Test Complete ---")