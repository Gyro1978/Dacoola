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
# import shutil # Already removed
from jinja2 import Environment, FileSystemLoader
import markdown
import re # Needed for slug generation
import requests # Needed for requests.utils.quote
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
    # *** TTS Agent Import REMOVED ***

except ImportError as e:
     print(f"FATAL IMPORT ERROR: {e}")
     print("Check file names, function definitions, and __init__.py files.")
     sys.exit(1)

# --- Load Environment Variables ---
load_dotenv(dotenv_path=os.path.join(PROJECT_ROOT_FOR_PATH, '.env'))
MAX_HOME_PAGE_ARTICLES = int(os.getenv('MAX_HOME_PAGE_ARTICLES', 20))
AUTHOR_NAME_DEFAULT = os.getenv('AUTHOR_NAME', 'AI News Team')
YOUR_WEBSITE_NAME = os.getenv('YOUR_WEBSITE_NAME', 'Dacoola')
YOUR_WEBSITE_LOGO_URL = os.getenv('YOUR_WEBSITE_LOGO_URL', '')
YOUR_SITE_BASE_URL = os.getenv('YOUR_SITE_BASE_URL', '')
# *** CAMB_AI_API_KEY Loading REMOVED ***

# --- Setup Logging ---
log_file_path = os.path.join(PROJECT_ROOT_FOR_PATH, 'dacoola.log')
try:
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    log_handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file_path, encoding='utf-8')
    ]
except OSError as e:
    print(f"Error creating log directory/file: {e}. Logging to console only.")
    log_handlers = [logging.StreamHandler(sys.stdout)]

logging.basicConfig(
    level=logging.INFO, # INFO for prod, DEBUG for testing
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=log_handlers,
    force=True
)
logger = logging.getLogger('main_orchestrator')

# --- Log env var warnings AFTER logger is set up ---
if not YOUR_SITE_BASE_URL:
    logger.warning("YOUR_SITE_BASE_URL environment variable not set. Canonical and Open Graph URLs will be relative or potentially incorrect.")
# *** CAMB_AI_API_KEY Warning REMOVED ***
if not YOUR_WEBSITE_LOGO_URL:
     logger.warning("YOUR_WEBSITE_LOGO_URL environment variable not set. Schema markup and potentially branding might be affected.")

# --- Configuration ---
DATA_DIR = os.path.join(PROJECT_ROOT_FOR_PATH, 'data')
SCRAPED_ARTICLES_DIR = os.path.join(DATA_DIR, 'scraped_articles')
PROCESSED_JSON_DIR = os.path.join(DATA_DIR, 'processed_json')
PUBLIC_DIR = os.path.join(PROJECT_ROOT_FOR_PATH, 'public')
OUTPUT_HTML_DIR = os.path.join(PUBLIC_DIR, 'articles')
TEMPLATE_DIR = os.path.join(PROJECT_ROOT_FOR_PATH, 'templates')
SITE_DATA_FILE = os.path.join(PUBLIC_DIR, 'site_data.json')
# *** OUTPUT_AUDIO_DIR REMOVED ***
ALL_ARTICLES_FILE = os.path.join(PUBLIC_DIR, 'all_articles.json')


# --- Jinja2 Setup ---
try:
    # Add escapejs filter for JSON-LD safety
    def escapejs_filter(value):
        if value is None: return ''
        value = str(value)
        value = value.replace('\\', '\\\\').replace("'", "\\'").replace('"', '\\"')
        value = value.replace('\n', '\\n').replace('\r', '').replace('/', '\\/')
        value = value.replace('<', '\\u003c').replace('>', '\\u003e')
        return value

    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    env.filters['escapejs'] = escapejs_filter
    logger.info(f"Jinja2 environment loaded from {TEMPLATE_DIR}")
except Exception as e:
    logger.exception(f"CRITICAL: Failed to initialize Jinja2 from {TEMPLATE_DIR}. Exiting.")
    sys.exit(1)

# --- Helper Functions ---
def ensure_directories():
    """Creates necessary directories if they don't exist."""
    try:
        os.makedirs(SCRAPED_ARTICLES_DIR, exist_ok=True)
        os.makedirs(PROCESSED_JSON_DIR, exist_ok=True)
        os.makedirs(OUTPUT_HTML_DIR, exist_ok=True)
        # *** os.makedirs(OUTPUT_AUDIO_DIR, ...) REMOVED ***
        logger.info("Ensured data, processed_json, and public/articles directories exist.")
    except OSError as e:
        logger.exception(f"CRITICAL: Could not create necessary directories: {e}")
        sys.exit(1)

def load_article_data(filepath):
    """Loads JSON data from a file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f: return json.load(f)
    except Exception as e: logger.error(f"Error loading {filepath}: {e}"); return None

def save_processed_data(filepath, article_data):
    """Saves processed article data to a JSON file."""
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
    """Removes the original scraped JSON file after successful processing."""
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
        # Link to absolute path /topic.html assuming public is web root
        return " ".join([f'<span class="tag-item"><a href="/topic.html?name={requests.utils.quote(str(tag))}">{tag}</a></span>' for tag in tags_list])
    except Exception as e:
        logger.error(f"Error formatting tags: {tags_list} - {e}")
        return ""

def get_sort_key(article_dict):
    """Helper function to extract a timezone-aware datetime object for sorting articles."""
    fallback_date = datetime(1970, 1, 1, tzinfo=timezone.utc)
    date_str = article_dict.get('published_iso')
    if not date_str: return fallback_date

    try:
        if date_str.endswith('Z'): date_str = date_str[:-1] + '+00:00'
        dt = datetime.fromisoformat(date_str)
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            return dt.replace(tzinfo=timezone.utc) # Assume UTC if naive
        return dt # Already timezone-aware
    except (ValueError, TypeError):
         try: # Attempt date-only format
             dt = datetime.strptime(date_str, '%Y-%m-%d')
             return dt.replace(tzinfo=timezone.utc)
         except Exception: # Fallback for any error
             logger.warning(f"Could not parse date '{date_str}' for sorting ID {article_dict.get('id', 'N/A')}, using fallback.")
             return fallback_date

def render_post_page(template_variables, slug_base):
    """Renders a single article HTML page using the template."""
    try:
        template = env.get_template('post_template.html')
        html_content = template.render(template_variables)

        # Generate safe filename from slug_base
        safe_filename = slug_base if slug_base else template_variables.get('id', 'untitled')
        safe_filename = re.sub(r'[<>:"/\\|?*\.]+', '', safe_filename).strip().lower()
        safe_filename = safe_filename.replace(' ', '-')
        safe_filename = re.sub('-+', '-', safe_filename).strip('-')[:80]
        if not safe_filename: safe_filename = template_variables.get('id', 'untitled_fallback')

        output_path = os.path.join(OUTPUT_HTML_DIR, f"{safe_filename}.html")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f: f.write(html_content)
        logger.info(f"Rendered HTML: {output_path}")
        return output_path
    except Exception as e:
        logger.exception(f"CRITICAL Error rendering template for ID {template_variables.get('id','N/A')}: {e}")
        return None

# --- Site Data Management ---
def load_recent_articles_for_comparison():
    """Loads recent article titles/summaries for similarity checking."""
    articles_for_comparison = []
    try:
        if os.path.exists(SITE_DATA_FILE):
            with open(SITE_DATA_FILE, 'r', encoding='utf-8') as f:
                site_data = json.load(f)
                if isinstance(site_data.get('articles'), list):
                    for a in site_data["articles"][:50]:
                         if a and a.get("title") and a.get("id"):
                             articles_for_comparison.append({
                                 "title": a.get("title"),
                                 "summary_short": a.get("summary_short", a.get("summary", ""))[:300]
                             })
    except Exception as e:
        logger.warning(f"Could not load/process recent articles from {SITE_DATA_FILE} for comparison: {e}")
    return articles_for_comparison

def update_site_data(new_article_info):
    """Updates site_data.json and all_articles.json with new/updated article info."""
    site_data = {"articles": []}
    all_articles_data = {"articles": []}
    article_id = new_article_info.get('id')

    if not article_id:
        logger.error("Cannot update site data: new_article_info missing 'id'.")
        return

    # Load existing data safely
    for filepath, data_dict in [(SITE_DATA_FILE, site_data), (ALL_ARTICLES_FILE, all_articles_data)]:
        try:
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    loaded_data = json.load(f)
                    if isinstance(loaded_data.get('articles'), list):
                        data_dict.update(loaded_data)
        except Exception as e:
            logger.warning(f"Could not load {os.path.basename(filepath)}: {e}. Starting fresh.")

    # Prepare the minimal entry for JSON files (NO audio_url)
    minimal_entry = {
        "id": article_id,
        "title": new_article_info.get('title'),
        "link": new_article_info.get('link'),
        "published_iso": new_article_info.get('published_iso'),
        "summary_short": new_article_info.get('summary_short'),
        "image_url": new_article_info.get('image_url'),
        "topic": new_article_info.get('topic'),
        "is_breaking": new_article_info.get('is_breaking', False),
        "tags": new_article_info.get('tags', []),
        # "audio_url": new_article_info.get('audio_url'), # REMOVED
        "trend_score": new_article_info.get('trend_score', 0)
    }

    # Update/Add Logic for BOTH files
    for data_dict, filename in [(site_data, "site_data.json"), (all_articles_data, "all_articles.json")]:
        current_articles = data_dict.setdefault("articles", [])
        index_to_update = next((i for i, article in enumerate(current_articles) if article.get('id') == article_id), -1)

        if index_to_update != -1:
            current_articles[index_to_update] = {**current_articles[index_to_update], **minimal_entry}
            logger.debug(f"Updating {article_id} in {filename}")
        else:
            current_articles.append(minimal_entry)
            logger.debug(f"Adding {article_id} to {filename}")

    # Sort and Limit
    site_data["articles"].sort(key=get_sort_key, reverse=True)
    all_articles_data["articles"].sort(key=get_sort_key, reverse=True)
    site_data["articles"] = site_data["articles"][:MAX_HOME_PAGE_ARTICLES]

    # Save BOTH files
    for filepath, data_dict in [(SITE_DATA_FILE, site_data), (ALL_ARTICLES_FILE, all_articles_data)]:
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data_dict, f, indent=2, ensure_ascii=False)
            logger.info(f"Updated {os.path.basename(filepath)} ({len(data_dict['articles'])} articles).")
        except Exception as e:
            logger.error(f"Failed to save {os.path.basename(filepath)}: {e}")

# --- Main Processing Pipeline ---
def process_single_article(json_filepath, recent_articles_context):
    """Processes a single scraped article JSON file through the agent pipeline."""
    logger.info(f"--- Processing article file: {os.path.basename(json_filepath)} ---")
    article_data = load_article_data(json_filepath)
    if not article_data: return False

    article_id = article_data.get('id', f'UNKNOWN_ID_{os.path.basename(json_filepath)}')
    processed_file_path = os.path.join(PROCESSED_JSON_DIR, os.path.basename(json_filepath))

    try:
        # 1. Check if already processed
        if os.path.exists(processed_file_path):
             logger.info(f"Article {article_id} already processed. Skipping.")
             remove_scraped_file(json_filepath)
             return False

        # 2. Filter Agent
        article_data = run_filter_agent(article_data)
        if not article_data or article_data.get('filter_verdict') is None:
             filter_error = article_data.get('filter_error', 'Unknown error') if article_data else 'Filter agent critical failure'
             logger.error(f"Filter Agent failed for {article_id}. Error: {filter_error}")
             return False

        filter_verdict = article_data['filter_verdict']
        importance_level = filter_verdict.get('importance_level')
        if importance_level == "Boring":
            logger.info(f"Article {article_id} classified as Boring. Skipping.")
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
        elif similarity_result is None: logger.warning(f"Similarity check failed for {article_id}. Proceeding cautiously.")
        else: logger.info(f"Article {article_id} passed similarity check.")

        # 4. Image Finding
        logger.info(f"Finding image for {article_id}...")
        scraped_image_url = None
        source_url = article_data.get('link')
        if source_url:
             try: scraped_image_url = scrape_source_for_image(source_url)
             except Exception as scrape_e: logger.error(f"Error scraping source image: {scrape_e}")

        if scraped_image_url:
            article_data['selected_image_url'] = scraped_image_url
            logger.info(f"Using scraped image for {article_id}: {scraped_image_url}")
        else:
             logger.info(f"Image scraping failed/no image, using API search for {article_id}...")
             image_query = primary_keyword if primary_keyword else article_data.get('title', 'AI News')
             article_data['selected_image_url'] = find_best_image(image_query)

        if not article_data.get('selected_image_url'):
            logger.error(f"Failed to find any image for {article_id}. Skipping article.")
            return False

        # 5. SEO Article Generation
        article_data = run_seo_article_agent(article_data)
        seo_results = article_data.get('seo_agent_results')
        if not seo_results or not seo_results.get('generated_article_body_md'):
            seo_error = article_data.get('seo_agent_error', 'SEO agent critical failure or empty body')
            logger.error(f"SEO Agent failed or returned unusable results for {article_id}. Error: {seo_error}. Skipping article.")
            return False
        elif article_data.get('seo_agent_error'):
             logger.warning(f"SEO Agent ran with non-critical errors for {article_id}: {article_data['seo_agent_error']}")

        # 6. Tags Generation
        article_data = run_tags_generator_agent(article_data)
        tags_error = article_data.get('tags_agent_error')
        if tags_error: logger.warning(f"Tags Agent failed/skipped for {article_id}. Error: {tags_error}")
        article_data['generated_tags'] = article_data.get('generated_tags', []) if isinstance(article_data.get('generated_tags'), list) else []

        # 7. Trend Score Calculation
        trend_score = 0
        tags_count = len(article_data['generated_tags'])
        publish_date_iso = article_data.get('published_iso')
        if importance_level == "Interesting": trend_score += 5
        elif importance_level == "Breaking": trend_score += 10
        trend_score += tags_count * 0.5
        if publish_date_iso:
            try:
                publish_dt = get_sort_key(article_data)
                now = datetime.now(timezone.utc)
                days_old = (now - publish_dt).total_seconds() / (60 * 60 * 24)
                if days_old < 0: recency_factor = 0
                elif days_old <= 1: recency_factor = 1.0
                elif days_old <= 3: recency_factor = 1.0 - (days_old - 1) / 2
                else: recency_factor = 0
                trend_score += recency_factor * 5
            except Exception as e: logger.warning(f"Could not calculate recency for trend score {article_id}: {e}")
        article_data['trend_score'] = round(max(0, trend_score), 2)
        logger.debug(f"Calculated trend score for {article_id}: {article_data['trend_score']}")

        # *** TTS Generation Step REMOVED ***

        # --- Prepare for HTML Rendering ---
        # 8. Generate Slug
        original_title = article_data.get('title', 'article-' + article_id)
        slug = original_title.lower().replace(' ', '-').replace('_', '-')
        slug = "".join(c for c in slug if c.isalnum() or c == '-')
        slug = re.sub('-+', '-', slug).strip('-')[:80]
        if not slug: slug = 'article-' + article_id
        article_data['slug'] = slug

        # 9. Prepare Template Variables
        article_relative_path = f"articles/{slug}.html"
        base_url_for_join = (YOUR_SITE_BASE_URL.rstrip('/') + '/') if YOUR_SITE_BASE_URL else ''
        canonical_url = urljoin(base_url_for_join, article_relative_path)

        body_md = seo_results.get('generated_article_body_md')
        try: body_html = markdown.markdown(body_md, extensions=['fenced_code', 'tables', 'nl2br'])
        except Exception as md_err:
            logger.error(f"Markdown conversion failed for {article_id}: {md_err}")
            body_html = f"<p><i>Content rendering error.</i></p><pre>{body_md}</pre>"

        tags_list = article_data.get('generated_tags', [])
        tags_html = format_tags_html(tags_list)
        publish_date_iso = article_data.get('published_iso', datetime.now(timezone.utc).isoformat())
        try: publish_dt = get_sort_key(article_data); publish_date_formatted = publish_dt.strftime('%B %d, %Y')
        except: publish_date_formatted = datetime.now(timezone.utc).strftime('%B %d, %Y')

        page_title = seo_results.get('generated_title_tag', article_data.get('title', 'AI News'))
        meta_description = seo_results.get('generated_meta_description', article_data.get('summary', '')[:160])
        # *** relative_audio_url REMOVED ***

        template_vars = {
            'PAGE_TITLE': page_title,
            'META_DESCRIPTION': meta_description,
            'AUTHOR_NAME': article_data.get('author', AUTHOR_NAME_DEFAULT),
            'META_KEYWORDS': ", ".join(tags_list),
            'CANONICAL_URL': canonical_url,
            'SITE_NAME': YOUR_WEBSITE_NAME,
            'YOUR_WEBSITE_LOGO_URL': YOUR_WEBSITE_LOGO_URL,
            'IMAGE_URL': article_data.get('selected_image_url'),
            'IMAGE_ALT_TEXT': page_title,
            'META_KEYWORDS_LIST': tags_list,
            'PUBLISH_ISO_FOR_META': publish_date_iso,
            'JSON_LD_SCRIPT_BLOCK': seo_results.get('generated_json_ld', ''),
            'ARTICLE_HEADLINE': article_data.get('title'),
            'PUBLISH_DATE': publish_date_formatted,
            'ARTICLE_BODY_HTML': body_html,
            'ARTICLE_TAGS_HTML': tags_html,
            'SOURCE_ARTICLE_URL': article_data.get('link', '#'),
            'ARTICLE_TITLE': article_data.get('title'),
            'id': article_id,
            'CURRENT_ARTICLE_ID': article_id,
            'CURRENT_ARTICLE_TOPIC': article_data.get('topic', ''),
            'CURRENT_ARTICLE_TAGS_JSON': json.dumps(tags_list),
            'AUDIO_URL': None # Explicitly set to None
        }

        # 10. Render HTML Page
        generated_html_path = render_post_page(template_vars, slug)

        # --- Finalize ---
        if generated_html_path:
            # 11. Prepare minimal data for site_data/all_articles JSON
            site_data_entry = {
                "id": article_id,
                "title": article_data.get('title'),
                "link": article_relative_path,
                "published_iso": publish_date_iso,
                "summary_short": meta_description,
                "image_url": article_data.get('selected_image_url'),
                "topic": article_data.get('topic', 'News'),
                "is_breaking": article_data.get('is_breaking', False),
                "tags": tags_list,
                "audio_url": None, # Ensure audio_url is None here too
                "trend_score": article_data.get('trend_score', 0)
            }
            # Update main data dict just before saving
            article_data['audio_url'] = None # Ensure audio_url is None in processed JSON

            # 12. Update Site Data JSON files
            update_site_data(site_data_entry)

            # 13. Save final processed data & remove original scraped file
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


# --- TTS Retry Logic REMOVED ---


# --- Main Orchestration Logic (Runs Once) ---
if __name__ == "__main__":
    start_time = time.time()
    logger.info("--- === Dacoola AI News Orchestrator Starting Single Run === ---")
    ensure_directories()
    scraper_processed_ids = set()
    try: scraper_processed_ids = load_processed_ids()
    except Exception as load_e: logger.exception(f"Error loading processed IDs: {load_e}")

    # *** TTS Retry Call REMOVED ***

    # 1. Scrape for new articles
    logger.info("--- Running Scraper ---")
    new_articles_count = 0
    try:
        new_articles_count = scrape_news(NEWS_FEED_URLS, scraper_processed_ids)
        logger.info(f"Scraper run completed. Found {new_articles_count} new JSON files potentially.")
    except NameError:
         logger.error("NEWS_FEED_URLS not defined. Cannot run scraper.")
         sys.exit(1)
    except Exception as scrape_e:
        logger.exception(f"Scraper failed: {scrape_e}")

    # 2. Process newly scraped articles (and any leftovers)
    logger.info("--- Running Processing Cycle ---")
    recent_articles_context = load_recent_articles_for_comparison()
    logger.info(f"Loaded {len(recent_articles_context)} recent articles for duplicate checking.")

    json_files = []
    try: json_files = glob.glob(os.path.join(SCRAPED_ARTICLES_DIR, '*.json'))
    except Exception as glob_e: logger.exception(f"Error listing JSON files: {glob_e}")

    if not json_files:
        logger.info("No new scraped articles to process.")
    else:
        logger.info(f"Found {len(json_files)} scraped articles to process.")
        processed_count = 0
        failed_skipped_count = 0
        try: json_files.sort(key=os.path.getmtime)
        except Exception as sort_e: logger.warning(f"Could not sort JSON files by time: {sort_e}")

        for filepath in json_files:
            current_recent_context = load_recent_articles_for_comparison()
            if process_single_article(filepath, current_recent_context):
                processed_count += 1
            else:
                 failed_skipped_count += 1
            time.sleep(1) # Small pause between processing articles

        logger.info(f"Processing cycle complete. Successful: {processed_count}, Failed/Skipped: {failed_skipped_count}")

    end_time = time.time()
    logger.info(f"--- === Dacoola AI News Orchestrator Single Run Finished ({end_time - start_time:.2f} seconds) === ---")