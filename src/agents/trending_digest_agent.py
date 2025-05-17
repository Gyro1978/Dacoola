# src/agents/trending_digest_agent.py

import os
import sys
import json
import logging
import requests # For DeepSeek API
import re
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urljoin, quote 

# --- Path Setup ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

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
DEEPSEEK_API_KEY_TD = os.getenv('DEEPSEEK_API_KEY') # TD for Trending Digest
DEEPSEEK_CHAT_API_URL_TD = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL_FOR_DIGEST = "deepseek-chat" 

MAX_RAW_ARTICLES_FOR_TREND_ANALYSIS = 50 
MIN_KEYWORD_FREQUENCY_FOR_TREND = 3 # This was used by the old keyword extractor, LLM trend ID might not need it directly
NUM_TRENDING_THEMES_TO_GENERATE = 3 
ARTICLES_PER_THEME_IN_DIGEST = 3 
MAX_TITLE_LENGTH_FOR_DIGEST_ITEM = 70
MAX_SUMMARY_LENGTH_FOR_DIGEST_ITEM = 150 
API_TIMEOUT_DIGEST_GEN = 180

# --- Prompt Templates ---
TREND_IDENTIFICATION_SYSTEM_TD = "You are an expert news analyst. Identify emerging trends from the provided article data. Respond ONLY with the JSON object."
TREND_IDENTIFICATION_USER_TD = """
Analyze the following list of articles (title and a short snippet of raw text) and identify {num_themes_target} distinct, significant, and currently trending themes or topics.
For each theme, also list the primary keywords that define it. Avoid overly broad themes.

**Article Data (List of Titles and Snippets):**
{article_data_for_trend_analysis}

**Output Format (Strictly JSON):**
{{
  "trending_themes": [
    {{"theme_name": "Example Theme 1: AI in Drug Discovery", "defining_keywords": ["drug discovery", "pharmaceutical AI", "medical research models"]}},
    {{"theme_name": "Example Theme 2: Advancements in Robotics Software", "defining_keywords": ["robotics OS", "AI for robot navigation", "collaborative robots software"]}}
  ]
}}
"""

DIGEST_PAGE_GENERATION_SYSTEM_TD = "You are an expert content curator and SEO specialist for {website_name}. Generate a Trending Digest page for the given theme. Respond ONLY with the JSON object."
DIGEST_PAGE_GENERATION_USER_TD = """
**Theme for this Digest:** {theme_name}
**Keywords defining this theme:** {theme_keywords_str}

**Available Articles related to this theme (Internal from our site, and potentially relevant external links):**
{available_articles_str}

**Instructions:**
1.  **Select Top Articles:** From the "Available Articles", select the top {articles_per_theme} most relevant, recent, and impactful articles for this theme. Prioritize variety if possible.
2.  **Digest Page Title:** Create a compelling, SEO-friendly title for this digest page (e.g., "AI in Healthcare: Top {articles_per_theme} Breakthroughs This Week"). Max {max_title_length} characters.
3.  **Digest Page Meta Description:** Write a concise meta description (max 160 characters) summarizing the digest's content.
4.  **Digest Introduction:** Write a brief (2-3 sentences) engaging Markdown introduction for the digest page, explaining the theme's current significance.
5.  **Article Summaries for Digest:** For each selected article:
    *   Use its provided title (or a slightly shortened version if too long, max {max_title_length} chars).
    *   Use its provided summary (or generate a new very concise 1-2 sentence summary if the provided one is too long or unsuitable for a digest, max {max_summary_length} chars).
    *   Include its URL.
    *   Indicate if it's an internal or external source.
6.  **JSON-LD for Digest Page:** Create a `CollectionPage` JSON-LD object for this digest page. Include headline, description, keywords (from theme), and datePublished.

**Output Format (Strictly JSON):**
{{
  "digest_page_title": "string",
  "digest_meta_description": "string",
  "digest_introduction_markdown": "string",
  "selected_articles_for_digest": [
    {{"title": "string", "url": "string", "summary_for_digest": "string", "is_internal": boolean}}
  ],
  "digest_page_json_ld_raw": {{
    "@context": "https://schema.org", "@type": "CollectionPage", "headline": "string",
    "description": "string", "keywords": ["string1", "string2"], "datePublished": "{current_iso_date}",
    "isPartOf": {{"@type": "WebSite", "url": "{site_base_url}"}},
    "publisher": {{"@type": "Organization", "name": "{website_name}", "logo": {{"@type": "ImageObject", "url": "{website_logo_url}"}}}}
  }}
}}
"""

# --- Helper Functions ---
def call_deepseek_for_digest_tasks(system_prompt, user_prompt, expect_json=True):
    if not DEEPSEEK_API_KEY_TD:
        logger.error("DEEPSEEK_API_KEY not set. Cannot call DeepSeek for digest task.")
        return None
        
    payload = {
        "model": DEEPSEEK_MODEL_FOR_DIGEST,
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        "temperature": 0.4 
    }
    if expect_json:
        payload["response_format"] = {"type": "json_object"}
    
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY_TD}", "Content-Type": "application/json"}

    try:
        logger.debug(f"Sending request to DeepSeek model {DEEPSEEK_MODEL_FOR_DIGEST} for digest task.")
        response = requests.post(DEEPSEEK_CHAT_API_URL_TD, headers=headers, json=payload, timeout=API_TIMEOUT_DIGEST_GEN)
        response.raise_for_status()
        response_json = response.json()

        if response_json.get("choices") and response_json["choices"][0].get("message") and response_json["choices"][0]["message"].get("content"):
            content = response_json["choices"][0]["message"]["content"]
            if expect_json:
                try: return json.loads(content)
                except json.JSONDecodeError:
                    logger.error(f"DeepSeek returned non-JSON for a JSON-formatted digest request: {content[:200]}...")
                    match = re.search(r'```json\s*(\{[\s\S]*?\}|\[[\s\S]*?\])\s*```', content, re.DOTALL)
                    if match:
                        try: return json.loads(match.group(1))
                        except: pass
                    return None
            return content.strip()
        else:
            logger.error(f"DeepSeek digest response missing expected content: {response_json}")
            return None
    except requests.exceptions.RequestException as e:
        logger.error(f"DeepSeek API request failed for digest task: {e}")
        if hasattr(e, 'response') and e.response is not None: logger.error(f"DeepSeek API Response: {e.response.text}")
    except Exception as e:
        logger.exception(f"Unexpected error in call_deepseek_for_digest_tasks: {e}")
    return None

# This function was part of the original logic for a non-LLM keyword extraction.
# While the LLM now identifies themes, this can still be a supplementary input or for other uses.
def extract_keywords_from_raw_articles(raw_articles_list):
    """Basic keyword extraction from titles of raw articles to find trend candidates."""
    all_words = []
    # More comprehensive stopwords might be beneficial
    stopwords = set([
        "the", "a", "an", "is", "are", "was", "were", "and", "or", "of", "to", "in", "it", "for", "on", "with", 
        "this", "that", "new", "news", "ai", "tech", "how", "what", "why", "when", "top", "best", "guide",
        "latest", "update", "review", "analysis", "report", "future", "impact", "advancements", "breakthroughs"
    ]) 
    
    for article in raw_articles_list:
        title = article.get('title', '').lower()
        # Simple tokenization: split by non-alphanum, keep words > 2 chars
        words = re.findall(r'\b[a-z]{3,}\b', title) # Consider bigrams/trigrams for better phrases
        for word in words:
            if word not in stopwords:
                all_words.append(word)
    
    if not all_words: return []
    
    word_counts = Counter(all_words)
    # This is a simple way to get candidates. LLM handles actual theme clustering.
    trend_candidates = [word for word, count in word_counts.most_common(50) if count >= MIN_KEYWORD_FREQUENCY_FOR_TREND] # Increased candidate pool
    logger.debug(f"Initial keyword candidates from raw titles (for context): {trend_candidates}")
    return trend_candidates


def slugify_digest_title(title_text):
    if not title_text: return f"digest-{datetime.now().strftime('%Y%m%d%H%M')}" # Added H M for more uniqueness
    s = str(title_text).strip().lower(); s = re.sub(r'[^\w\s-]', '', s); s = re.sub(r'[-\s]+', '-', s)
    return s[:75]

# --- Main Agent Function ---
def run_trending_digest_agent(raw_articles_found_this_run, all_processed_site_articles_summary):
    logger.info(f"--- Running Trending Digest Agent ---")
    generated_digest_pages_data = []

    if not raw_articles_found_this_run or len(raw_articles_found_this_run) < MIN_KEYWORD_FREQUENCY_FOR_TREND * 2: # Check if enough articles to even attempt
        logger.warning("Not enough raw articles found in this run to reliably determine trends. Skipping digest generation.")
        return generated_digest_pages_data

    # 1. Prepare data for LLM-based trend identification
    article_snippets_for_llm = ""
    # Use more articles for trend analysis if available
    for i, article in enumerate(raw_articles_found_this_run[:MAX_RAW_ARTICLES_FOR_TREND_ANALYSIS]):
        title = article.get('title', 'Untitled Article')
        # Use a snippet of raw_scraped_text if available, else title again
        snippet = (article.get('scraped_text', article.get('raw_scraped_text', ''))[:150] + "...") if (article.get('scraped_text') or article.get('raw_scraped_text')) else title
        article_snippets_for_llm += f"{i+1}. Title: {title}\n   Snippet: {snippet}\n\n"

    if not article_snippets_for_llm.strip():
        logger.warning("No valid snippets from raw articles to send for trend analysis. Skipping digest generation.")
        return generated_digest_pages_data

    user_prompt_trend = TREND_IDENTIFICATION_USER_TD.format(
        article_data_for_trend_analysis=article_snippets_for_llm.strip(),
        num_themes_target=NUM_TRENDING_THEMES_TO_GENERATE
    )
    
    logger.info("Attempting to identify trending themes via DeepSeek LLM...")
    identified_themes_response = call_deepseek_for_digest_tasks(TREND_IDENTIFICATION_SYSTEM_TD, user_prompt_trend, expect_json=True)
    
    trending_themes = []
    if identified_themes_response and "trending_themes" in identified_themes_response and isinstance(identified_themes_response["trending_themes"], list):
        trending_themes = identified_themes_response["trending_themes"]
        logger.info(f"DeepSeek LLM identified {len(trending_themes)} trending themes: {[t.get('theme_name') for t in trending_themes]}")
    else:
        logger.error("Failed to identify trending themes via DeepSeek LLM or response was malformed. Skipping digest generation.")
        return generated_digest_pages_data

    current_iso_date_for_digest = datetime.now(timezone.utc).isoformat()

    # 2. For each identified theme, generate a digest page
    for theme_obj in trending_themes:
        theme_name = theme_obj.get("theme_name")
        theme_keywords = theme_obj.get("defining_keywords", []) # These are from the LLM now
        if not theme_name or not theme_keywords:
            logger.warning(f"Skipping theme due to missing name or keywords from LLM: {theme_obj}")
            continue
        
        logger.info(f"Generating digest page for theme: '{theme_name}' (Keywords: {theme_keywords})")

        # Prepare available articles for this theme (mix of your site's processed articles and new raw ones)
        relevant_articles_for_prompt_list = []
        
        # Add relevant internal articles from your site
        internal_added_count = 0
        for proc_article in all_processed_site_articles_summary:
            if internal_added_count >= ARTICLES_PER_THEME_IN_DIGEST + 2: break # Get a few more internal than needed for LLM to choose from
            match = False
            title_lower = proc_article.get('title','').lower()
            summary_lower = proc_article.get('summary_short','').lower()
            tags_lower = [str(t).lower() for t in proc_article.get('tags',[])] # Ensure tags are strings
            for kw in theme_keywords: # Use LLM-identified theme keywords
                kw_lower = str(kw).lower()
                if kw_lower in title_lower or kw_lower in summary_lower or kw_lower in tags_lower:
                    match = True; break
            if match:
                full_url = urljoin(YOUR_SITE_BASE_URL_FOR_DIGEST, proc_article.get('link','').lstrip('/'))
                relevant_articles_for_prompt_list.append(
                    f"- Title: {proc_article.get('title', 'Untitled Internal Article')}\n  URL: {full_url}\n  Summary: {proc_article.get('summary_short', 'No summary available.')[:200]}\n  Source: Our Site (Internal)"
                )
                internal_added_count +=1

        # Add relevant new raw articles found in this run
        external_added_count = 0
        for raw_article in raw_articles_found_this_run:
            if external_added_count >= ARTICLES_PER_THEME_IN_DIGEST + 2: break # Get a few more external than needed
            match = False
            title_lower = raw_article.get('title','').lower()
            text_lower = (raw_article.get('scraped_text', '') or raw_article.get('raw_scraped_text','')).lower()
            for kw in theme_keywords:
                kw_lower = str(kw).lower()
                if kw_lower in title_lower or kw_lower in text_lower: 
                    match = True; break
            if match:
                raw_summary = (raw_article.get('scraped_text', '') or raw_article.get('raw_scraped_text',''))
                relevant_articles_for_prompt_list.append(
                    f"- Title: {raw_article.get('title', 'Untitled External Article')}\n  URL: {raw_article.get('url')}\n  Summary: {(raw_summary[:150] + '...') if raw_summary else 'No summary available.'}\n  Source: External"
                )
                external_added_count +=1
        
        if not relevant_articles_for_prompt_list:
            logger.warning(f"No relevant articles (internal or external) found to populate digest for theme: {theme_name}. Skipping this theme.")
            continue

        available_articles_str_for_prompt = "\n\n".join(relevant_articles_for_prompt_list)

        user_prompt_digest_gen = DIGEST_PAGE_GENERATION_USER_TD.format(
            theme_name=theme_name, theme_keywords_str=", ".join(theme_keywords),
            available_articles_str=available_articles_str_for_prompt,
            articles_per_theme=ARTICLES_PER_THEME_IN_DIGEST,
            max_title_length=MAX_TITLE_LENGTH_FOR_DIGEST_ITEM, max_summary_length=MAX_SUMMARY_LENGTH_FOR_DIGEST_ITEM,
            current_iso_date=current_iso_date_for_digest, site_base_url=YOUR_SITE_BASE_URL_FOR_DIGEST,
            website_name=YOUR_WEBSITE_NAME_FOR_DIGEST, website_logo_url=YOUR_WEBSITE_LOGO_URL_FOR_DIGEST
        )
        system_prompt_digest_gen = DIGEST_PAGE_GENERATION_SYSTEM_TD.format(website_name=YOUR_WEBSITE_NAME_FOR_DIGEST)
        
        logger.info(f"Requesting digest page content from DeepSeek for theme: {theme_name}")
        digest_page_content = call_deepseek_for_digest_tasks(system_prompt_digest_gen, user_prompt_digest_gen, expect_json=True)

        if digest_page_content and isinstance(digest_page_content, dict):
            if all(k in digest_page_content for k in ["digest_page_title", "selected_articles_for_digest"]):
                page_slug = slugify_digest_title(digest_page_content["digest_page_title"])
                json_ld_obj = digest_page_content.get("digest_page_json_ld_raw", {})
                # Ensure required fields for JSON-LD are present if using the one from LLM
                if not all(k in json_ld_obj for k in ["@context", "@type", "headline"]):
                    logger.warning(f"Generated JSON-LD for digest '{page_slug}' missing core fields. Rebuilding basic.")
                    json_ld_obj = { # Fallback basic JSON-LD
                        "@context": "https://schema.org", "@type": "CollectionPage",
                        "headline": digest_page_content["digest_page_title"],
                        "description": digest_page_content.get("digest_meta_description", f"Trending news on {theme_name}"),
                        "keywords": theme_keywords, "datePublished": current_iso_date_for_digest,
                        "isPartOf": {"@type": "WebSite", "url": YOUR_SITE_BASE_URL_FOR_DIGEST},
                        "publisher": {"@type": "Organization", "name": YOUR_WEBSITE_NAME_FOR_DIGEST, "logo": {"@type": "ImageObject", "url": YOUR_WEBSITE_LOGO_URL_FOR_DIGEST}}
                    }
                json_ld_script = f'<script type="application/ld+json">\n{json.dumps(json_ld_obj, indent=2, ensure_ascii=False)}\n</script>'
                
                generated_digest_pages_data.append({
                    'slug': page_slug, 
                    'page_title': digest_page_content["digest_page_title"],
                    'meta_description': digest_page_content.get("digest_meta_description", f"Latest trending news on {theme_name} from {YOUR_WEBSITE_NAME_FOR_DIGEST}."),
                    'introduction_md': digest_page_content.get("digest_introduction_markdown", f"Here's what's trending in {theme_name}:"),
                    'selected_articles': digest_page_content["selected_articles_for_digest"],
                    'json_ld_script_tag': json_ld_script, 
                    'theme_source_name': theme_name, 
                    'theme_source_keywords': theme_keywords 
                })
                logger.info(f"Successfully generated digest page content for theme: '{theme_name}' (Slug: {page_slug})")
            else: 
                logger.error(f"DeepSeek response for digest page theme '{theme_name}' missing critical keys (digest_page_title or selected_articles_for_digest). Response: {str(digest_page_content)[:300]}...")
        else: 
            logger.error(f"Failed to generate digest page content for theme '{theme_name}' or response malformed.")
            
    logger.info(f"--- Trending Digest Agent finished. Generated {len(generated_digest_pages_data)} digest pages. ---")
    return generated_digest_pages_data

# --- Standalone Execution Example ---
if __name__ == "__main__":
    if not logger.handlers:
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
                            format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')

    if not DEEPSEEK_API_KEY_TD:
        logger.error("DEEPSEEK_API_KEY not set in .env. Cannot run standalone test for trending_digest_agent with DeepSeek.")
        sys.exit(1)

    logger.info("--- Starting Trending Digest Agent Standalone Test (with DeepSeek) ---")
    
    mock_raw_articles = [
        {'url': 'http://example.com/news1', 'title': 'Revolutionary AI Model for Drug Discovery by PharmaCo', 'scraped_text': 'PharmaCo today unveiled an AI model that speeds up drug discovery by 500%. It uses advanced deep learning...'},
        {'url': 'http://example.com/news2', 'title': 'NVIDIA AI Chips Power New Drug Research', 'scraped_text': 'NVIDIA launched the RXG-Pharma chip, specifically designed to accelerate computational tasks in pharmaceutical AI research...'},
        {'url': 'http://example.com/news3', 'title': 'Ethical Concerns in AI-Powered Medical Diagnosis', 'scraped_text': 'A new report highlights potential biases in AI diagnostic tools, urging for more diverse training data in medical AI...'},
        {'url': 'http://example.com/news4', 'title': 'Google AI Develops Algorithm for Faster Protein Folding in Drug Design', 'scraped_text': 'Google AI researchers published a paper on a new algorithm that significantly improves protein folding predictions, aiding drug development...'},
    ]
    mock_site_summaries = [
        {'id': 'site001', 'title': 'Deep Dive: How AI is Changing Pharmaceutical Research', 'link': 'articles/ai-pharma-deep-dive.html', 'summary_short': 'An analysis of AI applications in the pharmaceutical industry, from research to clinical trials.', 'tags': ['ai in healthcare', 'drug discovery']},
        {'id': 'site002', 'title': 'The Road to Level 5 Autonomy: Where We Stand', 'link': 'articles/level-5-autonomy.html', 'summary_short': 'Exploring the current state and future challenges of achieving full self-driving capability in vehicles.', 'tags': ['autonomous vehicles', 'self-driving cars']}
    ]
        
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
                logger.info(f"    - Title: {art_item.get('title')}, URL: {art_item.get('url')}, Internal: {art_item.get('is_internal')}")
            # logger.info(f"  JSON-LD Script: {digest_page.get('json_ld_script_tag')}") 
            raw_json_ld_obj_str = (digest_page.get('json_ld_script_tag','<script>{}</script>').split('>',1)[1].rsplit('<',1)[0]).strip()
            try:
                raw_json_ld_obj = json.loads(raw_json_ld_obj_str)
                logger.info(f"  Raw JSON-LD Object (from digest): {json.dumps(raw_json_ld_obj,indent=2)}")
            except json.JSONDecodeError:
                logger.error(f"Could not parse JSON-LD from script tag for digest: {digest_page.get('slug')}")
                logger.debug(f"Problematic JSON string: {raw_json_ld_obj_str}")


    else:
        logger.info("No digest pages were generated.")
    logger.info("--- Trending Digest Agent Standalone Test Complete ---")