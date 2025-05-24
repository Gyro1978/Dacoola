# src/main.py
# Main orchestrator for the Dacoola AI News Generation Pipeline.
# This script coordinates scraping, content processing by various AI agents,
# HTML generation, sitemap updates, and social media posting.

# --- !! Path Setup - Must be at the very top !! ---
import sys
import random
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
import hashlib
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, quote
import markdown # For Markdown to HTML conversion

# --- Import Sitemap Generator ---
try:
    from generate_sitemap import generate_sitemap as run_sitemap_generator
except ImportError as e:
    temp_log_msg = f"FATAL IMPORT ERROR: Could not import sitemap generator: {e}."
    print(temp_log_msg); logging.critical(temp_log_msg); sys.exit(1)

# --- Import Agent and Scraper Functions ---
try:
    from src.agents.research_agent import run_research_agent
    from src.agents.filter_news_agent import run_filter_agent
    from src.agents.similarity_check_agent import run_similarity_check_agent
    from src.agents.keyword_generator_agent import run_keyword_generator_agent
    from src.agents.title_generator_agent import run_title_generator_agent
    from src.agents.description_generator_agent import run_description_generator_agent
    from src.agents.markdown_generator_agent import run_markdown_generator_agent
    from src.agents.section_writer_agent import run_section_writer_agent
    from src.agents.article_review_agent import run_article_review_agent
    from src.agents.seo_review_agent import run_seo_review_agent
    from src.social.social_media_poster import (
        initialize_social_clients, run_social_media_poster,
        load_post_history as load_social_post_history,
        mark_article_as_posted_in_history
    )
except ImportError as e:
     print(f"FATAL IMPORT ERROR in main.py (agents/scrapers/social): {e}")
     try: logging.critical(f"FATAL IMPORT ERROR (agents/scrapers/social): {e}")
     except NameError: pass 
     sys.exit(1)

# --- Load Environment Variables ---
dotenv_path = os.path.join(PROJECT_ROOT_FOR_PATH, '.env'); load_dotenv(dotenv_path=dotenv_path) # Initial load for other vars
AUTHOR_NAME_DEFAULT = os.getenv('AUTHOR_NAME', 'Dacoola AI Team')
YOUR_WEBSITE_NAME = os.getenv('WEBSITE_NAME', 'Dacoola')
YOUR_WEBSITE_LOGO_URL = os.getenv('WEBSITE_LOGO_URL', 'https://ibb.co/tpKjc98q')

# Explicitly get YOUR_SITE_BASE_URL from environment, this is what GitHub Actions sets
# Use a distinct variable name first to avoid confusion with the later script variable
env_your_site_base_url = os.getenv('YOUR_SITE_BASE_URL')
dotenv_path = os.path.join(PROJECT_ROOT_FOR_PATH, '.env') # Ensure dotenv_path is defined before use

if env_your_site_base_url:
    raw_base_url = env_your_site_base_url
    # Logger is not configured yet, print statements for this initial phase were removed
    # Logger calls will be made after logger initialization for these.
else:
    # Fallback if YOUR_SITE_BASE_URL is not in env (e.g. local run without .env properly set)
    raw_base_url = os.getenv('WEBSITE_BASE_URL') # Try WEBSITE_BASE_URL from env first
    if not raw_base_url: # If still not found, try .env
        # load_dotenv(dotenv_path=dotenv_path) # Already called initially
        raw_base_url = os.getenv('WEBSITE_BASE_URL', 'https://dacoolaa.netlify.app') # Default if not in .env

# The main script variable for the processed base URL
YOUR_SITE_BASE_URL_SCRIPT_VAR = (raw_base_url.rstrip('/') + '/') if raw_base_url and raw_base_url != 'https://dacoolaa.netlify.app' else ''
if not YOUR_SITE_BASE_URL_SCRIPT_VAR and raw_base_url == 'https://dacoolaa.netlify.app': # Handle case where default is used
    YOUR_SITE_BASE_URL_SCRIPT_VAR = 'https://dacoolaa.netlify.app/'


# Ensure BASE_URL_FOR_CANONICAL_MAIN uses the new variable
BASE_URL_FOR_CANONICAL_MAIN = YOUR_SITE_BASE_URL_SCRIPT_VAR

MAKE_WEBHOOK_URL = os.getenv('MAKE_INSTAGRAM_WEBHOOK_URL', None)
DAILY_TWEET_LIMIT = int(os.getenv('DAILY_TWEET_LIMIT', '3'))
MAX_AGE_FOR_SOCIAL_POST_HOURS = int(os.getenv('MAX_AGE_FOR_SOCIAL_POST_HOURS', '24'))
MAX_HOME_PAGE_ARTICLES = int(os.getenv('MAX_HOME_PAGE_ARTICLES', '20'))


# --- Setup Logging ---
log_file_path = os.path.join(PROJECT_ROOT_FOR_PATH, 'dacola.log')
try:
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    log_handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file_path, encoding='utf-8', mode='a') 
    ]
except OSError as e:
    print(f"Log setup warning: Could not create/access log file directory for {log_file_path}. Error: {e}. Logging to console only.")
    log_handlers = [logging.StreamHandler(sys.stdout)]

logging.basicConfig(
    level=logging.DEBUG, 
    format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=log_handlers,
    force=True 
)
logger = logging.getLogger('main_orchestrator')

# Log the determined base URL after logger is initialized
if env_your_site_base_url: # This was the variable holding the direct result of os.getenv('YOUR_SITE_BASE_URL')
    logger.info(f"Successfully read YOUR_SITE_BASE_URL from environment: {env_your_site_base_url}")
elif os.getenv('WEBSITE_BASE_URL') and os.getenv('WEBSITE_BASE_URL') != 'https://dacoolaa.netlify.app': # WEBSITE_BASE_URL was found in env
    logger.info(f"YOUR_SITE_BASE_URL not in env. Successfully read WEBSITE_BASE_URL from environment as fallback: {os.getenv('WEBSITE_BASE_URL')}")
elif raw_base_url and raw_base_url != 'https://dacoolaa.netlify.app': # WEBSITE_BASE_URL was found in .env
    logger.info(f"YOUR_SITE_BASE_URL and WEBSITE_BASE_URL not in env. Loaded WEBSITE_BASE_URL from .env file: {raw_base_url}")
elif raw_base_url == 'https://dacoolaa.netlify.app': # Default was used
    logger.warning("Neither YOUR_SITE_BASE_URL nor WEBSITE_BASE_URL found in environment or .env. Using default: https://dacoolaa.netlify.app")
# else: # This case should ideally not be reached if raw_base_url is always set to something.
    # logger.debug("Initial base URL check: Undetermined state or only default was available.")

if not YOUR_SITE_BASE_URL_SCRIPT_VAR or YOUR_SITE_BASE_URL_SCRIPT_VAR == '/':
    logger.error(f"CRITICAL: Site base URL is not properly set (derived value: '{YOUR_SITE_BASE_URL_SCRIPT_VAR}'). Check environment variables ('YOUR_SITE_BASE_URL' or 'WEBSITE_BASE_URL') or .env. Canonical URLs and sitemap will be incorrect.")
else:
    logger.info(f"Using site base URL for sitemap/canonicals: {YOUR_SITE_BASE_URL_SCRIPT_VAR}")
if not YOUR_WEBSITE_LOGO_URL:
    logger.warning("WEBSITE_LOGO_URL not set. Default or placeholder might be used in templates.")


# --- Configuration ---
DATA_DIR_MAIN = os.path.join(PROJECT_ROOT_FOR_PATH, 'data')
RAW_WEB_RESEARCH_OUTPUT_DIR = os.path.join(DATA_DIR_MAIN, 'raw_web_research')
PROCESSED_JSON_DIR = os.path.join(DATA_DIR_MAIN, 'processed_json')
PUBLIC_DIR = os.path.join(PROJECT_ROOT_FOR_PATH, 'public')
OUTPUT_HTML_DIR = os.path.join(PUBLIC_DIR, 'articles')
TEMPLATE_DIR = os.path.join(PROJECT_ROOT_FOR_PATH, 'templates')
ALL_ARTICLES_FILE = os.path.join(PUBLIC_DIR, 'all_articles.json')
ARTICLE_MAX_AGE_DAYS_FILTER = 30
TWITTER_DAILY_LIMIT_FILE = os.path.join(DATA_DIR_MAIN, 'twitter_daily_limit.json')
POST_TEMPLATE_FILE = os.path.join(TEMPLATE_DIR, 'post_template.html')


# --- Jinja2 Setup ---
try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    def escapejs_filter(value):
        if value is None: return ''
        value = str(value)
        value = value.replace('\\', '\\\\').replace("'", "\\'").replace('"', '\\"').replace('/', '\\/')
        value = value.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
        value = value.replace('<', '\\u003c').replace('>', '\\u003e')
        value = value.replace('\b', '\\b').replace('\f', '\\f')
        return value

    if not os.path.isdir(TEMPLATE_DIR):
        logger.critical(f"Jinja2 template directory not found: {TEMPLATE_DIR}. Exiting.")
        sys.exit(1)
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(['html', 'xml']),
        trim_blocks=True, 
        lstrip_blocks=True  
    )
    env.filters['escapejs'] = escapejs_filter 
    logger.info(f"Jinja2 environment loaded successfully from {TEMPLATE_DIR}")
except ImportError:
    logger.critical("Jinja2 library not found. HTML generation will fail. Please install Jinja2. Exiting.")
    sys.exit(1)
except Exception as e:
    logger.exception(f"CRITICAL: Failed to initialize Jinja2 environment. Exiting: {e}")
    sys.exit(1)

# --- Helper Functions ---
current_post_template_hash = None 

def ensure_directories():
    dirs_to_create = [
        DATA_DIR_MAIN, RAW_WEB_RESEARCH_OUTPUT_DIR, PROCESSED_JSON_DIR,
        PUBLIC_DIR, OUTPUT_HTML_DIR, TEMPLATE_DIR
    ]
    try:
        for d_path in dirs_to_create:
            os.makedirs(d_path, exist_ok=True)
        logger.info("Ensured all core directories exist.")
    except OSError as e:
        logger.exception(f"CRITICAL OS ERROR: Could not create directory {getattr(e, 'filename', 'N/A')}: {getattr(e, 'strerror', str(e))}. Exiting.")
        sys.exit(1)

def get_file_hash(filepath):
    hasher = hashlib.sha256()
    if not os.path.exists(filepath):
        logger.error(f"File NOT FOUND for hashing: {filepath}")
        return None
    try:
        with open(filepath, 'rb') as f:
            buf = f.read(65536) 
            while len(buf) > 0:
                hasher.update(buf)
                buf = f.read(65536)
        return hasher.hexdigest()
    except Exception as e:
        logger.error(f"Error hashing file {filepath}: {e}")
        return None

def load_article_data(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.debug(f"File not found during load_article_data: {filepath}")
        return None
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from file: {filepath}.")
        return None
    except Exception as e:
        logger.error(f"Unexpected error loading article data from {filepath}: {e}")
        return None

def save_processed_data(filepath, article_data_to_save):
    try:
         os.makedirs(os.path.dirname(filepath), exist_ok=True)
         if current_post_template_hash: 
             article_data_to_save['post_template_hash'] = current_post_template_hash
         else:
             logger.warning(f"current_post_template_hash is None. Template hash not saved in JSON for {os.path.basename(filepath)}.")
         
         with open(filepath, 'w', encoding='utf-8') as f:
             json.dump(article_data_to_save, f, indent=4, ensure_ascii=False)
         logger.info(f"Successfully saved processed data: {os.path.basename(filepath)}")
         return True
    except Exception as e:
        logger.error(f"Failed to save processed data to {os.path.basename(filepath)}: {e}")
        return False

def format_tags_html(tags_list_for_html):
    if not tags_list_for_html or not isinstance(tags_list_for_html, list):
        return ""
    try:
        tag_html_links = []
        base_url_for_tags = YOUR_SITE_BASE_URL_SCRIPT_VAR.rstrip('/') + '/' if YOUR_SITE_BASE_URL_SCRIPT_VAR and YOUR_SITE_BASE_URL_SCRIPT_VAR != '/' else '/'
        
        for tag_item in tags_list_for_html:
            safe_tag_item_for_url = quote(str(tag_item))
            escaped_tag_item_for_display = html.escape(str(tag_item))
            
            tag_page_url = urljoin(base_url_for_tags, f"topic.html?name={safe_tag_item_for_url}")
            tag_html_links.append(f'<a href="{tag_page_url}" class="tag-link">{escaped_tag_item_for_display}</a>')
        return ", ".join(tag_html_links)
    except Exception as e:
        logger.error(f"Error formatting tags to HTML. Input: {tags_list_for_html}. Error: {e}")
        return "" 

def get_sort_key(article_dict_item):
    fallback_past_date = datetime(1970, 1, 1, tzinfo=timezone.utc)
    if not isinstance(article_dict_item, dict): return fallback_past_date 

    date_iso_str = article_dict_item.get('published_iso')
    if not date_iso_str or not isinstance(date_iso_str, str):
        return fallback_past_date
    try:
        if date_iso_str.endswith('Z'):
            date_iso_str = date_iso_str[:-1] + '+00:00'
        dt_obj = datetime.fromisoformat(date_iso_str)
        return dt_obj.replace(tzinfo=timezone.utc) if dt_obj.tzinfo is None else dt_obj
    except ValueError:
        logger.warning(f"Could not parse date '{date_iso_str}' for article ID {article_dict_item.get('id', 'N/A')}. Using fallback date.")
        return fallback_past_date

def _read_tweet_tracker():
    today_date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    try:
        if os.path.exists(TWITTER_DAILY_LIMIT_FILE):
            with open(TWITTER_DAILY_LIMIT_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if data.get('date') == today_date_str:
                return data['date'], data.get('count', 0)
        return today_date_str, 0
    except Exception as e:
        logger.error(f"Error reading Twitter daily limit tracker: {e}. Resetting count for today.")
        return today_date_str, 0

def _write_tweet_tracker(date_str, count):
    try:
        os.makedirs(os.path.dirname(TWITTER_DAILY_LIMIT_FILE), exist_ok=True)
        with open(TWITTER_DAILY_LIMIT_FILE, 'w', encoding='utf-8') as f:
            json.dump({'date': date_str, 'count': count}, f, indent=2)
        logger.info(f"Twitter daily limit tracker updated: Date {date_str}, Count {count}")
    except Exception as e:
        logger.error(f"Error writing Twitter daily limit tracker: {e}")

def send_make_webhook(webhook_url, data_payload):
    if not webhook_url or "your_make_instagram_webhook_url_here" in webhook_url:
        logger.warning("Make.com webhook URL is missing or set to default. Skipping webhook send.")
        return False
    if not data_payload:
        logger.warning("No data payload provided for Make.com webhook. Skipping.")
        return False
    payload_to_send = {"articles": data_payload} if isinstance(data_payload, list) else data_payload
    log_id_info_str = f"batch of {len(data_payload)} articles" if isinstance(data_payload, list) else f"article ID: {data_payload.get('id', 'N/A')}"
    try:
        response = requests.post(webhook_url, headers={'Content-Type': 'application/json'}, json=payload_to_send, timeout=30)
        response.raise_for_status() 
        logger.info(f"Successfully sent {log_id_info_str} to Make.com webhook.")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send {log_id_info_str} to Make.com webhook: {e}")
        return False

def render_post_page(template_variables_dict, slug_base_str):
    try:
        template = env.get_template('post_template.html')
        # The ARTICLE_BODY_HTML is now expected to be fully pre-assembled by main.py
        html_content_output = template.render(template_variables_dict)
        
        safe_filename_str = slug_base_str 
        safe_filename_str = re.sub(r'[<>:"/\\|?*%\.]+', '', safe_filename_str).strip().lower().replace(' ', '-')
        safe_filename_str = re.sub(r'-+', '-', safe_filename_str).strip('-')[:80] 
        if not safe_filename_str: 
            safe_filename_str = template_variables_dict.get('id', f"article-fallback-{int(time.time())}")
            logger.warning(f"Slug for {template_variables_dict.get('id','N/A')} was empty after sanitization, using fallback: {safe_filename_str}")

        output_html_path = os.path.join(OUTPUT_HTML_DIR, f"{safe_filename_str}.html")
        os.makedirs(os.path.dirname(output_html_path), exist_ok=True)
        with open(output_html_path, 'w', encoding='utf-8') as f:
            f.write(html_content_output)
        logger.info(f"Successfully rendered HTML page: {os.path.basename(output_html_path)}")
        return output_html_path
    except Exception as e:
        logger.exception(f"CRITICAL ERROR during HTML page rendering for ID {template_variables_dict.get('id','N/A')}, slug_base: '{slug_base_str}': {e}")
        return None

def load_all_articles_data_from_json():
    if not os.path.exists(ALL_ARTICLES_FILE):
        logger.info(f"{ALL_ARTICLES_FILE} not found. Returning empty list.")
        return []
    try:
        with open(ALL_ARTICLES_FILE, 'r', encoding='utf-8') as f:
            data_content = json.load(f)
        if isinstance(data_content, dict) and isinstance(data_content.get('articles'), list):
            return data_content['articles']
        logger.warning(f"{ALL_ARTICLES_FILE} has an invalid structure. Expected {{'articles': [...]}}. Returning empty list.")
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from {ALL_ARTICLES_FILE}. Returning empty list.")
    except Exception as e:
        logger.error(f"Unexpected error loading {ALL_ARTICLES_FILE}: {e}. Returning empty list.")
    return []

def update_all_articles_json_file(new_article_summary_info):
    current_articles_list_data = load_all_articles_data_from_json()
    article_unique_id = new_article_summary_info.get('id')
    if not article_unique_id:
        logger.error("Cannot update all_articles.json: new article summary is missing 'id'.")
        return
    articles_dict = {art.get('id'): art for art in current_articles_list_data if isinstance(art, dict) and art.get('id')}
    articles_dict[article_unique_id] = new_article_summary_info 
    updated_articles_list = sorted(list(articles_dict.values()), key=get_sort_key, reverse=True)
    trimmed_articles_list = updated_articles_list[:MAX_HOME_PAGE_ARTICLES]
    final_data_to_save_to_json_obj = {"articles": trimmed_articles_list}
    try:
        json_string_to_write = json.dumps(final_data_to_save_to_json_obj, indent=2, ensure_ascii=False)
        try:
            json.loads(json_string_to_write) 
            logger.debug(f"JSON content for {ALL_ARTICLES_FILE} has been validated before writing.")
        except json.JSONDecodeError as jde:
            logger.error(f"CRITICAL: Generated content for {ALL_ARTICLES_FILE} is NOT VALID JSON: {jde}. Aborting save. Data Snippet: {json_string_to_write[:500]}")
            return 
        with open(ALL_ARTICLES_FILE, 'w', encoding='utf-8') as f:
            f.write(json_string_to_write)
        logger.info(f"Successfully updated {os.path.basename(ALL_ARTICLES_FILE)}. Total articles in source list: {len(updated_articles_list)}, Saved to file: {len(trimmed_articles_list)}.")
    except TypeError as te: 
        logger.error(f"CRITICAL: TypeError during JSON serialization for {ALL_ARTICLES_FILE}: {te}. Aborting save.")
    except Exception as e:
        logger.error(f"Failed to save updated {os.path.basename(ALL_ARTICLES_FILE)}: {e}")

def slugify(text_to_slugify):
    if not text_to_slugify: return "untitled-article"
    slug = str(text_to_slugify).lower().strip()
    slug = slug.replace("’", "").replace("'", "") 
    slug = re.sub(r'[^\w\s-]', '', slug) 
    slug = re.sub(r'[\s-]+', '-', slug) 
    slug = slug.strip('-')[:70] 
    return slug or "untitled-article" 

def process_link_placeholders(text_input, base_site_url_param): # Parameter name is fine, it receives YOUR_SITE_BASE_URL_SCRIPT_VAR
    if not text_input: return ""
    if not base_site_url_param or base_site_url_param == '/':
        logger.warning(f"Base site URL ('{base_site_url_param}') is invalid for link placeholder processing. Using relative links.")
        base_site_url_param = "/"

    def replace_internal(match):
        link_text = match.group(1).strip()
        target_identifier = match.group(2).strip() if match.group(2) else None
        href_val = ""
        final_link_text_html = html.escape(link_text)
        if target_identifier:
            if target_identifier.endswith(".html") or ('/' in target_identifier) or (target_identifier.count('-') > 1 and ' ' not in target_identifier) :
                if target_identifier.startswith("articles/"):
                     href_val = urljoin(base_site_url_param, target_identifier.lstrip('/'))
                else: 
                     href_val = urljoin(base_site_url_param, f"articles/{target_identifier.lstrip('/')}")
                     if not href_val.endswith(".html"): href_val += ".html"
            else: 
                href_val = urljoin(base_site_url_param, f"topic.html?name={quote(target_identifier)}")
        else: 
            slugified_link_text_for_topic = slugify(link_text) 
            href_val = urljoin(base_site_url_param, f"topic.html?name={quote(slugified_link_text_for_topic)}")
        logger.debug(f"Internal link processed: Text='{link_text}', Target='{target_identifier}', Href='{href_val}'")
        return f'<a href="{html.escape(href_val)}" class="internal-link">{final_link_text_html}</a>'

    processed_text_internal = re.sub(r'\[\[\s*(.+?)\s*(?:\|\s*(.+?)\s*)?\]\]', replace_internal, text_input)
    
    def replace_external(match):
        link_text_ext = match.group(1).strip()
        url_ext = match.group(2).strip()
        final_link_text_ext_html = html.escape(link_text_ext)
        logger.debug(f"External link processed: Text='{link_text_ext}', URL='{url_ext}'")
        return f'<a href="{html.escape(url_ext)}" target="_blank" rel="noopener noreferrer" class="external-link">{final_link_text_ext_html}</a>'
    
    return re.sub(r'\(\(\s*(.+?)\s*\|\s*(https?://.+?)\s*\)\)', replace_external, processed_text_internal)


def generate_json_ld(article_data, canonical_url_param):
    title = article_data.get('generated_seo_h1', article_data.get('title', 'Untitled Article'))
    description = article_data.get('generated_meta_description', 'No description available.')
    image_url = article_data.get('selected_image_url', '')
    published_time_iso = article_data.get('published_iso', datetime.now(timezone.utc).isoformat())
    author_name = article_data.get('author', AUTHOR_NAME_DEFAULT)
    publisher_name = YOUR_WEBSITE_NAME 
    publisher_logo_url = YOUR_WEBSITE_LOGO_URL 

    json_ld_data = {
        "@context": "https://schema.org",
        "@type": "NewsArticle", 
        "headline": title,
        "description": description,
        "image": [image_url] if image_url else [], 
        "datePublished": published_time_iso,
        "dateModified": article_data.get('last_modified_iso', published_time_iso), 
        "author": {"@type": "Person", "name": author_name},
        "publisher": {
            "@type": "Organization",
            "name": publisher_name,
            "logo": {"@type": "ImageObject", "url": publisher_logo_url} if publisher_logo_url else None
        },
        "mainEntityOfPage": {"@type": "WebPage", "@id": canonical_url_param}
    }
    if not publisher_logo_url: del json_ld_data["publisher"]["logo"]
    raw_json_ld_str = json.dumps(json_ld_data, indent=2, ensure_ascii=False)
    full_script_tag = f'<script type="application/ld+json">\n{raw_json_ld_str}\n</script>'
    return raw_json_ld_str, full_script_tag

def assemble_article_html_body(article_plan_with_content, base_site_url, article_id_for_log):
    """
    Assembles the final HTML body from section content, distinguishing Markdown from HTML snippets.
    """
    assembled_html_body_parts = []
    pure_markdown_parts = [] # For storing raw markdown of non-snippet sections

    for section_item in article_plan_with_content.get('sections', []):
        section_content = section_item.get('generated_content_for_section', '') # Content from SectionWriter
        if not section_content:
            logger.warning(f"No content for section type '{section_item.get('section_type')}' in article {article_id_for_log}. Skipping section in HTML.")
            continue

        is_html_snippet = section_item.get('is_html_snippet', False)

        if is_html_snippet:
            # This content is already HTML from SectionWriter.
            # It should NOT contain [[link]] or ((link)) placeholders.
            # If it does, process_link_placeholders would break it.
            # SectionWriter is prompted to use HTML links for HTML snippets.
            # Also, ArticleReviewAgent should flag if section_writer failed to produce HTML for a snippet.
            assembled_html_body_parts.append(section_content)
            # For 'full_generated_article_body_md', we could add a placeholder for HTML snippets
            # or the original Markdown plan for that snippet if it's useful for other agents.
            # For now, full_generated_article_body_md will primarily be the textual Markdown.
            pure_markdown_parts.append(f"<!-- HTML SNIPPET: {section_item.get('section_type')} -->\n<!-- HEADING_HOLDER_FOR_HTML_SNIPPET: {html.escape(section_item.get('heading_text',''))} -->\n")
        else:
            # This content is Markdown.
            pure_markdown_parts.append(section_content) # Store original Markdown
            md_with_links = process_link_placeholders(section_content, base_site_url)
            try:
                # Convert Markdown to HTML, including handling of headings
                html_part = html.unescape(markdown.markdown(md_with_links, extensions=['fenced_code', 'tables', 'sane_lists', 'extra', 'nl2br']))
                assembled_html_body_parts.append(html_part)
            except Exception as md_exc:
                logger.error(f"Error converting Markdown section to HTML for article {article_id_for_log}, type {section_item.get('section_type')}: {md_exc}")
                assembled_html_body_parts.append(f"<p><strong>Error rendering this section ({section_item.get('section_type')}).</strong></p>")
    
    final_html_body = "\n".join(assembled_html_body_parts).strip()
    final_pure_markdown_body = "\n\n".join(pure_markdown_parts).strip()
    
    return final_html_body, final_pure_markdown_body


def regenerate_article_html_if_needed(article_data_content, force_regen=False):
    global current_post_template_hash 
    if not current_post_template_hash:
        logger.error("CRITICAL: current_post_template_hash is None. Cannot check for HTML regeneration needs.")
        return False

    article_unique_id = article_data_content.get('id')
    article_slug_str = article_data_content.get('slug')

    if not article_unique_id or not article_slug_str:
        logger.error(f"Skipping HTML regeneration: missing 'id' or 'slug' in article data for title '{article_data_content.get('title', 'Unknown article')}'")
        return False

    expected_html_file_path = os.path.join(OUTPUT_HTML_DIR, f"{article_slug_str}.html")
    stored_template_hash = article_data_content.get('post_template_hash')
    needs_regeneration = False

    if not os.path.exists(expected_html_file_path):
        needs_regeneration = True
        logger.info(f"HTML file missing for slug '{article_slug_str}'. Regeneration needed.")
    elif force_regen:
        needs_regeneration = True
        logger.info(f"Forcing HTML regeneration for slug '{article_slug_str}'.")
    elif stored_template_hash != current_post_template_hash:
        needs_regeneration = True
        logger.info(f"Template hash changed for slug '{article_slug_str}'. Old: {stored_template_hash}, New: {current_post_template_hash}. Regeneration needed.")

    if needs_regeneration:
        logger.info(f"Proceeding with HTML regeneration for article ID: {article_unique_id} (Slug: {article_slug_str})...")
        
        article_plan_for_regen = article_data_content.get('article_plan')
        if not article_plan_for_regen or not isinstance(article_plan_for_regen.get('sections'), list):
            logger.error(f"Cannot regenerate HTML for {article_unique_id}: 'article_plan' or its 'sections' are missing/invalid in the stored JSON.")
            # Check if 'article_body_html_for_review' exists from a previous full run
            # This would be the case if only the template changed, but not the content.
            if 'article_body_html_for_review' in article_data_content:
                logger.info(f"Found 'article_body_html_for_review' for {article_unique_id}. Using this pre-assembled HTML for regeneration due to missing detailed plan.")
                final_article_body_html = article_data_content['article_body_html_for_review']
            else:
                # Last resort: try to use 'full_generated_article_body_md' if it's all we have
                # This might lead to incorrect rendering if it contains mixed HTML/Markdown.
                logger.warning(f"Regenerating HTML for {article_unique_id} using 'full_generated_article_body_md' as fallback due to missing detailed plan. Rendering issues may occur if it contains pre-rendered HTML snippets.")
                fallback_md = article_data_content.get('full_generated_article_body_md', '<p>Error: Content data missing for regeneration.</p>')
                md_with_links = process_link_placeholders(fallback_md, YOUR_SITE_BASE_URL_SCRIPT_VAR)
                try:
                    final_article_body_html = html.unescape(markdown.markdown(md_with_links, extensions=['fenced_code', 'tables', 'sane_lists', 'extra', 'nl2br']))
                except Exception as md_exc:
                    logger.error(f"Error during Markdown to HTML conversion for {article_unique_id} during fallback regeneration: {md_exc}")
                    final_article_body_html = f"<p><strong>Error converting Markdown to HTML during fallback regeneration.</strong></p>"
        else:
            # Preferred path: Re-assemble HTML from section content stored in the plan
            final_article_body_html, _ = assemble_article_html_body(
                article_plan_for_regen, 
                YOUR_SITE_BASE_URL_SCRIPT_VAR, 
                article_unique_id
            )
            if not final_article_body_html: # If assembly fails
                logger.error(f"HTML body assembly failed during regeneration for {article_unique_id}. Aborting HTML render for this article.")
                return False
        
        article_tags_list = article_data_content.get('generated_tags', [])
        article_tags_html_output = format_tags_html(article_tags_list)
        article_publish_datetime_obj = get_sort_key(article_data_content)
        
        relative_article_path_str = f"articles/{article_slug_str}.html"
        page_canonical_url = urljoin(YOUR_SITE_BASE_URL_SCRIPT_VAR, relative_article_path_str.lstrip('/')) if YOUR_SITE_BASE_URL_SCRIPT_VAR and YOUR_SITE_BASE_URL_SCRIPT_VAR != '/' else f"/{relative_article_path_str.lstrip('/')}"
        
        generated_json_ld_raw, generated_json_ld_full_script_tag = generate_json_ld(article_data_content, page_canonical_url)
        article_data_content['generated_json_ld_raw'] = generated_json_ld_raw
        article_data_content['generated_json_ld_full_script_tag'] = generated_json_ld_full_script_tag

        template_render_vars = {
            'PAGE_TITLE': article_data_content.get('generated_title_tag', article_data_content.get('title', 'Untitled')),
            'META_DESCRIPTION': article_data_content.get('generated_meta_description', 'No description available.'),
            'AUTHOR_NAME': article_data_content.get('author', AUTHOR_NAME_DEFAULT),
            'META_KEYWORDS_LIST': article_tags_list,
            'CANONICAL_URL': page_canonical_url,
            'SITE_NAME': YOUR_WEBSITE_NAME,
            'YOUR_WEBSITE_LOGO_URL': YOUR_WEBSITE_LOGO_URL,
            'IMAGE_URL': article_data_content.get('selected_image_url', ''),
            'IMAGE_ALT_TEXT': article_data_content.get('generated_seo_h1', article_data_content.get('title', 'Article Image')),
            'PUBLISH_ISO_FOR_META': article_data_content.get('published_iso', datetime.now(timezone.utc).isoformat()),
            'JSON_LD_SCRIPT_BLOCK': generated_json_ld_full_script_tag,
            'ARTICLE_HEADLINE': article_data_content.get('generated_seo_h1', article_data_content.get('title', 'Untitled Article')),
            'ARTICLE_SEO_H1': article_data_content.get('generated_seo_h1', article_data_content.get('title', 'Untitled Article')), 
            'PUBLISH_DATE': article_publish_datetime_obj.strftime('%B %d, %Y') if article_publish_datetime_obj != datetime(1970,1,1,tzinfo=timezone.utc) else "Date Unknown",
            'ARTICLE_BODY_HTML': final_article_body_html, 
            'ARTICLE_TAGS_HTML': article_tags_html_output,
            'SOURCE_ARTICLE_URL': article_data_content.get('original_source_url', article_data_content.get('link', '#')),
            'ARTICLE_TITLE': article_data_content.get('title', 'Untitled'), 
            'id': article_unique_id, 
            'CURRENT_ARTICLE_ID': article_unique_id,
            'CURRENT_ARTICLE_TOPIC': article_data_content.get('topic', 'General'),
            'CURRENT_ARTICLE_TAGS_JSON': json.dumps(article_tags_list),
            'AUDIO_URL': article_data_content.get('audio_url', None)
        }
        
        if render_post_page(template_render_vars, article_slug_str):
            logger.info(f"HTML regeneration successful for {article_unique_id}.")
            article_data_content['post_template_hash'] = current_post_template_hash
            proc_json_filepath_for_update = os.path.join(PROCESSED_JSON_DIR, f"{article_unique_id}.json")
            if save_processed_data(proc_json_filepath_for_update, article_data_content):
                logger.info(f"Successfully updated JSON for {article_unique_id} with new template hash: {current_post_template_hash}")
            else:
                logger.error(f"Failed to update template hash in {proc_json_filepath_for_update} after successful HTML regeneration.")
            return True
        else:
            logger.error(f"HTML rendering FAILED for {article_unique_id} during regeneration. JSON hash will not be updated.")
            return False
    return False 


# --- Main Processing Function for Newly Researched Articles ---
def process_researched_article_data(article_data_content, existing_articles_summary_data, current_run_fully_processed_data_list):
    article_unique_id = article_data_content.get('id')
    logger.info(f"--- Processing researched article data for ID: {article_unique_id} ---")

    final_processed_file_path = os.path.join(PROCESSED_JSON_DIR, f"{article_unique_id}.json")
    if os.path.exists(final_processed_file_path):
        logger.info(f"Article ID {article_unique_id} already fully processed (JSON exists). Skipping reprocessing this item."); return None

    try:
        publish_date_iso_str = article_data_content.get('published_iso')
        if publish_date_iso_str:
            publish_datetime_obj = get_sort_key(article_data_content)
            if publish_datetime_obj < (datetime.now(timezone.utc) - timedelta(days=ARTICLE_MAX_AGE_DAYS_FILTER)):
                logger.info(f"Researched article {article_unique_id} is too old ({publish_datetime_obj.date()}). Skipping."); return None
        else:
            logger.warning(f"Researched article {article_unique_id} is missing a publish date. Proceeding with caution.")

        current_title_lower_case = article_data_content.get('title', '').strip().lower()
        if not current_title_lower_case:
            logger.error(f"Article {article_unique_id} has an empty title after stripping. Skipping processing."); return None

        for existing_summary in existing_articles_summary_data: 
            if isinstance(existing_summary, dict) and \
               existing_summary.get('title','').strip().lower() == current_title_lower_case and \
               existing_summary.get('image_url') == article_data_content.get('selected_image_url') and \
               existing_summary.get('id') != article_unique_id: 
                logger.warning(f"Article {article_unique_id} appears to be a DUPLICATE (based on Title & Image) of existing article {existing_summary.get('id', 'N/A')} in all_articles.json. Skipping."); return None
        logger.debug(f"Article {article_unique_id} passed initial Title+Image duplicate check against all_articles.json.")

        article_data_content = run_filter_agent(article_data_content)
        if not article_data_content or article_data_content.get('filter_verdict') is None:
            logger.error(f"Filter Agent failed for {article_unique_id}. Skipping article."); return None
        
        filter_verdict_data = article_data_content['filter_verdict']
        importance_level = filter_verdict_data.get('importance_level')
        if importance_level == "Boring":
            logger.info(f"Article {article_unique_id} classified as 'Boring' by Filter Agent. Skipping."); return None
        
        article_data_content['topic'] = filter_verdict_data.get('topic', 'Other')
        article_data_content['is_breaking'] = (importance_level == "Breaking")
        article_data_content['primary_topic_keyword'] = filter_verdict_data.get('primary_topic_keyword', article_data_content.get('title','Untitled Article'))
        logger.info(f"Article {article_unique_id} classified as '{importance_level}' (Topic: {article_data_content['topic']}) by Filter Agent.")

        article_data_content = run_similarity_check_agent(article_data_content, PROCESSED_JSON_DIR, current_run_fully_processed_data_list)
        similarity_verdict = article_data_content.get('similarity_verdict', 'ERROR')
        if not similarity_verdict.startswith("OKAY"): 
            logger.warning(f"Article {article_unique_id} flagged by Similarity Check Agent: {similarity_verdict}. Skipping article."); return None
        logger.info(f"Article {article_unique_id} passed advanced similarity check (Verdict: {similarity_verdict}).")

        article_data_content = run_keyword_generator_agent(article_data_content)
        article_data_content = run_title_generator_agent(article_data_content) 
        article_data_content = run_description_generator_agent(article_data_content)
        article_data_content = run_markdown_generator_agent(article_data_content) 

        if not article_data_content.get('article_plan') or not article_data_content['article_plan'].get('sections'):
            logger.error(f"Markdown Generator Agent failed to produce a valid plan for {article_unique_id}. Skipping article."); return None

        # --- Section Writing and HTML Assembly ---
        article_plan_for_writing = article_data_content['article_plan']
        
        # Store generated content for each section directly in the plan items
        for i, section_plan_item in enumerate(article_plan_for_writing.get('sections', [])):
            section_content_output = run_section_writer_agent(section_plan_item, article_data_content)
            article_data_content['article_plan']['sections'][i]['generated_content_for_section'] = section_content_output
            # Log if section writer failed for a specific section
            if not section_content_output:
                 logger.warning(f"Section writer returned no content for section type '{section_plan_item.get('section_type')}' in {article_unique_id}. Fallback/placeholder will be used by SectionWriter.")

        # Now assemble the final HTML body and the pure Markdown body
        final_html_body, final_pure_markdown_body = assemble_article_html_body(
            article_data_content['article_plan'], # Pass the plan which now contains 'generated_content_for_section'
            YOUR_SITE_BASE_URL_SCRIPT_VAR,
            article_unique_id
        )
        article_data_content['article_body_html_for_review'] = final_html_body
        article_data_content['full_generated_article_body_md'] = final_pure_markdown_body
        
        article_data_content['generated_tags'] = article_data_content.get('final_keywords', [])[:15] 
        logger.info(f"Using {len(article_data_content['generated_tags'])} keywords as tags for {article_unique_id}.")

        # --- Review Agents ---
        article_data_content = run_article_review_agent(article_data_content) 
        article_data_content = run_seo_review_agent(article_data_content)     

        review_verdict = article_data_content.get('article_review_results', {}).get('review_verdict')
        if review_verdict in ["FAIL_CONTENT", "FAIL_RENDERING", "FAIL_CRITICAL"]:
            logger.error(f"Article Review Agent for {article_unique_id} resulted in '{review_verdict}'. Skipping article. Issues: {article_data_content.get('article_review_results', {}).get('issues_found')}")
            return None
        elif review_verdict == "FLAGGED_MAJOR":
             logger.warning(f"Article Review for {article_unique_id} is 'FLAGGED_MAJOR'. Proceeding with publication, but manual review strongly advised. Issues: {article_data_content.get('article_review_results', {}).get('issues_found')}")

        final_title_for_slug = article_data_content.get('generated_seo_h1', article_data_content.get('title', article_unique_id))
        article_data_content['slug'] = slugify(final_title_for_slug)
        logger.info(f"Generated slug for {article_unique_id}: {article_data_content['slug']}")

        num_tags = len(article_data_content.get('generated_tags', [])); calculated_trend_score = 0.0
        if importance_level == "Interesting": calculated_trend_score += 5.0
        elif importance_level == "Breaking": calculated_trend_score += 10.0
        calculated_trend_score += float(num_tags) * 0.5
        if publish_date_iso_str:
            publish_dt = get_sort_key(article_data_content); now_utc_time = datetime.now(timezone.utc)
            if publish_dt <= now_utc_time: 
                days_old_val = (now_utc_time - publish_dt).total_seconds() / 86400.0
                if days_old_val <= ARTICLE_MAX_AGE_DAYS_FILTER : 
                    calculated_trend_score += max(0.0, 1.0 - (days_old_val / float(ARTICLE_MAX_AGE_DAYS_FILTER))) * 5.0
        article_data_content['trend_score'] = round(max(0.0, calculated_trend_score), 2)

        # HTML regeneration is implicitly handled here for NEW articles by calling regenerate_article_html_if_needed with force_regen=True.
        # The 'final_article_body_html' used by the template will be the 'article_body_html_for_review' we just assembled.
        if not regenerate_article_html_if_needed(article_data_content, force_regen=True): # force_regen=True ensures it writes for new articles
            logger.error(f"Failed to render final HTML for new article {article_unique_id}. Skipping save and further processing."); return None
        
        relative_article_path_str = f"articles/{article_data_content['slug']}.html"
        page_canonical_url = urljoin(YOUR_SITE_BASE_URL_SCRIPT_VAR, relative_article_path_str.lstrip('/')) if YOUR_SITE_BASE_URL_SCRIPT_VAR and YOUR_SITE_BASE_URL_SCRIPT_VAR != '/' else f"/{relative_article_path_str.lstrip('/')}"
        
        summary_for_site_list = {
            "id": article_unique_id,
            "title": article_data_content.get('generated_seo_h1', article_data_content.get('title')), 
            "link": relative_article_path_str,
            "published_iso": article_data_content.get('published_iso') or datetime.now(timezone.utc).isoformat(),
            "summary_short": article_data_content.get('generated_meta_description', ''), 
            "image_url": article_data_content.get('selected_image_url'),
            "topic": article_data_content.get('topic', 'News'),
            "is_breaking": article_data_content.get('is_breaking', False),
            "tags": article_data_content.get('generated_tags', []),
            "audio_url": None, 
            "trend_score": article_data_content.get('trend_score', 0.0)
        }
        update_all_articles_json_file(summary_for_site_list)

        payload_for_social_media = {
            "id": article_unique_id,
            "title": article_data_content.get('generated_title_tag', summary_for_site_list['title']), 
            "article_url": page_canonical_url,
            "image_url": summary_for_site_list['image_url'],
            "topic": summary_for_site_list['topic'],
            "tags": summary_for_site_list['tags'],
            "summary_short": summary_for_site_list.get('summary_short', '') 
        }
        
        logger.info(f"--- Successfully processed and saved researched article: {article_unique_id} ---")
        return {"summary": summary_for_site_list, "social_post_data": payload_for_social_media, "full_data": article_data_content }

    except Exception as main_process_e:
        logger.exception(f"CRITICAL failure processing researched article {article_unique_id}: {main_process_e}")
        return None


# --- Main Orchestration ---
if __name__ == "__main__":
    run_start_timestamp = time.time()
    logger.info(f"--- === Dacoola AI News Orchestrator Starting Run ({datetime.now(timezone.utc).isoformat()}) === ---")
    ensure_directories() 

    current_post_template_hash = get_file_hash(POST_TEMPLATE_FILE)
    if not current_post_template_hash:
        logger.critical(f"CRITICAL FAILURE: Could not hash template file: {POST_TEMPLATE_FILE}. Cannot proceed with HTML checks. Exiting."); sys.exit(1)
    logger.info(f"Current post_template.html hash: {current_post_template_hash}")

    social_media_clients_glob = initialize_social_clients() # Corrected: use the actual variable name
    
    fully_processed_article_ids_set = set(os.path.basename(f).replace('.json', '') for f in glob.glob(os.path.join(PROCESSED_JSON_DIR, '*.json')))
    logger.info(f"Found {len(fully_processed_article_ids_set)} existing fully processed article JSONs.")

    logger.info("--- Stage 1: Checking/Regenerating HTML from Existing Processed Data ---")
    all_processed_json_files = glob.glob(os.path.join(PROCESSED_JSON_DIR, '*.json'))
    html_regenerated_count = 0
    for proc_json_filepath in all_processed_json_files:
        try:
            article_data_from_file = load_article_data(proc_json_filepath)
            if article_data_from_file:
                # The regenerate_article_html_if_needed function now expects section content to be
                # within article_data_from_file['article_plan']['sections'][i]['generated_content_for_section']
                # If this key is missing (e.g., older JSONs), it will log a warning and might skip sections.
                # A proper migration for old JSONs would be needed for perfect regeneration if their structure is different.
                if regenerate_article_html_if_needed(article_data_from_file): 
                    html_regenerated_count += 1
        except Exception as regen_exc:
            logger.exception(f"Error during HTML regeneration check for {os.path.basename(proc_json_filepath)}: {regen_exc}")
    logger.info(f"--- HTML Regeneration Stage Complete. Regenerated/Verified {html_regenerated_count} files based on template hash. ---")

    logger.info("--- Stage 2: Running Research Agent (Feeds & Gyro Picks) ---")
    newly_researched_articles_data_list = []
    MAX_ARTICLES_PER_RUN = int(os.getenv('MAX_ARTICLES_PER_RUN', '5')) 
    try:
        gyro_pick_files = glob.glob(os.path.join(RAW_WEB_RESEARCH_OUTPUT_DIR, 'gyro-*.json'))
        gyro_picks_to_process = []
        for gyro_file in gyro_pick_files:
            try:
                with open(gyro_file, 'r', encoding='utf-8') as gf:
                    gyro_data = json.load(gf)
                    if gyro_data.get('id') and gyro_data.get('id') not in fully_processed_article_ids_set:
                        gyro_picks_to_process.append(gyro_data)
                        logger.info(f"Queued Gyro Pick: {gyro_data.get('id')}")
                    elif gyro_data.get('id') in fully_processed_article_ids_set:
                        logger.info(f"Gyro Pick {gyro_data.get('id')} already processed. Moving file.")
                        processed_gyro_dir = os.path.join(RAW_WEB_RESEARCH_OUTPUT_DIR, 'processed_gyro_picks')
                        os.makedirs(processed_gyro_dir, exist_ok=True)
                        os.rename(gyro_file, os.path.join(processed_gyro_dir, os.path.basename(gyro_file)))
            except Exception as e_gyro_load:
                logger.error(f"Error loading Gyro Pick file {gyro_file}: {e_gyro_load}")
        
        newly_researched_articles_data_list = run_research_agent(
            processed_ids_set=fully_processed_article_ids_set.copy(), 
            max_articles_to_fetch=MAX_ARTICLES_PER_RUN,
            gyro_picks_data_list=gyro_picks_to_process 
        )
    except Exception as research_e:
        logger.exception(f"Research Agent run critically failed: {research_e}")
    logger.info(f"Research Agent run completed. Returned {len(newly_researched_articles_data_list)} new raw articles for processing.")

    logger.info("--- Stage 3: Processing Newly Researched Articles ---")
    all_articles_summary_data_for_run = load_all_articles_data_from_json() 
    current_run_fully_processed_data_accumulator = [] 
    successfully_processed_count = 0; failed_or_skipped_count = 0
    social_media_payloads_for_posting_queue = []

    if newly_researched_articles_data_list:
        for new_article_raw_data in newly_researched_articles_data_list:
            if not new_article_raw_data or not isinstance(new_article_raw_data, dict):
                logger.warning("Research agent returned an invalid item (not a dict or None). Skipping.")
                failed_or_skipped_count +=1
                continue

            processing_result = process_researched_article_data(
                new_article_raw_data,
                all_articles_summary_data_for_run, 
                current_run_fully_processed_data_accumulator 
            )
            if processing_result and isinstance(processing_result, dict):
                successfully_processed_count += 1
                if "full_data" in processing_result: 
                    current_run_fully_processed_data_accumulator.append(processing_result["full_data"])
                if "social_post_data" in processing_result:
                    social_media_payloads_for_posting_queue.append(processing_result["social_post_data"])
                if processing_result.get("full_data", {}).get("id"):
                    fully_processed_article_ids_set.add(processing_result["full_data"]["id"])
                    if processing_result["full_data"].get("is_gyro_pick"):
                        gyro_source_file = os.path.join(RAW_WEB_RESEARCH_OUTPUT_DIR, f"{processing_result['full_data']['id']}.json")
                        if os.path.exists(gyro_source_file):
                            processed_gyro_dir = os.path.join(RAW_WEB_RESEARCH_OUTPUT_DIR, 'processed_gyro_picks')
                            os.makedirs(processed_gyro_dir, exist_ok=True)
                            try:
                                os.rename(gyro_source_file, os.path.join(processed_gyro_dir, os.path.basename(gyro_source_file)))
                                logger.info(f"Moved processed Gyro Pick source {os.path.basename(gyro_source_file)} to archive.")
                            except Exception as e_mv_gyro:
                                logger.error(f"Could not move processed Gyro Pick source {gyro_source_file}: {e_mv_gyro}")
            else:
                failed_or_skipped_count += 1
    logger.info(f"Newly researched articles processing cycle complete. Successfully processed: {successfully_processed_count}, Failed/Skipped: {failed_or_skipped_count}")

    logger.info(f"--- Stage 3.5: Queuing Unposted Processed Articles (Last {MAX_AGE_FOR_SOCIAL_POST_HOURS}h) for Social Media ---")
    social_post_history_data = load_social_post_history()
    already_posted_social_ids = set(social_post_history_data.get('posted_articles', []))
    now_for_age_check = datetime.now(timezone.utc)
    cutoff_time_for_social = now_for_age_check - timedelta(hours=MAX_AGE_FOR_SOCIAL_POST_HOURS)
    
    ids_already_in_current_newly_processed_queue = {p.get('id') for p in social_media_payloads_for_posting_queue if p.get('id')}
    unposted_existing_processed_added_to_queue = 0

    all_processed_json_files_for_social_check = glob.glob(os.path.join(PROCESSED_JSON_DIR, '*.json'))
    for processed_json_file_path_check in all_processed_json_files_for_social_check:
        article_id_from_filename = os.path.basename(processed_json_file_path_check).replace('.json', '')
        if article_id_from_filename in ids_already_in_current_newly_processed_queue: continue 
        if article_id_from_filename in already_posted_social_ids: continue 

        processed_article_full_data = load_article_data(processed_json_file_path_check)
        if not processed_article_full_data: continue

        published_iso_for_social = processed_article_full_data.get('published_iso')
        if not published_iso_for_social: continue
        try:
            article_publish_dt = get_sort_key(processed_article_full_data)
            if article_publish_dt < cutoff_time_for_social: 
                mark_article_as_posted_in_history(article_id_from_filename) 
                continue
        except Exception: continue 
        
        logger.info(f"Article ID {article_id_from_filename} (from processed_json) is recent and unposted. Adding to social media queue.")
        article_title_for_social = processed_article_full_data.get('generated_title_tag', processed_article_full_data.get('generated_seo_h1', processed_article_full_data.get('title', 'Untitled')))
        article_slug_for_social = processed_article_full_data.get('slug')
        if not article_slug_for_social: logger.warning(f"Skipping {article_id_from_filename} for social queue: missing slug."); continue

        relative_link_for_social = f"articles/{article_slug_for_social}.html"
        canonical_url_for_social = urljoin(YOUR_SITE_BASE_URL_SCRIPT_VAR, relative_link_for_social.lstrip('/')) if YOUR_SITE_BASE_URL_SCRIPT_VAR and YOUR_SITE_BASE_URL_SCRIPT_VAR != '/' else f"/{relative_link_for_social.lstrip('/')}"
        summary_short_for_social = processed_article_full_data.get('generated_meta_description', '')

        payload = { "id": article_id_from_filename, "title": article_title_for_social, "article_url": canonical_url_for_social,
                    "image_url": processed_article_full_data.get('selected_image_url'), 
                    "topic": processed_article_full_data.get('topic', 'Technology'),
                    "tags": processed_article_full_data.get('generated_tags', []), 
                    "summary_short": summary_short_for_social }
        social_media_payloads_for_posting_queue.append(payload)
        unposted_existing_processed_added_to_queue += 1
        
    if unposted_existing_processed_added_to_queue > 0:
        logger.info(f"Added {unposted_existing_processed_added_to_queue} recent, unposted items from existing processed_json files to the social media queue.")

    current_run_date_str, twitter_posts_made_today = _read_tweet_tracker()
    if current_run_date_str != datetime.now(timezone.utc).strftime('%Y-%m-%d'): 
        twitter_posts_made_today = 0
        current_run_date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        _write_tweet_tracker(current_run_date_str, 0) 
    logger.info(f"Twitter posts made today ({current_run_date_str}) before this social cycle: {twitter_posts_made_today} (Daily Limit: {DAILY_TWEET_LIMIT})")

    if social_media_payloads_for_posting_queue:
        logger.info(f"--- Stage 4: Attempting to post {len(social_media_payloads_for_posting_queue)} total articles to Social Media ---")
        final_make_webhook_payloads = []
        
        def get_publish_date_for_social_sort(payload): 
            article_id_for_sort = payload.get('id')
            if not article_id_for_sort: return datetime(1970, 1, 1, tzinfo=timezone.utc)
            temp_data = load_article_data(os.path.join(PROCESSED_JSON_DIR, f"{article_id_for_sort}.json"))
            return get_sort_key(temp_data or {}) 

        try:
            social_media_payloads_for_posting_queue.sort(key=get_publish_date_for_social_sort, reverse=True)
            logger.info("Social media queue sorted by publish date (newest first).")
        except Exception as sort_e:
            logger.error(f"Error sorting social media queue: {sort_e}. Proceeding unsorted.")


        articles_posted_this_run_count = 0
        for social_payload_item in social_media_payloads_for_posting_queue:
            article_id_for_social_post = social_payload_item.get('id')
            current_social_history = load_social_post_history()
            if article_id_for_social_post in current_social_history.get('posted_articles',[]):
                logger.info(f"Article {article_id_for_social_post} was already marked in social history just before its posting turn. Skipping."); continue

            logger.info(f"Preparing to post article ID: {article_id_for_social_post} ('{social_payload_item.get('title', 'Untitled')[:40]}...')")
            platforms_to_attempt_post = ["bluesky", "reddit"] 
            
            if social_media_clients_glob.get("twitter_client"): # Corrected variable name
                _current_date_loop, current_twitter_posts_made_today_loop = _read_tweet_tracker()
                if _current_date_loop != current_run_date_str: 
                    current_twitter_posts_made_today_loop = 0
                    current_run_date_str = _current_date_loop
                    _write_tweet_tracker(current_run_date_str, 0)

                if current_twitter_posts_made_today_loop < DAILY_TWEET_LIMIT:
                    platforms_to_attempt_post.append("twitter")
                    logger.info(f"Article {article_id_for_social_post} WILL be attempted on Twitter. (Daily count: {current_twitter_posts_made_today_loop}/{DAILY_TWEET_LIMIT})")
                else:
                    logger.info(f"Daily Twitter limit ({DAILY_TWEET_LIMIT}) reached. Twitter SKIPPED for article ID: {article_id_for_social_post}")
            
            post_successful_on_any_platform = run_social_media_poster(social_payload_item, social_media_clients_glob, tuple(platforms_to_attempt_post)) # Corrected variable name
            
            if "twitter" in platforms_to_attempt_post and post_successful_on_any_platform:
                _ , current_twitter_posts_now = _read_tweet_tracker()
                if current_twitter_posts_now < DAILY_TWEET_LIMIT : 
                    _write_tweet_tracker(current_run_date_str, current_twitter_posts_now + 1)
            
            articles_posted_this_run_count +=1 
            if MAKE_WEBHOOK_URL and post_successful_on_any_platform:
                final_make_webhook_payloads.append(social_payload_item)
            
            if articles_posted_this_run_count < len(social_media_payloads_for_posting_queue): 
                time.sleep(random.randint(8, 15)) 

        logger.info(f"Social media posting cycle finished. Attempted to distribute {articles_posted_this_run_count} articles.")
        if MAKE_WEBHOOK_URL and final_make_webhook_payloads:
            logger.info(f"--- Sending {len(final_make_webhook_payloads)} successfully posted items to Make.com Webhook ---")
            if send_make_webhook(MAKE_WEBHOOK_URL, final_make_webhook_payloads):
                logger.info("Batched Make.com webhook for posted articles sent successfully.")
            else:
                logger.error("Batched Make.com webhook for posted articles failed.")
    else:
        logger.info("No new or unposted recent articles were queued for social media posting in this run.")

    logger.info("--- Stage 5: Generating Sitemap ---")
    if not YOUR_SITE_BASE_URL_SCRIPT_VAR or YOUR_SITE_BASE_URL_SCRIPT_VAR == '/':
        logger.error(f"Sitemap generation SKIPPED: Site base URL is not properly set (derived value: '{YOUR_SITE_BASE_URL_SCRIPT_VAR}').");
    else:
        try:
            run_sitemap_generator()
            logger.info("Sitemap generation completed successfully.")
        except Exception as main_sitemap_e:
            logger.exception(f"Sitemap generation failed during main run: {main_sitemap_e}")

    run_end_timestamp = time.time()
    logger.info(f"--- === Dacoola AI News Orchestrator Run Finished ({run_end_timestamp - run_start_timestamp:.2f} seconds) === ---")