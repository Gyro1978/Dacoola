# src/agents/web_research_agent.py

import os
import sys
import json
import logging
import requests 
from bs4 import BeautifulSoup, Comment
from datetime import datetime 
import time 
import re 
from urllib.parse import urlparse

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
DEEPSEEK_API_KEY_WR = os.getenv('DEEPSEEK_API_KEY') # WR for Web Research
DEEPSEEK_CHAT_API_URL_WR = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL_FOR_QUERY = "deepseek-chat" # Using chat model for query generation

MAX_SEARCH_RESULTS_PER_QUERY = 5 
MAX_QUERIES_PER_TOPIC = 3
ARTICLE_FETCH_TIMEOUT_SECONDS = 15
MIN_SCRAPED_TEXT_LENGTH = 200
API_TIMEOUT_QUERY_GEN = 60

# --- Agent Prompts ---
QUERY_GENERATION_SYSTEM_MESSAGE_WR = "You are an expert search query generator. Generate diverse and effective search queries for the given topic. Respond ONLY with a JSON list of strings."
QUERY_GENERATION_USER_TEMPLATE_WR = """
Topic: {topic}
Generate {num_queries} search queries to find the latest and most relevant news articles and in-depth information about this topic.
Focus on recent developments, key players, and significant events.
Output ONLY a JSON list of strings, where each string is a search query. Example: ["query 1", "query 2", "query 3"]
"""

def call_deepseek_for_queries(topic, num_queries=MAX_QUERIES_PER_TOPIC):
    """Generates search queries for a given topic using DeepSeek API."""
    if not DEEPSEEK_API_KEY_WR:
        logger.error("DEEPSEEK_API_KEY not found. Cannot call DeepSeek API for query generation.")
        return None

    user_prompt = QUERY_GENERATION_USER_TEMPLATE_WR.format(topic=topic, num_queries=num_queries)
    
    payload = {
        "model": DEEPSEEK_MODEL_FOR_QUERY,
        "messages": [
            {"role": "system", "content": QUERY_GENERATION_SYSTEM_MESSAGE_WR},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.7, # Higher temperature for more diverse queries
        "response_format": {"type": "json_object"} 
    }
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY_WR}",
        "Content-Type": "application/json"
    }

    try:
        logger.debug(f"Sending query generation request to DeepSeek for topic: {topic}")
        response = requests.post(DEEPSEEK_CHAT_API_URL_WR, headers=headers, json=payload, timeout=API_TIMEOUT_QUERY_GEN)
        response.raise_for_status()
        
        response_json = response.json()
        
        if response_json.get("choices") and response_json["choices"][0].get("message") and response_json["choices"][0]["message"].get("content"):
            generated_json_string = response_json["choices"][0]["message"]["content"]
            try:
                # DeepSeek might return a dict with a key like "queries" or just a list directly
                parsed_response = json.loads(generated_json_string)
                queries = None
                if isinstance(parsed_response, list) and all(isinstance(q, str) for q in parsed_response):
                    queries = parsed_response
                elif isinstance(parsed_response, dict):
                    # Try common keys for a list of queries
                    for key in ["queries", "search_queries", "generated_queries", "query_list"]:
                        if key in parsed_response and isinstance(parsed_response[key], list):
                            queries = [q for q in parsed_response[key] if isinstance(q, str)]
                            break
                    if not queries: # If no specific key, check if dict values are strings (less ideal)
                        queries = [val for val in parsed_response.values() if isinstance(val, str)]
                
                if queries:
                    logger.info(f"DeepSeek generated queries for '{topic}': {queries[:num_queries]}")
                    return queries[:num_queries]
                else:
                    logger.error(f"DeepSeek response parsed but no valid query list found: {parsed_response}")
                    return None

            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode JSON from DeepSeek query response: {generated_json_string}. Error: {e}")
                # Fallback: try to extract a list-like string if response_format failed
                match_list = re.search(r'\[\s*".*?"\s*(?:,\s*".*?"\s*)*\]', generated_json_string)
                if match_list:
                    try:
                        queries = json.loads(match_list.group(0))
                        if isinstance(queries, list) and all(isinstance(q, str) for q in queries):
                            logger.info(f"DeepSeek query gen (regex fallback) successful for '{topic}': {queries[:num_queries]}")
                            return queries[:num_queries]
                    except Exception as fallback_e:
                        logger.error(f"DeepSeek query gen regex fallback failed: {fallback_e}")
                return None
        else:
            logger.error(f"DeepSeek query generation response missing expected content: {response_json}")
            return None
            
    except requests.exceptions.RequestException as e:
        logger.error(f"DeepSeek API request for query generation failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"DeepSeek API Response Content: {e.response.text}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error in call_deepseek_for_queries: {e}")
        return None


def search_web_ddg(query, num_results=MAX_SEARCH_RESULTS_PER_QUERY):
    if not DDGS:
        logger.error("DDGS (duckduckgo_search) is not available. Cannot perform web search.")
        return []
    
    search_results = []
    try:
        logger.info(f"Searching DDG for: '{query}' (max {num_results} results)")
        ddgs_instance = DDGS() 
        results = list(ddgs_instance.text(query, max_results=num_results, region='wt-wt', safesearch='moderate')) 
        
        for r in results:
            if r.get('href') and r.get('title'):
                search_results.append({'url': r['href'], 'title': r['title']})
        logger.debug(f"DDG found {len(search_results)} results for '{query}'.")
    except Exception as e:
        logger.error(f"Error during DuckDuckGo search for '{query}': {e}")
    return search_results


def scrape_article_content(url):
    try:
        headers = { 
            'User-Agent': 'Mozilla/5.0 (compatible; DacoolaWebResearchBot/1.0; +https://dacoolaa.netlify.app)',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        logger.debug(f"Attempting to fetch content from URL: {url}")
        response = requests.get(url, headers=headers, timeout=ARTICLE_FETCH_TIMEOUT_SECONDS, allow_redirects=True)
        response.raise_for_status() 

        content_type = response.headers.get('Content-Type', '').lower()
        if 'html' not in content_type:
            logger.warning(f"Content from {url} is not HTML ({content_type}). Skipping full scrape.")
            return None

        html_content = response.text

        if trafilatura:
            logger.debug(f"Attempting Trafilatura extraction for {url}")
            extracted_text = trafilatura.extract(
                html_content,
                include_comments=False,
                include_tables=False, 
                output_format='txt',
                deduplicate=True
            )
            if extracted_text and len(extracted_text.strip()) >= MIN_SCRAPED_TEXT_LENGTH:
                logger.info(f"Trafilatura extracted content from {url} (Length: {len(extracted_text.strip())})")
                return extracted_text.strip()
            logger.debug(f"Trafilatura extracted insufficient text from {url}. Length: {len(extracted_text.strip() if extracted_text else '')}")
        
        logger.debug(f"Falling back to BeautifulSoup for {url}")
        soup = BeautifulSoup(html_content, 'html.parser')
        
        for comment_tag in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment_tag.extract()

        tags_to_remove = ['script', 'style', 'nav', 'footer', 'aside', 'header', 'form', 'button', 'input',
                          '.related-posts', '.comments', '.sidebar', '.ad', '.banner', '.share-buttons',
                          '.newsletter-signup', '.cookie-banner', '.site-header', '.site-footer',
                          '.navigation', '.menu', '.social-links', '.author-bio', '.pagination',
                          '#comments', '#sidebar', '#header', '#footer', '#navigation', '.print-button',
                          '.breadcrumbs', 'figcaption', 'figure > div']
        for selector in tags_to_remove:
            for element in soup.select(selector):
                element.decompose()
        
        main_content_selectors = ['article[class*="content"]', 'article[class*="post"]', 'article[class*="article"]',
                                  'main[id*="content"]', 'main[class*="content"]', 'div[class*="article-body"]',
                                  'div[class*="post-body"]', 'div[class*="entry-content"]', 'div[class*="story-content"]',
                                  'div[id*="article"]', 'div#content', 'div#main', '.article-content']
        best_text = ""
        for selector in main_content_selectors:
            element = soup.select_one(selector)
            if element:
                text_parts = []
                for child in element.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'li', 'blockquote', 'pre']):
                    if child.name == 'p' and child.find('a') and len(child.find_all(text=True, recursive=False)) == 0 and len(child.find_all('a')) == 1:
                        link_text = child.find('a').get_text(strip=True)
                        if link_text and len(link_text) > 20: text_parts.append(link_text)
                        continue
                    text_parts.append(child.get_text(separator=' ', strip=True))
                current_text = "\n\n".join(filter(None, text_parts)).strip()
                if len(current_text) > len(best_text): best_text = current_text
        
        if best_text and len(best_text) >= MIN_SCRAPED_TEXT_LENGTH:
            logger.info(f"BS (selector strategy) extracted from {url} (Length: {len(best_text)})")
            return best_text
        
        body = soup.find('body')
        if body:
            content_text = ""
            paragraphs = body.find_all('p')
            if paragraphs:
                 text_parts = [p.get_text(separator=' ', strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 50]
                 content_text = "\n\n".join(filter(None, text_parts)).strip()
            if content_text and len(content_text) >= MIN_SCRAPED_TEXT_LENGTH:
                logger.info(f"BS (aggressive fallback) extracted from {url} (Length: {len(content_text)})")
                return content_text
        logger.warning(f"BS fallback failed for {url} after all attempts.")
        return None

    except requests.exceptions.Timeout:
        logger.warning(f"Timeout fetching content from {url}")
    except requests.exceptions.RequestException as e:
        logger.warning(f"Request failed for {url}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error scraping {url}: {e}", exc_info=True) 
    return None


def run_web_research_agent(topics_of_interest, preferred_domains=None):
    logger.info(f"--- Starting Web Research Agent for topics: {topics_of_interest} ---")
    all_found_articles_data = []
    processed_urls_this_run = set()

    for topic in topics_of_interest:
        logger.info(f"Researching topic: {topic}")
        generated_queries = call_deepseek_for_queries(topic) # Changed function call

        if not generated_queries:
            logger.warning(f"No search queries generated for topic '{topic}'. Skipping topic.")
            continue

        for query in generated_queries:
            if not query.strip():
                continue
            
            logger.info(f"Executing search query: '{query}' for topic '{topic}'")
            search_hits = search_web_ddg(query, num_results=MAX_SEARCH_RESULTS_PER_QUERY)

            for hit in search_hits:
                url = hit.get('url')
                title = hit.get('title', 'No Title')

                if not url or url in processed_urls_this_run:
                    logger.debug(f"Skipping already processed or invalid URL: {url}")
                    continue
                
                processed_urls_this_run.add(url)
                
                try:
                    domain = urlparse(url).netloc.replace('www.', '')
                except Exception as e_parse: 
                    logger.warning(f"Could not parse domain from URL {url}: {e_parse}")
                    domain = "unknown_domain"

                scraped_text_content = scrape_article_content(url)

                if scraped_text_content:
                    all_found_articles_data.append({
                        'url': url,
                        'title': title,
                        'scraped_text': scraped_text_content, 
                        'source_domain': domain,
                        'research_topic': topic, 
                        'retrieved_at': datetime.now().isoformat() 
                    })
                    logger.info(f"Successfully scraped and added: '{title}' from {url}")
                else:
                    logger.warning(f"Failed to scrape sufficient content for: '{title}' from {url}")
            
            if len(generated_queries) > 1 : 
                 time.sleep(2) 
    
    logger.info(f"--- Web Research Agent finished. Found {len(all_found_articles_data)} potentially useful articles. ---")
    return all_found_articles_data

if __name__ == "__main__":
    if not logging.getLogger(__name__).handlers:
        logging.basicConfig(stream=sys.stdout, level=logging.INFO, 
                            format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')
    logger.setLevel(logging.DEBUG) 

    if not DEEPSEEK_API_KEY_WR:
        logger.error("DEEPSEEK_API_KEY not set in .env. Cannot run standalone test for web_research_agent with DeepSeek.")
        sys.exit(1)

    sample_topics = [
        "latest breakthroughs in AI model architectures",
        "Nvidia Blackwell GPU impact on AI training"
    ]
    
    logger.info("Starting web_research_agent.py standalone test (with DeepSeek)...")
    found_articles = run_web_research_agent(sample_topics)

    if found_articles:
        logger.info(f"\n--- Web Research Agent Test Results ({len(found_articles)} articles found) ---")
        for i, article in enumerate(found_articles):
            logger.info(f"Article {i+1}:")
            logger.info(f"  Topic: {article.get('research_topic')}")
            logger.info(f"  Title: {article.get('title')}")
            logger.info(f"  URL: {article.get('url')}")
            logger.info(f"  Domain: {article.get('source_domain')}")
            logger.info(f"  Scraped Text Length: {len(article.get('scraped_text', ''))}")
            logger.info("-" * 20)
        
        test_data_dir = os.path.join(PROJECT_ROOT, "data")
        os.makedirs(test_data_dir, exist_ok=True)
        output_test_file = os.path.join(test_data_dir, "web_research_test_output_deepseek.json")
        
        with open(output_test_file, "w", encoding="utf-8") as f:
            json.dump(found_articles, f, indent=2, ensure_ascii=False)
        logger.info(f"Test output saved to {output_test_file}")
    else:
        logger.info("Web Research Agent Test: No articles were found or scraped successfully.")
    logger.info("--- web_research_agent.py standalone test finished. ---")