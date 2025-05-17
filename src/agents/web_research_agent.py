# src/agents/web_research_agent.py (1/1)

import os
import sys
import json
import logging
import requests 
from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from datetime import datetime, timezone, timedelta
import time 
import re 
from urllib.parse import urlparse, urljoin

try:
    from duckduckgo_search import DDGS
except ImportError:
    DDGS = None
    logging.warning("duckduckgo_search library not found. Web search functionality will be limited. pip install -U duckduckgo_search")

try:
    import trafilatura
except ImportError:
    trafilatura = None
    logging.warning("Trafilatura library not found. Advanced content extraction will be limited. pip install trafilatura")

try:
    import htmldate
except ImportError:
    htmldate = None
    logging.warning("htmldate library not found. Precise article date extraction will be limited. pip install htmldate")


# --- Path Setup ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)
# --- End Path Setup ---

# --- Setup Logging ---
logger = logging.getLogger(__name__)
if not logger.handlers: 
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)] 
    )
logger.setLevel(logging.DEBUG) 

# --- Configuration ---
DEEPSEEK_API_KEY_WR = os.getenv('DEEPSEEK_API_KEY') 
DEEPSEEK_CHAT_API_URL_WR = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL_FOR_QUERY = "deepseek-chat" 

MAX_SEARCH_RESULTS_PER_QUERY = 7 
MAX_QUERIES_PER_TOPIC = 2 
ARTICLE_FETCH_TIMEOUT_SECONDS = 25 
MIN_SCRAPED_TEXT_LENGTH = 350 
API_TIMEOUT_QUERY_GEN = 75 
DDG_TIME_FILTER = "d" 
MAX_ARTICLE_AGE_HOURS = 40 
MIN_HTML_CONTENT_LENGTH_FOR_PROCESSING = 500 # New: min length for htmldate/trafilatura

# --- Agent Prompts ---
QUERY_GENERATION_SYSTEM_MESSAGE_WR = "You are an ASI-level Search Query Strategist. Your goal is to generate highly effective, diverse search queries to uncover the *absolute latest (within hours if possible, definitely within 1-2 days)*, most significant, and in-depth news, analyses, and primary source announcements for the given topic. Think about breaking developments, expert discussions, and official releases. Respond ONLY with a JSON list of query strings."
QUERY_GENERATION_USER_TEMPLATE_WR = """
Topic: {topic}

Generate {num_queries} distinct search queries. Prioritize queries that would yield:
1.  Breaking news and official announcements (e.g., from company blogs, press releases, major news outlets).
2.  In-depth technical analysis or expert commentary on recent developments.
3.  Novel insights or high-signal information not yet widely reported.

Queries should incorporate terms implying extreme recency (e.g., "latest hours," "breaking now," "just announced," specific current event tie-ins if relevant for the topic) and specificity. Avoid generic queries.

Output ONLY a JSON list of strings. Example:
{{
  "queries": ["{topic} breaking update today", "{topic} new architecture details announcement", "expert analysis {topic} impact latest hours"]
}}
"""

def call_deepseek_for_queries(topic, num_queries=MAX_QUERIES_PER_TOPIC):
    if not DEEPSEEK_API_KEY_WR: logger.error("DS_KEY_WR missing."); return None
    user_prompt = QUERY_GENERATION_USER_TEMPLATE_WR.format(topic=topic, num_queries=num_queries)
    payload = {"model": DEEPSEEK_MODEL_FOR_QUERY, "messages": [{"role": "system", "content": QUERY_GENERATION_SYSTEM_MESSAGE_WR}, {"role": "user", "content": user_prompt}], "temperature": 0.6, "response_format": {"type": "json_object"}}
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY_WR}", "Content-Type": "application/json"}
    try:
        logger.debug(f"DS Query Gen for: {topic}")
        response = requests.post(DEEPSEEK_CHAT_API_URL_WR, headers=headers, json=payload, timeout=API_TIMEOUT_QUERY_GEN)
        response.raise_for_status(); response_json = response.json()
        if response_json.get("choices") and response_json["choices"][0].get("message") and response_json["choices"][0]["message"].get("content"):
            generated_json_string = response_json["choices"][0]["message"]["content"]
            try:
                parsed_response = json.loads(generated_json_string)
                queries = None
                if "queries" in parsed_response and isinstance(parsed_response["queries"], list): queries = [q for q in parsed_response["queries"] if isinstance(q, str)]
                elif isinstance(parsed_response, list): queries = [q for q in parsed_response if isinstance(q, str)]
                if queries: logger.info(f"DS Queries for '{topic}': {queries[:num_queries]}"); return queries[:num_queries]
                else: logger.error(f"DS query list not found in: {parsed_response}"); return None
            except Exception as e: logger.error(f"DS query JSON decode error: {e} from '{generated_json_string}'"); return None
        else: logger.error(f"DS query response malformed: {response_json}"); return None
    except Exception as e: logger.error(f"DS query API error: {e}"); return None

def search_web_ddg(query, num_results=MAX_SEARCH_RESULTS_PER_QUERY):
    if not DDGS: logger.error("DDGS not available."); return []
    search_results = []
    try:
        logger.info(f"DDG: '{query}' (max {num_results}, time: {DDG_TIME_FILTER})")
        ddgs_instance = DDGS(timeout=20) 
        results = list(ddgs_instance.text(query, max_results=num_results, region='wt-wt', safesearch='moderate', timelimit=DDG_TIME_FILTER)) 
        for r in results:
            if r.get('href') and r.get('title'): search_results.append({'url': r['href'], 'title': r['title']})
        logger.debug(f"DDG found {len(search_results)} results for '{query}'.")
    except Exception as e: logger.error(f"DDG search error for '{query}': {e}")
    return search_results

def get_precise_publish_date(html_content, url_for_log=""):
    if not htmldate and not BeautifulSoup : return None 
    
    parsed_date = None
    if htmldate:
        try:
            parsed_date_str = htmldate.find_date(html_content, url=url_for_log, extensive_search=True, original_date=True)
            if parsed_date_str:
                try: 
                    parsed_date = datetime.fromisoformat(parsed_date_str.replace('Z', '+00:00'))
                    if parsed_date.tzinfo is None: parsed_date = parsed_date.replace(tzinfo=timezone.utc)
                    logger.debug(f"htmldate found: {parsed_date_str} for {url_for_log}")
                    return parsed_date
                except ValueError:
                    logger.debug(f"htmldate found string '{parsed_date_str}' but couldn't parse to datetime robustly.")
        except Exception as e:
            logger.debug(f"htmldate error for {url_for_log}: {e}")

    if not parsed_date and BeautifulSoup:
        try:
            soup = BeautifulSoup(html_content, 'lxml') # Use lxml
            meta_date_selectors = [
                {'property': 'article:published_time'}, {'name': 'cXenseParse:recs:publishtime'},
                {'name': 'pubdate'}, {'name': 'publishdate'}, {'name': 'timestamp'},
                {'itemprop': 'datePublished'}, {'name': 'sailthru.date'}, {'name': 'article.published'},
                {'name': 'article_date_original'}, {'name': 'date'}
            ]
            for selector in meta_date_selectors:
                tag = soup.find('meta', attrs=selector)
                if tag and tag.get('content'):
                    date_str_meta = tag['content'].strip()
                    try:
                        parsed_date = datetime.fromisoformat(date_str_meta.replace('Z', '+00:00'))
                        if parsed_date.tzinfo is None: parsed_date = parsed_date.replace(tzinfo=timezone.utc)
                        logger.debug(f"Meta tag {selector} found date: {date_str_meta} for {url_for_log}")
                        return parsed_date
                    except ValueError:
                        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M:%S', '%a, %d %b %Y %H:%M:%S %z'): 
                            try: 
                                parsed_date = datetime.strptime(date_str_meta, fmt)
                                if parsed_date.tzinfo is None: parsed_date = parsed_date.replace(tzinfo=timezone.utc) 
                                return parsed_date
                            except ValueError: continue
                        logger.debug(f"Could not parse date string '{date_str_meta}' from meta tag for {url_for_log}")
            time_tag = soup.find('time', attrs={'datetime': True})
            if time_tag and time_tag['datetime']:
                 date_str_time_tag = time_tag['datetime'].strip()
                 try:
                    parsed_date = datetime.fromisoformat(date_str_time_tag.replace('Z', '+00:00'))
                    if parsed_date.tzinfo is None: parsed_date = parsed_date.replace(tzinfo=timezone.utc)
                    return parsed_date
                 except ValueError: pass
        except Exception as e_bs_date:
            logger.debug(f"BeautifulSoup date parsing error for {url_for_log}: {e_bs_date}")
            
    return None

def clean_text_advanced(text):
    if not text: return ""
    text = re.sub(r'\s*\n\s*', '\n', text) 
    text = re.sub(r'([^\n])\n([^\n])', r'\1 \2', text) 
    text = re.sub(r'\n{3,}', '\n\n', text) 
    text = re.sub(r'For more information, contact:.*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Image credit:.*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Photo by .* on Unsplash', '', text, flags=re.IGNORECASE)
    return text.strip()

def scrape_article_content(url):
    logger.info(f"Advanced scraping attempt for URL: {url}")
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1', 'Upgrade-Insecure-Requests': '1', 'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Site': 'none', 'Sec-Fetch-User': '?1',
            'Referer': 'https://www.google.com/'
        }
        response = requests.get(url, headers=headers, timeout=ARTICLE_FETCH_TIMEOUT_SECONDS, allow_redirects=True)
        response.raise_for_status()
        content_type = response.headers.get('Content-Type', '').lower()
        if 'html' not in content_type: logger.warning(f"Not HTML ({content_type}): {url}"); return None, None
        
        html_content = response.text
        if len(html_content) < MIN_HTML_CONTENT_LENGTH_FOR_PROCESSING:
            logger.warning(f"HTML content too short ({len(html_content)} chars) for {url}. Skipping detailed processing.")
            return None, None # Or attempt date parsing if that's critical even for short pages

        publish_date_parsed = get_precise_publish_date(html_content, url)

        if trafilatura:
            try:
                extracted_text_traf = trafilatura.extract(html_content, include_comments=False, include_tables=True, output_format='txt', deduplicate=True, favor_recall=True, date_extraction_params={'extensive_search': True, 'original_date': True})
                if extracted_text_traf and len(extracted_text_traf.strip()) >= MIN_SCRAPED_TEXT_LENGTH:
                    logger.info(f"Trafilatura successful for {url} (Length: {len(extracted_text_traf.strip())})")
                    return clean_text_advanced(extracted_text_traf.strip()), publish_date_parsed
                logger.debug(f"Trafilatura insufficient for {url}, trying BeautifulSoup.")
            except Exception as e_traf: # Catch specific trafilatura errors if it fails internally
                logger.error(f"Trafilatura library error during extraction for {url}: {e_traf}", exc_info=False) # exc_info=False if too verbose
                logger.debug(f"Trafilatura failed for {url}, trying BeautifulSoup as fallback.")


        soup = BeautifulSoup(html_content, 'lxml') 

        selectors_to_remove = [
            'script', 'style', 'noscript', 'iframe', 'form', 'nav', 'footer', 'aside', 'header', 
            '.ad', '#ad', '[class*="advert"]', '[id*="advert"]', '.banner', '#banner', '.popup', '#popup',
            '.cookie', '#cookie', '.sidebar', '#sidebar', '.related', '.comments', '#comments', '.share', 
            '.social', '.footer', '.header', '.menu', '.nav', '.breadcrumb', '.print', '.meta', '.author-bio',
            '.pagination', '.widget', '[role="navigation"]', '[role="banner"]', '[role="complementary"]', 
            '[role="contentinfo"]', '[role="search"]', '[aria-hidden="true"]', 'figcaption', 'figure > div:not(:has(img))'
        ]
        for selector in selectors_to_remove:
            for element in soup.select(selector): element.decompose()
        for comment_tag in soup.find_all(string=lambda text: isinstance(text, Comment)): comment_tag.extract()

        candidate_containers = soup.select(
            'article, main, [role="main"], div[class*="content"], div[id*="content"], div[class*="post"], div[id*="post"], div[class*="story"], div[id*="story"], div[class*="article"], div[id*="article"]'
        )
        best_text_content = ""
        if not candidate_containers: candidate_containers = [soup.body] if soup.body else []

        for container in candidate_containers:
            if not isinstance(container, Tag): continue
            
            links_count = len(container.find_all('a', recursive=False)) 
            direct_text_len = len(container.get_text(separator=' ', strip=True))
            
            if links_count > 10 and direct_text_len / (links_count + 1) < 50 : 
                 logger.debug(f"Skipping container for high link density: {container.name}#{container.get('id','')} .{container.get('class','')}")
                 continue

            content_blocks = []
            for element in container.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'blockquote', 'pre', 'td', 'th']):
                if not isinstance(element, Tag): continue
                block_text = element.get_text(separator=' ', strip=True)
                if len(block_text) < 25 and not element.find_all(['img', 'video', 'code']): 
                    parent = element.parent
                    if parent and parent.name in ['ul', 'ol'] and len(parent.find_all('li', recursive=False)) <=3: 
                        pass 
                    else:
                        continue 
                content_blocks.append(block_text)
            
            current_container_text = "\n\n".join(content_blocks).strip()
            if len(current_container_text) > len(best_text_content):
                best_text_content = current_container_text
        
        if len(best_text_content) >= MIN_SCRAPED_TEXT_LENGTH:
            logger.info(f"BeautifulSoup advanced extraction for {url} (Length: {len(best_text_content)})")
            return clean_text_advanced(best_text_content), publish_date_parsed
        
        logger.warning(f"All scraping methods failed for {url}.")
        return None, publish_date_parsed

    except requests.exceptions.Timeout: logger.warning(f"Timeout fetching content from {url}")
    except requests.exceptions.RequestException as e: logger.warning(f"Request failed for {url}: {e}")
    except Exception as e: logger.error(f"Unexpected error scraping {url}: {e}", exc_info=True) 
    return None, None


def run_web_research_agent(topics_of_interest, preferred_domains=None):
    logger.info(f"--- Starting ADVANCED Web Research Agent for topics: {topics_of_interest} ---")
    all_found_articles_data = []
    processed_urls_this_run = set()
    time_threshold_utc = datetime.now(timezone.utc) - timedelta(hours=MAX_ARTICLE_AGE_HOURS)

    for topic in topics_of_interest:
        logger.info(f"Researching topic: {topic}")
        generated_queries = call_deepseek_for_queries(topic, num_queries=MAX_QUERIES_PER_TOPIC) 
        if not generated_queries: logger.warning(f"No queries for '{topic}'. Skipping."); continue

        for query_idx, query in enumerate(generated_queries):
            if not query.strip(): continue
            logger.info(f"Executing query ({query_idx+1}/{len(generated_queries)}): '{query}' for topic '{topic}'")
            search_hits = search_web_ddg(query, num_results=MAX_SEARCH_RESULTS_PER_QUERY) 

            for hit in search_hits:
                url = hit.get('url')
                title_from_search = hit.get('title', 'No Title Provided by Search')
                if not url or urlparse(url).scheme not in ['http', 'https'] or url in processed_urls_this_run:
                    logger.debug(f"Skipping invalid/duplicate URL: {url}"); continue
                processed_urls_this_run.add(url)
                
                scraped_text_content, precise_publish_date = scrape_article_content(url)
                retrieved_at_dt = datetime.now(timezone.utc) 

                effective_publish_date = precise_publish_date if precise_publish_date else retrieved_at_dt
                
                if effective_publish_date < time_threshold_utc:
                    logger.info(f"Skipping old article (EffectiveDate: {effective_publish_date.strftime('%Y-%m-%d %H:%M')}, Threshold: {time_threshold_utc.strftime('%Y-%m-%d %H:%M')}): {title_from_search} from {url}")
                    continue

                if scraped_text_content:
                    try: domain = urlparse(url).netloc.replace('www.', '')
                    except: domain = "unknown_domain"
                    all_found_articles_data.append({
                        'url': url, 'title': title_from_search, 'scraped_text': scraped_text_content, 
                        'source_domain': domain, 'research_topic': topic, 
                        'retrieved_at': retrieved_at_dt.isoformat(),
                        'parsed_publish_date_iso': precise_publish_date.isoformat() if precise_publish_date else None
                    })
                    logger.info(f"Successfully scraped & added recent article: '{title_from_search}' from {url}")
                else: logger.warning(f"Failed to scrape sufficient content for recent: '{title_from_search}' from {url}")
            if query_idx < len(generated_queries) - 1 : time.sleep(5) 
    
    logger.info(f"--- ADVANCED Web Research Agent finished. Found {len(all_found_articles_data)} recent & relevant articles. ---")
    return all_found_articles_data

if __name__ == "__main__":
    if not logging.getLogger(__name__).handlers:
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
                            format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')

    if not DEEPSEEK_API_KEY_WR:
        logger.error("DEEPSEEK_API_KEY not set. Test aborted.")
        sys.exit(1)

    sample_topics = ["latest breakthroughs NVIDIA AI chips", "OpenAI Sora model real-time updates"]
    logger.info(f"Starting ADVANCED web_research_agent.py standalone test (DeepSeek & DDG time filter {DDG_TIME_FILTER})...")
    found_articles = run_web_research_agent(sample_topics)

    if found_articles:
        logger.info(f"\n--- ADVANCED Web Research Test Results ({len(found_articles)} articles found) ---")
        for i, article in enumerate(found_articles):
            logger.info(f"Article {i+1}:")
            logger.info(f"  Topic: {article.get('research_topic')}")
            logger.info(f"  Title: {article.get('title')}")
            logger.info(f"  URL: {article.get('url')}")
            logger.info(f"  Parsed Publish Date: {article.get('parsed_publish_date_iso', 'N/A')}")
            logger.info(f"  Scraped Text Length: {len(article.get('scraped_text', ''))}")
            logger.info("-" * 20)
    else: logger.info("ADVANCED Web Research Test: No articles were found or scraped successfully.")
    logger.info("--- ADVANCED web_research_agent.py standalone test finished. ---")