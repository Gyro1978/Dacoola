import os
import sys
import json
import logging
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
import hashlib
import requests # <<<< ADDED IMPORT

# --- !! Path Setup - Must be at the very top !! ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR) 
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
# --- End Path Setup ---

# --- Import necessary functions ---
try:
    from scrapers.news_scraper import get_full_article_content 
    from scrapers.image_scraper import find_best_image, scrape_source_for_image
    from agents.keyword_research_agent import run_keyword_research_agent 
    from agents.seo_article_generator_agent import run_seo_article_agent 
    from social.social_media_poster import initialize_social_clients, run_social_media_poster
    
    try:
        from main import (
            ensure_directories, save_processed_data, update_all_articles_json,
            load_all_articles_data, get_sort_key, format_tags_html,
            AUTHOR_NAME_DEFAULT, YOUR_WEBSITE_NAME, YOUR_WEBSITE_LOGO_URL, YOUR_SITE_BASE_URL,
            PROCESSED_JSON_DIR, OUTPUT_HTML_DIR, TEMPLATE_DIR, 
            DAILY_TWEET_LIMIT, TWITTER_DAILY_LIMIT_FILE, MAKE_WEBHOOK_URL,
            _read_tweet_tracker, _write_tweet_tracker, send_make_webhook
        )
    except ImportError:
        print("Warning: Could not import some utilities from main.py. Manual submitter might have reduced functionality or use fallbacks.")
        AUTHOR_NAME_DEFAULT = "AI News Team"
        YOUR_WEBSITE_NAME = "Dacoola" 
        YOUR_WEBSITE_LOGO_URL = ""    
        YOUR_SITE_BASE_URL = "/"      
        PROCESSED_JSON_DIR = os.path.join(PROJECT_ROOT, 'data', 'processed_json')
        OUTPUT_HTML_DIR = os.path.join(PROJECT_ROOT, 'public', 'articles')
        TEMPLATE_DIR = os.path.join(PROJECT_ROOT, 'templates')


    import markdown
    from jinja2 import Environment, FileSystemLoader
    from dotenv import load_dotenv
    from bs4 import BeautifulSoup

except ImportError as e:
    print(f"FATAL IMPORT ERROR in manual_article_submitter.py: {e}")
    sys.exit(1)

# --- Load Environment Variables ---
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)

DEEPSEEK_API_KEY_MANUAL = os.getenv('DEEPSEEK_API_KEY') 
DEEPSEEK_API_URL_MANUAL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_HELPER_MODEL = "deepseek-chat"
MAX_RESEARCH_SNIPPET_LENGTH = 1500 

# --- Setup Logging ---
log_file_path = os.path.join(PROJECT_ROOT, 'dacola_manual_advanced.log')
try:
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    log_handlers = [logging.StreamHandler(sys.stdout), logging.FileHandler(log_file_path, encoding='utf-8')]
except OSError as e: print(f"Log warning: {e}. Console only."); log_handlers = [logging.StreamHandler(sys.stdout)]
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S', handlers=log_handlers, force=True)
logger = logging.getLogger('manual_submitter_adv')

# --- Jinja2 Setup ---
try:
    def escapejs_filter_manual_adv(value):
        if value is None: return ''; value = str(value); value = value.replace('\\', '\\\\').replace('"', '\\"').replace('/', '\\/')
        value = value.replace('<', '\\u003c').replace('>', '\\u003e'); value = value.replace('\b', '\\b').replace('\f', '\\f').replace('\n', '\\n')
        value = value.replace('\r', '\\r').replace('\t', '\\t'); return value
    env_manual_adv = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True) 
    env_manual_adv.filters['escapejs'] = escapejs_filter_manual_adv
    logger.info(f"Jinja2 environment loaded for ADVANCED manual submitter from {TEMPLATE_DIR}")
except Exception as e: logger.exception("CRITICAL: Failed Jinja2 init for ADVANCED manual submitter."); sys.exit(1)

def generate_manual_article_id(url, title):
    identifier_base = f"{url}::{title}::manual_submission" 
    return hashlib.sha256(identifier_base.encode('utf-8')).hexdigest()

def _call_deepseek_helper(prompt_text, purpose="helper task", expect_json=False): # Added expect_json flag
    if not DEEPSEEK_API_KEY_MANUAL:
        logger.error(f"DeepSeek API key missing for {purpose}.")
        return None
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {DEEPSEEK_API_KEY_MANUAL}"}
    payload = {
        "model": DEEPSEEK_HELPER_MODEL, 
        "messages": [{"role": "user", "content": prompt_text}], 
        "max_tokens": 300, 
        "temperature": 0.3
    }
    if expect_json: # Add response_format if JSON is expected
        payload["response_format"] = {"type": "json_object"}

    logger.info(f"Calling DeepSeek for {purpose} (expect_json: {expect_json})...")
    try:
        response = requests.post(DEEPSEEK_API_URL_MANUAL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()
        if result.get("choices") and result["choices"][0].get("message"):
            content_str = result["choices"][0]["message"].get("content","").strip()
            # Attempt to strip markdown fences if present, especially if not using json_object mode or it fails
            if content_str.startswith("```json"):
                content_str = content_str[7:].strip()
                if content_str.endswith("```"):
                    content_str = content_str[:-3].strip()
            elif content_str.startswith("```"):
                content_str = content_str[3:].strip()
                if content_str.endswith("```"):
                    content_str = content_str[:-3].strip()
            return content_str # Return string, parsing happens in calling function
        logger.error(f"DeepSeek API response malformed for {purpose}: {result}")
        return None
    except Exception as e: logger.exception(f"DeepSeek API call for {purpose} failed: {e}"); return None

def derive_topic_and_keyword(title, text_snippet):
    from agents.filter_news_agent import ALLOWED_TOPICS 
    allowed_topics_str = ", ".join(ALLOWED_TOPICS)
    prompt = f"""
    Analyze the following article title and content snippet:
    Title: "{title}"
    Snippet: "{text_snippet[:1000]}..."

    Your task is to:
    1. Identify the single MOST relevant topic from the provided list: {allowed_topics_str}.
    2. Formulate a concise (3-5 words) primary keyword phrase that encapsulates the core subject matter.

    Please provide your response strictly in the following JSON format:
    {{
      "derived_topic": "Your Selected Topic From List",
      "derived_primary_keyword": "Your Concise Keyword Phrase"
    }}
    """
    logger.info("Deriving topic and primary keyword using DeepSeek...")
    # Pass expect_json=True to _call_deepseek_helper
    response_str = _call_deepseek_helper(prompt, "topic/keyword derivation", expect_json=True)
    if response_str:
        try:
            # The response_str should already be clean JSON if json_object mode worked.
            data = json.loads(response_str) 
            derived_topic = data.get("derived_topic")
            derived_keyword = data.get("derived_primary_keyword")
            if derived_topic in ALLOWED_TOPICS and derived_keyword and isinstance(derived_keyword, str) and derived_keyword.strip():
                logger.info(f"Derived Topic: {derived_topic}, Derived Keyword: {derived_keyword}")
                return derived_topic, derived_keyword.strip()
            else:
                logger.warning(f"LLM derivation failed validation or returned unexpected types. Topic: {derived_topic} (type: {type(derived_topic)}), Keyword: {derived_keyword} (type: {type(derived_keyword)})")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from topic/keyword derivation: {response_str}. Error: {e}")
        except TypeError as e: # Catch if data.get() is on a non-dict, e.g. if LLM returns a list by mistake
            logger.error(f"LLM returned unexpected data type for topic/keyword derivation: {response_str}. Error: {e}")


    logger.warning("Falling back to default topic/keyword due to derivation issues.")
    # Fallback logic
    fallback_topic = "General Tech"
    fallback_keyword = ' '.join(title.split()[:4]).strip() if title else "Tech Article"
    if not fallback_keyword: fallback_keyword = "Tech Article"
    return fallback_topic, fallback_keyword


def fetch_research_snippets(query, num_snippets=2):
    logger.info(f"Simulating research for '{query}'. In a real setup, would fetch {num_snippets} snippets.")
    return []


def process_advanced_manual_submission(article_url):
    logger.info(f"--- ADVANCED Manual Processing for URL: {article_url} ---")
    if 'ensure_directories' in globals(): ensure_directories()
    else: logger.warning("ensure_directories function not available.")

    logger.info(f"Fetching primary content for: {article_url}...")
    primary_content = get_full_article_content(article_url)
    if not primary_content:
        logger.error(f"Failed to fetch content from {article_url}. Aborting."); return False
    logger.info(f"Fetched primary content (length: {len(primary_content)}).")

    page_title = "Manually Submitted Advanced Article"
    try:
        # Try parsing fetched HTML content first for title
        temp_soup_primary = BeautifulSoup(primary_content, 'html.parser')
        if temp_soup_primary.title and temp_soup_primary.title.string:
            page_title = temp_soup_primary.title.string.strip()
        elif temp_soup_primary.find('h1'):
            page_title = temp_soup_primary.find('h1').get_text(strip=True)
        
        # If still default, try fetching URL again just for fresh headers/title tag via requests
        if page_title == "Manually Submitted Advanced Article":
            logger.debug(f"Primary content parsing didn't yield title. Attempting direct request for title for {article_url}")
            response_title_fetch = requests.get(article_url, timeout=15, headers={'User-Agent': 'Mozilla/5.0 DacoolaTitleFetcher/1.0'})
            response_title_fetch.raise_for_status()
            soup_title = BeautifulSoup(response_title_fetch.content, 'html.parser')
            if soup_title.title and soup_title.title.string:
                page_title = soup_title.title.string.strip()
            elif soup_title.find('h1'): # Fallback to H1 from fresh request
                page_title = soup_title.find('h1').get_text(strip=True)
        
        if not page_title or page_title == "Manually Submitted Advanced Article": # Final fallback if still not found
             if len(primary_content) > 50: page_title = primary_content.splitlines()[0].strip()[:150] # Use first line
        
        if "|" in page_title: page_title = page_title.split("|")[0].strip()
        if " - " in page_title: page_title = page_title.split(" - ")[0].strip()
        page_title = page_title[:150] 
        logger.info(f"Extracted/Derived page title: {page_title}")
    except Exception as e: logger.warning(f"Could not extract refined title for {article_url}: {e}. Using default or first line.")


    article_id = generate_manual_article_id(article_url, page_title)
    processed_file_path = os.path.join(PROCESSED_JSON_DIR, f"{article_id}.json")
    if os.path.exists(processed_file_path):
        logger.warning(f"Article {article_id} (URL: {article_url}) already processed. Overwrite? (y/n)")
        if input("> ").strip().lower() != 'y': logger.info("Skipping."); return False

    importance_input = input("Is this 'Breaking' (1) or 'Interesting' (2)? [Default 2]: ").strip()
    importance_level = "Breaking" if importance_input == '1' else "Interesting"
    logger.info(f"Importance set to: {importance_level}")

    derived_topic, derived_primary_keyword = derive_topic_and_keyword(page_title, primary_content)
    research_snippets = fetch_research_snippets(f"{page_title} {derived_primary_keyword}", num_snippets=2)
    
    if research_snippets:
        logger.info(f"Found {len(research_snippets)} research snippets (conceptual).")

    article_data = {
        'id': article_id, 'title': page_title, 'link': article_url,
        'content_for_processing': primary_content, 
        'summary': primary_content[:500] + "..." if len(primary_content) > 500 else primary_content,
        'published_iso': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'scraped_at_iso': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'source_feed': 'manual_submission_advanced',
        'filter_verdict': {
            'importance_level': importance_level, 'topic': derived_topic,
            'reasoning_summary': {
                "override_entity_check": "Manual submission - advanced processing.",
                "factuality_novelty": "Content provided by user; processed for insights.",
                "impact_assessment": f"Manually set to '{importance_level}'.",
                "final_justification": f"Manually submitted as '{importance_level}'; topic/keyword derived by AI."
            },
            'primary_topic_keyword': derived_primary_keyword
        },
        'is_breaking': (importance_level == "Breaking"),
        'topic': derived_topic,
        'primary_keyword': derived_primary_keyword
    }

    logger.info(f"Finding image for '{page_title}'...")
    image_search_query = f"{page_title} {derived_primary_keyword}"
    selected_image_url = scrape_source_for_image(article_url) or find_best_image(image_search_query, article_url_for_scrape=article_url)
    if not selected_image_url: logger.warning(f"No image found for {article_url}. Article will lack image."); article_data['selected_image_url'] = ""
    else: article_data['selected_image_url'] = selected_image_url; logger.info(f"Selected image: {selected_image_url}")

    article_data = run_keyword_research_agent(article_data) 
    article_data['generated_tags'] = list(set(article_data.get('researched_keywords', [derived_primary_keyword])))

    article_data = run_seo_article_agent(article_data) 
    seo_results = article_data.get('seo_agent_results')
    if not seo_results or not seo_results.get('generated_article_body_md') or "<!-- Error:" in seo_results.get('generated_article_body_md',''):
        logger.error(f"ADVANCED SEO Agent failed for {article_id}. Aborting."); return False
    
    final_title = article_data.get('title', page_title) 
    article_data['slug'] = (re.sub(r'[^\w\s-]', '', final_title).strip().lower().replace(' ', '-')[:70] or f"manual-{article_id}")
    article_data['slug'] = re.sub(r'-+', '-', article_data['slug']).strip('-')


    article_relative_path = f"articles/{article_data['slug']}.html"
    canonical_url = urljoin(YOUR_SITE_BASE_URL, article_relative_path) if YOUR_SITE_BASE_URL != "/" else f"/{article_relative_path}"
    body_html = markdown.markdown(seo_results.get('generated_article_body_md', ''), extensions=['fenced_code', 'tables', 'nl2br'])
    tags_html_str = format_tags_html(article_data['generated_tags']) if 'format_tags_html' in globals() else ", ".join(article_data['generated_tags'])
    publish_dt_obj_manual = get_sort_key(article_data) if 'get_sort_key' in globals() else datetime.now(timezone.utc)

    template_vars = {
        'PAGE_TITLE': seo_results.get('generated_title_tag', final_title),
        'META_DESCRIPTION': seo_results.get('generated_meta_description', ''),
        'AUTHOR_NAME': AUTHOR_NAME_DEFAULT, 'META_KEYWORDS': ", ".join(article_data['generated_tags']),
        'CANONICAL_URL': canonical_url, 'SITE_NAME': YOUR_WEBSITE_NAME, 'YOUR_WEBSITE_LOGO_URL': YOUR_WEBSITE_LOGO_URL,
        'IMAGE_URL': article_data.get('selected_image_url', ''), 'IMAGE_ALT_TEXT': final_title,
        'META_KEYWORDS_LIST': article_data['generated_tags'], 
        'PUBLISH_ISO_FOR_META': article_data.get('published_iso'),
        'JSON_LD_SCRIPT_BLOCK': seo_results.get('generated_json_ld', ''), 
        'ARTICLE_HEADLINE': final_title, 
        'PUBLISH_DATE': publish_dt_obj_manual.strftime('%B %d, %Y'),
        'ARTICLE_BODY_HTML': body_html, 'ARTICLE_TAGS_HTML': tags_html_str,
        'SOURCE_ARTICLE_URL': article_data.get('link', '#'), 'ARTICLE_TITLE': final_title, 
        'id': article_id, 'CURRENT_ARTICLE_ID': article_id,
        'CURRENT_ARTICLE_TOPIC': article_data.get('topic', ''), 
        'CURRENT_ARTICLE_TAGS_JSON': json.dumps(article_data['generated_tags']),
        'AUDIO_URL': None
    }
    template = env_manual_adv.get_template('post_template.html')
    html_content = template.render(template_vars)
    output_html_path = os.path.join(OUTPUT_HTML_DIR, f"{article_data['slug']}.html")
    try:
        os.makedirs(os.path.dirname(output_html_path), exist_ok=True)
        with open(output_html_path, 'w', encoding='utf-8') as f: f.write(html_content)
        logger.info(f"Rendered HTML: {output_html_path}")
    except Exception as e: logger.exception(f"CRITICAL - Failed HTML render: {e}"); return False

    site_data_entry = {
        "id": article_id, "title": final_title, "link": article_relative_path,
        "published_iso": article_data.get('published_iso'),
        "summary_short": seo_results.get('generated_meta_description', '')[:250], 
        "image_url": article_data.get('selected_image_url'), "topic": article_data.get('topic'),
        "is_breaking": article_data.get('is_breaking', False), "tags": article_data['generated_tags'],
        "audio_url": None, "trend_score": 10.0 if importance_level == "Interesting" else 20.0 
    }
    if 'update_all_articles_json' in globals(): update_all_articles_json(site_data_entry)
    else: logger.warning("update_all_articles_json not available. Skipping all_articles.json update.")
    
    article_data['audio_url'] = None 
    
    if 'save_processed_data' in globals() and save_processed_data(processed_file_path, article_data):
        logger.info(f"--- Successfully processed ADVANCED manual article: {article_id} ---")
        return True
    else: logger.error(f"Failed to save final processed JSON for {article_id}."); return False


if __name__ == "__main__":
    logger.info("--- ADVANCED Manual Article Submitter ---")
    logger.info("Submits a URL for processing. Importance (Breaking/Interesting) is asked.")
    logger.info("Topic and primary keyword are AI-derived. Limited research snippets (conceptual).")
    
    while True:
        article_url_input = input("\nEnter article URL (or 'exit'): ").strip()
        if article_url_input.lower() == 'exit': break
        if not (article_url_input.startswith('http://') or article_url_input.startswith('https://')):
            logger.error("Invalid URL format."); continue

        if process_advanced_manual_submission(article_url_input):
            logger.info(f"ADVANCED processing complete for: {article_url_input}")
            
            # Check if main's sitemap components are available before trying to use them
            # For sitemap generation, it's better to rely on the main scheduled task
            # or a separate dedicated script for sitemap generation to avoid partial sitemaps
            # if this manual script is run intermittently.
            logger.info("Manual submission complete. Sitemap will be updated by the next scheduled run or manual sitemap generation.")

        else:
            logger.error(f"ADVANCED processing failed for: {article_url_input}")

    logger.info("--- ADVANCED Manual Article Submitter Finished ---")