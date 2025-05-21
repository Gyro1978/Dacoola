# src/agents/trending_digest_agent.py

import os
import sys
import json
import logging
import requests 
import re
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urljoin, quote 
import random 

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
DEEPSEEK_API_KEY_TD = os.getenv('DEEPSEEK_API_KEY') 
DEEPSEEK_CHAT_API_URL_TD = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL_FOR_DIGEST_THEMES = "deepseek-chat" 
DEEPSEEK_MODEL_FOR_DIGEST_PAGE = "deepseek-chat"

MAX_RAW_ARTICLES_FOR_TREND_ANALYSIS = 30 
MIN_ARTICLES_FOR_DIGEST_GENERATION = 3 
NUM_TRENDING_THEMES_TO_GENERATE = 2 
ARTICLES_PER_THEME_IN_DIGEST_MIN = 3
ARTICLES_PER_THEME_IN_DIGEST_MAX = 4 

MAX_TITLE_LENGTH_FOR_DIGEST_ITEM = 80 
MAX_SUMMARY_LENGTH_FOR_DIGEST_ITEM = 160 
MAX_DIGEST_PAGE_TITLE_LEN = 70
MAX_DIGEST_META_DESC_LEN = 160

API_TIMEOUT_DIGEST_GEN = 240 

# --- ASI-Level System Prompts & User Templates (v2.2 - Escaped JSON Examples in DigestWeaver System Prompt) ---

# === System Prompt for ThemeFinder Prime ===
THEMEFINDER_PRIME_SYSTEM_PROMPT = """
You are **ThemeFinder Prime**, an ASI-level News Analyst and Trend Forecaster specializing in AI & technology journalism. Your sole mission is to consume raw article data and **identify the top emerging themes** driving the conversation right now. You must think like a world-class news editor: spot clusters of recent developments, distill them into coherent, newsworthy trends, and justify your choices.

**Constraints & Format**

* **Output** *only* a single JSON object matching exactly this schema (no extra keys, no commentary):

  ```json
  {
    "trending_themes": [
      {
        "theme_name":    "string — descriptive, engaging, specific",
        "defining_keywords": ["kw1","kw2","kw3", …],  
        "brief_rationale":   "string — one sentence explaining why this theme is trending, citing a distinctive fact/statistic or unique phrase from input if possible."
      }
      // … up to the requested number of themes
    ]
  }
  ```
* **theme_name**: evocative title of the trend (e.g. “AI-powered Drug Discovery Revolution”).
* **defining_keywords**: 3–5 specific terms that tightly capture the theme.
* **brief_rationale**: exactly one sentence, tying the theme to the input data. Cite a distinctive fact, statistic, or unique phrase from input snippets if one stands out.
* **Do NOT** output anything beyond the JSON object.

**Editorial Guidelines**

1. **Emergence & Significance**: Pick themes that reflect **new** or **rapidly intensifying** discussions. A valid theme must be supported by at least **two distinct** input articles/snippets.
2. **Coherence**: Each theme must group multiple articles/snippets under a single narrative. Do not propose themes that cover **more than half** of the input set unless overwhelmingly justified by the data—those might be too broad. If no theme meets these criteria, identify the next most supported candidate(s) that still represent a clear trend.
3. **Specificity**: Avoid generic umbrellas (“Artificial Intelligence”). Go narrow but impactful.
4. **Engagement**: Theme names and rationales must read like compelling digest headlines.
"""

# === User Prompt Template for ThemeFinder Prime ===
THEMEFINDER_PRIME_USER_CONCEPTUAL_TEMPLATE = """
Identify {THEME_COUNT} trending themes from the provided {N_ARTICLES} recent articles.

The input data will be a JSON object with a key "recent_articles", which is a list of objects, each having "title" and "snippet".
Example conceptual structure of data you'll receive programmatically:
```json
{{ 
  "recent_articles": [
    {{ "title":"Example Article Title 1", "snippet":"Beginning of example snippet 1..." }},
    {{ "title":"Example Article Title 2", "snippet":"Beginning of example snippet 2..." }}
  ]
}}
```
Follow all system prompt instructions precisely.
"""


# === System Prompt for DigestWeaver Prime ===
DIGESTWEAVER_PRIME_SYSTEM_PROMPT = """
You are **DigestWeaver Prime**, an ASI-level Content Curator, SEO Specialist, and Tech News Editor. Given a **single trending theme** and a list of relevant articles, your job is to generate a **fully-formed digest page** that is engaging, SEO-optimized, and publication-ready.

**Constraints & Format**
- **Output** _only_ one JSON object_ exactly following this schema (no extra commentary):

  ```json
  {{
    "digest_page_title":          "string (≤{MAX_TITLE_LEN} chars)",
    "digest_meta_description":    "string (≤{MAX_META_LEN} chars)",
    "digest_introduction_markdown": "string (2–3 sentences in Markdown, with a strong narrative hook)",
    "selected_articles_for_digest": [
      {{
        "title":             "string (≤{MAX_ARTICLE_TITLE_LEN} chars)",
        "url":               "string",
        "summary_for_digest": "string (≤{MAX_ARTICLE_SUMMARY_LEN} chars, written as a compelling teaser)",
        "is_internal":       boolean
      }}
      // … {ARTICLES_PER_THEME_MIN_TARGET} to {ARTICLES_PER_THEME_MAX_TARGET} entries
    ],
    "digest_conclusion_markdown": "string (1-2 sentences synthesizing key takeaways or posing a final thought)",
    "digest_page_json_ld_raw":    {{ /* valid Schema.org CollectionPage, including hasPart for selected articles */ }}
  }}
  ```
* Titles & summaries must obey their length limits.
* Introduction must set context, explain relevance, and entice clicks with a question, provocative statement, or statistic.
* Select a **balanced mix** of internal & external sources; prioritize pillar/internal content when quality is equal.
* `summary_for_digest` should be a **teaser**, highlighting one key insight or finding from the article.
* JSON-LD must be valid, reflect the digest, and include your site’s context. It must include a `hasPart` array of `CreativeWork` for each selected article.

**Editorial Guidelines**

1. **Article Selection**: Pick the most recent, authoritative, and thematically diverse pieces.
2. **SEO Focus**: Weave in the theme’s defining keywords in the title and meta description.
3. **Reader Engagement**: Tone is concise, clear, and compelling.
4. **JSON-LD**: Use `CollectionPage` schema; fields mirror your digest’s title, description, keywords, and parts. `datePublished`, `isPartOf` (website), and `publisher` (organization with name and logo) are essential. Include `hasPart` for each selected article, providing its `headline` and `url`. If selected articles present conflicting viewpoints, briefly note this in the introduction or conclusion.
"""

# === User Prompt Template for DigestWeaver Prime ===
DIGESTWEAVER_PRIME_USER_CONCEPTUAL_TEMPLATE = """
Generate a digest for theme "{THEME_NAME}"
Defining Keywords for this theme: {THEME_KEYWORDS_STR}
Select between {ARTICLES_PER_THEME_MIN_TARGET} and {ARTICLES_PER_THEME_MAX_TARGET} articles from the pool provided in the subsequent JSON data.

The input data for available articles will be a JSON object with a key "available_articles", containing a list of article objects.
Example conceptual structure of data you'll receive programmatically for available articles:
```json
{{ 
  "available_articles": [
    {{ "title":"Example Available Article 1", "url":"http://example.com/1", "summary":"Summary of article 1...", "is_internal":true, "datePublished_iso_optional": "2024-01-01T10:00:00Z" }},
    {{ "title":"Example Available Article 2", "url":"http://externalsite.com/news", "summary":"Summary of external news...", "is_internal":false }}
  ]
}}
```

Site context:
* Website Name: "{WEBSITE_NAME_CONTEXT}"
* Base URL: "{SITE_BASE_URL_CONTEXT}"
* Logo URL: "{WEBSITE_LOGO_URL_CONTEXT}"
* Current Date (ISO 8601 for `datePublished` in JSON-LD): "{CURRENT_ISO_DATE_CONTEXT}"

Character limits:
* Digest Page Title ≤ {MAX_TITLE_LEN} chars
* Digest Meta Description ≤ {MAX_META_LEN} chars
* Individual Article Title in Digest ≤ {MAX_ARTICLE_TITLE_LEN} chars
* Individual Article Summary in Digest ≤ {MAX_ARTICLE_SUMMARY_LEN} chars

Output the JSON digest as specified by the system prompt.
"""


# --- Helper Functions ---
def call_deepseek_for_digest_tasks(system_prompt, user_prompt_input_data_dict, expect_json=True, model=DEEPSEEK_MODEL_FOR_DIGEST_THEMES):
    if not DEEPSEEK_API_KEY_TD:
        logger.error("DEEPSEEK_API_KEY_TD not set. Cannot call DeepSeek for digest task.")
        return None
    
    conceptual_instructions = user_prompt_input_data_dict.get("conceptual_instructions", "")
    actual_data_key = "recent_articles" if "recent_articles" in user_prompt_input_data_dict else "available_articles"
    actual_data_list = user_prompt_input_data_dict.get(actual_data_key, [])
    
    user_content_str = conceptual_instructions 
    user_content_str += f"\n\nActual Input Data ({actual_data_key}):\n```json\n{json.dumps({actual_data_key: actual_data_list})}\n```"

    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content_str}],
        "temperature": 0.45 
    }
    if expect_json:
        payload["response_format"] = {"type": "json_object"}
    
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY_TD}", "Content-Type": "application/json"}

    try:
        task_type_log = "Theme ID" if model == DEEPSEEK_MODEL_FOR_DIGEST_THEMES else "Digest Page Gen"
        logger.debug(f"Sending request to DeepSeek model {model} for digest task ({task_type_log}). User content (first 200): {user_content_str[:200]}")
        response = requests.post(DEEPSEEK_CHAT_API_URL_TD, headers=headers, json=payload, timeout=API_TIMEOUT_DIGEST_GEN)
        response.raise_for_status()
        response_json_api = response.json() 

        if response_json_api.get("choices") and response_json_api["choices"][0].get("message") and response_json_api["choices"][0]["message"].get("content"):
            content_str_from_llm = response_json_api["choices"][0]["message"]["content"] 
            if expect_json:
                try: 
                    parsed_llm_json_output = json.loads(content_str_from_llm) 
                    logger.debug(f"DeepSeek ({task_type_log}) raw JSON response: {content_str_from_llm[:300]}")
                    return parsed_llm_json_output
                except json.JSONDecodeError:
                    logger.error(f"DeepSeek ({task_type_log}) returned non-JSON for a JSON-formatted request: {content_str_from_llm[:200]}...")
                    match = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', content_str_from_llm, re.DOTALL)
                    if match:
                        try: 
                            parsed_json_fallback = json.loads(match.group(1))
                            logger.info(f"DeepSeek ({task_type_log}) extracted JSON from code block.")
                            return parsed_json_fallback
                        except Exception as e_fb:
                            logger.error(f"DeepSeek ({task_type_log}) fallback JSON extraction failed: {e_fb}")
                    return None
            logger.debug(f"DeepSeek ({task_type_log}) raw string response (unexpected for JSON request): {content_str_from_llm[:300]}")
            return content_str_from_llm.strip() 
        else:
            logger.error(f"DeepSeek ({task_type_log}) response missing expected content: {response_json_api}")
            return None
    except requests.exceptions.RequestException as e:
        logger.error(f"DeepSeek API request failed for digest task: {e}")
        if hasattr(e, 'response') and e.response is not None: logger.error(f"DeepSeek API Response: {e.response.text}")
    except Exception as e:
        logger.exception(f"Unexpected error in call_deepseek_for_digest_tasks: {e}")
    return None


def slugify_digest_title(title_text):
    if not title_text: return f"digest-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}" 
    s = str(title_text).strip().lower(); s = re.sub(r'[^\w\s-]', '', s); s = re.sub(r'[-\s]+', '-', s)
    return s[:75]

# --- Main Agent Function ---
def run_trending_digest_agent(raw_articles_found_this_run, all_processed_site_articles_summary):
    logger.info(f"--- Running Trending Digest Agent (ASI-Level Prompts v2.2) ---") 
    generated_digest_pages_data = []

    if not raw_articles_found_this_run or len(raw_articles_found_this_run) < MIN_ARTICLES_FOR_DIGEST_GENERATION:
        logger.warning(f"Not enough raw articles ({len(raw_articles_found_this_run)}) found in this run (min: {MIN_ARTICLES_FOR_DIGEST_GENERATION}). Skipping digest generation.")
        return generated_digest_pages_data

    article_data_for_theme_id_list = []
    for article in raw_articles_found_this_run[:MAX_RAW_ARTICLES_FOR_TREND_ANALYSIS]:
        title = article.get('title', 'Untitled Article')
        snippet_text_raw = article.get('scraped_text', article.get('raw_scraped_text', ''))
        snippet_text = (snippet_text_raw[:120] + "...") if snippet_text_raw else title[:120]+"..."
        article_data_for_theme_id_list.append({"title": title, "snippet": snippet_text})

    if not article_data_for_theme_id_list:
        logger.warning("No valid snippets from raw articles to send for trend analysis. Skipping digest generation.")
        return generated_digest_pages_data
    
    theme_finder_input_data_dict = {
        "conceptual_instructions": THEMEFINDER_PRIME_USER_CONCEPTUAL_TEMPLATE.format(
            N_ARTICLES=len(article_data_for_theme_id_list),
            THEME_COUNT=NUM_TRENDING_THEMES_TO_GENERATE
        ),
        "recent_articles": article_data_for_theme_id_list
    }
    
    logger.info("Attempting to identify trending themes via ThemeFinder Prime...")
    identified_themes_response = call_deepseek_for_digest_tasks(
        THEMEFINDER_PRIME_SYSTEM_PROMPT, 
        theme_finder_input_data_dict, 
        expect_json=True, 
        model=DEEPSEEK_MODEL_FOR_DIGEST_THEMES
    )
    
    trending_themes = []
    if identified_themes_response and "trending_themes" in identified_themes_response and isinstance(identified_themes_response["trending_themes"], list):
        trending_themes = identified_themes_response["trending_themes"]
        logger.info(f"ThemeFinder Prime identified {len(trending_themes)} trending themes: {[t.get('theme_name') for t in trending_themes]}")
    else:
        logger.error("Failed to identify trending themes via ThemeFinder Prime or response was malformed. Skipping digest generation.")
        return generated_digest_pages_data

    current_iso_date_for_digest = datetime.now(timezone.utc).isoformat()

    for theme_obj in trending_themes:
        theme_name = theme_obj.get("theme_name")
        theme_keywords = theme_obj.get("defining_keywords", [])
        if not theme_name or not theme_keywords:
            logger.warning(f"Skipping theme due to missing name or keywords from LLM: {theme_obj}")
            continue
        
        logger.info(f"Generating digest page for theme: '{theme_name}' (Keywords: {theme_keywords})")

        available_articles_for_digest_list_of_dicts = []
        for proc_article in all_processed_site_articles_summary:
            match = False; title_lower = proc_article.get('title','').lower(); summary_lower = proc_article.get('summary_short','').lower()
            tags_lower = [str(t).lower() for t in proc_article.get('tags',[])]
            for kw in theme_keywords:
                if str(kw).lower() in title_lower or str(kw).lower() in summary_lower or str(kw).lower() in tags_lower: match = True; break
            if match:
                available_articles_for_digest_list_of_dicts.append({
                    "title": proc_article.get('title', 'Internal Article')[:MAX_TITLE_LENGTH_FOR_DIGEST_ITEM], 
                    "url": urljoin(YOUR_SITE_BASE_URL_FOR_DIGEST, proc_article.get('link','').lstrip('/')), 
                    "summary": proc_article.get('summary_short', 'No summary.')[:MAX_SUMMARY_LENGTH_FOR_DIGEST_ITEM], 
                    "is_internal": True,
                    "datePublished_iso_optional": proc_article.get("published_iso") 
                })
        for raw_article in raw_articles_found_this_run:
            match = False; title_lower = raw_article.get('title','').lower(); text_lower = (raw_article.get('scraped_text', '') or raw_article.get('raw_scraped_text','')).lower()
            for kw in theme_keywords:
                if str(kw).lower() in title_lower or str(kw).lower() in text_lower: match = True; break
            if match:
                raw_summary_text = (raw_article.get('scraped_text', '') or raw_article.get('raw_scraped_text',''))
                available_articles_for_digest_list_of_dicts.append({
                    "title": raw_article.get('title', 'External Article')[:MAX_TITLE_LENGTH_FOR_DIGEST_ITEM], 
                    "url": raw_article.get('url'), 
                    "summary": (raw_summary_text[:MAX_SUMMARY_LENGTH_FOR_DIGEST_ITEM-3] + '...') if raw_summary_text else 'No summary available.', 
                    "is_internal": False,
                    "datePublished_iso_optional": raw_article.get("parsed_publish_date_iso") 
                })
        
        if not available_articles_for_digest_list_of_dicts:
            logger.warning(f"No relevant articles found to populate digest for theme: {theme_name}. Skipping this theme.")
            continue
        
        random.shuffle(available_articles_for_digest_list_of_dicts)
        articles_to_pass_to_llm = available_articles_for_digest_list_of_dicts[:10] 

        digest_weaver_input_data_dict = {
            "conceptual_instructions": DIGESTWEAVER_PRIME_USER_CONCEPTUAL_TEMPLATE.format(
                THEME_NAME=theme_name, THEME_KEYWORDS_STR=json.dumps(theme_keywords), 
                ARTICLES_PER_THEME_MIN_TARGET=ARTICLES_PER_THEME_IN_DIGEST_MIN,
                ARTICLES_PER_THEME_MAX_TARGET=ARTICLES_PER_THEME_IN_DIGEST_MAX,
                WEBSITE_NAME_CONTEXT=YOUR_WEBSITE_NAME_FOR_DIGEST, SITE_BASE_URL_CONTEXT=YOUR_SITE_BASE_URL_FOR_DIGEST,
                WEBSITE_LOGO_URL_CONTEXT=YOUR_WEBSITE_LOGO_URL_FOR_DIGEST, CURRENT_ISO_DATE_CONTEXT=current_iso_date_for_digest,
                MAX_TITLE_LEN=MAX_DIGEST_PAGE_TITLE_LEN, MAX_META_LEN=MAX_DIGEST_META_DESC_LEN,
                MAX_ARTICLE_TITLE_LEN=MAX_TITLE_LENGTH_FOR_DIGEST_ITEM, MAX_ARTICLE_SUMMARY_LEN=MAX_SUMMARY_LENGTH_FOR_DIGEST_ITEM
            ),
            "available_articles": articles_to_pass_to_llm
        }
        
        system_prompt_for_digest_weaver = DIGESTWEAVER_PRIME_SYSTEM_PROMPT.format(
            MAX_TITLE_LEN=MAX_DIGEST_PAGE_TITLE_LEN, MAX_META_LEN=MAX_DIGEST_META_DESC_LEN,
            MAX_ARTICLE_TITLE_LEN=MAX_TITLE_LENGTH_FOR_DIGEST_ITEM, MAX_ARTICLE_SUMMARY_LEN=MAX_SUMMARY_LENGTH_FOR_DIGEST_ITEM,
            ARTICLES_PER_THEME_MIN_TARGET=ARTICLES_PER_THEME_IN_DIGEST_MIN,
            ARTICLES_PER_THEME_MAX_TARGET=ARTICLES_PER_THEME_IN_DIGEST_MAX
        )

        logger.info(f"Requesting digest page content from DigestWeaver Prime for theme: {theme_name}")
        digest_page_content_response = call_deepseek_for_digest_tasks(
            system_prompt_for_digest_weaver, 
            digest_weaver_input_data_dict, 
            expect_json=True, 
            model=DEEPSEEK_MODEL_FOR_DIGEST_PAGE
        )

        if digest_page_content_response and isinstance(digest_page_content_response, dict):
            if all(k in digest_page_content_response for k in ["digest_page_title", "selected_articles_for_digest", "digest_page_json_ld_raw"]):
                page_slug = slugify_digest_title(digest_page_content_response["digest_page_title"])
                json_ld_obj = digest_page_content_response.get("digest_page_json_ld_raw", {})
                
                json_ld_obj["@context"] = "https://schema.org"
                json_ld_obj["@type"] = "CollectionPage"
                json_ld_obj["headline"] = digest_page_content_response["digest_page_title"]
                json_ld_obj["description"] = digest_page_content_response.get("digest_meta_description", f"Trending news on {theme_name}")
                json_ld_obj["keywords"] = theme_keywords 
                json_ld_obj["datePublished"] = current_iso_date_for_digest
                json_ld_obj.setdefault("isPartOf", {}).update({"@type": "WebSite", "name": YOUR_WEBSITE_NAME_FOR_DIGEST, "url": YOUR_SITE_BASE_URL_FOR_DIGEST})
                json_ld_obj.setdefault("publisher", {}).update({"@type": "Organization", "name": YOUR_WEBSITE_NAME_FOR_DIGEST, "logo": {"@type": "ImageObject", "url": YOUR_WEBSITE_LOGO_URL_FOR_DIGEST}})
                
                has_part_items = []
                for sel_art in digest_page_content_response.get("selected_articles_for_digest", []):
                    item = {"@type": "CreativeWork", "headline": sel_art.get("title"), "url": sel_art.get("url")}
                    original_article_data = next((art_d for art_d in articles_to_pass_to_llm if art_d.get("url") == sel_art.get("url")), None)
                    if original_article_data and original_article_data.get("datePublished_iso_optional"):
                        item["datePublished"] = original_article_data["datePublished_iso_optional"]
                    has_part_items.append(item)
                if has_part_items:
                    json_ld_obj["hasPart"] = has_part_items

                json_ld_script = f'<script type="application/ld+json">\n{json.dumps(json_ld_obj, indent=2, ensure_ascii=False)}\n</script>'
                
                generated_digest_pages_data.append({
                    'slug': page_slug, 
                    'page_title': digest_page_content_response["digest_page_title"],
                    'meta_description': digest_page_content_response.get("digest_meta_description", f"Latest trending news on {theme_name} from {YOUR_WEBSITE_NAME_FOR_DIGEST}."),
                    'introduction_md': digest_page_content_response.get("digest_introduction_markdown", f"Here's what's trending in {theme_name}:"),
                    'conclusion_md': digest_page_content_response.get("digest_conclusion_markdown", ""), 
                    'selected_articles': digest_page_content_response["selected_articles_for_digest"],
                    'json_ld_script_tag': json_ld_script, 
                    'theme_source_name': theme_name, 
                    'theme_source_keywords': theme_keywords 
                })
                logger.info(f"Successfully generated digest page content for theme: '{theme_name}' (Slug: {page_slug})")
            else: 
                logger.error(f"DigestWeaver Prime response for theme '{theme_name}' missing critical keys. Response: {str(digest_page_content_response)[:300]}...")
        else: 
            logger.warning(f"Failed to generate full digest page content for theme '{theme_name}'. Creating fallback mini-digest.")
            page_title_fallback = f"Top {theme_name} Stories This Week"
            page_slug_fallback = slugify_digest_title(page_title_fallback)
            intro_fallback = f"Here are some key articles related to {theme_name}:"
            
            selected_articles_fallback = []
            for i, art_data in enumerate(articles_to_pass_to_llm): 
                if i >= ARTICLES_PER_THEME_IN_DIGEST_MAX: break
                selected_articles_fallback.append({
                    "title": art_data.get("title"), "url": art_data.get("url"),
                    "summary_for_digest": art_data.get("summary")[:100] + "...", "is_internal": art_data.get("is_internal")
                })

            if selected_articles_fallback:
                json_ld_obj_fallback = {
                    "@context": "https://schema.org", "@type": "CollectionPage", "headline": page_title_fallback,
                    "description": f"A collection of recent articles about {theme_name}.", "keywords": theme_keywords, "datePublished": current_iso_date_for_digest,
                    "isPartOf": {"@type": "WebSite", "name": YOUR_WEBSITE_NAME_FOR_DIGEST, "url": YOUR_SITE_BASE_URL_FOR_DIGEST},
                    "publisher": {"@type": "Organization", "name": YOUR_WEBSITE_NAME_FOR_DIGEST, "logo": {"@type": "ImageObject", "url": YOUR_WEBSITE_LOGO_URL_FOR_DIGEST}},
                    "hasPart": [{"@type": "CreativeWork", "headline": sa.get("title"), "url": sa.get("url")} for sa in selected_articles_fallback]
                } 
                json_ld_script_fallback = f'<script type="application/ld+json">\n{json.dumps(json_ld_obj_fallback, indent=2, ensure_ascii=False)}\n</script>'

                generated_digest_pages_data.append({
                    'slug': page_slug_fallback, 'page_title': page_title_fallback,
                    'meta_description': f"A collection of recent articles about {theme_name}.",
                    'introduction_md': intro_fallback, 'conclusion_md': "Stay tuned for more updates on this developing topic.",
                    'selected_articles': selected_articles_fallback, 'json_ld_script_tag': json_ld_script_fallback,
                    'theme_source_name': theme_name, 'theme_source_keywords': theme_keywords, 'is_fallback_digest': True
                })
                logger.info(f"Generated FALLBACK mini-digest for theme: '{theme_name}' (Slug: {page_slug_fallback})")
            else:
                logger.error(f"Could not even generate fallback mini-digest for theme '{theme_name}' as no articles were available after filtering.")
            
    logger.info(f"--- Trending Digest Agent finished. Generated {len(generated_digest_pages_data)} digest pages. ---")
    return generated_digest_pages_data

# --- Standalone Execution Example ---
if __name__ == "__main__":
    if not logger.handlers:
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
                            format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')

    if not DEEPSEEK_API_KEY_TD:
        logger.error("DEEPSEEK_API_KEY_TD not set in .env. Cannot run standalone test for trending_digest_agent with DeepSeek.")
        sys.exit(1)

    logger.info("--- Starting Trending Digest Agent Standalone Test (ASI-Level Prompts v2.2) ---")
    
    mock_raw_articles = [
        {'url': 'http://example.com/news1', 'title': 'Revolutionary AI Model for Drug Discovery by PharmaCo', 'scraped_text': 'PharmaCo today unveiled an AI model that speeds up drug discovery by 500%. It uses advanced deep learning for protein folding prediction and molecular simulation. This breakthrough is expected to drastically reduce the time and cost of bringing new medicines to market, particularly for rare diseases and complex biologics.', 'parsed_publish_date_iso': '2024-03-10T10:00:00Z'},
        {'url': 'http://example.com/news2', 'title': 'NVIDIA AI Chips Power New Drug Research Platforms', 'raw_scraped_text': 'NVIDIA launched the RXG-Pharma chip, specifically designed to accelerate computational tasks in pharmaceutical AI research. Several major research institutions are adopting it for genomics and drug interaction studies.', 'parsed_publish_date_iso': '2024-03-09T10:00:00Z'},
        {'url': 'http://example.com/news3', 'title': 'Ethical Concerns in AI-Powered Medical Diagnosis Highlighted', 'scraped_text': 'A new report highlights potential biases in AI diagnostic tools, urging for more diverse training data in medical AI. The study found disparities in accuracy across demographic groups for certain conditions.', 'parsed_publish_date_iso': '2024-03-08T10:00:00Z'},
        {'url': 'http://example.com/news4', 'title': 'Google AI Develops Algorithm for Faster Protein Folding in Drug Design', 'raw_scraped_text': 'Google AI researchers published a paper on a new algorithm that significantly improves protein folding predictions, aiding drug development. Their method, "AlphaFold Omega", builds upon previous successes.', 'parsed_publish_date_iso': '2024-03-07T10:00:00Z'},
        {'url': 'http://example.com/news5', 'title': 'OpenAI Unveils Sora: Text-to-Video Model Stuns Creators', 'scraped_text': 'OpenAI today demonstrated Sora, a generative AI model capable of creating realistic and imaginative video scenes from text prompts. The quality and coherence of the generated videos have impressed and concerned industry observers.', 'parsed_publish_date_iso': '2024-03-06T10:00:00Z'},
        {'url': 'http://example.com/news6', 'title': 'New Regulations Proposed for Generative AI Video Tools like Sora', 'raw_scraped_text': 'Lawmakers are considering new regulations for powerful text-to-video AI tools like OpenAI\'s Sora, focusing on issues of deepfakes, copyright, and misinformation.', 'parsed_publish_date_iso': '2024-03-05T10:00:00Z'},
    ] 
    mock_site_summaries = [
        {'id': 'site001', 'title': 'Deep Dive: How AI is Changing Pharmaceutical Research', 'link': 'articles/ai-pharma-deep-dive.html', 'summary_short': 'An analysis of AI applications in the pharmaceutical industry, from research to clinical trials.', 'tags': ['ai in healthcare', 'drug discovery'], 'published_iso': '2024-03-01T10:00:00Z'},
        {'id': 'site002', 'title': 'The Road to Level 5 Autonomy: Where We Stand', 'link': 'articles/level-5-autonomy.html', 'summary_short': 'Exploring the current state and future challenges of achieving full self-driving capability in vehicles.', 'tags': ['autonomous vehicles', 'self-driving cars'], 'published_iso': '2024-02-28T10:00:00Z'},
        {'id': 'site003', 'title': 'Generative Video: The Next Frontier in AI Content Creation', 'link': 'articles/generative-video-ai.html', 'summary_short': 'A look at emerging text-to-video technologies and their potential impact.', 'tags': ['generative ai', 'video synthesis', 'sora'], "is_pillar_content": True, 'published_iso': '2024-03-02T10:00:00Z'}
    ]
        
    generated_digests = run_trending_digest_agent(mock_raw_articles, mock_site_summaries)

    logger.info("\n--- Trending Digest Test Results (ASI-Level Prompts v2.2) ---")
    if generated_digests:
        logger.info(f"Generated {len(generated_digests)} digest pages.")
        for i, digest_page in enumerate(generated_digests):
            logger.info(f"\n--- Digest Page {i+1} ---")
            logger.info(f"  Slug: {digest_page.get('slug')}")
            logger.info(f"  Title: {digest_page.get('page_title')}")
            logger.info(f"  Meta Desc: {digest_page.get('meta_description')}")
            logger.info(f"  Intro MD: {digest_page.get('introduction_md')}")
            logger.info(f"  Conclusion MD: {digest_page.get('conclusion_md')}")
            logger.info(f"  Source Theme Name: {digest_page.get('theme_source_name')}")
            logger.info(f"  Source Theme Keywords: {digest_page.get('theme_source_keywords')}")
            logger.info(f"  Is Fallback: {digest_page.get('is_fallback_digest', False)}")
            logger.info(f"  Selected Articles ({len(digest_page.get('selected_articles',[]))} items):")
            for art_item in digest_page.get('selected_articles',[]):
                logger.info(f"    - Title: {art_item.get('title')}, URL: {art_item.get('url')}, Internal: {art_item.get('is_internal')}, Summary: {art_item.get('summary_for_digest')}")
            
            json_ld_script_tag_content = digest_page.get('json_ld_script_tag','')
            if json_ld_script_tag_content:
                match_json_ld = re.search(r'<script type="application/ld\+json">\s*(\{[\s\S]*?\})\s*</script>', json_ld_script_tag_content, re.DOTALL)
                if match_json_ld:
                    try:
                        json_ld_object_parsed = json.loads(match_json_ld.group(1))
                        logger.info(f"  Parsed JSON-LD Object: {json.dumps(json_ld_object_parsed, indent=2)}")
                    except json.JSONDecodeError as e:
                        logger.error(f"  Failed to parse JSON-LD from script tag: {e}")
                        logger.debug(f"  Problematic JSON-LD content: {match_json_ld.group(1)}")
                else:
                    logger.warning("  Could not extract JSON-LD object from script tag.")
            else:
                logger.warning("  No JSON-LD script tag generated for this digest.")
    else:
        logger.info("No digest pages were generated.")
    logger.info("--- Trending Digest Agent Standalone Test (ASI-Level Prompts v2.2) Complete ---")
