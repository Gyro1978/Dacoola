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
from jinja2 import Environment, FileSystemLoader
import markdown
import re # Needed for slug generation
import requests # Needed for requests.utils.quote and webhook
from dotenv import load_dotenv
from datetime import datetime, timezone
from urllib.parse import urljoin # To create absolute URLs

# --- Import Agent and Scraper Functions ---
try:
    # ** IMPORT SCRAPER **
    from src.scrapers.news_scraper import scrape_news, load_processed_ids, NEWS_FEED_URLS
    from src.scrapers.image_scraper import find_best_image, scrape_source_for_image
    # ** IMPORT AGENTS **
    from src.agents.filter_news_agent import run_filter_agent
    from src.agents.similarity_check_agent import run_similarity_check_agent
    from src.agents.seo_article_generator_agent import run_seo_article_agent
    from src.agents.tags_generator_agent import run_tags_generator_agent
    # ** IMPORT SOCIAL POSTER **
    from src.social.twitter_poster import post_tweet_with_image

except ImportError as e:
     # Use basic print for critical startup errors before logging might be configured
     print(f"FATAL IMPORT ERROR in main.py: {e}")
     print("Check file names, function definitions, and __init__.py files in src/ and subfolders.")
     # Attempt to log just in case logger is partially working
     try: logging.critical(f"FATAL IMPORT ERROR: {e}")
     except: pass
     sys.exit(1)


# --- Load Environment Variables ---
# Use the project root determined by path setup
dotenv_path = os.path.join(PROJECT_ROOT_FOR_PATH, '.env')
load_dotenv(dotenv_path=dotenv_path)

MAX_HOME_PAGE_ARTICLES = int(os.getenv('MAX_HOME_PAGE_ARTICLES', 20))
AUTHOR_NAME_DEFAULT = os.getenv('AUTHOR_NAME', 'AI News Team')
YOUR_WEBSITE_NAME = os.getenv('YOUR_WEBSITE_NAME', 'Dacoola')
YOUR_WEBSITE_LOGO_URL = os.getenv('YOUR_WEBSITE_LOGO_URL', '')
# Ensure base URL ends with a slash if it exists, otherwise empty string
raw_base_url = os.getenv('YOUR_SITE_BASE_URL', '')
YOUR_SITE_BASE_URL = (raw_base_url.rstrip('/') + '/') if raw_base_url else ''
# Load Make.com Webhook URL
MAKE_WEBHOOK_URL = os.getenv('MAKE_INSTAGRAM_WEBHOOK_URL', None)


# --- Setup Logging ---
# Use project root determined by path setup
log_file_path = os.path.join(PROJECT_ROOT_FOR_PATH, 'dacoola.log')
try:
    # Ensure the directory for the log file exists
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    log_handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file_path, encoding='utf-8')
    ]
except OSError as e:
    # Fallback to console only if file handler fails
    print(f"Log setup warning: Could not create log directory/file at {log_file_path}. Error: {e}. Logging to console only.")
    log_handlers = [logging.StreamHandler(sys.stdout)]

logging.basicConfig(
    level=logging.INFO, # INFO for prod, DEBUG for testing/development
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S', # Consistent date format
    handlers=log_handlers,
    force=True # Allow reconfiguring if already set by imports
)
logger = logging.getLogger('main_orchestrator') # Specific logger for this file

# --- Log env var warnings AFTER logger is set up ---
if not YOUR_SITE_BASE_URL:
    logger.warning("YOUR_SITE_BASE_URL environment variable not set or empty. Canonical and Open Graph URLs will be relative or potentially incorrect.")
else:
    logger.info(f"Using site base URL: {YOUR_SITE_BASE_URL}")

if not YOUR_WEBSITE_LOGO_URL:
     logger.warning("YOUR_WEBSITE_LOGO_URL environment variable not set. Schema markup and potentially branding might be affected.")

if not MAKE_WEBHOOK_URL:
     logger.warning("MAKE_INSTAGRAM_WEBHOOK_URL environment variable not set. Cannot send data to Make.com.")


# --- Configuration ---
DATA_DIR = os.path.join(PROJECT_ROOT_FOR_PATH, 'data')
SCRAPED_ARTICLES_DIR = os.path.join(DATA_DIR, 'scraped_articles')
PROCESSED_JSON_DIR = os.path.join(DATA_DIR, 'processed_json')
PUBLIC_DIR = os.path.join(PROJECT_ROOT_FOR_PATH, 'public')
OUTPUT_HTML_DIR = os.path.join(PUBLIC_DIR, 'articles')
TEMPLATE_DIR = os.path.join(PROJECT_ROOT_FOR_PATH, 'templates')
SITE_DATA_FILE = os.path.join(PUBLIC_DIR, 'site_data.json')
ALL_ARTICLES_FILE = os.path.join(PUBLIC_DIR, 'all_articles.json')


# --- Jinja2 Setup ---
try:
    # Add escapejs filter for JSON-LD safety
    def escapejs_filter(value):
        if value is None: return ''
        value = str(value)
        # Basic escaping sufficient for JSON string values
        value = value.replace('\\', '\\\\').replace('"', '\\"').replace('/', '\\/')
        # Escape characters that could break script tags or HTML parsing within JS
        value = value.replace('<', '\\u003c').replace('>', '\\u003e')
        # Control characters and line breaks
        value = value.replace('\b', '\\b').replace('\f', '\\f').replace('\n', '\\n')
        value = value.replace('\r', '\\r').replace('\t', '\\t')
        return value

    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    env.filters['escapejs'] = escapejs_filter # Add custom filter
    logger.info(f"Jinja2 environment loaded from {TEMPLATE_DIR}")
except Exception as e:
    logger.exception(f"CRITICAL: Failed to initialize Jinja2 from {TEMPLATE_DIR}. Exiting.")
    sys.exit(1)

# --- Helper Functions ---
def ensure_directories():
    """Creates necessary directories if they don't exist."""
    dirs_to_create = [
        DATA_DIR,
        SCRAPED_ARTICLES_DIR,
        PROCESSED_JSON_DIR,
        PUBLIC_DIR, # Ensure public exists too
        OUTPUT_HTML_DIR,
        TEMPLATE_DIR # Check template dir exists, though Jinja loading might fail first
    ]
    try:
        for dir_path in dirs_to_create:
             os.makedirs(dir_path, exist_ok=True)
        logger.info("Ensured core directories exist.")
    except OSError as e:
        logger.exception(f"CRITICAL: Could not create necessary directory {e.filename}: {e.strerror}")
        sys.exit(1)


def load_article_data(filepath):
    """Loads JSON data from a file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f: return json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"JSON Decode Error loading {filepath}: {e}")
        return None
    except FileNotFoundError:
         logger.error(f"File not found when loading: {filepath}")
         return None
    except Exception as e:
         logger.error(f"Unexpected Error loading {filepath}: {e}")
         return None


def save_processed_data(filepath, article_data):
    """Saves processed article data to a JSON file."""
    try:
         # Ensure parent directory exists (redundant if ensure_directories ran, but safe)
         os.makedirs(os.path.dirname(filepath), exist_ok=True)
         with open(filepath, 'w', encoding='utf-8') as f:
              json.dump(article_data, f, indent=4, ensure_ascii=False)
         logger.info(f"Saved final processed data to: {os.path.basename(filepath)}")
         return True
    except TypeError as e:
         logger.error(f"TypeError saving data (might be non-serializable?): {e} for file {os.path.basename(filepath)}")
         return False
    except Exception as e:
         logger.error(f"Failed to save final processed data to {os.path.basename(filepath)}: {e}")
         return False


def remove_scraped_file(filepath):
    """Removes the original scraped JSON file after successful processing or skipping."""
    try:
         if os.path.exists(filepath):
              os.remove(filepath)
              logger.debug(f"Removed original scraped file: {os.path.basename(filepath)}")
         else:
              logger.warning(f"Scraped file to remove not found: {filepath}")
    except OSError as e:
         logger.error(f"Failed to remove original scraped file {filepath}: {e}")


def format_tags_html(tags_list):
    """Formats a list of tags into linked HTML spans."""
    if not tags_list or not isinstance(tags_list, list): return ""
    try:
        # Use absolute path from site root for topic links
        tag_links = []
        for tag in tags_list:
            safe_tag = requests.utils.quote(str(tag))
            tag_links.append(f'<span class="tag-item"><a href="/topic.html?name={safe_tag}">{tag}</a></span>')
        return " ".join(tag_links)
    except Exception as e:
        logger.error(f"Error formatting tags: {tags_list} - {e}")
        return ""


def get_sort_key(article_dict):
    """Helper function to extract a timezone-aware datetime object for sorting articles."""
    fallback_date = datetime(1970, 1, 1, tzinfo=timezone.utc)
    date_str = article_dict.get('published_iso')
    if not date_str or not isinstance(date_str, str):
        return fallback_date

    try:
        if date_str.endswith('Z'):
            date_str = date_str[:-1] + '+00:00'
        dt = datetime.fromisoformat(date_str)
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError) as e:
        logger.warning(f"Could not parse date '{date_str}' for sorting (ID: {article_dict.get('id', 'N/A')}). Error: {e}. Using fallback.")
        return fallback_date

# --- NEW WEBHOOK FUNCTION ---
def send_make_webhook(webhook_url, data):
    """Sends data to a Make.com webhook."""
    if not webhook_url:
        logger.warning("Make.com webhook URL not set. Skipping webhook send.")
        return False
    if not data:
        logger.warning("No data provided for Make.com webhook. Skipping.")
        return False

    try:
        headers = {'Content-Type': 'application/json'}
        # Send data as JSON payload
        response = requests.post(webhook_url, headers=headers, json=data, timeout=15)
        response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)
        logger.info(f"Successfully sent data to Make.com webhook for article ID: {data.get('id', 'N/A')}")
        return True
    except requests.exceptions.Timeout:
        logger.error("Request to Make.com webhook timed out.")
        return False
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send data to Make.com webhook: {e}")
        if e.response is not None:
             logger.error(f"Webhook Response Status: {e.response.status_code}")
             logger.error(f"Webhook Response Body: {e.response.text[:500]}") # Log first 500 chars
        return False
    except Exception as e:
         logger.exception(f"Unexpected error sending Make.com webhook: {e}")
         return False
# --- END NEW WEBHOOK FUNCTION ---

def render_post_page(template_variables, slug_base):
    """Renders a single article HTML page using the template."""
    try:
        template = env.get_template('post_template.html')
        # Ensure all expected variables are at least present, even if None/empty
        required_vars = ['PAGE_TITLE', 'META_DESCRIPTION', 'CANONICAL_URL', 'IMAGE_URL',
                         'IMAGE_ALT_TEXT', 'PUBLISH_ISO_FOR_META', 'AUTHOR_NAME',
                         'SITE_NAME', 'YOUR_WEBSITE_LOGO_URL', 'META_KEYWORDS_LIST',
                         'ARTICLE_HEADLINE', 'PUBLISH_DATE', 'ARTICLE_BODY_HTML',
                         'ARTICLE_TAGS_HTML', 'SOURCE_ARTICLE_URL', 'ARTICLE_TITLE',
                         'CURRENT_ARTICLE_ID', 'CURRENT_ARTICLE_TOPIC', 'CURRENT_ARTICLE_TAGS_JSON',
                         'AUDIO_URL'] # Keep AUDIO_URL key for template structure
        for key in required_vars:
             template_variables.setdefault(key, '') # Set default empty string if missing

        html_content = template.render(template_variables)

        # Generate safe filename from slug_base
        safe_filename = slug_base if slug_base else template_variables.get('id', 'untitled')
        safe_filename = re.sub(r'[<>:"/\\|?*%\.]+', '', safe_filename) # Added %
        safe_filename = safe_filename.strip().lower()
        safe_filename = safe_filename.replace(' ', '-')
        safe_filename = re.sub('-+', '-', safe_filename)
        safe_filename = safe_filename.strip('-')[:80]
        if not safe_filename:
             safe_filename = template_variables.get('id', 'untitled_fallback')

        output_path = os.path.join(OUTPUT_HTML_DIR, f"{safe_filename}.html")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
             f.write(html_content)
        logger.info(f"Rendered HTML: {os.path.basename(output_path)}")
        return output_path
    except Exception as e:
        logger.exception(f"CRITICAL Error rendering template for ID {template_variables.get('id','N/A')}: {e}")
        return None


# --- Site Data Management ---
def load_recent_articles_for_comparison(max_articles=50):
    """Loads recent article titles/summaries for similarity checking from all_articles.json."""
    articles_for_comparison = []
    source_file = ALL_ARTICLES_FILE
    if not os.path.exists(source_file):
        logger.info(f"Source file {os.path.basename(source_file)} not found for loading recent articles.")
        return []

    try:
        with open(source_file, 'r', encoding='utf-8') as f:
            site_data = json.load(f)
            if isinstance(site_data.get('articles'), list):
                sorted_articles = sorted(site_data["articles"], key=get_sort_key, reverse=True)
                for a in sorted_articles[:max_articles]:
                     if isinstance(a, dict) and a.get("title") and a.get("id"):
                         summary = a.get("summary_short", a.get("summary", ""))[:300]
                         articles_for_comparison.append({
                             "id": a.get("id"),
                             "title": a.get("title"),
                             "summary_short": summary
                         })
                     else:
                          logger.warning(f"Skipping invalid/incomplete recent article entry for comparison: {a.get('id', 'N/A')}")
                logger.info(f"Loaded {len(articles_for_comparison)} recent articles from {os.path.basename(source_file)} for comparison context.")
            else:
                 logger.warning(f"'articles' key missing or not a list in {os.path.basename(source_file)}.")

    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error loading {os.path.basename(source_file)} for comparison: {e}")
    except Exception as e:
        logger.warning(f"Could not load/process recent articles from {os.path.basename(source_file)} for comparison: {e}")

    return articles_for_comparison


def update_site_data(new_article_info):
    """Updates site_data.json (homepage) and all_articles.json (archive)."""
    site_data = {"articles": []}
    all_articles_data = {"articles": []}
    article_id = new_article_info.get('id')

    if not article_id:
        logger.error("Cannot update site data: new_article_info missing 'id'.")
        return

    # --- Load existing data safely ---
    for filepath, data_dict in [(SITE_DATA_FILE, site_data), (ALL_ARTICLES_FILE, all_articles_data)]:
        try:
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    loaded_data = json.load(f)
                    if isinstance(loaded_data.get('articles'), list):
                        data_dict['articles'] = loaded_data['articles']
                    else:
                         logger.warning(f"Loaded data from {os.path.basename(filepath)} is missing 'articles' list. Starting fresh.")
        except json.JSONDecodeError as e:
            logger.warning(f"Could not decode JSON from {os.path.basename(filepath)}: {e}. Starting fresh.")
        except Exception as e:
            logger.warning(f"Could not load {os.path.basename(filepath)}: {e}. Starting fresh.")

    # --- Prepare the minimal entry for JSON files ---
    minimal_entry = {
        "id": article_id,
        "title": new_article_info.get('title'),
        "link": new_article_info.get('link'), # Relative path 'articles/slug.html'
        "published_iso": new_article_info.get('published_iso'),
        "summary_short": new_article_info.get('summary_short'),
        "image_url": new_article_info.get('image_url'),
        "topic": new_article_info.get('topic'),
        "is_breaking": new_article_info.get('is_breaking', False),
        "tags": new_article_info.get('tags', []),
        "audio_url": None,
        "trend_score": new_article_info.get('trend_score', 0)
    }
    if not minimal_entry['link'] or not minimal_entry['title']:
         logger.error(f"Cannot add entry for {article_id}: missing critical link or title.")
         return

    # --- Update/Add Logic for BOTH files ---
    for data_dict, filename in [(site_data, SITE_DATA_FILE), (all_articles_data, ALL_ARTICLES_FILE)]:
        current_articles = data_dict.setdefault("articles", [])
        index_to_update = next((i for i, article in enumerate(current_articles) if isinstance(article, dict) and article.get('id') == article_id), -1)

        if index_to_update != -1:
            current_articles[index_to_update].update(minimal_entry)
            logger.debug(f"Updating {article_id} in {os.path.basename(filename)}")
        else:
            current_articles.append(minimal_entry)
            logger.debug(f"Adding {article_id} to {os.path.basename(filename)}")

    # --- Sort and Limit (Homepage only) ---
    site_data["articles"].sort(key=get_sort_key, reverse=True)
    all_articles_data["articles"].sort(key=get_sort_key, reverse=True)
    site_data["articles"] = site_data["articles"][:MAX_HOME_PAGE_ARTICLES]

    # --- Save BOTH files ---
    for filepath, data_dict in [(filepath, site_data), (ALL_ARTICLES_FILE, all_articles_data)]:
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data_dict, f, indent=2, ensure_ascii=False)
            logger.info(f"Updated {os.path.basename(filepath)} ({len(data_dict['articles'])} articles).")
        except Exception as e:
            logger.error(f"Failed to save {os.path.basename(filepath)}: {e}")


# --- Main Processing Pipeline ---
def process_single_article(json_filepath, recent_articles_context):
    """Processes a single scraped article JSON file through the agent pipeline."""
    article_filename = os.path.basename(json_filepath)
    logger.info(f"--- Processing article file: {article_filename} ---")
    article_data = load_article_data(json_filepath)
    if not article_data or not isinstance(article_data, dict):
        logger.error(f"Failed to load or invalid data in {article_filename}. Skipping.")
        remove_scraped_file(json_filepath) # Remove bad file
        return False

    article_id = article_data.get('id')
    if not article_id:
        feed_url = article_data.get('source_feed', 'unknown_feed')
        from src.scrapers.news_scraper import get_article_id # Local import for safety
        article_id = get_article_id(article_data, feed_url)
        article_data['id'] = article_id
        logger.warning(f"Article data missing 'id' in {article_filename}, generated: {article_id}")

    processed_file_path = os.path.join(PROCESSED_JSON_DIR, f"{article_id}.json")

    try:
        # 1. Check if already fully processed
        if os.path.exists(processed_file_path):
             logger.info(f"Article {article_id} already processed (processed JSON exists). Skipping.")
             remove_scraped_file(json_filepath)
             return False

        # --- Start Agent Pipeline ---
        # 2. Filter Agent
        logger.debug(f"Running filter agent for {article_id}...")
        article_data = run_filter_agent(article_data)
        if not article_data or article_data.get('filter_verdict') is None:
             filter_error = article_data.get('filter_error', 'Filter agent critical failure') if isinstance(article_data, dict) else 'Filter agent returned non-dict'
             logger.error(f"Filter Agent failed for {article_id}. Error: {filter_error}. Skipping.")
             remove_scraped_file(json_filepath)
             return False

        filter_verdict = article_data['filter_verdict']
        importance_level = filter_verdict.get('importance_level')
        if importance_level == "Boring":
            logger.info(f"Article {article_id} classified as Boring by Filter Agent. Skipping.")
            remove_scraped_file(json_filepath)
            return False

        assigned_topic = filter_verdict.get('topic', 'Other')
        article_data['topic'] = assigned_topic
        article_data['is_breaking'] = (importance_level == "Breaking")
        primary_keyword = filter_verdict.get('primary_topic_keyword', article_data.get('title',''))
        article_data['primary_keyword'] = primary_keyword
        logger.info(f"Article {article_id} classified as {importance_level} (Topic: {assigned_topic}).")

        # 3. Similarity Check
        logger.info(f"Checking duplicates for {article_id}...")
        similarity_result = run_similarity_check_agent(article_data, recent_articles_context)
        if similarity_result and similarity_result.get('is_semantic_duplicate'):
            logger.info(f"Article {article_id} is SEMANTIC DUPLICATE. Skipping. Reason: {similarity_result.get('reasoning')}")
            remove_scraped_file(json_filepath)
            return False
        elif similarity_result is None:
             logger.warning(f"Similarity check failed for {article_id}. Proceeding cautiously.")
             article_data['similarity_check_error'] = "Agent failed"
        else:
             logger.info(f"Article {article_id} passed similarity check.")
             article_data['similarity_check_error'] = None

        # 4. Image Finding
        logger.info(f"Finding image for {article_id}...")
        scraped_image_url = None
        source_url = article_data.get('link')
        if source_url and isinstance(source_url, str) and source_url.startswith('http'):
             try: scraped_image_url = scrape_source_for_image(source_url)
             except Exception as scrape_e: logger.error(f"Error scraping source image ({source_url}): {scrape_e}")

        if scraped_image_url:
            article_data['selected_image_url'] = scraped_image_url
            logger.info(f"Using scraped image for {article_id}: {scraped_image_url}")
        else:
             logger.info(f"Image scraping failed/no image, using API search for {article_id}...")
             image_query = primary_keyword if primary_keyword else article_data.get('title', 'AI News')
             api_image_url = find_best_image(image_query)
             if api_image_url:
                  article_data['selected_image_url'] = api_image_url
                  logger.info(f"Using API image for {article_id}: {api_image_url}")
             else:
                 logger.error(f"Failed to find any image (scrape or API) for {article_id}. Skipping article.")
                 remove_scraped_file(json_filepath)
                 return False

        # 5. SEO Article Generation
        logger.debug(f"Running SEO agent for {article_id}...")
        article_data = run_seo_article_agent(article_data)
        seo_results = article_data.get('seo_agent_results')
        if not seo_results or not seo_results.get('generated_article_body_md'):
            seo_error = article_data.get('seo_agent_error', 'SEO agent critical failure or empty body')
            logger.error(f"SEO Agent failed or returned unusable results for {article_id}. Error: {seo_error}. Skipping article.")
            remove_scraped_file(json_filepath)
            return False
        elif article_data.get('seo_agent_error'):
             logger.warning(f"SEO Agent ran with non-critical errors for {article_id}: {article_data['seo_agent_error']}")

        # 6. Tags Generation
        logger.debug(f"Running Tags agent for {article_id}...")
        article_data = run_tags_generator_agent(article_data)
        tags_error = article_data.get('tags_agent_error')
        if tags_error: logger.warning(f"Tags Agent failed/skipped for {article_id}. Error: {tags_error}")
        article_data['generated_tags'] = article_data.get('generated_tags', []) if isinstance(article_data.get('generated_tags'), list) else []

        # 7. Trend Score Calculation
        trend_score = 0
        tags_count = len(article_data['generated_tags'])
        publish_date_iso = article_data.get('published_iso')
        try:
            if importance_level == "Interesting": trend_score += 5
            elif importance_level == "Breaking": trend_score += 10
            trend_score += tags_count * 0.5
            if publish_date_iso:
                 publish_dt = get_sort_key(article_data)
                 now_utc = datetime.now(timezone.utc)
                 if publish_dt <= now_utc:
                     days_old = (now_utc - publish_dt).total_seconds() / (60 * 60 * 24)
                     recency_factor = max(0, 1 - (days_old / 7))
                     trend_score += recency_factor * 5
                 else:
                      logger.warning(f"Publish date {publish_date_iso} seems to be in the future for {article_id}.")
        except Exception as e:
             logger.warning(f"Could not calculate trend score factors for {article_id}: {e}")

        article_data['trend_score'] = round(max(0, trend_score), 2)
        logger.debug(f"Calculated trend score for {article_id}: {article_data['trend_score']}")

        # --- Prepare for HTML Rendering ---
        # 8. Generate Slug
        original_title = article_data.get('title', f'article-{article_id}')
        slug = original_title.lower()
        slug = re.sub(r'[^a-z0-9\s-]', '', slug)
        slug = re.sub(r'\s+', '-', slug)
        slug = re.sub(r'-+', '-', slug).strip('-')
        slug = slug[:80]
        if not slug: slug = f'article-{article_id}'
        article_data['slug'] = slug

        # 9. Prepare Template Variables
        article_relative_path = f"articles/{slug}.html"
        canonical_url = urljoin(YOUR_SITE_BASE_URL, article_relative_path) # Use absolute URL

        body_md = seo_results.get('generated_article_body_md', '')
        try: body_html = markdown.markdown(body_md, extensions=['fenced_code', 'tables', 'nl2br'])
        except Exception as md_err:
            logger.error(f"Markdown conversion failed for {article_id}: {md_err}")
            body_html = f"<p><i>Content rendering error.</i></p><pre>{body_md}</pre>"

        tags_list = article_data.get('generated_tags', [])
        tags_html = format_tags_html(tags_list)
        publish_date_iso_for_meta = article_data.get('published_iso', datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
        try:
             publish_dt = get_sort_key(article_data)
             publish_date_formatted = publish_dt.strftime('%B %d, %Y')
        except Exception:
             publish_date_formatted = "Date Unknown"
             logger.warning(f"Could not format publish date for display {article_id}")


        page_title = seo_results.get('generated_title_tag', article_data.get('title', 'AI News'))
        meta_description = seo_results.get('generated_meta_description', article_data.get('summary', '')[:160])

        template_vars = {
            'PAGE_TITLE': page_title,
            'META_DESCRIPTION': meta_description,
            'AUTHOR_NAME': article_data.get('author', AUTHOR_NAME_DEFAULT),
            'META_KEYWORDS': ", ".join(tags_list),
            'CANONICAL_URL': canonical_url,
            'SITE_NAME': YOUR_WEBSITE_NAME,
            'YOUR_WEBSITE_LOGO_URL': YOUR_WEBSITE_LOGO_URL,
            'IMAGE_URL': article_data.get('selected_image_url', ''),
            'IMAGE_ALT_TEXT': page_title,
            'META_KEYWORDS_LIST': tags_list,
            'PUBLISH_ISO_FOR_META': publish_date_iso_for_meta,
            'JSON_LD_SCRIPT_BLOCK': seo_results.get('generated_json_ld', ''),
            'ARTICLE_HEADLINE': article_data.get('title', 'Article'),
            'PUBLISH_DATE': publish_date_formatted,
            'ARTICLE_BODY_HTML': body_html,
            'ARTICLE_TAGS_HTML': tags_html,
            'SOURCE_ARTICLE_URL': article_data.get('link', '#'),
            'ARTICLE_TITLE': article_data.get('title'),
            'id': article_id,
            'CURRENT_ARTICLE_ID': article_id,
            'CURRENT_ARTICLE_TOPIC': article_data.get('topic', ''),
            'CURRENT_ARTICLE_TAGS_JSON': json.dumps(tags_list),
            'AUDIO_URL': None
        }

        # 10. Render HTML Page
        generated_html_path = render_post_page(template_vars, slug)
        if not generated_html_path:
            logger.error(f"Failed to render HTML for {article_id}. Skipping article.")
            return False

        # --- Finalize and Update Site ---
        # 11. Prepare minimal data for site_data/all_articles JSON
        site_data_entry = {
            "id": article_id,
            "title": article_data.get('title'),
            "link": article_relative_path, # Relative path for site JSONs
            "published_iso": publish_date_iso_for_meta,
            "summary_short": meta_description,
            "image_url": article_data.get('selected_image_url'),
            "topic": article_data.get('topic', 'News'),
            "is_breaking": article_data.get('is_breaking', False),
            "tags": tags_list,
            "audio_url": None,
            "trend_score": article_data.get('trend_score', 0)
        }
        article_data['audio_url'] = None # Ensure audio_url is None in final processed JSON

        # 12. Update Site Data JSON files
        update_site_data(site_data_entry)

        # --- Post to Twitter (AFTER site data is updated) ---
        logger.info(f"Attempting to post article {article_id} to Twitter...")
        try:
            tweet_link = canonical_url # Use absolute URL
            tweet_title = article_data.get('title', 'New AI/Tech Article')
            tweet_image = article_data.get('selected_image_url')

            if tweet_title and tweet_link and tweet_image:
                if not tweet_link.startswith('http'):
                     logger.error(f"Canonical URL '{tweet_link}' for tweet is not absolute! Check YOUR_SITE_BASE_URL. Skipping tweet.")
                else:
                     tweet_success = post_tweet_with_image(tweet_title, tweet_link, tweet_image)
                     if tweet_success:
                         logger.info(f"Successfully posted {article_id} to Twitter.")
                     else:
                         logger.error(f"Failed to post {article_id} to Twitter (function returned False).")
                         # Non-fatal error
            else:
                logger.error(f"Missing title ('{tweet_title}'), link ('{tweet_link}'), or image URL ('{tweet_image}') for Twitter post (Article ID: {article_id}). Skipping tweet.")

        except Exception as tweet_err:
             logger.exception(f"Unexpected error during Twitter posting attempt for {article_id}: {tweet_err}")
        # --- END Twitter Post ---

        # --- Send data to Make.com Webhook ---
        logger.info(f"Attempting to send webhook to Make.com for {article_id}...")
        try:
            webhook_data = {
                "id": article_id,
                "title": article_data.get('title', 'New Article'),
                "article_url": canonical_url, # Send absolute URL
                "image_url": article_data.get('selected_image_url'),
                "topic": article_data.get('topic'),
                "tags": article_data.get('generated_tags', [])
            }
            if MAKE_WEBHOOK_URL: # Check if URL is loaded
                webhook_success = send_make_webhook(MAKE_WEBHOOK_URL, webhook_data)
                if webhook_success:
                    logger.info(f"Successfully sent webhook for {article_id}.")
                else:
                    logger.error(f"Failed sending webhook for {article_id}.")
            else:
                logger.warning(f"MAKE_INSTAGRAM_WEBHOOK_URL not configured. Skipping webhook for {article_id}.")

        except Exception as webhook_err:
             logger.exception(f"Unexpected error preparing/sending Make.com webhook for {article_id}: {webhook_err}")
        # --- END Webhook Send ---

        # 13. Save final processed data & remove original scraped file
        if save_processed_data(processed_file_path, article_data):
             remove_scraped_file(json_filepath)
             logger.info(f"--- Successfully processed article: {article_id} ---")
             return True
        else:
             logger.error(f"Failed to save final processed JSON for {article_id}. Original scraped file NOT removed.")
             return False

    except Exception as process_e:
         logger.exception(f"CRITICAL failure processing {article_id} (file {article_filename}): {process_e}")
         return False


# --- Main Orchestration Logic (Single Run) ---
if __name__ == "__main__":
    run_start_time = time.time()
    logger.info(f"--- === Dacoola AI News Orchestrator Starting Run ({datetime.now()}) === ---")

    ensure_directories()

    scraper_processed_ids = set()
    try: scraper_processed_ids = load_processed_ids()
    except Exception as load_e: logger.exception(f"Error loading processed IDs: {load_e}")

    # 1. Scrape for new articles
    logger.info("--- Stage 1: Running Scraper ---")
    new_articles_found_count = 0
    try:
        new_articles_found_count = scrape_news(NEWS_FEED_URLS, scraper_processed_ids)
        logger.info(f"Scraper run completed. Saved {new_articles_found_count} new raw article JSON files.")
    except NameError:
         logger.critical("NEWS_FEED_URLS not defined. Cannot run scraper.")
         sys.exit(1)
    except Exception as scrape_e:
        logger.exception(f"Scraper stage failed critically: {scrape_e}")
        logger.error("Proceeding to processing stage despite scraper error.")


    # 2. Process newly scraped articles (and any leftovers)
    logger.info("--- Stage 2: Running Processing Cycle ---")
    recent_articles_context = load_recent_articles_for_comparison()
    logger.info(f"Loaded {len(recent_articles_context)} recent articles from existing site data for duplicate checking.")

    json_files_to_process = []
    try: json_files_to_process = glob.glob(os.path.join(SCRAPED_ARTICLES_DIR, '*.json'))
    except Exception as glob_e: logger.exception(f"Error listing JSON files for processing: {glob_e}")

    if not json_files_to_process:
        logger.info("No new/leftover scraped articles found in directory to process.")
    else:
        logger.info(f"Found {len(json_files_to_process)} scraped articles to process.")
        processed_successfully_count = 0
        failed_or_skipped_count = 0

        try: json_files_to_process.sort(key=os.path.getmtime)
        except Exception as sort_e: logger.warning(f"Could not sort JSON files by time: {sort_e}")

        for filepath in json_files_to_process:
            if process_single_article(filepath, recent_articles_context):
                processed_successfully_count += 1
            else:
                 failed_or_skipped_count += 1
            time.sleep(1) # Small pause

        logger.info(f"Processing cycle complete. Successfully processed: {processed_successfully_count}, Failed/Skipped/Duplicate: {failed_or_skipped_count}")

    run_end_time = time.time()
    logger.info(f"--- === Dacoola AI News Orchestrator Run Finished ({run_end_time - run_start_time:.2f} seconds) === ---")