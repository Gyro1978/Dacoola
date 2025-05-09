# src/main.py (1/1) - FULL SCRIPT with Keyword Research & Corrected Tag Handling

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
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin
import markdown

# --- Import Sitemap Generator ---
try:
    sys.path.insert(0, PROJECT_ROOT_FOR_PATH)
    from generate_sitemap import generate_sitemap as run_sitemap_generator
except ImportError as e:
    temp_log_msg = f"FATAL IMPORT ERROR: Could not import sitemap generator: {e}."
    print(temp_log_msg); logging.critical(temp_log_msg); sys.exit(1)

# --- Import Agent and Scraper Functions ---
try:
    from src.scrapers.news_scraper import (
        scrape_news, load_processed_ids, save_processed_id, get_article_id,
        NEWS_FEED_URLS, DATA_DIR as SCRAPER_DATA_DIR
    )
    from src.scrapers.image_scraper import find_best_image, scrape_source_for_image
    from src.agents.filter_news_agent import run_filter_agent
    from src.agents.keyword_research_agent import run_keyword_research_agent # NEW
    from src.agents.seo_article_generator_agent import run_seo_article_agent
    from src.social.twitter_poster import post_tweet_with_image
    # --- Import for new social poster ---
    from src.social.social_media_poster import initialize_social_clients, run_social_media_poster
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
# MAKE_WEBHOOK_URL is no longer primary, but keep if still used for some platforms
MAKE_WEBHOOK_URL = os.getenv('MAKE_INSTAGRAM_WEBHOOK_URL', None)

# --- Setup Logging ---
log_file_path = os.path.join(PROJECT_ROOT_FOR_PATH, 'dacola.log')
try:
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    log_handlers = [ logging.StreamHandler(sys.stdout), logging.FileHandler(log_file_path, encoding='utf-8') ]
except OSError as e: print(f"Log setup warning: {e}. Log console only."); log_handlers = [logging.StreamHandler(sys.stdout)]
logging.basicConfig( level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S', handlers=log_handlers, force=True )
logger = logging.getLogger('main_orchestrator')
if not YOUR_SITE_BASE_URL: logger.warning("YOUR_SITE_BASE_URL not set.")
else: logger.info(f"Using site base URL: {YOUR_SITE_BASE_URL}")
if not YOUR_WEBSITE_LOGO_URL: logger.warning("YOUR_WEBSITE_LOGO_URL not set.")
# if not MAKE_WEBHOOK_URL: logger.warning("MAKE_INSTAGRAM_WEBHOOK_URL not set (Make.com webhook posting will be skipped).")

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
ARTICLE_MAX_AGE_DAYS = 30

# --- Jinja2 Setup ---
try:
    from jinja2 import Environment, FileSystemLoader
    def escapejs_filter(value): # Ensure this is defined before use
        if value is None: return ''; value = str(value); value = value.replace('\\', '\\\\').replace('"', '\\"').replace('/', '\\/')
        value = value.replace('<', '\\u003c').replace('>', '\\u003e'); value = value.replace('\b', '\\b').replace('\f', '\\f').replace('\n', '\\n')
        value = value.replace('\r', '\\r').replace('\t', '\\t'); return value
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True); env.filters['escapejs'] = escapejs_filter
    logger.info(f"Jinja2 environment loaded from {TEMPLATE_DIR}")
except Exception as e: logger.exception(f"CRITICAL: Failed Jinja2 init. Exiting."); sys.exit(1)

# --- Helper Functions ---
def ensure_directories():
    dirs_to_create = [ DATA_DIR_MAIN, SCRAPED_ARTICLES_DIR, PROCESSED_JSON_DIR, PUBLIC_DIR, OUTPUT_HTML_DIR, TEMPLATE_DIR ]
    try: [os.makedirs(d, exist_ok=True) for d in dirs_to_create]; logger.info("Ensured core directories exist.")
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
            tag_links.append(f'<a href="{tag_url}" class="tag-link">{tag}</a>')
        return ", ".join(tag_links)
    except Exception as e: logger.error(f"Error formatting tags: {tags_list} - {e}"); return ""

def get_sort_key(article_dict):
    fallback_date = datetime(1970, 1, 1, tzinfo=timezone.utc)
    date_str = article_dict.get('published_iso')
    if not date_str or not isinstance(date_str, str): return fallback_date
    try:
        if date_str.endswith('Z'): date_str = date_str[:-1] + '+00:00'
        dt = datetime.fromisoformat(date_str)
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None: return dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception: return fallback_date # Simplified error handling

def _read_tweet_tracker():
    try:
        if os.path.exists(TWITTER_TRACKER_FILE):
            with open(TWITTER_TRACKER_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
            if isinstance(data, dict) and 'date' in data and 'count' in data and \
               isinstance(data.get('date'), str) and isinstance(data.get('count'), int):
                return data['date'], data['count']
        return None, 0
    except Exception: return None, 0

def _write_tweet_tracker(date_str, count):
    try:
        os.makedirs(os.path.dirname(TWITTER_TRACKER_FILE), exist_ok=True)
        with open(TWITTER_TRACKER_FILE, 'w', encoding='utf-8') as f: json.dump({'date': date_str, 'count': count}, f)
        logger.info(f"Updated tweet tracker: Date={date_str}, Count={count}")
    except Exception as e: logger.error(f"Error writing tweet tracker: {e}")

# send_make_webhook is kept for now if you still use it for some platforms like Instagram
def send_make_webhook(webhook_url, data):
    if not webhook_url: logger.warning("Make webhook URL missing."); return False
    if not data: logger.warning("No data for Make webhook."); return False
    payload = {"articles": data} if isinstance(data, list) else data
    log_id_info = f"batch of {len(data)} articles" if isinstance(data, list) else f"article ID: {data.get('id', 'N/A')}"
    try:
        response = requests.post(webhook_url, headers={'Content-Type': 'application/json'}, json=payload, timeout=30)
        response.raise_for_status()
        logger.info(f"Successfully sent to Make webhook for {log_id_info}")
        return True
    except Exception as e: logger.error(f"Failed send to Make webhook for {log_id_info}: {e}"); return False

def render_post_page(template_variables, slug_base):
    try:
        template = env.get_template('post_template.html')
        html_content = template.render(template_variables)
        safe_filename = slug_base if slug_base else template_variables.get('id', 'untitled')
        safe_filename = re.sub(r'[<>:"/\\|?*%\.]+', '', safe_filename).strip().lower().replace(' ', '-')
        safe_filename = re.sub(r'-+', '-', safe_filename).strip('-')[:80] or template_variables.get('id', 'untitled_fallback')
        output_path = os.path.join(OUTPUT_HTML_DIR, f"{safe_filename}.html")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f: f.write(html_content)
        logger.info(f"Rendered HTML: {os.path.basename(output_path)}")
        return output_path
    except Exception as e: logger.exception(f"CRITICAL: Failed render HTML {template_variables.get('id','N/A')}: {e}"); return None

def load_all_articles_data():
    if not os.path.exists(ALL_ARTICLES_FILE): return []
    try:
        with open(ALL_ARTICLES_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get('articles'), list): return data['articles']
    except Exception: pass
    return []

def update_all_articles_json(new_article_info):
    all_articles_container = {"articles": load_all_articles_data()}
    article_id = new_article_info.get('id')
    if not article_id: logger.error("Update all_articles.json: missing 'id'."); return

    minimal_entry = {
        "id": article_id, "title": new_article_info.get('title'), "link": new_article_info.get('link'),
        "published_iso": new_article_info.get('published_iso'), "summary_short": new_article_info.get('summary_short'),
        "image_url": new_article_info.get('image_url'), "topic": new_article_info.get('topic'),
        "is_breaking": new_article_info.get('is_breaking', False), "tags": new_article_info.get('tags', []),
        "audio_url": None, "trend_score": new_article_info.get('trend_score', 0)
    }
    if not minimal_entry['link'] or not minimal_entry['title']: logger.error(f"Skip update all_articles.json {article_id}: missing link/title."); return

    current_articles = all_articles_container.setdefault("articles", [])
    index_to_update = next((i for i, art in enumerate(current_articles) if isinstance(art, dict) and art.get('id') == article_id), -1)
    if index_to_update != -1: current_articles[index_to_update].update(minimal_entry)
    else: current_articles.append(minimal_entry)
    current_articles.sort(key=get_sort_key, reverse=True)
    try:
        with open(ALL_ARTICLES_FILE, 'w', encoding='utf-8') as f: json.dump(all_articles_container, f, indent=2, ensure_ascii=False)
        logger.info(f"Updated {os.path.basename(ALL_ARTICLES_FILE)} ({len(current_articles)} articles).")
    except Exception as e: logger.error(f"Failed to save {os.path.basename(ALL_ARTICLES_FILE)}: {e}")

# --- Main Processing Function ---
def process_single_article(json_filepath, existing_articles_data, processed_in_this_run_context):
    article_filename = os.path.basename(json_filepath)
    logger.info(f"--- Processing article file: {article_filename} ---")
    article_data = load_article_data(json_filepath)
    if not article_data or not isinstance(article_data, dict):
        logger.error(f"Failed load/invalid data {article_filename}. Skipping."); remove_scraped_file(json_filepath); return None

    article_id = article_data.get('id') or get_article_id(article_data, article_data.get('source_feed', 'unknown_feed'))
    article_data['id'] = article_id
    processed_file_path = os.path.join(PROCESSED_JSON_DIR, f"{article_id}.json")

    try:
        if os.path.exists(processed_file_path):
             logger.info(f"Article ID {article_id} already processed. Skipping raw."); remove_scraped_file(json_filepath); return None

        publish_date_iso = article_data.get('published_iso')
        if publish_date_iso:
            publish_dt = get_sort_key(article_data)
            if publish_dt < (datetime.now(timezone.utc) - timedelta(days=ARTICLE_MAX_AGE_DAYS)):
                logger.info(f"Article {article_id} too old ({publish_dt.date()}). Skipping."); remove_scraped_file(json_filepath); return None
        else: logger.warning(f"Article {article_id} missing publish date. Proceeding.")

        logger.info(f"Finding image for article ID: {article_id}...")
        selected_image_url = scrape_source_for_image(article_data.get('link')) or find_best_image(article_data.get('title', 'AI News'))
        if not selected_image_url: logger.error(f"FATAL: No image for {article_id}. Skipping."); remove_scraped_file(json_filepath); return None
        article_data['selected_image_url'] = selected_image_url

        current_title_lower = article_data.get('title', '').strip().lower()
        if not current_title_lower: logger.error(f"Article {article_id} empty title. Skipping."); remove_scraped_file(json_filepath); return None
        for existing_art in existing_articles_data + processed_in_this_run_context:
            if isinstance(existing_art, dict) and existing_art.get('title','').strip().lower() == current_title_lower and existing_art.get('image_url') == selected_image_url:
                logger.warning(f"Article {article_id} DUPLICATE (Title & Image) of {existing_art.get('id', 'N/A')}. Skipping."); remove_scraped_file(json_filepath); return None
        logger.info(f"Article {article_id} passed Title+Image duplicate check.")

        # --- Agent Pipeline ---
        # 1. Filter
        article_data = run_filter_agent(article_data)
        if not article_data or article_data.get('filter_verdict') is None: logger.error(f"Filter Agent failed {article_id}. Skip."); remove_scraped_file(json_filepath); return None
        filter_verdict = article_data['filter_verdict']; importance = filter_verdict.get('importance_level')
        if importance == "Boring": logger.info(f"Article {article_id} 'Boring'. Skipping."); remove_scraped_file(json_filepath); return None
        article_data['topic'] = filter_verdict.get('topic', 'Other')
        article_data['is_breaking'] = (importance == "Breaking")
        article_data['primary_keyword'] = filter_verdict.get('primary_topic_keyword', article_data.get('title',''))
        logger.info(f"Article {article_id} classified {importance} (Topic: {article_data['topic']}).")

        # 2. Keyword Research
        article_data = run_keyword_research_agent(article_data)
        if article_data.get('keyword_agent_error'): logger.warning(f"Keyword Research issue for {article_id}: {article_data['keyword_agent_error']}")
        researched_keywords = article_data.setdefault('researched_keywords', [])
        if not researched_keywords: researched_keywords.append(article_data['primary_keyword']); article_data['researched_keywords'] = list(set(researched_keywords))
        article_data['generated_tags'] = list(set(researched_keywords)) # Use researched for final tags
        logger.info(f"Using {len(article_data['generated_tags'])} keywords as tags for {article_id}.")

        # 3. SEO Article Generation
        article_data['_temp_keywords_for_seo_prompt'] = json.dumps(article_data['generated_tags']) # Use final tags for SEO prompt
        article_data = run_seo_article_agent(article_data)
        article_data.pop('_temp_keywords_for_seo_prompt', None)
        seo_results = article_data.get('seo_agent_results')
        if not seo_results or not seo_results.get('generated_article_body_md'): logger.error(f"SEO Agent failed {article_id}. Skip."); remove_scraped_file(json_filepath); return None
        if article_data.get('seo_agent_error'): logger.warning(f"SEO Agent non-critical errors for {article_id}: {article_data['seo_agent_error']}")

        # Trend Score
        trend_score = 0.0; tags_count = len(article_data['generated_tags'])
        if importance == "Interesting": trend_score += 5.0
        elif importance == "Breaking": trend_score += 10.0
        trend_score += float(tags_count) * 0.5
        if publish_date_iso:
            publish_dt = get_sort_key(article_data); now_utc = datetime.now(timezone.utc)
            if publish_dt <= now_utc and (days_old := (now_utc - publish_dt).total_seconds() / 86400.0) <= ARTICLE_MAX_AGE_DAYS:
                trend_score += max(0.0, 1.0 - (days_old / float(ARTICLE_MAX_AGE_DAYS))) * 5.0
        article_data['trend_score'] = round(max(0.0, trend_score), 2)

        # Slug & URL
        slug = re.sub(r'[<>:"/\\|?*%\.\'"]+', '', article_data.get('title', f'article-{article_id}')).strip().lower().replace(' ', '-')
        article_data['slug'] = re.sub(r'-+', '-', slug).strip('-')[:80] or f'article-{article_id}'
        article_relative_path = f"articles/{article_data['slug']}.html"
        canonical_url = urljoin(YOUR_SITE_BASE_URL.rstrip('/') + '/', article_relative_path.lstrip('/')) if YOUR_SITE_BASE_URL else f"/{article_relative_path.lstrip('/')}"

        # HTML Rendering
        body_md = seo_results.get('generated_article_body_md', ''); body_html = markdown.markdown(body_md, extensions=['fenced_code', 'tables', 'nl2br'])
        tags_html = format_tags_html(article_data['generated_tags'])
        publish_dt_obj = get_sort_key(article_data)
        template_vars = {
            'PAGE_TITLE': seo_results.get('generated_title_tag', article_data.get('title')), 'META_DESCRIPTION': seo_results.get('generated_meta_description', ''),
            'AUTHOR_NAME': article_data.get('author', AUTHOR_NAME_DEFAULT), 'META_KEYWORDS': ", ".join(article_data['generated_tags']),
            'CANONICAL_URL': canonical_url, 'SITE_NAME': YOUR_WEBSITE_NAME, 'YOUR_WEBSITE_LOGO_URL': YOUR_WEBSITE_LOGO_URL,
            'IMAGE_URL': article_data.get('selected_image_url', ''), 'IMAGE_ALT_TEXT': article_data.get('title'),
            'META_KEYWORDS_LIST': article_data['generated_tags'], 'PUBLISH_ISO_FOR_META': publish_date_iso or datetime.now(timezone.utc).isoformat(),
            'JSON_LD_SCRIPT_BLOCK': seo_results.get('generated_json_ld', ''), 'ARTICLE_HEADLINE': article_data.get('title'),
            'PUBLISH_DATE': publish_dt_obj.strftime('%B %d, %Y') if publish_dt_obj != datetime(1970,1,1,tzinfo=timezone.utc) else "Date Unknown",
            'ARTICLE_BODY_HTML': body_html, 'ARTICLE_TAGS_HTML': tags_html, 'SOURCE_ARTICLE_URL': article_data.get('link', '#'),
            'ARTICLE_TITLE': article_data.get('title'), 'id': article_id, 'CURRENT_ARTICLE_ID': article_id,
            'CURRENT_ARTICLE_TOPIC': article_data.get('topic', ''), 'CURRENT_ARTICLE_TAGS_JSON': json.dumps(article_data['generated_tags']),
            'AUDIO_URL': None
        }
        if not render_post_page(template_vars, article_data['slug']): logger.error(f"Failed HTML render for {article_id}. Skip."); return None

        # Update JSON and Socials
        site_data_entry = {"id": article_id, "title": article_data.get('title'), "link": article_relative_path, "published_iso": template_vars['PUBLISH_ISO_FOR_META'],
                           "summary_short": template_vars['META_DESCRIPTION'], "image_url": article_data.get('selected_image_url'), "topic": article_data.get('topic', 'News'),
                           "is_breaking": article_data.get('is_breaking', False), "tags": article_data['generated_tags'], "audio_url": None, "trend_score": article_data.get('trend_score', 0)}
        article_data['audio_url'] = None # Final set
        update_all_articles_json(site_data_entry)

        # Twitter Posting
        today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d'); tracker_date, count_today = _read_tweet_tracker()
        if tracker_date != today_str: count_today = 0; _write_tweet_tracker(today_str, count_today)
        if count_today < DAILY_TWEET_LIMIT:
            if post_tweet_with_image(article_data.get('title'), canonical_url, article_data.get('selected_image_url')):
                _write_tweet_tracker(today_str, count_today + 1)
        else: logger.info(f"Daily Twitter limit reached. Skip for {article_id}.")

        webhook_data_for_socials = {"id": article_id, "title": article_data.get('title'), "article_url": canonical_url,
                                   "image_url": article_data.get('selected_image_url'), "topic": article_data.get('topic'),
                                   "tags": article_data['generated_tags'], "summary_short": site_data_entry.get('summary_short', '')}

        if save_processed_data(processed_file_path, article_data):
             remove_scraped_file(json_filepath)
             logger.info(f"--- Successfully processed article: {article_id} ---")
             return {"summary": {"id": article_id, "title": article_data.get("title"), "image_url": article_data.get("selected_image_url")},
                     "social_post_data": webhook_data_for_socials } # Changed key
        else: logger.error(f"Failed save final JSON for {article_id}."); return None
    except Exception as process_e:
         logger.exception(f"CRITICAL failure processing {article_id} ({article_filename}): {process_e}")
         if os.path.exists(json_filepath): remove_scraped_file(json_filepath)
         return None

# --- Main Orchestration Logic ---
if __name__ == "__main__":
    run_start_time = time.time()
    logger.info(f"--- === Dacoola AI News Orchestrator Starting Run ({datetime.now(timezone.utc).isoformat()}) === ---")
    ensure_directories()

    # --- Initialize Social Media Clients ONCE ---
    social_media_clients = initialize_social_clients() # NEW

    glob_pattern = os.path.join(PROCESSED_JSON_DIR, '*.json')
    completed_article_ids = set(os.path.basename(f).replace('.json', '') for f in glob.glob(glob_pattern))
    logger.info(f"Found {len(completed_article_ids)} already fully processed articles.")

    scraper_processed_ids_on_disk = load_processed_ids()
    initial_processed_ids_for_scraper = scraper_processed_ids_on_disk.union(completed_article_ids)
    logger.info(f"Total initial processed IDs passed to scraper: {len(initial_processed_ids_for_scraper)}")

    # --- HTML Regeneration Step ---
    logger.info("--- Stage 1: Checking for Missing HTML from Processed Data ---")
    # ... (HTML Regeneration logic remains the same) ...
    processed_json_files_for_regen = glob.glob(os.path.join(PROCESSED_JSON_DIR, '*.json'))
    regenerated_count = 0
    if processed_json_files_for_regen:
        logger.info(f"Found {len(processed_json_files_for_regen)} processed JSON files to check for HTML regeneration.")
        for proc_filepath in processed_json_files_for_regen:
            try:
                article_data = load_article_data(proc_filepath)
                if not article_data or not isinstance(article_data, dict): logger.warning(f"Skipping invalid processed JSON during regen: {os.path.basename(proc_filepath)}"); continue
                article_id = article_data.get('id'); slug = article_data.get('slug')
                if not article_id or not slug: logger.warning(f"Skipping processed JSON missing id or slug during regen: {os.path.basename(proc_filepath)}"); continue
                expected_html_path = os.path.join(OUTPUT_HTML_DIR, f"{slug}.html")
                if not os.path.exists(expected_html_path):
                    logger.info(f"HTML missing for {article_id} ({slug}.html). Regenerating...")
                    seo_results = article_data.get('seo_agent_results', {})
                    body_md = seo_results.get('generated_article_body_md', '')
                    body_html = f"<p><i>Content generation error.</i></p><pre>{body_md}</pre>"
                    try: body_html = markdown.markdown(body_md, extensions=['fenced_code', 'tables', 'nl2br'])
                    except Exception as md_err: logger.error(f"Markdown failed during regen {article_id}: {md_err}")
                    tags_list = article_data.get('generated_tags', [])
                    tags_html = format_tags_html(tags_list)
                    publish_date_iso_for_meta = article_data.get('published_iso', datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
                    publish_date_formatted = "Date Unknown"; publish_dt_obj = get_sort_key(article_data)
                    if publish_dt_obj != datetime(1970,1,1,tzinfo=timezone.utc): publish_date_formatted = publish_dt_obj.strftime('%B %d, %Y')
                    page_title = seo_results.get('generated_title_tag', article_data.get('title', 'AI News'))
                    meta_description = seo_results.get('generated_meta_description', article_data.get('summary', '')[:160])
                    article_relative_path = f"articles/{slug}.html"
                    canonical_url = urljoin(YOUR_SITE_BASE_URL.rstrip('/') + '/', article_relative_path.lstrip('/')) if YOUR_SITE_BASE_URL else f"/{article_relative_path.lstrip('/')}"
                    template_vars = {
                        'PAGE_TITLE': page_title, 'META_DESCRIPTION': meta_description, 'AUTHOR_NAME': article_data.get('author', AUTHOR_NAME_DEFAULT),
                        'META_KEYWORDS': ", ".join(tags_list), 'CANONICAL_URL': canonical_url, 'SITE_NAME': YOUR_WEBSITE_NAME, 'YOUR_WEBSITE_LOGO_URL': YOUR_WEBSITE_LOGO_URL,
                        'IMAGE_URL': article_data.get('selected_image_url', ''), 'IMAGE_ALT_TEXT': page_title, 'META_KEYWORDS_LIST': tags_list,
                        'PUBLISH_ISO_FOR_META': publish_date_iso_for_meta, 'JSON_LD_SCRIPT_BLOCK': seo_results.get('generated_json_ld', ''),
                        'ARTICLE_HEADLINE': article_data.get('title', 'Article'), 'PUBLISH_DATE': publish_date_formatted, 'ARTICLE_BODY_HTML': body_html,
                        'ARTICLE_TAGS_HTML': tags_html, 'SOURCE_ARTICLE_URL': article_data.get('link', '#'), 'ARTICLE_TITLE': article_data.get('title'),
                        'id': article_id, 'CURRENT_ARTICLE_ID': article_id, 'CURRENT_ARTICLE_TOPIC': article_data.get('topic', ''),
                        'CURRENT_ARTICLE_TAGS_JSON': json.dumps(tags_list), 'AUDIO_URL': article_data.get('audio_url')
                    }
                    if render_post_page(template_vars, slug): regenerated_count += 1
                    else: logger.error(f"Failed to regenerate HTML for {article_id}.")
            except Exception as regen_e: logger.exception(f"Error during HTML regeneration for {os.path.basename(proc_filepath)}: {regen_e}")
    else: logger.info("No processed JSON files to check for regeneration.")
    logger.info(f"--- HTML Regeneration Check Complete. Regenerated {regenerated_count} files. ---")


    # --- Scraper and Processing Cycle ---
    logger.info("--- Stage 2: Running News Scraper ---")
    new_articles_found_count = 0
    try: new_articles_found_count = scrape_news(NEWS_FEED_URLS, initial_processed_ids_for_scraper)
    except Exception as scrape_e: logger.exception(f"Scraper error: {scrape_e}")
    logger.info(f"Scraper run completed. Saved {new_articles_found_count} new raw files.")

    logger.info("--- Stage 3: Running Processing Cycle ---")
    existing_articles_data = load_all_articles_data()
    logger.info(f"Loaded {len(existing_articles_data)} articles for context.")
    json_files_to_process = sorted(glob.glob(os.path.join(SCRAPED_ARTICLES_DIR, '*.json')), key=os.path.getmtime, reverse=True)
    logger.info(f"Found {len(json_files_to_process)} scraped articles to process (sorted newest first).")

    # --- Batching for Social Media Poster ---
    all_social_post_data_this_run = []

    processed_successfully_count = 0; failed_or_skipped_count = 0
    processed_in_this_run_context = [] # For duplicate checks within the same run

    for filepath in json_files_to_process:
        potential_id = os.path.basename(filepath).replace('.json', '')
        if potential_id in completed_article_ids:
            logger.debug(f"Skipping raw {potential_id}, processed JSON exists."); remove_scraped_file(filepath); failed_or_skipped_count += 1; continue

        processing_result = process_single_article(filepath, existing_articles_data, processed_in_this_run_context)

        if processing_result and isinstance(processing_result, dict):
            processed_successfully_count += 1
            if "summary" in processing_result: processed_in_this_run_context.append(processing_result["summary"])
            if "social_post_data" in processing_result: all_social_post_data_this_run.append(processing_result["social_post_data"]) # Collect for batch
            # Update existing_articles_data in memory for subsequent duplicate checks in this run
            if "summary" in processing_result and isinstance(processing_result["summary"], dict): existing_articles_data.append(processing_result["summary"])

        else: failed_or_skipped_count += 1

    logger.info(f"Processing cycle complete. Success: {processed_successfully_count}, Failed/Skipped/Duplicate: {failed_or_skipped_count}")

    # --- Send to new Social Media Poster (Batch or individual) ---
    if all_social_post_data_this_run:
        logger.info(f"--- Stage 3.5: Posting to Social Media ({len(all_social_post_data_this_run)} articles) ---")
        # Decide if you want to post one by one or batch (if poster supports batching for some platforms)
        for social_data in all_social_post_data_this_run:
            run_social_media_poster(social_data, social_media_clients) # Pass initialized clients
            time.sleep(10) # Add a delay between posting different articles to avoid rapid fire
    else:
        logger.info("No successful articles processed in this run to post to social media.")

    # --- Make.com Webhook (if still used for some things like Instagram) ---
    if MAKE_WEBHOOK_URL and all_social_post_data_this_run: # Or use a different trigger for Make
        logger.info(f"--- Sending to Make.com Webhook for remaining platforms ({len(all_social_post_data_this_run)} potential articles) ---")
        # You might want to filter/transform all_social_post_data_this_run if Make expects a different format
        if send_make_webhook(MAKE_WEBHOOK_URL, all_social_post_data_this_run): # Example: sending all
            logger.info("Batched Make.com webhook sent successfully.")
        else:
            logger.error("Batched Make.com webhook failed.")


    # --- Sitemap Generation ---
    logger.info("--- Stage 4: Generating Sitemap ---")
    if not YOUR_SITE_BASE_URL: logger.error("Sitemap generation SKIPPED: YOUR_SITE_BASE_URL is not set.")
    else:
        try: run_sitemap_generator(); logger.info("Sitemap generation completed successfully.")
        except Exception as sitemap_e: logger.exception(f"Sitemap generation failed: {sitemap_e}")

    run_end_time = time.time()
    logger.info(f"--- === Dacoola AI News Orchestrator Run Finished ({run_end_time - run_start_time:.2f} seconds) === ---")