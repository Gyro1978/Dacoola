# src/main.py (Updated to post Gyro Picks and other unposted processed articles)

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
import requests # For requests.utils.quote and webhook
import html # For html.escape in tag formatting
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin
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
    from src.agents.keyword_research_agent import run_keyword_research_agent # LLM version
    from src.agents.seo_article_generator_agent import run_seo_article_agent
    from src.social.social_media_poster import (
        initialize_social_clients, run_social_media_poster,
        load_post_history as load_social_post_history, # For checking before posting
        mark_article_as_posted_in_history # To mark after main.py initiates a post
    )
except ImportError as e:
     print(f"FATAL IMPORT ERROR in main.py (agents/scrapers/social): {e}")
     try: logging.critical(f"FATAL IMPORT ERROR (agents/scrapers/social): {e}")
     except: pass
     sys.exit(1)

# --- Load Environment Variables ---
dotenv_path = os.path.join(PROJECT_ROOT_FOR_PATH, '.env'); load_dotenv(dotenv_path=dotenv_path)
AUTHOR_NAME_DEFAULT = os.getenv('AUTHOR_NAME', 'AI News Team')
YOUR_WEBSITE_NAME = os.getenv('YOUR_WEBSITE_NAME', 'Dacoola')
YOUR_WEBSITE_LOGO_URL = os.getenv('YOUR_WEBSITE_LOGO_URL', '')
raw_base_url = os.getenv('YOUR_SITE_BASE_URL', ''); YOUR_SITE_BASE_URL = (raw_base_url.rstrip('/') + '/') if raw_base_url else ''
MAKE_WEBHOOK_URL = os.getenv('MAKE_INSTAGRAM_WEBHOOK_URL', None)
DAILY_TWEET_LIMIT = int(os.getenv('DAILY_TWEET_LIMIT', '3'))

# --- Setup Logging ---
log_file_path = os.path.join(PROJECT_ROOT_FOR_PATH, 'dacola.log')
try:
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    log_handlers = [ logging.StreamHandler(sys.stdout), logging.FileHandler(log_file_path, encoding='utf-8') ]
except OSError as e: print(f"Log setup warning: {e}. Log console only."); log_handlers = [logging.StreamHandler(sys.stdout)]
logging.basicConfig( level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S', handlers=log_handlers, force=True )
logger = logging.getLogger('main_orchestrator')

if not YOUR_SITE_BASE_URL or YOUR_SITE_BASE_URL == '/': # Check for valid base URL
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
# SOCIAL_POST_HISTORY_FILE is defined in social_media_poster.py, main.py will use its loader


# --- Jinja2 Setup ---
try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape # Added select_autoescape
    def escapejs_filter(value):
        if value is None: return ''; value = str(value); value = value.replace('\\', '\\\\').replace("'", "\\'").replace('"', '\\"').replace('/', '\\/').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t').replace('<', '\\u003c').replace('>', '\\u003e').replace('\b', '\\b').replace('\f', '\\f')
        return value
    if not os.path.isdir(TEMPLATE_DIR):
        logger.critical(f"Jinja2 template directory not found: {TEMPLATE_DIR}. Exiting.")
        sys.exit(1)
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(['html', 'xml']))
    env.filters['escapejs'] = escapejs_filter
    logger.info(f"Jinja2 environment loaded from {TEMPLATE_DIR}")
except ImportError:
    logger.critical("Jinja2 library not found. Please install it. Exiting.")
    sys.exit(1)
except Exception as e:
    logger.exception(f"CRITICAL: Failed Jinja2 initialization. Exiting: {e}")
    sys.exit(1)

# --- Helper Functions ---
def ensure_directories():
    # ... (no changes)
    dirs_to_create = [ DATA_DIR_MAIN, SCRAPED_ARTICLES_DIR, PROCESSED_JSON_DIR, PUBLIC_DIR, OUTPUT_HTML_DIR, TEMPLATE_DIR ]
    try:
        for d in dirs_to_create: os.makedirs(d, exist_ok=True)
        logger.info("Ensured core directories exist.")
    except OSError as e:
        logger.exception(f"CRITICAL: Create directory fail {getattr(e, 'filename', 'N/A')}: {getattr(e, 'strerror', str(e))}")
        sys.exit(1)

def load_article_data(filepath):
    # ... (no changes)
    try:
        with open(filepath, 'r', encoding='utf-8') as f: return json.load(f)
    except FileNotFoundError: logger.warning(f"File not found when trying to load: {filepath}"); return None
    except json.JSONDecodeError: logger.error(f"Error decoding JSON from {filepath}. File might be corrupted."); return None
    except Exception as e: logger.error(f"Error loading article data from {filepath}: {e}"); return None

def save_processed_data(filepath, article_data_to_save):
    # ... (no changes)
    try:
         os.makedirs(os.path.dirname(filepath), exist_ok=True)
         with open(filepath, 'w', encoding='utf-8') as f: json.dump(article_data_to_save, f, indent=4, ensure_ascii=False)
         logger.info(f"Saved processed data to: {os.path.basename(filepath)}"); return True
    except Exception as e: logger.error(f"Failed to save processed data {os.path.basename(filepath)}: {e}"); return False

def remove_scraped_file(filepath):
    # ... (no changes)
    try:
         if os.path.exists(filepath): os.remove(filepath); logger.debug(f"Removed original scraped file: {os.path.basename(filepath)}")
         else: logger.warning(f"Attempted to remove scraped file, but not found: {filepath}")
    except OSError as e: logger.error(f"Failed to remove scraped file {filepath}: {e}")

def format_tags_html(tags_list_for_html):
    # ... (no changes, uses html.escape now which is good)
    if not tags_list_for_html or not isinstance(tags_list_for_html, list): return ""
    try:
        tag_html_links = []; base_url_for_tags = YOUR_SITE_BASE_URL.rstrip('/') + '/' if YOUR_SITE_BASE_URL else '/'
        for tag_item in tags_list_for_html:
            safe_tag_item = requests.utils.quote(str(tag_item))
            tag_page_url = urljoin(base_url_for_tags, f"topic.html?name={safe_tag_item}")
            tag_html_links.append(f'<a href="{tag_page_url}" class="tag-link">{html.escape(str(tag_item))}</a>')
        return ", ".join(tag_html_links)
    except Exception as e: logger.error(f"Error formatting tags for HTML: {tags_list_for_html} - {e}"); return ""


def get_sort_key(article_dict_item):
    # ... (no changes)
    fallback_past_date = datetime(1970, 1, 1, tzinfo=timezone.utc)
    date_iso_str = article_dict_item.get('published_iso')
    if not date_iso_str or not isinstance(date_iso_str, str): return fallback_past_date
    try:
        if date_iso_str.endswith('Z'): date_iso_str = date_iso_str[:-1] + '+00:00'
        dt_obj = datetime.fromisoformat(date_iso_str)
        return dt_obj.replace(tzinfo=timezone.utc) if dt_obj.tzinfo is None else dt_obj
    except ValueError: logger.warning(f"Could not parse date '{date_iso_str}' for sorting. Using fallback."); return fallback_past_date


def _read_tweet_tracker():
    # ... (no changes)
    today_date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    try:
        if os.path.exists(TWITTER_DAILY_LIMIT_FILE):
            with open(TWITTER_DAILY_LIMIT_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
            if data.get('date') == today_date_str: return data['date'], data.get('count', 0)
        return today_date_str, 0
    except Exception as e: logger.error(f"Error reading Twitter tracker {TWITTER_DAILY_LIMIT_FILE}: {e}. Resetting."); return today_date_str, 0

def _write_tweet_tracker(date_str, count):
    # ... (no changes)
    try:
        os.makedirs(os.path.dirname(TWITTER_DAILY_LIMIT_FILE), exist_ok=True)
        with open(TWITTER_DAILY_LIMIT_FILE, 'w', encoding='utf-8') as f: json.dump({'date': date_str, 'count': count}, f, indent=2)
        logger.info(f"Twitter tracker updated: Date {date_str}, Count {count}")
    except Exception as e: logger.error(f"Error writing Twitter tracker {TWITTER_DAILY_LIMIT_FILE}: {e}")

def send_make_webhook(webhook_url, data_payload):
    # ... (no changes)
    if not webhook_url: logger.warning("Make webhook URL missing."); return False
    if not data_payload: logger.warning("No data for Make webhook."); return False
    payload_to_send = {"articles": data_payload} if isinstance(data_payload, list) else data_payload
    log_id_info_str = f"batch of {len(data_payload)} articles" if isinstance(data_payload, list) else f"article ID: {data_payload.get('id', 'N/A')}"
    try:
        response = requests.post(webhook_url, headers={'Content-Type': 'application/json'}, json=payload_to_send, timeout=30)
        response.raise_for_status(); logger.info(f"Successfully sent to Make webhook for {log_id_info_str}"); return True
    except Exception as e: logger.error(f"Failed send to Make webhook for {log_id_info_str}: {e}"); return False

def render_post_page(template_variables_dict, slug_base_str):
    # ... (no changes)
    try:
        template = env.get_template('post_template.html')
        html_content_output = template.render(template_variables_dict)
        safe_filename_str = slug_base_str if slug_base_str else template_variables_dict.get('id', 'untitled-article')
        safe_filename_str = re.sub(r'[<>:"/\\|?*%\.]+', '', safe_filename_str).strip().lower().replace(' ', '-')
        safe_filename_str = re.sub(r'-+', '-', safe_filename_str).strip('-')[:80] or template_variables_dict.get('id', 'article-fallback-slug')
        output_html_path = os.path.join(OUTPUT_HTML_DIR, f"{safe_filename_str}.html")
        os.makedirs(os.path.dirname(output_html_path), exist_ok=True)
        with open(output_html_path, 'w', encoding='utf-8') as f: f.write(html_content_output)
        logger.info(f"Rendered HTML: {os.path.basename(output_html_path)}")
        return output_html_path
    except Exception as e: logger.exception(f"CRITICAL: Failed to render HTML for {template_variables_dict.get('id','N/A')}: {e}"); return None

def load_all_articles_data_from_json():
    # ... (no changes)
    if not os.path.exists(ALL_ARTICLES_FILE): return []
    try:
        with open(ALL_ARTICLES_FILE, 'r', encoding='utf-8') as f: data_content = json.load(f)
        if isinstance(data_content, dict) and isinstance(data_content.get('articles'), list): return data_content['articles']
        logger.warning(f"{ALL_ARTICLES_FILE} does not have {{'articles': [...]}} structure. Returning empty.")
    except json.JSONDecodeError: logger.error(f"Error decoding JSON from {ALL_ARTICLES_FILE}. Returning empty.")
    except Exception as e: logger.error(f"Error loading {ALL_ARTICLES_FILE}: {e}. Returning empty.")
    return []

def update_all_articles_json_file(new_article_summary_info):
    # ... (no changes)
    current_articles_list_data = load_all_articles_data_from_json()
    article_unique_id = new_article_summary_info.get('id')
    if not article_unique_id: logger.error("Cannot update all_articles.json: new info missing 'id'."); return
    articles_dict = {art.get('id'): art for art in current_articles_list_data if isinstance(art, dict) and art.get('id')}
    articles_dict[article_unique_id] = new_article_summary_info
    updated_articles_list = sorted(list(articles_dict.values()), key=get_sort_key, reverse=True)
    final_data_to_save_to_json = {"articles": updated_articles_list}
    try:
        with open(ALL_ARTICLES_FILE, 'w', encoding='utf-8') as f: json.dump(final_data_to_save_to_json, f, indent=2, ensure_ascii=False)
        logger.info(f"Updated {os.path.basename(ALL_ARTICLES_FILE)} ({len(updated_articles_list)} articles).")
    except Exception as e: logger.error(f"Failed to save updated {os.path.basename(ALL_ARTICLES_FILE)}: {e}")


# --- Main Processing Function for Scraped Articles ---
def process_single_scraped_article(raw_json_filepath, existing_articles_summary_data, processed_ids_this_run_set):
    # ... (This function remains largely the same logic, ensure it returns social_post_payload)
    article_filename = os.path.basename(raw_json_filepath)
    logger.info(f"--- Processing article file: {article_filename} ---")
    article_data_content = load_article_data(raw_json_filepath)
    if not article_data_content or not isinstance(article_data_content, dict):
        logger.error(f"Failed load/invalid data {article_filename}. Skipping."); remove_scraped_file(raw_json_filepath); return None

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
        image_url = scrape_source_for_image(article_data_content.get('link')) or find_best_image(article_data_content.get('title', 'AI Technology News'), article_data_content.get('link'))
        if not image_url: logger.error(f"FATAL: No suitable image found for {article_unique_id}. Skipping."); remove_scraped_file(raw_json_filepath); return None
        article_data_content['selected_image_url'] = image_url

        current_title_lower_case = article_data_content.get('title', '').strip().lower()
        if not current_title_lower_case: logger.error(f"Article {article_unique_id} has empty title. Skipping."); remove_scraped_file(raw_json_filepath); return None
        
        # Combine existing_articles_summary_data and summaries from this run for duplicate check
        combined_check_list = list(existing_articles_summary_data) + list(processed_ids_this_run_set) # Ensure processed_ids_this_run_set contains dicts
        for existing_article_summary in combined_check_list:
            if isinstance(existing_article_summary, dict) and existing_article_summary.get('title','').strip().lower() == current_title_lower_case and existing_article_summary.get('image_url') == image_url:
                logger.warning(f"Article {article_unique_id} appears DUPLICATE (Title & Image) of {existing_article_summary.get('id', 'N/A')}. Skipping."); remove_scraped_file(raw_json_filepath); return None
        logger.info(f"Article {article_unique_id} passed Title+Image duplicate check.")

        article_data_content = run_filter_agent(article_data_content)
        if not article_data_content or article_data_content.get('filter_verdict') is None: logger.error(f"Filter Agent failed for {article_unique_id}. Skip."); remove_scraped_file(raw_json_filepath); return None
        filter_agent_verdict_data = article_data_content['filter_verdict']; importance_level = filter_agent_verdict_data.get('importance_level')
        if importance_level == "Boring": logger.info(f"Article {article_unique_id} classified 'Boring'. Skipping."); remove_scraped_file(raw_json_filepath); return None
        article_data_content['topic'] = filter_agent_verdict_data.get('topic', 'Other'); article_data_content['is_breaking'] = (importance_level == "Breaking")
        article_data_content['primary_keyword'] = filter_agent_verdict_data.get('primary_topic_keyword', article_data_content.get('title','Untitled'))
        logger.info(f"Article {article_unique_id} classified '{importance_level}' (Topic: {article_data_content['topic']}).")

        article_data_content = run_keyword_research_agent(article_data_content)
        if article_data_content.get('keyword_agent_error'): logger.warning(f"Keyword Research issue for {article_unique_id}: {article_data_content['keyword_agent_error']}")
        current_researched_keywords = article_data_content.setdefault('researched_keywords', []);
        if not current_researched_keywords and article_data_content.get('primary_keyword'): current_researched_keywords.append(article_data_content['primary_keyword'])
        article_data_content['generated_tags'] = list(set(kw for kw in current_researched_keywords if kw and len(kw.strip()) > 1))[:15]
        if not article_data_content['generated_tags'] and article_data_content.get('primary_keyword'): article_data_content['generated_tags'] = [article_data_content['primary_keyword']]
        logger.info(f"Using {len(article_data_content['generated_tags'])} keywords as tags for {article_unique_id}.")

        article_data_content = run_seo_article_agent(article_data_content)
        seo_agent_results_data = article_data_content.get('seo_agent_results')
        if not seo_agent_results_data or not seo_agent_results_data.get('generated_article_body_md'): logger.error(f"SEO Agent failed for {article_unique_id}. Skip."); remove_scraped_file(raw_json_filepath); return None
        if article_data_content.get('seo_agent_error'): logger.warning(f"SEO Agent non-critical errors for {article_unique_id}: {article_data_content['seo_agent_error']}")
        
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

        article_slug_str = re.sub(r'[<>:"/\\|?*%\.\'"]+', '', article_data_content.get('title', f'article-{article_unique_id}')).strip().lower().replace(' ', '-')
        article_data_content['slug'] = re.sub(r'-+', '-', article_slug_str).strip('-')[:80] or f'article-{article_unique_id}'
        relative_article_path_str = f"articles/{article_data_content['slug']}.html"
        page_canonical_url = urljoin(YOUR_SITE_BASE_URL, relative_article_path_str.lstrip('/')) if YOUR_SITE_BASE_URL and YOUR_SITE_BASE_URL != '/' else f"/{relative_article_path_str.lstrip('/')}"

        article_body_md_content = seo_agent_results_data.get('generated_article_body_md', ''); article_body_html_output = markdown.markdown(article_body_md_content, extensions=['fenced_code', 'tables', 'nl2br'])
        article_tags_html_output = format_tags_html(article_data_content.get('generated_tags', [])); article_publish_datetime_obj = get_sort_key(article_data_content)
        template_render_vars = {
            'PAGE_TITLE': seo_agent_results_data.get('generated_title_tag', article_data_content.get('title')), 'META_DESCRIPTION': seo_agent_results_data.get('generated_meta_description', ''),
            'AUTHOR_NAME': article_data_content.get('author', AUTHOR_NAME_DEFAULT), 'META_KEYWORDS_LIST': article_data_content.get('generated_tags', []),
            'CANONICAL_URL': page_canonical_url, 'SITE_NAME': YOUR_WEBSITE_NAME, 'YOUR_WEBSITE_LOGO_URL': YOUR_WEBSITE_LOGO_URL,
            'IMAGE_URL': article_data_content.get('selected_image_url', ''), 'IMAGE_ALT_TEXT': article_data_content.get('title', 'Article Image'),
            'PUBLISH_ISO_FOR_META': article_data_content.get('published_iso') or datetime.now(timezone.utc).isoformat(),
            'JSON_LD_SCRIPT_BLOCK': seo_agent_results_data.get('generated_json_ld', ''), 'ARTICLE_HEADLINE': article_data_content.get('title'),
            'PUBLISH_DATE': article_publish_datetime_obj.strftime('%B %d, %Y') if article_publish_datetime_obj != datetime(1970,1,1,tzinfo=timezone.utc) else "Date Unavailable",
            'ARTICLE_BODY_HTML': article_body_html_output, 'ARTICLE_TAGS_HTML': article_tags_html_output,
            'SOURCE_ARTICLE_URL': article_data_content.get('link', '#'), 'ARTICLE_TITLE': article_data_content.get('title'),
            'id': article_unique_id, 'CURRENT_ARTICLE_ID': article_unique_id, 'CURRENT_ARTICLE_TOPIC': article_data_content.get('topic', ''),
            'CURRENT_ARTICLE_TAGS_JSON': json.dumps(article_data_content.get('generated_tags', [])), 'AUDIO_URL': None
        }
        if not render_post_page(template_render_vars, article_data_content['slug']): logger.error(f"Failed HTML render for {article_unique_id}. Skip."); return None

        summary_for_site_list = {"id": article_unique_id, "title": article_data_content.get('title'), "link": relative_article_path_str, "published_iso": template_render_vars['PUBLISH_ISO_FOR_META'],
                                   "summary_short": template_render_vars['META_DESCRIPTION'], "image_url": article_data_content.get('selected_image_url'), "topic": article_data_content.get('topic', 'News'),
                                   "is_breaking": article_data_content.get('is_breaking', False), "tags": article_data_content.get('generated_tags', []), "audio_url": None, "trend_score": article_data_content.get('trend_score', 0)}
        article_data_content['audio_url'] = None; update_all_articles_json_file(summary_for_site_list)
        payload_for_social_media = {"id": article_unique_id, "title": article_data_content.get('title'), "article_url": page_canonical_url,
                                   "image_url": article_data_content.get('selected_image_url'), "topic": article_data_content.get('topic'),
                                   "tags": article_data_content.get('generated_tags', []), "summary_short": summary_for_site_list.get('summary_short', '')}
        if save_processed_data(final_processed_file_path, article_data_content):
             remove_scraped_file(raw_json_filepath); logger.info(f"--- Successfully processed scraped article: {article_unique_id} ---")
             return {"summary": summary_for_site_list, "social_post_data": payload_for_social_media }
        else: logger.error(f"Failed save final JSON {article_unique_id}."); return None
    except Exception as main_process_e:
         logger.exception(f"CRITICAL failure processing {article_unique_id} ({article_filename}): {main_process_e}")
         if os.path.exists(raw_json_filepath): remove_scraped_file(raw_json_filepath); return None

# --- Main Orchestration Logic ---
if __name__ == "__main__":
    run_start_timestamp = time.time()
    logger.info(f"--- === Dacoola AI News Orchestrator Starting Run ({datetime.now(timezone.utc).isoformat()}) === ---")
    ensure_directories()

    social_media_clients_glob = initialize_social_clients()

    fully_processed_article_ids_set = set(os.path.basename(f).replace('.json', '') for f in glob.glob(os.path.join(PROCESSED_JSON_DIR, '*.json')))
    logger.info(f"Found {len(fully_processed_article_ids_set)} fully processed article JSONs (scraped or Gyro).")

    scraper_tracker_ids_set = load_scraper_processed_ids()
    initial_ids_for_scraper_run = scraper_tracker_ids_set.union(fully_processed_article_ids_set)
    logger.info(f"Total initial IDs (from scraper history or already fully processed) passed to scraper: {len(initial_ids_for_scraper_run)}")

    # --- HTML Regeneration ---
    logger.info("--- Stage 1: Checking for Missing HTML from Processed Data (Scraped & Gyro) ---")
    # (This logic remains the same as your existing good version)
    all_processed_json_files = glob.glob(os.path.join(PROCESSED_JSON_DIR, '*.json'))
    html_regenerated_count = 0
    if all_processed_json_files:
        logger.info(f"Found {len(all_processed_json_files)} processed JSON files to check for HTML regeneration.")
        for proc_json_filepath in all_processed_json_files:
            try:
                article_data_content = load_article_data(proc_json_filepath)
                if not article_data_content or not isinstance(article_data_content, dict): logger.warning(f"Skipping invalid JSON for HTML regen: {os.path.basename(proc_json_filepath)}"); continue
                article_unique_id = article_data_content.get('id'); article_slug_str = article_data_content.get('slug')
                if not article_unique_id or not article_slug_str: logger.warning(f"Skipping JSON missing id/slug for HTML regen: {os.path.basename(proc_json_filepath)}"); continue
                expected_html_file_path = os.path.join(OUTPUT_HTML_DIR, f"{article_slug_str}.html")
                if not os.path.exists(expected_html_file_path):
                    logger.info(f"HTML missing for article ID {article_unique_id} (slug: {article_slug_str}). Regenerating...")
                    seo_agent_results_data = article_data_content.get('seo_agent_results', {}); article_body_md_content = seo_agent_results_data.get('generated_article_body_md', '')
                    article_body_html_output = markdown.markdown(article_body_md_content, extensions=['fenced_code', 'tables', 'nl2br'])
                    current_tags_list = article_data_content.get('generated_tags', []); article_tags_html_output = format_tags_html(current_tags_list)
                    article_publish_datetime_obj = get_sort_key(article_data_content); relative_article_path_str_regen = f"articles/{article_slug_str}.html"
                    page_canonical_url_regen = urljoin(YOUR_SITE_BASE_URL, relative_article_path_str_regen.lstrip('/')) if YOUR_SITE_BASE_URL and YOUR_SITE_BASE_URL != '/' else f"/{relative_article_path_str_regen.lstrip('/')}"
                    template_render_vars_regen = {
                        'PAGE_TITLE': seo_agent_results_data.get('generated_title_tag', article_data_content.get('title')), 'META_DESCRIPTION': seo_agent_results_data.get('generated_meta_description', ''),
                        'AUTHOR_NAME': article_data_content.get('author', AUTHOR_NAME_DEFAULT), 'META_KEYWORDS_LIST': current_tags_list, 'CANONICAL_URL': page_canonical_url_regen,
                        'SITE_NAME': YOUR_WEBSITE_NAME, 'YOUR_WEBSITE_LOGO_URL': YOUR_WEBSITE_LOGO_URL, 'IMAGE_URL': article_data_content.get('selected_image_url', ''),
                        'IMAGE_ALT_TEXT': article_data_content.get('title', 'Article Image'), 'PUBLISH_ISO_FOR_META': article_data_content.get('published_iso', datetime.now(timezone.utc).isoformat()),
                        'JSON_LD_SCRIPT_BLOCK': seo_agent_results_data.get('generated_json_ld', ''), 'ARTICLE_HEADLINE': article_data_content.get('title'),
                        'PUBLISH_DATE': article_publish_datetime_obj.strftime('%B %d, %Y') if article_publish_datetime_obj != datetime(1970,1,1,tzinfo=timezone.utc) else "Date Unknown",
                        'ARTICLE_BODY_HTML': article_body_html_output, 'ARTICLE_TAGS_HTML': article_tags_html_output, 'SOURCE_ARTICLE_URL': article_data_content.get('link', '#'),
                        'ARTICLE_TITLE': article_data_content.get('title'), 'id': article_unique_id, 'CURRENT_ARTICLE_ID': article_unique_id,
                        'CURRENT_ARTICLE_TOPIC': article_data_content.get('topic', ''), 'CURRENT_ARTICLE_TAGS_JSON': json.dumps(current_tags_list),
                        'AUDIO_URL': article_data_content.get('audio_url')}
                    if render_post_page(template_render_vars_regen, article_slug_str): html_regenerated_count += 1
            except Exception as regen_exc: logger.exception(f"Error during HTML regeneration for {os.path.basename(proc_json_filepath)}: {regen_exc}")
    logger.info(f"--- HTML Regeneration Complete. Regenerated {html_regenerated_count} files. ---")

    # --- Scraper ---
    logger.info("--- Stage 2: Running News Scraper ---")
    new_raw_articles_count = 0
    try: new_raw_articles_count = scrape_news(NEWS_FEED_URLS, initial_ids_for_scraper_run)
    except Exception as main_scrape_e: logger.exception(f"News scraper run failed: {main_scrape_e}")
    logger.info(f"News Scraper run completed. Found {new_raw_articles_count} new raw article files.")

    # --- Process Scraped Articles ---
    logger.info("--- Stage 3: Processing Newly Scraped Articles ---")
    all_articles_summary_data_for_run = load_all_articles_data_from_json()
    raw_json_files_to_process_list = sorted(glob.glob(os.path.join(SCRAPED_ARTICLES_DIR, '*.json')), key=os.path.getmtime, reverse=True)
    logger.info(f"Found {len(raw_json_files_to_process_list)} raw scraped articles to process.")

    processed_articles_in_current_run_summaries = []
    successfully_processed_scraped_count = 0; failed_or_skipped_scraped_count = 0
    social_media_payloads_for_posting_queue = []

    # Loop for scraped articles
    for raw_filepath in raw_json_files_to_process_list:
        # ... (same processing logic as before for scraped articles) ...
        # Ensures `social_media_payloads_for_posting_queue.append()` happens if successful
        article_potential_id = os.path.basename(raw_filepath).replace('.json', '')
        if article_potential_id in fully_processed_article_ids_set:
            logger.debug(f"Skipping raw file {article_potential_id}, as a fully processed JSON already exists."); remove_scraped_file(raw_filepath); failed_or_skipped_scraped_count += 1; continue
        single_article_processing_result = process_single_scraped_article(raw_filepath, all_articles_summary_data_for_run, processed_articles_in_current_run_summaries)
        if single_article_processing_result and isinstance(single_article_processing_result, dict):
            successfully_processed_scraped_count += 1
            if "summary" in single_article_processing_result:
                processed_articles_in_current_run_summaries.append(single_article_processing_result["summary"])
                all_articles_summary_data_for_run.append(single_article_processing_result["summary"])
            if "social_post_data" in single_article_processing_result:
                social_media_payloads_for_posting_queue.append(single_article_processing_result["social_post_data"])
        else:
            failed_or_skipped_scraped_count += 1
    logger.info(f"Scraped articles processing cycle complete. Success: {successfully_processed_scraped_count}, Failed/Skipped: {failed_or_skipped_scraped_count}")

    # --- Stage 3.5: Queue Unposted Processed Articles (including Gyro Picks) for Social Media ---
    logger.info("--- Checking ALL Processed Articles (Scraped & Gyro) for Social Media Posting ---")
    social_post_history_data = load_social_post_history()
    already_posted_social_ids = set(social_post_history_data.get('posted_articles', []))
    
    unposted_gyro_or_other_processed_count = 0
    for processed_json_file_path in all_processed_json_files: # Iterate all files in PROCESSED_JSON_DIR
        article_id_from_filename = os.path.basename(processed_json_file_path).replace('.json', '')
        
        if article_id_from_filename not in already_posted_social_ids:
            logger.info(f"Article ID {article_id_from_filename} (from processed_json) not in social history. Checking if it's already queued...")
            # Avoid re-queueing if it was just processed from SCRAPED_ARTICLES_DIR in this run
            if any(payload.get('id') == article_id_from_filename for payload in social_media_payloads_for_posting_queue):
                logger.debug(f"Article {article_id_from_filename} was just processed from scraped; already in social queue.")
                continue

            processed_article_full_data = load_article_data(processed_json_file_path)
            if not processed_article_full_data or not isinstance(processed_article_full_data, dict):
                logger.warning(f"Could not load or invalid data in processed file: {processed_json_file_path}. Skipping for social post check."); continue

            # Construct social media payload for this existing processed article
            article_title_for_social = processed_article_full_data.get('title', 'Untitled')
            article_slug_for_social = processed_article_full_data.get('slug')
            if not article_slug_for_social:
                logger.warning(f"Processed article {article_id_from_filename} missing slug. Cannot form URL for social media. Skipping."); continue
            
            relative_link_for_social = f"articles/{article_slug_for_social}.html"
            canonical_url_for_social = urljoin(YOUR_SITE_BASE_URL, relative_link_for_social.lstrip('/')) if YOUR_SITE_BASE_URL and YOUR_SITE_BASE_URL != '/' else f"/{relative_link_for_social.lstrip('/')}"
            
            payload = {
                "id": article_id_from_filename,
                "title": article_title_for_social,
                "article_url": canonical_url_for_social,
                "image_url": processed_article_full_data.get('selected_image_url'),
                "topic": processed_article_full_data.get('topic'),
                "tags": processed_article_full_data.get('generated_tags', []),
                "summary_short": processed_article_full_data.get('seo_agent_results', {}).get('generated_meta_description', '')
            }
            social_media_payloads_for_posting_queue.append(payload)
            unposted_gyro_or_other_processed_count += 1
            logger.info(f"Added existing processed article {article_id_from_filename} to social media posting queue.")
        else:
            logger.debug(f"Article {article_id_from_filename} already in social post history. Skipping.")
            
    if unposted_gyro_or_other_processed_count > 0:
        logger.info(f"Found {unposted_gyro_or_other_processed_count} existing processed articles (e.g. Gyro Picks) to attempt social media for.")

    # --- Twitter Daily Limit Tracking (Initialize before social posting loop) ---
    current_run_date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    twitter_limit_file_date, twitter_posts_made_today = _read_tweet_tracker()
    if twitter_limit_file_date != current_run_date_str:
        logger.info(f"New day ({current_run_date_str}) for Twitter. Resetting daily post count.")
        twitter_posts_made_today = 0; _write_tweet_tracker(current_run_date_str, 0)
    logger.info(f"Twitter posts made today before this social posting cycle: {twitter_posts_made_today} (Daily Limit: {DAILY_TWEET_LIMIT})")

    # --- Stage 4: Social Media Posting (Unified Loop) ---
    if social_media_payloads_for_posting_queue:
        logger.info(f"--- Attempting to post {len(social_media_payloads_for_posting_queue)} total articles to Social Media ---")
        final_make_webhook_payloads = []

        for social_payload_item in social_media_payloads_for_posting_queue:
            article_id_for_social_post = social_payload_item.get('id')
            # Double check if it somehow got posted between queueing and now (unlikely in single run)
            current_social_history = load_social_post_history() # Load fresh history
            if article_id_for_social_post in current_social_history.get('posted_articles', []):
                logger.info(f"Article {article_id_for_social_post} was already marked in social history before its turn. Skipping.")
                continue

            logger.info(f"Preparing to post article ID: {article_id_for_social_post} ('{social_payload_item.get('title', '')[:40]}...')")
            platforms_to_attempt_post = ["bluesky", "reddit"] # Default
            
            if social_media_clients_glob.get("twitter_client"):
                if twitter_posts_made_today < DAILY_TWEET_LIMIT:
                    platforms_to_attempt_post.append("twitter")
                    logger.info(f"Article {article_id_for_social_post} WILL be attempted on Twitter. (Daily count: {twitter_posts_made_today}/{DAILY_TWEET_LIMIT})")
                else:
                    logger.info(f"Daily Twitter limit ({DAILY_TWEET_LIMIT}) hit. Twitter SKIPPED for {article_id_for_social_post}")
            
            # run_social_media_poster should call mark_article_as_posted_in_history internally
            # after attempting posts, regardless of individual platform success.
            was_tweet_successful = run_social_media_poster(social_payload_item, social_media_clients_glob, platforms_to_post=tuple(platforms_to_attempt_post))
            
            # If Twitter was an attempted platform (i.e., slot was available)
            if "twitter" in platforms_to_attempt_post and social_media_clients_glob.get("twitter_client"):
                twitter_posts_made_today += 1 # Increment for the attempt
                _write_tweet_tracker(current_run_date_str, twitter_posts_made_today)
                logger.info(f"Twitter daily post count for {current_run_date_str} updated to: {twitter_posts_made_today} after attempt for {article_id_for_social_post}.")

            # Add to Make.com payload regardless of individual social media success for this article,
            # as long as it was processed.
            if MAKE_WEBHOOK_URL:
                final_make_webhook_payloads.append(social_payload_item)
            
            time.sleep(10) # Delay between posting different articles

        if MAKE_WEBHOOK_URL and final_make_webhook_payloads:
            logger.info(f"--- Sending {len(final_make_webhook_payloads)} items to Make.com Webhook ---")
            if send_make_webhook(MAKE_WEBHOOK_URL, final_make_webhook_payloads): logger.info("Batched Make.com webhook sent successfully.")
            else: logger.error("Batched Make.com webhook failed.")
    else:
        logger.info("No new articles queued for social media posting in this run.")

    # --- Stage 5: Generating Sitemap ---
    # ... (Sitemap generation logic remains the same, at the end) ...
    logger.info("--- Stage 5: Generating Sitemap ---")
    if not YOUR_SITE_BASE_URL or YOUR_SITE_BASE_URL == '/':
        logger.error("Sitemap generation SKIPPED: YOUR_SITE_BASE_URL is not set or is invalid ('/').")
    else:
        try: run_sitemap_generator(); logger.info("Sitemap generation completed successfully.")
        except Exception as main_sitemap_e: logger.exception(f"Sitemap generation failed: {main_sitemap_e}")

    run_end_timestamp = time.time()
    logger.info(f"--- === Dacoola AI News Orchestrator Run Finished ({run_end_timestamp - run_start_timestamp:.2f} seconds) === ---")