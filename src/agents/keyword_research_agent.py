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
TARGET_NUM_KEYWORDS = 5  # Number of secondary keywords to aim for
MIN_RELEVANCE_SCORE = 0.5
ENABLE_LIVE_ADS_API = True

DEFAULT_GOOGLE_ADS_YAML_PATH = os.path.join(PROJECT_ROOT, 'google-ads.yaml')
GOOGLE_ADS_CONFIG_PATH = os.getenv('GOOGLE_ADS_CONFIGURATION_FILE_PATH', DEFAULT_GOOGLE_ADS_YAML_PATH)
MIN_TOTAL_KEYWORDS_FALLBACK = 3 # Minimum distinct keywords we want before trying to split primary

# --- Helper Function for API Interaction ---
def _fetch_keyword_ideas_from_ads_api(seed_keyword, target_url=None):
    """
    Fetches keyword ideas from Google Ads API.
    Returns a list of keyword ideas or None/empty list on failure.
    """
    if not ENABLE_LIVE_ADS_API:
        logger.warning("Live Google Ads API call disabled by ENABLE_LIVE_ADS_API flag. No keywords will be fetched.")
        return []

    logger.info(f"Attempting Google Ads API call for seed: '{seed_keyword}' using config: {GOOGLE_ADS_CONFIG_PATH}")

    if not os.path.exists(GOOGLE_ADS_CONFIG_PATH):
        logger.error(f"Google Ads YAML configuration file not found at: {GOOGLE_ADS_CONFIG_PATH}. Cannot fetch live keywords.")
        return []

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
             return []

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
        logger.error("No keywords fetched due to GoogleAdsException.")
        return []
    except ImportError:
        logger.error("Google Ads library ('google-ads') is not installed. Run 'pip install google-ads'. No keywords fetched.")
        return []
    except Exception as e:
        logger.exception(f"Unexpected error during Google Ads API call: {e}. No keywords fetched.")
        return []

# --- Keyword Processing/Selection Logic ---
def _calculate_relevance(keyword_text, primary_keyword):
    primary_words = set(primary_keyword.lower().split())
    keyword_words = set(keyword_text.lower().split())
    if not primary_words: return 0.0
    common_words = primary_words.intersection(keyword_words)
    score = len(common_words) / len(primary_words)
    if primary_keyword.lower() in keyword_text.lower(): score = max(score, 0.85)
    if len(keyword_words) > len(primary_words) + 4: score *= 0.85 # Penalize much longer keywords slightly
    return score

def _select_best_keywords(ideas, primary_keyword, num_keywords_to_select=TARGET_NUM_KEYWORDS):
    if not ideas: return []
    selected_keywords = []
    scored_ideas = []
    for idea in ideas:
        keyword_text = idea.get('text')
        if not keyword_text or not isinstance(keyword_text, str) or not keyword_text.strip():
            continue # Skip empty or invalid keyword text
        
        keyword_text_cleaned = keyword_text.strip()
        if keyword_text_cleaned.lower() == primary_keyword.lower(): # Skip if it's identical to primary
            continue

        relevance = _calculate_relevance(keyword_text_cleaned, primary_keyword)
        if relevance < MIN_RELEVANCE_SCORE:
            logger.debug(f"Skipping '{keyword_text_cleaned}': low relevance ({relevance:.2f}) to '{primary_keyword}'")
            continue
        
        score = relevance * 1000
        volume = idea.get('avg_monthly_searches')
        if isinstance(volume, int):
            if volume > 10000: score += 100 # Higher weight for high volume
            elif volume > 1000: score += 50
            elif volume > 100: score += 20
            else: score += 5
        
        competition = idea.get('competition_level')
        if competition == 'HIGH': score -= 50 # Higher penalty for high competition
        elif competition == 'MEDIUM': score -=20
        elif competition == 'LOW': score += 30 # Higher reward for low competition
        
        # Penalize if secondary keyword is just a slight variation of primary (e.g., plural)
        if len(keyword_text_cleaned.split()) == len(primary_keyword.split()) and relevance > 0.9:
            score *= 0.85
        scored_ideas.append({'text': keyword_text_cleaned, 'score': score, 'volume': volume, 'relevance': relevance, 'competition': competition})

    scored_ideas.sort(key=lambda x: x['score'], reverse=True)
    logger.debug(f"Top scored keyword ideas for '{primary_keyword}':")
    for i, idea_info in enumerate(scored_ideas[:10]):
        logger.debug(f"  {i+1}. '{idea_info['text']}' (Score: {idea_info['score']:.0f}, Vol: {idea_info['volume']}, Rel: {idea_info['relevance']:.2f}, Comp: {idea_info['competition']})")

    seen_texts_lower = set()
    for idea in scored_ideas:
        kw_text = idea['text']
        if kw_text.lower() not in seen_texts_lower:
            selected_keywords.append(kw_text)
            seen_texts_lower.add(kw_text.lower())
            if len(selected_keywords) >= num_keywords_to_select:
                break
    logger.info(f"Selected {len(selected_keywords)} secondary keywords for '{primary_keyword}'.")
    return selected_keywords

# --- Main Agent Function ---
def run_keyword_research_agent(article_data):
    article_id = article_data.get('id', 'N/A')
    logger.info(f"Running Keyword Research Agent for article ID: {article_id}...")
    primary_keyword_raw = article_data.get('filter_verdict', {}).get('primary_topic_keyword')

    if not primary_keyword_raw or not isinstance(primary_keyword_raw, str) or not primary_keyword_raw.strip():
        logger.warning(f"No valid primary_topic_keyword for ID {article_id}. Keyword research skipped.")
        article_data['researched_keywords'] = []
        article_data['keyword_agent_error'] = "Missing or invalid primary keyword input"
        return article_data
    
    primary_keyword = primary_keyword_raw.strip()
    article_data['primary_keyword'] = primary_keyword # Ensure it's stored cleaned

    article_url = article_data.get('link')
    keyword_ideas_from_api = _fetch_keyword_ideas_from_ads_api(primary_keyword, target_url=article_url)

    selected_secondary_keywords = []
    if not keyword_ideas_from_api:
        logger.warning(f"No keyword ideas received from API for '{primary_keyword}'.")
    else:
        selected_secondary_keywords = _select_best_keywords(keyword_ideas_from_api, primary_keyword, num_keywords_to_select=TARGET_NUM_KEYWORDS)

    # --- Build the final list ---
    final_keywords_set = set()
    final_keywords_set.add(primary_keyword) # Add primary first

    for kw in selected_secondary_keywords:
        if kw and isinstance(kw, str) and kw.strip():
            final_keywords_set.add(kw.strip()) # Set handles uniqueness

    # --- Fallback: If too few distinct keywords and primary is a phrase, split it ---
    if len(final_keywords_set) < MIN_TOTAL_KEYWORDS_FALLBACK:
        primary_phrase_words = primary_keyword.split()
        if len(primary_phrase_words) > 1: # It's a multi-word phrase
            logger.info(f"Low distinct keywords ({len(final_keywords_set)} for '{primary_keyword}'). Splitting primary phrase for more tags.")
            for word in primary_phrase_words:
                cleaned_word = re.sub(r'[^\w\s-]', '', word).strip() # Remove punctuation, keep hyphens
                if len(cleaned_word) > 2 and cleaned_word.lower() not in ['the', 'and', 'for', 'with', 'from', 'into', 'over', 'this', 'that']: # Basic stopword filter
                    # Add capitalized version, set will handle uniqueness
                    final_keywords_set.add(cleaned_word.capitalize())
                    if len(final_keywords_set) >= TARGET_NUM_KEYWORDS + 1: # Max out around original target + primary
                        break
    
    # Convert set to list and sort. Primary keyword first, then alphabetically.
    # This makes primary_keyword effectively the "main tag" if it's treated that way downstream.
    final_keyword_list = sorted(list(final_keywords_set), key=lambda x: (x.lower() != primary_keyword.lower(), x.lower()))

    article_data['researched_keywords'] = final_keyword_list
    api_call_failed_or_empty = not keyword_ideas_from_api
    if api_call_failed_or_empty and len(final_keyword_list) <= 1 and primary_keyword in final_keyword_list:
         article_data['keyword_agent_error'] = "Keyword API call failed or returned no ideas, and primary keyword split didn't yield more."
    else:
        article_data['keyword_agent_error'] = None

    logger.info(f"Keyword research complete for ID {article_id}. Final keywords: {final_keyword_list}")
    return article_data

# --- Standalone Execution (for testing) ---
if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)
    logger.setLevel(logging.DEBUG)

    test_article_data_live_attempt = {
        'id': 'test-kw-tags-001', 'title': "OpenAI acquires Windsurf AI a small startup",
        'link': "https://example.com/openai-acquires-windsurf",
        'filter_verdict': { 'primary_topic_keyword': 'OpenAI acquires Windsurf' }
    }
    logger.info("\n--- Running Keyword Research Agent Standalone Test (Tag Generation Focus) ---")
    result_data_live = run_keyword_research_agent(test_article_data_live_attempt.copy())
    print("\n--- Keyword Research Results (Live Attempt) ---")
    if result_data_live.get('keyword_agent_error'):
        print(f"Error: {result_data_live['keyword_agent_error']}")
    print(f"Primary Keyword: {result_data_live.get('primary_keyword')}")
    print(f"Researched Keywords (for tags): {result_data_live.get('researched_keywords')}")

    test_article_data_short_primary = {
        'id': 'test-kw-tags-002', 'title': "New Nvidia Chip",
        'link': "https://example.com/nvidia-chip",
        'filter_verdict': { 'primary_topic_keyword': 'Nvidia Chip' }
    }
    logger.info("\n--- Running Keyword Research Agent Test (Short Primary Keyword) ---")
    result_data_short_primary = run_keyword_research_agent(test_article_data_short_primary.copy())
    print("\n--- Keyword Research Results (Short Primary) ---")
    if result_data_short_primary.get('keyword_agent_error'):
        print(f"Error: {result_data_short_primary['keyword_agent_error']}")
    print(f"Primary Keyword: {result_data_short_primary.get('primary_keyword')}")
    print(f"Researched Keywords (for tags): {result_data_short_primary.get('researched_keywords')}")

    logger.info("--- Keyword Research Agent Standalone Test Complete ---")