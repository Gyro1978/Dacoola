# src/agents/keyword_research_agent.py (1/1) - Advanced SEO Version
import os
import sys
import json
import logging
import re
import time
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
# Primary goal for high-quality secondary keywords. We'll fetch more to have options.
TARGET_NUM_QUALITY_SECONDARY_KEYWORDS = 15 # Aim for a good pool of quality secondary keywords
TOTAL_MIN_KEYWORDS_TARGET = 10 # The absolute minimum number of keywords in the final list (including primary)
MIN_RELEVANCE_SCORE_PRIMARY_SELECTION = 0.45 # Stricter relevance for initial quality selection
MIN_RELEVANCE_SCORE_FILLER_SELECTION = 0.25 # Looser relevance if we need to fill to meet the minimum
ENABLE_LIVE_ADS_API = True

DEFAULT_GOOGLE_ADS_YAML_PATH = os.path.join(PROJECT_ROOT, 'google-ads.yaml')
GOOGLE_ADS_CONFIG_PATH = os.getenv('GOOGLE_ADS_CONFIGURATION_FILE_PATH', DEFAULT_GOOGLE_ADS_YAML_PATH)
API_RETRY_COUNT = 2
API_RETRY_DELAY = 5 # seconds

# --- Helper Function for API Interaction ---
def _fetch_keyword_ideas_from_ads_api(seed_keyword, target_url=None, attempt=1):
    """
    Fetches keyword ideas from Google Ads API with retries.
    Returns a list of keyword ideas or an empty list on failure.
    """
    if not ENABLE_LIVE_ADS_API:
        logger.warning("Live Google Ads API call disabled by ENABLE_LIVE_ADS_API flag. No keywords will be fetched.")
        return []

    logger.info(f"Attempting Google Ads API call (Attempt {attempt}/{API_RETRY_COUNT+1}) for seed: '{seed_keyword}' using config: {GOOGLE_ADS_CONFIG_PATH}")

    if not os.path.exists(GOOGLE_ADS_CONFIG_PATH):
        logger.error(f"Google Ads YAML configuration file not found at: {GOOGLE_ADS_CONFIG_PATH}. Cannot fetch live keywords.")
        return []

    try:
        from google.ads.googleads.client import GoogleAdsClient
        from google.ads.googleads.errors import GoogleAdsException

        logger.debug(f"Initializing GoogleAdsClient from storage: {GOOGLE_ADS_CONFIG_PATH}...")
        # Ensure the client is re-initialized if multiple calls are made in one script run potentially
        googleads_client = GoogleAdsClient.load_from_storage(path=GOOGLE_ADS_CONFIG_PATH, version="v17")
        logger.debug("GoogleAdsClient initialized.")

        keyword_plan_idea_service = googleads_client.get_service("KeywordPlanIdeaService")
        # Ensure customer_id is present if login_customer_id is used implicitly by the client from YAML
        # For generate_keyword_ideas, customer_id in the request is optional if login_customer_id is set.

        request = googleads_client.get_type("GenerateKeywordIdeasRequest")
        # Optionally, set customer_id if not relying on login_customer_id for this specific call
        # if googleads_client.login_customer_id:
        #     request.customer_id = googleads_client.login_customer_id

        # Language is crucial for relevant keywords
        request.language = googleads_client.service("GoogleAdsService").language_constant_path("1000")  # English

        # Geo targeting (e.g., United States). Adjust if global or other regions are needed.
        request.geo_target_constants.append(
            googleads_client.service("GeoTargetConstantService").geo_target_constant_path("2840")  # United States
        )
        # Add more geo targets if needed, e.g., Canada: "2124"

        request.include_adult_keywords = False
        request.keyword_plan_network = googleads_client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH_AND_PARTNERS

        # Seed keywords
        if seed_keyword:
            request.keyword_seed.keywords.append(seed_keyword)
        
        # URL seed (optional, can provide context)
        if target_url:
            request.url_seed.url = target_url
            logger.info(f"Using URL seed: {target_url}")

        if not request.keyword_seed.keywords and not request.url_seed.url:
            logger.error("No seed keyword or URL provided. Cannot generate ideas via API.")
            return []

        logger.info(f"Sending keyword ideas request to Google Ads API for seed: '{seed_keyword}'...")
        response = keyword_plan_idea_service.generate_keyword_ideas(request=request)
        logger.info("Received response from Google Ads API.")

        ideas = []
        for result in response.results:
            metrics = result.keyword_idea_metrics
            avg_searches = metrics.avg_monthly_searches if metrics and metrics.HasField("avg_monthly_searches") else 0 # Default to 0 if no data
            
            competition_enum_val = metrics.competition if metrics and metrics.HasField("competition") else None
            competition_level_str = 'UNKNOWN'
            if competition_enum_val is not None:
                try:
                    competition_level_str = googleads_client.enums.KeywordPlanCompetitionLevelEnum(competition_enum_val).name
                except ValueError:
                    logger.warning(f"Unknown competition enum value: {competition_enum_val} for keyword '{result.text}'. Defaulting to UNKNOWN.")


            # Additional metrics (examples, uncomment and use if needed)
            # low_top_of_page_bid = metrics.low_top_of_page_bid_micros if metrics and metrics.HasField("low_top_of_page_bid_micros") else None
            # high_top_of_page_bid = metrics.high_top_of_page_bid_micros if metrics and metrics.HasField("high_top_of_page_bid_micros") else None
            # cpc_micros = metrics.average_cpc_micros if metrics and metrics.HasField("average_cpc_micros") else None

            ideas.append({
                'text': result.text,
                'avg_monthly_searches': avg_searches,
                'competition_level': competition_level_str,
                # 'low_bid': low_top_of_page_bid / 1_000_000 if low_top_of_page_bid else None, # Convert micros to currency unit
                # 'high_bid': high_top_of_page_bid / 1_000_000 if high_top_of_page_bid else None,
                # 'avg_cpc': cpc_micros / 1_000_000 if cpc_micros else None,
            })
        logger.info(f"Successfully processed {len(ideas)} keyword ideas from Google Ads API for seed '{seed_keyword}'.")
        if not ideas:
            logger.warning(f"Google Ads API returned 0 keyword ideas for seed '{seed_keyword}'.")
        return ideas

    except GoogleAdsException as ex:
        logger.error(f"Google Ads API request failed for seed '{seed_keyword}' with errors:")
        for error in ex.failure.errors:
            error_code_name = error.error_code.name if hasattr(error.error_code, 'name') else str(error.error_code)
            logger.error(f"\tError code: {error_code_name}")
            logger.error(f"\tMessage: {error.message}")
            if error.trigger: logger.error(f"\tTrigger: {error.trigger.string_value}")
            if error.location:
                for field_path_element in error.location.field_path_elements:
                    logger.error(f"\tField: {field_path_element.field_name}, Index: {field_path_element.index if field_path_element.HasField('index') else 'N/A'}")
        
        if attempt < API_RETRY_COUNT:
            logger.info(f"Retrying API call for '{seed_keyword}' in {API_RETRY_DELAY}s... (Attempt {attempt+1}/{API_RETRY_COUNT+1})")
            time.sleep(API_RETRY_DELAY)
            return _fetch_keyword_ideas_from_ads_api(seed_keyword, target_url, attempt + 1)
        logger.error(f"No keywords fetched for '{seed_keyword}' due to GoogleAdsException after {attempt} attempts.")
        return []
    except ImportError:
        logger.error("Google Ads library ('google-ads') is not installed. Run 'pip install google-ads'. No keywords fetched.")
        return []
    except Exception as e:
        logger.exception(f"Unexpected error during Google Ads API call for seed '{seed_keyword}': {e}")
        if attempt < API_RETRY_COUNT:
            logger.info(f"Retrying API call for '{seed_keyword}' due to unexpected error in {API_RETRY_DELAY}s...")
            time.sleep(API_RETRY_DELAY)
            return _fetch_keyword_ideas_from_ads_api(seed_keyword, target_url, attempt + 1)
        return []

# --- Keyword Processing/Selection Logic ---
def _calculate_relevance(keyword_text, primary_keyword_text):
    """Calculates relevance score between a keyword and the primary keyword."""
    primary_words = set(primary_keyword_text.lower().split())
    keyword_words = set(keyword_text.lower().split())

    if not primary_words or not keyword_words: return 0.0

    common_words = primary_words.intersection(keyword_words)
    # Jaccard index variation
    score = len(common_words) / len(primary_words.union(keyword_words))

    # Boost if primary keyword is a substring of the keyword (e.g., "ai models" in "best ai models 2024")
    if primary_keyword_text.lower() in keyword_text.lower():
        score = max(score, 0.7) # Ensure a decent base score
        score += 0.15 # Add a direct boost

    # Penalize if keyword is much longer than primary (could be too broad or unrelated)
    if len(keyword_words) > len(primary_words) + 3: # Allow some expansion for long-tail
        score *= 0.9

    # Boost for more specific (longer) keywords that are still relevant
    if len(keyword_words) > len(primary_words) and len(keyword_words) <= len(primary_words) + 3 :
        score += 0.05 * (len(keyword_words) - len(primary_words))
        
    return min(score, 1.0) # Cap score at 1.0

def _score_keyword_idea(idea, primary_keyword_text, min_relevance_threshold):
    """Scores a single keyword idea based on relevance, volume, and competition."""
    keyword_text = idea.get('text')
    if not keyword_text or keyword_text.lower() == primary_keyword_text.lower():
        return None # Skip primary keyword or empty ones

    relevance = _calculate_relevance(keyword_text, primary_keyword_text)
    if relevance < min_relevance_threshold:
        logger.debug(f"Skipping '{keyword_text}': low relevance ({relevance:.2f} < {min_relevance_threshold}) to '{primary_keyword_text}'")
        return None

    # Base score from relevance (scale to 0-100)
    score = relevance * 100.0

    # Volume contribution (logarithmic scaling to avoid extreme dominance by high-volume keywords)
    volume = idea.get('avg_monthly_searches', 0)
    if volume > 100000: score += 40
    elif volume > 10000: score += 30
    elif volume > 1000: score += 20
    elif volume > 100: score += 10
    elif volume > 10: score += 5
    else: score += 1


    # Competition adjustment (favor LOW to MEDIUM)
    competition = idea.get('competition_level', 'UNKNOWN').upper()
    if competition == 'LOW': score += 25
    elif competition == 'MEDIUM': score += 10
    # HIGH competition might be valuable but harder to rank for, so less of a boost or slight penalty
    elif competition == 'HIGH': score -= 15
    else: score += 0 # UNKNOWN or other values

    # Keyword length (favor slightly longer, more specific keywords - "long-tail" potential)
    num_words = len(keyword_text.split())
    if num_words > len(primary_keyword_text.split()):
        if 2 <= num_words <= 4: score += 5
        elif num_words > 4 and num_words <=6 : score += 10 # Sweet spot for long-tail
        else: score += 2 # Very long might be too niche

    # Penalize if it's just a plural/singular or very minor variation of primary if relevance is already high
    # This is complex, basic check:
    if relevance > 0.9 and abs(len(keyword_text) - len(primary_keyword_text)) <= 2 and num_words == len(primary_keyword_text.split()):
        score *= 0.8 # Reduce score for very minor variations

    return {
        'text': keyword_text,
        'score': score,
        'volume': volume,
        'relevance': relevance,
        'competition': competition
    }

def _select_best_keywords(ideas, primary_keyword_text, num_keywords_to_select, min_relevance_score):
    """Selects the best N keywords based on a composite score."""
    if not ideas: return []
    
    scored_ideas = []
    for idea in ideas:
        scored_idea = _score_keyword_idea(idea, primary_keyword_text, min_relevance_score)
        if scored_idea:
            scored_ideas.append(scored_idea)

    # Sort by the composite score in descending order
    scored_ideas.sort(key=lambda x: x['score'], reverse=True)

    logger.debug(f"Top scored keyword ideas for '{primary_keyword_text}' (Relevance >= {min_relevance_score}):")
    for i, idea_info in enumerate(scored_ideas[:num_keywords_to_select + 5]): # Log a few extra
        logger.debug(f"  {i+1}. '{idea_info['text']}' (Score: {idea_info['score']:.2f}, Vol: {idea_info['volume']}, Rel: {idea_info['relevance']:.2f}, Comp: {idea_info['competition']})")

    selected_keywords_texts = []
    seen_texts = set()
    for scored_idea in scored_ideas:
        kw_text = scored_idea['text']
        if kw_text.lower() not in seen_texts: # Ensure uniqueness
            selected_keywords_texts.append(kw_text)
            seen_texts.add(kw_text.lower())
            if len(selected_keywords_texts) >= num_keywords_to_select:
                break
                
    logger.info(f"Selected {len(selected_keywords_texts)} secondary keywords for '{primary_keyword_text}' based on min_relevance {min_relevance_score}.")
    return selected_keywords_texts

# --- Main Agent Function ---
def run_keyword_research_agent(article_data):
    article_id = article_data.get('id', 'N/A')
    logger.info(f"Running Advanced Keyword Research Agent for article ID: {article_id}...")
    
    primary_keyword_text = article_data.get('filter_verdict', {}).get('primary_topic_keyword')
    if not primary_keyword_text:
        logger.warning(f"No primary_topic_keyword found for article ID {article_id}. Keyword research will be limited or skipped.")
        article_data['researched_keywords'] = []
        article_data['keyword_agent_error'] = "Missing primary_topic_keyword from filter_verdict."
        return article_data

    article_url_for_seed = article_data.get('link') # Original source URL for context
    
    # Fetch a broad set of initial ideas from the API
    all_keyword_ideas_from_api = _fetch_keyword_ideas_from_ads_api(primary_keyword_text, target_url=article_url_for_seed)

    if not all_keyword_ideas_from_api:
        logger.warning(f"No keyword ideas received from API for primary keyword '{primary_keyword_text}'. Final list might be short.")
        # Fallback: use primary keyword only if API fails completely
        article_data['researched_keywords'] = [primary_keyword_text]
        article_data['keyword_agent_error'] = "Keyword API call failed or returned no ideas."
        # Ensure it meets the minimum if possible with just variations or related terms if we had a local list
        # For now, with API failure, this is the best we can do.
        while len(article_data['researched_keywords']) < TOTAL_MIN_KEYWORDS_TARGET:
            # This part is tricky without more data. Adding placeholders is bad.
            # We could try to generate simple variations of the primary_keyword if allowed.
            # For now, we accept it might be short if API fails.
            logger.warning(f"API failed, cannot meet TOTAL_MIN_KEYWORDS_TARGET of {TOTAL_MIN_KEYWORDS_TARGET}.")
            break 
        return article_data

    # --- Stage 1: Select high-quality keywords ---
    selected_quality_secondary_keywords = _select_best_keywords(
        all_keyword_ideas_from_api,
        primary_keyword_text,
        TARGET_NUM_QUALITY_SECONDARY_KEYWORDS,
        MIN_RELEVANCE_SCORE_PRIMARY_SELECTION
    )

    final_keyword_list = [primary_keyword_text]
    for kw in selected_quality_secondary_keywords:
        # Ensure uniqueness ignoring case, and not same as primary
        if kw.lower() != primary_keyword_text.lower() and kw.lower() not in [k.lower() for k in final_keyword_list]:
            final_keyword_list.append(kw)

    # --- Stage 2: Ensure minimum keyword count ---
    if len(final_keyword_list) < TOTAL_MIN_KEYWORDS_TARGET:
        logger.info(f"Current keyword count ({len(final_keyword_list)}) is less than target ({TOTAL_MIN_KEYWORDS_TARGET}). Attempting to add more keywords...")
        
        num_needed = TOTAL_MIN_KEYWORDS_TARGET - len(final_keyword_list)
        
        # Use a less strict relevance for filler keywords, from the remaining API ideas
        potential_filler_ideas = [
            idea for idea in all_keyword_ideas_from_api 
            if idea.get('text', '').lower() not in [k.lower() for k in final_keyword_list] # Exclude already selected
        ]
        
        selected_filler_keywords = _select_best_keywords(
            potential_filler_ideas,
            primary_keyword_text,
            num_needed, # Try to get exactly the number needed
            MIN_RELEVANCE_SCORE_FILLER_SELECTION # Use the looser relevance score
        )
        
        for kw in selected_filler_keywords:
            if kw.lower() not in [k.lower() for k in final_keyword_list]:
                final_keyword_list.append(kw)
            if len(final_keyword_list) >= TOTAL_MIN_KEYWORDS_TARGET:
                break
    
    # If still below target after trying fillers (e.g., API returned very few unique/relevant terms)
    if len(final_keyword_list) < TOTAL_MIN_KEYWORDS_TARGET:
        logger.warning(f"Could not meet total keyword target of {TOTAL_MIN_KEYWORDS_TARGET} for '{primary_keyword_text}'. Final count: {len(final_keyword_list)}. API might have returned limited relevant terms.")
        # At this point, we've done our best with the available API data.
        # Avoid adding random or very poor quality keywords just to hit the number.
        # If the constraint "no less allowed at all cost" means even adding low-quality, that's a different requirement.
        # Current interpretation: "try your absolute best to find 10 good ones".

    article_data['researched_keywords'] = final_keyword_list
    article_data['keyword_agent_error'] = None # Clear previous error if any
    logger.info(f"Keyword research complete for ID {article_id}. Final keywords ({len(final_keyword_list)}): {final_keyword_list}")
    return article_data

# --- Standalone Execution (for testing) ---
if __name__ == "__main__":
    logging.getLogger().setLevel(logging.DEBUG) # Enable debug level for detailed scoring logs
    logger.setLevel(logging.DEBUG)

    # Ensure your google-ads.yaml is correctly configured for this test to run the API.
    # If API call fails or returns no data, the script will log warnings/errors.

    test_article_data_live_attempt = {
        'id': 'test-kw-advanced-001',
        'title': "NVIDIA Unveils Blackwell B200 GPU for Trillion-Parameter AI Models",
        'link': "https://www.example-tech-news.com/nvidia-blackwell-b200-launch", # Example URL
        'filter_verdict': {
            'primary_topic_keyword': 'NVIDIA Blackwell B200' # A good, specific primary keyword
        }
    }
    logger.info("\n--- Running Keyword Research Agent Standalone Test (Advanced SEO Version) ---")
    result_data_live = run_keyword_research_agent(test_article_data_live_attempt.copy())
    
    print("\n--- Keyword Research Results (Live API Attempt) ---")
    if result_data_live.get('keyword_agent_error'):
        print(f"Error: {result_data_live['keyword_agent_error']}")
    
    final_keywords = result_data_live.get('researched_keywords', [])
    print(f"Primary Keyword: {result_data_live.get('filter_verdict', {}).get('primary_topic_keyword')}")
    print(f"Total Researched Keywords ({len(final_keywords)}):")
    for i, kw in enumerate(final_keywords):
        print(f"  {i+1}. {kw}")

    if len(final_keywords) < TOTAL_MIN_KEYWORDS_TARGET:
        print(f"\nWARNING: Final keyword count ({len(final_keywords)}) is less than the target of {TOTAL_MIN_KEYWORDS_TARGET}.")

    # Test with a more generic primary keyword
    test_article_data_generic_kw = {
        'id': 'test-kw-generic-002',
        'title': "The Rise of Artificial Intelligence in Modern Applications",
        'link': "https://www.example-general-ai.com/ai-rise-applications",
        'filter_verdict': {
            'primary_topic_keyword': 'artificial intelligence applications'
        }
    }
    logger.info("\n--- Running Test with Generic Primary Keyword ---")
    result_data_generic = run_keyword_research_agent(test_article_data_generic_kw.copy())
    final_keywords_generic = result_data_generic.get('researched_keywords', [])
    print(f"\nPrimary Keyword: {result_data_generic.get('filter_verdict', {}).get('primary_topic_keyword')}")
    print(f"Total Researched Keywords ({len(final_keywords_generic)}):")
    for i, kw in enumerate(final_keywords_generic):
        print(f"  {i+1}. {kw}")


    logger.info("\n--- Keyword Research Agent Standalone Test Complete ---")