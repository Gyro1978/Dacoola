# gyro-picks.py
import sys
import os
import json
import hashlib
import logging
import re
import time
from datetime import datetime, timezone, timedelta # Added timedelta
from urllib.parse import urlparse, urljoin
import markdown # For rendering final HTML content

# --- Path Setup - Ensure this is correct for your project structure ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

# --- Standard Imports ---
from dotenv import load_dotenv

# --- Import Agent and Scraper Functions ---
try:
    from src.scrapers.news_scraper import get_full_article_content
    from src.scrapers.image_scraper import find_best_image, scrape_source_for_image
    from src.agents.filter_news_agent import run_filter_agent
    from src.agents.keyword_research_agent import run_keyword_research_agent
    from src.agents.seo_article_generator_agent import run_seo_article_agent
    from src.social.social_media_poster import initialize_social_clients, run_social_media_poster
    # Import sitemap generator if you want to run it at the end
    from generate_sitemap import generate_sitemap as run_sitemap_generator
except ImportError as e:
    print(f"FATAL IMPORT ERROR: {e}. Ensure 'src' directory is in PYTHONPATH or script is run from project root.")
    sys.exit(1)

# --- Load Environment Variables ---
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)

# --- Configuration (adapted from main.py) ---
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
PROCESSED_JSON_DIR = os.path.join(DATA_DIR, 'processed_json')
PUBLIC_DIR = os.path.join(PROJECT_ROOT, 'public')
OUTPUT_HTML_DIR = os.path.join(PUBLIC_DIR, 'articles')
TEMPLATE_DIR = os.path.join(PROJECT_ROOT, 'templates')
ALL_ARTICLES_FILE = os.path.join(PUBLIC_DIR, 'all_articles.json')
TWITTER_DAILY_LIMIT_FILE = os.path.join(DATA_DIR, 'twitter_daily_limit.json') # Added for shared limit

AUTHOR_NAME_DEFAULT = os.getenv('AUTHOR_NAME', 'Gyro Pick Team')
YOUR_WEBSITE_NAME = os.getenv('YOUR_WEBSITE_NAME', 'Dacoola')
YOUR_WEBSITE_LOGO_URL = os.getenv('YOUR_WEBSITE_LOGO_URL', '')
raw_base_url = os.getenv('YOUR_SITE_BASE_URL', '')
YOUR_SITE_BASE_URL = (raw_base_url.rstrip('/') + '/') if raw_base_url else ''
DAILY_TWEET_LIMIT = int(os.getenv('DAILY_TWEET_LIMIT', '3')) # Added for shared limit

if not YOUR_SITE_BASE_URL:
    print("ERROR: YOUR_SITE_BASE_URL is not set in .env. HTML links will be relative.")

# --- Jinja2 Setup ---
try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    def escapejs_filter(value):
        if value is None: return ''
        value = str(value)
        value = value.replace('\\', '\\\\').replace('"', '\\"').replace('/', '\\/')
        value = value.replace('<', '\\u003c').replace('>', '\\u003e')
        value = value.replace('\b', '\\b').replace('\f', '\\f').replace('\n', '\\n')
        value = value.replace('\r', '\\r').replace('\t', '\\t')
        return value
    
    if not os.path.isdir(TEMPLATE_DIR):
        print(f"ERROR: Jinja2 template directory not found: {TEMPLATE_DIR}")
        sys.exit(1)

    jinja_env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(['html', 'xml'])
    )
    jinja_env.filters['escapejs'] = escapejs_filter
except ImportError:
    print("ERROR: Jinja2 library not found. Please install it: pip install Jinja2")
    sys.exit(1)
except Exception as e:
    print(f"ERROR: Failed to initialize Jinja2 environment: {e}")
    sys.exit(1)

# --- Logging Setup ---
log_file_path = os.path.join(PROJECT_ROOT, 'gyro-picks.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file_path, encoding='utf-8')
    ],
    force=True
)
logger = logging.getLogger('GyroPicks')

# --- Twitter Daily Limit Helper Functions (copied from main.py) ---
def _read_tweet_tracker():
    """Reads the Twitter daily limit tracker file."""
    today_date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    try:
        if os.path.exists(TWITTER_DAILY_LIMIT_FILE):
            with open(TWITTER_DAILY_LIMIT_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if data.get('date') == today_date_str:
                return data['date'], data.get('count', 0)
        return today_date_str, 0 # New day or file not found
    except Exception as e:
        logger.error(f"Error reading Twitter tracker {TWITTER_DAILY_LIMIT_FILE}: {e}. Resetting count.")
        return today_date_str, 0

def _write_tweet_tracker(date_str, count):
    """Writes to the Twitter daily limit tracker file."""
    try:
        os.makedirs(os.path.dirname(TWITTER_DAILY_LIMIT_FILE), exist_ok=True)
        with open(TWITTER_DAILY_LIMIT_FILE, 'w', encoding='utf-8') as f:
            json.dump({'date': date_str, 'count': count}, f, indent=2)
        logger.info(f"Twitter tracker updated: Date {date_str}, Count {count}")
    except Exception as e:
        logger.error(f"Error writing Twitter tracker {TWITTER_DAILY_LIMIT_FILE}: {e}")


# --- Helper Functions ---
def ensure_directories():
    dirs_to_create = [DATA_DIR, PROCESSED_JSON_DIR, PUBLIC_DIR, OUTPUT_HTML_DIR]
    for d in dirs_to_create:
        os.makedirs(d, exist_ok=True)
    logger.info("Ensured core directories exist.")

def generate_article_id(url):
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    url_hash = hashlib.sha1(url.encode()).hexdigest()[:8]
    return f"gyro-{timestamp}-{url_hash}"

def get_user_article_urls():
    urls = []
    print("\nEnter article URL(s). Press Enter after each URL. Type 'done' when finished.")
    while True:
        url_input = input(f"URL {len(urls) + 1} (or 'done'): ").strip()
        if url_input.lower() == 'done':
            if not urls:
                print("No URLs provided. Please provide at least one.")
                continue
            break
        if not (url_input.startswith('http://') or url_input.startswith('https://')):
            print("Invalid URL format. Please include http:// or https://")
            continue
        try:
            parsed = urlparse(url_input)
            if not parsed.netloc: raise ValueError("Missing domain")
            urls.append(url_input)
        except ValueError as e: print(f"Error: Invalid URL structure ({e}). Please try again.")
    logger.info(f"User provided URLs: {urls}")
    return urls

def get_user_importance():
    while True:
        choice = input("Mark as (1) Interesting or (2) Breaking: ").strip()
        if choice == '1': logger.info("Marked as Interesting by user."); return False
        elif choice == '2': logger.info("Marked as Breaking by user."); return True
        print("Invalid choice. Please enter 1 or 2.")

def get_user_image_url():
    have_url = input("Do you have a direct image URL? (yes/no): ").strip().lower()
    if have_url == 'yes':
        img_url = input("Paste image URL: ").strip()
        if (img_url.startswith('http://') or img_url.startswith('https://')):
            logger.info(f"User provided image URL: {img_url}"); return img_url
        else: print("Invalid image URL. Will attempt to scrape/search."); return None
    logger.info("No direct image URL from user. Will scrape/search."); return None

def fetch_content_and_title(article_urls):
    primary_url = article_urls[0]
    logger.info(f"Fetching content and title from primary URL: {primary_url}")
    full_text_content = get_full_article_content(primary_url)
    scraped_title = ""
    if full_text_content:
        try:
            import requests
            from bs4 import BeautifulSoup
            response = requests.get(primary_url, timeout=15, headers={'User-Agent': 'GyroPicksFetcher/1.0'})
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            if soup.title and soup.title.string: scraped_title = soup.title.string.strip(); logger.info(f"Scraped title: '{scraped_title}'")
            elif soup.find('h1'): scraped_title = soup.find('h1').get_text(strip=True); logger.info(f"Scraped H1 as title: '{scraped_title}'")
        except Exception as e: logger.warning(f"Could not scrape title from {primary_url}: {e}")
    else: logger.error(f"Failed to fetch content from primary URL: {primary_url}")
    
    user_title_override = input(f"Scraped title: '{scraped_title}'. Press Enter to use or type new title: ").strip()
    final_title = user_title_override if user_title_override else scraped_title
    if not final_title:
        final_title = input("Could not get title. Please enter article title: ").strip()
        while not final_title: final_title = input("Title cannot be empty. Please enter: ").strip()
    logger.info(f"Using title: '{final_title}'")
    return full_text_content, final_title

def determine_image(user_img_url, article_urls, article_title):
    if user_img_url: logger.info(f"Using user-provided image URL: {user_img_url}"); return user_img_url
    logger.info("Attempting to scrape image from source URLs...")
    for url_to_scrape in article_urls:
        scraped_image = scrape_source_for_image(url_to_scrape)
        if scraped_image: logger.info(f"Scraped image from {url_to_scrape}: {scraped_image}"); return scraped_image
    logger.warning("Failed to scrape image. Falling back to SerpAPI search.")
    if not article_title: logger.error("Cannot search image without title."); return "https://via.placeholder.com/1200x675.png?text=Image+Not+Found"
    searched_image = find_best_image(article_title, article_url_for_scrape=article_urls[0] if article_urls else None)
    if searched_image: logger.info(f"Found image via SerpAPI: {searched_image}"); return searched_image
    logger.error(f"No image for '{article_title}'. Using placeholder."); return "https://via.placeholder.com/1200x675.png?text=Image+Not+Found"

def save_processed_data_local(filepath, article_data_to_save):
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f: json.dump(article_data_to_save, f, indent=4, ensure_ascii=False)
        logger.info(f"Saved Gyro Pick data: {os.path.basename(filepath)}"); return True
    except Exception as e: logger.error(f"Failed save Gyro Pick data {os.path.basename(filepath)}: {e}"); return False

def format_tags_html_local(tags_list):
    if not tags_list: return ""
    import requests # Ensure quote is available
    tag_links = []
    base = YOUR_SITE_BASE_URL if YOUR_SITE_BASE_URL else "/"
    for tag in tags_list:
        safe_tag = requests.utils.quote(str(tag))
        tag_url = urljoin(base, f"topic.html?name={safe_tag}")
        tag_links.append(f'<a href="{tag_url}" class="tag-link">{tag}</a>')
    return ", ".join(tag_links)

def render_post_page_local(template_variables, slug_base):
    try:
        template = jinja_env.get_template('post_template.html')
        html_content = template.render(template_variables)
        safe_filename_base = slug_base if slug_base else template_variables.get('id', 'untitled-gyro')
        safe_filename = re.sub(r'[<>:"/\\|?*%\.]+', '', safe_filename_base).strip().lower().replace(' ', '-')
        safe_filename = re.sub(r'-+', '-', safe_filename).strip('-')[:80] or template_variables.get('id', 'gyro-fallback')
        output_path = os.path.join(OUTPUT_HTML_DIR, f"{safe_filename}.html")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f: f.write(html_content)
        logger.info(f"Rendered HTML for Gyro Pick: {os.path.basename(output_path)}"); return output_path
    except Exception as e: logger.exception(f"CRITICAL: Failed render HTML for Gyro ID {template_variables.get('id','N/A')}: {e}"); return None

def get_sort_key_local(article_dict):
    fallback_date = datetime(1970, 1, 1, tzinfo=timezone.utc)
    date_str = article_dict.get('published_iso')
    if not date_str: return fallback_date
    try:
        if date_str.endswith('Z'): date_str = date_str[:-1] + '+00:00'
        dt = datetime.fromisoformat(date_str)
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except Exception: return fallback_date

def update_all_articles_json_local(new_article_info):
    all_articles_data = []
    if os.path.exists(ALL_ARTICLES_FILE):
        try:
            with open(ALL_ARTICLES_FILE, 'r', encoding='utf-8') as f: content = json.load(f)
            if isinstance(content, dict) and "articles" in content: all_articles_data = content.get("articles", [])
            elif isinstance(content, list): all_articles_data = content
        except Exception as e: logger.error(f"Error loading/parsing {ALL_ARTICLES_FILE}: {e}. Will create new if saving.")

    article_id = new_article_info.get('id')
    if not article_id: logger.error("Update all_articles: missing 'id'."); return
    
    updated = False
    for i, art in enumerate(all_articles_data):
        if isinstance(art, dict) and art.get('id') == article_id:
            all_articles_data[i].update(new_article_info); updated = True; break
    if not updated: all_articles_data.append(new_article_info)
    
    all_articles_data.sort(key=get_sort_key_local, reverse=True)
    try:
        with open(ALL_ARTICLES_FILE, 'w', encoding='utf-8') as f: json.dump({"articles": all_articles_data}, f, indent=2, ensure_ascii=False)
        logger.info(f"Updated {os.path.basename(ALL_ARTICLES_FILE)} ({len(all_articles_data)} articles).")
    except Exception as e: logger.error(f"Failed save {os.path.basename(ALL_ARTICLES_FILE)}: {e}")

# --- Main Script Logic ---
def main():
    logger.info("--- Gyro Picks - Manual Article Processor ---")
    ensure_directories()
    if not YOUR_SITE_BASE_URL: logger.warning("YOUR_SITE_BASE_URL not set in .env.")

    article_urls = get_user_article_urls()
    if not article_urls: logger.info("No URLs. Exiting."); return

    is_breaking_news = get_user_importance()
    user_direct_image_url = get_user_image_url()
    article_content_text, article_title_text = fetch_content_and_title(article_urls)

    if not article_content_text:
        logger.error("Failed to retrieve content. Cannot proceed.")
        if input("Use placeholder summary for testing? (yes/no): ").strip().lower() == 'yes':
            article_content_text = f"Placeholder summary for '{article_title_text}'. Original content failed."
            logger.info("Proceeding with placeholder content.")
        else: logger.info("Exiting."); return

    article_image_final_url = determine_image(user_direct_image_url, article_urls, article_title_text)
    article_id = generate_article_id(article_urls[0])
    current_iso_time = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    initial_article_data = {
        'id': article_id, 'title': article_title_text, 'link': article_urls[0],
        'all_source_links': article_urls, 'published_iso': current_iso_time,
        'summary': (article_content_text[:300] + "...") if article_content_text and len(article_content_text) > 300 else article_content_text,
        'full_text_content': article_content_text, 'content_for_processing': article_content_text,
        'source_feed': "Gyro Pick - Manual", 'scraped_at_iso': current_iso_time,
        'selected_image_url': article_image_final_url,
    }
    logger.debug(f"Initial data: {initial_article_data}")
    logger.info(f"--- Running Agent Pipeline for Gyro Pick ID: {article_id} ---")

    processed_data = run_filter_agent(initial_article_data.copy())
    if not processed_data or processed_data.get('filter_verdict') is None: logger.error(f"Filter Agent failed {article_id}. Abort."); return
    filter_verdict = processed_data['filter_verdict']
    logger.info(f"Filter Agent: {filter_verdict.get('importance_level', 'N/A')}. User set: {'Breaking' if is_breaking_news else 'Interesting'}.")
    processed_data['is_breaking'] = is_breaking_news
    processed_data['topic'] = filter_verdict.get('topic', 'General Tech')
    processed_data['primary_keyword'] = filter_verdict.get('primary_topic_keyword', processed_data['title'])

    processed_data = run_keyword_research_agent(processed_data)
    if processed_data.get('keyword_agent_error'): logger.warning(f"Keyword Research issue {article_id}: {processed_data['keyword_agent_error']}")
    researched_keywords = processed_data.setdefault('researched_keywords', [])
    if not researched_keywords and processed_data.get('primary_keyword'): researched_keywords.append(processed_data['primary_keyword'])
    processed_data['generated_tags'] = list(set(kw for kw in researched_keywords if kw))
    logger.info(f"Using {len(processed_data['generated_tags'])} tags for {article_id}.")

    processed_data['author'] = AUTHOR_NAME_DEFAULT
    processed_data = run_seo_article_agent(processed_data)
    seo_results = processed_data.get('seo_agent_results')
    if not seo_results or not seo_results.get('generated_article_body_md'): logger.error(f"SEO Agent failed {article_id}. Abort."); return
    if processed_data.get('seo_agent_error'): logger.warning(f"SEO Agent non-critical errors {article_id}: {processed_data['seo_agent_error']}")
    if seo_results.get('generated_seo_h1'): processed_data['title'] = seo_results['generated_seo_h1']

    trend_score = (10.0 if processed_data['is_breaking'] else 5.0) + (float(len(processed_data.get('generated_tags', []))) * 0.5)
    processed_data['trend_score'] = round(max(0.0, trend_score), 2)

    slug_text = processed_data.get('title', f'gyro-{article_id}')
    slug = re.sub(r'[<>:"/\\|?*%\.\'"]+', '', slug_text).strip().lower().replace(' ', '-')
    processed_data['slug'] = re.sub(r'-+', '-', slug).strip('-')[:80] or f'gyro-{article_id}'
    article_relative_path = f"articles/{processed_data['slug']}.html"
    canonical_url = urljoin(YOUR_SITE_BASE_URL, article_relative_path.lstrip('/')) if YOUR_SITE_BASE_URL else f"/{article_relative_path.lstrip('/')}"

    body_md = seo_results.get('generated_article_body_md', '')
    body_html = markdown.markdown(body_md, extensions=['fenced_code', 'tables', 'nl2br'])
    tags_html = format_tags_html_local(processed_data['generated_tags'])
    publish_dt = get_sort_key_local(processed_data)

    template_vars = {
        'PAGE_TITLE': seo_results.get('generated_title_tag', processed_data.get('title')), 'META_DESCRIPTION': seo_results.get('generated_meta_description', ''),
        'AUTHOR_NAME': processed_data.get('author', AUTHOR_NAME_DEFAULT), 'META_KEYWORDS': ", ".join(processed_data['generated_tags']),
        'CANONICAL_URL': canonical_url, 'SITE_NAME': YOUR_WEBSITE_NAME, 'YOUR_WEBSITE_LOGO_URL': YOUR_WEBSITE_LOGO_URL,
        'IMAGE_URL': processed_data.get('selected_image_url', ''), 'IMAGE_ALT_TEXT': processed_data.get('title'),
        'META_KEYWORDS_LIST': processed_data['generated_tags'], 'PUBLISH_ISO_FOR_META': processed_data.get('published_iso', current_iso_time),
        'JSON_LD_SCRIPT_BLOCK': seo_results.get('generated_json_ld', ''), 'ARTICLE_HEADLINE': processed_data.get('title'),
        'PUBLISH_DATE': publish_dt.strftime('%B %d, %Y') if publish_dt != datetime(1970,1,1,tzinfo=timezone.utc) else "N/A",
        'ARTICLE_BODY_HTML': body_html, 'ARTICLE_TAGS_HTML': tags_html, 'SOURCE_ARTICLE_URL': processed_data.get('link', '#'),
        'ARTICLE_TITLE': processed_data.get('title'), 'id': article_id, 'CURRENT_ARTICLE_ID': article_id,
        'CURRENT_ARTICLE_TOPIC': processed_data.get('topic', ''), 'CURRENT_ARTICLE_TAGS_JSON': json.dumps(processed_data['generated_tags']),
        'AUDIO_URL': None
    }

    html_path = render_post_page_local(template_vars, processed_data['slug'])
    if not html_path: logger.error(f"Failed HTML render {article_id}. Abort saves."); return

    processed_file_path = os.path.join(PROCESSED_JSON_DIR, f"{article_id}.json")
    if not save_processed_data_local(processed_file_path, processed_data): logger.error(f"Failed save processed JSON {article_id}."); return

    site_entry = {
        "id": article_id, "title": processed_data.get('title'), "link": article_relative_path,
        "published_iso": template_vars['PUBLISH_ISO_FOR_META'], "summary_short": template_vars['META_DESCRIPTION'],
        "image_url": processed_data.get('selected_image_url'), "topic": processed_data.get('topic', 'News'),
        "is_breaking": processed_data.get('is_breaking', False), "tags": processed_data['generated_tags'],
        "audio_url": None, "trend_score": processed_data.get('trend_score', 0)
    }
    update_all_articles_json_local(site_entry)
    logger.info(f"--- Processed Gyro Pick: {article_id} ('{processed_data.get('title')}') ---")
    logger.info(f"    HTML: {os.path.relpath(html_path, PROJECT_ROOT)}")
    logger.info(f"    JSON: {os.path.relpath(processed_file_path, PROJECT_ROOT)}")

    if input("Post to social media? (yes/no): ").strip().lower() == 'yes':
        logger.info("Initializing social media clients...")
        social_clients = initialize_social_clients() # From social_media_poster

        # Corrected check for active social media clients
        active_clients_exist = any(
            (isinstance(client_val, list) and client_val) or \
            (not isinstance(client_val, list) and client_val)
            for client_val in social_clients.values()
        )

        if not active_clients_exist:
            logger.warning("No social media clients were successfully initialized. Cannot post.")
            # Do not return here, allow sitemap generation attempt
        else:
            twitter_client_available = bool(social_clients.get("twitter_client"))
            can_post_to_twitter = False
            current_twitter_posted_count = 0 # Initialize here

            if twitter_client_available:
                today_date_str_for_gyro = datetime.now(timezone.utc).strftime('%Y-%m-%d')
                gyro_twitter_date, current_twitter_posted_count = _read_tweet_tracker()
                if gyro_twitter_date != today_date_str_for_gyro:
                    logger.info(f"New day for Twitter via Gyro. Resetting count from {current_twitter_posted_count}.")
                    current_twitter_posted_count = 0 # Reset for the current script's context
                
                if current_twitter_posted_count < DAILY_TWEET_LIMIT:
                    can_post_to_twitter = True
                    logger.info(f"Gyro Pick CAN be posted to Twitter. Count: {current_twitter_posted_count}/{DAILY_TWEET_LIMIT}")
                else:
                    logger.info(f"Daily Twitter limit reached via Gyro. Twitter SKIPPED for {article_id}")
            
            platforms_for_this_post = ["bluesky", "reddit"]
            if can_post_to_twitter:
                platforms_for_this_post.append("twitter")

            social_payload = {
                'id': article_id, 'title': processed_data.get('title'), 'article_url': canonical_url,
                'image_url': processed_data.get('selected_image_url'), 'summary_short': site_entry.get('summary_short',''),
                'topic': processed_data.get('topic'), 'tags': processed_data['generated_tags']
            }
            
            logger.info(f"Attempting to post Gyro Pick to: {', '.join(platforms_for_this_post)}")
            # run_social_media_poster returns True if Twitter was successfully posted (if attempted)
            twitter_posted_successfully_by_gyro = run_social_media_poster(social_payload, social_clients, platforms_to_post=tuple(platforms_for_this_post))
            
            # Only increment if Twitter was one of the platforms we intended to post to AND it was successful
            if "twitter" in platforms_for_this_post and twitter_posted_successfully_by_gyro:
                # Read the tracker again to ensure atomicity if multiple scripts run close together (less likely for gyro-picks)
                # For gyro-picks, it's more about respecting the limit read at the start of its social posting decision.
                # If it decided to post, it means current_twitter_posted_count was < DAILY_TWEET_LIMIT.
                # So, we increment that count and write it back.
                current_twitter_posted_count += 1 
                _write_tweet_tracker(datetime.now(timezone.utc).strftime('%Y-%m-%d'), current_twitter_posted_count)
                logger.info(f"Gyro Pick successfully posted to Twitter. Updated daily count to {current_twitter_posted_count}.")
            elif "twitter" in platforms_for_this_post and not twitter_posted_successfully_by_gyro:
                 logger.warning(f"Twitter was targeted for Gyro Pick {article_id} but post failed. Daily count not incremented for this attempt.")


    else: logger.info("Skipping social media for this Gyro Pick.")
    
    if input("Regenerate sitemap now? (yes/no): ").strip().lower() == 'yes':
        try:
            logger.info("Regenerating sitemap...")
            run_sitemap_generator()
            logger.info("Sitemap regeneration complete.")
        except Exception as e:
            logger.error(f"Error during sitemap regeneration: {e}")
    else:
        logger.info("Skipping sitemap regeneration. Remember to run it later or via GitHub Action.")


if __name__ == "__main__":
    main()
    logger.info("--- Gyro Picks script finished. ---")