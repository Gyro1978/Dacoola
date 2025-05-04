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
import re # <-- Added import
import requests
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta # <-- Added timedelta
from urllib.parse import urljoin # <-- Added import
import markdown # <-- Added import

# --- Import Sitemap Generator ---
try:
    # Assuming generate_sitemap.py is in the project root alongside main.py's parent (src)
    sys.path.insert(0, PROJECT_ROOT_FOR_PATH) # Ensure project root is in path
    from generate_sitemap import generate_sitemap as run_sitemap_generator
except ImportError as e:
    temp_log_msg = f"FATAL IMPORT ERROR: Could not import sitemap generator from generate_sitemap.py: {e}. Ensure it's in project root: {PROJECT_ROOT_FOR_PATH}"
    print(temp_log_msg)
    try:
        # Try logging if possible
        logging.critical(temp_log_msg)
    except:
        pass
    sys.exit(1)
# --- End Sitemap Generator Import ---


# --- Import Agent and Scraper Functions ---
try:
    from src.scrapers.news_scraper import (
        scrape_news, load_processed_ids, save_processed_id, get_article_id,
        NEWS_FEED_URLS, DATA_DIR as SCRAPER_DATA_DIR
    )
    from src.scrapers.image_scraper import find_best_image, scrape_source_for_image
    from src.agents.filter_news_agent import run_filter_agent
    from src.agents.seo_article_generator_agent import run_seo_article_agent
    from src.agents.tags_generator_agent import run_tags_generator_agent
    from src.social.twitter_poster import post_tweet_with_image
except ImportError as e:
     # Use standard print for early errors before logging might be fully set up
     print(f"FATAL IMPORT ERROR in main.py (agents/scrapers): {e}")
     print("Check file names, function definitions, and __init__.py files in src/ and subfolders.")
     try: logging.critical(f"FATAL IMPORT ERROR (agents/scrapers): {e}")
     except: pass
     sys.exit(1)

# --- Load Environment Variables ---
dotenv_path = os.path.join(PROJECT_ROOT_FOR_PATH, '.env'); load_dotenv(dotenv_path=dotenv_path)
AUTHOR_NAME_DEFAULT = os.getenv('AUTHOR_NAME', 'AI News Team')
YOUR_WEBSITE_NAME = os.getenv('YOUR_WEBSITE_NAME', 'Dacoola')
YOUR_WEBSITE_LOGO_URL = os.getenv('YOUR_WEBSITE_LOGO_URL', '')
raw_base_url = os.getenv('YOUR_SITE_BASE_URL', ''); YOUR_SITE_BASE_URL = (raw_base_url.rstrip('/') + '/') if raw_base_url else ''
MAKE_WEBHOOK_URL = os.getenv('MAKE_INSTAGRAM_WEBHOOK_URL', None)

# --- Setup Logging (Needs to be done AFTER imports and .env load) ---
log_file_path = os.path.join(PROJECT_ROOT_FOR_PATH, 'dacola.log')
try:
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    log_handlers = [ logging.StreamHandler(sys.stdout), logging.FileHandler(log_file_path, encoding='utf-8') ]
except OSError as e: print(f"Log setup warning: {e}. Log console only."); log_handlers = [logging.StreamHandler(sys.stdout)]
# Configure root logger - this will apply to loggers obtained via logging.getLogger() in other modules too
logging.basicConfig( level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S', handlers=log_handlers, force=True )
logger = logging.getLogger('main_orchestrator') # Now get the logger *after* basicConfig
if not YOUR_SITE_BASE_URL: logger.warning("YOUR_SITE_BASE_URL not set (critical for sitemap and canonical URLs).")
else: logger.info(f"Using site base URL: {YOUR_SITE_BASE_URL}")
if not YOUR_WEBSITE_LOGO_URL: logger.warning("YOUR_WEBSITE_LOGO_URL not set (used in structured data).")
if not MAKE_WEBHOOK_URL: logger.warning("MAKE_INSTAGRAM_WEBHOOK_URL not set (Webhook posting will be skipped).")

# --- Configuration ---
DATA_DIR_MAIN = os.path.join(PROJECT_ROOT_FOR_PATH, 'data')
SCRAPED_ARTICLES_DIR = os.path.join(DATA_DIR_MAIN, 'scraped_articles')
PROCESSED_JSON_DIR = os.path.join(DATA_DIR_MAIN, 'processed_json')
PUBLIC_DIR = os.path.join(PROJECT_ROOT_FOR_PATH, 'public')
OUTPUT_HTML_DIR = os.path.join(PUBLIC_DIR, 'articles')
TEMPLATE_DIR = os.path.join(PROJECT_ROOT_FOR_PATH, 'templates')
ALL_ARTICLES_FILE = os.path.join(PUBLIC_DIR, 'all_articles.json')
DAILY_TWEET_LIMIT = 3
TWITTER_TRACKER_FILE = os.path.join(DATA_DIR_MAIN, 'twitter_daily_limit.json')
ARTICLE_MAX_AGE_DAYS = 30 # <-- Added: Max age in days for processing

# --- Jinja2 Setup ---
try:
    from jinja2 import Environment, FileSystemLoader # Move jinja import here
    def escapejs_filter(value):
        if value is None: return ''; value = str(value); value = value.replace('\\', '\\\\').replace('"', '\\"').replace('/', '\\/')
        value = value.replace('<', '\\u003c').replace('>', '\\u003e'); value = value.replace('\b', '\\b').replace('\f', '\\f').replace('\n', '\\n')
        value = value.replace('\r', '\\r').replace('\t', '\\t'); return value
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True); env.filters['escapejs'] = escapejs_filter
    logger.info(f"Jinja2 environment loaded from {TEMPLATE_DIR}")
except Exception as e: logger.exception(f"CRITICAL: Failed Jinja2 init. Exiting."); sys.exit(1)

# --- Helper Functions (Defined at top level) ---
def ensure_directories():
    dirs_to_create = [ DATA_DIR_MAIN, SCRAPED_ARTICLES_DIR, PROCESSED_JSON_DIR, PUBLIC_DIR, OUTPUT_HTML_DIR, TEMPLATE_DIR ]
    try:
        for d in dirs_to_create:
            os.makedirs(d, exist_ok=True)
        logger.info("Ensured core directories exist.")
    except OSError as e: logger.exception(f"CRITICAL: Create directory fail {e.filename}: {e.strerror}"); sys.exit(1)

def load_article_data(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f: return json.load(f)
    except Exception as e: logger.error(f"Error loading {filepath}: {e}"); return None

def save_processed_data(filepath, article_data):
    try:
         os.makedirs(os.path.dirname(filepath), exist_ok=True)
         with open(filepath, 'w', encoding='utf-8') as f: json.dump(article_data, f, indent=4, ensure_ascii=False)
         logger.info(f"Saved final processed data to: {os.path.basename(filepath)}")
         return True
    except Exception as e: logger.error(f"Failed save final data {os.path.basename(filepath)}: {e}"); return False

def remove_scraped_file(filepath):
    try:
         if os.path.exists(filepath): os.remove(filepath); logger.debug(f"Removed original scraped file: {os.path.basename(filepath)}")
         else: logger.warning(f"Scraped file remove failed: Not found {filepath}")
    except OSError as e: logger.error(f"Failed remove scraped file {filepath}: {e}")

def format_tags_html(tags_list):
    if not tags_list or not isinstance(tags_list, list): return ""
    try:
        tag_links = []
        base = YOUR_SITE_BASE_URL if YOUR_SITE_BASE_URL else "/"
        for tag in tags_list:
            safe_tag = requests.utils.quote(str(tag))
            tag_url = urljoin(base, f"topic.html?name={safe_tag}")
            tag_links.append(f'<a href="{tag_url}" class="tag-link">{tag}</a>') # Added class for potential styling
        # Return tags separated by a space or comma+space for readability
        return ", ".join(tag_links)
    except Exception as e: logger.error(f"Error formatting tags: {tags_list} - {e}"); return ""

def get_sort_key(article_dict):
    """ Parses ISO date string for sorting, handles 'Z' and timezone offset. Returns datetime object."""
    fallback_date = datetime(1970, 1, 1, tzinfo=timezone.utc) # Consistent fallback
    date_str = article_dict.get('published_iso')
    if not date_str or not isinstance(date_str, str): return fallback_date

    try:
        # Handle 'Z' suffix for UTC explicitly
        if date_str.endswith('Z'):
            date_str = date_str[:-1] + '+00:00'
        dt = datetime.fromisoformat(date_str)
        # If datetime object is naive (no timezone), assume UTC
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt # Return timezone-aware datetime object
    except ValueError:
        logger.warning(f"Date parse error (ValueError) for ID {article_dict.get('id', 'N/A')}: '{date_str}'. Using fallback.")
        return fallback_date
    except Exception as e:
        logger.warning(f"Unexpected date parse error for ID {article_dict.get('id', 'N/A')}: {e}. Using fallback.")
        return fallback_date

def _read_tweet_tracker():
    try:
        if os.path.exists(TWITTER_TRACKER_FILE):
            with open(TWITTER_TRACKER_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
            if isinstance(data, dict) and 'date' in data and 'count' in data:
                # Validate data types
                if isinstance(data.get('date'), str) and isinstance(data.get('count'), int):
                     return data['date'], data['count']
                else:
                     logger.warning(f"Tweet tracker file {TWITTER_TRACKER_FILE} has invalid data types. Resetting.")
                     return None, 0
            else: logger.warning(f"Tweet tracker file {TWITTER_TRACKER_FILE} has invalid format. Resetting."); return None, 0
        else: logger.info(f"Tweet tracker file {TWITTER_TRACKER_FILE} not found. Start fresh."); return None, 0
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from tweet tracker {TWITTER_TRACKER_FILE}: {e}. Resetting.")
        return None, 0
    except Exception as e:
        logger.error(f"Error reading tweet tracker {TWITTER_TRACKER_FILE}: {e}. Resetting.")
        return None, 0

def _write_tweet_tracker(date_str, count):
    logger.debug(f"Writing tweet tracker: Date={date_str}, Count={count} to {TWITTER_TRACKER_FILE}")
    try:
        os.makedirs(os.path.dirname(TWITTER_TRACKER_FILE), exist_ok=True)
        with open(TWITTER_TRACKER_FILE, 'w', encoding='utf-8') as f: json.dump({'date': date_str, 'count': count}, f)
        logger.info(f"Updated tweet tracker: Date={date_str}, Count={count}")
    except Exception as e: logger.error(f"Error writing tweet tracker {TWITTER_TRACKER_FILE}: {e}")

def send_make_webhook(webhook_url, data):
    """Sends data (single dict or list of dicts) to Make webhook."""
    if not webhook_url: logger.warning("Make webhook URL missing. Skipping webhook send."); return False
    if not data: logger.warning("No data provided for Make webhook. Skipping."); return False

    is_batch = isinstance(data, list)
    payload = {"articles": data} if is_batch else data
    log_id_info = f"batch of {len(data)} articles" if is_batch else f"article ID: {data.get('id', 'N/A')}"

    try:
        headers = {'Content-Type': 'application/json'}
        response = requests.post(webhook_url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        logger.info(f"Successfully sent data to Make webhook for {log_id_info}")
        return True
    except requests.exceptions.Timeout: logger.error(f"Make webhook request timed out for {log_id_info}."); return False
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send data to Make webhook for {log_id_info}: {e}")
        if e.response is not None: logger.error(f"Webhook Response Status: {e.response.status_code}, Body: {e.response.text[:500]}")
        return False
    except Exception as e: logger.exception(f"Unexpected error sending Make webhook for {log_id_info}: {e}"); return False

def render_post_page(template_variables, slug_base):
    try:
        template = env.get_template('post_template.html')
        required_vars = ['PAGE_TITLE','META_DESCRIPTION','CANONICAL_URL','IMAGE_URL','IMAGE_ALT_TEXT','PUBLISH_ISO_FOR_META','AUTHOR_NAME','SITE_NAME','YOUR_WEBSITE_LOGO_URL','META_KEYWORDS_LIST','JSON_LD_SCRIPT_BLOCK','ARTICLE_HEADLINE','PUBLISH_DATE','ARTICLE_BODY_HTML','ARTICLE_TAGS_HTML','SOURCE_ARTICLE_URL','ARTICLE_TITLE','id','CURRENT_ARTICLE_ID','CURRENT_ARTICLE_TOPIC','CURRENT_ARTICLE_TAGS_JSON','AUDIO_URL']
        for key in required_vars: template_variables.setdefault(key, '') # Ensure keys exist

        html_content = template.render(template_variables)

        # Slug generation needs to be robust
        safe_filename = slug_base if slug_base else template_variables.get('id', 'untitled')
        safe_filename = re.sub(r'[<>:"/\\|?*%\.]+', '', safe_filename).strip().lower().replace(' ', '-') # Remove invalid chars
        safe_filename = re.sub(r'-+', '-', safe_filename).strip('-')[:80] # Collapse multiple hyphens, limit length
        if not safe_filename: safe_filename = template_variables.get('id', 'untitled_fallback') # Final fallback

        output_path = os.path.join(OUTPUT_HTML_DIR, f"{safe_filename}.html")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f: f.write(html_content)
        logger.info(f"Rendered HTML page to: {os.path.basename(output_path)}")
        return output_path
    except Exception as e: logger.exception(f"CRITICAL: Failed render HTML for {template_variables.get('id','N/A')}: {e}"); return None

def load_all_articles_data():
    articles = []
    if not os.path.exists(ALL_ARTICLES_FILE): logger.info(f"{os.path.basename(ALL_ARTICLES_FILE)} not found. Starting with empty list."); return articles
    try:
        with open(ALL_ARTICLES_FILE, 'r', encoding='utf-8') as f: all_data_json = json.load(f)
        if isinstance(all_data_json, dict) and isinstance(all_data_json.get('articles'), list):
            articles = all_data_json['articles']; logger.info(f"Loaded {len(articles)} articles from {os.path.basename(ALL_ARTICLES_FILE)}.")
        else: logger.warning(f"Format error in {os.path.basename(ALL_ARTICLES_FILE)}. Returning empty list.")
    except json.JSONDecodeError as e:
         logger.warning(f"JSON decode error loading {os.path.basename(ALL_ARTICLES_FILE)}: {e}. Returning empty list.")
    except Exception as e:
         logger.warning(f"Error loading {os.path.basename(ALL_ARTICLES_FILE)}: {e}. Returning empty list.")
    return articles

def update_all_articles_json(new_article_info):
    """Updates all_articles.json, ensuring list exists and sorting."""
    all_articles_container = {"articles": load_all_articles_data()} # Reload fresh data each time
    article_id = new_article_info.get('id')
    if not article_id: logger.error("Cannot update all_articles.json: new_article_info missing 'id'."); return

    # Create the minimal entry for the JSON file
    minimal_entry = {
        "id": article_id,
        "title": new_article_info.get('title'),
        "link": new_article_info.get('link'), # This should be the relative path like "articles/slug.html"
        "published_iso": new_article_info.get('published_iso'),
        "summary_short": new_article_info.get('summary_short'),
        "image_url": new_article_info.get('image_url'),
        "topic": new_article_info.get('topic'),
        "is_breaking": new_article_info.get('is_breaking', False),
        "tags": new_article_info.get('tags', []),
        "audio_url": None, # Or actual value if/when implemented
        "trend_score": new_article_info.get('trend_score', 0)
    }

    if not minimal_entry['link'] or not minimal_entry['title']:
        logger.error(f"Skipping update all_articles.json for ID {article_id}: missing 'link' or 'title'."); return

    # Ensure 'articles' list exists
    current_articles_list = all_articles_container.setdefault("articles", [])

    # Find if article exists and update, otherwise append
    index_to_update = next((i for i, article in enumerate(current_articles_list) if isinstance(article, dict) and article.get('id') == article_id), -1)
    if index_to_update != -1:
        current_articles_list[index_to_update].update(minimal_entry); logger.debug(f"Updating ID {article_id} in {os.path.basename(ALL_ARTICLES_FILE)}")
    else:
        current_articles_list.append(minimal_entry); logger.debug(f"Adding new ID {article_id} to {os.path.basename(ALL_ARTICLES_FILE)}")

    # Sort articles by date (newest first) after adding/updating
    current_articles_list.sort(key=get_sort_key, reverse=True)

    # Save the updated list
    try:
        with open(ALL_ARTICLES_FILE, 'w', encoding='utf-8') as f:
            json.dump(all_articles_container, f, indent=2, ensure_ascii=False)
        logger.info(f"Updated {os.path.basename(ALL_ARTICLES_FILE)} (now contains {len(current_articles_list)} articles).")
    except Exception as e: logger.error(f"Failed to save {os.path.basename(ALL_ARTICLES_FILE)}: {e}")


# --- Main Processing Function (Defined at top level) ---
def process_single_article(json_filepath, existing_articles_data, processed_in_this_run_context):
    """Processes a single scraped article file through the agent pipeline.
       Checks for title/image duplicates against existing_articles_data + processed_in_this_run.
       Requires a valid image URL and recent date to proceed.
       Returns a dict with article summary and webhook data if successful, None otherwise."""
    article_filename = os.path.basename(json_filepath)
    logger.info(f"--- Processing article file: {article_filename} ---")
    article_data = load_article_data(json_filepath)
    if not article_data or not isinstance(article_data, dict):
        logger.error(f"Failed load/invalid data {article_filename}. Skipping."); remove_scraped_file(json_filepath); return None

    article_id = article_data.get('id')
    if not article_id:
        feed_url = article_data.get('source_feed', 'unknown_feed'); article_id = get_article_id(article_data, feed_url)
        article_data['id'] = article_id; logger.warning(f"Generated missing ID {article_id} for {article_filename}")

    processed_file_path = os.path.join(PROCESSED_JSON_DIR, f"{article_id}.json")

    try:
        if os.path.exists(processed_file_path):
             logger.info(f"Article ID {article_id} already processed (JSON exists). Skipping raw file."); remove_scraped_file(json_filepath); return None

        # --- ** Date Filter ** ---
        publish_date_iso = article_data.get('published_iso')
        if publish_date_iso:
            try:
                publish_dt = get_sort_key(article_data) # Use robust parsing
                cutoff_date = datetime.now(timezone.utc) - timedelta(days=ARTICLE_MAX_AGE_DAYS)
                if publish_dt < cutoff_date:
                    logger.info(f"Article ID {article_id} is older than {ARTICLE_MAX_AGE_DAYS} days ({publish_dt.date()}). Skipping.")
                    remove_scraped_file(json_filepath)
                    return None
            except Exception as date_e: # Catch errors from get_sort_key
                 logger.warning(f"Could not verify date for article {article_id} due to parse error: {date_e}. Proceeding cautiously.")
        else:
             logger.warning(f"Article ID {article_id} missing publish date. Proceeding cautiously.")
        # --- ** End Date Filter ** ---


        # --- Image Finding Logic ---
        logger.info(f"Finding image for article ID: {article_id}...")
        selected_image_url = None # Initialize
        source_url = article_data.get('link')

        # Attempt 1: Scrape source page for meta tags
        if source_url and isinstance(source_url, str) and source_url.startswith('http'):
            try:
                selected_image_url = scrape_source_for_image(source_url)
                if selected_image_url:
                    logger.info(f"Found image via source scrape for {article_id}.")
                else:
                    logger.info(f"Source scrape did not find image for {article_id}.")
            except Exception as scrape_e:
                logger.error(f"Error scraping image from source {source_url}: {scrape_e}")

        # Attempt 2: Use SerpApi if source scrape failed
        if not selected_image_url:
            logger.info(f"Source scrape failed or yielded no image, using API search for {article_id}...")
            image_query = article_data.get('title', 'AI Technology News') # Use title as query
            try:
                selected_image_url = find_best_image(image_query) # find_best_image handles SerpApi call
                if selected_image_url:
                    logger.info(f"Found image via API search for {article_id}.")
                else:
                    logger.warning(f"API search did not find image for {article_id}.")
            except Exception as find_img_e:
                logger.error(f"Error during find_best_image API call for {article_id}: {find_img_e}")
                selected_image_url = None # Ensure it's None on error

        # --- *** Image Check: Skip article if no image found *** ---
        if not selected_image_url:
            logger.error(f"FATAL: Could not find any image URL (scrape or API) for article ID: {article_id}. Skipping article processing.")
            remove_scraped_file(json_filepath)
            return None
        # --- *** End of Image Check *** ---

        article_data['selected_image_url'] = selected_image_url
        logger.debug(f"Using image URL: {selected_image_url} for article {article_id}")

        # --- Duplicate Check (Title + Image URL) ---
        current_title_lower = article_data.get('title', '').strip().lower()
        if not current_title_lower:
            logger.error(f"Article ID {article_id} has empty title. Skipping processing."); remove_scraped_file(json_filepath); return None
        else:
            full_context_for_dup_check = existing_articles_data + processed_in_this_run_context
            for existing_article in full_context_for_dup_check:
                # Compare lowercase titles and the selected image URL
                if (isinstance(existing_article, dict) and
                    existing_article.get('title','').strip().lower() == current_title_lower and
                    existing_article.get('image_url') == selected_image_url): # Check against selected image
                    logger.warning(f"Article ID {article_id} is DUPLICATE (Title & Image) of {existing_article.get('id', 'N/A')}. Skipping.")
                    remove_scraped_file(json_filepath); return None
            logger.info(f"Article ID {article_id} passed Title+Image duplicate check.")

        # --- Start Agent Pipeline (Filter, SEO, Tags) ---
        logger.debug(f"Running filter agent for article ID: {article_id}...")
        article_data = run_filter_agent(article_data)
        if not article_data or article_data.get('filter_verdict') is None:
             filter_error_msg = article_data.get('filter_error', 'Filter fail') if isinstance(article_data, dict) else 'Filter non-dict'
             logger.error(f"Filter Agent failed {article_id}: {filter_error_msg}. Skip."); remove_scraped_file(json_filepath); return None
        filter_verdict = article_data['filter_verdict']; importance_level = filter_verdict.get('importance_level')
        if importance_level == "Boring":
            logger.info(f"Article ID {article_id} classified as 'Boring'. Skipping."); remove_scraped_file(json_filepath); return None
        assigned_topic = filter_verdict.get('topic', 'Other'); article_data['topic'] = assigned_topic
        article_data['is_breaking'] = (importance_level == "Breaking")
        primary_keyword = filter_verdict.get('primary_topic_keyword', article_data.get('title','')); article_data['primary_keyword'] = primary_keyword
        logger.info(f"Article ID {article_id} classified {importance_level} (Topic: {assigned_topic}).")

        logger.debug(f"Running SEO agent for article ID: {article_id}...")
        article_data = run_seo_article_agent(article_data)
        seo_results = article_data.get('seo_agent_results')
        if not seo_results or not seo_results.get('generated_article_body_md'):
            seo_error_msg = article_data.get('seo_agent_error', 'SEO fail'); logger.error(f"SEO Agent failed {article_id}: {seo_error_msg}. Skip."); remove_scraped_file(json_filepath); return None
        elif article_data.get('seo_agent_error'):
            logger.warning(f"SEO Agent completed with non-critical errors for {article_id}: {article_data['seo_agent_error']}")

        logger.debug(f"Running Tags agent for article ID: {article_id}...")
        article_data = run_tags_generator_agent(article_data)
        if article_data.get('tags_agent_error'):
            logger.warning(f"Tags Agent failed/skipped for {article_id}: {article_data['tags_agent_error']}")
        article_data['generated_tags'] = article_data.get('generated_tags', []) if isinstance(article_data.get('generated_tags'), list) else []

        # --- Trend Score Calculation ---
        trend_score = 0.0; tags_count = len(article_data['generated_tags']); publish_date_iso = article_data.get('published_iso')
        try:
            if importance_level == "Interesting": trend_score += 5.0
            elif importance_level == "Breaking": trend_score += 10.0
            trend_score += float(tags_count) * 0.5
            if publish_date_iso:
                publish_dt = get_sort_key(article_data); now_utc = datetime.now(timezone.utc)
                if publish_dt <= now_utc: # Check if date is not in the future
                    days_old = (now_utc - publish_dt).total_seconds() / 86400.0
                    # Only apply recency score if not older than max age (already checked, but safe)
                    if days_old <= ARTICLE_MAX_AGE_DAYS:
                        recency_factor = max(0.0, 1.0 - (days_old / float(ARTICLE_MAX_AGE_DAYS))) # Scale recency over max age
                        trend_score += recency_factor * 5.0
                else:
                     logger.warning(f"Article ID {article_id} has future publish date: {publish_date_iso}.")
        except Exception as e:
             logger.warning(f"Error calculating trend score for {article_id}: {e}")
        article_data['trend_score'] = round(max(0.0, trend_score), 2); logger.debug(f"Trend score {article_id}: {article_data['trend_score']}")

        # --- Slug and URL Generation ---
        original_title = article_data.get('title', f'article-{article_id}'); slug = original_title.lower()
        slug = re.sub(r'[<>:"/\\|?*%\.]+', '', slug).strip().lower().replace(' ', '-')
        slug = re.sub(r'-+', '-', slug).strip('-')[:80]
        if not slug: slug = f'article-{article_id}'
        article_data['slug'] = slug # Save the generated slug

        article_relative_path = f"articles/{slug}.html"
        # Ensure YOUR_SITE_BASE_URL ends with /
        canonical_url = urljoin(YOUR_SITE_BASE_URL.rstrip('/') + '/', article_relative_path.lstrip('/')) if YOUR_SITE_BASE_URL else f"/{article_relative_path.lstrip('/')}"
        logger.debug(f"Calculated canonical_url: '{canonical_url}'")

        # --- HTML Rendering Preparation ---
        body_md = seo_results.get('generated_article_body_md', ''); body_html = f"<p><i>Content generation error.</i></p><pre>{body_md}</pre>"
        try: body_html = markdown.markdown(body_md, extensions=['fenced_code', 'tables', 'nl2br'])
        except Exception as md_err: logger.error(f"Markdown rendering failed for {article_id}: {md_err}")
        tags_list = article_data.get('generated_tags', []); tags_html = format_tags_html(tags_list)
        publish_date_iso_for_meta = article_data.get('published_iso', datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
        publish_date_formatted = "Date Unknown"
        try: publish_dt = get_sort_key(article_data); publish_date_formatted = publish_dt.strftime('%B %d, %Y')
        except Exception: logger.warning(f"Publish date formatting error for {article_id}")
        page_title = seo_results.get('generated_title_tag', article_data.get('title', 'AI News'))
        meta_description = seo_results.get('generated_meta_description', article_data.get('summary', '')[:160])
        template_vars = {
            'PAGE_TITLE': page_title, 'META_DESCRIPTION': meta_description, 'AUTHOR_NAME': article_data.get('author', AUTHOR_NAME_DEFAULT),
            'META_KEYWORDS': ", ".join(tags_list), 'CANONICAL_URL': canonical_url, 'SITE_NAME': YOUR_WEBSITE_NAME, 'YOUR_WEBSITE_LOGO_URL': YOUR_WEBSITE_LOGO_URL,
            'IMAGE_URL': article_data.get('selected_image_url', ''), 'IMAGE_ALT_TEXT': page_title, 'META_KEYWORDS_LIST': tags_list,
            'PUBLISH_ISO_FOR_META': publish_date_iso_for_meta, 'JSON_LD_SCRIPT_BLOCK': seo_results.get('generated_json_ld', ''),
            'ARTICLE_HEADLINE': article_data.get('title', 'Article'), 'PUBLISH_DATE': publish_date_formatted, 'ARTICLE_BODY_HTML': body_html,
            'ARTICLE_TAGS_HTML': tags_html, 'SOURCE_ARTICLE_URL': article_data.get('link', '#'), 'ARTICLE_TITLE': article_data.get('title'),
            'id': article_id, 'CURRENT_ARTICLE_ID': article_id, 'CURRENT_ARTICLE_TOPIC': article_data.get('topic', ''),
            'CURRENT_ARTICLE_TAGS_JSON': json.dumps(tags_list), 'AUDIO_URL': None
        }

        # --- Render HTML ---
        generated_html_path = render_post_page(template_vars, slug)
        if not generated_html_path:
            logger.error(f"Failed to render HTML page for {article_id}. Skipping article completion."); return None # Don't save JSON or update lists if HTML fails

        # --- Update Site Data JSON ---
        site_data_entry = {
            "id": article_id, "title": article_data.get('title'), "link": article_relative_path,
            "published_iso": publish_date_iso_for_meta, "summary_short": meta_description,
            "image_url": article_data.get('selected_image_url'), "topic": article_data.get('topic', 'News'),
            "is_breaking": article_data.get('is_breaking', False), "tags": tags_list,
            "audio_url": None, # Or actual value if/when implemented
            "trend_score": article_data.get('trend_score', 0)
        }
        article_data['audio_url'] = None # Ensure it's set in the full processed data too
        update_all_articles_json(site_data_entry)

        # --- Twitter Posting Logic ---
        logger.info(f"Checking Twitter daily limit for article ID: {article_id}...")
        try:
            today_date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            tracker_date, count_today = _read_tweet_tracker()
            if tracker_date != today_date_str:
                logger.info(f"New day ({today_date_str}). Resetting Twitter count."); count_today = 0; _write_tweet_tracker(today_date_str, count_today)

            if count_today < DAILY_TWEET_LIMIT:
                logger.info(f"Twitter limit check passed ({count_today}/{DAILY_TWEET_LIMIT}). Preparing tweet for {article_id}...")
                tweet_link_to_post = canonical_url # Use the canonical URL of the generated page
                tweet_title_to_post = article_data.get('title', 'New AI/Tech Article')
                tweet_image_url_to_post = article_data.get('selected_image_url')

                if tweet_title_to_post and tweet_link_to_post and tweet_image_url_to_post:
                    if not tweet_link_to_post.startswith('http'):
                        logger.error(f"Tweet link '{tweet_link_to_post}' is not an absolute URL! Skipping tweet.")
                    else:
                        tweet_success = post_tweet_with_image(tweet_title_to_post, tweet_link_to_post, tweet_image_url_to_post)
                        if tweet_success:
                            logger.info(f"Tweet successful for {article_id}. Incrementing count.")
                            count_today += 1; _write_tweet_tracker(today_date_str, count_today)
                        else:
                            logger.error(f"Tweet post failed for {article_id}.")
                else:
                    logger.error(f"Missing title, link, or image URL for tweet {article_id}. Skipping tweet.")
            else:
                logger.info(f"Daily Twitter limit ({DAILY_TWEET_LIMIT}) reached. Skipping tweet for {article_id}.")
        except Exception as tweet_err:
             logger.exception(f"Error during Twitter posting logic for {article_id}: {tweet_err}")

        # --- Prepare Webhook Data ---
        webhook_data_for_batch = {
            "id": article_id,
            "title": article_data.get('title', 'New Article'),
            "article_url": canonical_url, # Use canonical URL for webhook too
            "image_url": article_data.get('selected_image_url'),
            "topic": article_data.get('topic'),
            "tags": tags_list,
            "summary_short": site_data_entry.get('summary_short', '')
        }

        # --- Final Save & Cleanup ---
        if save_processed_data(processed_file_path, article_data):
             remove_scraped_file(json_filepath)
             logger.info(f"--- Successfully processed article: {article_id} ---")
             # Return summary for dup check AND webhook data
             return {
                 "summary": {"id": article_id, "title": article_data.get("title"), "image_url": article_data.get("selected_image_url")},
                 "webhook_data": webhook_data_for_batch
             }
        else:
             logger.error(f"Failed to save final processed JSON for {article_id}. Original scraped file NOT removed.")
             return None # Indicate failure if final save fails

    except Exception as process_e:
         logger.exception(f"CRITICAL failure processing {article_id} (file: {article_filename}): {process_e}")
         # Attempt cleanup even on unexpected failure
         if os.path.exists(json_filepath):
             logger.warning(f"Attempting to remove potentially problematic raw file: {article_filename}")
             remove_scraped_file(json_filepath)
         return None


# --- Main Orchestration Logic ---
if __name__ == "__main__":
    run_start_time = time.time()
    logger.info(f"--- === Dacoola AI News Orchestrator Starting Run ({datetime.now(timezone.utc).isoformat()}) === ---")
    ensure_directories()

    glob_pattern = os.path.join(PROCESSED_JSON_DIR, '*.json')
    completed_article_ids = set(os.path.basename(f).replace('.json', '') for f in glob.glob(glob_pattern))
    logger.info(f"Found {len(completed_article_ids)} already fully processed articles.")

    scraper_processed_ids_on_disk = load_processed_ids()
    initial_processed_ids_for_scraper = scraper_processed_ids_on_disk.union(completed_article_ids)
    logger.info(f"Total initial processed IDs passed to scraper: {len(initial_processed_ids_for_scraper)}")

    logger.info("--- Stage 1: Running News Scraper ---")
    new_articles_found_count = 0
    try: new_articles_found_count = scrape_news(NEWS_FEED_URLS, initial_processed_ids_for_scraper)
    except Exception as scrape_e: logger.exception(f"Scraper error: {scrape_e}"); logger.error("Proceeding despite scraper error.")
    logger.info(f"Scraper run completed. Saved {new_articles_found_count} new raw files.")

    logger.info("--- Stage 2: Running Processing Cycle ---")
    existing_articles_data = load_all_articles_data() # Load historical data for dup checks
    logger.info(f"Loaded {len(existing_articles_data)} articles from {os.path.basename(ALL_ARTICLES_FILE)} for context.")

    json_files_to_process = []
    try: json_files_to_process = glob.glob(os.path.join(SCRAPED_ARTICLES_DIR, '*.json'))
    except Exception as glob_e: logger.exception(f"Error listing raw files: {glob_e}")

    successful_articles_for_webhook = []
    processed_in_this_run_context = [] # Keep this for in-run duplicate checks

    if not json_files_to_process:
        logger.info("No new scraped articles to process.")
    else:
        logger.info(f"Found {len(json_files_to_process)} scraped articles to process.")
        processed_successfully_count = 0
        failed_or_skipped_count = 0

        # --- Sort by modification time, NEWEST FIRST ---
        try:
            json_files_to_process.sort(key=os.path.getmtime, reverse=True)
            logger.info("Sorted scraped files by modification time (newest first).")
        except Exception as sort_e:
            logger.warning(f"Could not sort scraped files by modification time: {sort_e}. Processing in glob order.")

        for filepath in json_files_to_process:
            potential_id = os.path.basename(filepath).replace('.json', '')
            if potential_id in completed_article_ids:
                 logger.debug(f"Skipping raw {potential_id}, processed JSON exists."); remove_scraped_file(filepath); failed_or_skipped_count += 1; continue

            # Pass historical + current run context for duplicate checks
            processing_result = process_single_article(filepath, existing_articles_data, processed_in_this_run_context)

            if processing_result and isinstance(processing_result, dict): # If successful returns dict
                processed_successfully_count += 1
                # Add summary to context for next iteration's duplicate check
                if "summary" in processing_result and isinstance(processing_result["summary"], dict):
                    processed_in_this_run_context.append(processing_result["summary"])
                    new_id = processing_result["summary"].get('id')
                    if new_id:
                        completed_article_ids.add(new_id) # Track as completed
                        # Update historical list IN MEMORY for next iteration's duplicate check
                        existing_articles_data.append(processing_result["summary"])
                    else:
                        logger.error("Processing result summary missing 'id'. Cannot update context lists accurately.")

                # Add webhook data to the batch list
                if "webhook_data" in processing_result and isinstance(processing_result["webhook_data"], dict):
                    successful_articles_for_webhook.append(processing_result["webhook_data"])
            else:
                 failed_or_skipped_count += 1
            # Optional small delay between processing articles if hitting API rate limits
            # time.sleep(0.5)

        logger.info(f"Processing cycle complete. Success: {processed_successfully_count}, Failed/Skipped/Duplicate: {failed_or_skipped_count}")

    # --- Send Batched Webhook ---
    if successful_articles_for_webhook:
        logger.info(f"--- Stage 2.5: Sending Batched Make.com Webhook ({len(successful_articles_for_webhook)} articles) ---")
        if MAKE_WEBHOOK_URL:
            if send_make_webhook(MAKE_WEBHOOK_URL, successful_articles_for_webhook):
                logger.info("Batched Make.com webhook sent successfully.")
            else:
                logger.error("Batched Make.com webhook failed.")
        else:
            logger.warning("MAKE_INSTAGRAM_WEBHOOK_URL not set. Skipping batched webhook send.")
    else:
        logger.info("No successful articles processed in this run to send to Make.com webhook.")

    logger.info("--- Stage 3: Generating Sitemap ---")
    if not YOUR_SITE_BASE_URL:
        logger.error("Sitemap generation SKIPPED: YOUR_SITE_BASE_URL is not set in the environment.")
    else:
        try:
            run_sitemap_generator()
            logger.info("Sitemap generation completed successfully.")
        except Exception as sitemap_e:
            logger.exception(f"Sitemap generation failed: {sitemap_e}")

    run_end_time = time.time()
    logger.info(f"--- === Dacoola AI News Orchestrator Run Finished ({run_end_time - run_start_time:.2f} seconds) === ---")