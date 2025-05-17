# src/agents/post_processor_agent.py

import os
import sys
import json
import logging
import markdown # For converting final Markdown to HTML
import html # For unescaping entities
import re # <<< ADDED MISSING IMPORT
from urllib.parse import urljoin, quote
from datetime import datetime, timezone, timedelta # <<< ADDED timedelta

# --- Path Setup ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Load .env for necessary configs like site base URL
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

# --- Configuration from .env (used by helper functions) ---
YOUR_SITE_BASE_URL_PP = os.getenv('YOUR_SITE_BASE_URL', 'https://yoursite.example.com').rstrip('/')
YOUR_WEBSITE_NAME_PP = os.getenv('YOUR_WEBSITE_NAME', 'Dacoola')
YOUR_WEBSITE_LOGO_URL_PP = os.getenv('YOUR_WEBSITE_LOGO_URL', '')
AUTHOR_NAME_DEFAULT_PP = os.getenv('AUTHOR_NAME', 'Dacoola AI Team') # PP for Post Processor

PUBLIC_DIR_PP = os.path.join(PROJECT_ROOT, 'public')
OUTPUT_HTML_DIR_PP = os.path.join(PUBLIC_DIR_PP, 'articles')
DIGEST_OUTPUT_HTML_DIR_PP = os.path.join(PUBLIC_DIR_PP, 'digests') # For digest pages
ALL_ARTICLES_FILE_PP = os.path.join(PUBLIC_DIR_PP, 'all_articles.json')


# --- Helper Functions (some might be duplicates from main.py, centralize later if needed) ---

def slugify_filename_pp(text_to_slugify):
    if not text_to_slugify: return "untitled-slug"
    s = str(text_to_slugify).strip().lower()
    s = re.sub(r'[^\w\s-]', '', s)
    s = re.sub(r'[-\s]+', '-', s)
    return s[:75]

def get_sort_key_pp(item):
    fallback = datetime(1970, 1, 1, tzinfo=timezone.utc); iso_str = item.get('published_iso')
    if not iso_str: return fallback
    try:
        if iso_str.endswith('Z'): iso_str = iso_str[:-1] + '+00:00'
        dt = datetime.fromisoformat(iso_str)
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except ValueError: logger.warning(f"Date parse error '{iso_str}' for sort key. Fallback."); return fallback

def format_tags_html_pp(tags_list):
    if not tags_list: return ""
    try:
        links = []; base = YOUR_SITE_BASE_URL_PP + '/' if YOUR_SITE_BASE_URL_PP else '/'
        for tag_item in tags_list:
            tag_str = str(tag_item) if tag_item is not None else "untagged"
            safe_tag = quote(tag_str)
            url = urljoin(base, f"topic.html?name={safe_tag}")
            links.append(f'<a href="{url}" class="tag-link">{html.escape(tag_str)}</a>')
        return ", ".join(links)
    except Exception as e:
        logger.error(f"Error formatting tags HTML (PP) for tags: {tags_list} - {e}")
        return "Error formatting tags"

def process_final_markdown_to_html_pp(markdown_text):
    """Converts final Markdown (with integrated images and links) to HTML."""
    if not markdown_text: return ""
    html_content = markdown.markdown(markdown_text, extensions=['fenced_code', 'tables', 'nl2br', 'sane_lists', 'extra', 'attr_list'])
    return html.unescape(html_content)

def _load_json_data_pp(filepath, data_description="data"): # Renamed to avoid conflict if main.py is imported
    """Internal helper to load JSON, used by update_all_articles_json_pp."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.debug(f"{data_description} file not found for PP: {filepath}")
        return None
    except json.JSONDecodeError:
        logger.error(f"JSON decode error in {data_description} file for PP: {filepath}.")
        return None
    except Exception as e:
        logger.error(f"Error loading {data_description} from {filepath} for PP: {e}")
        return None

def _save_json_data_pp(filepath, data_to_save, data_description="data"): # Renamed
    """Internal helper to save JSON, used by update_all_articles_json_pp."""
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, indent=4, ensure_ascii=False)
        logger.info(f"Saved {data_description} (PP) to: {os.path.basename(filepath)}")
        return True
    except Exception as e:
        logger.error(f"Failed to save {data_description} (PP) to {os.path.basename(filepath)}: {e}")
        return False


def render_and_save_article_page_pp(article_pipeline_data, jinja_env, post_template_hash_current):
    logger.info(f"PostProcessor: Rendering article page for ID: {article_pipeline_data.get('id')}")
    
    article_id = article_pipeline_data.get('id')
    final_title = article_pipeline_data.get('final_title', article_pipeline_data.get('initial_title_from_web', 'Untitled Article'))
    slug = article_pipeline_data.get('slug', slugify_filename_pp(final_title))

    if not article_id or not slug:
        logger.error(f"PostProcessor: Missing ID or slug for '{final_title}'. Cannot render HTML.")
        return False

    seo_results = article_pipeline_data.get('seo_agent_results', {})
    markdown_body_final = seo_results.get('generated_article_body_md', '') 

    article_body_html = process_final_markdown_to_html_pp(markdown_body_final)
    
    tags_list_final = article_pipeline_data.get('final_keywords', [])
    tags_html_final = format_tags_html_pp(tags_list_final) 

    publish_datetime_obj = get_sort_key_pp(article_pipeline_data)
    publish_date_formatted_final = publish_datetime_obj.strftime('%B %d, %Y') if publish_datetime_obj != datetime(1970,1,1,tzinfo=timezone.utc) else "Date Not Available"

    relative_web_path = f"articles/{slug}.html"
    canonical_url_final = urljoin(YOUR_SITE_BASE_URL_PP + '/', relative_web_path.lstrip('/'))

    json_ld_raw_from_seo = seo_results.get('generated_json_ld_raw', '{}')
    json_ld_script_tag_from_seo = seo_results.get('generated_json_ld_full_script_tag', '<script type="application/ld+json">{}</script>')
    
    canonical_placeholder_in_json_ld_seo = f"{os.getenv('YOUR_SITE_BASE_URL', 'https://yoursite.example.com').rstrip('/')}/articles/{{SLUG_PLACEHOLDER}}"
    
    final_json_ld_for_template = json_ld_script_tag_from_seo
    if canonical_placeholder_in_json_ld_seo in json_ld_raw_from_seo:
        final_json_ld_content = json_ld_raw_from_seo.replace(canonical_placeholder_in_json_ld_seo, canonical_url_final)
        final_json_ld_for_template = f'<script type="application/ld+json">\n{final_json_ld_content}\n</script>'

    template_vars = {
        'PAGE_TITLE': seo_results.get('generated_title_tag', final_title),
        'META_DESCRIPTION': seo_results.get('generated_meta_description', 'Read the latest tech and AI news.'),
        'AUTHOR_NAME': article_pipeline_data.get('author', AUTHOR_NAME_DEFAULT_PP),
        'META_KEYWORDS_LIST': tags_list_final,
        'CANONICAL_URL': canonical_url_final,
        'SITE_NAME': YOUR_WEBSITE_NAME_PP,
        'YOUR_WEBSITE_LOGO_URL': YOUR_WEBSITE_LOGO_URL_PP,
        'IMAGE_URL': article_pipeline_data.get('selected_image_url', ''), 
        'IMAGE_ALT_TEXT': article_pipeline_data.get('final_featured_image_alt_text', final_title),
        'PUBLISH_ISO_FOR_META': article_pipeline_data.get('published_iso', datetime.now(timezone.utc).isoformat()),
        'JSON_LD_SCRIPT_BLOCK': final_json_ld_for_template,
        'ARTICLE_HEADLINE': final_title,
        'ARTICLE_SEO_H1': final_title, 
        'PUBLISH_DATE': publish_date_formatted_final,
        'ARTICLE_BODY_HTML': article_body_html, 
        'ARTICLE_TAGS_HTML': tags_html_final,
        'SOURCE_ARTICLE_URL': article_pipeline_data.get('original_source_url', '#'),
        'ARTICLE_TITLE': final_title, 
        'id': article_id,
        'CURRENT_ARTICLE_ID': article_id,
        'CURRENT_ARTICLE_TOPIC': article_pipeline_data.get('primary_topic', 'General Tech'),
        'CURRENT_ARTICLE_TAGS_JSON': json.dumps(tags_list_final),
        'AUDIO_URL': article_pipeline_data.get('generated_audio_url', None)
    }

    try:
        template = jinja_env.get_template('post_template.html')
        html_page_content = template.render(template_vars)
        
        filepath = os.path.join(OUTPUT_HTML_DIR_PP, f"{slug}.html")
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_page_content)
        logger.info(f"PostProcessor: Successfully rendered and saved article page: {filepath}")
        article_pipeline_data['post_template_hash'] = post_template_hash_current
        return True
    except Exception as e:
        logger.exception(f"PostProcessor: Failed to render/save article page for {article_id}: {e}")
        return False

def render_and_save_digest_page_pp(digest_page_data_item, jinja_env):
    logger.info(f"PostProcessor: Rendering digest page for slug: {digest_page_data_item.get('slug')}")
    
    slug = digest_page_data_item.get('slug')
    if not slug:
        logger.error("PostProcessor: Digest data missing slug. Cannot render.")
        return False

    introduction_html = process_final_markdown_to_html_pp(digest_page_data_item.get('introduction_md', ''))
    
    canonical_url_digest = urljoin(YOUR_SITE_BASE_URL_PP + '/', f"digests/{slug}.html".lstrip('/'))

    template_vars = {
        'PAGE_TITLE': digest_page_data_item.get('page_title', 'Trending Digest'),
        'META_DESCRIPTION': digest_page_data_item.get('meta_description', f'Trending topics from {YOUR_WEBSITE_NAME_PP}'),
        'META_KEYWORDS_LIST': digest_page_data_item.get('theme_source_keywords', []), 
        'CANONICAL_URL': canonical_url_digest,
        'SITE_NAME': YOUR_WEBSITE_NAME_PP,
        'YOUR_WEBSITE_LOGO_URL': YOUR_WEBSITE_LOGO_URL_PP,
        'FAVICON_URL': os.getenv('YOUR_FAVICON_URL', 'https://i.ibb.co/W7xMqdT/dacoola-image-logo.png'), 
        'OG_IMAGE_URL': os.getenv('DEFAULT_OG_IMAGE_FOR_DIGESTS', YOUR_WEBSITE_LOGO_URL_PP), 
        'PUBLISH_ISO_FOR_META': datetime.now(timezone.utc).isoformat(), 
        'JSON_LD_SCRIPT_TAG': digest_page_data_item.get('json_ld_script_tag', ''), 
        'INTRODUCTION_HTML': introduction_html,
        'SELECTED_ARTICLES': digest_page_data_item.get('selected_articles', [])
    }
    
    try:
        template = jinja_env.get_template('digest_page_template.html') 
        html_page_content = template.render(template_vars)
        
        filepath = os.path.join(DIGEST_OUTPUT_HTML_DIR_PP, f"{slug}.html")
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_page_content)
        logger.info(f"PostProcessor: Successfully rendered and saved digest page: {filepath}")
        return True
    except Exception as e:
        logger.exception(f"PostProcessor: Failed to render/save digest page for slug {slug}: {e}")
        return False


def update_all_articles_json_pp(article_summary_data_list_for_update):
    if not isinstance(article_summary_data_list_for_update, list):
        logger.error("PostProcessor: update_all_articles_json_pp expects a list of article summaries.")
        return

    logger.info(f"PostProcessor: Updating {ALL_ARTICLES_FILE_PP} with {len(article_summary_data_list_for_update)} current summaries.")
    
    article_summary_data_list_for_update.sort(key=get_sort_key_pp, reverse=True)
    
    if not _save_json_data_pp(ALL_ARTICLES_FILE_PP, {"articles": article_summary_data_list_for_update}, "master article list"): # Corrected
        logger.error(f"PostProcessor: CRITICAL - Failed to save updated {os.path.basename(ALL_ARTICLES_FILE_PP)}")


# --- Standalone Test (Conceptual - this agent is mostly called by main.py) ---
if __name__ == "__main__":
    if not logger.handlers:
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
                            format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')
    
    logger.info("--- Starting Post Processor Agent Standalone Test (Conceptual) ---")
    
    from jinja2 import Environment, DictLoader
    mock_jinja_env = Environment(loader=DictLoader({
        'post_template.html': "<h1>{{ ARTICLE_HEADLINE }}</h1><div>{{ ARTICLE_BODY_HTML | safe }}</div>",
        'digest_page_template.html': "<h1>{{ PAGE_TITLE }}</h1><section>{{ INTRODUCTION_HTML | safe }}</section>"
    }))
    mock_post_template_hash = "dummyhash123"

    logger.info("\n--- Testing Article Page Rendering ---")
    mock_article_data = {
        'id': 'test_article_pp001',
        'final_title': 'Test Article for Post Processor',
        'slug': 'test-article-post-processor',
        'author': 'PP Test Author',
        'final_keywords': ['testing', 'post-processor', 'python'],
        'published_iso': datetime.now(timezone.utc).isoformat(),
        'selected_image_url': 'https://via.placeholder.com/800x400.png?text=Test+Image',
        'final_featured_image_alt_text': 'Test image alt text',
        'original_source_url': 'http://example.com/source',
        'primary_topic': 'Software Testing',
        'seo_agent_results': {
            'generated_title_tag': 'Test Article for PP | MySite',
            'generated_meta_description': 'This is a test article for the post processor agent.',
            'generated_article_body_md': "## Hello World\n\nThis is **Markdown** content.\n\n<!-- IMAGE_PLACEHOLDER: A conceptual test image -->\n\nCheck out [[Another Topic | another-topic-slug]] and ((External Example | https://example.org)).",
            'generated_json_ld_raw': json.dumps({"@context": "https://schema.org", "@type": "NewsArticle", "headline": "Test Article for Post Processor", "articleBody": "Hello World This is Markdown content.", "wordCount":"7"}),
            'generated_json_ld_full_script_tag': f"<script type=\"application/ld+json\">{json.dumps({'@context': 'https://schema.org', '@type': 'NewsArticle', 'headline': 'Test Article for Post Processor'})}</script>"
        }
    }
    if render_and_save_article_page_pp(mock_article_data, mock_jinja_env, mock_post_template_hash):
        logger.info("Article page rendering test successful (check public/articles/test-article-post-processor.html)")
        assert mock_article_data['post_template_hash'] == mock_post_template_hash
    else:
        logger.error("Article page rendering test FAILED.")

    logger.info("\n--- Testing Digest Page Rendering ---")
    mock_digest_data = {
        'slug': 'daily-ai-news-digest-test',
        'page_title': 'Daily AI News Digest - Test',
        'meta_description': 'Today\'s top AI news, curated for you.',
        'theme_source_keywords': ['ai trends', 'llm updates'],
        'introduction_md': "Here's what's trending in AI today!",
        'selected_articles': [
            {'title': 'New LLM Released', 'url': 'http://example.com/llm-news', 'summary_for_digest': 'A new powerful LLM was released.', 'is_internal': False},
            {'title': 'Our Analysis of LLMs', 'url': f"{YOUR_SITE_BASE_URL_PP}/articles/our-llm-analysis.html", 'summary_for_digest': 'Our site takes a deep dive.', 'is_internal': True}
        ],
        'json_ld_script_tag': f"<script type=\"application/ld+json\">{json.dumps({'@context': 'https://schema.org', '@type': 'CollectionPage', 'headline': 'Daily AI News Digest - Test'})}</script>"
    }
    if render_and_save_digest_page_pp(mock_digest_data, mock_jinja_env):
        logger.info("Digest page rendering test successful (check public/digests/daily-ai-news-digest-test.html)")
    else:
        logger.error("Digest page rendering test FAILED.")

    logger.info("\n--- Testing Master Article List Update ---")
    mock_summary1 = {"id": "test_article_pp001", "title": "Test Article for Post Processor", "link": "articles/test-article-post-processor.html", "published_iso": datetime.now(timezone.utc).isoformat()}
    mock_summary2 = {"id": "another002", "title": "Another Test Article", "link": "articles/another-test.html", "published_iso": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()} # Corrected: timedelta
    
    if os.path.exists(ALL_ARTICLES_FILE_PP):
        os.remove(ALL_ARTICLES_FILE_PP)
        
    update_all_articles_json_pp([mock_summary1, mock_summary2])
    loaded_back = _load_json_data_pp(ALL_ARTICLES_FILE_PP) # Corrected
    if loaded_back and len(loaded_back.get('articles',[])) == 2:
        logger.info("Master article list update test successful.")
    else:
        logger.error(f"Master article list update test FAILED. Content: {loaded_back}")

    logger.info("--- Post Processor Agent Standalone Test Complete ---")