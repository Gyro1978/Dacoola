# gyro-picks.py (Full Script - Corrected Pylance "not defined" errors)
import sys
import os
import json
import hashlib
import logging
import re
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, urljoin, quote 
import markdown
import html

# --- Path Setup & Project Root ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv

try:
    from src.scrapers.news_scraper import get_full_article_content
    from src.scrapers.image_scraper import find_best_image, scrape_source_for_image
    from src.agents.filter_news_agent import run_filter_agent
    from src.agents.keyword_research_agent import run_keyword_research_agent
    from src.agents.seo_article_generator_agent import run_seo_article_agent
    from src.agents.similarity_check_agent import run_similarity_check_agent 
    from generate_sitemap import generate_sitemap as run_sitemap_generator 
except ImportError as e:
    print(f"FATAL IMPORT ERROR in gyro-picks.py: {e}.")
    print(f"Current sys.path: {sys.path}")
    print(f"PROJECT_ROOT: {PROJECT_ROOT}")
    sys.exit(1)

dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)

# --- Configuration ---
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
PROCESSED_JSON_DIR = os.path.join(DATA_DIR, 'processed_json')
PUBLIC_DIR = os.path.join(PROJECT_ROOT, 'public')
OUTPUT_HTML_DIR = os.path.join(PUBLIC_DIR, 'articles')
TEMPLATE_DIR = os.path.join(PROJECT_ROOT, 'templates')
ALL_ARTICLES_FILE = os.path.join(PUBLIC_DIR, 'all_articles.json')
POST_TEMPLATE_FILE = os.path.join(TEMPLATE_DIR, 'post_template.html') 

AUTHOR_NAME_DEFAULT = os.getenv('AUTHOR_NAME', 'Gyro Pick Team')
YOUR_WEBSITE_NAME = os.getenv('YOUR_WEBSITE_NAME', 'Dacoola')
YOUR_WEBSITE_LOGO_URL = os.getenv('YOUR_WEBSITE_LOGO_URL', '')
raw_base_url_env = os.getenv('YOUR_SITE_BASE_URL', '')
YOUR_SITE_BASE_URL_FOR_LINKS = (raw_base_url_env.rstrip('/') + '/') if raw_base_url_env else '/' 
BASE_URL_FOR_CANONICAL_PLACEHOLDER_CHECK = os.getenv('YOUR_SITE_BASE_URL', 'https://your-site-url.com')

if not YOUR_SITE_BASE_URL_FOR_LINKS or YOUR_SITE_BASE_URL_FOR_LINKS == "/":
    print("ERROR: YOUR_SITE_BASE_URL not set or invalid in .env.")

# --- Jinja2 Setup ---
try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    def escapejs_filter(value):
        if value is None: return ''
        return str(value).replace('\\', '\\\\').replace("'", "\\'").replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r')

    if not os.path.isdir(TEMPLATE_DIR):
        print(f"ERROR: Jinja2 template dir not found: {TEMPLATE_DIR}"); sys.exit(1)
    jinja_env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(['html', 'xml']))
    jinja_env.filters['escapejs'] = escapejs_filter
except ImportError: print("ERROR: Jinja2 library not found."); sys.exit(1)
except Exception as e: print(f"ERROR: Jinja2 initialization failed: {e}"); sys.exit(1)

# --- Logging Setup ---
log_file_path = os.path.join(PROJECT_ROOT, 'gyro-picks.log')
logging.basicConfig(
    level=logging.DEBUG, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_file_path, encoding='utf-8')],
    force=True
)
logger = logging.getLogger('GyroPicksOrchestrator') 
logger.setLevel(logging.DEBUG)


# --- Helper Functions ---
def ensure_directories():
    for d_path in [DATA_DIR, PROCESSED_JSON_DIR, PUBLIC_DIR, OUTPUT_HTML_DIR]:
        os.makedirs(d_path, exist_ok=True)
    logger.info("Ensured core directories exist.")

def generate_article_id(url_for_hash): 
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')
    url_hash_part = hashlib.sha1(url_for_hash.encode('utf-8')).hexdigest()[:10]
    return f"gyro-{timestamp}-{url_hash_part}"

def get_file_hash(filepath):
    hasher = hashlib.sha256()
    if not os.path.exists(filepath): logger.error(f"File NOT FOUND for hashing: {filepath}"); return None
    try:
        with open(filepath, 'rb') as f:
            buf = f.read(65536)
            while len(buf) > 0: hasher.update(buf); buf = f.read(65536)
        return hasher.hexdigest()
    except Exception as e: logger.error(f"Error hashing file {filepath}: {e}"); return None

current_post_template_hash_gyro = None 

def slugify(text):
    if not text: return "untitled"
    text = str(text).lower(); text = re.sub(r'[^\w\s-]', '', text).strip(); text = re.sub(r'[-\s]+', '-', text)       
    return text[:70] 

def process_link_placeholders(markdown_text, base_site_url):
    if not markdown_text: return ""
    if not base_site_url or base_site_url == '/': logger.warning("Base site URL invalid for link placeholders."); base_site_url = "/" 
    
    internal_link_regex = r'\[\[\s*(.*?)\s*(?:\|\s*(.*?)\s*)?\]\]'

    def replace_internal(match):
        link_text = match.group(1).strip()
        topic_or_slug = match.group(2).strip() if match.group(2) else None # Corrected to group 2
        href = ""
        if topic_or_slug:
            if topic_or_slug.endswith(".html") or (' ' not in topic_or_slug and topic_or_slug.count('-') > 0):
                 if topic_or_slug.endswith(".html") and not topic_or_slug.startswith("articles/"): href = urljoin(base_site_url, f"articles/{topic_or_slug.lstrip('/')}")
                 elif not topic_or_slug.endswith(".html"): href = urljoin(base_site_url, f"topic.html?name={quote(topic_or_slug)}")
                 else: href = urljoin(base_site_url, topic_or_slug.lstrip('/'))
            else: href = urljoin(base_site_url, f"topic.html?name={quote(topic_or_slug)}")
        else: slugified_link_text = slugify(link_text); href = urljoin(base_site_url, f"topic.html?name={quote(slugified_link_text)}")
        
        logger.debug(f"Internal link: Text='{link_text}', Target='{topic_or_slug}', Href='{href}'")
        return f'<a href="{html.escape(href)}" class="internal-link">{html.escape(link_text)}</a>'
    
    processed_text = re.sub(internal_link_regex, replace_internal, markdown_text)
    
    def replace_external(match):
        link_text = match.group(1).strip(); url = match.group(2).strip()
        return f'<a href="{html.escape(url)}" target="_blank" rel="noopener noreferrer" class="external-link">{html.escape(link_text)}</a>'
    return re.sub(r'\(\(\s*(.*?)\s*\|\s*(https?://.*?)\s*\)\)', replace_external, processed_text)

def get_quick_add_urls():
    urls = []; print("\n--- Gyro Pick - Quick Add Mode --- \nPaste article URL(s). Press Enter after each. Type 'done'.")
    while True:
        url_input = input(f"Quick Add URL {len(urls) + 1} (or 'done'): ").strip()
        if url_input.lower() == 'done':
            if not urls: print("No URLs. Exiting Quick Add."); return []
            break
        if not (url_input.startswith('http://') or url_input.startswith('https://')): print("Err: URL format."); continue
        try: parsed = urlparse(url_input); assert parsed.scheme and parsed.netloc; urls.append(url_input)
        except Exception: print(f"Err: Invalid URL.")
    return urls

def get_advanced_add_inputs():
    urls = []; print("\n--- Gyro Pick - Advanced Add Mode --- \nPrimary URL then optional other URLs for same story. Type 'done' for URLs.")
    primary_url = ""
    while not primary_url:
        primary_url = input("Primary URL: ").strip()
        if not (primary_url.startswith('http://') or primary_url.startswith('https://')): print("Err: Primary URL format."); primary_url = ""; continue
        try: urlparse(primary_url); urls.append(primary_url)
        except: print("Err: Invalid primary URL."); primary_url = ""
    print("Secondary URLs (optional). Type 'done'.")
    while True:
        url_input = input(f"Secondary URL {len(urls)} (or 'done'): ").strip()
        if url_input.lower() == 'done': break
        if not (url_input.startswith('http://') or url_input.startswith('https://')): print("Err: URL format."); continue
        try: urlparse(url_input); urls.append(url_input)
        except: print("Err: Invalid URL.")
    user_importance = "Interesting"
    while True:
        choice = input("Mark as (1) Interesting or (2) Breaking [Default: 1]: ").strip()
        if choice == '1' or not choice: user_importance = "Interesting"; break
        elif choice == '2': user_importance = "Breaking"; break
        else: print("Invalid choice.")
    is_trending = input("Mark as 'Trending Pick'? (yes/no) [Default: no]: ").strip().lower() == 'yes'
    user_img = None
    if input("Direct image URL? (yes/no) [Default: no]: ").strip().lower() == 'yes':
        img_input = input("Paste image URL: ").strip()
        if img_input.startswith('http://') or img_input.startswith('https://'): user_img = img_input
        else: print("Warn: Invalid image URL. Will scrape/search.")
    return urls, user_importance, is_trending, user_img

def get_content_and_initial_title(url):
    logger.info(f"Fetching content & title from: {url}")
    content = get_full_article_content(url); title = "Untitled Gyro Pick"
    if content:
        try:
            from bs4 import BeautifulSoup; soup = BeautifulSoup(content, 'html.parser')
            if soup.title and soup.title.string: title = soup.title.string.strip()
            elif soup.find('h1'): title = soup.find('h1').get_text(strip=True)
            if title: title = re.sub(r'\s+', ' ', title).strip()
            logger.info(f"Scraped initial title: '{title}'")
        except Exception as e: logger.warning(f"Could not scrape title from {url}: {e}")
    else: logger.warning(f"Content fetch failed for {url}."); content = f"Content for '{url}' could not be fetched."
    return content, title

def determine_image_url_for_gyro(user_img, sources, title):
    if user_img: logger.info(f"Using user image: {user_img}"); return user_img
    logger.info("No user image. Scraping sources...")
    for url_to_scan in sources: # Iterate through all provided source URLs for an image
        scraped = scrape_source_for_image(url_to_scan)
        if scraped: logger.info(f"Scraped from {url_to_scan}: {scraped}"); return scraped
    logger.warning(f"Image scrape failed for all sources. SerpAPI search: '{title}'.")
    if not title or title == "Untitled Gyro Pick": return "https://via.placeholder.com/1200x675.png?text=Image+Unavailable"
    hint = sources[0] if sources else None
    searched = find_best_image(title, article_url_for_scrape=hint)
    if searched: logger.info(f"Found via SerpAPI: {searched}"); return searched
    logger.error(f"Image search failed for '{title}'. Placeholder."); return "https://via.placeholder.com/1200x675.png?text=Image+Not+Found"

def save_processed_gyro_pick_json(article_id, data):
    global current_post_template_hash_gyro
    if current_post_template_hash_gyro: data['post_template_hash'] = current_post_template_hash_gyro
    else: logger.warning(f"Template hash None for {article_id}.")
    os.makedirs(PROCESSED_JSON_DIR, exist_ok=True)
    filepath = os.path.join(PROCESSED_JSON_DIR, f"{article_id}.json")
    try:
        with open(filepath, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
        logger.info(f"Saved Gyro JSON: {os.path.basename(filepath)}"); return True
    except Exception as e: logger.error(f"Failed save Gyro JSON {os.path.basename(filepath)}: {e}"); return False

def format_tags_for_html(tags): 
    if not tags: return ""
    links = []; base = YOUR_SITE_BASE_URL_FOR_LINKS
    for tag in tags:
        safe = quote(str(tag)); url = urljoin(base, f"topic.html?name={safe}")
        links.append(f'<a href="{url}" class="tag-link">{html.escape(str(tag))}</a>')
    return ", ".join(links)

def render_gyro_pick_html(variables, slug):
    try:
        template = jinja_env.get_template('post_template.html'); html_out = template.render(variables)
        fname_base = slug or variables.get('id', 'untitled-gyro')
        tmp_slug = re.sub(r'[^\w\s-]', '', str(fname_base).lower()).strip(); tmp_slug = re.sub(r'[-\s]+', '-', tmp_slug)
        fname = tmp_slug[:80] or variables.get('id', 'gyro-err-slug')
        os.makedirs(OUTPUT_HTML_DIR, exist_ok=True)
        fpath = os.path.join(OUTPUT_HTML_DIR, f"{fname}.html")
        with open(fpath, 'w', encoding='utf-8') as f: f.write(html_out)
        logger.info(f"Rendered HTML (Gyro): {os.path.basename(fpath)}")
        return fpath, f"articles/{fname}.html"
    except Exception as e: logger.exception(f"HTML Render Fail (Gyro) ID {variables.get('id','N/A')}: {e}"); return None, None

def get_article_sort_key(item): 
    fallback = datetime(1970, 1, 1, tzinfo=timezone.utc)
    iso_str = item.get('published_iso')
    if not iso_str: return fallback
    try:
        if iso_str.endswith('Z'): iso_str = iso_str[:-1] + '+00:00'
        dt = datetime.fromisoformat(iso_str)
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except ValueError: logger.warning(f"Date parse error '{iso_str}'."); return fallback

def update_all_articles_list_json(summary): 
    all_articles = []
    if os.path.exists(ALL_ARTICLES_FILE):
        try:
            with open(ALL_ARTICLES_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
            if isinstance(data, dict) and "articles" in data: all_articles = data.get("articles", [])
            elif isinstance(data, list): all_articles = data
            if not isinstance(all_articles, list): all_articles = []
        except Exception as e: logger.error(f"Error loading {ALL_ARTICLES_FILE}: {e}.")
    
    pick_id = summary.get('id')
    if not pick_id: logger.error("Gyro summary missing ID."); return
    
    all_articles = [a for a in all_articles if isinstance(a, dict) and a.get('id') != pick_id]
    all_articles.append(summary)
    all_articles.sort(key=get_article_sort_key, reverse=True)
    
    try:
        with open(ALL_ARTICLES_FILE, 'w', encoding='utf-8') as f: json.dump({"articles": all_articles}, f, indent=2, ensure_ascii=False)
        logger.info(f"Updated {os.path.basename(ALL_ARTICLES_FILE)} ({len(all_articles)} articles).")
    except Exception as e: logger.error(f"Failed save {os.path.basename(ALL_ARTICLES_FILE)}: {e}")

# --- Main Processing Logic for a single Gyro Pick instance ---
def process_one_gyro_pick(article_urls, mode, user_importance_override=None, user_is_trending_pick=None, user_provided_image_url=None):
    global current_post_template_hash_gyro 
    if not current_post_template_hash_gyro: 
        current_post_template_hash_gyro = get_file_hash(POST_TEMPLATE_FILE)
        if not current_post_template_hash_gyro:
             logger.critical("CRITICAL: Could not hash Gyro Pick template. Aborting pick."); return False

    if not article_urls: logger.error("No URLs for this Gyro Pick. Skipping."); return False
    primary_url = article_urls[0]
    logger.info(f"--- Starting Gyro Pick ({mode} mode) for URL: {primary_url} ---")

    gyro_pick_id = generate_article_id(primary_url) 
    
    if os.path.exists(os.path.join(PROCESSED_JSON_DIR, f"{gyro_pick_id}.json")):
        logger.warning(f"Gyro Pick ID {gyro_pick_id} (from {primary_url}) already has a processed JSON. Skipping.")
        return False

    content_for_agents, initial_title = get_content_and_initial_title(primary_url)
    if not content_for_agents: logger.error(f"No content from {primary_url}. Cannot proceed."); return False

    image_url_to_use = determine_image_url_for_gyro(user_provided_image_url, article_urls, initial_title)
    current_time_iso_str = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    article_data = {
        'id': gyro_pick_id, 'title': initial_title, 'link': primary_url,
        'all_source_links': article_urls, 'published_iso': current_time_iso_str,
        'summary': (content_for_agents[:300] + "...") if content_for_agents and len(content_for_agents) > 300 else content_for_agents,
        'full_text_content': content_for_agents, 'content_for_processing': content_for_agents,
        'source_feed': f"Gyro Pick - {mode} Mode", 'scraped_at_iso': current_time_iso_str,
        'selected_image_url': image_url_to_use, 'author': AUTHOR_NAME_DEFAULT,
    }
    
    logger.info(f"Running Similarity Check for Gyro Pick {gyro_pick_id}...")
    article_data = run_similarity_check_agent(article_data, PROCESSED_JSON_DIR, current_run_processed_articles_data_list=None) 
    similarity_verdict = article_data.get('similarity_verdict', 'ERROR')

    if mode == "Quick" and similarity_verdict != "OKAY" and not similarity_verdict.startswith("OKAY_"):
        logger.warning(f"Quick Mode Gyro Pick {gyro_pick_id} flagged by similarity: {similarity_verdict} (to {article_data.get('similar_article_id', 'N/A')}). Skipping.")
        return False
    elif mode == "Advanced" and similarity_verdict != "OKAY" and not similarity_verdict.startswith("OKAY_"):
        logger.info(f"Advanced Mode Gyro Pick {gyro_pick_id} flagged by similarity: {similarity_verdict} (to {article_data.get('similar_article_id', 'N/A')}). Proceeding as Advanced overrides this.")
    
    logger.info(f"Filter Agent for Gyro Pick ID: {gyro_pick_id}...")
    article_data = run_filter_agent(article_data.copy()) 
    if not article_data or article_data.get('filter_verdict') is None:
        logger.error(f"Filter Agent failed for Gyro Pick {gyro_pick_id}. ABORTING."); return False
    
    filter_agent_verdict = article_data['filter_verdict']
    
    if mode == "Quick":
        if filter_agent_verdict.get('importance_level') == "Boring":
            logger.info(f"Quick Mode Gyro Pick {gyro_pick_id} classified 'Boring' by Filter Agent. Skipping."); return False
        article_data['is_breaking'] = (filter_agent_verdict.get('importance_level') == "Breaking")
    elif mode == "Advanced":
        logger.info(f"Advanced Mode: Overriding Filter Agent importance. User set: {user_importance_override}. Filter suggested: {filter_agent_verdict.get('importance_level')}")
        article_data['is_breaking'] = (user_importance_override == "Breaking")
        article_data['filter_verdict']['importance_level'] = user_importance_override 

    article_data['topic'] = filter_agent_verdict.get('topic', 'General Technology News')
    article_data['primary_keyword'] = filter_agent_verdict.get('primary_topic_keyword', initial_title)

    logger.info(f"Keyword Research for Gyro Pick ID: {gyro_pick_id}...")
    article_data = run_keyword_research_agent(article_data.copy())
    researched_kw_list = article_data.get('researched_keywords', [])
    primary_kw_from_filter = article_data.get('primary_keyword') 
    final_tags_list = []
    if primary_kw_from_filter and isinstance(primary_kw_from_filter, str) and len(primary_kw_from_filter.strip()) > 1:
        final_tags_list.append(primary_kw_from_filter.strip())
    if researched_kw_list:
        for kw_item in researched_kw_list:
            if kw_item and isinstance(kw_item, str) and len(kw_item.strip()) > 1 and kw_item.strip().lower() not in (t.lower() for t in final_tags_list):
                final_tags_list.append(kw_item.strip())
    if not final_tags_list:
        logger.warning(f"No usable keywords/tags for {gyro_pick_id}. Using generic: Topic and 'AI Insights'.")
        final_tags_list = [article_data.get('topic', "Tech News"), "AI Insights"]
    article_data['generated_tags'] = final_tags_list[:15]

    logger.info(f"SEO Article Generation for Gyro Pick ID: {gyro_pick_id}...")
    article_data = run_seo_article_agent(article_data.copy()) 
    seo_agent_results = article_data.get('seo_agent_results')
    if not seo_agent_results or not seo_agent_results.get('generated_article_body_md'):
        logger.error(f"SEO Agent failed for Gyro Pick {gyro_pick_id} or returned invalid/incomplete results. ABORTING."); return False
    if article_data.get('seo_agent_error'): 
        logger.warning(f"SEO Agent reported non-critical errors for Gyro Pick {gyro_pick_id}: {article_data['seo_agent_error']}")

    final_seo_title = article_data.get('title', initial_title) 
    logger.info(f"Final AI Generated Title for Gyro Pick {gyro_pick_id}: '{final_seo_title}'")

    gyro_trend_score = 0.0
    if article_data.get('is_breaking', False): gyro_trend_score += 10.0
    else: gyro_trend_score += 5.0 
    
    actual_is_trending_pick = user_is_trending_pick if mode == "Advanced" and user_is_trending_pick is not None else False
    if actual_is_trending_pick: gyro_trend_score += 7.0

    gyro_trend_score += float(len(article_data.get('generated_tags', []))) * 0.3
    article_data['trend_score'] = round(max(0.0, gyro_trend_score), 2)

    slug_for_file = slugify(final_seo_title) 
    article_data['slug'] = slug_for_file or f'gyro-pick-{gyro_pick_id}' 
    
    article_relative_web_path = f"articles/{article_data['slug']}.html"
    canonical_page_url = urljoin(YOUR_SITE_BASE_URL_FOR_LINKS, article_relative_web_path.lstrip('/')) if YOUR_SITE_BASE_URL_FOR_LINKS and YOUR_SITE_BASE_URL_FOR_LINKS != '/' else f"/{article_relative_web_path.lstrip('/')}"
    
    article_body_markdown_raw = seo_agent_results.get('generated_article_body_md', '')
    article_body_markdown_with_links = process_link_placeholders(article_body_markdown_raw, YOUR_SITE_BASE_URL_FOR_LINKS) 
    article_body_html_content = html.unescape(markdown.markdown(article_body_markdown_with_links, extensions=['fenced_code', 'tables', 'nl2br', 'sane_lists', 'extra']))
    
    article_tags_html_content = format_tags_for_html(article_data.get('generated_tags', []))
    publish_datetime_obj = get_article_sort_key(article_data) 
    
    raw_json_ld = seo_agent_results.get('generated_json_ld_raw', '{}')
    placeholder_in_json_ld = f"{BASE_URL_FOR_CANONICAL_PLACEHOLDER_CHECK.rstrip('/')}/articles/{{SLUG_PLACEHOLDER}}"
    final_json_ld_script_tag = seo_agent_results.get('generated_json_ld_full_script_tag', '<script type="application/ld+json">{}</script>')
    if placeholder_in_json_ld in raw_json_ld: 
        final_json_ld_str = raw_json_ld.replace(placeholder_in_json_ld, canonical_page_url)
        final_json_ld_script_tag = f'<script type="application/ld+json">\n{final_json_ld_str}\n</script>'

    template_render_variables = {
        'PAGE_TITLE': seo_agent_results.get('generated_title_tag', final_seo_title),
        'META_DESCRIPTION': seo_agent_results.get('generated_meta_description', ''),
        'AUTHOR_NAME': article_data.get('author', AUTHOR_NAME_DEFAULT),
        'META_KEYWORDS_LIST': article_data.get('generated_tags', []), 
        'CANONICAL_URL': canonical_page_url,
        'SITE_NAME': YOUR_WEBSITE_NAME, 
        'YOUR_WEBSITE_LOGO_URL': YOUR_WEBSITE_LOGO_URL,
        'IMAGE_URL': article_data.get('selected_image_url', ''), 
        'IMAGE_ALT_TEXT': final_seo_title,
        'PUBLISH_ISO_FOR_META': article_data.get('published_iso', current_time_iso_str),
        'JSON_LD_SCRIPT_BLOCK': final_json_ld_script_tag, 
        'ARTICLE_HEADLINE': final_seo_title, 
        'ARTICLE_SEO_H1': final_seo_title, 
        'PUBLISH_DATE': publish_datetime_obj.strftime('%B %d, %Y') if publish_datetime_obj != datetime(1970,1,1,tzinfo=timezone.utc) else "Date Not Available",
        'ARTICLE_BODY_HTML': article_body_html_content, 
        'ARTICLE_TAGS_HTML': article_tags_html_content,
        'SOURCE_ARTICLE_URL': article_data.get('link', '#'), 
        'ARTICLE_TITLE': final_seo_title, 
        'id': gyro_pick_id, 
        'CURRENT_ARTICLE_ID': gyro_pick_id, 
        'CURRENT_ARTICLE_TOPIC': article_data.get('topic', 'News'),
        'CURRENT_ARTICLE_TAGS_JSON': json.dumps(article_data.get('generated_tags', [])), 
        'AUDIO_URL': None 
    }

    rendered_html_path, relative_web_link = render_gyro_pick_html(template_render_variables, article_data['slug'])
    if not rendered_html_path: 
        logger.error(f"Failed to render HTML for Gyro Pick {gyro_pick_id}. Aborting final save steps.")
        return False

    if not save_processed_gyro_pick_json(gyro_pick_id, article_data): 
        logger.error(f"Failed to save processed JSON for Gyro Pick {gyro_pick_id}.")
        return False 

    summary_for_all_articles = {
        "id": gyro_pick_id, "title": final_seo_title, "link": relative_web_link,
        "published_iso": article_data.get('published_iso', current_time_iso_str),
        "summary_short": seo_agent_results.get('generated_meta_description', ''),
        "image_url": article_data.get('selected_image_url'), "topic": article_data.get('topic', 'News'),
        "is_breaking": article_data.get('is_breaking', False), 
        "is_trending_pick": actual_is_trending_pick, 
        "tags": article_data.get('generated_tags', []), "audio_url": None, 
        "trend_score": article_data.get('trend_score', 0)
    }
    update_all_articles_list_json(summary_for_all_articles)

    logger.info(f"--- Successfully processed Gyro Pick: {gyro_pick_id} ('{final_seo_title}') ---")
    logger.info(f"    HTML Output: {os.path.relpath(rendered_html_path, PROJECT_ROOT)}")
    logger.info(f"    Processed JSON: {os.path.join(PROCESSED_JSON_DIR, f'{gyro_pick_id}.json')}")
    return True


if __name__ == "__main__":
    if not os.getenv('DEEPSEEK_API_KEY'):
        logger.error("DEEPSEEK_API_KEY is not set. GyroPicks pipeline cannot run."); sys.exit(1)
    ensure_directories()
    current_post_template_hash_gyro = get_file_hash(POST_TEMPLATE_FILE)
    if not current_post_template_hash_gyro:
        logger.critical(f"CRITICAL: GyroPicks could not hash template: {POST_TEMPLATE_FILE}. Exiting."); sys.exit(1)
    logger.info(f"GyroPicks using template hash: {current_post_template_hash_gyro}")

    while True:
        mode_choice = input("\nGyro Pick: (1) Quick Add (2) Advanced Add (0) Exit: ").strip()
        if mode_choice == '0': break
        elif mode_choice == '1':
            q_urls = get_quick_add_urls()
            if not q_urls: continue
            p_count = 0
            for i, url in enumerate(q_urls):
                logger.info(f"\nProcessing Quick Add {i+1}/{len(q_urls)}: {url}")
                if process_one_gyro_pick([url], mode="Quick"): p_count += 1
                if i < len(q_urls) - 1: logger.info("Brief pause..."); time.sleep(2) # Reduced delay for testing
            logger.info(f"Quick Add finished. Processed {p_count}/{len(q_urls)}.")
        elif mode_choice == '2':
            adv_urls, imp, trend, img = get_advanced_add_inputs()
            if not adv_urls: continue
            process_one_gyro_pick(adv_urls, mode="Advanced", user_importance_override=imp, user_is_trending_pick=trend, user_provided_image_url=img)
        else: print("Invalid choice.")

    if YOUR_SITE_BASE_URL_FOR_LINKS and YOUR_SITE_BASE_URL_FOR_LINKS != '/':
        logger.info("--- Sitemap Gen Post Gyro ---");
        try: run_sitemap_generator(); logger.info("Sitemap OK.")
        except Exception as e: logger.error(f"Sitemap failed: {e}")
    else: logger.warning("Sitemap skipped: YOUR_SITE_BASE_URL invalid.")
    logger.info("--- Gyro Picks script finished. ---")