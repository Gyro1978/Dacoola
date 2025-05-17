# src/main.py (Full script - No changes needed from previous full version for this request)

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
MAX_AGE_FOR_SOCIAL_POST_HOURS = int(os.getenv('MAX_AGE_FOR_SOCIAL_POST_HOURS', '24')) # Made int


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
SCRAPED_ARTICLES_DIR = os.path.join(DATA_DIR_MAIN, 'scraped_articles') # Raw files from scraper AND raw gyro picks
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
    def escapejs_filter(value): 
        if value is None: return ''
        value = str(value).replace('\\', '\\\\').replace("'", "\\'").replace('"', '\\"').replace('/', '\\/')
        value = value.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
        value = value.replace('<', '\\u003c').replace('>', '\\u003e').replace('\b', '\\b').replace('\f', '\\f')
        return value
    if not os.path.isdir(TEMPLATE_DIR):
        logger.critical(f"Jinja2 template directory not found: {TEMPLATE_DIR}. Exiting."); sys.exit(1)
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(['html', 'xml']))
    env.filters['escapejs'] = escapejs_filter
    logger.info(f"Jinja2 environment loaded from {TEMPLATE_DIR}")
except ImportError: logger.critical("Jinja2 library not found. Exiting."); sys.exit(1)
except Exception as e: logger.exception(f"CRITICAL: Failed Jinja2 init. Exiting: {e}"); sys.exit(1)

# --- Helper Functions --- (Ensure these are identical to gyro-picks.py if shared, or keep local)
def ensure_directories():
    dirs_to_create = [ DATA_DIR_MAIN, SCRAPED_ARTICLES_DIR, PROCESSED_JSON_DIR, PUBLIC_DIR, OUTPUT_HTML_DIR, TEMPLATE_DIR ]
    try:
        for d in dirs_to_create: os.makedirs(d, exist_ok=True)
        logger.info("Ensured core directories exist.")
    except OSError as e: logger.exception(f"CRITICAL dir create fail: {e}"); sys.exit(1)

def get_file_hash(filepath):
    hasher = hashlib.sha256(); logger.debug(f"Hashing: {filepath}")
    if not os.path.exists(filepath): logger.error(f"NOT FOUND for hash: {filepath}"); return None
    try:
        with open(filepath, 'rb') as f:
            buf = f.read(65536)
            while len(buf) > 0: hasher.update(buf); buf = f.read(65536)
        hex_digest = hasher.hexdigest(); logger.debug(f"Hashed {filepath}: {hex_digest}"); return hex_digest
    except Exception as e: logger.error(f"Error hashing {filepath}: {e}"); return None

current_post_template_hash = None 

def load_article_data(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f: return json.load(f)
    except FileNotFoundError: logger.warning(f"Not found: {filepath}"); return None
    except json.JSONDecodeError: logger.error(f"JSON decode error: {filepath}."); return None
    except Exception as e: logger.error(f"Error loading {filepath}: {e}"); return None

def save_processed_data(filepath, article_data_to_save):
    try:
         os.makedirs(os.path.dirname(filepath), exist_ok=True)
         if current_post_template_hash: article_data_to_save['post_template_hash'] = current_post_template_hash
         else: logger.warning("current_post_template_hash None. Hash not saved in JSON.")
         with open(filepath, 'w', encoding='utf-8') as f: json.dump(article_data_to_save, f, indent=4, ensure_ascii=False)
         logger.info(f"Saved processed: {os.path.basename(filepath)}"); return True
    except Exception as e: logger.error(f"Failed save processed {os.path.basename(filepath)}: {e}"); return False

def remove_scraped_file(filepath):
    try:
         if os.path.exists(filepath): os.remove(filepath); logger.debug(f"Removed raw: {os.path.basename(filepath)}")
         else: logger.warning(f"Attempted remove non-existent: {filepath}")
    except OSError as e: logger.error(f"Failed remove raw {filepath}: {e}")

def format_tags_html(tags_list):
    if not tags_list: return ""
    try:
        links = []; base = YOUR_SITE_BASE_URL.rstrip('/') + '/' if YOUR_SITE_BASE_URL else '/'
        for tag in tags_list:
            safe = requests.utils.quote(str(tag)); url = urljoin(base, f"topic.html?name={safe}")
            links.append(f'<a href="{url}" class="tag-link">{html.escape(str(tag))}</a>')
        return ", ".join(links)
    except Exception as e: logger.error(f"Error formatting tags HTML: {tags_list} - {e}"); return ""

def get_sort_key(item):
    fallback = datetime(1970, 1, 1, tzinfo=timezone.utc); iso_str = item.get('published_iso')
    if not iso_str: return fallback
    try:
        if iso_str.endswith('Z'): iso_str = iso_str[:-1] + '+00:00'
        dt = datetime.fromisoformat(iso_str)
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except ValueError: logger.warning(f"Date parse error '{iso_str}'. Fallback."); return fallback

def _read_tweet_tracker():
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    try:
        if os.path.exists(TWITTER_DAILY_LIMIT_FILE):
            with open(TWITTER_DAILY_LIMIT_FILE, 'r') as f: data = json.load(f)
            if data.get('date') == today: return data['date'], data.get('count', 0)
        return today, 0
    except Exception as e: logger.error(f"Error read Twitter tracker: {e}. Reset."); return today, 0

def _write_tweet_tracker(date_str, count):
    try:
        os.makedirs(os.path.dirname(TWITTER_DAILY_LIMIT_FILE), exist_ok=True)
        with open(TWITTER_DAILY_LIMIT_FILE, 'w') as f: json.dump({'date': date_str, 'count': count}, f, indent=2)
        logger.info(f"Twitter tracker: Date {date_str}, Count {count}")
    except Exception as e: logger.error(f"Error write Twitter tracker: {e}")

def send_make_webhook(url, payload):
    if not url: logger.warning("Make webhook URL missing."); return False
    if not payload: logger.warning("No data for Make webhook."); return False
    data = {"articles": payload} if isinstance(payload, list) else payload
    log_id = f"batch of {len(payload)}" if isinstance(payload, list) else f"ID: {payload.get('id', 'N/A')}"
    try:
        res = requests.post(url, headers={'Content-Type': 'application/json'}, json=data, timeout=30)
        res.raise_for_status(); logger.info(f"Sent to Make: {log_id}"); return True
    except Exception as e: logger.error(f"Failed send to Make {log_id}: {e}"); return False

def render_post_page(variables, slug_base):
    try:
        template = env.get_template('post_template.html'); html_out = template.render(variables)
        if not isinstance(slug_base, str): slug_base = str(variables.get('id', 'untitled'))
        safe_fn = re.sub(r'[<>:"/\\|?*%\.]+', '', slug_base).strip().lower().replace(' ', '-')
        safe_fn = re.sub(r'-+', '-', safe_fn)[:80] or variables.get('id', 'fallback-slug')
        fpath = os.path.join(OUTPUT_HTML_DIR, f"{safe_fn}.html")
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with open(fpath, 'w', encoding='utf-8') as f: f.write(html_out)
        logger.info(f"Rendered HTML: {os.path.basename(fpath)}"); return fpath
    except Exception as e: logger.exception(f"CRITICAL HTML render fail ID {variables.get('id','N/A')}: {e}"); return None

def load_all_articles_data_from_json():
    if not os.path.exists(ALL_ARTICLES_FILE): return []
    try:
        with open(ALL_ARTICLES_FILE, 'r') as f: data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get('articles'), list): return data['articles']
        logger.warning(f"{ALL_ARTICLES_FILE} invalid structure.")
    except Exception as e: logger.error(f"Error loading {ALL_ARTICLES_FILE}: {e}.")
    return []

def update_all_articles_json_file(summary):
    articles = load_all_articles_data_from_json()
    article_id = summary.get('id')
    if not article_id: logger.error("Update all_articles: info missing 'id'."); return
    articles_map = {a.get('id'): a for a in articles if isinstance(a, dict) and a.get('id')}
    articles_map[article_id] = summary
    updated_list = sorted(list(articles_map.values()), key=get_sort_key, reverse=True)
    try:
        json_str = json.dumps({"articles": updated_list}, indent=2, ensure_ascii=False)
        try: json.loads(json_str); logger.debug("all_articles.json content validated.")
        except json.JSONDecodeError as jde: logger.error(f"CRITICAL: all_articles.json not valid: {jde}. Data: {json_str[:200]}"); return
        with open(ALL_ARTICLES_FILE, 'w', encoding='utf-8') as f: f.write(json_str)
        logger.info(f"Updated {os.path.basename(ALL_ARTICLES_FILE)} ({len(updated_list)} articles).")
    except Exception as e: logger.error(f"Failed save {os.path.basename(ALL_ARTICLES_FILE)}: {e}")

def slugify(text):
    if not text: return "untitled"; text = str(text).lower()
    text = re.sub(r'[^\w\s-]', '', text).strip(); text = re.sub(r'[-\s]+', '-', text)      
    return text[:70]

def process_link_placeholders(markdown_text, base_site_url):
    if not markdown_text: return ""
    if not base_site_url or base_site_url == '/': logger.warning("Base URL invalid for link placeholders."); base_site_url = "/"
    internal_regex = r'\[\[\s*(.*?)\s*(?:\|\s*(.*?)\s*)?\]\]'
    def replace_internal(match):
        link_text = match.group(1).strip(); topic_slug = match.group(2).strip() if match.group(2) else None; href = ""
        if topic_slug:
            if topic_slug.endswith(".html") or (' ' not in topic_slug and topic_slug.count('-') > 0): # Slug-like
                 prefix = "articles/" if topic_slug.endswith(".html") and not topic_slug.startswith("articles/") else ""
                 href = urljoin(base_site_url, f"{prefix}{topic_slug.lstrip('/')}")
            else: href = urljoin(base_site_url, f"topic.html?name={quote(topic_slug)}") # Topic name
        else: href = urljoin(base_site_url, f"topic.html?name={quote(slugify(link_text))}") # Slugify link text for topic
        return f'<a href="{html.escape(href)}" class="internal-link">{html.escape(link_text)}</a>'
    processed = re.sub(internal_regex, replace_internal, markdown_text)
    def replace_external(match):
        text, url = match.group(1).strip(), match.group(2).strip()
        return f'<a href="{html.escape(url)}" target="_blank" rel="noopener noreferrer" class="external-link">{html.escape(text)}</a>'
    return re.sub(r'\(\(\s*(.*?)\s*\|\s*(https?://.*?)\s*\)\)', replace_external, processed)

def regenerate_article_html_if_needed(article_data, force_regen=False):
    global current_post_template_hash
    if not current_post_template_hash: logger.error("CRITICAL: Template hash None. Cannot regen."); return False
    article_id, slug = article_data.get('id'), article_data.get('slug')
    if not article_id: logger.warning(f"Regen skip: no id for {article_data.get('title', 'Unknown')}"); return False
    if not slug:
        slug = slugify(article_data.get('title', article_id)) or article_id
        logger.warning(f"Article {article_id} missing slug. Derived: {slug}"); article_data['slug'] = slug
    
    html_path = os.path.join(OUTPUT_HTML_DIR, f"{slug}.html")
    stored_hash = article_data.get('post_template_hash')
    regen = False
    logger.debug(f"RegenCheck ID {article_id}: CurrentHash='{current_post_template_hash}', StoredHash='{stored_hash}', Force='{force_regen}', Exists='{os.path.exists(html_path)}'")
    if not os.path.exists(html_path): logger.info(f"HTML missing for {article_id}. Regen=True."); regen = True
    elif force_regen: logger.info(f"Forcing regen for {article_id}. Regen=True."); regen = True
    elif stored_hash != current_post_template_hash: logger.info(f"Template changed for {article_id}. Old:{stored_hash}, New:{current_post_template_hash}. Regen=True."); regen = True
    else: logger.debug(f"RegenCheck for {article_id}: No criteria met.")

    if regen:
        logger.info(f"Regenerating HTML for {article_id}...")
        seo_results = article_data.get('seo_agent_results', {})
        if not isinstance(seo_results, dict): seo_results = {}
        md_raw = seo_results.get('generated_article_body_md', '')
        if not md_raw: logger.warning(f"{article_id} empty md_body.")
        
        md_linked = process_link_placeholders(md_raw, YOUR_SITE_BASE_URL)
        html_body = html.unescape(markdown.markdown(md_linked, extensions=['fenced_code', 'tables', 'nl2br', 'sane_lists', 'extra']))
        
        tags = article_data.get('generated_tags', []); tags_html = format_tags_html(tags)
        pub_dt = get_sort_key(article_data)
        rel_path = f"articles/{slug}.html"
        canon_url = urljoin(YOUR_SITE_BASE_URL, rel_path.lstrip('/')) if YOUR_SITE_BASE_URL and YOUR_SITE_BASE_URL != '/' else f"/{rel_path.lstrip('/')}"
        
        json_ld_raw = seo_results.get('generated_json_ld_raw', '{}')
        json_ld_placeholder = f"{BASE_URL_FOR_CANONICAL_MAIN.rstrip('/')}/articles/{{SLUG_PLACEHOLDER}}"
        final_json_ld_tag = seo_results.get('generated_json_ld_full_script_tag', '<script type="application/ld+json">{}</script>')
        if json_ld_placeholder in json_ld_raw:
            final_json_ld_str = json_ld_raw.replace(json_ld_placeholder, canon_url)
            final_json_ld_tag = f'<script type="application/ld+json">\n{final_json_ld_str}\n</script>'
        
        tpl_vars = {
            'PAGE_TITLE': seo_results.get('generated_title_tag', article_data.get('title')), 'META_DESCRIPTION': seo_results.get('generated_meta_description', ''),
            'AUTHOR_NAME': article_data.get('author', AUTHOR_NAME_DEFAULT), 'META_KEYWORDS_LIST': tags, 'CANONICAL_URL': canon_url,
            'SITE_NAME': YOUR_WEBSITE_NAME, 'YOUR_WEBSITE_LOGO_URL': YOUR_WEBSITE_LOGO_URL, 'IMAGE_URL': article_data.get('selected_image_url', ''),
            'IMAGE_ALT_TEXT': article_data.get('title', 'Article Image'), 'PUBLISH_ISO_FOR_META': article_data.get('published_iso', datetime.now(timezone.utc).isoformat()),
            'JSON_LD_SCRIPT_BLOCK': final_json_ld_tag, 'ARTICLE_HEADLINE': article_data.get('title'), 'ARTICLE_SEO_H1': article_data.get('title'),
            'PUBLISH_DATE': pub_dt.strftime('%B %d, %Y') if pub_dt != datetime(1970,1,1,tzinfo=timezone.utc) else "Date Unknown",
            'ARTICLE_BODY_HTML': html_body, 'ARTICLE_TAGS_HTML': tags_html, 'SOURCE_ARTICLE_URL': article_data.get('link', '#'),
            'ARTICLE_TITLE': article_data.get('title'), 'id': article_id, 'CURRENT_ARTICLE_ID': article_id,
            'CURRENT_ARTICLE_TOPIC': article_data.get('topic', ''), 'CURRENT_ARTICLE_TAGS_JSON': json.dumps(tags), 'AUDIO_URL': article_data.get('audio_url')
        }
        if render_post_page(tpl_vars, slug):
            logger.info(f"HTML render OK for {article_id}. Updating JSON hash.")
            article_data['post_template_hash'] = current_post_template_hash
            json_path_update = os.path.join(PROCESSED_JSON_DIR, f"{article_id}.json")
            if save_processed_data(json_path_update, article_data): logger.info(f"Updated JSON for {article_id} with new hash: {current_post_template_hash}")
            else: logger.error(f"Failed update template hash in {json_path_update}.")
            return True
        else: logger.error(f"HTML render FAILED for {article_id}."); return False
    logger.debug(f"RegenCheck for {article_id}: No regen performed.")
    return False

def process_single_scraped_article(raw_json_filepath, existing_articles_summary_data, current_run_fully_processed_data_list):
    article_filename = os.path.basename(raw_json_filepath); logger.info(f"--- Processing: {article_filename} ---")
    article_data = load_article_data(raw_json_filepath)
    if not article_data: logger.error(f"Load/invalid data {article_filename}. Skip."); remove_scraped_file(raw_json_filepath); return None

    article_id = article_data.get('id') or get_article_id(article_data, article_data.get('source_feed', 'unknown'))
    article_data['id'] = article_id
    processed_json_path = os.path.join(PROCESSED_JSON_DIR, f"{article_id}.json")

    try:
        if os.path.exists(processed_json_path):
            logger.info(f"ID {article_id} already fully processed. Skip raw."); remove_scraped_file(raw_json_filepath); return None

        pub_iso = article_data.get('published_iso')
        if pub_iso and get_sort_key(article_data) < (datetime.now(timezone.utc) - timedelta(days=ARTICLE_MAX_AGE_DAYS)):
            logger.info(f"{article_id} too old. Skip."); remove_scraped_file(raw_json_filepath); return None
        
        is_gyro_adv = article_data.get('source_feed') == "Gyro Pick - Advanced"
        user_importance = article_data.get('user_importance_override') if is_gyro_adv else None
        user_trending = article_data.get('user_is_trending_pick', False) if is_gyro_adv else False
        user_img = article_data.get('user_provided_image_url') if is_gyro_adv else None

        if user_img: article_data['selected_image_url'] = user_img
        elif not article_data.get('selected_image_url'):
            logger.info(f"Finding image for {article_id} ('{article_data.get('title', '')[:30]}...')")
            img_url = scrape_source_for_image(article_data.get('link')) or find_best_image(article_data.get('title', 'AI News'), article_url_for_scrape=article_data.get('link'))
            if not img_url: logger.error(f"No image for {article_id}. Skip."); remove_scraped_file(raw_json_filepath); return None
            article_data['selected_image_url'] = img_url
        
        title_lower = article_data.get('title', '').strip().lower()
        if not title_lower: logger.error(f"{article_id} empty title. Skip."); remove_scraped_file(raw_json_filepath); return None
        for ex_sum in existing_articles_summary_data:
            if isinstance(ex_sum, dict) and ex_sum.get('title','').strip().lower() == title_lower and \
               ex_sum.get('image_url') == article_data['selected_image_url'] and ex_sum.get('id') != article_id:
                logger.warning(f"{article_id} DUPLICATE (Title/Img) of {ex_sum.get('id', 'N/A')}. Skip."); remove_scraped_file(raw_json_filepath); return None
        
        article_data = run_filter_agent(article_data)
        if not article_data or article_data.get('filter_verdict') is None: logger.error(f"Filter Agent fail for {article_id}. Skip."); remove_scraped_file(raw_json_filepath); return None
        
        filter_verdict = article_data['filter_verdict']; importance = filter_verdict.get('importance_level')
        if is_gyro_adv and user_importance:
            logger.info(f"Gyro Adv: Override filter importance. User: {user_importance}. Filter: {importance}")
            importance = user_importance; filter_verdict['importance_level'] = user_importance
        article_data['is_breaking'] = (importance == "Breaking")
        if importance == "Boring" and not is_gyro_adv : # Gyro Advanced is never boring
            logger.info(f"{article_id} 'Boring'. Skip."); remove_scraped_file(raw_json_filepath); return None
        
        article_data['topic'] = filter_verdict.get('topic', 'Other')
        article_data['primary_keyword'] = filter_verdict.get('primary_topic_keyword', article_data.get('title','Untitled'))
        logger.info(f"{article_id} final class '{importance}' (Topic: {article_data['topic']}).")

        article_data = run_similarity_check_agent(article_data, PROCESSED_JSON_DIR, current_run_fully_processed_data_list)
        sim_verdict = article_data.get('similarity_verdict', 'ERROR')
        if is_gyro_adv and sim_verdict != "OKAY" and not sim_verdict.startswith("OKAY_"): logger.info(f"Gyro Adv {article_id} similarity: {sim_verdict}. Proceeding.")
        elif sim_verdict != "OKAY" and not sim_verdict.startswith("OKAY_"):
            logger.warning(f"{article_id} similarity: {sim_verdict} (to {article_data.get('similar_article_id', 'N/A')}). Skip."); remove_scraped_file(raw_json_filepath); return None
        
        article_data = run_keyword_research_agent(article_data)
        tags = list(set(kw.strip() for kw in article_data.get('researched_keywords', []) + [article_data.get('primary_keyword')] if kw and kw.strip()))[:15]
        article_data['generated_tags'] = tags if tags else [article_data.get('topic', "Tech"), "News"]
        
        article_data = run_seo_article_agent(article_data.copy()) 
        seo_results = article_data.get('seo_agent_results')
        if not seo_results or not seo_results.get('generated_article_body_md'):
            logger.error(f"SEO Agent fail for {article_id}. Skip."); remove_scraped_file(raw_json_filepath); return None
        
        article_data['slug'] = slugify(article_data.get('title', article_id)) or article_id
        
        trend_score = 10.0 if article_data.get('is_breaking') else 5.0
        actual_trending = user_trending if is_gyro_adv else False
        if actual_trending: trend_score += 7.0
        trend_score += float(len(tags)) * 0.5
        if pub_iso:
            pub_dt = get_sort_key(article_data); now = datetime.now(timezone.utc)
            if pub_dt <= now: days_old = (now - pub_dt).total_seconds() / 86400.0
            if days_old <= ARTICLE_MAX_AGE_DAYS: trend_score += max(0.0, 1.0 - (days_old / float(ARTICLE_MAX_AGE_DAYS))) * 5.0
        article_data['trend_score'] = round(max(0.0, trend_score), 2)
        
        if not regenerate_article_html_if_needed(article_data, force_regen=True): 
            logger.error(f"HTML render fail for new {article_id}. Skip save."); remove_scraped_file(raw_json_filepath); return None
        
        rel_path = f"articles/{article_data['slug']}.html"
        canon_url = urljoin(YOUR_SITE_BASE_URL, rel_path.lstrip('/')) if YOUR_SITE_BASE_URL and YOUR_SITE_BASE_URL != '/' else f"/{rel_path.lstrip('/')}"
        
        summary = {
            "id": article_id, "title": article_data.get('title'), "link": rel_path,
            "published_iso": article_data.get('published_iso') or datetime.now(timezone.utc).isoformat(), 
            "summary_short": seo_results.get('generated_meta_description', ''),
            "image_url": article_data.get('selected_image_url'), "topic": article_data.get('topic', 'News'), 
            "is_breaking": article_data.get('is_breaking', False), "is_trending_pick": actual_trending,
            "tags": article_data.get('generated_tags', []), "audio_url": None, 
            "trend_score": article_data.get('trend_score', 0)
        }
        article_data['audio_url'] = None
        update_all_articles_json_file(summary)
        if not save_processed_data(processed_json_path, article_data): logger.error(f"Failed save main processed JSON for {article_id}.")
        
        social_payload = {
            "id": article_id, "title": article_data.get('title'), "article_url": canon_url, 
            "image_url": article_data.get('selected_image_url'), "topic": article_data.get('topic'), 
            "tags": article_data.get('generated_tags', []), "summary_short": summary.get('summary_short', '')
        }
        
        if os.path.exists(raw_json_filepath): remove_scraped_file(raw_json_filepath)
        logger.info(f"--- Successfully processed article (scraped/gyro): {article_id} ---")
        return {"summary": summary, "social_post_data": social_payload, "full_data": article_data }

    except Exception as e:
        logger.exception(f"CRITICAL failure processing {article_id} ({article_filename}): {e}")
        if os.path.exists(raw_json_filepath): remove_scraped_file(raw_json_filepath)
        return None


if __name__ == "__main__":
    run_start_timestamp = time.time()
    logger.info(f"--- === Dacoola AI News Orchestrator Starting Run ({datetime.now(timezone.utc).isoformat()}) === ---")
    ensure_directories()

    logger.info(f"Attempting to read and hash template file: {POST_TEMPLATE_FILE}")
    current_post_template_hash = get_file_hash(POST_TEMPLATE_FILE) 
    if not current_post_template_hash:
        logger.critical(f"CRITICAL FAILURE: Could not hash template file: {POST_TEMPLATE_FILE}. Exiting.")
        sys.exit(1) 
    else:
        logger.info(f"Successfully obtained current post_template.html hash: {current_post_template_hash}")

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
        logger.info(f"Using current template hash for this run: {current_post_template_hash}")
        for proc_json_filepath in all_processed_json_files:
            article_id_for_log = os.path.basename(proc_json_filepath).replace('.json', '')
            try:
                article_data_content = load_article_data(proc_json_filepath)
                if not article_data_content:
                    logger.warning(f"Skipping HTML regen for invalid/unreadable JSON: {article_id_for_log}"); continue
                
                article_id_from_content = article_data_content.get('id', article_id_for_log)
                if article_id_from_content != article_id_for_log:
                    logger.warning(f"Mismatch: Filename ID '{article_id_for_log}' vs Content ID '{article_id_from_content}'. Using content ID.")
                
                logger.debug(f"Checking regen for article ID: {article_id_from_content}. Stored hash: {article_data_content.get('post_template_hash')}")
                if regenerate_article_html_if_needed(article_data_content): 
                    html_regenerated_count += 1
                    logger.info(f"Successfully regenerated HTML for {article_id_from_content} and its JSON should now have the new hash.")
                else:
                    logger.debug(f"HTML for {article_id_from_content} did NOT need regeneration OR regeneration process failed.")
            except Exception as regen_exc:
                logger.exception(f"Error during HTML regeneration main loop for {article_id_for_log}: {regen_exc}")
    logger.info(f"--- HTML Regeneration Stage Complete. Regenerated/Verified {html_regenerated_count} files. ---")

    logger.info("--- Stage 2: Running News Scraper ---")
    new_raw_articles_count = 0
    try: new_raw_articles_count = scrape_news(NEWS_FEED_URLS, initial_ids_for_scraper_run)
    except Exception as main_scrape_e: logger.exception(f"News scraper run failed: {main_scrape_e}")
    logger.info(f"News Scraper run completed. Found {new_raw_articles_count} new raw article files.")

    logger.info("--- Stage 3: Processing Newly Scraped Articles (and Raw Gyro Picks) ---")
    all_articles_summary_data_for_run = load_all_articles_data_from_json()
    # Process files from SCRAPED_ARTICLES_DIR (includes raw gyro picks now)
    raw_json_files_to_process_list = sorted(glob.glob(os.path.join(SCRAPED_ARTICLES_DIR, '*.json')), key=os.path.getmtime, reverse=True)
    logger.info(f"Found {len(raw_json_files_to_process_list)} raw article files (scraped & gyro) to process.")

    current_run_fully_processed_data = [] 
    successfully_processed_scraped_count = 0; failed_or_skipped_scraped_count = 0
    social_media_payloads_for_posting_queue = []

    for raw_filepath in raw_json_files_to_process_list:
        article_potential_id = os.path.basename(raw_filepath).replace('.json', '')
        if article_potential_id in fully_processed_article_ids_set and not article_potential_id.startswith("gyro-"): 
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
    logger.info(f"Article processing cycle complete. Success: {successfully_processed_scraped_count}, Failed/Skipped: {failed_or_skipped_scraped_count}")


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
            logger.debug(f"Article {article_id_from_filename} was from current processing run; already in social queue if eligible.")
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
            logger.warning(f"Processed article {article_id_from_filename} missing 'published_iso'. Skipping social.")
            continue

        try:
            article_publish_dt = get_sort_key(processed_article_full_data)
            if article_publish_dt < cutoff_time_for_social:
                logger.debug(f"Processed article {article_id_from_filename} too old ({article_publish_dt.date()}). Skipping social.")
                mark_article_as_posted_in_history(article_id_from_filename) 
                continue
        except Exception as date_e:
            logger.warning(f"Error parsing date for {article_id_from_filename} for social age check: {date_e}. Skipping.")
            continue

        logger.info(f"Article ID {article_id_from_filename} (from processed_json) not in history & recent. Adding to social queue.")
        article_title_for_social = processed_article_full_data.get('title', 'Untitled')
        article_slug_for_social = processed_article_full_data.get('slug')
        if not article_slug_for_social:
            logger.warning(f"Processed article {article_id_from_filename} missing slug. Cannot form URL for social. Skipping."); continue

        relative_link_for_social = f"articles/{article_slug_for_social}.html"
        canonical_url_for_social = urljoin(YOUR_SITE_BASE_URL, relative_link_for_social.lstrip('/')) if YOUR_SITE_BASE_URL and YOUR_SITE_BASE_URL != '/' else f"/{relative_link_for_social.lstrip('/')}"

        seo_results_data_for_social = processed_article_full_data.get('seo_agent_results', {})
        summary_short_for_social = seo_results_data_for_social.get('generated_meta_description', '') if isinstance(seo_results_data_for_social, dict) else ''
        
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
                logger.info(f"Article {article_id_for_social_post} already marked in history. Skipping.")
                continue

            logger.info(f"Preparing to post article ID: {article_id_for_social_post} ('{social_payload_item.get('title', '')[:40]}...')")
            platforms_to_attempt_post = ["bluesky", "reddit"] 

            if social_media_clients_glob.get("twitter_client"):
                current_date_for_twitter_check, posts_today_for_twitter = _read_tweet_tracker()
                if current_date_for_twitter_check != current_run_date_str: 
                    posts_today_for_twitter = 0
                    _write_tweet_tracker(current_run_date_str, 0) 

                if posts_today_for_twitter < DAILY_TWEET_LIMIT:
                    platforms_to_attempt_post.append("twitter")
                    logger.info(f"Article {article_id_for_social_post} WILL be attempted on Twitter. (Count: {posts_today_for_twitter}/{DAILY_TWEET_LIMIT})")
                else:
                    logger.info(f"Daily Twitter limit ({DAILY_TWEET_LIMIT}) reached. Twitter SKIPPED for ID: {article_id_for_social_post}")
            else:
                logger.debug("Twitter client not available for social posting.")

            post_success = run_social_media_poster(
                social_payload_item,
                social_media_clients_glob,
                platforms_to_post=tuple(platforms_to_attempt_post)
            )
            
            # Logic for updating twitter count if a twitter post was SUCCESSFUL
            if "twitter" in platforms_to_attempt_post and social_media_clients_glob.get("twitter_client"):
                # Check if post_to_twitter actually succeeded by inspecting history or a return value from it
                # For now, we assume run_social_media_poster handles marking history which might imply success.
                # A more direct way is if post_to_twitter in social_media_poster.py returned a clear success for Twitter.
                # The current social_media_poster returns a general any_post_successful_flag.
                # Let's refine this slightly: if twitter was attempted and the generic success flag is true,
                # we *assume* twitter might have been one of the successes if not the only one.
                # A better way is for run_social_media_poster to return a dict of successes.
                # For now, if twitter was in the list of attempts, and *any* post was successful, we'll re-read and write the tracker.
                # This might over-increment if a Bsky post succeeded but Twitter failed due to non-limit reasons.
                # A more robust solution: post_to_twitter should update the tracker if it succeeds.
                # The existing `post_to_twitter` in `social_media_poster.py` was given logic to update this file itself.
                # So, we just re-read here to get the latest count for logging.
                _, twitter_posts_made_today_after_post = _read_tweet_tracker()
                logger.info(f"Twitter daily post count now: {twitter_posts_made_today_after_post} after attempt for {article_id_for_social_post}.")


            articles_posted_this_run_count +=1 
            if MAKE_WEBHOOK_URL: final_make_webhook_payloads.append(social_payload_item)

            if articles_posted_this_run_count < len(social_media_payloads_for_posting_queue):
                 post_delay_seconds = 10 
                 logger.debug(f"Sleeping for {post_delay_seconds} seconds before next social post...")
                 time.sleep(post_delay_seconds)

        logger.info(f"Social media posting cycle finished. Attempted {articles_posted_this_run_count} articles.")
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