# src/agents/knowledge_graph_agent.py

import os
import sys
import json
import logging
import requests # For Ollama
import re
from urllib.parse import quote # For creating safe URL parts for topic links

# --- Path Setup ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

ALL_ARTICLES_SUMMARY_FILE_PATH = os.path.join(PROJECT_ROOT, 'public', 'all_articles.json') # Path to site graph data
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
# A model good at text understanding and instruction following for link placement.
# Falcon 7B is compact; Mistral 7B is also a good choice.
OLLAMA_LINKING_MODEL = "falcon:7b-instruct-q4_K_M" # Or "mistral:latest"
# OLLAMA_LINKING_MODEL = "mistral:latest" 

MAX_LINKS_PER_ARTICLE = 3 # Max internal links to try and add to one article
MIN_LINK_RELEVANCE_SCORE = 0.6 # Simulated relevance from LLM for link candidate
MAX_MARKDOWN_SNIPPET_FOR_LLM = 1500 # Max characters of markdown to send for link analysis

# --- Prompt Templates ---
INTERNAL_LINK_IDENTIFICATION_PROMPT = """
You are an expert internal linking strategist for a tech news website.
Your task is to analyze a snippet of an article's Markdown content and identify up to {max_phrases_to_identify} distinct key phrases or concepts within that snippet that would be excellent candidates for internal links to other relevant articles on the site.

**Guidelines for Identifying Linkable Phrases:**
- Focus on specific nouns, noun phrases, technical terms, product names, company names, or core concepts.
- Avoid overly generic phrases (e.g., "the technology," "an update," "researchers said").
- The phrase should be substantial enough to represent a distinct topic that another article might cover.
- The phrase must exist *exactly* as identified within the provided "Article Markdown Snippet".

**Article Markdown Snippet (Only analyze this snippet):**
```markdown
{markdown_snippet}
```

Based on the snippet above, provide a JSON list of the exact phrases you've identified as good internal linking candidates.
Each phrase in the list should be a string that is an exact substring of the provided snippet.

Example Output:
{{
  "linkable_phrases": ["specific AI model name", "a key technology concept", "mentioned company X"]
}}

Identify linkable phrases now.
"""

INTERNAL_LINK_PLACEMENT_PROMPT = """
You are an expert content editor specializing in natural internal linking.
You are given an original sentence from an article, a specific "Phrase to Link" within that sentence, and a "Target Article Title" that the phrase should link to. The target article's slug for the link will be `articles/{target_article_slug}.html`.

Your task is to rewrite the "Original Sentence" to naturally incorporate a Markdown link for the "Phrase to Link", pointing to the target article.

**Constraints:**
- The rewritten sentence MUST retain the original meaning and flow naturally.
- The Markdown link format MUST be `[[Linked Text | articles/{target_article_slug}.html]]`.
- The "Linked Text" in the Markdown link should ideally be the original "Phrase to Link", or a very close, natural variation if necessary for flow. Do NOT change the meaning.
- If the "Phrase to Link" appears multiple times in the "Original Sentence", only link the first occurrence unless specified.
- If the phrase cannot be linked naturally without awkward phrasing, output the original sentence unchanged.

**Input:**
Original Sentence: "{original_sentence}"
Phrase to Link: "{phrase_to_link}"
Target Article Title: "{target_article_title}"
Target Article Slug (for link path): "articles/{target_article_slug}.html"

**Output (Provide ONLY the rewritten sentence as a single string):**
Rewritten Sentence: [Your rewritten sentence with the Markdown link, or the original sentence if no natural link placement is possible]
"""

# --- Helper Functions ---
def load_site_content_graph():
    """Loads the all_articles.json file to serve as a site content graph."""
    if not os.path.exists(ALL_ARTICLES_SUMMARY_FILE_PATH):
        logger.warning(f"Site content graph file not found: {ALL_ARTICLES_SUMMARY_FILE_PATH}. Internal linking will be limited.")
        return []
    try:
        with open(ALL_ARTICLES_SUMMARY_FILE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict) and 'articles' in data and isinstance(data['articles'], list):
            logger.info(f"Loaded {len(data['articles'])} articles for site content graph.")
            return data['articles'] # List of article summary dicts
        logger.error(f"Invalid format in site content graph file: {ALL_ARTICLES_SUMMARY_FILE_PATH}")
        return []
    except Exception as e:
        logger.error(f"Error loading site content graph: {e}")
        return []

def find_relevant_existing_article(phrase, site_articles, current_article_id):
    """
    Finds the most relevant existing article for a given phrase, excluding the current article.
    Returns: dict of the target article summary (with 'title', 'slug') or None.
    This is a basic search; a more advanced version would use embeddings or LLM for relevance.
    """
    best_match = None
    highest_score = 0 # Simple scoring: title match = 2, tag/keyword match = 1

    phrase_lower = phrase.lower()

    for article_summary in site_articles:
        if article_summary.get('id') == current_article_id:
            continue # Don't link to self

        score = 0
        title_lower = article_summary.get('title', '').lower()
        tags_lower = [tag.lower() for tag in article_summary.get('tags', [])]
        
        # More sophisticated matching could be done here
        if phrase_lower in title_lower:
            score += 2
        elif any(phrase_lower in tag for tag in tags_lower):
            score += 1
        # Could add primary topic matching from filter_enrich if that data is in all_articles.json
        
        # Simple check: if phrase is a substring of title
        if phrase_lower in title_lower:
             # Prioritize if the phrase is a significant part of the title
            if len(phrase_lower) > 5 and len(title_lower) / len(phrase_lower) < 3: # e.g. phrase is > 1/3rd of title
                score +=1

        if score > highest_score:
            highest_score = score
            best_match = article_summary
            
    if best_match and highest_score > 0: # Require some level of match
        if 'slug' not in best_match or not best_match['slug']: # Ensure slug exists for linking
             # Try to get slug from link if available
            link_path = best_match.get('link') # e.g., "articles/my-slug.html"
            if link_path and link_path.startswith("articles/") and link_path.endswith(".html"):
                best_match['slug'] = link_path.replace("articles/", "").replace(".html", "")
            else: # Fallback slug if needed
                best_match['slug'] = slugify_filename_kg(best_match.get('title', best_match.get('id','unknown-slug'))) # Use local slugify
        
        logger.debug(f"Found relevant article for '{phrase}': '{best_match.get('title')}' (Slug: {best_match.get('slug')}) with score {highest_score}")
        return best_match
    return None

def call_ollama_for_linking(prompt, model=OLLAMA_LINKING_MODEL):
    """Generic Ollama call for linking tasks."""
    payload = {"model": model, "prompt": prompt, "stream": False}
    # If the model is expected to return JSON and supports it:
    if "json" in prompt.lower() or "{" in prompt: # Basic heuristic
        payload["format"] = "json"
        
    try:
        logger.debug(f"Sending request to Ollama model {model} for linking task.")
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=60)
        response.raise_for_status()
        response_json = response.json()
        content = response_json.get("response", "")

        if payload.get("format") == "json": # If we requested JSON
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                logger.error(f"Ollama returned non-JSON for a JSON-formatted request: {content[:200]}...")
                # Try to extract JSON if wrapped
                match = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', content, re.DOTALL)
                if match:
                    try: return json.loads(match.group(1))
                    except: pass
                return None # Failed to get JSON
        return content.strip() # Return text if not JSON formatted request
    except requests.exceptions.RequestException as e:
        logger.error(f"Ollama API request failed for linking: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error in call_ollama_for_linking: {e}")
    return None

# Define slugify_filename_kg for standalone test or if not available from main context
def slugify_filename_kg(text_to_slugify): # kg for knowledge_graph
    if not text_to_slugify: return "untitled-slug"
    s = str(text_to_slugify).strip().lower()
    s = re.sub(r'[^\w\s-]', '', s)
    s = re.sub(r'[-\s]+', '-', s)
    return s[:75]


def run_knowledge_graph_agent(article_pipeline_data, all_site_articles_summary):
    """
    Adds internal links to the article's Markdown body.
    Content gap analysis might be a separate global function or integrated here later.
    """
    article_id = article_pipeline_data.get('id', 'unknown_id')
    markdown_body = article_pipeline_data.get('seo_agent_results', {}).get('generated_article_body_md', '')

    logger.info(f"--- Running Knowledge Graph Agent (Internal Linking) for Article ID: {article_id} ---")

    if not markdown_body:
        logger.warning(f"No Markdown body for {article_id}. Skipping internal linking.")
        article_pipeline_data['knowledge_graph_status'] = "SKIPPED_NO_MARKDOWN"
        return article_pipeline_data

    # Take a snippet of the body for link identification to manage LLM context
    # Try to get a middle portion, as intros/conclusions might be less ideal for diverse internal links.
    body_len = len(markdown_body)
    start_index = max(0, body_len // 4)
    snippet_for_llm = markdown_body[start_index : start_index + MAX_MARKDOWN_SNIPPET_FOR_LLM]

    link_ident_prompt = INTERNAL_LINK_IDENTIFICATION_PROMPT.format(
        markdown_snippet=snippet_for_llm,
        max_phrases_to_identify=MAX_LINKS_PER_ARTICLE * 2 # Ask for more to have choices
    )
    
    identified_phrases_response = call_ollama_for_linking(link_ident_prompt)
    linkable_phrases = []
    if isinstance(identified_phrases_response, dict) and "linkable_phrases" in identified_phrases_response:
        linkable_phrases = identified_phrases_response["linkable_phrases"]
        logger.info(f"LLM identified potential linkable phrases for {article_id}: {linkable_phrases}")
    else:
        logger.warning(f"Could not identify linkable phrases via LLM for {article_id}. Response: {str(identified_phrases_response)[:200]}")

    modified_markdown_body = markdown_body
    links_added_count = 0
    integration_log = []

    # Find sentences containing these phrases to give more context to placement LLM
    # This is complex if phrases span multiple "sentences". For now, simple paragraph search.
    paragraphs = modified_markdown_body.split('\n\n')

    for phrase in linkable_phrases:
        if links_added_count >= MAX_LINKS_PER_ARTICLE:
            break
        if not phrase or len(phrase) < 5: # Skip very short/empty phrases
            continue

        target_article_summary = find_relevant_existing_article(phrase, all_site_articles_summary, article_id)
        
        if target_article_summary and target_article_summary.get('slug'):
            target_title = target_article_summary.get('title', 'Related Article')
            target_slug = target_article_summary.get('slug')

            # Find the paragraph/sentence in the *current* modified_markdown_body that contains the phrase
            # This is important because previous replacements might have changed the body
            # We need to be careful not to re-link an already linked phrase.
            
            # Iterate through paragraphs of the *current* state of the markdown body
            temp_paragraphs = modified_markdown_body.split('\n\n')
            found_in_paragraph_idx = -1
            original_sentence_for_llm = ""

            for idx, para in enumerate(temp_paragraphs):
                # Simple search for now, ensure it's not already part of a Markdown link
                # Regex to find phrase not already in [[...]] or (...)
                # This regex tries to find 'phrase' that is not preceded by "[[Anything|" or "](" or "[[", and not followed by "]]" or ")"
                # It's a heuristic to avoid re-linking.
                # (?<!...) is negative lookbehind, (?!...) is negative lookahead.
                # A more robust way is to parse Markdown, but that's much heavier.
                
                # Search for the phrase only if it's NOT already linked
                # This checks if the phrase is present and NOT part of an existing Markdown link
                # Simple check: if `[[` or `](` is too close to `phrase`, it might be linked.
                # This is tricky. A simpler approach is to only link the phrase if it's not inside `[[...]]`
                
                # Let's try a simpler approach for now: only process paragraphs that contain the phrase
                # and don't already seem to have that phrase linked.
                if phrase in para and f"[[{phrase}" not in para and f"{phrase}]]" not in para and f"](articles/{target_slug}.html)" not in para:
                    # Try to find the sentence containing the phrase
                    # Split paragraph into sentences (basic split by period, question mark, exclamation)
                    sentences = re.split(r'(?<=[.?!])\s+', para)
                    for sent in sentences:
                        if phrase in sent:
                            original_sentence_for_llm = sent.strip()
                            found_in_paragraph_idx = idx
                            break
                    if original_sentence_for_llm:
                        break 
            
            if original_sentence_for_llm and found_in_paragraph_idx != -1:
                link_placement_prompt = INTERNAL_LINK_PLACEMENT_PROMPT.format(
                    original_sentence=original_sentence_for_llm,
                    phrase_to_link=phrase,
                    target_article_title=target_title,
                    target_article_slug=target_slug
                )
                rewritten_sentence_response = call_ollama_for_linking(link_placement_prompt)
                
                # The response should be "Rewritten Sentence: Actual sentence"
                rewritten_sentence = ""
                if isinstance(rewritten_sentence_response, str) and "Rewritten Sentence:" in rewritten_sentence_response:
                    rewritten_sentence = rewritten_sentence_response.split("Rewritten Sentence:", 1)[-1].strip()
                elif isinstance(rewritten_sentence_response, str): # LLM might just give the sentence
                    rewritten_sentence = rewritten_sentence_response.strip()


                if rewritten_sentence and rewritten_sentence != original_sentence_for_llm and f"articles/{target_slug}.html" in rewritten_sentence:
                    # Replace the original sentence in the specific paragraph
                    current_para_content = temp_paragraphs[found_in_paragraph_idx]
                    # Ensure we replace only the first occurrence of the sentence in that paragraph to avoid over-linking
                    updated_para_content = current_para_content.replace(original_sentence_for_llm, rewritten_sentence, 1)
                    
                    if updated_para_content != current_para_content: # If replacement happened
                        temp_paragraphs[found_in_paragraph_idx] = updated_para_content
                        modified_markdown_body = "\n\n".join(temp_paragraphs) # Reconstruct body
                        links_added_count += 1
                        log_msg = f"Added internal link for '{phrase}' to '{target_title}' (slug: {target_slug})"
                        integration_log.append(log_msg)
                        logger.info(f"For {article_id}: {log_msg}")
                    else:
                        logger.warning(f"LLM rewriting did not change sentence for '{phrase}' or link was not added correctly.")
                else:
                    logger.warning(f"LLM could not naturally place link for '{phrase}' or returned original. Response: '{str(rewritten_sentence_response)[:100]}'")
            else:
                logger.debug(f"Phrase '{phrase}' not found in a suitable unlinked sentence in current markdown_body for {article_id}.")
        else:
            logger.debug(f"No relevant existing article found for phrase: '{phrase}'")

    if links_added_count > 0:
        article_pipeline_data.setdefault('seo_agent_results', {})['generated_article_body_md'] = modified_markdown_body
        article_pipeline_data['knowledge_graph_status'] = f"SUCCESS_ADDED_{links_added_count}_INTERNAL_LINKS"
    else:
        article_pipeline_data['knowledge_graph_status'] = "NO_INTERNAL_LINKS_ADDED"

    article_pipeline_data['knowledge_graph_log'] = integration_log
    logger.info(f"--- Knowledge Graph Agent (Internal Linking) finished for {article_id}. Status: {article_pipeline_data['knowledge_graph_status']} ---")
    # Content Gap Analysis would be a separate, more global function
    return article_pipeline_data


# --- Standalone Execution Example ---
if __name__ == "__main__":
    if not logger.handlers:
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
                            format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')

    logger.info("--- Starting Knowledge Graph Agent (Internal Linking) Standalone Test ---")
    # Ensure Ollama is running with your OLLAMA_LINKING_MODEL

    # Mock all_articles.json data
    mock_site_articles = [
        {"id": "article001", "title": "Understanding Large Language Models (LLMs)", "slug": "understanding-llms", "tags": ["llm", "ai basics"]},
        {"id": "article002", "title": "The Rise of Generative AI", "slug": "generative-ai-rise", "tags": ["generative ai", "ai trends"]},
        {"id": "article003", "title": "NVIDIA's Impact on AI Hardware", "slug": "nvidia-ai-hardware", "tags": ["nvidia", "gpu", "ai hardware"]},
        {"id": "article004", "title": "Deep Dive into Transformer Architecture", "slug": "transformer-architecture-deep-dive", "tags": ["transformer", "ai models", "deep learning"]},

    ]
    # Create a dummy all_articles.json for the test to load
    dummy_all_articles_path = os.path.join(PROJECT_ROOT, 'public', 'all_articles_kg_test.json')
    with open(dummy_all_articles_path, 'w') as f:
        json.dump({"articles": mock_site_articles}, f)
    
    # Override the global path for the test
    original_all_articles_path = sys.modules[__name__].ALL_ARTICLES_SUMMARY_FILE_PATH
    sys.modules[__name__].ALL_ARTICLES_SUMMARY_FILE_PATH = dummy_all_articles_path


    sample_article_pipeline_data = {
        'id': 'current_article_xyz',
        'seo_agent_results': {
            'generated_article_body_md': """
            ## Introduction to Advanced AI
            This article discusses advanced AI topics. One key area is the development of Large Language Models (LLMs).
            These models are based on the Transformer architecture and have enabled amazing feats in Generative AI.

            ### Impact of Hardware
            Companies like NVIDIA play a crucial role by providing powerful GPUs. The progress in AI hardware is undeniable.
            We also see new trends in AI model capabilities.
            """
        },
        # Other necessary fields for find_relevant_existing_article if it used them
        'title': "Advanced AI Overview" 
    }

    # Load the (mocked) site graph
    loaded_site_articles = load_site_content_graph()

    result_data = run_knowledge_graph_agent(sample_article_pipeline_data.copy(), loaded_site_articles)

    logger.info("\n--- Knowledge Graph (Internal Linking) Test Results ---")
    logger.info(f"KG Agent Status: {result_data.get('knowledge_graph_status')}")
    
    logger.info("\nKG Integration Log:")
    for log_entry in result_data.get('knowledge_graph_log', []):
        logger.info(f"  - {log_entry}")

    logger.info("\n--- Final Markdown Body with Internal Links ---")
    final_md = result_data.get('seo_agent_results', {}).get('generated_article_body_md', "ERROR: Markdown body not found.")
    print(final_md)

    # Check if links were added (example check)
    if "[[Large Language Models (LLMs) | articles/understanding-llms.html]]" in final_md or \
       "[[Transformer architecture | articles/transformer-architecture-deep-dive.html]]" in final_md or \
       "[[Generative AI | articles/generative-ai-rise.html]]" in final_md or \
       "[[NVIDIA | articles/nvidia-ai-hardware.html]]" in final_md:
        logger.info("\nSUCCESS: At least one internal link seems to have been added.")
    else:
        logger.warning("\nWARNING: Expected internal links might be missing. Check LLM output and logic.")

    # Clean up dummy file
    if os.path.exists(dummy_all_articles_path):
        os.remove(dummy_all_articles_path)
    # Restore original path
    sys.modules[__name__].ALL_ARTICLES_SUMMARY_FILE_PATH = original_all_articles_path


    logger.info("--- Knowledge Graph Agent (Internal Linking) Standalone Test Complete ---")
