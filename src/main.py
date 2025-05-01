# src/main.py

# --- !! Path Setup - Must be at the very top !! ---
import sys
import os
PROJECT_ROOT_FOR_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT_FOR_PATH not in sys.path:
    sys.path.insert(0, PROJECT_ROOT_FOR_PATH)
# --- End Path Setup ---

# --- Standard Imports ---
import time
import json
import logging
import glob
import shutil
from jinja2 import Environment, FileSystemLoader
import markdown
import re # Needed for slug generation
from dotenv import load_dotenv
from datetime import datetime, timezone
from urllib.parse import urljoin # To create absolute URLs

# --- Import Agent and Scraper Functions ---
try:
    # ** IMPORT SCRAPER **
    from src.scrapers.news_scraper import scrape_news, load_processed_ids, NEWS_FEED_URLS # Import URLs too
    from src.scrapers.image_scraper import find_best_image, scrape_source_for_image
    # ** IMPORT AGENTS **
    from src.agents.filter_news_agent import run_filter_agent
    from src.agents.similarity_check_agent import run_similarity_check_agent
    from src.agents.seo_article_generator_agent import run_seo_article_agent
    from src.agents.tags_generator_agent import run_tags_generator_agent
    # *** IMPORT TTS AGENT ***
    from src.agents.tts_generator_agent import run_tts_generator_agent
except ImportError as e:
     print(f"FATAL IMPORT ERROR: {e}")
     print("Check file names, function definitions, and __init__.py files.")
     sys.exit(1)

# --- Load Environment Variables ---
load_dotenv(dotenv_path=os.path.join(PROJECT_ROOT_FOR_PATH, '.env'))
# CHECK_INTERVAL_SECONDS = int(os.getenv('CHECK_INTERVAL_SECONDS', 900)) # No longer needed for sleep
MAX_HOME_PAGE_ARTICLES = int(os.getenv('MAX_HOME_PAGE_ARTICLES', 20))
AUTHOR_NAME_DEFAULT = os.getenv('AUTHOR_NAME', 'AI News Team')
# *** ADDED Site Config Vars ***
YOUR_WEBSITE_NAME = os.getenv('YOUR_WEBSITE_NAME', 'Dacoola') # Default name
YOUR_WEBSITE_LOGO_URL = os.getenv('YOUR_WEBSITE_LOGO_URL', '') # Get logo URL
YOUR_SITE_BASE_URL = os.getenv('YOUR_SITE_BASE_URL', '') # e.g., https://www.dacoola.com
if not YOUR_SITE_BASE_URL:
    logging.warning("YOUR_SITE_BASE_URL environment variable not set. Canonical and Open Graph URLs will be relative.")
# *** ADD TTS API KEY CHECK ***
CAMB_AI_API_KEY = os.getenv('CAMB_AI_API_KEY')
if not CAMB_AI_API_KEY:
     logging.warning("CAMB_AI_API_KEY environment variable not set. TTS generation will be skipped.")


# --- Configuration ---
DATA_DIR = os.path.join(PROJECT_ROOT_FOR_PATH, 'data')
SCRAPED_ARTICLES_DIR = os.path.join(DATA_DIR, 'scraped_articles')
PROCESSED_JSON_DIR = os.path.join(DATA_DIR, 'processed_json')
PUBLIC_DIR = os.path.join(PROJECT_ROOT_FOR_PATH, 'public')
OUTPUT_HTML_DIR = os.path.join(PUBLIC_DIR, 'articles')
TEMPLATE_DIR = os.path.join(PROJECT_ROOT_FOR_PATH, 'templates')
SITE_DATA_FILE = os.path.join(PUBLIC_DIR, 'site_data.json')
# *** ADD AUDIO OUTPUT DIR ***
OUTPUT_AUDIO_DIR = os.path.join(PUBLIC_DIR, 'audio') # Audio files saved here
# *** ADD ALL ARTICLES FILE PATH ***
ALL_ARTICLES_FILE = os.path.join(PUBLIC_DIR, 'all_articles.json')

# --- Setup Logging ---
log_file_path = os.path.join(PROJECT_ROOT_FOR_PATH, 'dacoola.log')
logging.basicConfig(
    level=logging.INFO, # Changed to INFO for build logs
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_file_path)
    ]
)
logger = logging.getLogger('main_orchestrator')

# --- Jinja2 Setup ---
try:
    # Add escapejs filter for JSON-LD safety
    def escapejs_filter(value):
        if value is None: return ''
        # Basic JS string escaping
        value = str(value)
        value = value.replace('\\', '\\\\')
        value = value.replace("'", "\\'")
        value = value.replace('"', '\\"')
        value = value.replace('\n', '\\n')
        value = value.replace('\r', '') # Remove carriage returns
        value = value.replace('/', '\\/') # Escape forward slash for script tags
        value = value.replace('<', '\\u003c') # Escape <
        value = value.replace('>', '\\u003e') # Escape >
        return value

    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    env.filters['escapejs'] = escapejs_filter # Register the filter
    logger.info(f"Jinja2 environment loaded from {TEMPLATE_DIR}")
except Exception as e:
    logger.exception(f"CRITICAL: Failed to initialize Jinja2 from {TEMPLATE_DIR}. Exiting.")
    sys.exit(1)

# --- Helper Functions ---
def ensure_directories():
    os.makedirs(SCRAPED_ARTICLES_DIR, exist_ok=True)
    os.makedirs(PROCESSED_JSON_DIR, exist_ok=True)
    os.makedirs(OUTPUT_HTML_DIR, exist_ok=True)
    os.makedirs(OUTPUT_AUDIO_DIR, exist_ok=True)
    logger.info("Ensured data, public, and audio directories exist.")

def load_article_data(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f: return json.load(f)
    except Exception as e: logger.error(f"Error loading {filepath}: {e}"); return None

def save_processed_data(filepath, article_data):
     try:
          os.makedirs(os.path.dirname(filepath), exist_ok=True)
          with open(filepath, 'w', encoding='utf-8') as f:
               json.dump(article_data, f, indent=4, ensure_ascii=False)
          logger.info(f"Saved final processed data to {filepath}")
          return True
     except Exception as e:
          logger.error(f"Failed to save final processed data to {filepath}: {e}")
          return False

def remove_scraped_file(filepath):
     try:
          if os.path.exists(filepath):
               os.remove(filepath)
               logger.debug(f"Removed original scraped file: {os.path.basename(filepath)}")
          else:
               logger.warning(f"Scraped file to remove not found: {filepath}")
     except OSError as e:
          logger.error(f"Failed to remove original scraped file {filepath}: {e}")

def format_tags_html(tags_list):
    if not tags_list or not isinstance(tags_list, list): return ""
    return " ".join([f'<span class="tag-item"><a href="#">{tag}</a></span>' for tag in tags_list])

def render_post_page(template_variables, output_filename):
    try:
        template = env.get_template('post_template.html')
        html_content = template.render(template_variables)
        safe_filename = output_filename
        if not safe_filename: safe_filename = template_variables.get('id', 'untitled')
        output_path = os.path.join(OUTPUT_HTML_DIR, f"{safe_filename}.html")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f: f.write(html_content)
        logger.info(f"Rendered HTML: {output_path}")
        return output_path
    except Exception as e: logger.exception(f"CRITICAL Error rendering template {output_filename}: {e}"); return None

# --- Site Data Management ---
def load_recent_articles_for_comparison():
    try:
        if os.path.exists(SITE_DATA_FILE):
            with open(SITE_DATA_FILE, 'r', encoding='utf-8') as f:
                site_data = json.load(f)
                if isinstance(site_data.get('articles'), list):
                    # Return only titles and summaries needed for the check
                    return [{"title": a.get("title"), "summary_short": a.get("summary_short")}
                            for a in site_data["articles"][:50] if a.get("title")] # Limit context size
    except Exception as e: logger.warning(f"Could not load recent articles from {SITE_DATA_FILE} for comparison: {e}")
    return []

def update_site_data(new_article_info):
    site_data = {"articles": []}
    all_articles_data = {"articles": []}

    # Load existing site_data (for homepage limit)
    try:
        if os.path.exists(SITE_DATA_FILE):
            with open(SITE_DATA_FILE, 'r', encoding='utf-8') as f:
                site_data = json.load(f)
                if not isinstance(site_data.get('articles'), list):
                     logger.warning(f"{SITE_DATA_FILE} format invalid. Resetting.")
                     site_data = {"articles": []}
    except Exception as e: logger.warning(f"Could not load {SITE_DATA_FILE}: {e}. Starting fresh."); site_data = {"articles": []}

    # Load existing full articles list (for appending/updating)
    try:
        if os.path.exists(ALL_ARTICLES_FILE):
            with open(ALL_ARTICLES_FILE, 'r', encoding='utf-8') as f:
                all_articles_data = json.load(f)
                if not isinstance(all_articles_data.get('articles'), list):
                     logger.warning(f"{ALL_ARTICLES_FILE} format invalid. Resetting.")
                     all_articles_data = {"articles": []}
    except Exception as e: logger.warning(f"Could not load {ALL_ARTICLES_FILE}: {e}. Starting fresh."); all_articles_data = {"articles": []}


    article_id = new_article_info.get('id')
    site_data_found = False
    all_articles_found = False

    # Update/Add to homepage list (site_data)
    if article_id:
        for i, existing_article in enumerate(site_data["articles"]):
            if existing_article.get('id') == article_id:
                updated_entry = {**existing_article, **new_article_info}
                site_data["articles"][i] = updated_entry
                site_data_found = True; logger.debug(f"Updating {article_id} in site_data.json"); break
    if not site_data_found and article_id: site_data["articles"].append(new_article_info); logger.debug(f"Adding {article_id} to site_data.json")

    # Update/Add to full list (all_articles_data)
    if article_id:
        for i, existing_article in enumerate(all_articles_data["articles"]):
            if existing_article.get('id') == article_id:
                updated_entry = {**existing_article, **new_article_info}
                all_articles_data["articles"][i] = updated_entry
                all_articles_found = True; logger.debug(f"Updating {article_id} in all_articles.json"); break
    if not all_articles_found and article_id: all_articles_data["articles"].append(new_article_info); logger.debug(f"Adding {article_id} to all_articles.json")


    # Sort both lists by date
    def get_sort_key(x):
        date_str = x.get('published_iso', '1970-01-01T00:00:00')
        try: return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except:
             try: return datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=timezone.utc)
             except: return datetime(1970, 1, 1, tzinfo=timezone.utc)

    site_data["articles"].sort(key=get_sort_key, reverse=True)
    all_articles_data["articles"].sort(key=get_sort_key, reverse=True)

    # Apply limit ONLY to site_data
    site_data["articles"] = site_data["articles"][:MAX_HOME_PAGE_ARTICLES]

    # Save site_data.json
    try:
        with open(SITE_DATA_FILE, 'w', encoding='utf-8') as f: json.dump(site_data, f, indent=2, ensure_ascii=False)
        logger.info(f"Updated {SITE_DATA_FILE} ({len(site_data['articles'])} articles).")
    except Exception as e: logger.error(f"Failed to save {SITE_DATA_FILE}: {e}")

    # Save all_articles.json
    try:
        with open(ALL_ARTICLES_FILE, 'w', encoding='utf-8') as f: json.dump(all_articles_data, f, indent=2, ensure_ascii=False)
        logger.info(f"Updated {ALL_ARTICLES_FILE} ({len(all_articles_data['articles'])} articles).")
    except Exception as e: logger.error(f"Failed to save {ALL_ARTICLES_FILE}: {e}")


# --- Main Processing Pipeline ---
def process_single_article(json_filepath, recent_articles_context):
    """Processes one scraped article JSON file through the entire pipeline."""
    logger.info(f"--- Processing article file: {os.path.basename(json_filepath)} ---")
    article_data = load_article_data(json_filepath)
    if not article_data: return False

    article_id = article_data.get('id', f'UNKNOWN_ID_{os.path.basename(json_filepath)}')
    processed_file_path = os.path.join(PROCESSED_JSON_DIR, os.path.basename(json_filepath))

    try:
        # == Step 0: Check if already processed ==
        if os.path.exists(processed_file_path):
             logger.info(f"Article {article_id} already processed (JSON exists). Skipping pipeline.")
             remove_scraped_file(json_filepath)
             return False

        # == Step 1: Filter Agent ==
        article_data = run_filter_agent(article_data)
        if not article_data or not article_data.get('filter_verdict'):
             logger.error(f"Filter Agent failed for {article_id}. Error: {article_data.get('filter_error', 'Unknown')}")
             return False
        filter_verdict = article_data['filter_verdict']
        importance_level = filter_verdict.get('importance_level')
        assigned_topic = filter_verdict.get('topic')
        if importance_level == "Boring":
            logger.info(f"Article {article_id} is Boring. Skipping.")
            remove_scraped_file(json_filepath)
            return False
        elif importance_level not in ["Interesting", "Breaking"]:
             logger.warning(f"Unknown importance level '{importance_level}' for {article_id}. Treating as Interesting.")
             importance_level = "Interesting"
        article_data['topic'] = assigned_topic
        article_data['is_breaking'] = (importance_level == "Breaking")
        logger.info(f"Article {article_id} is {importance_level} (Topic: {assigned_topic}). Checking duplicates...")
        primary_keyword = filter_verdict.get('primary_topic_keyword', article_data.get('title',''))
        article_data['primary_keyword'] = primary_keyword

        # == Step 2: Similarity Check ==
        similarity_result = run_similarity_check_agent(article_data, recent_articles_context)
        if similarity_result and similarity_result.get('is_semantic_duplicate'):
            logger.info(f"Article {article_id} is SEMANTIC DUPLICATE. Skipping. Reason: {similarity_result.get('reasoning')}")
            remove_scraped_file(json_filepath)
            return False
        elif similarity_result is None: logger.warning(f"Similarity check failed for {article_id}. Proceeding cautiously.")
        else: logger.info(f"Article {article_id} passed similarity check.")

        # == Step 3: Image Scraper / Finder ==
        scraped_image_url = None
        source_url = article_data.get('link')
        if source_url:
             try: scraped_image_url = scrape_source_for_image(source_url)
             except Exception as scrape_e: logger.error(f"Error scraping source image: {scrape_e}")
        if scraped_image_url: article_data['selected_image_url'] = scraped_image_url; logger.info(f"Using scraped image for {article_id}")
        else:
             logger.info(f"Image scraping failed/no image, using API search for {article_id}...")
             image_query = primary_keyword if primary_keyword else article_data.get('title', 'AI News')
             article_data['selected_image_url'] = find_best_image(image_query)
        if not article_data.get('selected_image_url'):
            logger.error(f"Failed to find image for {article_id}. Skipping.")
            return False

        # == Step 4: SEO Article Generator ==
        article_data = run_seo_article_agent(article_data)
        if not article_data or not article_data.get('seo_agent_results'):
            logger.error(f"SEO Agent failed for {article_id}. Error: {article_data.get('seo_agent_error', 'Unknown')}")
            # Don't return False here, maybe we can proceed without SEO data?
            # Or maybe we should? Decide based on how critical SEO data is.
            # For now, let's log the error and continue, but the post might be incomplete.
            # If SEO is mandatory, uncomment the next line:
            # return False
            seo_results = {} # Use an empty dict if SEO failed
        else:
            seo_results = article_data['seo_agent_results']

        # == Step 5: Tags Generator ==
        article_data = run_tags_generator_agent(article_data)
        if article_data.get('tags_agent_error'):
             logger.warning(f"Tags Agent failed/skipped for {article_id}. Error: {article_data.get('tags_agent_error')}")
        article_data['generated_tags'] = article_data.get('generated_tags', [])

        # == Step 6.5: Calculate Trend Score (Proxy) ==
        trend_score = 0
        importance_level = article_data.get('filter_verdict', {}).get('importance_level')
        tags_count = len(article_data.get('generated_tags', []))
        publish_date_iso = article_data.get('published_iso')

        if importance_level == "Interesting":
            trend_score += 10
        elif importance_level == "Breaking":
            trend_score += 5 # Less weight maybe? Or more? Adjust as needed.

        trend_score += tags_count # Add points for tags

        # Add recency factor (penalize very new and very old slightly)
        if publish_date_iso:
            try:
                publish_dt = datetime.fromisoformat(publish_date_iso.replace('Z', '+00:00'))
                now = datetime.now(timezone.utc)
                days_old = (now - publish_dt).total_seconds() / (60 * 60 * 24)
                # Simple curve: peaks around 1-3 days old, drops off
                recency_factor = max(0, 1 - abs(days_old - 2) / 5) # Peaks at day 2, zero after ~7 days / before -3 days
                trend_score += recency_factor * 5 # Add small recency bonus
            except Exception as e:
                logger.warning(f"Could not calculate recency for trend score: {e}")

        article_data['trend_score'] = round(trend_score, 2) # Store the score
        logger.debug(f"Calculated trend score for {article_id}: {article_data['trend_score']}")

        # == Step 6: TTS Generation ==
        article_data['audio_url'] = None
        if CAMB_AI_API_KEY:
            logger.info(f"Attempting TTS generation for {article_id}...")
            article_text_for_tts = seo_results.get('generated_article_body_md', '') # Use SEO result if available
            if article_text_for_tts:
                article_data = run_tts_generator_agent(article_data, article_text_for_tts, OUTPUT_AUDIO_DIR)
                if article_data.get('tts_agent_error'): logger.error(f"TTS Agent failed for {article_id}. Error: {article_data.get('tts_agent_error')}")
                else: logger.info(f"TTS successful for {article_id}. Path: {article_data.get('audio_url')}")
            else: logger.warning(f"No article body found for TTS generation for {article_id}.")
        else: logger.info("Skipping TTS generation - CAMB_AI_API_KEY not set.")


        # == Step 7: Prepare HTML Vars ==
        slug = article_data.get('title', 'article-' + article_id)
        slug = slug.lower().replace(' ', '-').replace('_', '-')
        slug = "".join(c for c in slug if c.isalnum() or c == '-')
        slug = re.sub('-+', '-', slug).strip('-')[:80]
        if not slug: slug = 'article-' + article_id
        article_data['slug'] = slug

        article_relative_path = f"articles/{slug}.html"
        canonical_url = urljoin(YOUR_SITE_BASE_URL + '/', article_relative_path) if YOUR_SITE_BASE_URL else article_relative_path

        body_md = seo_results.get('generated_article_body_md', article_data.get('summary','*Content generation incomplete.*')) # Fallback
        body_html = markdown.markdown(body_md, extensions=['fenced_code', 'tables'])
        tags_list = article_data.get('generated_tags', [])
        tags_html = format_tags_html(tags_list)
        publish_date_iso = article_data.get('published_iso', datetime.now(timezone.utc).isoformat())
        try:
             publish_dt = datetime.fromisoformat(publish_date_iso.replace('Z', '+00:00'))
             publish_date_formatted = publish_dt.strftime('%B %d, %Y')
        except: publish_date_formatted = datetime.now(timezone.utc).strftime('%B %d, %Y')

        # *** ADDED/UPDATED TEMPLATE VARS for SEO ***
        template_vars = {
            'PAGE_TITLE': seo_results.get('generated_title_tag', article_data.get('title', 'AI News')),
            'META_DESCRIPTION': seo_results.get('generated_meta_description', article_data.get('summary', '')[:160]),
            'AUTHOR_NAME': article_data.get('author', AUTHOR_NAME_DEFAULT),
            'META_KEYWORDS': ", ".join(tags_list), # Comma-separated for meta tag
            'CANONICAL_URL': canonical_url,
            'SITE_NAME': YOUR_WEBSITE_NAME,
            'YOUR_WEBSITE_LOGO_URL': YOUR_WEBSITE_LOGO_URL,
            'IMAGE_URL': article_data.get('selected_image_url'),
            'IMAGE_ALT_TEXT': seo_results.get('generated_title_tag', article_data.get('title', 'AI News Image')),
            'META_KEYWORDS_LIST': tags_list, # Python list for JSON-LD/OG
            'PUBLISH_ISO_FOR_META': publish_date_iso, # Raw ISO date for meta tags
            'JSON_LD_SCRIPT_BLOCK': seo_results.get('generated_json_ld', ''), # Use SEO result or empty string
            'ARTICLE_HEADLINE': article_data.get('title'),
            'PUBLISH_DATE': publish_date_formatted, # Formatted date for display
            'ARTICLE_BODY_HTML': body_html,
            'ARTICLE_TAGS_HTML': tags_html,
            'SOURCE_ARTICLE_URL': article_data.get('link', '#'),
            'ARTICLE_TITLE': article_data.get('title'),
            'id': article_id,
            'CURRENT_ARTICLE_ID': article_id,
            'CURRENT_ARTICLE_TOPIC': article_data.get('topic', ''), # Pass topic
            'CURRENT_ARTICLE_TAGS_JSON': json.dumps(tags_list), # Pass tags as JSON string
            'AUDIO_URL': article_data.get('audio_url') # Pass audio URL
        }

        # == Step 8: Render HTML ==
        generated_html_path = render_post_page(template_vars, slug)

        if generated_html_path:
            # == Step 9: Update Site Data ==
            site_data_entry = {
                "id": article_id,
                "title": article_data.get('title'),
                "link": article_relative_path, # Use relative path for JS fetches
                "published_iso": article_data.get('published_iso'),
                "summary_short": seo_results.get('generated_meta_description', article_data.get('summary', '')[:160] + '...'),
                "image_url": article_data.get('selected_image_url'),
                "topic": article_data.get('topic', 'News'),
                "is_breaking": article_data.get('is_breaking', False),
                "tags": article_data.get('generated_tags', []),
                "audio_url": article_data.get('audio_url') # Add audio URL to site data
            }
            update_site_data(site_data_entry)

            # == Step 10: Save Final Processed Data & Remove Original ==
            if save_processed_data(processed_file_path, article_data):
                 remove_scraped_file(json_filepath)
                 logger.info(f"--- Successfully processed article: {article_id} ---")
                 return True
            else:
                 logger.error(f"Failed to save processed JSON for {article_id}. Original scraped file kept.")
                 return False
        else:
            logger.error(f"Failed to render HTML for {article_id}. Keeping scraped JSON.");
            return False

    except Exception as process_e:
         logger.exception(f"CRITICAL failure processing {article_id} file {os.path.basename(json_filepath)}: {process_e}")
         return False


# --- TTS Retry Logic ---
def retry_failed_tts():
     if not CAMB_AI_API_KEY:
          logger.info("Skipping TTS retry check - CAMB_AI_API_KEY not set.")
          return

     logger.info("--- Checking for articles needing TTS retry ---")
     processed_files = glob.glob(os.path.join(PROCESSED_JSON_DIR, '*.json'))
     retried_count = 0
     failed_count = 0

     for filepath in processed_files:
          try:
               article_data = load_article_data(filepath)
               # Retry if audio_url is missing AND there was NO previous TTS error recorded
               # (prevents retrying indefinitely if TTS consistently fails for an article)
               if (article_data and not article_data.get('audio_url')
                    and article_data.get('seo_agent_results')
                    and article_data.get('tts_agent_error') is None):

                    article_id = article_data.get('id')
                    logger.info(f"Retrying TTS generation for article {article_id} from {os.path.basename(filepath)}")

                    article_text_for_tts = article_data.get('seo_agent_results', {}).get('generated_article_body_md', '')
                    if article_text_for_tts:
                         article_data = run_tts_generator_agent(article_data, article_text_for_tts, OUTPUT_AUDIO_DIR)
                         if save_processed_data(filepath, article_data):
                              if not article_data.get('tts_agent_error') and article_data.get('audio_url'):
                                   logger.info(f"TTS Retry Successful for {article_id}. Updating site_data.")
                                   # Update only the necessary fields in site_data
                                   site_data_entry = {"id": article_id, "audio_url": article_data.get('audio_url')}
                                   update_site_data(site_data_entry)
                                   retried_count += 1
                              else:
                                   logger.error(f"TTS Retry Failed for {article_id}. Error recorded: {article_data.get('tts_agent_error')}")
                                   failed_count +=1
                         else:
                              logger.error(f"Failed to save updated processed JSON after TTS retry for {article_id}")
                              failed_count += 1
                    else:
                         logger.warning(f"No article body found in processed JSON for {article_id}, cannot retry TTS.")
                         failed_count += 1
                    time.sleep(2) # Avoid hammering API during retries

          except Exception as retry_e:
               logger.exception(f"Error during TTS retry check for file {filepath}: {retry_e}")
               failed_count += 1

     logger.info(f"--- TTS Retry Check Complete. Successful Retries: {retried_count}, Failures During Retry: {failed_count} ---")


# --- Main Orchestration Logic (Runs Once) ---
if __name__ == "__main__":
    logger.info("--- === Dacoola AI News Orchestrator Starting Single Run === ---")
    ensure_directories()
    scraper_processed_ids = set()
    try: scraper_processed_ids = load_processed_ids()
    except Exception as load_e: logger.exception(f"Error loading processed IDs: {load_e}")

    # Run TTS retry logic once at the start of the build
    retry_failed_tts()

    # Removed the while True: loop here

    logger.info("--- Running Processing Cycle ---")
    # 1. Run Scraper
    try:
        new_articles_count = scrape_news(NEWS_FEED_URLS, scraper_processed_ids)
        logger.info(f"Scraper run completed. Found {new_articles_count} new JSON files potentially.")
    except NameError:
         logger.error("NEWS_FEED_URLS not defined. Cannot run scraper.")
         sys.exit(1) # Exit if scraper config fails
    except Exception as scrape_e:
        logger.exception(f"Scraper failed: {scrape_e}")
        sys.exit(1) # Exit if scraper fails

    # 2. Load context for similarity check
    recent_articles_context = load_recent_articles_for_comparison()
    logger.info(f"Loaded {len(recent_articles_context)} recent articles for duplicate checking.")

    # 3. Process newly scraped JSON files
    json_files = []
    try: json_files = glob.glob(os.path.join(SCRAPED_ARTICLES_DIR, '*.json'))
    except Exception as glob_e: logger.exception(f"Error listing JSON files: {glob_e}")

    if not json_files: logger.info("No new scraped articles to process.")
    else:
        logger.info(f"Found {len(json_files)} scraped articles to process.")
        processed_count = 0; failed_skipped_count = 0
        try: json_files.sort(key=os.path.getmtime) # Process older scraped files first
        except Exception as sort_e: logger.warning(f"Could not sort JSON files: {sort_e}")

        for filepath in json_files:
            if process_single_article(filepath, recent_articles_context):
                processed_count += 1
                # OPTIONAL: Reload context after each success to prevent duplicates *within the same run*
                # If processing many files, this adds overhead. If few files, it's safer.
                # recent_articles_context = load_recent_articles_for_comparison()
            else:
                 failed_skipped_count += 1
            time.sleep(2) # Keep short sleep between API-heavy processing steps

        logger.info(f"Processing cycle complete. Successful: {processed_count}, Failed/Skipped: {failed_skipped_count}")

    # Removed the sleep logic and outer loop

    logger.info("--- === Dacoola AI News Orchestrator Single Run Finished === ---")
    # Script will now exit naturally