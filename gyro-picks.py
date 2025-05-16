# gyro-picks.py (Streamlined - Automated Title & Sitemap - API Calls Made Here)
import sys
import os
import json
import hashlib
import logging
import re
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, urljoin, quote # Added quote
import markdown
import html

# --- Path Setup & Project Root ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(PROJECT_ROOT))

from dotenv import load_dotenv

try:
    from src.scrapers.news_scraper import get_full_article_content
    from src.scrapers.image_scraper import find_best_image, scrape_source_for_image
    from src.agents.filter_news_agent import run_filter_agent
    from src.agents.keyword_research_agent import run_keyword_research_agent
    from src.agents.seo_article_generator_agent import run_seo_article_agent
    from generate_sitemap import generate_sitemap as run_sitemap_generator
except ImportError as e:
    print(f"FATAL IMPORT ERROR: {e}. Ensure 'src' directory is in the project root and PYTHONPATH is correct.")
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

AUTHOR_NAME_DEFAULT = os.getenv('AUTHOR_NAME', 'Gyro Pick Team')
YOUR_WEBSITE_NAME = os.getenv('YOUR_WEBSITE_NAME', 'Dacoola')
YOUR_WEBSITE_LOGO_URL = os.getenv('YOUR_WEBSITE_LOGO_URL', '')
raw_base_url_env = os.getenv('YOUR_SITE_BASE_URL', '')
YOUR_SITE_BASE_URL_FOR_LINKS = (raw_base_url_env.rstrip('/') + '/') if raw_base_url_env else '/' # Used for link placeholders
BASE_URL_FOR_CANONICAL_PLACEHOLDER_CHECK = os.getenv('YOUR_SITE_BASE_URL', 'https://your-site-url.com')


if not YOUR_SITE_BASE_URL_FOR_LINKS or YOUR_SITE_BASE_URL_FOR_LINKS == "/":
    print("ERROR: YOUR_SITE_BASE_URL not set or invalid in .env. Sitemap, canonical URLs, and internal links will be affected.")

# --- Jinja2 Setup ---
try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    def escapejs_filter(value):
        if value is None: return ''
        return str(value).replace('\\', '\\\\').replace("'", "\\'").replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r')

    if not os.path.isdir(TEMPLATE_DIR):
        print(f"ERROR: Jinja2 template dir not found: {TEMPLATE_DIR}")
        sys.exit(1)
    jinja_env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(['html', 'xml']))
    jinja_env.filters['escapejs'] = escapejs_filter
except ImportError:
    print("ERROR: Jinja2 library not found. Please install it: pip install Jinja2")
    sys.exit(1)
except Exception as e:
    print(f"ERROR: Jinja2 initialization failed: {e}")
    sys.exit(1)

# --- Logging Setup ---
log_file_path = os.path.join(PROJECT_ROOT, 'gyro-picks.log')
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file_path, encoding='utf-8')
    ],
    force=True
)
logger = logging.getLogger('GyroPicks')
logger.setLevel(logging.DEBUG)


# --- Helper Functions (ensure_directories, generate_article_id, etc. remain the same) ---
def ensure_directories():
    for d_path in [DATA_DIR, PROCESSED_JSON_DIR, PUBLIC_DIR, OUTPUT_HTML_DIR]:
        os.makedirs(d_path, exist_ok=True)
    logger.info("Ensured core directories exist.")

def generate_article_id(url_for_hash):
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    url_hash_part = hashlib.sha1(url_for_hash.encode('utf-8')).hexdigest()[:8]
    return f"gyro-{timestamp}-{url_hash_part}"

def get_user_inputs_for_gyro():
    urls = []
    print("\n--- Gyro Pick - Manual Article Processor (Full Pipeline) ---")
    print("Paste article URL(s) for Gyro Pick. Press Enter after each. Type 'done' when finished.")
    while True:
        url_input = input(f"URL {len(urls) + 1} (or 'done'): ").strip()
        if url_input.lower() == 'done':
            if not urls:
                print("Error: At least one URL must be provided for a Gyro Pick.")
                continue
            break
        if not (url_input.startswith('http://') or url_input.startswith('https://')):
            print("Error: Invalid URL format. Please include http:// or https://")
            continue
        try:
            parsed = urlparse(url_input)
            if not parsed.scheme or not parsed.netloc:
                raise ValueError("URL scheme or network location missing.")
            urls.append(url_input)
        except ValueError as e:
            print(f"Error: Invalid URL ({e}). Please try again.")

    is_breaking_choice = False
    while True:
        choice = input("Mark Gyro Pick as (1) Interesting or (2) Breaking [Default: 1]: ").strip()
        if choice == '1' or not choice:
            is_breaking_choice = False
            break
        elif choice == '2':
            is_breaking_choice = True
            break
        else:
            print("Invalid choice. Please enter 1 or 2.")

    is_trending_choice = input("Is this Gyro Pick article trending? (yes/no) [Default: no]: ").strip().lower() == 'yes'

    user_provided_img_url = None
    if input("Do you have a direct image URL for this Gyro Pick? (yes/no) [Default: no]: ").strip().lower() == 'yes':
        img_url_input = input("Paste image URL: ").strip()
        if img_url_input.startswith('http://') or img_url_input.startswith('https://'):
            user_provided_img_url = img_url_input
        else:
            print("Warning: Invalid image URL provided. The script will attempt to scrape/search for an image.")

    logger.info(f"User Inputs for Gyro Pick: URLs={urls}, IsBreaking={is_breaking_choice}, IsTrending={is_trending_choice}, ProvidedImageURL={user_provided_img_url}")
    return urls, is_breaking_choice, is_trending_choice, user_provided_img_url


def get_content_and_initial_title(primary_url):
    logger.info(f"Fetching content and initial title from primary URL: {primary_url}")
    content = get_full_article_content(primary_url)

    initial_title = "Untitled Gyro Pick"
    if content:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(content, 'html.parser')
            if soup.title and soup.title.string:
                initial_title = soup.title.string.strip()
            elif soup.find('h1'):
                initial_title = soup.find('h1').get_text(strip=True)
            if initial_title:
                initial_title = re.sub(r'\s+', ' ', initial_title).strip()
            logger.info(f"Scraped initial title: '{initial_title}'")
        except Exception as e:
            logger.warning(f"Could not scrape initial title from content of {primary_url}: {e}")
    else:
        logger.warning(f"Content fetching failed for {primary_url}. Title will be placeholder.")
        content = f"Content for '{primary_url}' could not be fetched. This is a placeholder."

    return content, initial_title


def determine_image_url_for_gyro(user_img_url, article_source_urls, article_current_title):
    if user_img_url:
        logger.info(f"Using user-provided image URL: {user_img_url}")
        return user_img_url

    logger.info("No user image provided. Attempting to scrape image from source URLs...")
    for url_to_scan in article_source_urls:
        scraped_img = scrape_source_for_image(url_to_scan)
        if scraped_img:
            logger.info(f"Successfully scraped image from {url_to_scan}: {scraped_img}")
            return scraped_img

    logger.warning(f"Failed to scrape image from any source URL. Falling back to SerpAPI search using title: '{article_current_title}'.")
    if not article_current_title or article_current_title == "Untitled Gyro Pick":
        logger.error("Cannot perform effective image search without a valid article title.")
        return "https://via.placeholder.com/1200x675.png?text=Image+Unavailable"

    primary_url_for_scrape_hint = article_source_urls[0] if article_source_urls else None
    searched_img = find_best_image(article_current_title, article_url_for_scrape=primary_url_for_scrape_hint)
    if searched_img:
        logger.info(f"Found image via SerpAPI search: {searched_img}")
        return searched_img

    logger.error(f"Image scraping and search failed for '{article_current_title}'. Using placeholder image.")
    return "https://via.placeholder.com/1200x675.png?text=Image+Not+Found"


def save_processed_gyro_pick_json(article_id, data_to_save):
    os.makedirs(PROCESSED_JSON_DIR, exist_ok=True)
    filepath = os.path.join(PROCESSED_JSON_DIR, f"{article_id}.json")
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, indent=4, ensure_ascii=False)
        logger.info(f"Saved final processed Gyro Pick data to: {os.path.basename(filepath)}")
        return True
    except Exception as e:
        logger.error(f"Failed to save final Gyro Pick JSON data {os.path.basename(filepath)}: {e}")
        return False

def format_tags_for_html(tags_list):
    if not tags_list or not isinstance(tags_list, list):
        return ""
    import requests
    tag_html_links = []
    base_site_url = YOUR_SITE_BASE_URL_FOR_LINKS
    for tag_item in tags_list:
        safe_tag_item = quote(str(tag_item)) # Use urllib.parse.quote
        tag_page_url = urljoin(base_site_url, f"topic.html?name={safe_tag_item}")
        tag_html_links.append(f'<a href="{tag_page_url}" class="tag-link">{html.escape(str(tag_item))}</a>') # Escape tag text
    return ", ".join(tag_html_links)

def render_gyro_pick_html(template_variables, slug_for_filename):
    try:
        template = jinja_env.get_template('post_template.html')
        html_output_content = template.render(template_variables)

        safe_filename_base = slug_for_filename if slug_for_filename else template_variables.get('id', 'untitled-gyro-pick')
        temp_slug = re.sub(r'[^\w\s-]', '', str(safe_filename_base).lower()).strip()
        temp_slug = re.sub(r'[-\s]+', '-', temp_slug)
        safe_filename = temp_slug[:80] or template_variables.get('id', 'gyro-pick-error-slug')

        os.makedirs(OUTPUT_HTML_DIR, exist_ok=True)
        final_html_path = os.path.join(OUTPUT_HTML_DIR, f"{safe_filename}.html")

        with open(final_html_path, 'w', encoding='utf-8') as f:
            f.write(html_output_content)
        logger.info(f"Rendered HTML for Gyro Pick: {os.path.basename(final_html_path)}")
        return final_html_path, f"articles/{safe_filename}.html"
    except Exception as e:
        logger.exception(f"CRITICAL: Failed to render HTML for Gyro Pick ID {template_variables.get('id','N/A')}: {e}")
        return None, None

def get_article_sort_key(article_dict_item):
    default_past_date = datetime(1970, 1, 1, tzinfo=timezone.utc)
    date_iso_str = article_dict_item.get('published_iso')
    if not date_iso_str or not isinstance(date_iso_str, str):
        return default_past_date
    try:
        if date_iso_str.endswith('Z'):
            date_iso_str = date_iso_str[:-1] + '+00:00'
        datetime_obj = datetime.fromisoformat(date_iso_str)
        return datetime_obj.replace(tzinfo=timezone.utc) if datetime_obj.tzinfo is None else datetime_obj
    except ValueError:
        logger.warning(f"Could not parse date string '{date_iso_str}' for sorting. Using default.")
        return default_past_date

def update_all_articles_list_json(new_gyro_pick_summary):
    current_articles_list = []
    if os.path.exists(ALL_ARTICLES_FILE):
        try:
            with open(ALL_ARTICLES_FILE, 'r', encoding='utf-8') as f:
                json_content = json.load(f)
            if isinstance(json_content, dict) and "articles" in json_content:
                current_articles_list = json_content.get("articles", [])
            elif isinstance(json_content, list):
                current_articles_list = json_content
                logger.info(f"Loaded old list format from {ALL_ARTICLES_FILE}. Will save in new format.")
            if not isinstance(current_articles_list, list):
                logger.warning(f"Content of 'articles' in {ALL_ARTICLES_FILE} is not a list. Resetting.")
                current_articles_list = []
        except json.JSONDecodeError:
            logger.warning(f"{ALL_ARTICLES_FILE} is corrupted or empty. Starting a new list.")
        except Exception as e:
            logger.error(f"Unexpected error loading {ALL_ARTICLES_FILE}: {e}. Starting new list.")

    gyro_pick_id = new_gyro_pick_summary.get('id')
    if not gyro_pick_id:
        logger.error("Cannot update all_articles.json: Gyro Pick summary is missing 'id'.")
        return

    current_articles_list = [
        article for article in current_articles_list
        if isinstance(article, dict) and article.get('id') != gyro_pick_id
    ]
    current_articles_list.append(new_gyro_pick_summary)

    current_articles_list.sort(key=get_article_sort_key, reverse=True)

    final_data_to_save = {"articles": current_articles_list}
    try:
        with open(ALL_ARTICLES_FILE, 'w', encoding='utf-8') as f:
            json.dump(final_data_to_save, f, indent=2, ensure_ascii=False)
        logger.info(f"Successfully updated {os.path.basename(ALL_ARTICLES_FILE)} with {len(current_articles_list)} articles.")
    except Exception as e:
        logger.error(f"Failed to save updated {os.path.basename(ALL_ARTICLES_FILE)}: {e}")

# --- NEW: Link Placeholder Processing ---
def slugify(text):
    """Generates a URL-friendly slug from text."""
    if not text: return "untitled"
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text).strip() # Remove non-alphanumeric (except space, hyphen)
    text = re.sub(r'[-\s]+', '-', text)       # Replace spaces/hyphens with single hyphen
    return text[:70] # Max length for slug part

def process_link_placeholders(markdown_text, base_site_url):
    """
    Processes [[Internal Link Text | Optional Topic/Slug]] and 
              ((External Link Text | https://...)) placeholders in Markdown.
    """
    if not markdown_text:
        return ""

    # Process internal links: [[Link Text | Topic/Slug]] or [[Link Text]]
    def replace_internal(match):
        link_text = match.group(1).strip()
        topic_or_slug = match.group(3).strip() if match.group(3) else None

        if topic_or_slug:
            # Assume it's a topic name, construct topic URL
            # If it looks like a pre-made slug (e.g., ends .html or has no spaces), use as is
            if topic_or_slug.endswith(".html") or ' ' not in topic_or_slug:
                 href = urljoin(base_site_url, f"articles/{topic_or_slug.lstrip('/')}") if topic_or_slug.endswith(".html") else urljoin(base_site_url, f"topic.html?name={quote(topic_or_slug)}")
            else: # Assume it's a topic name
                href = urljoin(base_site_url, f"topic.html?name={quote(topic_or_slug)}")
        else:
            # Slugify the link text to create a topic URL
            slugified_link_text = slugify(link_text)
            href = urljoin(base_site_url, f"topic.html?name={quote(slugified_link_text)}")
        
        logger.debug(f"Internal link: Text='{link_text}', Target='{topic_or_slug}', Href='{href}'")
        return f'<a href="{html.escape(href)}" class="internal-link">{html.escape(link_text)}</a>'

    markdown_text = re.sub(r'\[\[\s*(.*?)\s*(?:\|\s*(.*?)\s*)?\]\]', replace_internal, markdown_text)

    # Process external links: ((Link Text | URL))
    def replace_external(match):
        link_text = match.group(1).strip()
        url = match.group(2).strip()
        logger.debug(f"External link: Text='{link_text}', URL='{url}'")
        return f'<a href="{html.escape(url)}" target="_blank" rel="noopener noreferrer" class="external-link">{html.escape(link_text)}</a>'

    markdown_text = re.sub(r'\(\(\s*(.*?)\s*\|\s*(https?://.*?)\s*\)\)', replace_external, markdown_text)
    
    return markdown_text


# --- Main Processing Logic for Gyro Picks ---
def process_gyro_pick():
    logger.info("--- Gyro Picks - Manual Article Processor (Full Pipeline) ---")
    ensure_directories()

    article_urls, user_is_breaking, user_is_trending, user_img_url = get_user_inputs_for_gyro()
    if not article_urls:
        logger.info("No URLs provided by user. Exiting Gyro Pick processor.")
        return

    primary_url = article_urls[0]
    content_for_agents, initial_title_for_image_search = get_content_and_initial_title(primary_url)

    if not content_for_agents:
        logger.error(f"Failed to fetch critical content from {primary_url}. Cannot proceed with this Gyro Pick.")
        return

    image_url_to_use = determine_image_url_for_gyro(user_img_url, article_urls, initial_title_for_image_search)

    gyro_pick_id = generate_article_id(primary_url)
    current_time_iso_str = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    initial_article_data = {
        'id': gyro_pick_id,
        'title': initial_title_for_image_search,
        'link': primary_url,
        'all_source_links': article_urls,
        'published_iso': current_time_iso_str,
        'summary': (content_for_agents[:300] + "...") if content_for_agents and len(content_for_agents) > 300 else content_for_agents,
        'full_text_content': content_for_agents,
        'content_for_processing': content_for_agents,
        'source_feed': "Gyro Pick - Manual Input",
        'scraped_at_iso': current_time_iso_str,
        'selected_image_url': image_url_to_use,
        'author': AUTHOR_NAME_DEFAULT,
    }
    logger.info(f"--- Running Agent Pipeline for Gyro Pick ID: {gyro_pick_id} ---")

    filtered_article_data = run_filter_agent(initial_article_data.copy())
    if not filtered_article_data or filtered_article_data.get('filter_verdict') is None:
        logger.error(f"Filter Agent failed for Gyro Pick {gyro_pick_id}. ABORTING.")
        return
    filter_agent_verdict = filtered_article_data['filter_verdict']
    logger.info(f"Filter Agent classified Gyro Pick as: {filter_agent_verdict.get('importance_level', 'N/A')}.")

    filtered_article_data['is_breaking'] = user_is_breaking
    filtered_article_data['topic'] = filter_agent_verdict.get('topic', 'General Technology News')
    filtered_article_data['primary_keyword'] = filter_agent_verdict.get('primary_topic_keyword', initial_title_for_image_search)

    keywords_article_data = run_keyword_research_agent(filtered_article_data.copy())
    if keywords_article_data.get('keyword_agent_error'):
        logger.warning(f"Keyword Research issue for Gyro Pick {gyro_pick_id}: {keywords_article_data['keyword_agent_error']}")

    researched_kw_list = keywords_article_data.get('researched_keywords', [])
    primary_kw_from_filter = keywords_article_data.get('primary_keyword')
    final_tags_list = []
    if primary_kw_from_filter and isinstance(primary_kw_from_filter, str) and len(primary_kw_from_filter.strip()) > 1:
        final_tags_list.append(primary_kw_from_filter.strip())
    if researched_kw_list:
        for kw_item in researched_kw_list:
            if kw_item and isinstance(kw_item, str) and len(kw_item.strip()) > 1 and kw_item.strip().lower() not in (t.lower() for t in final_tags_list):
                final_tags_list.append(kw_item.strip())
    if not final_tags_list:
        logger.error(f"No usable keywords/tags found for {gyro_pick_id} after keyword research. Using generic tags.")
        final_tags_list = [keywords_article_data.get('topic', "Tech News"), "AI Insights"]
    keywords_article_data['generated_tags'] = final_tags_list[:15]

    seo_article_data = run_seo_article_agent(keywords_article_data.copy())
    seo_agent_results = seo_article_data.get('seo_agent_results')
    if not seo_agent_results or not seo_agent_results.get('generated_article_body_md'):
        logger.error(f"SEO Article Generator Agent failed for Gyro Pick {gyro_pick_id}. ABORTING.")
        return
    if seo_article_data.get('seo_agent_error'):
        logger.warning(f"SEO Agent reported non-critical errors for Gyro Pick {gyro_pick_id}: {seo_article_data['seo_agent_error']}")

    final_seo_title = seo_article_data.get('title', initial_title_for_image_search)
    logger.info(f"Final AI Generated Title for Gyro Pick {gyro_pick_id}: '{final_seo_title}'")

    gyro_trend_score = 0.0
    if seo_article_data.get('is_breaking', False): gyro_trend_score += 10.0
    else: gyro_trend_score += 5.0
    if user_is_trending: gyro_trend_score += 7.0
    gyro_trend_score += float(len(seo_article_data.get('generated_tags', []))) * 0.3
    seo_article_data['trend_score'] = round(max(0.0, gyro_trend_score), 2)

    slug_for_file = re.sub(r'[<>:"/\\|?*%\.\'"]+', '', str(final_seo_title)).strip().lower().replace(' ', '-')
    seo_article_data['slug'] = re.sub(r'-+', '-', slug_for_file).strip('-')[:80] or f'gyro-pick-{gyro_pick_id}'

    article_relative_web_path = f"articles/{seo_article_data['slug']}.html"
    if YOUR_SITE_BASE_URL_FOR_LINKS and YOUR_SITE_BASE_URL_FOR_LINKS != '/': # Use the correct base URL variable
        canonical_page_url = urljoin(YOUR_SITE_BASE_URL_FOR_LINKS, article_relative_web_path.lstrip('/'))
    else: canonical_page_url = f"/{article_relative_web_path.lstrip('/')}"

    article_body_markdown_raw = seo_agent_results.get('generated_article_body_md', '')
    logger.debug(f"======= RAW MARKDOWN FROM LLM (GyroPick ID: {gyro_pick_id}) =======")
    logger.debug(article_body_markdown_raw[:1000] + "..." if len(article_body_markdown_raw) > 1000 else article_body_markdown_raw)
    logger.debug(f"======= END RAW MARKDOWN FROM LLM =======")

    # --- Process Link Placeholders BEFORE Markdown to HTML conversion ---
    logger.info(f"Processing link placeholders for Gyro Pick {gyro_pick_id}...")
    article_body_markdown_with_links = process_link_placeholders(article_body_markdown_raw, YOUR_SITE_BASE_URL_FOR_LINKS)
    logger.debug(f"======= MARKDOWN AFTER LINK PLACEHOLDERS (GyroPick ID: {gyro_pick_id}) =======")
    logger.debug(article_body_markdown_with_links[:1000] + "..." if len(article_body_markdown_with_links) > 1000 else article_body_markdown_with_links)
    logger.debug(f"======= END MARKDOWN AFTER LINK PLACEHOLDERS =======")
    # --- End Link Placeholder Processing ---

    article_body_html_content = markdown.markdown(
        article_body_markdown_with_links, # Use the version with <a href> tags already inserted
        extensions=['fenced_code', 'tables', 'nl2br', 'sane_lists', 'extra']
    )
    
    logger.critical(f"CRITICAL DEBUG - article_body_html_content PRE-UNESCAPE (first 500 chars): {article_body_html_content[:500]}")
    if "<" in article_body_html_content or ">" in article_body_html_content or "&" in article_body_html_content:
        logger.warning(f"Detected HTML entities in markdown output for {gyro_pick_id}. Attempting to unescape.")
        article_body_html_content = html.unescape(article_body_html_content)
        logger.critical(f"CRITICAL DEBUG - article_body_html_content POST-UNESCAPE (first 500 chars): {article_body_html_content[:500]}")

    logger.debug(f"======= HTML CONTENT AFTER MARKDOWN & UNESCAPE (GyroPick ID: {gyro_pick_id}) =======")
    logger.debug(article_body_html_content[:1000] + "..." if len(article_body_html_content) > 1000 else article_body_html_content)
    logger.debug(f"======= END HTML CONTENT =======")

    article_tags_html_content = format_tags_for_html(seo_article_data.get('generated_tags', []))
    publish_datetime_obj = get_article_sort_key(seo_article_data)

    raw_json_ld = seo_agent_results.get('generated_json_ld_raw', '{}')
    placeholder_in_json_ld = f"{BASE_URL_FOR_CANONICAL_PLACEHOLDER_CHECK.rstrip('/')}/articles/{{SLUG_PLACEHOLDER}}"

    if placeholder_in_json_ld in raw_json_ld:
        final_json_ld_str = raw_json_ld.replace(placeholder_in_json_ld, canonical_page_url)
        final_json_ld_script_tag = f'<script type="application/ld+json">\n{final_json_ld_str}\n</script>'
        logger.info(f"Replaced JSON-LD placeholder for {gyro_pick_id} with actual canonical URL: {canonical_page_url}")
    else:
        final_json_ld_script_tag = seo_agent_results.get('generated_json_ld_full_script_tag', '<script type="application/ld+json">{}</script>')
        expected_placeholder_debug = f"{BASE_URL_FOR_CANONICAL_PLACEHOLDER_CHECK.rstrip('/')}/articles/{{SLUG_PLACEHOLDER}}"
        if "{SLUG_PLACEHOLDER}" in raw_json_ld and expected_placeholder_debug not in raw_json_ld:
             logger.warning(f"JSON-LD for {gyro_pick_id} contains '{{SLUG_PLACEHOLDER}}' but not the expected full placeholder '{expected_placeholder_debug}'. Raw JSON-LD might be malformed or base URL used by SEO agent differs. Raw JSON-LD prefix: {raw_json_ld[:250]}...")
        elif "{SLUG_PLACEHOLDER}" not in raw_json_ld:
             logger.info(f"JSON-LD placeholder '{expected_placeholder_debug}' not found in raw_json_ld for {gyro_pick_id}. Using existing full script tag.")


    template_render_variables = {
        'PAGE_TITLE': seo_agent_results.get('generated_title_tag', final_seo_title),
        'META_DESCRIPTION': seo_agent_results.get('generated_meta_description', ''),
        'AUTHOR_NAME': seo_article_data.get('author', AUTHOR_NAME_DEFAULT),
        'META_KEYWORDS_LIST': seo_article_data.get('generated_tags', []),
        'CANONICAL_URL': canonical_page_url,
        'SITE_NAME': YOUR_WEBSITE_NAME,
        'YOUR_WEBSITE_LOGO_URL': YOUR_WEBSITE_LOGO_URL,
        'IMAGE_URL': seo_article_data.get('selected_image_url', ''),
        'IMAGE_ALT_TEXT': final_seo_title,
        'PUBLISH_ISO_FOR_META': seo_article_data.get('published_iso', current_time_iso_str),
        'JSON_LD_SCRIPT_BLOCK': final_json_ld_script_tag,
        'ARTICLE_HEADLINE': final_seo_title,
        'ARTICLE_SEO_H1': final_seo_title,
        'PUBLISH_DATE': publish_datetime_obj.strftime('%B %d, %Y') if publish_datetime_obj != datetime(1970,1,1,tzinfo=timezone.utc) else "Date Not Available",
        'ARTICLE_BODY_HTML': article_body_html_content,
        'ARTICLE_TAGS_HTML': article_tags_html_content,
        'SOURCE_ARTICLE_URL': seo_article_data.get('link', '#'),
        'ARTICLE_TITLE': final_seo_title,
        'id': gyro_pick_id,
        'CURRENT_ARTICLE_ID': gyro_pick_id,
        'CURRENT_ARTICLE_TOPIC': seo_article_data.get('topic', 'News'),
        'CURRENT_ARTICLE_TAGS_JSON': json.dumps(seo_article_data.get('generated_tags', [])),
        'AUDIO_URL': None
    }

    rendered_html_path, relative_web_link = render_gyro_pick_html(template_render_variables, seo_article_data['slug'])
    if not rendered_html_path:
        logger.error(f"Failed to render HTML page for Gyro Pick {gyro_pick_id}. Aborting final save steps.")
        return

    if not save_processed_gyro_pick_json(gyro_pick_id, seo_article_data):
        logger.error(f"Failed to save processed JSON for Gyro Pick {gyro_pick_id}.")

    summary_for_all_articles = {
        "id": gyro_pick_id,
        "title": final_seo_title,
        "link": relative_web_link,
        "published_iso": seo_article_data.get('published_iso', current_time_iso_str),
        "summary_short": seo_agent_results.get('generated_meta_description', ''),
        "image_url": seo_article_data.get('selected_image_url'),
        "topic": seo_article_data.get('topic', 'News'),
        "is_breaking": seo_article_data.get('is_breaking', False),
        "is_trending_pick": user_is_trending,
        "tags": seo_article_data.get('generated_tags', []),
        "audio_url": None,
        "trend_score": seo_article_data.get('trend_score', 0)
    }
    update_all_articles_list_json(summary_for_all_articles)

    logger.info(f"--- Successfully processed Gyro Pick: {gyro_pick_id} ('{final_seo_title}') ---")
    logger.info(f"    HTML Output: {os.path.relpath(rendered_html_path, PROJECT_ROOT)}")
    logger.info(f"    Processed JSON: {os.path.join(PROCESSED_JSON_DIR, f'{gyro_pick_id}.json')}")
    logger.info("Gyro Pick processing complete. Changes will be part of the next GitHub commit/push.")
    logger.info("Social media posting for Gyro Picks is handled by the main GitHub Action workflow AFTER content is committed and deployed.")


if __name__ == "__main__":
    if not os.getenv('DEEPSEEK_API_KEY'):
        logger.error("DEEPSEEK_API_KEY is not set in the environment. GyroPicks full processing pipeline cannot run.")
        sys.exit(1)

    process_gyro_pick()

    if YOUR_SITE_BASE_URL_FOR_LINKS and YOUR_SITE_BASE_URL_FOR_LINKS != '/':
        logger.info("--- Running Sitemap Generator Post Gyro Pick ---")
        try:
            run_sitemap_generator()
            logger.info("Sitemap generation completed successfully after Gyro Pick.")
        except Exception as e:
            logger.error(f"Sitemap generation failed after Gyro Pick: {e}")
    else:
        logger.warning("Sitemap generation skipped after Gyro Pick: YOUR_SITE_BASE_URL not set or is invalid.")

    logger.info("--- Gyro Picks script finished. ---")