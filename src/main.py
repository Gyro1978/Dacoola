# src/main.py (Modular Pipeline v1.5.3 - Corrected NoneType for Gyro raw_scraped_text)

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
import html
import hashlib
import random
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, quote

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
        run_deduplication_agent, load_historical_embeddings, save_historical_embeddings
    )
    from src.agents.keyword_intelligence_agent import run_keyword_intelligence_agent
    from src.agents.title_agent import run_title_agent
    from src.agents.meta_description_agent import run_meta_description_agent
    from src.agents.article_outline_agent import run_article_outline_agent
    from src.agents.section_writer_agent import run_section_writer_agent
    from src.agents.content_assembler_agent import assemble_article_content
    from src.agents.json_ld_agent import run_json_ld_agent
    from src.agents.final_review_agent import run_final_review_agent
    from src.agents.vision_media_agent import run_vision_media_agent
    from src.agents.image_integration_agent import run_image_integration_agent
    from src.agents.knowledge_graph_agent import run_knowledge_graph_agent, load_site_content_graph
    from src.agents.trending_digest_agent import run_trending_digest_agent
    from src.agents.post_processor_agent import (
        render_and_save_article_page_pp,
        render_and_save_digest_page_pp,
        update_all_articles_json_pp
    )
    from src.social.social_media_poster import (
        initialize_social_clients, run_social_media_poster,
        load_post_history as load_social_post_history,
        mark_article_as_posted_in_history
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
MAX_ARTICLES_TO_PROCESS_PER_RUN = int(os.getenv('MAX_ARTICLES_TO_PROCESS_PER_RUN', '10'))

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
logger = logging.getLogger('main_orchestrator_v1.5.3') # Version bump for fix

if not YOUR_SITE_BASE_URL or YOUR_SITE_BASE_URL == '/':
    logger.error("CRITICAL: YOUR_SITE_BASE_URL is not set or is invalid ('/'). Canonical URLs and sitemap will be incorrect.")
else:
    logger.info(f"Using site base URL: {YOUR_SITE_BASE_URL}")

# --- Configuration ---
DATA_DIR_MAIN = os.path.join(PROJECT_ROOT_FOR_PATH, 'data')
RAW_WEB_RESEARCH_OUTPUT_DIR_MAIN = os.path.join(DATA_DIR_MAIN, 'raw_web_research')
PROCESSED_JSON_DIR_MAIN = os.path.join(DATA_DIR_MAIN, 'processed_json')
PUBLIC_DIR_MAIN = os.path.join(PROJECT_ROOT_FOR_PATH, 'public')
OUTPUT_HTML_DIR_MAIN = os.path.join(PUBLIC_DIR_MAIN, 'articles')
DIGEST_OUTPUT_HTML_DIR_MAIN = os.path.join(PUBLIC_DIR_MAIN, 'digests')
TEMPLATE_DIR_MAIN = os.path.join(PROJECT_ROOT_FOR_PATH, 'templates')
ALL_ARTICLES_FILE_MAIN_PATH = os.path.join(PUBLIC_DIR_MAIN, 'all_articles.json')
TWITTER_DAILY_LIMIT_FILE_MAIN = os.path.join(DATA_DIR_MAIN, 'twitter_daily_limit.json')
POST_TEMPLATE_FILE_MAIN = os.path.join(TEMPLATE_DIR_MAIN, 'post_template.html')
DIGEST_TEMPLATE_FILE_MAIN = os.path.join(TEMPLATE_DIR_MAIN, 'digest_page_template.html')

# --- Jinja2 Setup ---
try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    import markdown
    def escapejs_filter(value):
        if value is None: return ''
        value = str(value).replace('\\', '\\\\').replace("'", "\\'").replace('"', '\\"').replace('/', '\\/')
        value = value.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
        value = value.replace('<', '\\u003c').replace('>', '\\u003e').replace('\b', '\\b').replace('\f', '\\f')
        return value
    if not os.path.isdir(TEMPLATE_DIR_MAIN):
        logger.critical(f"Jinja2 template directory not found: {TEMPLATE_DIR_MAIN}. Exiting."); sys.exit(1)
    jinja_env_main_instance = Environment(loader=FileSystemLoader(TEMPLATE_DIR_MAIN), autoescape=select_autoescape(['html', 'xml']))
    jinja_env_main_instance.filters['escapejs'] = escapejs_filter
    logger.info(f"Jinja2 environment loaded from {TEMPLATE_DIR_MAIN}")
except ImportError: logger.critical("Jinja2 or Markdown library not found. Exiting."); sys.exit(1)
except Exception as e: logger.exception(f"CRITICAL: Failed Jinja2 init. Exiting: {e}"); sys.exit(1)

# --- Helper Functions (Local to main.py) ---
def ensure_directories_main():
    dirs_to_create = [
        DATA_DIR_MAIN, RAW_WEB_RESEARCH_OUTPUT_DIR_MAIN, PROCESSED_JSON_DIR_MAIN,
        PUBLIC_DIR_MAIN, OUTPUT_HTML_DIR_MAIN, DIGEST_OUTPUT_HTML_DIR_MAIN, TEMPLATE_DIR_MAIN
    ]
    try:
        for d in dirs_to_create: os.makedirs(d, exist_ok=True)
        logger.info("Ensured core directories exist (main).")
    except OSError as e: logger.exception(f"CRITICAL dir create fail (main): {e}"); sys.exit(1)

def get_file_hash_main(filepath):
    hasher = hashlib.sha256();
    if not os.path.exists(filepath): logger.error(f"NOT FOUND for hash (main): {filepath}"); return None
    try:
        with open(filepath, 'rb') as f:
            buf = f.read(65536)
            while len(buf) > 0: hasher.update(buf); buf = f.read(65536)
        hex_digest = hasher.hexdigest(); return hex_digest
    except Exception as e: logger.error(f"Error hashing {filepath} (main): {e}"); return None

current_post_template_hash_main_var = None
current_digest_template_hash_main_var = None

def load_json_data_main(filepath, data_description="data"):
    try:
        with open(filepath, 'r', encoding='utf-8') as f: return json.load(f)
    except FileNotFoundError: logger.debug(f"{data_description} file not found (main): {filepath}"); return None
    except json.JSONDecodeError: logger.error(f"JSON decode error in {data_description} file (main): {filepath}."); return None
    except Exception as e: logger.error(f"Error loading {data_description} from {filepath} (main): {e}"); return None

def save_json_data_main(filepath, data_to_save, data_description="data"):
    try:
         os.makedirs(os.path.dirname(filepath), exist_ok=True)
         with open(filepath, 'w', encoding='utf-8') as f: json.dump(data_to_save, f, indent=4, ensure_ascii=False)
         logger.info(f"Saved {data_description} (main) to: {os.path.basename(filepath)}"); return True
    except Exception as e: logger.error(f"Failed to save {data_description} (main) to {os.path.basename(filepath)}: {e}"); return False

def get_article_universal_id_main(article_url_or_identifier_string):
    if not article_url_or_identifier_string:
        timestamp_id = str(time.time()) + str(random.random())
        return hashlib.sha256(timestamp_id.encode('utf-8')).hexdigest()
    return hashlib.sha256(str(article_url_or_identifier_string).encode('utf-8')).hexdigest()

def read_tweet_tracker_main():
    today_utc_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    default_data = {'date': today_utc_str, 'count': 0}
    try:
        os.makedirs(os.path.dirname(TWITTER_DAILY_LIMIT_FILE_MAIN), exist_ok=True)
        if os.path.exists(TWITTER_DAILY_LIMIT_FILE_MAIN):
            with open(TWITTER_DAILY_LIMIT_FILE_MAIN, 'r', encoding='utf-8') as f: data = json.load(f)
            if data.get('date') == today_utc_str: return data['date'], data.get('count', 0)
        with open(TWITTER_DAILY_LIMIT_FILE_MAIN, 'w', encoding='utf-8') as f: json.dump(default_data, f, indent=2)
        logger.info(f"Initialized/reset Twitter tracker for {today_utc_str} (main).")
        return today_utc_str, 0
    except Exception as e:
        logger.error(f"Error R/W Twitter tracker (main): {e}. Resetting count for {today_utc_str}.")
        try:
            with open(TWITTER_DAILY_LIMIT_FILE_MAIN, 'w', encoding='utf-8') as f: json.dump(default_data, f, indent=2)
        except Exception as e_write: logger.error(f"Could not write default twitter tracker (main): {e_write}")
        return today_utc_str, 0

def increment_tweet_count_main():
    date_str, count = read_tweet_tracker_main()
    today_utc_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if date_str == today_utc_str:
        new_count = count + 1
    else:
        new_count = 1

    try:
        with open(TWITTER_DAILY_LIMIT_FILE_MAIN, 'w', encoding='utf-8') as f:
            json.dump({'date': today_utc_str, 'count': new_count}, f, indent=2)
        logger.debug(f"Updated Twitter count to {new_count} for {today_utc_str}.")
        return new_count
    except Exception as e:
        logger.error(f"Error updating Twitter tracker count: {e}")
        return count

def slugify_filename_main(text_to_slugify):
    if not text_to_slugify: return "untitled-slug"
    s = str(text_to_slugify).strip().lower()
    s = re.sub(r'[^\w\s-]', '', s)
    s = re.sub(r'[-\s]+', '-', s)
    return s[:75]

def get_sort_key_for_master_list_main(item):
    fallback = datetime(1970, 1, 1, tzinfo=timezone.utc)
    if not item or not isinstance(item, dict): 
        logger.warning(f"Invalid item provided to get_sort_key_for_master_list_main: {item}")
        return fallback
    iso_str = item.get('published_iso')
    if not iso_str: return fallback
    try:
        if iso_str.endswith('Z'): iso_str = iso_str[:-1] + '+00:00'
        dt = datetime.fromisoformat(iso_str)
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except ValueError:
        logger.warning(f"Date parse error '{iso_str}' for master list sort. Fallback.")
        return fallback
# --- End Helper Functions ---

# --- Main Orchestration Logic ---
if __name__ == "__main__":
    run_start_timestamp = time.time()
    logger.info(f"--- === Dacoola AI Content Engine (Modular Pipeline v1.5.3) - Orchestrator Starting Run ({datetime.now(timezone.utc).isoformat()}) === ---")
    ensure_directories_main()

    logger.info(f"Hashing templates: {POST_TEMPLATE_FILE_MAIN}, {DIGEST_TEMPLATE_FILE_MAIN}")
    current_post_template_hash_main_var = get_file_hash_main(POST_TEMPLATE_FILE_MAIN)
    current_digest_template_hash_main_var = get_file_hash_main(DIGEST_TEMPLATE_FILE_MAIN)
    if not current_post_template_hash_main_var:
        logger.critical(f"CRITICAL FAILURE: Could not hash post_template.html. Exiting."); sys.exit(1)
    logger.info(f"Current post_template.html hash: {current_post_template_hash_main_var}")
    if current_digest_template_hash_main_var:
        logger.info(f"Current digest_template.html hash: {current_digest_template_hash_main_var}")
    else:
        logger.warning("Could not hash digest_template.html. Digest regeneration based on template changes will not occur.")

    social_media_clients_main = initialize_social_clients()

    logger.info("--- Stage 0: Checking/Regenerating HTML for existing processed articles (if template changed) ---")
    all_existing_processed_files = glob.glob(os.path.join(PROCESSED_JSON_DIR_MAIN, '*.json'))
    html_regen_count_articles = 0
    if all_existing_processed_files:
        for proc_json_file in all_existing_processed_files:
            article_data_for_regen = load_json_data_main(proc_json_file, f"regen check: {os.path.basename(proc_json_file)}")
            if not article_data_for_regen or not article_data_for_regen.get('id') or not article_data_for_regen.get('slug'):
                 logger.warning(f"Skipping JSON missing id/slug for HTML regen: {os.path.basename(proc_json_file)}.")
                 continue

            stored_template_hash = article_data_for_regen.get('post_template_hash')
            html_file_path_check = os.path.join(OUTPUT_HTML_DIR_MAIN, f"{article_data_for_regen['slug']}.html")

            if not os.path.exists(html_file_path_check) or stored_template_hash != current_post_template_hash_main_var:
                logger.info(f"Regenerating HTML for {article_data_for_regen['id']} (Reason: {'missing HTML' if not os.path.exists(html_file_path_check) else 'template changed'}).")
                render_success = render_and_save_article_page_pp(
                    article_pipeline_data=article_data_for_regen,
                    jinja_env=jinja_env_main_instance,
                    post_template_hash_current=current_post_template_hash_main_var
                )
                if render_success:
                    save_json_data_main(proc_json_file, article_data_for_regen, f"processed article {article_data_for_regen['id']} (hash updated post-regen)")
                    html_regen_count_articles +=1
    logger.info(f"Article HTML Regeneration check complete. Regenerated/Verified {html_regen_count_articles} files based on template hash.")

    all_existing_digest_files_json_like_slugs = [
        os.path.basename(f).replace('.html', '') for f in glob.glob(os.path.join(DIGEST_OUTPUT_HTML_DIR_MAIN, '*.html'))
    ]
    html_regen_count_digests = 0
    if all_existing_digest_files_json_like_slugs and current_digest_template_hash_main_var:
        logger.info("Digest HTML Regeneration check skipped for this version (would require re-running digest agent or stored digest data).")
    elif not current_digest_template_hash_main_var:
        logger.warning("Digest HTML Regeneration check skipped (no digest template hash).")


    raw_articles_from_web_main = []
    run_web_research_config = True
    if run_web_research_config:
        logger.info("--- Stage 1a: Running Web Research Agent ---")
        sites_to_monitor_config_main = [
            {
                "name": "TechCrunch AI", "url": "https://techcrunch.com/category/artificial-intelligence/",
                "rss_feed_url": "https://techcrunch.com/category/artificial-intelligence/feed/", "type": "html_index",
                "article_link_selectors": ["h2.post-block__title > a", "a.post-block__title__link", "a.river-block__title__link"],
                "max_article_age_hours": 48, "default_topic": "AI News", "force_rss": False
            },
            {
                "name": "OpenAI News", "url": "https://openai.com/news/",
                "rss_feed_url": "https://openai.com/blog/rss/", "type": "html_index",
                "article_link_selectors": ["a[href*='/blog/']", "div[class*='card'] > a"],
                "max_article_age_hours": 168, "default_topic": "OpenAI Updates", "force_rss": True
            },
             {
                "name": "ArtificialIntelligence-News", "url": "https://www.artificialintelligence-news.com/artificial-intelligence-news/",
                "rss_feed_url": "https://www.artificialintelligence-news.com/feed/", "type": "rss",
                "max_article_age_hours": 48, "default_topic": "AI Industry News"
            },
        ]
        web_agent_articles_results = run_web_research_agent(sites_to_monitor_config_main)
        if web_agent_articles_results: raw_articles_from_web_main.extend(web_agent_articles_results)

    gyro_pick_files_main = glob.glob(os.path.join(RAW_WEB_RESEARCH_OUTPUT_DIR_MAIN, "gyro-*.json"))
    if gyro_pick_files_main:
        logger.info(f"--- Stage 1b: Processing {len(gyro_pick_files_main)} raw Gyro Pick files ---")
        for gyro_file_path in gyro_pick_files_main:
            gyro_data = load_json_data_main(gyro_file_path, "raw gyro pick")
            if gyro_data: raw_articles_from_web_main.append(gyro_data)

    successfully_processed_articles_this_run_main = []
    social_media_queue_this_run_main = []
    historical_embeddings_main = load_historical_embeddings()
    site_content_graph_data_main = load_site_content_graph()

    logger.info(f"--- Starting main processing pipeline for {len(raw_articles_from_web_main)} total raw items ---")
    processed_in_run_count = 0

    for raw_article_input in raw_articles_from_web_main:
        if processed_in_run_count >= MAX_ARTICLES_TO_PROCESS_PER_RUN:
            logger.info(f"Reached MAX_ARTICLES_TO_PROCESS_PER_RUN ({MAX_ARTICLES_TO_PROCESS_PER_RUN}). Stopping new article processing for this run."); break

        article_id_source_key = raw_article_input.get('id', raw_article_input.get('url'))
        if not article_id_source_key:
            logger.warning(f"Raw article input missing 'id' (Gyro) or 'url' (Web). Skipping."); continue

        current_article_id_str = get_article_universal_id_main(article_id_source_key)
        logger.info(f"--- Processing Article ID: {current_article_id_str} (Source Key: {str(article_id_source_key)[:70]}) ---")

        processed_json_path = os.path.join(PROCESSED_JSON_DIR_MAIN, f"{current_article_id_str}.json")
        if os.path.exists(processed_json_path):
            logger.info(f"Article {current_article_id_str} already processed (JSON exists). Skipping main pipeline for this item.");
            if raw_article_input.get('is_gyro_pick') and raw_article_input.get('id'):
                raw_gyro_file_to_remove = os.path.join(RAW_WEB_RESEARCH_OUTPUT_DIR_MAIN, f"{raw_article_input.get('id')}.json")
                if os.path.exists(raw_gyro_file_to_remove):
                    try: os.remove(raw_gyro_file_to_remove); logger.debug(f"Cleaned up raw Gyro (already processed): {raw_gyro_file_to_remove}")
                    except Exception as e_rem: logger.warning(f"Could not remove raw Gyro (already processed) {raw_gyro_file_to_remove}: {e_rem}")
            continue

        # --- Corrected Initialization for 'raw_scraped_text' ---
        raw_text_from_input = raw_article_input.get('scraped_text', raw_article_input.get('raw_scraped_text'))
        article_pipeline_data = {
            'id': current_article_id_str,
            'original_source_url': raw_article_input.get('url', raw_article_input.get('original_source_url')),
            'initial_title_from_web': raw_article_input.get('title', raw_article_input.get('initial_title_from_web')),
            'raw_scraped_text': raw_text_from_input if raw_text_from_input is not None else '', # Default to empty string if None
            'research_topic': raw_article_input.get('research_topic'),
            'published_iso': raw_article_input.get('parsed_publish_date_iso') or raw_article_input.get('retrieved_at') or datetime.now(timezone.utc).isoformat(),
            'pipeline_status': 'started',
            'is_gyro_pick': raw_article_input.get('is_gyro_pick', False),
            'gyro_pick_mode': raw_article_input.get('gyro_pick_mode'),
            'user_importance_override_gyro': raw_article_input.get('user_importance_override_gyro'),
            'user_is_trending_pick_gyro': raw_article_input.get('user_is_trending_pick_gyro'),
            'selected_image_url': raw_article_input.get('selected_image_url'),
            'author': raw_article_input.get('author', AUTHOR_NAME_DEFAULT),
            'final_page_h1': None, 'generated_title_tag': None, 'generated_meta_description': None,
            'final_keywords': [], 'article_outline': {}, 'assembled_article_body_md': None,
            'generated_json_ld_object': {}, 'final_review_findings': {}, 'final_review_status': "PENDING",
            'media_candidates_for_body': [], 'final_featured_image_alt_text': None,
            'post_template_hash': None,
            'seo_agent_results': {}
        }
        # --- End Corrected Initialization ---


        article_pipeline_data = run_filter_enrich_agent(article_pipeline_data)
        if not article_pipeline_data.get('filter_passed', False):
            logger.info(f"Skipping {current_article_id_str} (Filter/Enrich Fail): {article_pipeline_data.get('filter_reason')}")
            if raw_article_input.get('is_gyro_pick') and raw_article_input.get('id'): os.remove(os.path.join(RAW_WEB_RESEARCH_OUTPUT_DIR_MAIN, f"{raw_article_input.get('id')}.json"))
            continue

        article_pipeline_data = run_deduplication_agent(article_pipeline_data, historical_embeddings_main)
        if article_pipeline_data.get('is_duplicate', False):
            logger.info(f"Skipping {current_article_id_str} (Duplicate of {article_pipeline_data.get('highest_similar_article_id')}).")
            if raw_article_input.get('is_gyro_pick') and raw_article_input.get('id'): os.remove(os.path.join(RAW_WEB_RESEARCH_OUTPUT_DIR_MAIN, f"{raw_article_input.get('id')}.json"))
            continue

        article_pipeline_data = run_keyword_intelligence_agent(article_pipeline_data)
        article_pipeline_data = run_title_agent(article_pipeline_data)
        article_pipeline_data = run_meta_description_agent(article_pipeline_data)
        article_pipeline_data = run_article_outline_agent(article_pipeline_data)

        if article_pipeline_data.get('outline_agent_status', '').startswith("FAILED"):
            logger.error(f"Skipping {current_article_id_str}: Outline generation failed. Cannot write sections.")
            if raw_article_input.get('is_gyro_pick') and raw_article_input.get('id'): os.remove(os.path.join(RAW_WEB_RESEARCH_OUTPUT_DIR_MAIN, f"{raw_article_input.get('id')}.json"))
            continue

        outline_sections = article_pipeline_data.get('article_outline', {}).get('sections', [])
        if not outline_sections:
             logger.error(f"Skipping {current_article_id_str}: Outline has no sections.")
             if raw_article_input.get('is_gyro_pick') and raw_article_input.get('id'): os.remove(os.path.join(RAW_WEB_RESEARCH_OUTPUT_DIR_MAIN, f"{raw_article_input.get('id')}.json"))
             continue

        for section_idx, section_detail in enumerate(outline_sections):
            article_pipeline_data = run_section_writer_agent(article_pipeline_data, section_detail, section_idx)

        article_pipeline_data = assemble_article_content(article_pipeline_data)
        article_pipeline_data.setdefault('seo_agent_results', {})['generated_article_body_md'] = article_pipeline_data.get('assembled_article_body_md')

        if not article_pipeline_data.get('assembled_article_body_md'):
            logger.error(f"Skipping {current_article_id_str}: Content assembly resulted in empty body.")
            if raw_article_input.get('is_gyro_pick') and raw_article_input.get('id'): os.remove(os.path.join(RAW_WEB_RESEARCH_OUTPUT_DIR_MAIN, f"{raw_article_input.get('id')}.json"))
            continue

        article_pipeline_data = run_vision_media_agent(article_pipeline_data)
        article_pipeline_data = run_image_integration_agent(article_pipeline_data)
        article_pipeline_data['assembled_article_body_md'] = article_pipeline_data.get('seo_agent_results',{}).get('generated_article_body_md', article_pipeline_data.get('assembled_article_body_md'))

        article_pipeline_data = run_knowledge_graph_agent(article_pipeline_data, site_content_graph_data_main)
        article_pipeline_data['assembled_article_body_md'] = article_pipeline_data.get('seo_agent_results',{}).get('generated_article_body_md', article_pipeline_data.get('assembled_article_body_md'))

        final_title_for_slug = article_pipeline_data.get('final_page_h1',
                                article_pipeline_data.get('generated_seo_h1',
                                article_pipeline_data.get('initial_title_from_web', 'untitled-' + current_article_id_str[:8])))
        article_pipeline_data['slug'] = slugify_filename_main(final_title_for_slug)
        logger.info(f"Slug for {current_article_id_str} set to: {article_pipeline_data['slug']}")

        article_pipeline_data = run_json_ld_agent(article_pipeline_data)
        article_pipeline_data = run_final_review_agent(article_pipeline_data)

        if article_pipeline_data.get('final_review_status') == "FAILED_REVIEW":
            logger.error(f"Skipping HTML gen for {current_article_id_str} (Failed Review): {article_pipeline_data.get('final_review_findings', {}).get('errors')}")
            save_json_data_main(processed_json_path, article_pipeline_data, f"final processed (failed review) article {current_article_id_str}")
            if raw_article_input.get('is_gyro_pick') and raw_article_input.get('id'): os.remove(os.path.join(RAW_WEB_RESEARCH_OUTPUT_DIR_MAIN, f"{raw_article_input.get('id')}.json"))
            continue

        if not render_and_save_article_page_pp(article_pipeline_data, jinja_env_main_instance, current_post_template_hash_main_var):
            logger.error(f"Failed to render HTML for {current_article_id_str}. Skipping this item."); continue

        save_json_data_main(processed_json_path, article_pipeline_data, f"final processed article {current_article_id_str}")

        summary_for_master_list = {
            "id": current_article_id_str,
            "title": article_pipeline_data.get('final_page_h1', 'Untitled Article'),
            "link": f"articles/{article_pipeline_data['slug']}.html",
            "published_iso": article_pipeline_data.get('published_iso'),
            "summary_short": article_pipeline_data.get('generated_meta_description', article_pipeline_data.get('processed_summary','')),
            "image_url": article_pipeline_data.get('selected_image_url'),
            "topic": article_pipeline_data.get('primary_topic', 'News'),
            "is_breaking": article_pipeline_data.get('importance_level') == "Breaking",
            "is_trending_pick": article_pipeline_data.get('user_is_trending_pick_gyro', False),
            "tags": article_pipeline_data.get('final_keywords', []),
            "audio_url": article_pipeline_data.get('generated_audio_url', None),
            "trend_score": 0
        }

        current_all_articles_data = load_json_data_main(ALL_ARTICLES_FILE_MAIN_PATH, "all_articles_for_update_main")
        articles_list_to_update_main_pp = []
        if current_all_articles_data and isinstance(current_all_articles_data.get('articles'), list):
            articles_list_to_update_main_pp = [art for art in current_all_articles_data['articles'] if art.get('id') != current_article_id_str]
        articles_list_to_update_main_pp.append(summary_for_master_list)
        update_all_articles_json_pp(articles_list_to_update_main_pp)

        social_payload = {
            "id": current_article_id_str, "title": summary_for_master_list['title'],
            "article_url": urljoin(YOUR_SITE_BASE_URL, summary_for_master_list['link'].lstrip('/')),
            "image_url": summary_for_master_list['image_url'], "topic": summary_for_master_list['topic'],
            "tags": summary_for_master_list['tags'], "summary_short": summary_for_master_list['summary_short']
        }
        social_media_queue_this_run_main.append(social_payload)
        successfully_processed_articles_this_run_main.append(article_pipeline_data)

        if raw_article_input.get('is_gyro_pick') and raw_article_input.get('id'):
            raw_gyro_file_to_remove = os.path.join(RAW_WEB_RESEARCH_OUTPUT_DIR_MAIN, f"{raw_article_input.get('id')}.json")
            if os.path.exists(raw_gyro_file_to_remove):
                try: os.remove(raw_gyro_file_to_remove); logger.info(f"Cleaned up raw Gyro file: {raw_gyro_file_to_remove}")
                except OSError as e_rem: logger.warning(f"Could not remove raw Gyro: {raw_gyro_file_to_remove}: {e_rem}")

        processed_in_run_count += 1
        logger.info(f"--- Successfully processed Article ID: {current_article_id_str} through all modular stages ---")
        if processed_in_run_count < len(raw_articles_from_web_main):
            time.sleep(random.uniform(5, 10))

    save_historical_embeddings(historical_embeddings_main)

    logger.info("--- Stage 9: Running Trending Digest Agent ---")
    all_site_articles_for_digest_data = load_json_data_main(ALL_ARTICLES_FILE_MAIN_PATH, "all_articles_for_digest_input")
    all_site_articles_list_for_digest_main = []
    if isinstance(all_site_articles_for_digest_data, dict) and isinstance(all_site_articles_for_digest_data.get('articles'), list):
        all_site_articles_list_for_digest_main = all_site_articles_for_digest_data.get('articles',[])

    digest_pages_generated_data_main = run_trending_digest_agent(raw_articles_from_web_main, all_site_articles_list_for_digest_main)

    if digest_pages_generated_data_main:
        logger.info(f"Digest Agent produced {len(digest_pages_generated_data_main)} digest pages. Rendering...")
        for digest_item in digest_pages_generated_data_main:
            render_and_save_digest_page_pp(digest_item, jinja_env_main_instance)
    else:
        logger.info("Trending Digest Agent produced no digest pages this run.")

    social_post_history_main = load_social_post_history()
    already_posted_ids_main = set(social_post_history_main.get('posted_articles', []))

    final_social_queue_main = [p for p in social_media_queue_this_run_main if p['id'] not in already_posted_ids_main]
    for p in final_social_queue_main: already_posted_ids_main.add(p['id'])

    now_utc_main = datetime.now(timezone.utc)
    social_cutoff_dt_main = now_utc_main - timedelta(hours=MAX_AGE_FOR_SOCIAL_POST_HOURS)

    for hist_file_path in glob.glob(os.path.join(PROCESSED_JSON_DIR_MAIN, '*.json')):
        hist_id = os.path.basename(hist_file_path).replace('.json','')
        if hist_id not in already_posted_ids_main:
            hist_data_social = load_json_data_main(hist_file_path, "historical for social queue")
            if hist_data_social and hist_data_social.get('published_iso') and hist_data_social.get('slug'):
                try:
                    article_publish_date = get_sort_key_for_master_list_main(hist_data_social)
                    if article_publish_date >= social_cutoff_dt_main:
                        hist_payload_social = {
                            "id": hist_data_social['id'],
                            "title": hist_data_social.get('final_page_h1', hist_data_social.get('final_title', 'Article')),
                            "article_url": urljoin(YOUR_SITE_BASE_URL, f"articles/{hist_data_social['slug']}.html".lstrip('/')),
                            "image_url": hist_data_social.get('selected_image_url'),
                            "topic": hist_data_social.get('primary_topic'),
                            "tags": hist_data_social.get('final_keywords', []),
                            "summary_short": hist_data_social.get('generated_meta_description','')
                        }
                        final_social_queue_main.append(hist_payload_social)
                        already_posted_ids_main.add(hist_data_social['id'])
                except Exception as e: logger.warning(f"Error queueing historical article {hist_id} for social: {e}")

    if final_social_queue_main:
        logger.info(f"--- Stage 10: Attempting {len(final_social_queue_main)} posts to Social Media ---")
        final_social_queue_main.sort(key=lambda x: get_sort_key_for_master_list_main(load_json_data_main(os.path.join(PROCESSED_JSON_DIR_MAIN, f"{x['id']}.json"), "social sort lookup") or {}), reverse=True)


        for item_to_social_post in final_social_queue_main:
            platforms = ["bluesky", "reddit"]
            if social_media_clients_main.get("twitter_client"):
                date_str_twitter, count_twitter = read_tweet_tracker_main()
                if date_str_twitter != datetime.now(timezone.utc).strftime('%Y-%m-%d'):
                    count_twitter = 0
                if count_twitter < DAILY_TWEET_LIMIT:
                    platforms.append("twitter")
                    increment_tweet_count_main()
                else:
                    logger.info(f"Twitter daily limit ({DAILY_TWEET_LIMIT}) hit. Skipping Twitter for {item_to_social_post.get('id')}")

            run_social_media_poster(item_to_social_post, social_media_clients_main, tuple(platforms))
            time.sleep(random.uniform(10,15))
    else:
        logger.info("No articles identified for social media posting this run.")

    logger.info("--- Stage 11: Generating Sitemap ---")
    if not YOUR_SITE_BASE_URL or YOUR_SITE_BASE_URL == '/':
        logger.error("Sitemap generation SKIPPED: YOUR_SITE_BASE_URL not set or invalid.");
    else:
        try: run_sitemap_generator(); logger.info("Sitemap generation completed successfully.")
        except Exception as e: logger.exception(f"Sitemap generation failed: {e}")

    run_end_timestamp = time.time()
    logger.info(f"--- === Dacoola AI Content Engine (Modular Pipeline v1.5.3) - Orchestrator Run Finished ({run_end_timestamp - run_start_timestamp:.2f} seconds) === ---")