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
    from src.scrapers.news_scraper import (
        scrape_news, load_processed_ids, save_processed_id, get_article_id,
        NEWS_FEED_URLS, DATA_DIR as SCRAPER_DATA_DIR
    )
    from src.scrapers.image_scraper import find_best_image, scrape_source_for_image
    # ** IMPORT AGENTS **
    from src.agents.filter_news_agent import run_filter_agent
    from src.agents.similarity_check_agent import run_similarity_check_agent
    from src.agents.seo_article_generator_agent import run_seo_article_agent
    from src.agents.tags_generator_agent import run_tags_generator_agent
    # ** IMPORT SOCIAL POSTER **
    from src.social.twitter_poster import post_tweet_with_image

except ImportError as e:
     print(f"FATAL IMPORT ERROR in main.py: {e}")
     print("Check file names, function definitions, and __init__.py files in src/ and subfolders.")
     try: logging.critical(f"FATAL IMPORT ERROR: {e}")
     except: pass
     sys.exit(1)


# --- Load Environment Variables ---
dotenv_path = os.path.join(PROJECT_ROOT_FOR_PATH, '.env')
load_dotenv(dotenv_path=dotenv_path)

# MAX_HOME_PAGE_ARTICLES only relevant for JS rendering now
AUTHOR_NAME_DEFAULT = os.getenv('AUTHOR_NAME', 'AI News Team')
YOUR_WEBSITE_NAME = os.getenv('YOUR_WEBSITE_NAME', 'Dacoola')
YOUR_WEBSITE_LOGO_URL = os.getenv('YOUR_WEBSITE_LOGO_URL', '')
raw_base_url = os.getenv('YOUR_SITE_BASE_URL', '')
YOUR_SITE_BASE_URL = (raw_base_url.rstrip('/') + '/') if raw_base_url else ''
MAKE_WEBHOOK_URL = os.getenv('MAKE_INSTAGRAM_WEBHOOK_URL', None)


# --- Setup Logging ---
log_file_path = os.path.join(PROJECT_ROOT_FOR_PATH, 'dacoola.log')
try:
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    log_handlers = [ logging.StreamHandler(sys.stdout), logging.FileHandler(log_file_path, encoding='utf-8') ]
except OSError as e:
    print(f"Log setup warning: {e}. Logging to console only.")
    log_handlers = [logging.StreamHandler(sys.stdout)]
logging.basicConfig( level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S', handlers=log_handlers, force=True )
logger = logging.getLogger('main_orchestrator')

if not YOUR_SITE_BASE_URL: logger.warning("YOUR_SITE_BASE_URL not set.")
else: logger.info(f"Using site base URL: {YOUR_SITE_BASE_URL}")
if not YOUR_WEBSITE_LOGO_URL: logger.warning("YOUR_WEBSITE_LOGO_URL not set.")
if not MAKE_WEBHOOK_URL: logger.warning("MAKE_INSTAGRAM_WEBHOOK_URL not set.")


# --- Configuration ---
DATA_DIR_MAIN = os.path.join(PROJECT_ROOT_FOR_PATH, 'data')
SCRAPED_ARTICLES_DIR = os.path.join(DATA_DIR_MAIN, 'scraped_articles')
PROCESSED_JSON_DIR = os.path.join(DATA_DIR_MAIN, 'processed_json')
PUBLIC_DIR = os.path.join(PROJECT_ROOT_FOR_PATH, 'public')
OUTPUT_HTML_DIR = os.path.join(PUBLIC_DIR, 'articles')
TEMPLATE_DIR = os.path.join(PROJECT_ROOT_FOR_PATH, 'templates')
# SITE_DATA_FILE REMOVED
ALL_ARTICLES_FILE = os.path.join(PUBLIC_DIR, 'all_articles.json') # Single source
DAILY_TWEET_LIMIT = 3
TWITTER_TRACKER_FILE = os.path.join(DATA_DIR_MAIN, 'twitter_daily_limit.json')


# --- Jinja2 Setup ---
try:
    def escapejs_filter(value):
        if value is None: return ''
        value = str(value); value = value.replace('\\', '\\\\').replace('"', '\\"').replace('/', '\\/')
        value = value.replace('<', '\\u003c').replace('>', '\\u003e'); value = value.replace('\b', '\\b').replace('\f', '\\f').replace('\n', '\\n')
        value = value.replace('\r', '\\r').replace('\t', '\\t'); return value
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True); env.filters['escapejs'] = escapejs_filter
    logger.info(f"Jinja2 environment loaded from {TEMPLATE_DIR}")
except Exception as e: logger.exception(f"CRITICAL: Failed Jinja2 init. Exiting."); sys.exit(1)

# --- Helper Functions (Keep all previous helper functions) ---
def ensure_directories():
    dirs_to_create = [ DATA_DIR_MAIN, SCRAPED_ARTICLES_DIR, PROCESSED_JSON_DIR, PUBLIC_DIR, OUTPUT_HTML_DIR, TEMPLATE_DIR ]
    try:
        for dir_path in dirs_to_create: os.makedirs(dir_path, exist_ok=True)
        logger.info("Ensured core directories exist.")
    except OSError as e: logger.exception(f"CRITICAL: Could not create directory {e.filename}: {e.strerror}"); sys.exit(1)

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
        for tag in tags_list: safe_tag = requests.utils.quote(str(tag)); tag_links.append(f'<span class="tag-item"><a href="/topic.html?name={safe_tag}">{tag}</a></span>')
        return " ".join(tag_links)
    except Exception as e: logger.error(f"Error formatting tags: {tags_list} - {e}"); return ""

def get_sort_key(article_dict):
    fallback_date = datetime(1970, 1, 1, tzinfo=timezone.utc); date_str = article_dict.get('published_iso')
    if not date_str or not isinstance(date_str, str): return fallback_date
    try:
        if date_str.endswith('Z'): date_str = date_str[:-1] + '+00:00'
        dt = datetime.fromisoformat(date_str)
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None: return dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception as e: logger.warning(f"Date parse error {article_dict.get('id', 'N/A')}: {e}. Fallback."); return fallback_date

def _read_tweet_tracker():
    try:
        if os.path.exists(TWITTER_TRACKER_FILE):
            with open(TWITTER_TRACKER_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
            if 'date' in data and 'count' in data: return data.get('date'), data.get('count', 0)
            else: logger.warning(f"Tweet tracker invalid. Reset."); return None, 0
        else: return None, 0
    except Exception as e: logger.error(f"Error read tweet tracker: {e}. Reset."); return None, 0

def _write_tweet_tracker(date_str, count):
    try:
        os.makedirs(os.path.dirname(TWITTER_TRACKER_FILE), exist_ok=True)
        with open(TWITTER_TRACKER_FILE, 'w', encoding='utf-8') as f: json.dump({'date': date_str, 'count': count}, f)
        logger.debug(f"Updated tweet tracker: Date={date_str}, Count={count}")
    except IOError as e: logger.error(f"Error write tweet tracker: {e}")

def send_make_webhook(webhook_url, data):
    if not webhook_url: logger.warning("Make webhook URL missing. Skip."); return False
    if not data: logger.warning("No data for Make webhook. Skip."); return False
    try:
        headers = {'Content-Type': 'application/json'}; response = requests.post(webhook_url, headers=headers, json=data, timeout=15)
        response.raise_for_status(); logger.info(f"Sent data to Make webhook {data.get('id', 'N/A')}"); return True
    except requests.exceptions.Timeout: logger.error("Make webhook timed out."); return False
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed send to Make webhook: {e}")
        if e.response is not None: logger.error(f"Webhook Resp: {e.response.status_code} Body: {e.response.text[:500]}")
        return False
    except Exception as e: logger.exception(f"Unexpected Make webhook error: {e}"); return False

def render_post_page(template_variables, slug_base):
    try:
        template = env.get_template('post_template.html')
        required_vars = ['PAGE_TITLE','META_DESCRIPTION','CANONICAL_URL','IMAGE_URL','IMAGE_ALT_TEXT','PUBLISH_ISO_FOR_META','AUTHOR_NAME','SITE_NAME','YOUR_WEBSITE_LOGO_URL','META_KEYWORDS_LIST','JSON_LD_SCRIPT_BLOCK','ARTICLE_HEADLINE','PUBLISH_DATE','ARTICLE_BODY_HTML','ARTICLE_TAGS_HTML','SOURCE_ARTICLE_URL','ARTICLE_TITLE','id','CURRENT_ARTICLE_ID','CURRENT_ARTICLE_TOPIC','CURRENT_ARTICLE_TAGS_JSON','AUDIO_URL']
        for key in required_vars: template_variables.setdefault(key, '')
        html_content = template.render(template_variables)
        safe_filename = slug_base if slug_base else template_variables.get('id', 'untitled'); safe_filename = re.sub(r'[<>:"/\\|?*%\.]+', '', safe_filename)
        safe_filename = safe_filename.strip().lower(); safe_filename = safe_filename.replace(' ', '-'); safe_filename = re.sub('-+', '-', safe_filename)
        safe_filename = safe_filename.strip('-')[:80];
        if not safe_filename: safe_filename = template_variables.get('id', 'untitled_fallback')
        output_path = os.path.join(OUTPUT_HTML_DIR, f"{safe_filename}.html")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f: f.write(html_content)
        logger.info(f"Rendered HTML: {os.path.basename(output_path)}")
        return output_path
    except Exception as e: logger.exception(f"CRITICAL Render fail {template_variables.get('id','N/A')}: {e}"); return None

def load_recent_articles_for_comparison(max_articles=50):
    articles_for_comparison = []
    if not os.path.exists(ALL_ARTICLES_FILE): logger.info(f"{os.path.basename(ALL_ARTICLES_FILE)} not found."); return []
    try:
        with open(ALL_ARTICLES_FILE, 'r', encoding='utf-8') as f: all_data = json.load(f)
        if isinstance(all_data.get('articles'), list):
            sorted_articles = sorted(all_data["articles"], key=get_sort_key, reverse=True)
            for a in sorted_articles[:max_articles]:
                 if isinstance(a, dict) and a.get("title") and a.get("id"):
                     summary = a.get("summary_short", a.get("summary", ""))[:300]
                     articles_for_comparison.append({"id": a.get("id"), "title": a.get("title"), "summary_short": summary})
                 else: logger.warning(f"Skip invalid recent entry: {a.get('id', 'N/A')}")
            logger.info(f"Loaded {len(articles_for_comparison)} from {os.path.basename(ALL_ARTICLES_FILE)} for context.")
        else: logger.warning(f"'articles' missing/not list in {os.path.basename(ALL_ARTICLES_FILE)}.")
    except Exception as e: logger.warning(f"Error loading {os.path.basename(ALL_ARTICLES_FILE)}: {e}")
    return articles_for_comparison

# --- MODIFIED Site Data Management ---
def update_all_articles_json(new_article_info):
    """Updates ONLY all_articles.json."""
    all_articles_data = {"articles": []}
    article_id = new_article_info.get('id')
    if not article_id: logger.error("Update all_articles fail: missing 'id'."); return

    # Load existing data safely
    try:
        if os.path.exists(ALL_ARTICLES_FILE):
            with open(ALL_ARTICLES_FILE, 'r', encoding='utf-8') as f: loaded_data = json.load(f)
            if isinstance(loaded_data.get('articles'), list): all_articles_data['articles'] = loaded_data['articles']
            else: logger.warning(f"{os.path.basename(ALL_ARTICLES_FILE)} missing 'articles'. Start fresh.")
    except Exception as e: logger.warning(f"Could not load {os.path.basename(ALL_ARTICLES_FILE)}: {e}. Start fresh.")

    # Prepare minimal entry
    minimal_entry = { "id": article_id, "title": new_article_info.get('title'), "link": new_article_info.get('link'),
                      "published_iso": new_article_info.get('published_iso'), "summary_short": new_article_info.get('summary_short'),
                      "image_url": new_article_info.get('image_url'), "topic": new_article_info.get('topic'), "is_breaking": new_article_info.get('is_breaking', False),
                      "tags": new_article_info.get('tags', []), "audio_url": None, "trend_score": new_article_info.get('trend_score', 0) }
    if not minimal_entry['link'] or not minimal_entry['title']: logger.error(f"Entry {article_id} missing link/title. Skip update."); return

    # Update/Add Logic
    current_articles = all_articles_data.setdefault("articles", []); index_to_update = next((i for i, article in enumerate(current_articles) if isinstance(article, dict) and article.get('id') == article_id), -1)
    if index_to_update != -1: current_articles[index_to_update].update(minimal_entry); logger.debug(f"Updating {article_id} in all_articles.json")
    else: current_articles.append(minimal_entry); logger.debug(f"Adding {article_id} to all_articles.json")

    # Sort
    all_articles_data["articles"].sort(key=get_sort_key, reverse=True)

    # Save
    try:
        with open(ALL_ARTICLES_FILE, 'w', encoding='utf-8') as f: json.dump(all_articles_data, f, indent=2, ensure_ascii=False)
        logger.info(f"Updated {os.path.basename(ALL_ARTICLES_FILE)} ({len(all_articles_data['articles'])} articles).")
    except Exception as e: logger.error(f"Failed save {os.path.basename(ALL_ARTICLES_FILE)}: {e}")


# --- Main Processing Pipeline (Modified context handling) ---
def process_single_article(json_filepath, historical_context, processed_in_this_run_context):
    """Processes a single scraped article file through the agent pipeline.
       Returns a summary dict if successful, None otherwise."""
    article_filename = os.path.basename(json_filepath)
    logger.info(f"--- Processing article file: {article_filename} ---")
    article_data = load_article_data(json_filepath)
    if not article_data or not isinstance(article_data, dict):
        logger.error(f"Failed load/invalid data {article_filename}. Skip."); remove_scraped_file(json_filepath); return None

    article_id = article_data.get('id')
    if not article_id:
        feed_url = article_data.get('source_feed', 'unknown_feed'); article_id = get_article_id(article_data, feed_url)
        article_data['id'] = article_id; logger.warning(f"Generated missing ID {article_id} for {article_filename}")

    processed_file_path = os.path.join(PROCESSED_JSON_DIR, f"{article_id}.json")

    try:
        # 1. Check if already fully processed
        if os.path.exists(processed_file_path):
             logger.info(f"Article {article_id} already processed. Skip."); remove_scraped_file(json_filepath); return None

        # --- Prepare combined context for checks ---
        current_title_lower = article_data.get('title', '').lower()
        full_context = historical_context + processed_in_this_run_context

        # 2. --- Exact Title Check (Against full context) ---
        for existing_article in full_context:
            if existing_article.get('title','').lower() == current_title_lower:
                logger.info(f"Article {article_id} is EXACT TITLE DUPLICATE of existing {existing_article.get('id', 'N/A')}. Skip.")
                remove_scraped_file(json_filepath); return None
        # --- End Exact Title Check ---

        # 3. Filter Agent
        logger.debug(f"Running filter agent for {article_id}...")
        article_data = run_filter_agent(article_data)
        if not article_data or article_data.get('filter_verdict') is None:
             filter_error = article_data.get('filter_error', 'Filter critical fail') if isinstance(article_data, dict) else 'Filter returned non-dict'
             logger.error(f"Filter Agent failed {article_id}: {filter_error}. Skip."); remove_scraped_file(json_filepath); return None

        filter_verdict = article_data['filter_verdict']; importance_level = filter_verdict.get('importance_level')
        if importance_level == "Boring": logger.info(f"Article {article_id} classified Boring. Skip."); remove_scraped_file(json_filepath); return None

        assigned_topic = filter_verdict.get('topic', 'Other'); article_data['topic'] = assigned_topic
        article_data['is_breaking'] = (importance_level == "Breaking")
        primary_keyword = filter_verdict.get('primary_topic_keyword', article_data.get('title','')); article_data['primary_keyword'] = primary_keyword
        logger.info(f"Article {article_id} classified {importance_level} (Topic: {assigned_topic}).")

        # 4. Semantic Similarity Check (using combined context)
        logger.info(f"Checking semantic duplicates for {article_id} against {len(full_context)} articles...")
        similarity_result = run_similarity_check_agent(article_data, full_context) # Use combined context
        if similarity_result and similarity_result.get('is_semantic_duplicate'):
            logger.info(f"Article {article_id} is SEMANTIC DUPLICATE. Skip. Reason: {similarity_result.get('reasoning')}")
            remove_scraped_file(json_filepath); return None
        elif similarity_result is None: logger.warning(f"Similarity check failed {article_id}. Proceed cautiously."); article_data['similarity_check_error'] = "Agent failed"
        else: logger.info(f"Article {article_id} passed semantic check."); article_data['similarity_check_error'] = None

        # 5. Image Finding
        logger.info(f"Finding image for {article_id}...")
        scraped_image_url = None; source_url = article_data.get('link')
        if source_url and isinstance(source_url, str) and source_url.startswith('http'):
            try: scraped_image_url = scrape_source_for_image(source_url)
            except Exception as scrape_e: logger.error(f"Error scraping image {source_url}: {scrape_e}")
        if scraped_image_url: article_data['selected_image_url'] = scraped_image_url; logger.info(f"Using scraped image {article_id}")
        else:
            logger.info(f"Image scrape fail/none, using API search {article_id}...")
            image_query = primary_keyword if primary_keyword else article_data.get('title', 'AI News'); api_image_url = find_best_image(image_query)
            if api_image_url: article_data['selected_image_url'] = api_image_url; logger.info(f"Using API image {article_id}")
            else: logger.error(f"Failed find any image {article_id}. Skip."); remove_scraped_file(json_filepath); return None

        # 6. SEO Article Generation
        logger.debug(f"Running SEO agent for {article_id}...")
        article_data = run_seo_article_agent(article_data)
        seo_results = article_data.get('seo_agent_results')
        if not seo_results or not seo_results.get('generated_article_body_md'):
            seo_error = article_data.get('seo_agent_error', 'SEO critical fail'); logger.error(f"SEO Agent failed {article_id}: {seo_error}. Skip."); remove_scraped_file(json_filepath); return None
        elif article_data.get('seo_agent_error'): logger.warning(f"SEO Agent non-critical errors {article_id}: {article_data['seo_agent_error']}")

        # 7. Tags Generation
        logger.debug(f"Running Tags agent for {article_id}...")
        article_data = run_tags_generator_agent(article_data)
        if article_data.get('tags_agent_error'): logger.warning(f"Tags Agent failed/skipped {article_id}: {article_data['tags_agent_error']}")
        article_data['generated_tags'] = article_data.get('generated_tags', []) if isinstance(article_data.get('generated_tags'), list) else []

        # 8. Trend Score Calculation
        trend_score = 0; tags_count = len(article_data['generated_tags']); publish_date_iso = article_data.get('published_iso')
        try:
            if importance_level == "Interesting": trend_score += 5
            elif importance_level == "Breaking": trend_score += 10
            trend_score += tags_count * 0.5
            if publish_date_iso:
                publish_dt = get_sort_key(article_data); now_utc = datetime.now(timezone.utc)
                if publish_dt <= now_utc: days_old = (now_utc - publish_dt).total_seconds() / 86400; recency_factor = max(0, 1 - (days_old / 7)); trend_score += recency_factor * 5
                else: logger.warning(f"Future publish date {publish_date_iso} for {article_id}.")
        except Exception as e: logger.warning(f"Trend score error {article_id}: {e}")
        article_data['trend_score'] = round(max(0, trend_score), 2); logger.debug(f"Trend score {article_id}: {article_data['trend_score']}")

        # --- Prepare for HTML Rendering ---
        # 9. Generate Slug
        original_title = article_data.get('title', f'article-{article_id}'); slug = original_title.lower()
        slug = re.sub(r'[^a-z0-9\s-]', '', slug); slug = re.sub(r'\s+', '-', slug); slug = re.sub(r'-+', '-', slug).strip('-'); slug = slug[:80]
        if not slug: slug = f'article-{article_id}'; article_data['slug'] = slug

        # 10. Prepare Template Variables
        article_relative_path = f"articles/{slug}.html"; canonical_url = urljoin(YOUR_SITE_BASE_URL, article_relative_path)
        body_md = seo_results.get('generated_article_body_md', ''); body_html = f"<p><i>Content error.</i></p><pre>{body_md}</pre>"
        try: body_html = markdown.markdown(body_md, extensions=['fenced_code', 'tables', 'nl2br'])
        except Exception as md_err: logger.error(f"Markdown failed {article_id}: {md_err}")
        tags_list = article_data.get('generated_tags', []); tags_html = format_tags_html(tags_list)
        publish_date_iso_for_meta = article_data.get('published_iso', datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
        publish_date_formatted = "Date Unknown"
        try: publish_dt = get_sort_key(article_data); publish_date_formatted = publish_dt.strftime('%B %d, %Y')
        except Exception: logger.warning(f"Date format error {article_id}")
        page_title = seo_results.get('generated_title_tag', article_data.get('title', 'AI News'))
        meta_description = seo_results.get('generated_meta_description', article_data.get('summary', '')[:160])
        template_vars = { 'PAGE_TITLE': page_title, 'META_DESCRIPTION': meta_description, 'AUTHOR_NAME': article_data.get('author', AUTHOR_NAME_DEFAULT),
                          'META_KEYWORDS': ", ".join(tags_list), 'CANONICAL_URL': canonical_url, 'SITE_NAME': YOUR_WEBSITE_NAME, 'YOUR_WEBSITE_LOGO_URL': YOUR_WEBSITE_LOGO_URL,
                          'IMAGE_URL': article_data.get('selected_image_url', ''), 'IMAGE_ALT_TEXT': page_title, 'META_KEYWORDS_LIST': tags_list,
                          'PUBLISH_ISO_FOR_META': publish_date_iso_for_meta, 'JSON_LD_SCRIPT_BLOCK': seo_results.get('generated_json_ld', ''),
                          'ARTICLE_HEADLINE': article_data.get('title', 'Article'), 'PUBLISH_DATE': publish_date_formatted, 'ARTICLE_BODY_HTML': body_html,
                          'ARTICLE_TAGS_HTML': tags_html, 'SOURCE_ARTICLE_URL': article_data.get('link', '#'), 'ARTICLE_TITLE': article_data.get('title'),
                          'id': article_id, 'CURRENT_ARTICLE_ID': article_id, 'CURRENT_ARTICLE_TOPIC': article_data.get('topic', ''),
                          'CURRENT_ARTICLE_TAGS_JSON': json.dumps(tags_list), 'AUDIO_URL': None }

        # 11. Render HTML Page
        generated_html_path = render_post_page(template_vars, slug)
        if not generated_html_path: logger.error(f"Failed render HTML {article_id}. Skip."); return None

        # --- Finalize and Update Site/Socials ---
        # 12. Prepare final data entry
        site_data_entry = { "id": article_id, "title": article_data.get('title'), "link": article_relative_path, "published_iso": publish_date_iso_for_meta,
                            "summary_short": meta_description, "image_url": article_data.get('selected_image_url'), "topic": article_data.get('topic', 'News'),
                            "is_breaking": article_data.get('is_breaking', False), "tags": tags_list, "audio_url": None, "trend_score": article_data.get('trend_score', 0) }
        article_data['audio_url'] = None

        # 13. Update all_articles.json ONLY
        update_all_articles_json(site_data_entry) # <<< Use the new function

        # 14. --- Post to Twitter (with Daily Limit) ---
        logger.info(f"Check Twitter limit {article_id}...")
        try:
            today_date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d'); tracker_date, count_today = _read_tweet_tracker()
            if tracker_date != today_date_str: logger.info(f"New day {today_date_str}. Reset tweet count."); count_today = 0; _write_tweet_tracker(today_date_str, count_today)
            if count_today < DAILY_TWEET_LIMIT:
                logger.info(f"Daily limit {count_today}/{DAILY_TWEET_LIMIT}. Try tweet..."); tweet_link = canonical_url; tweet_title = article_data.get('title', 'New AI/Tech Article'); tweet_image = article_data.get('selected_image_url')
                if tweet_title and tweet_link and tweet_image:
                    if not tweet_link.startswith('http'): logger.error(f"URL '{tweet_link}' not absolute! Skip tweet.")
                    else:
                        tweet_success = post_tweet_with_image(tweet_title, tweet_link, tweet_image)
                        if tweet_success: logger.info(f"Tweet OK {article_id}."); count_today += 1; _write_tweet_tracker(today_date_str, count_today)
                        else: logger.error(f"Tweet failed {article_id}.")
                else: logger.error(f"Missing data tweet {article_id}.")
            else: logger.info(f"Daily Twitter limit reached. Skip tweet {article_id}.")
        except Exception as tweet_err: logger.exception(f"Twitter error {article_id}: {tweet_err}")
        # --- END Twitter Post ---

        # 15. --- Send data to Make.com Webhook ---
        logger.info(f"Attempting send webhook {article_id}...")
        try:
            webhook_data = { "id": article_id, "title": article_data.get('title', 'New Article'), "article_url": canonical_url,
                             "image_url": article_data.get('selected_image_url'), "topic": article_data.get('topic'), "tags": tags_list }
            if MAKE_WEBHOOK_URL:
                if send_make_webhook(MAKE_WEBHOOK_URL, webhook_data): logger.info(f"Webhook OK {article_id}.")
                else: logger.error(f"Webhook failed {article_id}.")
            else: logger.warning(f"Make URL not set. Skip webhook {article_id}.")
        except Exception as webhook_err: logger.exception(f"Webhook error {article_id}: {webhook_err}")
        # --- END Webhook Send ---

        # 16. Save final processed data & remove original scraped file
        if save_processed_data(processed_file_path, article_data):
             remove_scraped_file(json_filepath)
             logger.info(f"--- Successfully processed article: {article_id} ---")
             # <<< RETURN processed data summary for in-run context >>>
             return {"id": article_id, "title": article_data.get("title"), "summary_short": meta_description}
        else:
             logger.error(f"Failed save final processed JSON {article_id}. Scraped file NOT removed.")
             return None # Failed save

    except Exception as process_e:
         logger.exception(f"CRITICAL failure processing {article_id} (file {article_filename}): {process_e}")
         return None # Failed processing


# --- Main Orchestration Logic (Updated context handling) ---
if __name__ == "__main__":
    run_start_time = time.time()
    logger.info(f"--- === Dacoola AI News Orchestrator Starting Run ({datetime.now()}) === ---")
    ensure_directories()

    # Load IDs already fully processed (from processed_json folder)
    glob_pattern = os.path.join(PROCESSED_JSON_DIR, '*.json')
    completed_article_ids = set(os.path.basename(f).replace('.json', '') for f in glob.glob(glob_pattern))
    logger.info(f"Found {len(completed_article_ids)} already fully processed articles.")

    # Load scraper's persistent processed ID list (from processed_article_ids.txt)
    scraper_processed_ids_on_disk = load_processed_ids()
    initial_processed_ids_for_scraper = scraper_processed_ids_on_disk.union(completed_article_ids)
    logger.info(f"Total initial processed IDs passed to scraper: {len(initial_processed_ids_for_scraper)}")

    # 1. Scrape for new articles
    logger.info("--- Stage 1: Running Scraper ---")
    new_articles_found_count = 0
    try:
        new_articles_found_count = scrape_news(NEWS_FEED_URLS, initial_processed_ids_for_scraper)
        logger.info(f"Scraper run completed. Saved {new_articles_found_count} new raw article JSON files.")
    except NameError: logger.critical("NEWS_FEED_URLS not defined."); sys.exit(1)
    except Exception as scrape_e: logger.exception(f"Scraper stage failed: {scrape_e}"); logger.error("Proceeding despite scraper error.")

    # 2. Process newly scraped articles (and leftovers)
    logger.info("--- Stage 2: Running Processing Cycle ---")
    historical_context = load_recent_articles_for_comparison() # Load from all_articles.json
    processed_in_this_run_context = [] # Track articles processed THIS run
    logger.info(f"Loaded {len(historical_context)} articles from history for duplicate checking.")

    json_files_to_process = []
    try: json_files_to_process = glob.glob(os.path.join(SCRAPED_ARTICLES_DIR, '*.json'))
    except Exception as glob_e: logger.exception(f"Error listing JSON files: {glob_e}")

    if not json_files_to_process: logger.info("No scraped articles found to process.")
    else:
        logger.info(f"Found {len(json_files_to_process)} scraped articles to process.")
        processed_successfully_count = 0; failed_or_skipped_count = 0
        try: json_files_to_process.sort(key=os.path.getmtime) # Process oldest first
        except Exception as sort_e: logger.warning(f"Could not sort JSON files by time: {sort_e}")

        for filepath in json_files_to_process:
            potential_id = os.path.basename(filepath).replace('.json', '')
            if potential_id in completed_article_ids:
                 logger.debug(f"Skipping {potential_id} as processed JSON exists."); remove_scraped_file(filepath); failed_or_skipped_count += 1; continue

            # Process the article, passing historical and current run context
            processed_summary = process_single_article(
                filepath,
                historical_context,
                processed_in_this_run_context # Pass list processed *so far*
            )
            if processed_summary: # If it returned a summary dict (was successful)
                processed_successfully_count += 1
                # Add to the context for checks within this run
                processed_in_this_run_context.append(processed_summary)
                # Add its ID to the completed set to prevent reprocessing if somehow listed again
                completed_article_ids.add(processed_summary['id'])
            else:
                 failed_or_skipped_count += 1 # Count failures/skips
            time.sleep(1) # Small pause

        logger.info(f"Processing cycle complete. Successfully processed: {processed_successfully_count}, Failed/Skipped/Duplicate: {failed_or_skipped_count}")

    run_end_time = time.time()
    logger.info(f"--- === Dacoola AI News Orchestrator Run Finished ({run_end_time - run_start_time:.2f} seconds) === ---")