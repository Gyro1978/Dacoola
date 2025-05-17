# src/main.py (Orchestrator - Fully Integrated with All Agents - Corrected with logging)

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
import hashlib
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, quote
import markdown

# --- Import Sitemap Generator ---
try:
    from generate_sitemap import generate_sitemap as run_sitemap_generator
except ImportError as e:
    temp_log_msg = f"FATAL IMPORT ERROR: Could not import sitemap generator: {e}."
    print(temp_log_msg); logging.critical(temp_log_msg); sys.exit(1)

# --- Import Agent Functions ---
try:
    from src.agents.web_research_agent import run_web_research_agent
    from src.agents.filter_enrich_agent import run_filter_enrich_agent
    from src.agents.deduplication_agent import (
        run_deduplication_agent,
        load_historical_embeddings,
        save_historical_embeddings
    )
    from src.agents.keyword_intelligence_agent import run_keyword_intelligence_agent
    from src.agents.seo_writing_agent import run_seo_writing_agent
    from src.agents.vision_media_agent import run_vision_media_agent
    from src.agents.image_integration_agent import run_image_integration_agent
    from src.agents.knowledge_graph_agent import run_knowledge_graph_agent, load_site_content_graph
    from src.agents.trending_digest_agent import run_trending_digest_agent
    
    from src.social.social_media_poster import (
        initialize_social_clients, run_social_media_poster,
        load_post_history as load_social_post_history,
        mark_article_as_posted_in_history # This is used by social_media_poster internally
    )
except ImportError as e:
     print(f"FATAL IMPORT ERROR in main.py (agents): {e}")
     try: logging.critical(f"FATAL IMPORT ERROR (agents): {e}")
     except: pass 
     sys.exit(1)

# --- Load Environment Variables ---
dotenv_path = os.path.join(PROJECT_ROOT_FOR_PATH, '.env'); load_dotenv(dotenv_path=dotenv_path)
AUTHOR_NAME_DEFAULT = os.getenv('AUTHOR_NAME', 'Dacoola AI Team')
YOUR_WEBSITE_NAME = os.getenv('YOUR_WEBSITE_NAME', 'Dacoola')
YOUR_WEBSITE_LOGO_URL = os.getenv('YOUR_WEBSITE_LOGO_URL', '')
raw_base_url = os.getenv('YOUR_SITE_BASE_URL', ''); YOUR_SITE_BASE_URL = (raw_base_url.rstrip('/') + '/') if raw_base_url else ''
BASE_URL_FOR_CANONICAL_MAIN = YOUR_SITE_BASE_URL 
MAKE_WEBHOOK_URL = os.getenv('MAKE_INSTAGRAM_WEBHOOK_URL', None)
DAILY_TWEET_LIMIT = int(os.getenv('DAILY_TWEET_LIMIT', '3'))
MAX_AGE_FOR_SOCIAL_POST_HOURS = int(os.getenv('MAX_AGE_FOR_SOCIAL_POST_HOURS', '24'))
MAX_ARTICLES_TO_PROCESS_PER_RUN = int(os.getenv('MAX_ARTICLES_TO_PROCESS_PER_RUN', '5')) 


# --- Setup Logging ---
log_file_path = os.path.join(PROJECT_ROOT_FOR_PATH, 'dacola.log')
try:
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    log_handlers = [ logging.StreamHandler(sys.stdout), logging.FileHandler(log_file_path, encoding='utf-8') ]
except OSError as e: print(f"Log setup warning: {e}. Log console only."); log_handlers = [logging.StreamHandler(sys.stdout)]

logging.basicConfig(
    level=logging.DEBUG, 
    format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=log_handlers,
    force=True
)
logger = logging.getLogger('main_orchestrator')

if not YOUR_SITE_BASE_URL or YOUR_SITE_BASE_URL == '/':
    logger.error("CRITICAL: YOUR_SITE_BASE_URL is not set or is invalid ('/'). Canonical URLs and sitemap will be incorrect.")
else:
    logger.info(f"Using site base URL: {YOUR_SITE_BASE_URL}")

# --- Configuration ---
DATA_DIR_MAIN = os.path.join(PROJECT_ROOT_FOR_PATH, 'data')
RAW_WEB_RESEARCH_OUTPUT_DIR = os.path.join(DATA_DIR_MAIN, 'raw_web_research') 
PROCESSED_JSON_DIR = os.path.join(DATA_DIR_MAIN, 'processed_json') 
PUBLIC_DIR = os.path.join(PROJECT_ROOT_FOR_PATH, 'public')
OUTPUT_HTML_DIR = os.path.join(PUBLIC_DIR, 'articles')
DIGEST_OUTPUT_HTML_DIR = os.path.join(PUBLIC_DIR, 'digests') 
TEMPLATE_DIR = os.path.join(PROJECT_ROOT_FOR_PATH, 'templates')
ALL_ARTICLES_FILE = os.path.join(PUBLIC_DIR, 'all_articles.json') 
TWITTER_DAILY_LIMIT_FILE = os.path.join(DATA_DIR_MAIN, 'twitter_daily_limit.json')
POST_TEMPLATE_FILE = os.path.join(TEMPLATE_DIR, 'post_template.html')
DIGEST_TEMPLATE_FILE = os.path.join(TEMPLATE_DIR, 'digest_page_template.html') 

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
    jinja_env_main = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(['html', 'xml']))
    jinja_env_main.filters['escapejs'] = escapejs_filter
    logger.info(f"Jinja2 environment loaded from {TEMPLATE_DIR}")
except ImportError: logger.critical("Jinja2 library not found. Exiting."); sys.exit(1)
except Exception as e: logger.exception(f"CRITICAL: Failed Jinja2 init. Exiting: {e}"); sys.exit(1)


# --- Helper Functions ---
def ensure_directories():
    dirs_to_create = [
        DATA_DIR_MAIN, RAW_WEB_RESEARCH_OUTPUT_DIR, PROCESSED_JSON_DIR,
        PUBLIC_DIR, OUTPUT_HTML_DIR, DIGEST_OUTPUT_HTML_DIR, TEMPLATE_DIR
    ]
    try:
        for d in dirs_to_create: os.makedirs(d, exist_ok=True)
        logger.info("Ensured core directories exist.")
    except OSError as e: logger.exception(f"CRITICAL dir create fail: {e}"); sys.exit(1)

def get_file_hash(filepath):
    hasher = hashlib.sha256();
    if not os.path.exists(filepath): logger.error(f"NOT FOUND for hash: {filepath}"); return None
    try:
        with open(filepath, 'rb') as f:
            buf = f.read(65536)
            while len(buf) > 0: hasher.update(buf); buf = f.read(65536)
        hex_digest = hasher.hexdigest(); return hex_digest
    except Exception as e: logger.error(f"Error hashing {filepath}: {e}"); return None

current_post_template_hash_main = None 
current_digest_template_hash_main = None 

def load_json_data(filepath, data_description="data"):
    try:
        with open(filepath, 'r', encoding='utf-8') as f: return json.load(f)
    except FileNotFoundError: logger.debug(f"{data_description} file not found: {filepath}"); return None
    except json.JSONDecodeError: logger.error(f"JSON decode error in {data_description} file: {filepath}."); return None
    except Exception as e: logger.error(f"Error loading {data_description} from {filepath}: {e}"); return None

def save_json_data(filepath, data_to_save, data_description="data"):
    try:
         os.makedirs(os.path.dirname(filepath), exist_ok=True)
         with open(filepath, 'w', encoding='utf-8') as f: json.dump(data_to_save, f, indent=4, ensure_ascii=False)
         logger.info(f"Saved {data_description} to: {os.path.basename(filepath)}"); return True
    except Exception as e: logger.error(f"Failed to save {data_description} to {os.path.basename(filepath)}: {e}"); return False

def get_article_universal_id(article_url_or_identifier_string):
    if not article_url_or_identifier_string:
        # Fallback if truly no identifier - should be rare with Gyro having its own ID
        return hashlib.sha256(str(time.time()).encode('utf-8')).hexdigest()
    return hashlib.sha256(str(article_url_or_identifier_string).encode('utf-8')).hexdigest()


def get_sort_key_for_all_articles(item):
    fallback = datetime(1970, 1, 1, tzinfo=timezone.utc); iso_str = item.get('published_iso')
    if not iso_str: return fallback
    try:
        if iso_str.endswith('Z'): iso_str = iso_str[:-1] + '+00:00'
        dt = datetime.fromisoformat(iso_str)
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except ValueError: logger.warning(f"Date parse error '{iso_str}' for all_articles.json sort. Fallback."); return fallback

def _read_tweet_tracker():
    today_utc_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    default_data = {'date': today_utc_str, 'count': 0}
    try:
        os.makedirs(os.path.dirname(TWITTER_DAILY_LIMIT_FILE), exist_ok=True) # Ensure directory exists
        if os.path.exists(TWITTER_DAILY_LIMIT_FILE):
            with open(TWITTER_DAILY_LIMIT_FILE, 'r', encoding='utf-8') as f: 
                data = json.load(f)
            if data.get('date') == today_utc_str:
                return data['date'], data.get('count', 0)
        
        # If file doesn't exist, or date is old, create/overwrite it with default
        with open(TWITTER_DAILY_LIMIT_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_data, f, indent=2)
        logger.info(f"Initialized/reset Twitter tracker for {today_utc_str} at {TWITTER_DAILY_LIMIT_FILE}.")
        return today_utc_str, 0
    except Exception as e:
        logger.error(f"Error R/W Twitter tracker: {e}. Resetting count for {today_utc_str}.")
        try: # Try to write default even on error
            with open(TWITTER_DAILY_LIMIT_FILE, 'w', encoding='utf-8') as f:
                json.dump(default_data, f, indent=2)
        except Exception as e_write:
            logger.error(f"Could not even write default twitter tracker: {e_write}")
        return today_utc_str, 0

def slugify_filename(text_to_slugify):
    if not text_to_slugify: return "untitled-slug"
    s = str(text_to_slugify).strip().lower()
    s = re.sub(r'[^\w\s-]', '', s) 
    s = re.sub(r'[-\s]+', '-', s) 
    return s[:75] 

def format_tags_html_main(tags_list): 
    if not tags_list: return ""
    try:
        links = []; base = YOUR_SITE_BASE_URL 
        for tag_item in tags_list:
            tag_str = str(tag_item) if tag_item is not None else "untagged"
            safe_tag_slug = slugify_filename(tag_str) # Slugify for URL consistency
            quoted_slug = quote(safe_tag_slug)
            url = urljoin(base, f"topic.html?name={quoted_slug}") 
            links.append(f'<a href="{url}" class="tag-link">{html.escape(tag_str)}</a>') # Display original tag text
        return ", ".join(links)
    except Exception as e:
        logger.error(f"Error formatting tags HTML (main): {tags_list} - {e}")
        return "Error formatting tags"

def process_final_markdown_to_html_main(markdown_text):
    if not markdown_text: return ""
    
    # Custom link processing MUST happen BEFORE markdown.markdown()
    # Convert custom internal article links: [[Text | articles/slug.html]]
    markdown_text = re.sub(r'\[\[\s*(.*?)\s*\|\s*(articles\/.*?\.html)\s*\]\]', 
                           r'<a href="/\2" class="internal-link">\1</a>', 
                           markdown_text)
    # Convert custom internal topic links: [[Text | Topic Name]] (slugify Topic Name for URL)
    markdown_text = re.sub(r'\[\[\s*(.*?)\s*\|\s*([^\]]+?)\s*\]\]', 
                           lambda m: f'<a href="/topic.html?name={quote(slugify_filename(m.group(2).strip()))}" class="internal-link">{m.group(1).strip()}</a>', 
                           markdown_text)
    # Convert custom internal topic links (short form, no pipe): [[Topic Name Only]]
    markdown_text = re.sub(r'\[\[\s*([^\]|]+?)\s*\]\]', 
                           lambda m: f'<a href="/topic.html?name={quote(slugify_filename(m.group(1).strip()))}" class="internal-link">{m.group(1).strip()}</a>', 
                           markdown_text)
    # Convert custom external links: ((Text | URL))
    markdown_text = re.sub(r'\(\(\s*(.*?)\s*\|\s*(https?://.*?)\s*\)\)', 
                           r'<a href="\2" class="external-link" target="_blank" rel="noopener noreferrer">\1</a>', 
                           markdown_text)

    html_content = markdown.markdown(markdown_text, extensions=['fenced_code', 'tables', 'nl2br', 'sane_lists', 'extra', 'attr_list'])
    return html.unescape(html_content)


def render_html_page_main(template_name, template_vars, output_dir, output_filename_base):
    """Generic HTML page renderer, used by main."""
    try:
        template = jinja_env_main.get_template(template_name)
        html_page_content = template.render(template_vars)
        
        filepath = os.path.join(output_dir, f"{output_filename_base}.html")
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_page_content)
        logger.info(f"Successfully rendered HTML page '{template_name}' to: {filepath}")
        return True
    except Exception as e:
        logger.exception(f"Failed to render/save HTML page '{template_name}' for {output_filename_base}: {e}")
        return False

def update_master_article_list_json(article_summary_data):
    if not article_summary_data or not isinstance(article_summary_data, dict) or not article_summary_data.get('id'):
        logger.error("Cannot update all_articles.json: Invalid or missing article summary data/ID.")
        return

    all_articles_data_envelope = load_json_data(ALL_ARTICLES_FILE, "all_articles_summary")
    all_articles_list = []
    if all_articles_data_envelope and isinstance(all_articles_data_envelope, dict) and 'articles' in all_articles_data_envelope and isinstance(all_articles_data_envelope['articles'], list):
        all_articles_list = all_articles_data_envelope['articles']
    elif all_articles_data_envelope is not None: 
        logger.warning(f"Format of {ALL_ARTICLES_FILE} unexpected or empty. Starting new list.")
    
    article_id_to_update = article_summary_data['id']
    all_articles_list = [art for art in all_articles_list if isinstance(art,dict) and art.get('id') != article_id_to_update]
    all_articles_list.append(article_summary_data)
    all_articles_list.sort(key=get_sort_key_for_all_articles, reverse=True)
    save_json_data(ALL_ARTICLES_FILE, {"articles": all_articles_list}, "master article list")


# --- Main Orchestration Logic ---
if __name__ == "__main__":
    run_start_timestamp = time.time()
    logger.info(f"--- === Dacoola AI Content Engine - Orchestrator Starting Run ({datetime.now(timezone.utc).isoformat()}) === ---")
    ensure_directories()

    logger.info(f"Hashing templates: {POST_TEMPLATE_FILE}, {DIGEST_TEMPLATE_FILE}")
    current_post_template_hash_main = get_file_hash(POST_TEMPLATE_FILE)
    current_digest_template_hash_main = get_file_hash(DIGEST_TEMPLATE_FILE) 
    if not current_post_template_hash_main:
        logger.critical(f"CRITICAL FAILURE: Could not hash post_template.html. Exiting.")
        sys.exit(1)
    if not current_digest_template_hash_main: 
        logger.warning(f"Warning: Could not hash digest_page_template.html. Digest regen might be affected.")
    logger.info(f"Current post_template.html hash: {current_post_template_hash_main}")
    logger.info(f"Current digest_template.html hash: {current_digest_template_hash_main}")

    social_media_clients = initialize_social_clients()
    
    logger.info("--- Stage 0: Checking/Regenerating HTML for existing processed articles & digests ---")
    all_existing_processed_files = glob.glob(os.path.join(PROCESSED_JSON_DIR, '*.json'))
    html_regen_count_articles = 0
    if all_existing_processed_files:
        for proc_json_file in all_existing_processed_files:
            article_data_for_regen = load_json_data(proc_json_file, f"regen check: {os.path.basename(proc_json_file)}")
            if not article_data_for_regen or not article_data_for_regen.get('id') or not article_data_for_regen.get('slug'):
                 logger.warning(f"Skipping HTML regen for {os.path.basename(proc_json_file)}: missing id/slug or invalid data.")
                 continue
            
            seo_results_regen = article_data_for_regen.get('seo_agent_results')
            if not isinstance(seo_results_regen, dict): seo_results_regen = {} 

            stored_template_hash = article_data_for_regen.get('post_template_hash')
            html_file_path_check = os.path.join(OUTPUT_HTML_DIR, f"{article_data_for_regen['slug']}.html")
            
            if not os.path.exists(html_file_path_check) or stored_template_hash != current_post_template_hash_main:
                logger.info(f"Regenerating HTML for {article_data_for_regen['id']} (Reason: {'missing HTML' if not os.path.exists(html_file_path_check) else 'template changed'}).")
                
                template_vars_for_regen = {
                    'PAGE_TITLE': seo_results_regen.get('generated_title_tag', article_data_for_regen.get('final_title', article_data_for_regen.get('initial_title_from_web', 'Untitled'))),
                    'META_DESCRIPTION': seo_results_regen.get('generated_meta_description', 'Read the latest AI and tech news from Dacoola.'),
                    'AUTHOR_NAME': article_data_for_regen.get('author', AUTHOR_NAME_DEFAULT),
                    'META_KEYWORDS_LIST': article_data_for_regen.get('final_keywords', []),
                    'CANONICAL_URL': urljoin(YOUR_SITE_BASE_URL, f"articles/{article_data_for_regen['slug']}.html".lstrip('/')),
                    'SITE_NAME': YOUR_WEBSITE_NAME,
                    'YOUR_WEBSITE_LOGO_URL': YOUR_WEBSITE_LOGO_URL,
                    'IMAGE_URL': article_data_for_regen.get('selected_image_url', ''),
                    'IMAGE_ALT_TEXT': article_data_for_regen.get('final_featured_image_alt_text', article_data_for_regen.get('final_title', 'Article Image')),
                    'PUBLISH_ISO_FOR_META': article_data_for_regen.get('published_iso', datetime.now(timezone.utc).isoformat()),
                    'JSON_LD_SCRIPT_BLOCK': seo_results_regen.get('generated_json_ld_full_script_tag','<script type="application/ld+json">{}</script>'),
                    'ARTICLE_HEADLINE': article_data_for_regen.get('final_title', article_data_for_regen.get('initial_title_from_web', 'Untitled')),
                    'ARTICLE_SEO_H1': article_data_for_regen.get('final_title', article_data_for_regen.get('initial_title_from_web', 'Untitled')),
                    'PUBLISH_DATE': get_sort_key_for_all_articles(article_data_for_regen).strftime('%B %d, %Y') if article_data_for_regen.get('published_iso') else "Date Not Available",
                    'ARTICLE_BODY_HTML': process_final_markdown_to_html_main(seo_results_regen.get('generated_article_body_md','')),
                    'ARTICLE_TAGS_HTML': format_tags_html_main(article_data_for_regen.get('final_keywords',[])),
                    'SOURCE_ARTICLE_URL': article_data_for_regen.get('original_source_url','#'),
                    'ARTICLE_TITLE': article_data_for_regen.get('final_title', article_data_for_regen.get('initial_title_from_web', 'Untitled')),
                    'id': article_data_for_regen['id'],
                    'CURRENT_ARTICLE_ID': article_data_for_regen['id'],
                    'CURRENT_ARTICLE_TOPIC': article_data_for_regen.get('primary_topic','News'),
                    'CURRENT_ARTICLE_TAGS_JSON': json.dumps(article_data_for_regen.get('final_keywords',[])),
                    'AUDIO_URL': article_data_for_regen.get('generated_audio_url')
                }
                if render_html_page_main('post_template.html', template_vars_for_regen, OUTPUT_HTML_DIR, article_data_for_regen['slug']):
                    article_data_for_regen['post_template_hash'] = current_post_template_hash_main
                    save_json_data(proc_json_file, article_data_for_regen, f"processed article {article_data_for_regen['id']} (hash update)")
                    html_regen_count_articles +=1
    logger.info(f"Article HTML Regeneration complete. Regenerated/Verified {html_regen_count_articles} files.")
    
    # --- Stage 1: Web Research / Gyro Picks ---
    raw_articles_from_web = [] # Initialize empty list
    # Web Research (Optional, can be primary source if no Gyro Picks)
    # To disable, comment out or set topics_for_research to empty list
    run_web_research = True # Set to False to disable Web Research Agent
    if run_web_research:
        logger.info("--- Stage 1a: Running Web Research Agent ---")
        topics_for_research = [ 
            "latest breakthroughs in AI model architectures", "NVIDIA AI hardware news", "OpenAI new products",
            "Google DeepMind advancements", "AI ethics and regulation", "Robotics and AI"
        ]
        web_agent_articles = run_web_research_agent(topics_for_research) 
        if web_agent_articles:
            logger.info(f"Web Research Agent found {len(web_agent_articles)} raw articles.")
            raw_articles_from_web.extend(web_agent_articles)
        else: 
            logger.info("Web Research Agent found no new articles.")
    else:
        logger.info("Skipping Web Research Agent based on configuration.")


    # Process Gyro Picks
    gyro_pick_files = glob.glob(os.path.join(RAW_WEB_RESEARCH_OUTPUT_DIR, "gyro-*.json"))
    if gyro_pick_files:
        logger.info(f"--- Stage 1b: Processing {len(gyro_pick_files)} raw Gyro Pick files ---")
        for gyro_file_path in gyro_pick_files:
            gyro_data = load_json_data(gyro_file_path, "raw gyro pick")
            if gyro_data: 
                raw_articles_from_web.append(gyro_data) 
            else: 
                logger.warning(f"Could not load gyro pick file: {gyro_file_path}")
    else:
        logger.info("No Gyro Pick files found in raw_web_research directory.")
    
    successfully_processed_articles_this_run = []
    social_media_queue_this_run = []
    historical_embeddings = load_historical_embeddings()
    site_content_graph_data = load_site_content_graph() 

    logger.info(f"--- Starting main processing pipeline for {len(raw_articles_from_web)} total raw items (Web Research + Gyro) ---")
    processed_in_run_count = 0
    for raw_article_input in raw_articles_from_web:
        if processed_in_run_count >= MAX_ARTICLES_TO_PROCESS_PER_RUN:
            logger.info(f"Reached MAX_ARTICLES_TO_PROCESS_PER_RUN ({MAX_ARTICLES_TO_PROCESS_PER_RUN}). Stopping further processing.")
            break

        article_id_source_key = raw_article_input.get('id') 
        if not article_id_source_key: 
            article_id_source_key = raw_article_input.get('url') 
        
        if not article_id_source_key: 
            logger.warning(f"Raw article input missing 'id' (for Gyro) and 'url' (for Web). Skipping. Data: {str(raw_article_input)[:200]}")
            continue
            
        current_article_id_str = get_article_universal_id(article_id_source_key)
        
        logger.info(f"MAIN.PY RAW_INPUT: url={raw_article_input.get('original_source_url', raw_article_input.get('url', 'N/A'))}, gyro={raw_article_input.get('is_gyro_pick', False)}, RAW_TITLE: {raw_article_input.get('initial_title_from_web', raw_article_input.get('title','N/A'))}")
        logger.info(f"--- Processing Article ID: {current_article_id_str} (Source Key: {str(article_id_source_key)[:60]}) ---")

        processed_json_path = os.path.join(PROCESSED_JSON_DIR, f"{current_article_id_str}.json")
        if os.path.exists(processed_json_path):
            logger.info(f"Article {current_article_id_str} already has a final processed JSON. Skipping full pipeline.")
            if raw_article_input.get('is_gyro_pick') and raw_article_input.get('id'):
                raw_gyro_file_to_remove = os.path.join(RAW_WEB_RESEARCH_OUTPUT_DIR, f"{raw_article_input.get('id')}.json")
                if os.path.exists(raw_gyro_file_to_remove):
                    try: os.remove(raw_gyro_file_to_remove); logger.debug(f"Removed already-processed raw Gyro file: {raw_gyro_file_to_remove}")
                    except Exception as e_rem: logger.warning(f"Could not remove raw Gyro file {raw_gyro_file_to_remove}: {e_rem}")
            continue

        article_pipeline_data = {
            'id': current_article_id_str,
            'original_source_url': raw_article_input.get('url', raw_article_input.get('original_source_url')), 
            'initial_title_from_web': raw_article_input.get('title', raw_article_input.get('initial_title_from_web')), 
            'raw_scraped_text': raw_article_input.get('scraped_text', raw_article_input.get('raw_scraped_text')), 
            'research_topic': raw_article_input.get('research_topic'), 
            'published_iso': raw_article_input.get('retrieved_at', raw_article_input.get('published_iso', datetime.now(timezone.utc).isoformat())), 
            'pipeline_status': 'started',
            'is_gyro_pick': raw_article_input.get('is_gyro_pick', False),
            'gyro_pick_mode': raw_article_input.get('gyro_pick_mode'),
            'user_importance_override_gyro': raw_article_input.get('user_importance_override_gyro'),
            'user_is_trending_pick_gyro': raw_article_input.get('user_is_trending_pick_gyro'),
            'selected_image_url': raw_article_input.get('selected_image_url'), 
            'author': raw_article_input.get('author', AUTHOR_NAME_DEFAULT) 
        }
        
        logger.info(f"MAIN.PY PIPELINE_DATA_INIT for ID {article_pipeline_data.get('id')}: Title='{article_pipeline_data.get('initial_title_from_web')}', Gyro={article_pipeline_data.get('is_gyro_pick')}, TextLen={len(str(article_pipeline_data.get('raw_scraped_text')))}")


        article_pipeline_data = run_filter_enrich_agent(article_pipeline_data)
        logger.info(f"MAIN.PY POST_FILTER_ENRICH for ID {article_pipeline_data.get('id')}: Importance='{article_pipeline_data.get('importance_level')}', Summary='{str(article_pipeline_data.get('processed_summary'))[:50]}', Passed={article_pipeline_data.get('filter_passed')}")

        if not article_pipeline_data.get('filter_passed', False):
            logger.info(f"Skipping {current_article_id_str}: Failed filter/enrichment. Reason: {article_pipeline_data.get('filter_reason')}")
            if raw_article_input.get('is_gyro_pick') and raw_article_input.get('id'): 
                raw_gyro_file_to_remove = os.path.join(RAW_WEB_RESEARCH_OUTPUT_DIR, f"{raw_article_input.get('id')}.json")
                if os.path.exists(raw_gyro_file_to_remove):
                    try: os.remove(raw_gyro_file_to_remove); logger.debug(f"Removed failed Gyro raw file: {raw_gyro_file_to_remove}")
                    except: pass
            continue

        article_pipeline_data = run_deduplication_agent(article_pipeline_data, historical_embeddings)
        if article_pipeline_data.get('is_duplicate', False):
            logger.info(f"Skipping {current_article_id_str}: Duplicate of {article_pipeline_data.get('similar_article_id')}.")
            if raw_article_input.get('is_gyro_pick') and raw_article_input.get('id'): 
                raw_gyro_file_to_remove = os.path.join(RAW_WEB_RESEARCH_OUTPUT_DIR, f"{raw_article_input.get('id')}.json")
                if os.path.exists(raw_gyro_file_to_remove):
                    try: os.remove(raw_gyro_file_to_remove); logger.debug(f"Removed duplicate Gyro raw file: {raw_gyro_file_to_remove}")
                    except: pass
            continue
        
        article_pipeline_data = run_keyword_intelligence_agent(article_pipeline_data)
        
        article_pipeline_data = run_seo_writing_agent(article_pipeline_data)
        seo_res_check_main = article_pipeline_data.get('seo_agent_results', {})
        logger.info(f"MAIN.PY POST_SEO_WRITER for ID {article_pipeline_data.get('id')}: H1='{seo_res_check_main.get('generated_seo_h1')}', MD_Body_Len={len(str(seo_res_check_main.get('generated_article_body_md')))}")


        if not article_pipeline_data.get('seo_agent_results', {}).get('generated_article_body_md'):
            logger.error(f"Skipping {current_article_id_str}: SEO Writing Agent failed. Status: {article_pipeline_data.get('seo_agent_status')}")
            if raw_article_input.get('is_gyro_pick') and raw_article_input.get('id'): 
                raw_gyro_file_to_remove = os.path.join(RAW_WEB_RESEARCH_OUTPUT_DIR, f"{raw_article_input.get('id')}.json")
                if os.path.exists(raw_gyro_file_to_remove):
                    try: os.remove(raw_gyro_file_to_remove); logger.debug(f"Removed failed (SEO) Gyro raw file: {raw_gyro_file_to_remove}")
                    except: pass
            continue
        
        article_pipeline_data = run_vision_media_agent(article_pipeline_data)
        article_pipeline_data = run_image_integration_agent(article_pipeline_data)
        article_pipeline_data = run_knowledge_graph_agent(article_pipeline_data, site_content_graph_data) 
        
        final_render_vars_main = {
            'PAGE_TITLE': article_pipeline_data.get('seo_agent_results',{}).get('generated_title_tag', article_pipeline_data.get('final_title','Untitled Article')),
            'META_DESCRIPTION': article_pipeline_data.get('seo_agent_results',{}).get('generated_meta_description', 'Default description...'),
            'AUTHOR_NAME': article_pipeline_data.get('author', AUTHOR_NAME_DEFAULT),
            'META_KEYWORDS_LIST': article_pipeline_data.get('final_keywords', []),
            'CANONICAL_URL': urljoin(YOUR_SITE_BASE_URL, f"articles/{article_pipeline_data['slug']}.html".lstrip('/')),
            'SITE_NAME': YOUR_WEBSITE_NAME,
            'YOUR_WEBSITE_LOGO_URL': YOUR_WEBSITE_LOGO_URL,
            'IMAGE_URL': article_pipeline_data.get('selected_image_url', ''),
            'IMAGE_ALT_TEXT': article_pipeline_data.get('final_featured_image_alt_text', article_pipeline_data.get('final_title','Article Image')),
            'PUBLISH_ISO_FOR_META': article_pipeline_data.get('published_iso'),
            'JSON_LD_SCRIPT_BLOCK': article_pipeline_data.get('seo_agent_results',{}).get('generated_json_ld_full_script_tag','<script type="application/ld+json">{}</script>'),
            'ARTICLE_HEADLINE': article_pipeline_data.get('final_title','Untitled Article'),
            'ARTICLE_SEO_H1': article_pipeline_data.get('final_title','Untitled Article'),
            'PUBLISH_DATE': get_sort_key_for_all_articles(article_pipeline_data).strftime('%B %d, %Y') if article_pipeline_data.get('published_iso') else "Date Not Available",
            'ARTICLE_BODY_HTML': process_final_markdown_to_html_main(article_pipeline_data.get('seo_agent_results',{}).get('generated_article_body_md','')),
            'ARTICLE_TAGS_HTML': format_tags_html_main(article_pipeline_data.get('final_keywords',[])),
            'SOURCE_ARTICLE_URL': article_pipeline_data.get('original_source_url','#'),
            'ARTICLE_TITLE': article_pipeline_data.get('final_title','Untitled Article'),
            'id': current_article_id_str,
            'CURRENT_ARTICLE_ID': current_article_id_str,
            'CURRENT_ARTICLE_TOPIC': article_pipeline_data.get('primary_topic','News'),
            'CURRENT_ARTICLE_TAGS_JSON': json.dumps(article_pipeline_data.get('final_keywords',[])),
            'AUDIO_URL': article_pipeline_data.get('generated_audio_url') 
        }
        if not render_html_page_main('post_template.html', final_render_vars_main, OUTPUT_HTML_DIR, article_pipeline_data['slug']):
            logger.error(f"Failed to render final HTML for {current_article_id_str}. Skipping further processing for this item.")
            continue
        
        article_pipeline_data['post_template_hash'] = current_post_template_hash_main
        save_json_data(processed_json_path, article_pipeline_data, f"final processed article {current_article_id_str}")

        summary_for_master = {
            "id": current_article_id_str, "title": article_pipeline_data['final_title'],
            "link": f"articles/{article_pipeline_data['slug']}.html", "published_iso": article_pipeline_data['published_iso'],
            "summary_short": (article_pipeline_data.get('seo_agent_results') if isinstance(article_pipeline_data.get('seo_agent_results'), dict) else {}).get('generated_meta_description', article_pipeline_data.get('processed_summary','')),
            "image_url": article_pipeline_data.get('selected_image_url'), "topic": article_pipeline_data.get('primary_topic', 'News'),
            "is_breaking": article_pipeline_data.get('importance_level') == "Breaking",
            "is_trending_pick": article_pipeline_data.get('user_is_trending_pick_gyro', False),
            "tags": article_pipeline_data.get('final_keywords', []), "audio_url": None, "trend_score": 0 
        }
        update_master_article_list_json(summary_for_master)
        
        social_payload = {
            "id": current_article_id_str, "title": summary_for_master['title'],
            "article_url": urljoin(YOUR_SITE_BASE_URL, summary_for_master['link'].lstrip('/')),
            "image_url": summary_for_master['image_url'], "topic": summary_for_master['topic'],
            "tags": summary_for_master['tags'], "summary_short": summary_for_master['summary_short']
        }
        social_media_queue_this_run.append(social_payload)
        successfully_processed_articles_this_run.append(article_pipeline_data)
        
        if raw_article_input.get('is_gyro_pick') and raw_article_input.get('id'):
            raw_gyro_file_to_remove = os.path.join(RAW_WEB_RESEARCH_OUTPUT_DIR, f"{raw_article_input.get('id')}.json")
            if os.path.exists(raw_gyro_file_to_remove):
                try: os.remove(raw_gyro_file_to_remove); logger.info(f"Removed processed raw Gyro file: {raw_gyro_file_to_remove}")
                except OSError as e_rem: logger.warning(f"Could not remove raw Gyro file {raw_gyro_file_to_remove}: {e_rem}")
        
        processed_in_run_count += 1
        logger.info(f"--- Successfully processed Article ID: {current_article_id_str} through all stages ---")
            
    save_historical_embeddings(historical_embeddings)

    logger.info("--- Stage 9: Running Trending Digest Agent ---")
    all_site_articles_for_digest = load_json_data(ALL_ARTICLES_FILE, "all_articles_for_digest")
    # Ensure all_site_articles_for_digest is a list, even if file was empty or malformed
    if not isinstance(all_site_articles_for_digest, dict) or not isinstance(all_site_articles_for_digest.get('articles'), list):
        all_site_articles_for_digest = [] 
    else:
        all_site_articles_for_digest = all_site_articles_for_digest.get('articles',[])

    digest_pages_generated_data = run_trending_digest_agent(raw_articles_from_web, all_site_articles_for_digest)


    if digest_pages_generated_data:
        logger.info(f"Trending Digest Agent produced {len(digest_pages_generated_data)} digest pages. Rendering them...")
        for digest_data_item in digest_pages_generated_data:
            digest_template_vars = {
                'PAGE_TITLE': digest_data_item.get('page_title'),
                'META_DESCRIPTION': digest_data_item.get('meta_description'),
                'META_KEYWORDS_LIST': digest_data_item.get('theme_source_keywords', []),
                'CANONICAL_URL': urljoin(YOUR_SITE_BASE_URL, f"digests/{digest_data_item['slug']}.html".lstrip('/')),
                'SITE_NAME': YOUR_WEBSITE_NAME,
                'YOUR_WEBSITE_LOGO_URL': YOUR_WEBSITE_LOGO_URL,
                'FAVICON_URL': os.getenv('YOUR_FAVICON_URL', 'https://i.ibb.co/W7xMqdT/dacoola-image-logo.png'), # Keep default if not set
                'OG_IMAGE_URL': os.getenv('DEFAULT_OG_IMAGE_FOR_DIGESTS', YOUR_WEBSITE_LOGO_URL),
                'PUBLISH_ISO_FOR_META': datetime.now(timezone.utc).isoformat(),
                'JSON_LD_SCRIPT_TAG': digest_data_item.get('json_ld_script_tag', ''),
                'INTRODUCTION_HTML': process_final_markdown_to_html_main(digest_data_item.get('introduction_md','')),
                'SELECTED_ARTICLES': digest_data_item.get('selected_articles', [])
            }
            render_html_page_main('digest_page_template.html', digest_template_vars, DIGEST_OUTPUT_HTML_DIR, digest_data_item['slug'])
    else:
        logger.info("Trending Digest Agent produced no digest pages this run.")

    # --- Stage 10: Social Media Posting ---
    social_post_history = load_social_post_history()
    already_posted_social_ids_set = set(social_post_history.get('posted_articles', []))
    
    final_queue_for_social_posting = [
        p for p in social_media_queue_this_run 
        if p['id'] not in already_posted_social_ids_set
    ]
    for p in final_queue_for_social_posting: # Mark current run's items as "to be posted"
        already_posted_social_ids_set.add(p['id'])

    now_utc = datetime.now(timezone.utc)
    social_cutoff_time = now_utc - timedelta(hours=MAX_AGE_FOR_SOCIAL_POST_HOURS)
    
    for processed_file_path in glob.glob(os.path.join(PROCESSED_JSON_DIR, '*.json')):
        hist_article_id = os.path.basename(processed_file_path).replace('.json','')
        if hist_article_id not in already_posted_social_ids_set:
            hist_data = load_json_data(processed_file_path, "historical for social")
            if hist_data and hist_data.get('published_iso') and hist_data.get('slug'):
                try:
                    if get_sort_key_for_all_articles(hist_data) >= social_cutoff_time:
                        seo_res_hist = hist_data.get('seo_agent_results') if isinstance(hist_data.get('seo_agent_results'), dict) else {}
                        hist_payload = {
                            "id": hist_data['id'], 
                            "title": hist_data.get('final_title', 'Article'),
                            "article_url": urljoin(YOUR_SITE_BASE_URL, f"articles/{hist_data['slug']}.html".lstrip('/')),
                            "image_url": hist_data.get('selected_image_url'), 
                            "topic": hist_data.get('primary_topic'),
                            "tags": hist_data.get('final_keywords', []),
                            "summary_short": seo_res_hist.get('generated_meta_description','')
                        }
                        final_queue_for_social_posting.append(hist_payload)
                        already_posted_social_ids_set.add(hist_data['id']) 
                except Exception as e: logger.warning(f"Error queueing hist article {hist_article_id}: {e}")
    
    if final_queue_for_social_posting:
        logger.info(f"--- Stage 10: Attempting {len(final_queue_for_social_posting)} posts to Social Media ---")
        def get_true_publish_date_for_social_sort(payload_item):
            article_id_lookup = payload_item.get('id')
            if not article_id_lookup: return datetime(1970, 1, 1, tzinfo=timezone.utc)
            
            data_for_sort = next((art for art in successfully_processed_articles_this_run if art.get('id') == article_id_lookup), None)
            if not data_for_sort: 
                data_for_sort = load_json_data(os.path.join(PROCESSED_JSON_DIR, f"{article_id_lookup}.json"))
            return get_sort_key_for_all_articles(data_for_sort or {})
        
        final_queue_for_social_posting.sort(key=get_true_publish_date_for_social_sort, reverse=True)

        for item_to_post in final_queue_for_social_posting:
            platforms_to_attempt_final = ["bluesky", "reddit"] 
            if social_media_clients.get("twitter_client"):
                current_run_date_str_twitter, posts_today_twitter = _read_tweet_tracker()
                today_utc_str_twitter = datetime.now(timezone.utc).strftime('%Y-%m-%d')
                if current_run_date_str_twitter != today_utc_str_twitter: posts_today_twitter = 0
                
                if posts_today_twitter < DAILY_TWEET_LIMIT:
                    platforms_to_attempt_final.append("twitter")
                else:
                    logger.info(f"Daily Twitter limit reached. Twitter SKIPPED for social post ID: {item_to_post.get('id')}")

            # run_social_media_poster should handle marking as posted
            run_social_media_poster(item_to_post, social_media_clients, tuple(platforms_to_attempt_final))
            time.sleep(10) 
    else: 
        logger.info("No articles queued for social media posting this run.")


    # --- Stage 11: Generate Sitemap ---
    logger.info("--- Stage 11: Generating Sitemap ---")
    if not YOUR_SITE_BASE_URL or YOUR_SITE_BASE_URL == '/':
        logger.error("Sitemap generation SKIPPED: YOUR_SITE_BASE_URL not set or invalid.");
    else:
        try: run_sitemap_generator(); logger.info("Sitemap generation completed successfully.")
        except Exception as e: logger.exception(f"Sitemap generation failed: {e}")

    run_end_timestamp = time.time()
    logger.info(f"--- === Dacoola AI Content Engine - Orchestrator Run Finished ({run_end_timestamp - run_start_timestamp:.2f} seconds) === ---")