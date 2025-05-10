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
TARGET_NUM_GOOD_SECONDARY_KEYWORDS_FROM_API = 7 # How many "good" secondary keywords to aim for from API
MIN_DESIRED_TOTAL_TAGS = 8                    # The minimum number of total tags we want
MIN_RELEVANCE_SCORE = 0.45 # Slightly lower to allow more candidates initially
ENABLE_LIVE_ADS_API = True

DEFAULT_GOOGLE_ADS_YAML_PATH = os.path.join(PROJECT_ROOT, 'google-ads.yaml')
GOOGLE_ADS_CONFIG_PATH = os.getenv('GOOGLE_ADS_CONFIGURATION_FILE_PATH', DEFAULT_GOOGLE_ADS_YAML_PATH)
COMMON_WORDS_TO_EXCLUDE_FROM_SPLIT = {'the', 'and', 'for', 'with', 'from', 'into', 'over', 'this', 'that', 'its', 'was', 'are', 'has', 'had', 'will', 'not', 'but', 'new', 'about'}


# --- Helper Function for API Interaction ---
def _fetch_keyword_ideas_from_ads_api(seed_keyword, target_url=None):
    if not ENABLE_LIVE_ADS_API:
        logger.warning("Live Google Ads API call disabled. No keywords will be fetched.")
        return []
    logger.info(f"Attempting Google Ads API call for seed: '{seed_keyword}'")
    if not os.path.exists(GOOGLE_ADS_CONFIG_PATH):
        logger.error(f"Google Ads YAML config not found: {GOOGLE_ADS_CONFIG_PATH}.")
        return []
    try:
        from google.ads.googleads.client import GoogleAdsClient
        from google.ads.googleads.errors import GoogleAdsException
        googleads_client = GoogleAdsClient.load_from_storage(path=GOOGLE_ADS_CONFIG_PATH, version="v17")
        keyword_plan_idea_service = googleads_client.get_service("KeywordPlanIdeaService")
        request = googleads_client.get_type("GenerateKeywordIdeasRequest")
        request.language = googleads_client.service("GoogleAdsService").language_constant_path("1000")
        request.geo_target_constants.append(
            googleads_client.service("GeoTargetConstantService").geo_target_constant_path("2840")
        )
        request.include_adult_keywords = False
        request.keyword_plan_network = googleads_client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH_AND_PARTNERS
        if seed_keyword: request.keyword_seed.keywords.append(seed_keyword)
        if target_url: request.url_seed.url = target_url
        if not request.keyword_seed.keywords and not request.url_seed.url:
             logger.error("No seed keyword or URL for API."); return []
        response = keyword_plan_idea_service.generate_keyword_ideas(request=request)
        ideas = []
        for result in response.results:
            metrics = result.keyword_idea_metrics
            avg_searches = metrics.avg_monthly_searches if metrics and metrics.HasField("avg_monthly_searches") else None
            comp_val = metrics.competition if metrics and metrics.HasField("competition") else None
            comp_level = googleads_client.enums.KeywordPlanCompetitionLevelEnum(comp_val).name if comp_val is not None else 'UNKNOWN'
            ideas.append({'text': result.text, 'avg_monthly_searches': avg_searches, 'competition_level': comp_level})
        logger.info(f"Google Ads API returned {len(ideas)} ideas for '{seed_keyword}'.")
        return ideas
    except GoogleAdsException as ex: logger.error(f"Google Ads API Error: {ex.failure.errors}"); return []
    except ImportError: logger.error("google-ads library not installed."); return []
    except Exception as e: logger.exception(f"Unexpected Ads API error: {e}"); return []

# --- Keyword Processing/Selection Logic ---
def _calculate_relevance(keyword_text, primary_keyword):
    primary_words = set(primary_keyword.lower().split())
    keyword_words = set(keyword_text.lower().split())
    if not primary_words: return 0.0
    common_words = primary_words.intersection(keyword_words)
    score = len(common_words) / max(len(primary_words), len(keyword_words)) 
    if primary_keyword.lower() in keyword_text.lower() or keyword_text.lower() in primary_keyword.lower():
        score = max(score, 0.75) 
    if len(keyword_words) > len(primary_words) + 5: score *= 0.80 
    return score

def _select_best_keywords(api_ideas, primary_keyword, num_keywords_to_select):
    if not api_ideas: return []
    scored_ideas = []
    for idea in api_ideas:
        kw_text = idea.get('text')
        if not kw_text or not isinstance(kw_text, str) or not kw_text.strip(): continue
        kw_cleaned = kw_text.strip()
        if kw_cleaned.lower() == primary_keyword.lower(): continue
        
        relevance = _calculate_relevance(kw_cleaned, primary_keyword)
        if relevance < MIN_RELEVANCE_SCORE:
            logger.debug(f"Skipping '{kw_cleaned}': low relevance ({relevance:.2f}) to '{primary_keyword}'")
            continue
        
        score = relevance * 1000  # Base score on relevance

        volume = idea.get('avg_monthly_searches')
        if isinstance(volume, int):
            if volume > 10000: score += 500  # Very high volume
            elif volume > 1000: score += 250 # High volume
            elif volume > 100: score += 100  # Medium volume
            elif volume > 10: score += 30    # Low volume
            else: score += 5                 # Very low volume
        
        comp = idea.get('competition_level')
        if comp == 'HIGH':
            score *= 0.7  # Penalize high competition significantly
        elif comp == 'MEDIUM':
            score *= 0.9  # Slight penalty for medium
        elif comp == 'LOW':
            score *= 1.2  # Boost low competition

        num_words_in_kw = len(kw_cleaned.split())
        if num_words_in_kw == 1 and (not isinstance(volume, int) or volume < 1000): 
            score *= 0.8 # Penalize single words unless high volume
        elif num_words_in_kw >= 2 and num_words_in_kw <= 4: 
            score *= 1.1 # Bonus for 2-4 word phrases
        elif num_words_in_kw > 5: 
            score *= 0.9 # Slight penalty for very long phrases

        scored_ideas.append({'text': kw_cleaned, 'score': score, 'volume': volume, 'relevance': relevance, 'competition': comp})

    scored_ideas.sort(key=lambda x: x['score'], reverse=True)
    logger.debug(f"Top scored API ideas for '{primary_keyword}': {scored_ideas[:num_keywords_to_select + 5]}")
    
    selected_keywords = []
    seen_texts_lower = set()
    for idea_info in scored_ideas:
        if idea_info['text'].lower() not in seen_texts_lower:
            selected_keywords.append(idea_info['text'])
            seen_texts_lower.add(idea_info['text'].lower())
            if len(selected_keywords) >= num_keywords_to_select: break
            
    logger.info(f"Selected {len(selected_keywords)} best secondary keywords from API for '{primary_keyword}'.")
    return selected_keywords

# --- Main Agent Function ---
def run_keyword_research_agent(article_data):
    article_id = article_data.get('id', 'N/A')
    logger.info(f"Running Keyword Research Agent for article ID: {article_id} (Target: >= {MIN_DESIRED_TOTAL_TAGS} tags)...")
    primary_keyword_raw = article_data.get('filter_verdict', {}).get('primary_topic_keyword')

    if not primary_keyword_raw or not isinstance(primary_keyword_raw, str) or len(primary_keyword_raw.strip()) == 0:
        logger.warning(f"No valid primary_topic_keyword for ID {article_id}. Defaulting to title.")
        primary_keyword_raw = article_data.get('title', '')
        # Check again after defaulting
        if not primary_keyword_raw or not isinstance(primary_keyword_raw, str) or len(primary_keyword_raw.strip()) == 0:
             article_data['researched_keywords'] = []
             article_data['keyword_agent_error'] = "Missing primary keyword and title"
             return article_data
    
    primary_keyword = primary_keyword_raw.strip()
    article_data['primary_keyword'] = primary_keyword

    final_keywords_set = set()
    final_keywords_set.add(primary_keyword)

    # --- Step 1: Get best secondary keywords from API ---
    article_url = article_data.get('link')
    all_api_ideas = _fetch_keyword_ideas_from_ads_api(primary_keyword, target_url=article_url)
    
    best_secondary_from_api = []
    if all_api_ideas:
        best_secondary_from_api = _select_best_keywords(all_api_ideas, primary_keyword, num_keywords_to_select=TARGET_NUM_GOOD_SECONDARY_KEYWORDS_FROM_API)
        for kw in best_secondary_from_api:
            final_keywords_set.add(kw.strip())
    else:
        logger.warning(f"No keyword ideas received from API for '{primary_keyword}'.")

    # --- Step 2: Fallback - Split primary keyword if still not enough tags ---
    if len(final_keywords_set) < MIN_DESIRED_TOTAL_TAGS:
        primary_phrase_words = primary_keyword.split()
        if len(primary_phrase_words) > 1: 
            logger.info(f"Tag count {len(final_keywords_set)} < {MIN_DESIRED_TOTAL_TAGS}. Splitting primary: '{primary_keyword}'.")
            for word in primary_phrase_words:
                cleaned_word = re.sub(r'[^\w\s-]', '', word).strip() 
                if len(cleaned_word) > 2 and cleaned_word.lower() not in COMMON_WORDS_TO_EXCLUDE_FROM_SPLIT:
                    final_keywords_set.add(cleaned_word.capitalize()) 
                    if len(final_keywords_set) >= MIN_DESIRED_TOTAL_TAGS:
                        break 
    
    # --- Step 3: Fallback - Use more (less ideal) API ideas if STILL not enough tags ---
    if len(final_keywords_set) < MIN_DESIRED_TOTAL_TAGS and all_api_ideas:
        logger.info(f"Tag count {len(final_keywords_set)} < {MIN_DESIRED_TOTAL_TAGS}. Trying remaining API ideas.")
        
        current_selected_texts_lower = {kw.lower() for kw in final_keywords_set}
        
        potential_fillers = []
        for idea in all_api_ideas:
            idea_text = idea.get('text', '').strip()
            if idea_text and idea_text.lower() not in current_selected_texts_lower:
                volume = idea.get('avg_monthly_searches')
                score = (len(idea_text.split()) * 10) + (volume if isinstance(volume, int) else 0)
                potential_fillers.append({'text': idea_text, 'score': score})
        
        potential_fillers.sort(key=lambda x: x['score'], reverse=True)

        for filler_idea in potential_fillers:
            final_keywords_set.add(filler_idea['text'])
            if len(final_keywords_set) >= MIN_DESIRED_TOTAL_TAGS:
                break

    final_keyword_list = sorted(list(final_keywords_set), key=lambda x: (x.lower() != primary_keyword.lower(), x.lower()))

    article_data['researched_keywords'] = final_keyword_list
    
    if len(final_keyword_list) < MIN_DESIRED_TOTAL_TAGS:
        article_data['keyword_agent_error'] = f"Could only generate {len(final_keyword_list)}/{MIN_DESIRED_TOTAL_TAGS} desired tags."
        logger.warning(article_data['keyword_agent_error'])
    else:
        article_data['keyword_agent_error'] = None

    logger.info(f"Keyword research complete for ID {article_id}. Final tags ({len(final_keyword_list)}): {final_keyword_list}")
    return article_data

# --- Standalone Execution (for testing) ---
if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)
    logger.setLevel(logging.DEBUG)

    test_article_data_long_primary = {
        'id': 'test-kw-tags-001', 'title': "OpenAI acquires Windsurf AI a small startup for multimodal development",
        'link': "https://example.com/openai-acquires-windsurf",
        'filter_verdict': { 'primary_topic_keyword': 'OpenAI acquires Windsurf AI for multimodal' }
    }
    logger.info("\n--- Running Keyword Research Agent Standalone Test (Target >=8 Tags, Long Primary, SEO Focus) ---")
    result_data_live = run_keyword_research_agent(test_article_data_long_primary.copy())
    print("\n--- Keyword Research Results ---")
    if result_data_live.get('keyword_agent_error'): print(f"Error: {result_data_live['keyword_agent_error']}")
    print(f"Primary Keyword: {result_data_live.get('primary_keyword')}")
    print(f"Researched Keywords (for tags): {result_data_live.get('researched_keywords')}")
    print(f"Number of tags: {len(result_data_live.get('researched_keywords', []))}")

    test_article_data_short_primary_no_api = { 
        'id': 'test-kw-tags-002', 'title': "Future of AI Models",
        'link': "https://example.com/future-ai",
        'filter_verdict': { 'primary_topic_keyword': 'Future of AI Models' }
    }
    logger.info("\n--- Running Keyword Research Agent Test (Target >=8 Tags, Potentially No API results, SEO Focus) ---")
    result_data_short_primary = run_keyword_research_agent(test_article_data_short_primary_no_api.copy())
    print("\n--- Keyword Research Results ---")
    if result_data_short_primary.get('keyword_agent_error'): print(f"Error: {result_data_short_primary['keyword_agent_error']}")
    print(f"Primary Keyword: {result_data_short_primary.get('primary_keyword')}")
    print(f"Researched Keywords (for tags): {result_data_short_primary.get('researched_keywords')}")
    print(f"Number of tags: {len(result_data_short_primary.get('researched_keywords', []))}")

    logger.info("--- Keyword Research Agent Standalone Test Complete ---")