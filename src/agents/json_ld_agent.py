# src/agents/json_ld_agent.py
"""
JSON-LD Agent for generating comprehensive and SEO-beneficial NewsArticle
structured data, adhering to schema.org and Google best practices.
"""

import os
import sys
import json
import logging
import re
from datetime import datetime, timezone

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
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
# --- End Setup Logging ---

# --- Configuration from .env ---
YOUR_WEBSITE_NAME_JSONLD = os.getenv('YOUR_WEBSITE_NAME', 'Dacoola')
YOUR_WEBSITE_LOGO_URL_JSONLD = os.getenv('YOUR_WEBSITE_LOGO_URL', 'https://via.placeholder.com/200x60.png?text=YourLogo')
BASE_URL_FOR_CANONICAL_JSONLD = os.getenv('YOUR_SITE_BASE_URL', 'https://yoursite.example.com').rstrip('/')
AUTHOR_NAME_DEFAULT_JSONLD = os.getenv('AUTHOR_NAME', 'Dacoola AI Team')

MAX_ARTICLE_BODY_FOR_JSONLD = 3000
MAX_KEYWORDS_FOR_JSONLD = 15

# --- Helper Functions ---
def strip_markdown_html_for_jsonld(text: str | None) -> str:
    if not text: return ""
    # Remove script and style tags first
    text = re.sub(r'<script.*?>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style.*?>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    # Remove other HTML tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Markdown stripping
    text = re.sub(r'^\s*#{1,6}\s+', '', text, flags=re.MULTILINE) # Headings
    text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text) # Links
    text = re.sub(r'!\[(.*?)\]\(.*?\)', r'\1', text) # Images (alt text)
    text = re.sub(r'\*\*([^*]+?)\*\*', r'\1', text) # Bold
    text = re.sub(r'__([^_]+?)__', r'\1', text) # Bold (underscore)
    text = re.sub(r'\*([^*]+?)\*', r'\1', text) # Italics
    text = re.sub(r'_([^_]+?)_', r'\1', text) # Italics (underscore)
    text = re.sub(r'`(.*?)`', r'\1', text) # Inline code
    text = re.sub(r'```[\s\S]*?```', '', text, flags=re.DOTALL) # Fenced code blocks
    text = re.sub(r'^\s*>\s*', '', text, flags=re.MULTILINE) # Blockquotes
    text = re.sub(r'^\s*[\*\-\+]\s+', '', text, flags=re.MULTILINE) # List items
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE) # Numbered list items
    text = re.sub(r'<!-- IMAGE_PLACEHOLDER:.*?-->', '', text, flags=re.DOTALL)
    text = re.sub(r'<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->', '', text)
    # Normalize whitespace
    text = re.sub(r'\s{2,}', ' ', text).strip()
    return text

def truncate_at_word_boundary(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    truncated = text[:max_length]
    # Find the last space to avoid cutting words mid-way
    last_space = truncated.rfind(' ')
    if last_space != -1 and last_space > max_length - 50: # Only cut at space if it's reasonably close
        return truncated[:last_space].strip() + "..."
    return truncated.strip() + "..." # Fallback to hard truncate

def slugify_filename_jsonld(text_to_slugify: str | None) -> str:
    if not text_to_slugify: return "untitled-article-slug"
    s = str(text_to_slugify).strip().lower()
    s = re.sub(r'[^\w\s-]', '', s) # Remove non-alphanumeric chars except whitespace and hyphens
    s = re.sub(r'[-\s]+', '-', s)   # Replace whitespace/multiple hyphens with single hyphen
    return s[:75]                   # Truncate

def generate_news_article_json_ld(article_pipeline_data: dict) -> dict:
    article_id = article_pipeline_data.get('id', 'unknown_id')
    logger.info(f"--- Generating JSON-LD for Article ID: {article_id} ---")

    headline_source = "initial_title_from_web" # Start with the least preferred
    headline = article_pipeline_data.get('initial_title_from_web', 'Untitled Tech Article')
    if article_pipeline_data.get('final_title'):
        headline = article_pipeline_data['final_title']; headline_source = "final_title"
    if article_pipeline_data.get('generated_seo_h1'):
        headline = article_pipeline_data['generated_seo_h1']; headline_source = "generated_seo_h1"
    if article_pipeline_data.get('article_h1_final_suggestion'):
        headline = article_pipeline_data['article_h1_final_suggestion']; headline_source = "article_h1_final_suggestion"
    if article_pipeline_data.get('final_page_h1'): # This should be the most definitive
        headline = article_pipeline_data['final_page_h1']; headline_source = "final_page_h1"
    
    if headline_source != "final_page_h1":
        logger.warning(f"JSON-LD headline for {article_id} using fallback source: '{headline_source}'. Value: '{headline}'")
    
    keywords_list = article_pipeline_data.get('final_keywords', [])
    keywords_for_jsonld = [str(kw) for kw in keywords_list if kw and isinstance(kw, str)][:MAX_KEYWORDS_FOR_JSONLD]
    if not keywords_for_jsonld:
        logger.warning(f"No keywords available for JSON-LD for article {article_id}.")

    slug = article_pipeline_data.get('slug')
    if not slug:
        slug = slugify_filename_jsonld(headline)
        logger.warning(f"Slug was not found for {article_id}, generated fallback: {slug}")
        
    main_entity_of_page_url = f"{BASE_URL_FOR_CANONICAL_JSONLD}/articles/{slug}.html"

    raw_markdown_body = article_pipeline_data.get('assembled_article_body_md', '')
    article_body_plain_text_full = strip_markdown_html_for_jsonld(raw_markdown_body)
    article_body_for_jsonld = truncate_at_word_boundary(article_body_plain_text_full, MAX_ARTICLE_BODY_FOR_JSONLD)
    if len(article_body_plain_text_full) > MAX_ARTICLE_BODY_FOR_JSONLD:
        logger.info(f"articleBody for {article_id} truncated from {len(article_body_plain_text_full)} to {len(article_body_for_jsonld)} chars.")
    
    word_count = len(article_body_plain_text_full.split())

    author_name_raw = article_pipeline_data.get('author')
    author_name = author_name_raw if author_name_raw and isinstance(author_name_raw, str) else AUTHOR_NAME_DEFAULT_JSONLD
    
    date_published_iso_raw = article_pipeline_data.get('published_iso')
    date_published_iso = None
    if date_published_iso_raw and isinstance(date_published_iso_raw, str):
        try: 
            dt_pub_str = date_published_iso_raw.replace('Z', '+00:00') # Ensure ISO 8601 UTC format
            dt_pub = datetime.fromisoformat(dt_pub_str)
            # Ensure timezone-aware UTC
            if dt_pub.tzinfo is None or dt_pub.tzinfo.utcoffset(dt_pub) is None:
                dt_pub = dt_pub.replace(tzinfo=timezone.utc)
            date_published_iso = dt_pub.isoformat()
        except ValueError:
            logger.error(f"Invalid datePublished format '{date_published_iso_raw}' for {article_id}. Omitting datePublished.")
    else:
        logger.warning(f"Missing or invalid 'published_iso' for {article_id}. Omitting datePublished from JSON-LD.")

    date_modified_iso = date_published_iso # Default modified to published
    date_modified_iso_raw = article_pipeline_data.get('modified_iso')
    if date_modified_iso_raw and isinstance(date_modified_iso_raw, str) and date_published_iso: # Only set if published is also set
        try:
            dt_mod_str = date_modified_iso_raw.replace('Z', '+00:00')
            dt_mod = datetime.fromisoformat(dt_mod_str)
            if dt_mod.tzinfo is None or dt_mod.tzinfo.utcoffset(dt_mod) is None:
                dt_mod = dt_mod.replace(tzinfo=timezone.utc)
            date_modified_iso = dt_mod.isoformat()
        except ValueError:
            logger.warning(f"Invalid dateModified format '{date_modified_iso_raw}' for {article_id}. Using datePublished value if available.")
    elif not date_published_iso: # If datePublished was omitted, omit dateModified too
        date_modified_iso = None
        if date_modified_iso_raw: # Log if modified_iso was present but couldn't be used
             logger.warning(f"datePublished omitted for {article_id}, so dateModified (from '{date_modified_iso_raw}') will also be omitted.")


    image_url = article_pipeline_data.get('selected_image_url')
    image_object_list_for_jsonld = []
    if image_url and isinstance(image_url, str) and image_url.startswith('http'):
        image_object_list_for_jsonld.append({
            "@type": "ImageObject",
            "url": image_url
            # "width": 1200, # Placeholder, ideally get from image_pipeline_data if available
            # "height": 675  # Placeholder
        })
    else:
        logger.warning(f"Missing/invalid selected_image_url for {article_id}. Article image will be omitted from JSON-LD. Publisher logo remains.")

    json_ld_data = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": headline,
        "mainEntityOfPage": {
            "@type": "WebPage",
            "@id": main_entity_of_page_url
        },
        "author": {"@type": "Person", "name": author_name},
        "publisher": {
            "@type": "Organization",
            "name": YOUR_WEBSITE_NAME_JSONLD,
            "logo": {"@type": "ImageObject", "url": YOUR_WEBSITE_LOGO_URL_JSONLD}
        },
        "description": article_pipeline_data.get('generated_meta_description', headline[:160]), # Fallback desc to headline
        "articleBody": article_body_for_jsonld,
        "wordCount": word_count,
        "isPartOf": {"@type": "WebSite", "name": YOUR_WEBSITE_NAME_JSONLD, "url": BASE_URL_FOR_CANONICAL_JSONLD}
    }
    
    if keywords_for_jsonld:
        json_ld_data["keywords"] = keywords_for_jsonld
    if date_published_iso:
        json_ld_data["datePublished"] = date_published_iso
    if date_modified_iso:
        json_ld_data["dateModified"] = date_modified_iso
    if image_object_list_for_jsonld:
        json_ld_data["image"] = image_object_list_for_jsonld # Will be an array with one ImageObject
    
    primary_topic_name = article_pipeline_data.get('primary_topic')
    if primary_topic_name and isinstance(primary_topic_name, str):
        json_ld_data["about"] = [{"@type": "Thing", "name": primary_topic_name}]
        logger.debug(f"Added 'about' property to JSON-LD for {article_id} with topic: {primary_topic_name}")

    logger.info(f"Successfully generated JSON-LD for article {article_id}.")
    logger.debug(f"JSON-LD for {article_id}: {json.dumps(json_ld_data, indent=2)}")
    return json_ld_data

def run_json_ld_agent(article_pipeline_data: dict) -> dict:
    json_ld_object = generate_news_article_json_ld(article_pipeline_data)
    article_pipeline_data['generated_json_ld_object'] = json_ld_object # Store the dict
    
    # For embedding in HTML, ensure a clean JSON string
    json_ld_string_for_script = json.dumps(json_ld_object, indent=2, ensure_ascii=False)
    article_pipeline_data['generated_json_ld_full_script_tag'] = f'<script type="application/ld+json">\n{json_ld_string_for_script}\n</script>'
    
    article_pipeline_data['json_ld_agent_status'] = "SUCCESS"
    logger.info(f"JSON-LD Agent for {article_pipeline_data.get('id', 'unknown_id')} completed.")
    return article_pipeline_data

if __name__ == "__main__":
    logger.info("--- Starting JSON-LD Agent Standalone Test (Enhanced Logic) ---")
    
    sample_data_complete = {
        'id': 'test_jsonld_complete_001',
        'final_page_h1': "NVIDIA Blackwell B200: A New Titan for AI Supercomputing", 
        'slug': "nvidia-blackwell-b200-ai-supercomputing-titan", 
        'final_keywords': ["NVIDIA Blackwell B200", "AI GPU", "Supercomputing", "Deep Learning Accelerators"],
        'author': "Tech Analyst Pro",
        'published_iso': "2024-03-18T10:00:00Z", 
        'modified_iso': "2024-03-19T11:30:00Z",
        'selected_image_url': "https://example.com/images/nvidia_blackwell_b200.jpg",
        'generated_meta_description': "NVIDIA's Blackwell B200 GPU sets a new standard in AI supercomputing, offering unprecedented power.",
        'assembled_article_body_md': "## The Blackwell Architecture\n\nNVIDIA today announced **Blackwell**. <!-- IMAGE_PLACEHOLDER: diagram --> It's *fast*.",
        'primary_topic': "AI Hardware"
    }
    result_complete = run_json_ld_agent(sample_data_complete.copy())
    logger.info("\n--- Test Results (Complete Data) ---")
    logger.info(f"Status: {result_complete.get('json_ld_agent_status')}")
    print("Generated JSON-LD Object:\n", json.dumps(result_complete.get('generated_json_ld_object',{}), indent=2))

    sample_data_minimal = {
        'id': 'test_jsonld_minimal_002',
        'final_page_h1': "Quick Tech Note", # Only headline
        'slug': "quick-tech-note",
        # no keywords, no author, no dates, no image, no meta_description, no body, no primary_topic
    }
    result_minimal = run_json_ld_agent(sample_data_minimal.copy())
    logger.info("\n--- Test Results (Minimal Data) ---")
    logger.info(f"Status: {result_minimal.get('json_ld_agent_status')}")
    print("Generated JSON-LD Object (Minimal):\n", json.dumps(result_minimal.get('generated_json_ld_object',{}), indent=2))
    
    sample_data_bad_date = {
        'id': 'test_jsonld_baddate_003',
        'final_page_h1': "Article With Bad Date",
        'slug': "article-bad-date",
        'published_iso': "NOT_A_VALID_DATE",
        'selected_image_url': "http://example.com/image.png",
        'assembled_article_body_md': "Some content."
    }
    result_bad_date = run_json_ld_agent(sample_data_bad_date.copy())
    logger.info("\n--- Test Results (Bad Date) ---")
    logger.info(f"Status: {result_bad_date.get('json_ld_agent_status')}")
    json_ld_obj_bad_date = result_bad_date.get('generated_json_ld_object',{})
    print("Generated JSON-LD Object (Bad Date):\n", json.dumps(json_ld_obj_bad_date, indent=2))
    assert "datePublished" not in json_ld_obj_bad_date, "datePublished should be omitted if invalid"
    assert "dateModified" not in json_ld_obj_bad_date, "dateModified should be omitted if datePublished is omitted"


    logger.info("--- JSON-LD Agent Standalone Test Complete ---")