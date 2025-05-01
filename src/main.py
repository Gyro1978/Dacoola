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
import requests # Added requests import
from dotenv import load_dotenv
from datetime import datetime, timezone # Make sure timezone is imported
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
    # --- Catchy Title Agent Import REMOVED ---
    # from src.agents.catch_title_generator_agent import run_catch_title_agent # No longer needed

except ImportError as e:
     print(f"FATAL IMPORT ERROR: {e}")
     print("Check file names, function definitions, and __init__.py files.")
     sys.exit(1)

# --- Load Environment Variables ---
load_dotenv(dotenv_path=os.path.join(PROJECT_ROOT_FOR_PATH, '.env'))
MAX_HOME_PAGE_ARTICLES = int(os.getenv('MAX_HOME_PAGE_ARTICLES', 20))
AUTHOR_NAME_DEFAULT = os.getenv('AUTHOR_NAME', 'AI News Team')
# *** ADDED Site Config Vars ***
YOUR_WEBSITE_NAME = os.getenv('YOUR_WEBSITE_NAME', 'Dacoola') # Default name
YOUR_WEBSITE_LOGO_URL = os.getenv('YOUR_WEBSITE_LOGO_URL', '') # Get logo URL
YOUR_SITE_BASE_URL = os.getenv('YOUR_SITE_BASE_URL', '') # e.g., https://www.dacoola.com

# --- Setup Logging (before checking env vars so warnings are logged) ---
log_file_path = os.path.join(PROJECT_ROOT_FOR_PATH, 'dacoola.log')
# Ensure log directory exists if it's not the project root
try:
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    log_handlers = [
        # Try setting encoding for StreamHandler too, might help on some terminals
        logging.StreamHandler(sys.stdout), # .reconfigure(encoding='utf-8') # Python 3.9+
        logging.FileHandler(log_file_path, encoding='utf-8') # Specify UTF-8 for file handler
    ]
except OSError as e:
    print(f"Error creating log directory/file: {e}. Logging to console only.")
    log_handlers = [logging.StreamHandler(sys.stdout)]
# Setup basicConfig with handlers
logging.basicConfig(
    level=logging.INFO, # Keep as INFO for production, DEBUG for testing
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=log_handlers,
    force=True # Added force=True to allow reconfiguring if needed
)
# Set encoding for the root logger's stream handlers if possible (Python 3.9+)
# for handler in logging.getLogger().handlers:
#      if isinstance(handler, logging.StreamHandler):
#           try:
#                handler.reconfigure(encoding='utf-8')
#           except AttributeError: # Older Python versions might not have reconfigure
#                pass
logger = logging.getLogger('main_orchestrator')


# --- Log env var warnings AFTER logger is set up ---
if not YOUR_SITE_BASE_URL:
    logger.warning("YOUR_SITE_BASE_URL environment variable not set. Canonical and Open Graph URLs will be relative.")
CAMB_AI_API_KEY = os.getenv('CAMB_AI_API_KEY')
if not CAMB_AI_API_KEY:
     logger.warning("CAMB_AI_API_KEY environment variable not set. TTS generation will be skipped.")


# --- Configuration ---
DATA_DIR = os.path.join(PROJECT_ROOT_FOR_PATH, 'data')
SCRAPED_ARTICLES_DIR = os.path.join(DATA_DIR, 'scraped_articles')
PROCESSED_JSON_DIR = os.path.join(DATA_DIR, 'processed_json')
PUBLIC_DIR = os.path.join(PROJECT_ROOT_FOR_PATH, 'public')
OUTPUT_HTML_DIR = os.path.join(PUBLIC_DIR, 'articles')
TEMPLATE_DIR = os.path.join(PROJECT_ROOT_FOR_PATH, 'templates')
SITE_DATA_FILE = os.path.join(PUBLIC_DIR, 'site_data.json')
OUTPUT_AUDIO_DIR = os.path.join(PUBLIC_DIR, 'audio')
ALL_ARTICLES_FILE = os.path.join(PUBLIC_DIR, 'all_articles.json')


# --- Jinja2 Setup ---
try:
    # Add escapejs filter for JSON-LD safety
    def escapejs_filter(value):
        if value is None: return ''
        value = str(value)
        value = value.replace('\\', '\\\\')
        value = value.replace("'", "\\'")
        value = value.replace('"', '\\"')
        value = value.replace('\n', '\\n')
        value = value.replace('\r', '')
        value = value.replace('/', '\\/')
        value = value.replace('<', '\\u003c')
        value = value.replace('>', '\\u003e')
        return value

    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    env.filters['escapejs'] = escapejs_filter
    logger.info(f"Jinja2 environment loaded from {TEMPLATE_DIR}")
except Exception as e:
    logger.exception(f"CRITICAL: Failed to initialize Jinja2 from {TEMPLATE_DIR}. Exiting.")
    sys.exit(1)

# --- Helper Functions ---
def ensure_directories():
    try:
        os.makedirs(SCRAPED_ARTICLES_DIR, exist_ok=True)
        os.makedirs(PROCESSED_JSON_DIR, exist_ok=True)
        os.makedirs(OUTPUT_HTML_DIR, exist_ok=True)
        os.makedirs(OUTPUT_AUDIO_DIR, exist_ok=True)
        logger.info("Ensured data, public, and audio directories exist.")
    except OSError as e:
        logger.exception(f"CRITICAL: Could not create necessary directories: {e}")
        sys.exit(1)

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
    try:
        # Link to absolute path /topic.html assuming public is web root
        # Ensure tag names are URL-encoded using requests.utils.quote
        return " ".join([f'<span class="tag-item"><a href="/topic.html?name={requests.utils.quote(str(tag))}">{tag}</a></span>' for tag in tags_list])
    except Exception as e:
        logger.error(f"Error formatting tags: {tags_list} - {e}")
        return "" # Return empty string on error

# <<< --- FIX: Moved get_sort_key function here and made more robust --- >>>
def get_sort_key(x):
    """Helper function to extract a timezone-aware datetime object for sorting articles."""
    fallback_date = datetime(1970, 1, 1, tzinfo=timezone.utc) # Ensure fallback is offset-aware
    date_str = x.get('published_iso') # Don't provide default here
    if not date_str: # Handle None or empty string
        return fallback_date

    try:
        # Handle potential 'Z' timezone indicator
        if date_str.endswith('Z'):
            date_str = date_str[:-1] + '+00:00'
        dt = datetime.fromisoformat(date_str)
        # If parsed dt is naive, assume UTC (or local time if appropriate, but UTC is safer)
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            logger.debug(f"Date '{date_str}' was naive, assuming UTC.")
            return dt.replace(tzinfo=timezone.utc)
        return dt # Already timezone-aware
    except (ValueError, TypeError):
         # Attempt to parse date-only format, assuming UTC
         try:
             dt = datetime.strptime(date_str, '%Y-%m-%d')
             return dt.replace(tzinfo=timezone.utc) # Make it timezone-aware
         except: # Fallback for any other error
             logger.warning(f"Could not parse date '{date_str}' for sorting, using fallback.")
             return fallback_date

def render_post_page(template_variables, output_filename):
    try:
        template = env.get_template('post_template.html')
        html_content = template.render(template_variables)
        safe_filename = output_filename
        if not safe_filename: safe_filename = template_variables.get('id', 'untitled')
        safe_filename = re.sub(r'[<>:"/\\|?*\.]+', '', safe_filename)
        safe_filename = safe_filename[:100]
        if not safe_filename: safe_filename = template_variables.get('id', 'untitled_fallback')

        output_path = os.path.join(OUTPUT_HTML_DIR, f"{safe_filename}.html")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        # Ensure writing with UTF-8
        with open(output_path, 'w', encoding='utf-8') as f: f.write(html_content)
        logger.info(f"Rendered HTML: {output_path}")
        return output_path
    except Exception as e: logger.exception(f"CRITICAL Error rendering template for ID {template_variables.get('id','N/A')}: {e}"); return None

# --- Site Data Management ---
def load_recent_articles_for_comparison():
    articles_for_comparison = []
    try:
        if os.path.exists(SITE_DATA_FILE):
            with open(SITE_DATA_FILE, 'r', encoding='utf-8') as f:
                site_data = json.load(f)
                if isinstance(site_data.get('articles'), list):
                    for a in site_data["articles"][:50]: # Limit context size
                         if a and a.get("title"): # Check if article entry exists and has a title
                             articles_for_comparison.append({
                                 "title": a.get("title"),
                                 "summary_short": a.get("summary_short", a.get("summary", ""))[:300]
                             })
    except Exception as e: logger.warning(f"Could not load/process recent articles from {SITE_DATA_FILE} for comparison: {e}")
    return articles_for_comparison


def update_site_data(new_article_info):
    site_data = {"articles": []}
    all_articles_data = {"articles": []}

    # Load existing site_data
    try:
        if os.path.exists(SITE_DATA_FILE):
            with open(SITE_DATA_FILE, 'r', encoding='utf-8') as f:
                site_data = json.load(f)
                if not isinstance(site_data.get('articles'), list):
                     logger.warning(f"{SITE_DATA_FILE} format invalid. Resetting.")
                     site_data = {"articles": []}
    except Exception as e: logger.warning(f"Could not load {SITE_DATA_FILE}: {e}. Starting fresh."); site_data = {"articles": []}

    # Load existing all_articles_data
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

    minimal_entry = {
        "id": new_article_info.get('id'),
        "title": new_article_info.get('title'),
        "link": new_article_info.get('link'), # Relative path like 'articles/slug.html'
        "published_iso": new_article_info.get('published_iso'),
        "summary_short": new_article_info.get('summary_short'),
        "image_url": new_article_info.get('image_url'),
        "topic": new_article_info.get('topic'),
        "is_breaking": new_article_info.get('is_breaking', False),
        "tags": new_article_info.get('tags', []),
        "audio_url": new_article_info.get('audio_url'), # Should be relative like 'audio/file.mp3'
        "trend_score": new_article_info.get('trend_score', 0)
    }

    # Update/Add to site_data
    if article_id:
        # Use list comprehension for potentially cleaner update/add
        existing_ids_site = {a.get('id') for a in site_data.get("articles", []) if a}
        if article_id in existing_ids_site:
             site_data["articles"] = [
                 {**a, **minimal_entry} if a.get('id') == article_id else a
                 for a in site_data.get("articles", []) if a # Ensure 'a' is not None
             ]
             site_data_found = True
             logger.debug(f"Updating {article_id} in site_data.json")
        else:
             site_data.setdefault("articles", []).append(minimal_entry)
             logger.debug(f"Adding {article_id} to site_data.json")


    # Update/Add to all_articles_data
    if article_id:
        existing_ids_all = {a.get('id') for a in all_articles_data.get("articles", []) if a}
        if article_id in existing_ids_all:
            all_articles_data["articles"] = [
                 {**a, **minimal_entry} if a.get('id') == article_id else a
                 for a in all_articles_data.get("articles", []) if a
            ]
            all_articles_found = True
            logger.debug(f"Updating {article_id} in all_articles.json")
        else:
            all_articles_data.setdefault("articles", []).append(minimal_entry)
            logger.debug(f"Adding {article_id} to all_articles.json")


    # Sort both lists by date (using the moved get_sort_key function)
    site_data["articles"].sort(key=get_sort_key, reverse=True)
    all_articles_data["articles"].sort(key=get_sort_key, reverse=True)
    site_data["articles"] = site_data["articles"][:MAX_HOME_PAGE_ARTICLES]

    try:
        with open(SITE_DATA_FILE, 'w', encoding='utf-8') as f: json.dump(site_data, f, indent=2, ensure_ascii=False)
        logger.info(f"Updated {SITE_DATA_FILE} ({len(site_data['articles'])} articles).")
    except Exception as e: logger.error(f"Failed to save {SITE_DATA_FILE}: {e}")

    try:
        with open(ALL_ARTICLES_FILE, 'w', encoding='utf-8') as f: json.dump(all_articles_data, f, indent=2, ensure_ascii=False)
        logger.info(f"Updated {ALL_ARTICLES_FILE} ({len(all_articles_data['articles'])} articles).")
    except Exception as e: logger.error(f"Failed to save {ALL_ARTICLES_FILE}: {e}")


# --- Main Processing Pipeline ---
def process_single_article(json_filepath, recent_articles_context):
    logger.info(f"--- Processing article file: {os.path.basename(json_filepath)} ---")
    article_data = load_article_data(json_filepath)
    if not article_data: return False

    article_id = article_data.get('id', f'UNKNOWN_ID_{os.path.basename(json_filepath)}')
    processed_file_path = os.path.join(PROCESSED_JSON_DIR, os.path.basename(json_filepath))

    try:
        if os.path.exists(processed_file_path):
             logger.info(f"Article {article_id} already processed. Skipping.")
             remove_scraped_file(json_filepath)
             return False

        article_data = run_filter_agent(article_data)
        # Corrected: Check if article_data is not None before accessing keys
        if not article_data or article_data.get('filter_verdict') is None:
             filter_error = article_data.get('filter_error', 'Unknown error') if article_data else 'Article data became None after filter agent'
             logger.error(f"Filter Agent failed for {article_id}. Error: {filter_error}")
             return False # Skip this article if filter fails critically

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

        similarity_result = run_similarity_check_agent(article_data, recent_articles_context)
        if similarity_result and similarity_result.get('is_semantic_duplicate'):
            logger.info(f"Article {article_id} is SEMANTIC DUPLICATE. Skipping. Reason: {similarity_result.get('reasoning')}")
            remove_scraped_file(json_filepath)
            return False
        elif similarity_result is None: logger.warning(f"Similarity check failed for {article_id}. Proceeding cautiously.")
        else: logger.info(f"Article {article_id} passed similarity check.")

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

        article_data = run_seo_article_agent(article_data)
        seo_results = article_data.get('seo_agent_results') if article_data else None
        if not seo_results:
            seo_error = article_data.get('seo_agent_error', 'Unknown error') if article_data else 'Article data became None after SEO agent'
            logger.error(f"SEO Agent failed for {article_id}. Error: {seo_error}")
            seo_results = {}

        article_data = run_tags_generator_agent(article_data)
        tags_error = article_data.get('tags_agent_error') if article_data else 'Article data became None after Tags agent'
        if tags_error:
             logger.warning(f"Tags Agent failed/skipped for {article_id}. Error: {tags_error}")
        # Ensure 'generated_tags' exists and is a list AFTER the agent call
        article_data['generated_tags'] = article_data.get('generated_tags', []) if article_data and isinstance(article_data.get('generated_tags'), list) else []


        trend_score = 0
        importance_level = article_data.get('filter_verdict', {}).get('importance_level')
        tags_count = len(article_data.get('generated_tags', [])) # Now safe
        publish_date_iso = article_data.get('published_iso')

        if importance_level == "Interesting": trend_score += 5
        elif importance_level == "Breaking": trend_score += 10
        trend_score += tags_count * 0.5

        if publish_date_iso:
            try:
                publish_dt = get_sort_key(article_data) # Use moved function
                now = datetime.now(timezone.utc) # Ensure 'now' is offset-aware
                # Ensure publish_dt is offset-aware before subtracting
                if publish_dt.tzinfo is None or publish_dt.tzinfo.utcoffset(publish_dt) is None:
                     logger.warning(f"Making publish_dt timezone-aware for trend score calc (assuming UTC): {publish_dt}")
                     publish_dt = publish_dt.replace(tzinfo=timezone.utc)

                days_old = (now - publish_dt).total_seconds() / (60 * 60 * 24)
                if days_old < 0: recency_factor = 0
                elif days_old <= 1: recency_factor = 1.0
                elif days_old <= 3: recency_factor = 1.0 - (days_old - 1) / 2
                else: recency_factor = 0
                trend_score += recency_factor * 5
            except Exception as e: logger.warning(f"Could not calculate recency for trend score {article_id}: {e}")
        article_data['trend_score'] = round(max(0, trend_score), 2)
        logger.debug(f"Calculated trend score for {article_id}: {article_data['trend_score']}")

        article_data['audio_url'] = None
        if CAMB_AI_API_KEY:
            logger.info(f"Attempting TTS generation for {article_id}...")
            article_text_for_tts = seo_results.get('generated_article_body_md', '')
            if article_text_for_tts:
                article_data = run_tts_generator_agent(article_data, article_text_for_tts, OUTPUT_AUDIO_DIR)
                tts_error = article_data.get('tts_agent_error') if article_data else 'Article data became None after TTS agent'
                if tts_error: logger.error(f"TTS Agent failed for {article_id}. Error: {tts_error}")
                elif article_data.get('audio_url'): logger.info(f"TTS successful for {article_id}. Path: {article_data['audio_url']}")
                else: logger.warning(f"TTS Agent ran but did not return an audio_url for {article_id}.")
            else: logger.warning(f"No article body found for TTS generation for {article_id}.")
        else: logger.info("Skipping TTS generation - CAMB_AI_API_KEY not set.")

        original_title = article_data.get('title', 'article-' + article_id)
        slug = original_title.lower().replace(' ', '-').replace('_', '-')
        slug = "".join(c for c in slug if c.isalnum() or c == '-')
        slug = re.sub('-+', '-', slug).strip('-')[:80]
        if not slug: slug = 'article-' + article_id
        article_data['slug'] = slug

        article_relative_path = f"articles/{slug}.html"
        canonical_url = urljoin(YOUR_SITE_BASE_URL + '/', article_relative_path) if YOUR_SITE_BASE_URL else article_relative_path

        body_md = seo_results.get('generated_article_body_md', article_data.get('summary','*Content generation failed or incomplete.*'))
        try:
            body_html = markdown.markdown(body_md, extensions=['fenced_code', 'tables', 'nl2br'])
        except Exception as md_err:
            logger.error(f"Markdown conversion failed for {article_id}: {md_err}")
            body_html = f"<p><i>Content rendering error.</i></p><pre>{body_md}</pre>"

        tags_list = article_data.get('generated_tags', [])
        tags_html = format_tags_html(tags_list)
        publish_date_iso = article_data.get('published_iso', datetime.now(timezone.utc).isoformat())
        try:
             publish_dt = get_sort_key(article_data) # Use moved function
             publish_date_formatted = publish_dt.strftime('%B %d, %Y')
        except: publish_date_formatted = datetime.now(timezone.utc).strftime('%B %d, %Y')

        page_title = seo_results.get('generated_title_tag', article_data.get('title', 'AI News'))
        meta_description = seo_results.get('generated_meta_description', article_data.get('summary', '')[:160])

        absolute_audio_path = article_data.get('audio_url')
        relative_audio_url = None
        if absolute_audio_path and os.path.isabs(absolute_audio_path):
             try:
                  relative_audio_url = os.path.relpath(absolute_audio_path, PUBLIC_DIR).replace('\\', '/')
                  logger.debug(f"Calculated relative audio URL: {relative_audio_url}")
             except ValueError as e:
                  logger.error(f"Could not make audio path relative for {article_id} (path: {absolute_audio_path}, public_dir: {PUBLIC_DIR}): {e}")
                  relative_audio_url = None
        elif absolute_audio_path:
             relative_audio_url = absolute_audio_path

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
            'AUDIO_URL': relative_audio_url
        }

        generated_html_path = render_post_page(template_vars, slug)

        if generated_html_path:
            site_data_entry = {
                "id": article_id,
                "title": article_data.get('title'),
                "link": article_relative_path,
                "published_iso": article_data.get('published_iso'),
                "summary_short": meta_description,
                "image_url": article_data.get('selected_image_url'),
                "topic": article_data.get('topic', 'News'),
                "is_breaking": article_data.get('is_breaking', False),
                "tags": article_data.get('generated_tags', []),
                "audio_url": relative_audio_url,
                "trend_score": article_data.get('trend_score', 0)
            }
            article_data['audio_url'] = relative_audio_url # Save relative path to processed JSON too

            update_site_data(site_data_entry)

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
               if (article_data and not article_data.get('audio_url')
                    and article_data.get('seo_agent_results')
                    and article_data.get('tts_agent_error') is None):

                    article_id = article_data.get('id')
                    logger.info(f"Retrying TTS generation for article {article_id} from {os.path.basename(filepath)}")

                    article_text_for_tts = article_data.get('seo_agent_results', {}).get('generated_article_body_md', '')
                    if article_text_for_tts:
                         article_data = run_tts_generator_agent(article_data, article_text_for_tts, OUTPUT_AUDIO_DIR)
                         relative_audio_url = None
                         absolute_audio_path_retry = article_data.get('audio_url')
                         if absolute_audio_path_retry and os.path.isabs(absolute_audio_path_retry):
                              try:
                                   relative_audio_url = os.path.relpath(absolute_audio_path_retry, PUBLIC_DIR).replace('\\', '/')
                                   article_data['audio_url'] = relative_audio_url
                              except ValueError as e:
                                   logger.error(f"Could not make TTS retry path relative for {article_id}: {e}")
                                   article_data['audio_url'] = None
                         elif absolute_audio_path_retry:
                             relative_audio_url = absolute_audio_path_retry

                         if save_processed_data(filepath, article_data):
                              if not article_data.get('tts_agent_error') and relative_audio_url:
                                   logger.info(f"TTS Retry Successful for {article_id}. Updating site_data.")
                                   site_data_entry = {"id": article_id, "audio_url": relative_audio_url}
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
                         article_data['tts_agent_error'] = "Missing article body for TTS retry"
                         save_processed_data(filepath, article_data)
                         failed_count += 1
                    time.sleep(2)

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

    retry_failed_tts()

    logger.info("--- Running Processing Cycle ---")
    try:
        new_articles_count = scrape_news(NEWS_FEED_URLS, scraper_processed_ids)
        logger.info(f"Scraper run completed. Found {new_articles_count} new JSON files potentially.")
    except NameError:
         logger.error("NEWS_FEED_URLS not defined. Cannot run scraper.")
         sys.exit(1)
    except Exception as scrape_e:
        logger.exception(f"Scraper failed: {scrape_e}")
        sys.exit(1)

    recent_articles_context = load_recent_articles_for_comparison()
    logger.info(f"Loaded {len(recent_articles_context)} recent articles for duplicate checking.")

    json_files = []
    try: json_files = glob.glob(os.path.join(SCRAPED_ARTICLES_DIR, '*.json'))
    except Exception as glob_e: logger.exception(f"Error listing JSON files: {glob_e}")

    if not json_files: logger.info("No new scraped articles to process.")
    else:
        logger.info(f"Found {len(json_files)} scraped articles to process.")
        processed_count = 0; failed_skipped_count = 0
        try: json_files.sort(key=os.path.getmtime)
        except Exception as sort_e: logger.warning(f"Could not sort JSON files: {sort_e}")

        for filepath in json_files:
            current_recent_context = load_recent_articles_for_comparison()
            if process_single_article(filepath, current_recent_context):
                processed_count += 1
            else:
                 failed_skipped_count += 1
            time.sleep(1) # Be nice to APIs

        logger.info(f"Processing cycle complete. Successful: {processed_count}, Failed/Skipped: {failed_skipped_count}")

    logger.info("--- === Dacoola AI News Orchestrator Single Run Finished === ---")