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
from urllib.parse import urlparse # <<< --- THIS WAS MISSING, NOW ADDED BACK

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
OLLAMA_API_URL = "http://localhost:11434/api/generate" 
OLLAMA_QUERY_MODEL = "mistral:latest" 
MAX_SEARCH_RESULTS_PER_QUERY = 5 
MAX_QUERIES_PER_TOPIC = 3
ARTICLE_FETCH_TIMEOUT_SECONDS = 15
MIN_SCRAPED_TEXT_LENGTH = 200 

# --- Agent Prompts ---
QUERY_GENERATION_PROMPT_TEMPLATE = """
You are an expert search query generator. Given the following topic, generate {num_queries} diverse and effective search queries that would help find the latest and most relevant news articles and in-depth information about it.
Focus on queries that target recent developments, key players, and significant events.
Output ONLY a JSON list of strings, where each string is a search query. Example: ["query 1", "query 2", "query 3"]

Topic: {topic}
"""

def call_ollama_for_queries(topic, num_queries=MAX_QUERIES_PER_TOPIC):
    """Generates search queries for a given topic using a local Ollama LLM."""
    prompt = QUERY_GENERATION_PROMPT_TEMPLATE.format(topic=topic, num_queries=num_queries)
    payload = {
        "model": OLLAMA_QUERY_MODEL,
        "prompt": prompt,
        "format": "json", 
        "stream": False
    }
    try:
        logger.debug(f"Sending query generation request to Ollama for topic: {topic}")
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=90) # Increased timeout
        response.raise_for_status()
        
        response_json = response.json()
        generated_json_string = response_json.get("response")

        if not generated_json_string:
            logger.error(f"Ollama query generation response missing 'response' field or empty: {response_json}")
            return None

        queries = None
        try:
            parsed_response = json.loads(generated_json_string)
            if isinstance(parsed_response, list) and all(isinstance(q, str) for q in parsed_response):
                queries = parsed_response
            elif isinstance(parsed_response, dict): 
                queries = [q_text for q_text in parsed_response.values() if isinstance(q_text, str)]
                if not queries: 
                    if "queries" in parsed_response and isinstance(parsed_response["queries"], list):
                         queries = [q for q in parsed_response["queries"] if isinstance(q, str)]
            
            if queries:
                logger.info(f"Ollama generated queries for '{topic}': {queries[:num_queries]}")
                return queries[:num_queries] 
            else:
                logger.error(f"Ollama response parsed but no valid query list found: {parsed_response}")
                if "[" in generated_json_string and "]" in generated_json_string:
                    logger.debug(f"Attempting fallback list extraction for: {generated_json_string}")
                    try:
                        match = re.search(r'(\[.*?\])', generated_json_string.replace('\\n', ''))
                        if match:
                            extracted_list_str = match.group(1)
                            extracted_list_str = re.sub(r',\s*\]', ']', extracted_list_str)
                            temp_queries = json.loads(extracted_list_str)
                            if isinstance(temp_queries, list) and all(isinstance(q, str) for q in temp_queries):
                                logger.info(f"Ollama fallback list extraction successful: {temp_queries[:num_queries]}")
                                return temp_queries[:num_queries]
                    except Exception as e_fallback_list:
                        logger.error(f"Fallback list extraction also failed: {e_fallback_list}")
                return None

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to decode JSON directly from Ollama query response: {generated_json_string}. Error: {e}. Trying fallback extraction.")
            match = re.search(r'```json\s*(\[[\s\S]*?\])\s*```', generated_json_string, re.DOTALL)
            if match:
                try:
                    queries = json.loads(match.group(1))
                    if isinstance(queries, list) and all(isinstance(q, str) for q in queries):
                        logger.info(f"Ollama fallback JSON list extraction successful for queries: {queries[:num_queries]}")
                        return queries[:num_queries]
                except Exception as ext_e:
                     logger.error(f"Fallback JSON list extraction also failed: {ext_e}")
            
            if "[" in generated_json_string and "]" in generated_json_string: 
                try:
                    extracted_list_str = generated_json_string[generated_json_string.find("[") : generated_json_string.rfind("]") + 1]
                    extracted_list_str = re.sub(r'(?<!\\)"?([^"\n\[\],]+)"?', r'"\1"', extracted_list_str) 
                    extracted_list_str = extracted_list_str.replace("'", '"') 
                    
                    queries = json.loads(extracted_list_str)
                    if isinstance(queries, list) and all(isinstance(q, str) for q in queries):
                        logger.info(f"Ollama fallback (string manipulation) successful for queries: {queries[:num_queries]}")
                        return queries[:num_queries]
                except Exception as e_fallback_str:
                    logger.error(f"Final fallback query extraction (string manipulation) also failed: {e_fallback_str}")
            logger.error(f"Could not parse queries from Ollama response: {generated_json_string}")
            return None

    except requests.exceptions.RequestException as e:
        logger.error(f"Ollama API request for query generation failed: {e}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error in call_ollama_for_queries: {e}")
        return None


def search_web_ddg(query, num_results=MAX_SEARCH_RESULTS_PER_QUERY):
    """Performs a web search using DuckDuckGo and returns URLs and titles."""
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
    """Scrapes the main content from a given URL."""
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
        generated_queries = call_ollama_for_queries(topic)

        if not generated_queries:
            logger.warning(f"No search queries generated by Ollama for topic '{topic}'. Skipping topic.")
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
                    # Correctly use urlparse here
                    domain = urlparse(url).netloc.replace('www.', '')
                except Exception as e_parse: # Catch potential errors during parsing
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

    sample_topics = [
        "latest breakthroughs in AI model architectures",
        "Nvidia Blackwell GPU impact on AI training"
    ]
    
    logger.info("Starting web_research_agent.py standalone test...")
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
        output_test_file = os.path.join(test_data_dir, "web_research_test_output.json")
        
        with open(output_test_file, "w", encoding="utf-8") as f:
            json.dump(found_articles, f, indent=2, ensure_ascii=False)
        logger.info(f"Test output saved to {output_test_file}")
    else:
        logger.info("Web Research Agent Test: No articles were found or scraped successfully.")
    logger.info("--- web_research_agent.py standalone test finished. ---")