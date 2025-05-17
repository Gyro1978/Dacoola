# src/agents/knowledge_graph_agent.py

import os
import sys
import json
import logging
import requests # For DeepSeek API
import re
from urllib.parse import quote 

# --- Path Setup ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)

ALL_ARTICLES_SUMMARY_FILE_PATH = os.path.join(PROJECT_ROOT, 'public', 'all_articles.json')
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
DEEPSEEK_API_KEY_KG = os.getenv('DEEPSEEK_API_KEY') # KG for Knowledge Graph
DEEPSEEK_CHAT_API_URL_KG = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL_FOR_LINKING = "deepseek-chat" # Or a smaller/faster one if available and suitable

MAX_LINKS_PER_ARTICLE = 3 
MAX_MARKDOWN_SNIPPET_FOR_LLM = 1500 
API_TIMEOUT_LINKING = 90

# --- Prompt Templates ---
INTERNAL_LINK_IDENTIFICATION_SYSTEM_KG = "You are an expert internal linking strategist. Analyze the Markdown snippet and identify distinct key phrases suitable for internal links. Respond ONLY with a JSON list of these exact phrases."
INTERNAL_LINK_IDENTIFICATION_USER_KG = """
**Article Markdown Snippet (Only analyze this snippet):**
```markdown
{markdown_snippet}
```
Identify up to {max_phrases_to_identify} linkable phrases. The phrase must exist *exactly* as identified within the snippet.
Output ONLY a JSON list of strings. Example: {{"linkable_phrases": ["specific AI model name", "a key technology concept"]}}
"""

INTERNAL_LINK_PLACEMENT_SYSTEM_KG = "You are an expert content editor for internal linking. Rewrite the sentence to naturally incorporate the Markdown link. Respond ONLY with the rewritten sentence."
INTERNAL_LINK_PLACEMENT_USER_KG = """
**Input:**
Original Sentence: "{original_sentence}"
Phrase to Link: "{phrase_to_link}"
Target Article Title: "{target_article_title}"
Target Article Slug (for link path): "articles/{target_article_slug}.html"

**Constraints:**
- Retain original meaning.
- Markdown link format MUST be `[[Linked Text | articles/{target_article_slug}.html]]`.
- "Linked Text" should be the original "Phrase to Link" or a natural variation.
- If unnatural, output the original sentence unchanged.

**Output (Provide ONLY the rewritten sentence as a single string):**
Rewritten Sentence: [Your rewritten sentence]
"""

# --- Helper Functions ---
def load_site_content_graph():
    if not os.path.exists(ALL_ARTICLES_SUMMARY_FILE_PATH):
        logger.warning(f"Site content graph file not found: {ALL_ARTICLES_SUMMARY_FILE_PATH}. Internal linking limited.")
        return []
    try:
        with open(ALL_ARTICLES_SUMMARY_FILE_PATH, 'r', encoding='utf-8') as f: data = json.load(f)
        if isinstance(data, dict) and 'articles' in data and isinstance(data['articles'], list):
            logger.info(f"Loaded {len(data['articles'])} articles for site content graph.")
            return data['articles']
        logger.error(f"Invalid format in {ALL_ARTICLES_SUMMARY_FILE_PATH}")
        return []
    except Exception as e: logger.error(f"Error loading site content graph: {e}"); return []

def find_relevant_existing_article(phrase, site_articles, current_article_id):
    best_match = None; highest_score = 0; phrase_lower = phrase.lower()
    for article_summary in site_articles:
        if article_summary.get('id') == current_article_id: continue
        score = 0; title_lower = article_summary.get('title', '').lower()
        tags_lower = [tag.lower() for tag in article_summary.get('tags', [])]
        if phrase_lower in title_lower: score += 2
        elif any(phrase_lower in tag for tag in tags_lower): score += 1
        if len(phrase_lower) > 5 and phrase_lower in title_lower and len(title_lower) / len(phrase_lower) < 3: score +=1
        if score > highest_score: highest_score = score; best_match = article_summary
    if best_match and highest_score > 0:
        if 'slug' not in best_match or not best_match['slug']:
            link_path = best_match.get('link')
            if link_path and link_path.startswith("articles/") and link_path.endswith(".html"):
                best_match['slug'] = link_path.replace("articles/", "").replace(".html", "")
            else: best_match['slug'] = slugify_filename_kg_agent(best_match.get('title', best_match.get('id','unknown-slug')))
        logger.debug(f"Found relevant article for '{phrase}': '{best_match.get('title')}' (Slug: {best_match.get('slug')}) score {highest_score}")
        return best_match
    return None

def call_deepseek_for_linking(system_message, user_message, expect_json=False):
    if not DEEPSEEK_API_KEY_KG:
        logger.error("DEEPSEEK_API_KEY not set. Cannot call DeepSeek for linking task.")
        return None
    
    payload = {
        "model": DEEPSEEK_MODEL_FOR_LINKING,
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message}
        ],
        "temperature": 0.2 # More deterministic for specific tasks
    }
    if expect_json:
        payload["response_format"] = {"type": "json_object"}

    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY_KG}", "Content-Type": "application/json"}
        
    try:
        logger.debug(f"Sending request to DeepSeek model {DEEPSEEK_MODEL_FOR_LINKING} for linking task.")
        response = requests.post(DEEPSEEK_CHAT_API_URL_KG, headers=headers, json=payload, timeout=API_TIMEOUT_LINKING)
        response.raise_for_status()
        response_json = response.json()

        if response_json.get("choices") and response_json["choices"][0].get("message") and response_json["choices"][0]["message"].get("content"):
            content = response_json["choices"][0]["message"]["content"]
            if expect_json:
                try: return json.loads(content)
                except json.JSONDecodeError:
                    logger.error(f"DeepSeek returned non-JSON for a JSON-formatted request: {content[:200]}...")
                    match = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', content, re.DOTALL)
                    if match:
                        try: return json.loads(match.group(1))
                        except: pass
                    return None 
            return content.strip()
        else:
            logger.error(f"DeepSeek linking response missing expected content: {response_json}")
            return None
    except requests.exceptions.RequestException as e:
        logger.error(f"DeepSeek API request failed for linking: {e}")
        if hasattr(e, 'response') and e.response is not None: logger.error(f"DeepSeek API Response: {e.response.text}")
    except Exception as e:
        logger.exception(f"Unexpected error in call_deepseek_for_linking: {e}")
    return None

def slugify_filename_kg_agent(text_to_slugify): 
    if not text_to_slugify: return "untitled-slug"
    s = str(text_to_slugify).strip().lower(); s = re.sub(r'[^\w\s-]', '', s); s = re.sub(r'[-\s]+', '-', s)
    return s[:75]


def run_knowledge_graph_agent(article_pipeline_data, all_site_articles_summary):
    article_id = article_pipeline_data.get('id', 'unknown_id')
    markdown_body = article_pipeline_data.get('seo_agent_results', {}).get('generated_article_body_md', '')

    logger.info(f"--- Running Knowledge Graph Agent (Internal Linking) for Article ID: {article_id} ---")

    if not markdown_body:
        logger.warning(f"No Markdown body for {article_id}. Skipping internal linking.")
        article_pipeline_data['knowledge_graph_status'] = "SKIPPED_NO_MARKDOWN"
        return article_pipeline_data

    body_len = len(markdown_body)
    start_index = max(0, body_len // 4)
    snippet_for_llm = markdown_body[start_index : start_index + MAX_MARKDOWN_SNIPPET_FOR_LLM]

    user_prompt_ident = INTERNAL_LINK_IDENTIFICATION_USER_KG.format(
        markdown_snippet=snippet_for_llm,
        max_phrases_to_identify=MAX_LINKS_PER_ARTICLE * 2
    )
    identified_phrases_response = call_deepseek_for_linking(INTERNAL_LINK_IDENTIFICATION_SYSTEM_KG, user_prompt_ident, expect_json=True)
    
    linkable_phrases = []
    if isinstance(identified_phrases_response, dict) and "linkable_phrases" in identified_phrases_response and isinstance(identified_phrases_response["linkable_phrases"], list):
        linkable_phrases = identified_phrases_response["linkable_phrases"]
        logger.info(f"DeepSeek identified potential linkable phrases for {article_id}: {linkable_phrases}")
    else:
        logger.warning(f"Could not identify linkable phrases via DeepSeek for {article_id}. Response: {str(identified_phrases_response)[:200]}")

    modified_markdown_body = markdown_body; links_added_count = 0; integration_log = []
    paragraphs = modified_markdown_body.split('\n\n')

    for phrase in linkable_phrases:
        if links_added_count >= MAX_LINKS_PER_ARTICLE: break
        if not phrase or len(phrase) < 5: continue

        target_article_summary = find_relevant_existing_article(phrase, all_site_articles_summary, article_id)
        
        if target_article_summary and target_article_summary.get('slug'):
            target_title = target_article_summary.get('title', 'Related Article')
            target_slug = target_article_summary.get('slug')
            
            temp_paragraphs = modified_markdown_body.split('\n\n'); found_in_paragraph_idx = -1; original_sentence_for_llm = ""
            for idx, para in enumerate(temp_paragraphs):
                if phrase in para and f"[[{phrase}" not in para and f"{phrase}]]" not in para and f"](articles/{target_slug}.html)" not in para:
                    sentences = re.split(r'(?<=[.?!])\s+', para)
                    for sent in sentences:
                        if phrase in sent: original_sentence_for_llm = sent.strip(); found_in_paragraph_idx = idx; break
                    if original_sentence_for_llm: break 
            
            if original_sentence_for_llm and found_in_paragraph_idx != -1:
                user_prompt_place = INTERNAL_LINK_PLACEMENT_USER_KG.format(
                    original_sentence=original_sentence_for_llm, phrase_to_link=phrase,
                    target_article_title=target_title, target_article_slug=target_slug
                )
                rewritten_sentence_response = call_deepseek_for_linking(INTERNAL_LINK_PLACEMENT_SYSTEM_KG, user_prompt_place)
                
                rewritten_sentence = ""
                if isinstance(rewritten_sentence_response, str) and "Rewritten Sentence:" in rewritten_sentence_response:
                    rewritten_sentence = rewritten_sentence_response.split("Rewritten Sentence:", 1)[-1].strip()
                elif isinstance(rewritten_sentence_response, str): rewritten_sentence = rewritten_sentence_response.strip()

                if rewritten_sentence and rewritten_sentence != original_sentence_for_llm and f"articles/{target_slug}.html" in rewritten_sentence:
                    current_para_content = temp_paragraphs[found_in_paragraph_idx]
                    updated_para_content = current_para_content.replace(original_sentence_for_llm, rewritten_sentence, 1)
                    if updated_para_content != current_para_content:
                        temp_paragraphs[found_in_paragraph_idx] = updated_para_content
                        modified_markdown_body = "\n\n".join(temp_paragraphs)
                        links_added_count += 1
                        log_msg = f"Added internal link for '{phrase}' to '{target_title}' (slug: {target_slug})"
                        integration_log.append(log_msg); logger.info(f"For {article_id}: {log_msg}")
                    else: logger.warning(f"DeepSeek rewriting did not change sentence for '{phrase}' or link was not added.")
                else: logger.warning(f"DeepSeek could not place link for '{phrase}' or returned original. Response: '{str(rewritten_sentence_response)[:100]}'")
            else: logger.debug(f"Phrase '{phrase}' not found in suitable unlinked sentence for {article_id}.")
        else: logger.debug(f"No relevant existing article found for phrase: '{phrase}'")

    if links_added_count > 0:
        article_pipeline_data.setdefault('seo_agent_results', {})['generated_article_body_md'] = modified_markdown_body
        article_pipeline_data['knowledge_graph_status'] = f"SUCCESS_ADDED_{links_added_count}_INTERNAL_LINKS"
    else: article_pipeline_data['knowledge_graph_status'] = "NO_INTERNAL_LINKS_ADDED"

    article_pipeline_data['knowledge_graph_log'] = integration_log
    logger.info(f"--- Knowledge Graph Agent (Internal Linking) finished for {article_id}. Status: {article_pipeline_data['knowledge_graph_status']} ---")
    return article_pipeline_data

# --- Standalone Execution Example ---
if __name__ == "__main__":
    if not logger.handlers:
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
                            format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')

    if not DEEPSEEK_API_KEY_KG:
        logger.error("DEEPSEEK_API_KEY not set in .env. Cannot run standalone test for knowledge_graph_agent with DeepSeek.")
        sys.exit(1)
        
    logger.info("--- Starting Knowledge Graph Agent (Internal Linking) Standalone Test (with DeepSeek) ---")
    
    mock_site_articles = [
        {"id": "article001", "title": "Understanding Large Language Models (LLMs)", "slug": "understanding-llms", "tags": ["llm", "ai basics"]},
        {"id": "article002", "title": "The Rise of Generative AI", "slug": "generative-ai-rise", "tags": ["generative ai", "ai trends"]},
    ]
    dummy_all_articles_path_kg = os.path.join(PROJECT_ROOT, 'public', 'all_articles_kg_ds_test.json') # Use _ds_ for deepseek test
    with open(dummy_all_articles_path_kg, 'w') as f: json.dump({"articles": mock_site_articles}, f)
    
    original_all_articles_path_kg = sys.modules[__name__].ALL_ARTICLES_SUMMARY_FILE_PATH
    sys.modules[__name__].ALL_ARTICLES_SUMMARY_FILE_PATH = dummy_all_articles_path_kg

    sample_article_pipeline_data = {
        'id': 'current_article_xyz',
        'seo_agent_results': {
            'generated_article_body_md': "This article discusses Large Language Models (LLMs) and their role in Generative AI advancements."
        }, 'title': "Advanced AI Overview" 
    }
    loaded_site_articles = load_site_content_graph()
    result_data = run_knowledge_graph_agent(sample_article_pipeline_data.copy(), loaded_site_articles)

    logger.info("\n--- Knowledge Graph (Internal Linking) Test Results ---")
    logger.info(f"KG Agent Status: {result_data.get('knowledge_graph_status')}")
    logger.info("\nKG Integration Log:"); [logger.info(f"  - {log_entry}") for log_entry in result_data.get('knowledge_graph_log', [])]
    logger.info("\n--- Final Markdown Body with Internal Links ---")
    print(result_data.get('seo_agent_results', {}).get('generated_article_body_md', "ERROR: Markdown body not found."))

    if os.path.exists(dummy_all_articles_path_kg): os.remove(dummy_all_articles_path_kg)
    sys.modules[__name__].ALL_ARTICLES_SUMMARY_FILE_PATH = original_all_articles_path_kg
    logger.info("--- Knowledge Graph Agent (Internal Linking) Standalone Test Complete ---")
