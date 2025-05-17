# src/main.py (Corrected with Similarity Check Agent & Template Hashing & Link Placeholder Processing)

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
import re
import requests
import html
import hashlib # For template hashing
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, quote # Added quote for link placeholder processing
import markdown

# --- Import Sitemap Generator ---
try:
    from generate_sitemap import generate_sitemap as run_sitemap_generator
except ImportError as e:
    temp_log_msg = f"FATAL IMPORT ERROR: Could not import sitemap generator: {e}."
    print(temp_log_msg); logging.critical(temp_log_msg); sys.exit(1)

# --- Import Agent and Scraper Functions ---
try:
    from src.scrapers.news_scraper import (
        scrape_news, load_processed_ids as load_scraper_processed_ids,
        save_processed_id as save_scraper_processed_id, get_article_id,
        NEWS_FEED_URLS
    )
    from src.scrapers.image_scraper import find_best_image, scrape_source_for_image
    from src.agents.filter_news_agent import run_filter_agent
    from src.agents.similarity_check_agent import run_similarity_check_agent
    from src.agents.keyword_research_agent import run_keyword_research_agent
    from src.agents.seo_article_generator_agent import run_seo_article_agent
    from src.social.social_media_poster import (
        initialize_social_clients, run_social_media_poster,
        load_post_history as load_social_post_history,
        mark_article_as_posted_in_history
    )
except ImportError as e:
     print(f"FATAL IMPORT ERROR in main.py (agents/scrapers/social): {e}")
     try: logging.critical(f"FATAL IMPORT ERROR (agents/scrapers/social): {e}")
     except ImportError: pass # logging might not be set up yet
     sys.exit(1)

# --- Load Environment Variables ---
dotenv_path = os.path.join(PROJECT_ROOT_FOR_PATH, '.env'); load_dotenv(dotenv_path=dotenv_path)
AUTHOR_NAME_DEFAULT = os.getenv('AUTHOR_NAME', 'AI News Team')
YOUR_WEBSITE_NAME = os.getenv('YOUR_WEBSITE_NAME', 'Dacoola')
YOUR_WEBSITE_LOGO_URL = os.getenv('YOUR_WEBSITE_LOGO_URL', '')
raw_base_url = os.getenv('YOUR_SITE_BASE_URL', ''); YOUR_SITE_BASE_URL = (raw_base_url.rstrip('/') + '/') if raw_base_url else ''
BASE_URL_FOR_CANONICAL_MAIN = YOUR_SITE_BASE_URL # Used for JSON-LD placeholder replacement
MAKE_WEBHOOK_URL = os.getenv('MAKE_INSTAGRAM_WEBHOOK_URL', None)
DAILY_TWEET_LIMIT = int(os.getenv('DAILY_TWEET_LIMIT', '3'))
MAX_AGE_FOR_SOCIAL_POST_HOURS = 24


# --- Setup Logging ---
log_file_path = os.path.join(PROJECT_ROOT_FOR_PATH, 'dacola.log')
try:
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    log_handlers = [ logging.StreamHandler(sys.stdout), logging.FileHandler(log_file_path, encoding='utf-8') ]
except OSError as e: print(f"Log setup warning: {e}. Log console only."); log_handlers = [logging.StreamHandler(sys.stdout)]

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=log_handlers,
    force=True
)
logger = logging.getLogger('main_orchestrator')
logger.setLevel(logging.DEBUG)

if not YOUR_SITE_BASE_URL or YOUR_SITE_BASE_URL == '/':
    logger.error("CRITICAL: YOUR_SITE_BASE_URL is not set or is invalid ('/'). Canonical URLs and sitemap will be incorrect.")
else:
    logger.info(f"Using site base URL: {YOUR_SITE_BASE_URL}")
if not YOUR_WEBSITE_LOGO_URL: logger.warning("YOUR_WEBSITE_LOGO_URL not set.")


# --- Configuration ---
DATA_DIR_MAIN = os.path.join(PROJECT_ROOT_FOR_PATH, 'data')
SCRAPED_ARTICLES_DIR = os.path.join(DATA_DIR_MAIN, 'scraped_articles')
PROCESSED_JSON_DIR = os.path.join(DATA_DIR_MAIN, 'processed_json')
PUBLIC_DIR = os.path.join(PROJECT_ROOT_FOR_PATH, 'public')
OUTPUT_HTML_DIR = os.path.join(PUBLIC_DIR, 'articles')
TEMPLATE_DIR = os.path.join(PROJECT_ROOT_FOR_PATH, 'templates')
ALL_ARTICLES_FILE = os.path.join(PUBLIC_DIR, 'all_articles.json')
ARTICLE_MAX_AGE_DAYS = 30
TWITTER_DAILY_LIMIT_FILE = os.path.join(DATA_DIR_MAIN, 'twitter_daily_limit.json')
POST_TEMPLATE_FILE = os.path.join(TEMPLATE_DIR, 'post_template.html')


# --- Jinja2 Setup ---
try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    def escapejs_filter(value): # JavaScript string escape
        if value is None: return ''
        value = str(value)
        value = value.replace('\\', '\\\\')
        value = value.replace("'", "\\'")
        value = value.replace('"', '\\"')
        value = value.replace('/', '\\/')
        value = value.replace('\n', '\\n')
        value = value.replace('\r', '\\r')
        value = value.replace('\t', '\\t')
        value = value.replace('<', '\\u003c')
        value = value.replace('>', '\\u003e')
        value = value.replace('\b', '\\b')
        value = value.replace('\f', '\\f')
        return value
    if not os.path.isdir(TEMPLATE_DIR):
        logger.critical(f"Jinja2 template directory not found: {TEMPLATE_DIR}. Exiting.")
        sys.exit(1)
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(['html', 'xml']))
    env.filters['escapejs'] = escapejs_filter
    logger.info(f"Jinja2 environment loaded from {TEMPLATE_DIR}")
except ImportError: logger.critical("Jinja2 library not found. Exiting."); sys.exit(1)
except Exception as e: logger.exception(f"CRITICAL: Failed Jinja2 init. Exiting: {e}"); sys.exit(1)

# --- Helper Functions ---
def ensure_directories():
    dirs_to_create = [ DATA_DIR_MAIN, SCRAPED_ARTICLES_DIR, PROCESSED_JSON_DIR, PUBLIC_DIR, OUTPUT_HTML_DIR, TEMPLATE_DIR ]
    try:
        for d in dirs_to_create: os.makedirs(d, exist_ok=True)
        logger.info("Ensured core directories exist.")
    except OSError as e: logger.exception(f"CRITICAL: Create directory fail {getattr(e, 'filename', 'N/A')}: {getattr(e, 'strerror', str(e))}"); sys.exit(1)

def get_file_hash(filepath):
    hasher = hashlib.sha256()
    try:
        with open(filepath, 'rb') as f:
            buf = f.read(65536)
            while len(buf) > 0:
                hasher.update(buf)
                buf = f.read(65536)
        return hasher.hexdigest()
    except FileNotFoundError:
        logger.error(f"File not found for hashing: {filepath}")
        return None
    except Exception as e:
        logger.error(f"Error hashing file {filepath}: {e}")
        return None

current_post_template_hash = None

def load_article_data(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f: return json.load(f)
    except FileNotFoundError: logger.warning(f"File not found: {filepath}"); return None
    except json.JSONDecodeError: logger.error(f"Error decoding JSON from {filepath}."); return None
    except Exception as e: logger.error(f"Error loading article data {filepath}: {e}"); return None

def save_processed_data(filepath, article_data_to_save):
    try:
         os.makedirs(os.path.dirname(filepath), exist_ok=True)
         if current_post_template_hash:
             article_data_to_save['post_template_hash'] = current_post_template_hash
         else:
             logger.warning("current_post_template_hash is None during save_processed_data. Hash will not be saved.")

         with open(filepath, 'w', encoding='utf-8') as f: json.dump(article_data_to_save, f, indent=4, ensure_ascii=False)
         logger.info(f"Saved processed data: {os.path.basename(filepath)}"); return True
    except Exception as e: logger.error(f"Failed save processed data {os.path.basename(filepath)}: {e}"); return False

def remove_scraped_file(filepath):
    try:
         if os.path.exists(filepath): os.remove(filepath); logger.debug(f"Removed original scraped file: {os.path.basename(filepath)}")
         else: logger.warning(f"Attempted remove non-existent file: {filepath}")
    except OSError as e: logger.error(f"Failed remove scraped file {filepath}: {e}")

def format_tags_html(tags_list_for_html):
    if not tags_list_for_html or not isinstance(tags_list_for_html, list): return ""
    try:
        tag_html_links = []; base_url_for_tags = YOUR_SITE_BASE_URL.rstrip('/') + '/' if YOUR_SITE_BASE_URL else '/'
        for tag_item in tags_list_for_html:
            safe_tag_item = requests.utils.quote(str(tag_item))
            tag_page_url = urljoin(base_url_for_tags, f"topic.html?name={safe_tag_item}")
            tag_html_links.append(f'<a href="{tag_page_url}" class="tag-link">{html.escape(str(tag_item))}</a>')
        return ", ".join(tag_html_links)
    except Exception as e: logger.error(f"Error formatting tags HTML: {tags_list_for_html} - {e}"); return ""

def get_sort_key(article_dict_item):
    fallback_past_date = datetime(1970, 1, 1, tzinfo=timezone.utc)
    date_iso_str = article_dict_item.get('published_iso')
    if not date_iso_str or not isinstance(date_iso_str, str): return fallback_past_date
    try:
        if date_iso_str.endswith('Z'): date_iso_str = date_iso_str[:-1] + '+00:00'
        dt_obj = datetime.fromisoformat(date_iso_str)
        return dt_obj.replace(tzinfo=timezone.utc) if dt_obj.tzinfo is None else dt_obj
    except ValueError: logger.warning(f"Parse date error '{date_iso_str}'. Using fallback."); return fallback_past_date

def _read_tweet_tracker():
    today_date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    try:
        if os.path.exists(TWITTER_DAILY_LIMIT_FILE):
            with open(TWITTER_DAILY_LIMIT_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
            if data.get('date') == today_date_str: return data['date'], data.get('count', 0)
        return today_date_str, 0
    except Exception as e: logger.error(f"Error reading Twitter tracker {TWITTER_DAILY_LIMIT_FILE}: {e}. Resetting."); return today_date_str, 0

def _write_tweet_tracker(date_str, count):
    try:
        os.makedirs(os.path.dirname(TWITTER_DAILY_LIMIT_FILE), exist_ok=True)
        with open(TWITTER_DAILY_LIMIT_FILE, 'w', encoding='utf-8') as f: json.dump({'date': date_str, 'count': count}, f, indent=2)
        logger.info(f"Twitter tracker updated: Date {date_str}, Count {count}")
    except Exception as e: logger.error(f"Error writing Twitter tracker {TWITTER_DAILY_LIMIT_FILE}: {e}")

def send_make_webhook(webhook_url, data_payload):
    if not webhook_url: logger.warning("Make webhook URL missing."); return False
    if not data_payload: logger.warning("No data for Make webhook."); return False
    payload_to_send = {"articles": data_payload} if isinstance(data_payload, list) else data_payload
    log_id_info_str = f"batch of {len(data_payload)} articles" if isinstance(data_payload, list) else f"article ID: {data_payload.get('id', 'N/A')}"
    try:
        response = requests.post(webhook_url, headers={'Content-Type': 'application/json'}, json=payload_to_send, timeout=30)
        response.raise_for_status(); logger.info(f"Sent to Make webhook: {log_id_info_str}"); return True
    except Exception as e: logger.error(f"Failed send to Make webhook {log_id_info_str}: {e}"); return False

def render_post_page(template_variables_dict, slug_base_str):
    try:
        template = env.get_template('post_template.html')
        html_content_output = template.render(template_variables_dict)

        # Ensure slug_base_str is a string before processing
        if not isinstance(slug_base_str, str):
            logger.error(f"Slug base is not a string for article ID {template_variables_dict.get('id','N/A')}. Using ID as fallback.")
            slug_base_str = str(template_variables_dict.get('id', 'untitled-article-fallback-id'))

        safe_filename_str = slug_base_str
        safe_filename_str = re.sub(r'[<>:"/\\|?*%\.]+', '', safe_filename_str).strip().lower().replace(' ', '-')
        safe_filename_str = re.sub(r'-+', '-', safe_filename_str).strip('-')[:80] or template_variables_dict.get('id', 'article-fallback-slug')
        
        output_html_path = os.path.join(OUTPUT_HTML_DIR, f"{safe_filename_str}.html")
        os.makedirs(os.path.dirname(output_html_path), exist_ok=True)
        with open(output_html_path, 'w', encoding='utf-8') as f: f.write(html_content_output)
        logger.info(f"Rendered HTML: {os.path.basename(output_html_path)}")
        return output_html_path
    except Exception as e: logger.exception(f"CRITICAL: Failed HTML render for article ID {template_variables_dict.get('id','N/A')}, slug_base: {slug_base_str}: {e}"); return None


def load_all_articles_data_from_json():
    if not os.path.exists(ALL_ARTICLES_FILE): return []
    try:
        with open(ALL_ARTICLES_FILE, 'r', encoding='utf-8') as f: data_content = json.load(f)
        if isinstance(data_content, dict) and isinstance(data_content.get('articles'), list): return data_content['articles']
        logger.warning(f"{ALL_ARTICLES_FILE} invalid structure. Returning empty.")
    except json.JSONDecodeError: logger.error(f"Error decoding {ALL_ARTICLES_FILE}. Returning empty.")
    except Exception as e: logger.error(f"Error loading {ALL_ARTICLES_FILE}: {e}. Returning empty.")
    return []

def update_all_articles_json_file(new_article_summary_info):
    current_articles_list_data = load_all_articles_data_from_json()
    article_unique_id = new_article_summary_info.get('id')
    if not article_unique_id:
        logger.error("Update all_articles: new info missing 'id'.")
        return

    articles_dict = {
        art.get('id'): art
        for art in current_articles_list_data
        if isinstance(art, dict) and art.get('id')
    }
    articles_dict[article_unique_id] = new_article_summary_info

    updated_articles_list = sorted(
        list(articles_dict.values()), key=get_sort_key, reverse=True
    )
    final_data_to_save_to_json_obj = {"articles": updated_articles_list}

    try:
        json_string_to_write = json.dumps(final_data_to_save_to_json_obj, indent=2, ensure_ascii=False)
        try:
            json.loads(json_string_to_write)
            logger.debug(f"JSON content for {ALL_ARTICLES_FILE} validated successfully before writing.")
        except json.JSONDecodeError as jde:
            logger.error(f"CRITICAL: Generated content for {ALL_ARTICLES_FILE} is NOT VALID JSON before writing: {jde}")
            logger.error(f"Problematic data (first 500 chars of generated string): {json_string_to_write[:500]}")
            return
        with open(ALL_ARTICLES_FILE, 'w', encoding='utf-8') as f:
            f.write(json_string_to_write)
        logger.info(f"Updated {os.path.basename(ALL_ARTICLES_FILE)} ({len(updated_articles_list)} articles).")
    except TypeError as te:
        logger.error(f"CRITICAL: TypeError during JSON serialization for {ALL_ARTICLES_FILE}: {te}.")
    except Exception as e:
        logger.error(f"Failed to save updated {os.path.basename(ALL_ARTICLES_FILE)}: {e}")

# --- Link Placeholder Processing Functions (copied from gyro-picks.py) ---
def slugify(text):
    """Generates a URL-friendly slug from text."""
    if not text: return "untitled"
    text = str(text).lower() # Ensure text is string
    text = re.sub(r'[^\w\s-]', '', text).strip() 
    text = re.sub(r'[-\s]+', '-', text)       
    return text[:70] 

def process_link_placeholders(markdown_text, base_site_url):
    """
    Processes [[Internal Link Text | Optional Topic/Slug]] and 
              ((External Link Text | https://...)) placeholders in Markdown.
    """
    if not markdown_text: return ""
    if not base_site_url or base_site_url == '/':
        logger.warning("Base site URL is not valid for link placeholder processing. Links may be incorrect.")
        # Default to relative links if base_site_url is problematic
        base_site_url = "/" 

    def replace_internal(match):
        link_text = match.group(1).strip()
        topic_or_slug = match.group(3).strip() if match.group(3) else None
        href = ""
        if topic_or_slug:
            if topic_or_slug.endswith(".html") or ' ' not in topic_or_slug and topic_or_slug.count('-') > 0: # Looks like a pre-made slug
                 # Ensure 'articles/' prefix for slugs that are just filenames.
                 if topic_or_slug.endswith(".html") and not topic_or_slug.startswith("articles/"):
                     href = urljoin(base_site_url, f"articles/{topic_or_slug.lstrip('/')}")
                 elif not topic_or_slug.endswith(".html"): # It's a topic-like slug without .html, treat as topic
                     href = urljoin(base_site_url, f"topic.html?name={quote(topic_or_slug)}")
                 else: # Already has articles/ prefix or is a full path segment
                     href = urljoin(base_site_url, topic_or_slug.lstrip('/'))
            else: # Assume it's a topic name
                href = urljoin(base_site_url, f"topic.html?name={quote(topic_or_slug)}")
        else:
            slugified_link_text = slugify(link_text)
            href = urljoin(base_site_url, f"topic.html?name={quote(slugified_link_text)}")
        
        logger.debug(f"Internal link: Text='{link_text}', Target='{topic_or_slug}', Href='{href}'")
        return f'<a href="{html.escape(href)}" class="internal-link">{html.escape(link_text)}</a>'

    processed_text = re.sub(r'\[\[\s*(.*?)\s*(?:\|\s*(.*?)\s*)?\]\]', replace_internal, markdown_text)

    def replace_external(match):
        link_text = match.group(1).strip()
        url = match.group(2).strip()
        logger.debug(f"External link: Text='{link_text}', URL='{url}'")
        return f'<a href="{html.escape(url)}" target="_blank" rel="noopener noreferrer" class="external-link">{html.escape(link_text)}</a>'

    processed_text = re.sub(r'\(\(\s*(.*?)\s*\|\s*(https?://.*?)\s*\)\)', replace_external, processed_text)
    return processed_text
# --- End Link Placeholder Processing Functions ---


def regenerate_article_html_if_needed(article_data_content, force_regen=False):
    global current_post_template_hash
    if not current_post_template_hash:
        logger.error("Current post template hash not available. Cannot reliably check for regeneration.")
        return False

    article_unique_id = article_data_content.get('id')
    article_slug_str = article_data_content.get('slug')

    if not article_unique_id:
        logger.warning(f"Skipping HTML regen check: missing id in data for {article_data_content.get('title', 'Unknown article')}")
        return False
    if not article_slug_str:
        article_title_for_slug = article_data_content.get('title', article_unique_id)
        temp_slug = re.sub(r'[^\w\s-]', '', str(article_title_for_slug).lower()).strip() # Ensure title is string
        article_slug_str = re.sub(r'[-\s]+', '-', temp_slug)[:80] or article_unique_id
        logger.warning(f"Article {article_unique_id} missing slug. Derived for regen: {article_slug_str}")
        article_data_content['slug'] = article_slug_str

    expected_html_file_path = os.path.join(OUTPUT_HTML_DIR, f"{article_slug_str}.html")
    stored_template_hash = article_data_content.get('post_template_hash')
    needs_regeneration = False

    if not os.path.exists(expected_html_file_path):
        logger.info(f"HTML missing for article ID {article_unique_id} (slug: {article_slug_str}). Will regenerate.")
        needs_regeneration = True
    elif force_regen:
        logger.info(f"Forcing HTML regeneration for article ID {article_unique_id} (slug: {article_slug_str}).")
        needs_regeneration = True
    elif stored_template_hash != current_post_template_hash:
        logger.info(f"Template changed for article ID {article_unique_id} (slug: {article_slug_str}). Old hash: {stored_template_hash}, New: {current_post_template_hash}. Will regenerate.")
        needs_regeneration = True

    if needs_regeneration:
        logger.info(f"Regenerating HTML for article ID {article_unique_id}...")
        seo_agent_results_data = article_data_content.get('seo_agent_results', {})
        if not isinstance(seo_agent_results_data, dict):
            logger.error(f"Article {article_unique_id} 'seo_agent_results' is not a dictionary. Using empty for regen.")
            seo_agent_results_data = {}

        article_body_md_content_raw = seo_agent_results_data.get('generated_article_body_md', '')
        if not article_body_md_content_raw:
             logger.warning(f"Article {article_unique_id} has empty 'generated_article_body_md'. HTML body will be empty.")
        
        # --- Process Link Placeholders before Markdown to HTML conversion ---
        logger.debug(f"Processing link placeholders for article ID {article_unique_id} during regeneration.")
        article_body_md_with_links = process_link_placeholders(article_body_md_content_raw, YOUR_SITE_BASE_URL)
        # --- End Link Placeholder Processing ---

        article_body_html_output = markdown.markdown(
            article_body_md_with_links, # Use the version with <a href> tags from placeholders
            extensions=['fenced_code', 'tables', 'nl2br', 'sane_lists', 'extra']
        )
        # Unescape HTML entities that Markdown might have double-escaped, or that were in the original MD from LLM
        article_body_html_output = html.unescape(article_body_html_output)


        current_tags_list = article_data_content.get('generated_tags', [])
        article_tags_html_output = format_tags_html(current_tags_list)
        article_publish_datetime_obj = get_sort_key(article_data_content)
        relative_article_path_str_regen = f"articles/{article_slug_str}.html"

        if not YOUR_SITE_BASE_URL or YOUR_SITE_BASE_URL == '/':
            logger.error(f"Cannot generate canonical URL for {article_unique_id}: YOUR_SITE_BASE_URL is invalid.")
            page_canonical_url_regen = f"/{relative_article_path_str_regen.lstrip('/')}"
        else:
            page_canonical_url_regen = urljoin(YOUR_SITE_BASE_URL, relative_article_path_str_regen.lstrip('/'))

        raw_json_ld = seo_agent_results_data.get('generated_json_ld_raw', '{}')
        placeholder_in_json_ld = f"{BASE_URL_FOR_CANONICAL_MAIN.rstrip('/')}/articles/{{SLUG_PLACEHOLDER}}"
        final_json_ld_script_tag = seo_agent_results_data.get('generated_json_ld_full_script_tag', '<script type="application/ld+json">{}</script>')

        if placeholder_in_json_ld in raw_json_ld:
            final_json_ld_str = raw_json_ld.replace(placeholder_in_json_ld, page_canonical_url_regen)
            final_json_ld_script_tag = f'<script type="application/ld+json">\n{final_json_ld_str}\n</script>'
            logger.debug(f"Replaced JSON-LD canonical placeholder for {article_unique_id} with {page_canonical_url_regen}")
        elif seo_agent_results_data.get('generated_json_ld_full_script_tag'):
             logger.warning(f"JSON-LD canonical placeholder not found in raw JSON for {article_unique_id}. Using existing full script tag.")
        else:
            logger.warning(f"No raw JSON-LD or placeholder found for {article_unique_id}. Using default empty JSON-LD.")

        template_render_vars_regen = {
            'PAGE_TITLE': seo_agent_results_data.get('generated_title_tag', article_data_content.get('title')),
            'META_DESCRIPTION': seo_agent_results_data.get('generated_meta_description', ''),
            'AUTHOR_NAME': article_data_content.get('author', AUTHOR_NAME_DEFAULT),
            'META_KEYWORDS_LIST': current_tags_list,
            'CANONICAL_URL': page_canonical_url_regen,
            'SITE_NAME': YOUR_WEBSITE_NAME,
            'YOUR_WEBSITE_LOGO_URL': YOUR_WEBSITE_LOGO_URL,
            'IMAGE_URL': article_data_content.get('selected_image_url', ''),
            'IMAGE_ALT_TEXT': article_data_content.get('title', 'Article Image'),
            'PUBLISH_ISO_FOR_META': article_data_content.get('published_iso', datetime.now(timezone.utc).isoformat()),
            'JSON_LD_SCRIPT_BLOCK': final_json_ld_script_tag,
            'ARTICLE_HEADLINE': article_data_content.get('title'),
            'ARTICLE_SEO_H1': article_data_content.get('title'),
            'PUBLISH_DATE': article_publish_datetime_obj.strftime('%B %d, %Y') if article_publish_datetime_obj != datetime(1970,1,1,tzinfo=timezone.utc) else "Date Unknown",
            'ARTICLE_BODY_HTML': article_body_html_output,
            'ARTICLE_TAGS_HTML': article_tags_html_output,
            'SOURCE_ARTICLE_URL': article_data_content.get('link', '#'),
            'ARTICLE_TITLE': article_data_content.get('title'),
            'id': article_unique_id,
            'CURRENT_ARTICLE_ID': article_unique_id,
            'CURRENT_ARTICLE_TOPIC': article_data_content.get('topic', ''),
            'CURRENT_ARTICLE_TAGS_JSON': json.dumps(current_tags_list),
            'AUDIO_URL': article_data_content.get('audio_url')
        }
        if render_post_page(template_render_vars_regen, article_slug_str): # Pass slug for filename
            article_data_content['post_template_hash'] = current_post_template_hash
            proc_json_filepath_for_update = os.path.join(PROCESSED_JSON_DIR, f"{article_unique_id}.json")
            if not save_processed_data(proc_json_filepath_for_update, article_data_content):
                 logger.error(f"Failed to update template hash in {proc_json_filepath_for_update} after HTML regeneration.")
            return True
        return False
    return False


# --- Main Processing Function for Scraped Articles ---
def process_single_scraped_article(raw_json_filepath, existing_articles_summary_data, current_run_fully_processed_data_list):
    article_filename = os.path.basename(raw_json_filepath)
    logger.info(f"--- Processing article file: {article_filename} ---")
    article_data_content = load_article_data(raw_json_filepath)
    if not article_data_content or not isinstance(article_data_content, dict):
        logger.error(f"Failed load/invalid data {article_filename}. Skipping."); remove_scraped_file(raw_json_filepath); return None

    # --- Ensure 'id' is present early ---
    article_unique_id = article_data_content.get('id') or get_article_id(article_data_content, article_data_content.get('source_feed', 'unknown_feed'))
    article_data_content['id'] = article_unique_id
    final_processed_file_path = os.path.join(PROCESSED_JSON_DIR, f"{article_unique_id}.json")

    try:
        if os.path.exists(final_processed_file_path):
             logger.info(f"Article ID {article_unique_id} already fully processed (JSON exists). Skipping raw file."); remove_scraped_file(raw_json_filepath); return None

        publish_date_iso_str = article_data_content.get('published_iso')
        if publish_date_iso_str:
            publish_datetime_obj = get_sort_key(article_data_content)
            if publish_datetime_obj < (datetime.now(timezone.utc) - timedelta(days=ARTICLE_MAX_AGE_DAYS)):
                logger.info(f"Scraped article {article_unique_id} too old ({publish_datetime_obj.date()}). Skipping."); remove_scraped_file(raw_json_filepath); return None
        else: logger.warning(f"Scraped article {article_unique_id} missing publish date. Proceeding with caution.")

        logger.info(f"Finding image for article ID: {article_unique_id} ('{article_data_content.get('title', '')[:30]}...')")
        image_url = scrape_source_for_image(article_data_content.get('link')) or find_best_image(article_data_content.get('title', 'AI Technology News'), article_url_for_scrape=article_data_content.get('link'))
        if not image_url: logger.error(f"FATAL: No suitable image found for {article_unique_id}. Skipping."); remove_scraped_file(raw_json_filepath); return None
        article_data_content['selected_image_url'] = image_url

        current_title_lower_case = article_data_content.get('title', '').strip().lower()
        if not current_title_lower_case: logger.error(f"Article {article_unique_id} has empty title. Skipping."); remove_scraped_file(raw_json_filepath); return None

        for existing_summary in existing_articles_summary_data:
             if isinstance(existing_summary, dict) and \
                existing_summary.get('title','').strip().lower() == current_title_lower_case and \
                existing_summary.get('image_url') == image_url and \
                existing_summary.get('id') != article_unique_id :
                    logger.warning(f"Article {article_unique_id} appears DUPLICATE (Title & Image) of {existing_summary.get('id', 'N/A')}. Skipping."); remove_scraped_file(raw_json_filepath); return None
        logger.info(f"Article {article_unique_id} passed Title+Image duplicate check against all_articles.json.")


        article_data_content = run_filter_agent(article_data_content)
        if not article_data_content or article_data_content.get('filter_verdict') is None: logger.error(f"Filter Agent failed for {article_unique_id}. Skip."); remove_scraped_file(raw_json_filepath); return None
        filter_agent_verdict_data = article_data_content['filter_verdict']; importance_level = filter_agent_verdict_data.get('importance_level')
        if importance_level == "Boring": logger.info(f"Article {article_unique_id} classified 'Boring'. Skipping."); remove_scraped_file(raw_json_filepath); return None
        article_data_content['topic'] = filter_agent_verdict_data.get('topic', 'Other'); article_data_content['is_breaking'] = (importance_level == "Breaking")
        article_data_content['primary_keyword'] = filter_agent_verdict_data.get('primary_topic_keyword', article_data_content.get('title','Untitled'))
        logger.info(f"Article {article_unique_id} classified '{importance_level}' (Topic: {article_data_content['topic']}).")

        article_data_content = run_similarity_check_agent(article_data_content, PROCESSED_JSON_DIR, current_run_fully_processed_data_list)
        similarity_verdict = article_data_content.get('similarity_verdict', 'ERROR')
        if similarity_verdict != "OKAY" and not similarity_verdict.startswith("OKAY_"):
            logger.warning(f"Article {article_unique_id} flagged by similarity check: {similarity_verdict} (Similar to: {article_data_content.get('similar_article_id', 'N/A')}). Skipping.")
            remove_scraped_file(raw_json_filepath)
            return None
        logger.info(f"Article {article_unique_id} passed advanced similarity check (Verdict: {similarity_verdict}).")

        article_data_content = run_keyword_research_agent(article_data_content)
        if article_data_content.get('keyword_agent_error'): logger.warning(f"Keyword Research issue for {article_unique_id}: {article_data_content['keyword_agent_error']}")
        current_researched_keywords = article_data_content.setdefault('researched_keywords', []);
        if not current_researched_keywords and article_data_content.get('primary_keyword'): current_researched_keywords.append(article_data_content.get('primary_keyword'))
        final_tags = set(kw.strip() for kw in current_researched_keywords if kw and kw.strip())
        if article_data_content.get('primary_keyword'): final_tags.add(article_data_content['primary_keyword'].strip())
        article_data_content['generated_tags'] = list(final_tags)[:15]
        logger.info(f"Using {len(article_data_content['generated_tags'])} keywords as tags for {article_unique_id}.")

        # --- MODIFIED PART FOR SEO AGENT ---
        # run_seo_article_agent now modifies article_data_content in place
        article_data_content = run_seo_article_agent(article_data_content.copy()) # Pass a copy if run_seo_article_agent modifies it and you need original parts
        # --- END MODIFIED PART ---

        seo_agent_results_data = article_data_content.get('seo_agent_results')
        if not seo_agent_results_data or not isinstance(seo_agent_results_data, dict) or \
           not seo_agent_results_data.get('generated_article_body_md'):
            logger.error(f"SEO Agent failed for {article_unique_id} or returned invalid/incomplete results. SEO results: {seo_agent_results_data}. Skipping.")
            remove_scraped_file(raw_json_filepath)
            return None
        if article_data_content.get('seo_agent_error'):
            logger.warning(f"SEO Agent reported non-critical errors for {article_unique_id}: {article_data_content['seo_agent_error']}")

        final_title_for_slug = article_data_content.get('title', article_unique_id)
        temp_slug = re.sub(r'[^\w\s-]', '', str(final_title_for_slug).lower()).strip() # Ensure final_title_for_slug is string
        article_data_content['slug'] = re.sub(r'[-\s]+', '-', temp_slug)[:80] or article_unique_id
        logger.info(f"Generated slug for {article_unique_id}: {article_data_content['slug']}")

        num_tags = len(article_data_content.get('generated_tags', [])); calculated_trend_score = 0.0
        if importance_level == "Interesting": calculated_trend_score += 5.0
        elif importance_level == "Breaking": calculated_trend_score += 10.0
        calculated_trend_score += float(num_tags) * 0.5
        if publish_date_iso_str:
            publish_dt = get_sort_key(article_data_content); now_utc_time = datetime.now(timezone.utc)
            if publish_dt <= now_utc_time:
                days_old_val = (now_utc_time - publish_dt).total_seconds() / 86400.0
                if days_old_val <= ARTICLE_MAX_AGE_DAYS : calculated_trend_score += max(0.0, 1.0 - (days_old_val / float(ARTICLE_MAX_AGE_DAYS))) * 5.0
        article_data_content['trend_score'] = round(max(0.0, calculated_trend_score), 2)

        # --- CRITICAL CHECK BEFORE HTML REGENERATION ---
        if not article_data_content.get('id') or not article_data_content.get('slug'):
            logger.error(f"CRITICAL PRE-REGEN: Article {article_unique_id} is missing 'id' or 'slug'. Title: '{article_data_content.get('title')}', Slug: '{article_data_content.get('slug')}'. Aborting for this article.")
            remove_scraped_file(raw_json_filepath)
            return None
        if 'seo_agent_results' not in article_data_content or not isinstance(article_data_content.get('seo_agent_results'), dict) or not article_data_content.get('seo_agent_results', {}).get('generated_article_body_md'):
            logger.error(f"CRITICAL PRE-REGEN: Article {article_unique_id} 'seo_agent_results' or 'generated_article_body_md' is missing/invalid. Aborting for this article.")
            logger.debug(f"Full article_data_content before failing regen: {json.dumps(article_data_content, indent=2)}")
            remove_scraped_file(raw_json_filepath)
            return None
        # --- END CRITICAL CHECK ---

        if not regenerate_article_html_if_needed(article_data_content, force_regen=True):
            logger.error(f"Failed HTML render for new article {article_unique_id} via regenerate function. Skipping save.");
            remove_scraped_file(raw_json_filepath)
            return None

        relative_article_path_str = f"articles/{article_data_content['slug']}.html"
        page_canonical_url = urljoin(YOUR_SITE_BASE_URL, relative_article_path_str.lstrip('/')) if YOUR_SITE_BASE_URL and YOUR_SITE_BASE_URL != '/' else f"/{relative_article_path_str.lstrip('/')}"

        summary_for_site_list = {
            "id": article_unique_id,
            "title": article_data_content.get('title'),
            "link": relative_article_path_str,
            "published_iso": article_data_content.get('published_iso') or datetime.now(timezone.utc).isoformat(),
            "summary_short": seo_agent_results_data.get('generated_meta_description', ''),
            "image_url": article_data_content.get('selected_image_url'),
            "topic": article_data_content.get('topic', 'News'),
            "is_breaking": article_data_content.get('is_breaking', False),
            "tags": article_data_content.get('generated_tags', []),
            "audio_url": None,
            "trend_score": article_data_content.get('trend_score', 0)
        }
        article_data_content['audio_url'] = None;
        update_all_articles_json_file(summary_for_site_list) # This also saves the full article_data_content to its JSON

        payload_for_social_media = {
            "id": article_unique_id,
            "title": article_data_content.get('title'),
            "article_url": page_canonical_url,
            "image_url": article_data_content.get('selected_image_url'),
            "topic": article_data_content.get('topic'),
            "tags": article_data_content.get('generated_tags', []),
            "summary_short": summary_for_site_list.get('summary_short', '')
        }

        remove_scraped_file(raw_json_filepath)
        logger.info(f"--- Successfully processed scraped article: {article_unique_id} ---")
        return {"summary": summary_for_site_list, "social_post_data": payload_for_social_media, "full_data": article_data_content }

    except Exception as main_process_e:
         logger.exception(f"CRITICAL failure processing {article_unique_id} ({article_filename}): {main_process_e}")
         if os.path.exists(raw_json_filepath): remove_scraped_file(raw_json_filepath)
         return None

# --- Main Orchestration Logic ---
if __name__ == "__main__":
    run_start_timestamp = time.time()
    logger.info(f"--- === Dacoola AI News Orchestrator Starting Run ({datetime.now(timezone.utc).isoformat()}) === ---")
    ensure_directories()

    current_post_template_hash = get_file_hash(POST_TEMPLATE_FILE)
    if not current_post_template_hash:
        logger.error(f"CRITICAL: Could not hash template file: {POST_TEMPLATE_FILE}. HTML regeneration based on template changes will not work.")
    else:
        logger.info(f"Current post_template.html hash: {current_post_template_hash}")


    social_media_clients_glob = initialize_social_clients()
    fully_processed_article_ids_set = set(os.path.basename(f).replace('.json', '') for f in glob.glob(os.path.join(PROCESSED_JSON_DIR, '*.json')))
    logger.info(f"Found {len(fully_processed_article_ids_set)} fully processed article JSONs (scraped or Gyro).")

    scraper_tracker_ids_set = load_scraper_processed_ids()
    initial_ids_for_scraper_run = scraper_tracker_ids_set.union(fully_processed_article_ids_set)
    logger.info(f"Total initial IDs (from scraper history or already fully processed) passed to scraper: {len(initial_ids_for_scraper_run)}")

    logger.info("--- Stage 1: Checking/Regenerating HTML from Processed Data (Scraped & Gyro) ---")
    all_processed_json_files = glob.glob(os.path.join(PROCESSED_JSON_DIR, '*.json'))
    html_regenerated_count = 0
    if all_processed_json_files:
        logger.info(f"Found {len(all_processed_json_files)} processed JSON files to check for HTML regeneration.")
        for proc_json_filepath in all_processed_json_files:
            try:
                article_data_content = load_article_data(proc_json_filepath)
                if not article_data_content:
                    logger.warning(f"Skipping HTML regen for invalid/unreadable JSON: {os.path.basename(proc_json_filepath)}"); continue

                if regenerate_article_html_if_needed(article_data_content):
                    html_regenerated_count += 1
            except Exception as regen_exc:
                logger.exception(f"Error during HTML regeneration main loop for {os.path.basename(proc_json_filepath)}: {regen_exc}")
    logger.info(f"--- HTML Regeneration Stage Complete. Regenerated/Verified {html_regenerated_count} files. ---")


    logger.info("--- Stage 2: Running News Scraper ---")
    new_raw_articles_count = 0
    try: new_raw_articles_count = scrape_news(NEWS_FEED_URLS, initial_ids_for_scraper_run)
    except Exception as main_scrape_e: logger.exception(f"News scraper run failed: {main_scrape_e}")
    logger.info(f"News Scraper run completed. Found {new_raw_articles_count} new raw article files.")

    logger.info("--- Stage 3: Processing Newly Scraped Articles ---")
    all_articles_summary_data_for_run = load_all_articles_data_from_json()
    raw_json_files_to_process_list = sorted(glob.glob(os.path.join(SCRAPED_ARTICLES_DIR, '*.json')), key=os.path.getmtime, reverse=True)
    logger.info(f"Found {len(raw_json_files_to_process_list)} raw scraped articles to process.")

    current_run_fully_processed_data = []
    successfully_processed_scraped_count = 0; failed_or_skipped_scraped_count = 0
    social_media_payloads_for_posting_queue = []

    for raw_filepath in raw_json_files_to_process_list:
        article_potential_id = os.path.basename(raw_filepath).replace('.json', '')
        if article_potential_id in fully_processed_article_ids_set:
            logger.debug(f"Skipping raw file {article_potential_id}, as fully processed JSON already exists.");
            remove_scraped_file(raw_filepath);
            continue

        single_article_processing_result = process_single_scraped_article(
            raw_filepath,
            all_articles_summary_data_for_run,
            current_run_fully_processed_data
        )

        if single_article_processing_result and isinstance(single_article_processing_result, dict):
            successfully_processed_scraped_count += 1
            if "full_data" in single_article_processing_result and isinstance(single_article_processing_result["full_data"], dict):
               current_run_fully_processed_data.append(single_article_processing_result["full_data"])
            if "social_post_data" in single_article_processing_result and isinstance(single_article_processing_result["social_post_data"], dict):
                social_media_payloads_for_posting_queue.append(single_article_processing_result["social_post_data"])
                if single_article_processing_result["social_post_data"].get("id"):
                    fully_processed_article_ids_set.add(single_article_processing_result["social_post_data"]["id"])
        else:
            failed_or_skipped_scraped_count += 1
    logger.info(f"Scraped articles processing cycle complete. Success: {successfully_processed_scraped_count}, Failed/Skipped: {failed_or_skipped_scraped_count}")


    logger.info(f"--- Stage 3.5: Queuing Unposted Processed Articles (Last {MAX_AGE_FOR_SOCIAL_POST_HOURS}h) for Social Media ---")
    social_post_history_data = load_social_post_history()
    already_posted_social_ids = set(social_post_history_data.get('posted_articles', []))

    unposted_existing_processed_added_to_queue = 0
    now_for_age_check = datetime.now(timezone.utc)
    cutoff_time_for_social = now_for_age_check - timedelta(hours=MAX_AGE_FOR_SOCIAL_POST_HOURS)

    all_processed_json_files_for_social_check = glob.glob(os.path.join(PROCESSED_JSON_DIR, '*.json'))
    logger.info(f"Checking {len(all_processed_json_files_for_social_check)} total processed files for social media queue.")

    ids_already_in_current_scrape_queue = {p.get('id') for p in social_media_payloads_for_posting_queue if p.get('id')}

    for processed_json_file_path_check in all_processed_json_files_for_social_check:
        article_id_from_filename = os.path.basename(processed_json_file_path_check).replace('.json', '')

        if article_id_from_filename in ids_already_in_current_scrape_queue:
            logger.debug(f"Article {article_id_from_filename} was from recent scrape; already in social queue.")
            continue
        if article_id_from_filename in already_posted_social_ids:
            logger.debug(f"Article {article_id_from_filename} already in social post history. Skipping for queue.")
            continue

        processed_article_full_data = load_article_data(processed_json_file_path_check)
        if not processed_article_full_data:
            logger.warning(f"Could not load data from {processed_json_file_path_check} for social queue. Skipping.")
            continue

        published_iso_for_social = processed_article_full_data.get('published_iso')
        if not published_iso_for_social:
            logger.warning(f"Processed article {article_id_from_filename} missing 'published_iso'. Cannot check age for social posting. Skipping.")
            continue

        try:
            article_publish_dt = get_sort_key(processed_article_full_data)
            if article_publish_dt < cutoff_time_for_social:
                logger.debug(f"Processed article {article_id_from_filename} (published: {article_publish_dt.date()}) is older than {MAX_AGE_FOR_SOCIAL_POST_HOURS} hours (cutoff: {cutoff_time_for_social.strftime('%Y-%m-%d %H:%M:%S %Z')}). Skipping social post.")
                mark_article_as_posted_in_history(article_id_from_filename)
                continue
        except Exception as date_e:
            logger.warning(f"Error parsing date for {article_id_from_filename} for social age check: {date_e}. Skipping.")
            continue

        logger.info(f"Article ID {article_id_from_filename} (from processed_json) not in social history and IS recent enough. Adding to queue.")
        article_title_for_social = processed_article_full_data.get('title', 'Untitled')
        article_slug_for_social = processed_article_full_data.get('slug')
        if not article_slug_for_social:
            logger.warning(f"Processed article {article_id_from_filename} missing slug. Cannot form URL for social. Skipping."); continue

        relative_link_for_social = f"articles/{article_slug_for_social}.html"
        canonical_url_for_social = urljoin(YOUR_SITE_BASE_URL, relative_link_for_social.lstrip('/')) if YOUR_SITE_BASE_URL and YOUR_SITE_BASE_URL != '/' else f"/{relative_link_for_social.lstrip('/')}"

        seo_results_data_for_social = processed_article_full_data.get('seo_agent_results', {})
        summary_short_for_social = ''
        if isinstance(seo_results_data_for_social, dict):
            summary_short_for_social = seo_results_data_for_social.get('generated_meta_description', '')
        else:
             logger.warning(f"Article {article_id_from_filename} 'seo_agent_results' is not a dict. Meta description for social will be empty.")

        payload = {
            "id": article_id_from_filename, "title": article_title_for_social,
            "article_url": canonical_url_for_social, "image_url": processed_article_full_data.get('selected_image_url'),
            "topic": processed_article_full_data.get('topic'), "tags": processed_article_full_data.get('generated_tags', []),
            "summary_short": summary_short_for_social
        }
        social_media_payloads_for_posting_queue.append(payload)
        unposted_existing_processed_added_to_queue += 1

    if unposted_existing_processed_added_to_queue > 0:
        logger.info(f"Added {unposted_existing_processed_added_to_queue} recent, unposted items from processed_json to social media queue.")

    current_run_date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    twitter_limit_file_date, twitter_posts_made_today = _read_tweet_tracker()
    if twitter_limit_file_date != current_run_date_str:
        logger.info(f"New day ({current_run_date_str}) for Twitter. Resetting daily post count.")
        twitter_posts_made_today = 0; _write_tweet_tracker(current_run_date_str, 0)
    logger.info(f"Twitter posts made today before this social posting cycle: {twitter_posts_made_today} (Daily Limit: {DAILY_TWEET_LIMIT})")

    if social_media_payloads_for_posting_queue:
        logger.info(f"--- Stage 4: Attempting to post {len(social_media_payloads_for_posting_queue)} total articles to Social Media ---")
        final_make_webhook_payloads = []

        def get_publish_date_for_social_sort(payload):
            article_id = payload.get('id')
            if not article_id: return datetime(1970, 1, 1, tzinfo=timezone.utc)
            filepath = os.path.join(PROCESSED_JSON_DIR, f"{article_id}.json")
            data = load_article_data(filepath)
            return get_sort_key(data or {})

        social_media_payloads_for_posting_queue.sort(key=get_publish_date_for_social_sort, reverse=True)
        logger.info("Social media queue sorted by publish date (newest first).")

        articles_posted_this_run_count = 0
        for social_payload_item in social_media_payloads_for_posting_queue:
            article_id_for_social_post = social_payload_item.get('id')
            current_social_history = load_social_post_history()
            if article_id_for_social_post in current_social_history.get('posted_articles', []):
                logger.info(f"Article {article_id_for_social_post} was already marked in social history just before its posting turn. Skipping.")
                continue

            logger.info(f"Preparing to post article ID: {article_id_for_social_post} ('{social_payload_item.get('title', '')[:40]}...')")
            platforms_to_attempt_post = ["bluesky", "reddit"]

            if social_media_clients_glob.get("twitter_client"):
                _, current_twitter_posts_made_today = _read_tweet_tracker()
                if current_twitter_posts_made_today < DAILY_TWEET_LIMIT:
                    platforms_to_attempt_post.append("twitter")
                    logger.info(f"Article {article_id_for_social_post} WILL be attempted on Twitter. (Daily count: {current_twitter_posts_made_today}/{DAILY_TWEET_LIMIT})")
                else:
                    logger.info(f"Daily Twitter limit ({DAILY_TWEET_LIMIT}) reached. Twitter SKIPPED for article ID: {article_id_for_social_post}")
            else:
                logger.debug("Twitter client not available for social posting.")


            run_social_media_poster(
                social_payload_item,
                social_media_clients_glob,
                platforms_to_post=tuple(platforms_to_attempt_post)
            )
            articles_posted_this_run_count +=1

            if "twitter" in platforms_to_attempt_post and social_media_clients_glob.get("twitter_client"):
                twitter_limit_file_date_after_post, twitter_posts_made_today_after_post = _read_tweet_tracker()
                if twitter_limit_file_date_after_post == current_run_date_str:
                    _write_tweet_tracker(current_run_date_str, twitter_posts_made_today_after_post) # Already incremented by run_social_media_poster
                    logger.info(f"Twitter daily post count for {current_run_date_str} confirmed after attempt for {article_id_for_social_post}.")
                else:
                    logger.warning(f"Date changed mid-run during Twitter post logic. Tracker reset for new date {twitter_limit_file_date_after_post}.")
                    _write_tweet_tracker(twitter_limit_file_date_after_post, 1 if twitter_posts_made_today_after_post > 0 else 0)


            if MAKE_WEBHOOK_URL: final_make_webhook_payloads.append(social_payload_item)

            if articles_posted_this_run_count < len(social_media_payloads_for_posting_queue):
                 post_delay_seconds = 10
                 logger.debug(f"Sleeping for {post_delay_seconds} seconds before next social post...")
                 time.sleep(post_delay_seconds)

        logger.info(f"Social media posting cycle finished. Attempted to post {articles_posted_this_run_count} articles.")
        if MAKE_WEBHOOK_URL and final_make_webhook_payloads:
            logger.info(f"--- Sending {len(final_make_webhook_payloads)} items to Make.com Webhook ---")
            if send_make_webhook(MAKE_WEBHOOK_URL, final_make_webhook_payloads): logger.info("Batched Make.com webhook sent successfully.")
            else: logger.error("Batched Make.com webhook failed.")
    else:
        logger.info("No new or unposted recent articles queued for social media posting in this run.")

    logger.info("--- Stage 5: Generating Sitemap ---")
    if not YOUR_SITE_BASE_URL or YOUR_SITE_BASE_URL == '/': logger.error("Sitemap generation SKIPPED: YOUR_SITE_BASE_URL not set or invalid.");
    else:
        try: run_sitemap_generator(); logger.info("Sitemap generation completed successfully.")
        except Exception as main_sitemap_e: logger.exception(f"Sitemap generation failed: {main_sitemap_e}")

    run_end_timestamp = time.time()
    logger.info(f"--- === Dacoola AI News Orchestrator Run Finished ({run_end_timestamp - run_start_timestamp:.2f} seconds) === ---")