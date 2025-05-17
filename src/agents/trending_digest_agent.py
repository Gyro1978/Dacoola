# src/agents/trending_digest_agent.py

import os
import sys
import json
import logging
import requests # For Ollama
import re
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urljoin, quote # For links in digest

# --- Path Setup ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# For site base URL, needed for constructing full URLs in digest
from dotenv import load_dotenv
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)
YOUR_SITE_BASE_URL_FOR_DIGEST = os.getenv('YOUR_SITE_BASE_URL', 'https://yoursite.example.com').rstrip('/')
YOUR_WEBSITE_NAME_FOR_DIGEST = os.getenv('YOUR_WEBSITE_NAME', 'Dacoola')
YOUR_WEBSITE_LOGO_URL_FOR_DIGEST = os.getenv('YOUR_WEBSITE_LOGO_URL', '')
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
# Mixtral is good for summarization, clustering, and generation tasks
OLLAMA_DIGEST_MODEL = "mixtral:latest"
# OLLAMA_DIGEST_MODEL = "llama3:70b" # More powerful, but slower/more resource intensive

MAX_RAW_ARTICLES_FOR_TREND_ANALYSIS = 50 # Analyze up to this many recent raw articles for trends
MIN_KEYWORD_FREQUENCY_FOR_TREND = 3 # A keyword needs to appear in at least this many raw articles to be a trend candidate
NUM_TRENDING_THEMES_TO_GENERATE = 3 # How many digest pages to create
ARTICLES_PER_THEME_IN_DIGEST = 3 # How many articles to feature per theme
MAX_TITLE_LENGTH_FOR_DIGEST_ITEM = 70
MAX_SUMMARY_LENGTH_FOR_DIGEST_ITEM = 150 # Characters for the short summary in the digest

# --- Prompt Templates ---
TREND_IDENTIFICATION_PROMPT = """
You are an expert news analyst tasked with identifying emerging trends from a collection of recent raw article titles and snippets.
Analyze the following list of articles (title and a short snippet of raw text) and identify {num_themes_target} distinct, significant, and currently trending themes or topics.
For each theme, also list the primary keywords that define it. Avoid overly broad themes.

**Article Data (List of Titles and Snippets):**
{article_data_for_trend_analysis}

**Output Format (Strictly JSON):**
Provide a JSON list, where each item is an object representing a theme:
{{
  "trending_themes": [
    {{
      "theme_name": "Example Theme 1: AI in Drug Discovery",
      "defining_keywords": ["drug discovery", "pharmaceutical AI", "medical research models"]
    }},
    {{
      "theme_name": "Example Theme 2: Advancements in Robotics Software",
      "defining_keywords": ["robotics OS", "AI for robot navigation", "collaborative robots software"]
    }}
    // ... up to {num_themes_target} themes
  ]
}}

Identify trending themes now.
"""

DIGEST_PAGE_GENERATION_PROMPT = """
You are an expert content curator and SEO specialist for a tech news website called "{website_name}".
Your task is to generate a "Trending Digest" page for a specific theme. This page will highlight key articles (both internal from our site and potentially important external ones) related to this theme.

**Theme for this Digest:** {theme_name}
**Keywords defining this theme:** {theme_keywords_str}

**Available Articles related to this theme (Internal from our site, and potentially relevant external links):**
{available_articles_str}

**Instructions:**
1.  **Select Top Articles:** From the "Available Articles", select the top {articles_per_theme} most relevant, recent, and impactful articles for this theme. Prioritize variety if possible.
2.  **Digest Page Title:** Create a compelling, SEO-friendly title for this digest page (e.g., "AI in Healthcare: Top {articles_per_theme} Breakthroughs This Week"). Max 70 characters.
3.  **Digest Page Meta Description:** Write a concise meta description (max 160 characters) summarizing the digest's content.
4.  **Digest Introduction:** Write a brief (2-3 sentences) engaging introduction for the digest page, explaining the theme's current significance.
5.  **Article Summaries for Digest:** For each selected article:
    *   Use its provided title (or a slightly shortened version if too long).
    *   Use its provided summary (or generate a new very concise 1-2 sentence summary if the provided one is too long or unsuitable for a digest).
    *   Include its URL.
6.  **JSON-LD for Digest Page:** Create a `WebPage` or `CollectionPage` JSON-LD object for this digest page. Include headline, description, keywords (from theme), and datePublished.

**Output Format (Strictly JSON):**
Provide ONLY a valid JSON object with the following structure:
{{
  "digest_page_title": "string",
  "digest_meta_description": "string",
  "digest_introduction_markdown": "string", // Markdown formatted intro
  "selected_articles_for_digest": [ // Array of {articles_per_theme} articles
    {{
      "title": "string", // Article title (max {max_title_length} chars)
      "url": "string",   // Full URL to the article
      "summary_for_digest": "string", // Concise summary (max {max_summary_length} chars)
      "is_internal": boolean // True if it's an article from our site (YOUR_SITE_BASE_URL), False if external
    }}
  ],
  "digest_page_json_ld_raw": {{ // Raw JSON-LD object for the digest page itself
    "@context": "https://schema.org",
    "@type": "CollectionPage", // Or WebPage
    "headline": "string", // Same as digest_page_title
    "description": "string", // Same as digest_meta_description
    "keywords": ["string1", "string2"], // From theme_keywords_str
    "datePublished": "{current_iso_date}",
    "isPartOf": {{"@type": "WebSite", "url": "{site_base_url}"}},
    "publisher": {{"@type": "Organization", "name": "{website_name}", "logo": {{"@type": "ImageObject", "url": "{website_logo_url}"}}}}
    // Potentially add "hasPart": [{{@type: CreativeWork, url: article_url1}}, ...] for linked items
  }}
}}
"""

# --- Helper Functions ---
def call_ollama_for_digest_tasks(prompt_text, model=OLLAMA_DIGEST_MODEL, expect_json=True):
    payload = {"model": model, "prompt": prompt_text, "stream": False}
    if expect_json:
        payload["format"] = "json"
    
    try:
        logger.debug(f"Sending request to Ollama model {model} for digest task.")
        # Timeout can be longer for complex generation/analysis
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=180)
        response.raise_for_status()
        response_json = response.json()
        content = response_json.get("response", "")

        if expect_json:
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                logger.error(f"Ollama returned non-JSON for a JSON-formatted digest request: {content[:200]}...")
                # Try to extract JSON if wrapped by LLM
                match = re.search(r'```json\s*(\{[\s\S]*?\}|\[[\s\S]*?\])\s*```', content, re.DOTALL)
                if match:
                    try: return json.loads(match.group(1))
                    except: pass
                return None # Failed to get JSON
        return content.strip() # Return text if not JSON formatted request
    except requests.exceptions.RequestException as e:
        logger.error(f"Ollama API request failed for digest task: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error in call_ollama_for_digest_tasks: {e}")
    return None

def extract_keywords_from_raw_articles(raw_articles_list):
    """Basic keyword extraction from titles of raw articles to find trend candidates."""
    all_words = []
    stopwords = set(["the", "a", "an", "is", "are", "was", "were", "and", "or", "of", "to", "in", "it", "for", "on", "with", "this", "that", "new", "news", "ai", "tech"]) # Basic stopwords
    
    for article in raw_articles_list:
        title = article.get('title', '').lower()
        # Simple tokenization: split by non-alphanum, keep words > 2 chars
        words = re.findall(r'\b[a-z]{3,}\b', title)
        for word in words:
            if word not in stopwords:
                all_words.append(word)
    
    if not all_words: return []
    
    # Count word frequencies
    word_counts = Counter(all_words)
    # Consider frequent words/bigrams as potential trend keywords
    # This is very basic; LLM will do the proper theme clustering.
    # For this basic version, let's just return frequent single words.
    trend_candidates = [word for word, count in word_counts.most_common(30) if count >= MIN_KEYWORD_FREQUENCY_FOR_TREND]
    logger.debug(f"Initial trend keyword candidates from raw titles: {trend_candidates}")
    return trend_candidates


def slugify_digest_title(title_text):
    if not title_text: return f"digest-{datetime.now().strftime('%Y%m%d')}"
    s = str(title_text).strip().lower()
    s = re.sub(r'[^\w\s-]', '', s)
    s = re.sub(r'[-\s]+', '-', s)
    return s[:75]

# --- Main Agent Function ---
def run_trending_digest_agent(raw_articles_found_this_run, all_processed_site_articles_summary):
    """
    Identifies trends from raw articles, then generates digest pages.
    Args:
        raw_articles_found_this_run (list): Output from web_research_agent.
        all_processed_site_articles_summary (list): Summary data of all articles on your site (from all_articles.json).
    Returns:
        list: A list of digest page data dictionaries.
              Each dict: {'slug', 'page_title', 'meta_description', 'introduction_md', 'selected_articles', 'json_ld_raw'}
    """
    logger.info(f"--- Running Trending Digest Agent ---")
    generated_digest_pages_data = []

    if not raw_articles_found_this_run or len(raw_articles_found_this_run) < MIN_KEYWORD_FREQUENCY_FOR_TREND * 2:
        logger.warning("Not enough raw articles found in this run to reliably determine trends. Skipping digest generation.")
        return generated_digest_pages_data

    # 1. Identify Trends using LLM based on raw article data
    # Prepare a string of titles and snippets for the LLM
    article_snippets_for_llm = ""
    for i, article in enumerate(raw_articles_found_this_run[:MAX_RAW_ARTICLES_FOR_TREND_ANALYSIS]):
        title = article.get('title', 'Untitled')
        # Use a snippet of raw_scraped_text if available, else title again
        snippet = (article.get('scraped_text', '')[:150] + "...") if article.get('scraped_text') else title
        article_snippets_for_llm += f"{i+1}. Title: {title}\n   Snippet: {snippet}\n\n"

    trend_prompt = TREND_IDENTIFICATION_PROMPT.format(
        article_data_for_trend_analysis=article_snippets_for_llm.strip(),
        num_themes_target=NUM_TRENDING_THEMES_TO_GENERATE
    )
    
    logger.info("Attempting to identify trending themes via LLM...")
    identified_themes_response = call_ollama_for_digest_tasks(trend_prompt)
    
    trending_themes = []
    if identified_themes_response and "trending_themes" in identified_themes_response:
        trending_themes = identified_themes_response["trending_themes"]
        logger.info(f"LLM identified {len(trending_themes)} trending themes: {[t.get('theme_name') for t in trending_themes]}")
    else:
        logger.error("Failed to identify trending themes via LLM or response was malformed. Skipping digest generation.")
        return generated_digest_pages_data

    current_iso_date_for_digest = datetime.now(timezone.utc).isoformat()

    # 2. For each identified theme, generate a digest page
    for theme_obj in trending_themes:
        theme_name = theme_obj.get("theme_name")
        theme_keywords = theme_obj.get("defining_keywords", [])
        if not theme_name or not theme_keywords:
            logger.warning(f"Skipping theme due to missing name or keywords: {theme_obj}")
            continue
        
        logger.info(f"Generating digest page for theme: '{theme_name}' (Keywords: {theme_keywords})")

        # Prepare available articles for this theme (mix of your site's processed articles and new raw ones)
        # This is a simplified selection process for the prompt.
        # A more advanced version would use embeddings to find relevant articles.
        
        relevant_articles_for_prompt = []
        # Add some from your site (all_processed_site_articles_summary)
        for proc_article in all_processed_site_articles_summary:
            match = False
            title_lower = proc_article.get('title','').lower()
            summary_lower = proc_article.get('summary_short','').lower()
            tags_lower = [t.lower() for t in proc_article.get('tags',[])]
            for kw in theme_keywords:
                kw_lower = kw.lower()
                if kw_lower in title_lower or kw_lower in summary_lower or kw_lower in tags_lower:
                    match = True; break
            if match:
                full_url = urljoin(YOUR_SITE_BASE_URL_FOR_DIGEST, proc_article.get('link','').lstrip('/'))
                relevant_articles_for_prompt.append(
                    f"- Title: {proc_article.get('title', 'Untitled')}\n  URL: {full_url}\n  Summary: {proc_article.get('summary_short', '')[:200]}\n  Source: Our Site (Internal)"
                )
            if len(relevant_articles_for_prompt) > 5 : break # Limit internal links shown to LLM

        # Add some from the new raw finds for this theme
        raw_articles_added_to_prompt = 0
        for raw_article in raw_articles_found_this_run:
            match = False
            title_lower = raw_article.get('title','').lower()
            text_lower = raw_article.get('scraped_text','').lower()
            for kw in theme_keywords:
                kw_lower = kw.lower()
                if kw_lower in title_lower or kw_lower in text_lower: # Check raw text for keywords
                    match = True; break
            if match:
                relevant_articles_for_prompt.append(
                    f"- Title: {raw_article.get('title', 'Untitled')}\n  URL: {raw_article.get('url')}\n  Summary: {(raw_article.get('scraped_text', '')[:150] + '...') if raw_article.get('scraped_text') else ''}\n  Source: External"
                )
                raw_articles_added_to_prompt +=1
            if raw_articles_added_to_prompt > 5: break # Limit external links shown to LLM
        
        if not relevant_articles_for_prompt:
            logger.warning(f"No relevant articles found to populate digest for theme: {theme_name}. Skipping this theme.")
            continue

        available_articles_str_for_prompt = "\n\n".join(relevant_articles_for_prompt)

        digest_gen_prompt = DIGEST_PAGE_GENERATION_PROMPT.format(
            website_name=YOUR_WEBSITE_NAME_FOR_DIGEST,
            theme_name=theme_name,
            theme_keywords_str=", ".join(theme_keywords),
            available_articles_str=available_articles_str_for_prompt,
            articles_per_theme=ARTICLES_PER_THEME_IN_DIGEST,
            max_title_length=MAX_TITLE_LENGTH_FOR_DIGEST_ITEM,
            max_summary_length=MAX_SUMMARY_LENGTH_FOR_DIGEST_ITEM,
            current_iso_date=current_iso_date_for_digest,
            site_base_url=YOUR_SITE_BASE_URL_FOR_DIGEST,
            website_logo_url=YOUR_WEBSITE_LOGO_URL_FOR_DIGEST
        )

        digest_page_content = call_ollama_for_digest_tasks(digest_gen_prompt)

        if digest_page_content and isinstance(digest_page_content, dict):
            # Validate essential keys
            if all(k in digest_page_content for k in ["digest_page_title", "selected_articles_for_digest"]):
                page_slug = slugify_digest_title(digest_page_content["digest_page_title"])
                # Construct full JSON-LD script tag
                json_ld_obj = digest_page_content.get("digest_page_json_ld_raw", {})
                json_ld_script = f'<script type="application/ld+json">\n{json.dumps(json_ld_obj, indent=2, ensure_ascii=False)}\n</script>'

                generated_digest_pages_data.append({
                    'slug': page_slug,
                    'page_title': digest_page_content["digest_page_title"],
                    'meta_description': digest_page_content.get("digest_meta_description", f"Latest trending news on {theme_name} from {YOUR_WEBSITE_NAME_FOR_DIGEST}."),
                    'introduction_md': digest_page_content.get("digest_introduction_markdown", f"Here's what's trending in {theme_name}:"),
                    'selected_articles': digest_page_content["selected_articles_for_digest"],
                    'json_ld_script_tag': json_ld_script, # Store the full script tag
                    'theme_source_name': theme_name, # For reference
                    'theme_source_keywords': theme_keywords # For reference
                })
                logger.info(f"Successfully generated digest page content for theme: '{theme_name}' (Slug: {page_slug})")
            else:
                logger.error(f"LLM response for digest page theme '{theme_name}' missing critical keys. Response: {str(digest_page_content)[:300]}...")
        else:
            logger.error(f"Failed to generate digest page content for theme '{theme_name}' or response malformed.")
            
    logger.info(f"--- Trending Digest Agent finished. Generated {len(generated_digest_pages_data)} digest pages. ---")
    return generated_digest_pages_data

# --- Standalone Execution Example ---
if __name__ == "__main__":
    if not logger.handlers:
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
                            format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')

    logger.info("--- Starting Trending Digest Agent Standalone Test ---")
    # Ensure Ollama is running with your OLLAMA_DIGEST_MODEL (e.g., mixtral)

    # Mock raw articles found in a run
    mock_raw_articles = [
        {'url': 'http://example.com/news1', 'title': 'Revolutionary AI Model for Drug Discovery Announced by PharmaGiant', 'scraped_text': 'PharmaGiant today unveiled an AI model that speeds up drug discovery by 500%. It uses advanced deep learning...'},
        {'url': 'http://example.com/news2', 'title': 'NVIDIA Unveils New GPU for AI Drug Research', 'scraped_text': 'NVIDIA launched the RXG-Pharma chip, specifically designed to accelerate computational tasks in pharmaceutical AI research...'},
        {'url': 'http://example.com/news3', 'title': 'Ethical Concerns in AI-Powered Medical Diagnosis', 'scraped_text': 'A new report highlights potential biases in AI diagnostic tools, urging for more diverse training data in medical AI...'},
        {'url': 'http://example.com/news4', 'title': 'Google AI Develops Algorithm for Faster Protein Folding in Drug Design', 'scraped_text': 'Google AI researchers published a paper on a new algorithm that significantly improves protein folding predictions, aiding drug development...'},
        {'url': 'http://example.com/news5', 'title': 'Self-Driving Cars: Tesla Reaches New Milestone in FSD Beta', 'scraped_text': 'Tesla\'s Full Self-Driving beta program has reportedly achieved 1 million miles driven with the latest update, showcasing progress in autonomous vehicle tech...'},
        {'url': 'http://example.com/news6', 'title': 'Waymo Expands Robotaxi Service to Downtown Phoenix', 'scraped_text': 'Waymo, Google\'s self-driving car company, is now offering its autonomous ride-hailing service in downtown Phoenix...'},
        {'url': 'http://example.com/news7', 'title': 'Challenges in Regulating Autonomous Vehicle Technology', 'scraped_text': 'Governments worldwide are grappling with how to regulate the rapidly evolving field of autonomous vehicles, balancing innovation with safety...'}
    ]

    # Mock processed articles on your site (simulating all_articles.json content)
    mock_site_summaries = [
        {'id': 'site001', 'title': 'Deep Dive: How AI is Changing Pharmaceutical Research', 'link': 'articles/ai-pharma-deep-dive.html', 'summary_short': 'An analysis of AI applications in the pharmaceutical industry, from research to clinical trials.', 'tags': ['ai in healthcare', 'drug discovery']},
        {'id': 'site002', 'title': 'The Road to Level 5 Autonomy: Where We Stand', 'link': 'articles/level-5-autonomy.html', 'summary_short': 'Exploring the current state and future challenges of achieving full self-driving capability in vehicles.', 'tags': ['autonomous vehicles', 'self-driving cars', 'tesla', 'waymo']}
    ]
    
    # Create a dummy all_articles.json for the test to load if needed by supporting functions
    # (though this agent primarily uses passed-in summaries)
    dummy_all_articles_path_digest = os.path.join(PROJECT_ROOT, 'public', 'all_articles_digest_test.json')
    with open(dummy_all_articles_path_digest, 'w') as f:
        json.dump({"articles": mock_site_summaries}, f)
    
    original_all_articles_path_digest = None
    if 'ALL_ARTICLES_SUMMARY_FILE_PATH' in sys.modules[__name__].__dict__: # If it was defined (e.g. by kg_agent)
        original_all_articles_path_digest = sys.modules[__name__].ALL_ARTICLES_SUMMARY_FILE_PATH
    sys.modules[__name__].ALL_ARTICLES_SUMMARY_FILE_PATH = dummy_all_articles_path_digest


    # Run the agent
    generated_digests = run_trending_digest_agent(mock_raw_articles, mock_site_summaries)

    logger.info("\n--- Trending Digest Test Results ---")
    if generated_digests:
        logger.info(f"Generated {len(generated_digests)} digest pages.")
        for i, digest_page in enumerate(generated_digests):
            logger.info(f"\n--- Digest Page {i+1} ---")
            logger.info(f"  Slug: {digest_page.get('slug')}")
            logger.info(f"  Title: {digest_page.get('page_title')}")
            logger.info(f"  Meta Desc: {digest_page.get('meta_description')}")
            logger.info(f"  Intro MD: {digest_page.get('introduction_md')}")
            logger.info(f"  Source Theme Name: {digest_page.get('theme_source_name')}")
            logger.info(f"  Selected Articles ({len(digest_page.get('selected_articles',[]))} items):")
            for art_item in digest_page.get('selected_articles',[]):
                logger.info(f"    - Title: {art_item.get('title')}")
                logger.info(f"      URL: {art_item.get('url')}")
                logger.info(f"      Summary: {art_item.get('summary_for_digest')}")
                logger.info(f"      Internal: {art_item.get('is_internal')}")
            # logger.info(f"  JSON-LD Script: {digest_page.get('json_ld_script_tag')}") # Can be very long
            logger.info(f"  Raw JSON-LD Object (from digest): {json.dumps(json.loads(digest_page.get('json_ld_script_tag','<script>{}</script>').split('>')[1].split('<')[0]),indent=2)}")


    else:
        logger.info("No digest pages were generated.")

    # Clean up dummy file
    if os.path.exists(dummy_all_articles_path_digest):
        os.remove(dummy_all_articles_path_digest)
    if original_all_articles_path_digest and 'ALL_ARTICLES_SUMMARY_FILE_PATH' in sys.modules[__name__].__dict__ :
         sys.modules[__name__].ALL_ARTICLES_SUMMARY_FILE_PATH = original_all_articles_path_digest


    logger.info("--- Trending Digest Agent Standalone Test Complete ---")