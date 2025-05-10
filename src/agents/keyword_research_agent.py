import os
import sys
import json
import logging
import re
import time # For potential retries or delays
from dotenv import load_dotenv
import requests # For calling DeepSeek API

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

# --- Load Environment Variables & Config ---
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)

# Google Ads API Config
ENABLE_LIVE_ADS_API = True # Keep True, but handle failures gracefully
DEFAULT_GOOGLE_ADS_YAML_PATH = os.path.join(os.path.dirname(PROJECT_ROOT), 'google-ads.yaml')
GOOGLE_ADS_CONFIG_PATH = os.getenv('GOOGLE_ADS_CONFIGURATION_FILE_PATH', DEFAULT_GOOGLE_ADS_YAML_PATH)

# DeepSeek API Config (for keyword brainstorming fallback/enhancement)
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_KEYWORD_MODEL = "deepseek-chat" # Or "deepseek-coder" if preferred for this task
DEEPSEEK_MAX_TOKENS_KEYWORDS = 300
DEEPSEEK_TEMPERATURE_KEYWORDS = 0.5

# Keyword Strategy Config
TARGET_NUM_GOOD_SECONDARY_KEYWORDS_FROM_API = 6 # Aim for this many *good* ones from Ads API
MIN_DESIRED_TOTAL_TAGS = 8
MIN_RELEVANCE_SCORE_ADS_API = 0.40 # Slightly more lenient for Ads API initial pull
MIN_KEYWORD_LENGTH_FOR_SPLIT_WORDS = 3 # Words shorter than this from split primary are ignored
MAX_KEYWORDS_FROM_LLM_BRAINSTORM = 10 # Max to ask LLM for in one go
COMMON_WORDS_TO_EXCLUDE = { # Expanded list
    'a', 'an', 'the', 'and', 'or', 'but', 'for', 'nor', 'so', 'yet',
    'in', 'on', 'at', 'by', 'from', 'to', 'with', 'without', 'about', 'above',
    'after', 'again', 'against', 'all', 'am', 'are', 'as', 'at', 'be',
    'because', 'been', 'before', 'being', 'below', 'between', 'both',
    'can', 'cannot', 'could', 'did', 'do', 'does', 'doing', 'down', 'during',
    'each', 'few', 'further', 'had', 'has', 'have', 'having', 'he', 'her',
    'here', 'hers', 'herself', 'him', 'himself', 'his', 'how', 'i', 'if',
    'into', 'is', 'it', 'its', 'itself', 'just', 'me', 'more', 'most', 'my',
    'myself', 'no', 'not', 'now', 'of', 'off', 'once', 'only', 'other', 'our',
    'ours', 'ourselves', 'out', 'over', 'own', 'same', 'she', 'should',
    'some', 'such', 'than', 'that', 'their', 'theirs', 'them', 'themselves',
    'then', 'there', 'these', 'they', 'this', 'those', 'through', 'too',
    'under', 'until', 'up', 'very', 'was', 'we', 'were', 'what', 'when',
    'where', 'which', 'while', 'who', 'whom', 'why', 'will', 'would', 'you',
    'your', 'yours', 'yourself', 'yourselves',
    'ai', 'news', 'model', 'models', 'new', 'technology', 'tech', 'data' # Domain specific common words
}

# --- DeepSeek API Call for Keyword Brainstorming ---
def _call_deepseek_for_keywords(primary_keyword, article_title, article_summary_glimpse, num_needed):
    if not DEEPSEEK_API_KEY:
        logger.warning("DEEPSEEK_API_KEY not set. Cannot use LLM for keyword brainstorming.")
        return []

    prompt_text = f"""
    Given the primary keyword phrase "{primary_keyword}" for a tech news article titled "{article_title}" with an initial summary glimpse: "{article_summary_glimpse[:200]}...",
    brainstorm up to {num_needed + 5} closely related and SEO-valuable keywords or short phrases (2-4 words ideally).
    Focus on terms that users interested in the primary keyword might also search for.
    Include a mix of specific entities, related technologies, concepts, or user problems/questions if applicable.
    Prioritize terms that are distinct from the primary keyword but semantically linked. Avoid overly generic terms unless they are highly relevant contextually.
    Return these keywords as a flat JSON list of strings. Example: ["keyword1", "long-tail keyword 2", "concept 3"]
    Ensure the output is ONLY the JSON list, nothing else.
    """
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
    payload = {
        "model": DEEPSEEK_KEYWORD_MODEL,
        "messages": [{"role": "user", "content": prompt_text}],
        "max_tokens": DEEPSEEK_MAX_TOKENS_KEYWORDS,
        "temperature": DEEPSEEK_TEMPERATURE_KEYWORDS,
        "response_format": {"type": "json_object"} # Request JSON output
    }
    logger.info(f"Asking DeepSeek to brainstorm keywords for: '{primary_keyword}' (needs ~{num_needed})")
    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=45)
        response.raise_for_status()
        result = response.json()
        if result.get("choices") and result["choices"][0].get("message"):
            content_str = result["choices"][0]["message"].get("content","").strip()
            # The response should be a JSON string representing a list.
            # Sometimes LLMs wrap it like: {"keywords": ["k1", "k2"]}
            # Or just the list: ["k1", "k2"]
            try:
                # Attempt to parse the entire content as JSON first
                potential_json = json.loads(content_str)
                if isinstance(potential_json, list):
                    keywords = [str(kw).strip() for kw in potential_json if isinstance(kw, str) and kw.strip()]
                    logger.info(f"DeepSeek brainstormed {len(keywords)} keywords (direct list).")
                    return keywords
                elif isinstance(potential_json, dict):
                    # Look for a common key like "keywords", "tags", "related_terms"
                    for key in ["keywords", "tags", "related_terms", "suggestions", "keyword_list"]:
                        if isinstance(potential_json.get(key), list):
                            keywords = [str(kw).strip() for kw in potential_json[key] if isinstance(kw, str) and kw.strip()]
                            logger.info(f"DeepSeek brainstormed {len(keywords)} keywords (from dict key '{key}').")
                            return keywords
                    logger.warning(f"DeepSeek returned a dict but no known keyword list key found: {potential_json.keys()}")
            except json.JSONDecodeError:
                logger.error(f"DeepSeek keyword response not valid JSON: {content_str}")
        return []
    except Exception as e:
        logger.exception(f"DeepSeek API call for keywords failed: {e}")
        return []


# --- Google Ads API Interaction ---
def _fetch_keyword_ideas_from_ads_api(seed_keyword, target_url=None):
    # (This function remains largely the same as your provided "fixed" version)
    # Ensure it returns an empty list on any failure rather than None.
    if not ENABLE_LIVE_ADS_API:
        logger.warning("Live Google Ads API call disabled. No keywords will be fetched.")
        return []
    logger.info(f"Attempting Google Ads API call for seed: '{seed_keyword}' using config: {GOOGLE_ADS_CONFIG_PATH}")
    if not os.path.exists(GOOGLE_ADS_CONFIG_PATH):
        logger.error(f"Google Ads YAML config not found: {GOOGLE_ADS_CONFIG_PATH}. Cannot fetch live keywords.")
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
             logger.error("No seed keyword or URL for Ads API."); return []
        response = keyword_plan_idea_service.generate_keyword_ideas(request=request)
        ideas = []
        for result in response.results:
            metrics = result.keyword_idea_metrics
            avg_searches = metrics.avg_monthly_searches if metrics and metrics.HasField("avg_monthly_searches") else 0 # Default to 0
            comp_val = metrics.competition if metrics and metrics.HasField("competition") else None
            comp_level = googleads_client.enums.KeywordPlanCompetitionLevelEnum(comp_val).name if comp_val is not None else 'UNKNOWN'
            ideas.append({'text': result.text, 'avg_monthly_searches': avg_searches, 'competition_level': comp_level})
        logger.info(f"Google Ads API returned {len(ideas)} ideas for '{seed_keyword}'.")
        return ideas
    except GoogleAdsException as ex:
        logger.error(f"Google Ads API Error. Failure: {ex.failure}")
        return []
    except ImportError:
        logger.error("Google Ads library ('google-ads') is not installed. Cannot fetch live keywords.")
        return []
    except Exception as e:
        logger.exception(f"Unexpected error during Google Ads API call: {e}")
        return []


# --- Advanced Keyword Processing/Selection ---
def _calculate_relevance_score(keyword_text, primary_keyword, article_title):
    # (More nuanced relevance calculation if needed, current one is okay as a base)
    primary_words = set(primary_keyword.lower().split())
    title_words = set(article_title.lower().split())
    keyword_words = set(keyword_text.lower().split())
    if not primary_words: return 0.0
    
    # Score based on primary keyword
    common_with_primary = primary_words.intersection(keyword_words)
    relevance_primary = len(common_with_primary) / max(len(primary_words), len(keyword_words), 1)

    # Score based on title (less weight)
    common_with_title = title_words.intersection(keyword_words)
    relevance_title = len(common_with_title) / max(len(title_words), len(keyword_words), 1)
    
    score = 0.7 * relevance_primary + 0.3 * relevance_title

    if primary_keyword.lower() in keyword_text.lower() or keyword_text.lower() in primary_keyword.lower():
        score = max(score, 0.70) 
    if len(keyword_words) > len(primary_words) + 6: score *= 0.75 # Penalize very long keywords more
    return score


def _score_and_select_keywords(api_ideas, primary_keyword, article_title, num_to_select):
    if not api_ideas: return []
    scored_ideas = []
    for idea in api_ideas:
        kw_text = idea.get('text')
        if not kw_text or not isinstance(kw_text, str) or not kw_text.strip(): continue
        kw_cleaned = kw_text.strip().lower() # Normalize to lower for processing/deduplication
        
        if kw_cleaned == primary_keyword.lower(): continue # Skip if identical to primary

        relevance = _calculate_relevance_score(kw_cleaned, primary_keyword, article_title)
        if relevance < MIN_RELEVANCE_SCORE_ADS_API:
            logger.debug(f"ADS_SELECT: Skipping '{kw_cleaned}' (Relevance: {relevance:.2f} vs {primary_keyword})")
            continue
        
        score = relevance * 1000
        volume = idea.get('avg_monthly_searches', 0)
        comp = idea.get('competition_level', 'UNKNOWN')

        # Volume scoring (more aggressive)
        if volume > 10000: score += 1000
        elif volume > 1000: score += 500
        elif volume > 100: score += 200
        elif volume > 10: score += 50
        else: score += 10
        
        # Competition scoring
        if comp == 'HIGH': score *= 0.6
        elif comp == 'MEDIUM': score *= 0.85
        elif comp == 'LOW': score *= 1.3

        # Keyword length factor
        num_words = len(kw_cleaned.split())
        if num_words == 1 and volume < 5000: score *= 0.7 # Penalize single words unless very high volume
        elif 2 <= num_words <= 4: score *= 1.15 # Sweet spot
        elif num_words >= 5: score *= 0.85 # Penalize longer tails unless relevance/volume are very high

        # Deduplication by adding to a set for checking, store original case for output
        scored_ideas.append({'text_original_case': idea.get('text').strip(), 'text_lower': kw_cleaned, 'score': score, 'relevance': relevance, 'volume': volume, 'competition': comp})

    # Sort and deduplicate based on the lowercased text
    unique_scored_ideas = []
    seen_lower = set()
    scored_ideas.sort(key=lambda x: x['score'], reverse=True)
    for idea_info in scored_ideas:
        if idea_info['text_lower'] not in seen_lower:
            unique_scored_ideas.append(idea_info)
            seen_lower.add(idea_info['text_lower'])
            
    logger.debug(f"Top {len(unique_scored_ideas)} unique scored API ideas for '{primary_keyword}':")
    for i, item in enumerate(unique_scored_ideas[:num_to_select + 5]): # Log a few extra
         logger.debug(f"  {i+1}. '{item['text_original_case']}' (Score: {item['score']:.0f}, Rel: {item['relevance']:.2f}, Vol: {item['volume']}, Comp: {item['competition']})")
    
    selected_keywords = [idea['text_original_case'] for idea in unique_scored_ideas[:num_to_select]]
    logger.info(f"Selected {len(selected_keywords)} keywords from Ads API based on advanced scoring.")
    return selected_keywords

# --- Main Agent Function ---
def run_keyword_research_agent(article_data):
    article_id = article_data.get('id', 'N/A')
    article_title = article_data.get('title', '')
    article_summary_glimpse = article_data.get('summary', '')[:300] # For LLM context

    logger.info(f"Running ADVANCED Keyword Research for ID: {article_id} (Target: >= {MIN_DESIRED_TOTAL_TAGS} tags)...")
    primary_keyword_raw = article_data.get('filter_verdict', {}).get('primary_topic_keyword')

    if not primary_keyword_raw or not isinstance(primary_keyword_raw, str) or len(primary_keyword_raw.strip()) == 0:
        logger.warning(f"No valid primary_topic_keyword for {article_id}. Using article title as primary.")
        primary_keyword_raw = article_title
        if not primary_keyword_raw or not isinstance(primary_keyword_raw, str) or len(primary_keyword_raw.strip()) == 0:
             article_data['researched_keywords'] = []
             article_data['keyword_agent_error'] = "Missing primary keyword and title for research."
             logger.error(article_data['keyword_agent_error'])
             return article_data
    
    primary_keyword = primary_keyword_raw.strip()
    article_data['primary_keyword'] = primary_keyword # Store the cleaned primary keyword

    # --- Keyword Generation Pipeline ---
    final_keywords_set = set() # Use a set for automatic deduplication (case-insensitive)
    final_keywords_set_display_case = {} # Store original casing

    def add_keyword(kw):
        kw_cleaned = kw.strip()
        if kw_cleaned and kw_cleaned.lower() not in (k.lower() for k in final_keywords_set_display_case.keys()):
            final_keywords_set_display_case[kw_cleaned] = kw_cleaned # Store with original case for display

    add_keyword(primary_keyword)

    # 1. Attempt Google Ads API
    ads_api_keywords = []
    if ENABLE_LIVE_ADS_API:
        logger.info("Fetching keywords from Google Ads API...")
        raw_ads_ideas = _fetch_keyword_ideas_from_ads_api(primary_keyword, target_url=article_data.get('link'))
        if raw_ads_ideas:
            ads_api_keywords = _score_and_select_keywords(raw_ads_ideas, primary_keyword, article_title, TARGET_NUM_GOOD_SECONDARY_KEYWORDS_FROM_API)
            for kw in ads_api_keywords: add_keyword(kw)
        else:
            logger.warning("Google Ads API returned no ideas or failed. Will rely on other methods.")
    
    # 2. If not enough, try LLM brainstorming
    if len(final_keywords_set_display_case) < MIN_DESIRED_TOTAL_TAGS:
        num_needed_from_llm = MIN_DESIRED_TOTAL_TAGS - len(final_keywords_set_display_case) + 3 # Ask for a few more
        logger.info(f"Tag count ({len(final_keywords_set_display_case)}) is low. Brainstorming with DeepSeek, need ~{num_needed_from_llm}.")
        llm_brainstormed_keywords = _call_deepseek_for_keywords(primary_keyword, article_title, article_summary_glimpse, num_needed_from_llm)
        if llm_brainstormed_keywords:
            for kw in llm_brainstormed_keywords: add_keyword(kw)
        else:
            logger.warning("LLM brainstorming returned no keywords.")

    # 3. If STILL not enough, split the primary keyword (if it's a phrase)
    if len(final_keywords_set_display_case) < MIN_DESIRED_TOTAL_TAGS:
        primary_phrase_words = primary_keyword.split()
        if len(primary_phrase_words) > 1:
            logger.info(f"Tag count ({len(final_keywords_set_display_case)}) still low. Splitting primary: '{primary_keyword}'.")
            for word in primary_phrase_words:
                cleaned_word = re.sub(r'[^\w\s-]', '', word).strip()
                if len(cleaned_word) >= MIN_KEYWORD_LENGTH_FOR_SPLIT_WORDS and cleaned_word.lower() not in COMMON_WORDS_TO_EXCLUDE:
                    add_keyword(cleaned_word.capitalize())
                    if len(final_keywords_set_display_case) >= MIN_DESIRED_TOTAL_TAGS + 2: # Allow a couple extra from splitting
                        break
    
    # 4. Final Check: If still desperate, and Ads API had more ideas, grab some less strictly scored ones
    if len(final_keywords_set_display_case) < MIN_DESIRED_TOTAL_TAGS and ENABLE_LIVE_ADS_API and raw_ads_ideas:
        logger.info(f"Tag count ({len(final_keywords_set_display_case)}) critically low. Re-visiting all Ads API ideas less strictly.")
        all_ads_texts_lower = {kw.lower() for kw in final_keywords_set_display_case.keys()}
        for idea in raw_ads_ideas:
            kw_text_original = idea.get('text','').strip()
            if kw_text_original and kw_text_original.lower() not in all_ads_texts_lower and kw_text_original.lower() != primary_keyword.lower():
                add_keyword(kw_text_original)
                all_ads_texts_lower.add(kw_text_original.lower())
                if len(final_keywords_set_display_case) >= MIN_DESIRED_TOTAL_TAGS:
                    break

    # Prepare final list: primary first, then the rest sorted by some logic (e.g., length then alpha)
    final_keyword_list = [primary_keyword]
    other_keywords = [kw for kw in final_keywords_set_display_case.values() if kw.lower() != primary_keyword.lower()]
    other_keywords.sort(key=lambda x: (-len(x.split()), x.lower())) # Sort by num words desc, then alpha
    final_keyword_list.extend(other_keywords)
    
    # Ensure we don't exceed a reasonable max, e.g. 15, if too many were generated
    final_keyword_list = final_keyword_list[:MIN_DESIRED_TOTAL_TAGS + 7]


    article_data['researched_keywords'] = final_keyword_list
    
    if len(final_keyword_list) < MIN_DESIRED_TOTAL_TAGS:
        error_msg = f"Could only generate {len(final_keyword_list)}/{MIN_DESIRED_TOTAL_TAGS} desired tags after all methods."
        article_data['keyword_agent_error'] = error_msg
        logger.warning(f"For Article ID {article_id}: {error_msg}")
    else:
        article_data['keyword_agent_error'] = None

    logger.info(f"Keyword research for ID {article_id} COMPLETE. Final tags ({len(final_keyword_list)}): {final_keyword_list}")
    return article_data

# --- Standalone Execution (for testing) ---
if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO) # Set root logger
    logger.setLevel(logging.DEBUG) # Set this module's logger to DEBUG for verbose output

    # Test Case 1: Long primary keyword, expect splitting and API
    test_article_1 = {
        'id': 'adv-kw-test-001',
        'title': "OpenAI's Newest GPT-5 Architecture Shows Staggering Improvement in Multimodal Reasoning",
        'summary': "OpenAI has just unveiled details about its upcoming GPT-5 model, focusing on enhanced multimodal capabilities, including video and audio processing, and significantly improved logical reasoning scores on several benchmarks.",
        'filter_verdict': { 'primary_topic_keyword': "GPT-5 multimodal reasoning improvement" },
        'link': 'https://example.com/gpt5-multimodal-boost'
    }
    logger.info("\n--- Running ADVANCED Keyword Research Test (Long Primary) ---")
    result_1 = run_keyword_research_agent(test_article_1.copy())
    print("\n--- Results for Long Primary ---")
    if result_1.get('keyword_agent_error'): print(f"Error: {result_1['keyword_agent_error']}")
    print(f"Primary: {result_1.get('primary_keyword')}")
    print(f"Researched Tags ({len(result_1.get('researched_keywords',[]))}): {result_1.get('researched_keywords')}")

    # Test Case 2: Shorter primary, heavily rely on API and LLM brainstorm
    test_article_2 = {
        'id': 'adv-kw-test-002',
        'title': "Nvidia Blackwell GPU Announced",
        'summary': "Nvidia has officially announced its new Blackwell GPU architecture, promising significant performance gains for AI training and inference workloads. Details on specific SKUs and pricing are expected later this year.",
        'filter_verdict': { 'primary_topic_keyword': "Nvidia Blackwell GPU" },
        'link': 'https://example.com/nvidia-blackwell'
    }
    logger.info("\n--- Running ADVANCED Keyword Research Test (Short Primary) ---")
    result_2 = run_keyword_research_agent(test_article_2.copy())
    print("\n--- Results for Short Primary ---")
    if result_2.get('keyword_agent_error'): print(f"Error: {result_2['keyword_agent_error']}")
    print(f"Primary: {result_2.get('primary_keyword')}")
    print(f"Researched Tags ({len(result_2.get('researched_keywords',[]))}): {result_2.get('researched_keywords')}")
    
    # Test Case 3: No Google Ads API (simulate by disabling flag temporarily)
    # This requires ENABLE_LIVE_ADS_API = False at the top for this block, or mocking
    # For a real standalone test of this, you'd manually set ENABLE_LIVE_ADS_API = False
    # For now, this test will still try to call it if the flag is True globally.
    # We can see its effect by looking at logs if google-ads.yaml is missing.
    logger.info("\n--- Running ADVANCED Keyword Research Test (Simulating No Ads API / Relying on LLM & Split) ---")
    # To truly test no Ads API, you'd comment out the call or ensure GOOGLE_ADS_CONFIG_PATH is invalid
    # For this example, if GOOGLE_ADS_CONFIG_PATH is invalid as per logs, it will simulate it.
    test_article_3 = {
        'id': 'adv-kw-test-003',
        'title': "The Ethical Implications of Advanced AI Autonomy",
        'summary': "A new report discusses the complex ethical challenges posed by increasingly autonomous AI systems, particularly in decision-making processes with real-world consequences. It calls for robust frameworks.",
        'filter_verdict': { 'primary_topic_keyword': "Ethical Implications of AI Autonomy" },
        'link': 'https://example.com/ai-ethics-autonomy'
    }
    result_3 = run_keyword_research_agent(test_article_3.copy())
    print("\n--- Results for No Ads API (Relies on LLM & Split) ---")
    if result_3.get('keyword_agent_error'): print(f"Error: {result_3['keyword_agent_error']}")
    print(f"Primary: {result_3.get('primary_keyword')}")
    print(f"Researched Tags ({len(result_3.get('researched_keywords',[]))}): {result_3.get('researched_keywords')}")

    logger.info("--- ADVANCED Keyword Research Agent Standalone Test Complete ---")