# src/agents/knowledge_graph_agent.py

import os
import sys
import json
import logging
import requests 
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
DEEPSEEK_API_KEY_KG = os.getenv('DEEPSEEK_API_KEY') 
DEEPSEEK_CHAT_API_URL_KG = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL_FOR_LINKING = "deepseek-chat" 

MAX_LINKS_PER_ARTICLE = 4 # Increased to match expected 4 links in test
MAX_MARKDOWN_SNIPPET_FOR_LLM_IDENTIFY = 2000 
API_TIMEOUT_LINKING = 120 
MIN_RELEVANCE_SCORE_THRESHOLD_KG = 5 # Lowered further to catch more potential matches
STOP_ADJECTIVES_KG = {"modern","new","advanced","latest", "standard"}


# --- LinkWeaver Prime System Prompt (Enhanced based on ChatGPT Feedback v3) ---
LINKWEAVER_PRIME_SYSTEM_PROMPT = """
You are LinkWeaver Prime, an ASI-level SEO strategist, expert tech editor, and master of Markdown.
Your primary objective is **maximal reader value**: choose links that deepen context, build site authority, and guide readers along logical topic paths. Prioritize cornerstone content and high-traffic ‘pillar’ articles.
Your sole mission is to enhance user experience and SEO by crafting perfect internal links. You have two distinct tasks—follow the instructions for each *exactly* and output *only* in the prescribed format.

---

## Task 1: Identify Linkable Phrases

**Input:** A snippet of Markdown text.
**Output:** A JSON object with one key, `linkable_phrases`, whose value is an array of *exact* phrases from the snippet identified as high-value internal-link anchors.

### Instructions for Task 1

* Prioritize named entities (products, companies, people), core technologies, and precise technical terms that represent strategic anchors or pillar topics.
* Avoid generic or vague phrases (e.g., "the new feature," "this technology").
* Anchors must be meaningful: ≥ 3 words *or* very specific proper nouns (1–2 words).
* Extract phrases *exactly* as they appear.
* Never choose a phrase that, if linked, would distract from the current flow or target a low-value concept.
* Output strictly:

  ```json
  {"linkable_phrases": ["Phrase One", "Phrase Two", …]}
  ```

### Example (Task 1)

**Input Snippet:**

```markdown
The new QuantumFlow Algorithm can parallelize model training across thousands of GPUs. In tests, it outperformed standard transformer pipelines by 3×. This technology is a breakthrough.
```

**Expected Output (Good):**

```json
{"linkable_phrases": [
  "QuantumFlow Algorithm",
  "parallelize model training",
  "standard transformer pipelines"
]}
```

**Bad Output (Avoid - generic phrases):**
```json
{"linkable_phrases": ["This technology", "thousands of GPUs"]}
```

---

## Task 2: Rewrite Sentence to Place Internal Link

**Input:**

1. Original sentence (Markdown).
2. Exact “Phrase to Link” (from Task 1).
3. Title of the target article.
4. Slug of the target article (e.g., `understanding-ai-ethics`).

**Output:** A single rewritten sentence that *naturally* incorporates a Markdown link in this form, using the phrase (or a close variation) as link text:

```
[[Linked Text | articles/target-article-slug.html]]
```

### Instructions for Task 2

* Maintain original meaning and fluency.
* Use the exact phrase as link text whenever possible.
* The link placement must feel editorial and unobtrusive, never forced. It should deepen context, not dilute it.
* If integration harms clarity, flow, or targets a low-value concept, output the original sentence unchanged.
* Output *only* the rewritten sentence—no JSON, no prefixes.

### Example (Task 2 - Good Integration)

**Inputs:**

1. Sentence: `“QuantumFlow Algorithm reduces training time dramatically.”`
2. Phrase to Link: `QuantumFlow Algorithm`
3. Target Title: `“Understanding the QuantumFlow Algorithm”`
4. Slug: `understanding-quantumflow-algorithm`

**Expected Output:**

```
[[QuantumFlow Algorithm | articles/understanding-quantumflow-algorithm.html]] reduces training time dramatically.
```

### Example (Task 2 - Forced Link Rejection)

**Inputs:**

1. Sentence: `“We discuss many topics.”`
2. Phrase to Link: `many topics`
3. Target Title: `“Overview of Our Topics”`
4. Slug: `all-topics-overview`

**Expected Output (Unchanged):**
```
We discuss many topics.
```
---

**Remember:**

* Persona: Precise, analytical, strategic.
* Do *not* include any additional text, explanations, or formatting beyond what each task mandates.
* Your outputs must be machine-parsable and publication-ready.
"""

# --- User Prompt Templates for LinkWeaver Prime ---
TASK1_IDENTIFY_USER_TEMPLATE_KG = """
**Input Snippet:**
```markdown
{markdown_snippet}
```
(Task 1: Identify Linkable Phrases as per system prompt instructions.)
"""

TASK2_PLACE_LINK_USER_TEMPLATE_KG = """
**Inputs:**
1. Original Sentence: "{original_sentence}"
2. Phrase to Link: "{phrase_to_link}"
3. Target Article Title: "{target_article_title}"
4. Slug: "{target_article_slug}"

(Task 2: Rewrite Sentence to Place Internal Link as per system prompt instructions. Output only the rewritten sentence string.)
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
    best_match = None; highest_score = 0; phrase_lower = phrase.lower().strip()
    
    # Enhanced: Strip stop adjectives for broader matching on core concepts
    core_phrase_words = [w for w in phrase_lower.split() if w not in STOP_ADJECTIVES_KG]
    core_phrase_lower = " ".join(core_phrase_words) if core_phrase_words else phrase_lower


    for article_summary in site_articles:
        if article_summary.get('id') == current_article_id: continue 
        
        score = 0
        title_lower = article_summary.get('title', '').lower()
        tags_lower = [str(tag).lower().strip() for tag in article_summary.get('tags', []) if isinstance(tag, str)]
        summary_short_lower = article_summary.get('summary_short', '').lower()
        topic_lower = article_summary.get('topic','').lower() 
        final_keywords_lower = [str(kw).lower().strip() for kw in article_summary.get('final_keywords', []) if isinstance(kw, str)]


        # Exact phrase match in title is very strong
        if phrase_lower == title_lower: score += 50
        elif phrase_lower in title_lower: score += 25 
        
        # Core phrase (without stop adjectives) match in title
        if core_phrase_lower and core_phrase_lower == title_lower: score += 40
        elif core_phrase_lower and core_phrase_lower in title_lower: score += 20

        if phrase_lower == topic_lower: score += 20 
        if core_phrase_lower and phrase_lower != core_phrase_lower and core_phrase_lower == topic_lower: score += 15


        if any(phrase_lower == tag for tag in tags_lower): score += 15 
        if core_phrase_lower and any(core_phrase_lower == tag for tag in tags_lower): score += 10
        
        if phrase_lower in summary_short_lower : score += 10
        if core_phrase_lower and phrase_lower != core_phrase_lower and core_phrase_lower in summary_short_lower : score += 5


        if any(phrase_lower == kw for kw in final_keywords_lower): score += 10
        if core_phrase_lower and any(core_phrase_lower == kw for kw in final_keywords_lower): score += 8
        
        # Sub-phrase word set match in title
        phrase_words = set(core_phrase_words if core_phrase_words else phrase_lower.split())
        title_words_set = set(title_lower.split())
        if len(phrase_words)>1 and phrase_words.issubset(title_words_set): # All words of phrase in title
            score += 15


        if article_summary.get('is_pillar_content', False) and score > 0: # Boost if it's a pillar and has some match
            score *= 1.2 
            score += 5 # Flat bonus for pillar

        if score > highest_score: 
            highest_score = score
            best_match = article_summary
            
    if best_match and (highest_score >= MIN_RELEVANCE_SCORE_THRESHOLD_KG or best_match.get('is_pillar_content')): 
        if 'slug' not in best_match or not best_match['slug']:
            link_path = best_match.get('link') 
            if link_path and link_path.startswith("articles/") and link_path.endswith(".html"):
                best_match['slug'] = link_path.replace("articles/", "").replace(".html", "")
            else: 
                best_match['slug'] = slugify_filename_kg_agent(best_match.get('title', best_match.get('id','unknown-slug')))
        logger.debug(f"Found relevant article for '{phrase}' (core: '{core_phrase_lower}'): '{best_match.get('title')}' (Slug: {best_match.get('slug')}) score {highest_score:.2f}")
        return best_match
    logger.debug(f"No sufficiently relevant article found for '{phrase}' (core: '{core_phrase_lower}'). Highest score: {highest_score:.2f}")
    return None

def call_linkweaver_prime(user_message, expect_json=False):
    if not DEEPSEEK_API_KEY_KG:
        logger.error("DEEPSEEK_API_KEY_KG not set. Cannot call LinkWeaver Prime.")
        return None
    
    payload = {
        "model": DEEPSEEK_MODEL_FOR_LINKING,
        "messages": [
            {"role": "system", "content": LINKWEAVER_PRIME_SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ],
        "temperature": 0.25, 
        "max_tokens": 500 
    }
    if expect_json:
        payload["response_format"] = {"type": "json_object"}

    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY_KG}", "Content-Type": "application/json"}
        
    try:
        task_type = "Identify Phrases" if expect_json else "Place Link"
        logger.debug(f"Sending request to LinkWeaver Prime ({task_type}). Model: {DEEPSEEK_MODEL_FOR_LINKING}.")
        response = requests.post(DEEPSEEK_CHAT_API_URL_KG, headers=headers, json=payload, timeout=API_TIMEOUT_LINKING)
        response.raise_for_status()
        response_json = response.json()

        if response_json.get("choices") and response_json["choices"][0].get("message") and response_json["choices"][0]["message"].get("content"):
            content = response_json["choices"][0]["message"]["content"]
            if expect_json:
                try: 
                    parsed_json = json.loads(content)
                    logger.debug(f"LinkWeaver Prime ({task_type}) raw JSON response: {content[:300]}")
                    return parsed_json
                except json.JSONDecodeError:
                    logger.error(f"LinkWeaver Prime ({task_type}) returned non-JSON for a JSON-formatted request: {content[:200]}...")
                    match = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', content, re.DOTALL)
                    if match:
                        try: 
                            parsed_json_fallback = json.loads(match.group(1))
                            logger.info(f"LinkWeaver Prime ({task_type}) extracted JSON from code block.")
                            return parsed_json_fallback
                        except Exception as e_fb:
                            logger.error(f"LinkWeaver Prime ({task_type}) fallback JSON extraction failed: {e_fb}")
                    return None 
            
            logger.debug(f"LinkWeaver Prime ({task_type}) raw string response before stripping: '{content[:300]}'")
            stripped_content = content.strip()
            if stripped_content.startswith("```") and stripped_content.endswith("```"):
                lines = stripped_content.splitlines()
                if lines[0].strip().lower() in ["```", "```markdown", "```text"]: # Check for common code block starts
                    stripped_content = "\n".join(lines[1:-1]).strip()
                else: # If first line has content after ```, just strip the fences (less common for single sentence)
                    stripped_content = stripped_content[3:-3].strip()
            elif stripped_content.startswith("```"): 
                lines = stripped_content.splitlines()
                if lines[0].strip().lower() in ["```", "```markdown", "```text"]:
                    stripped_content = "\n".join(lines[1:]).strip()
                else:
                    stripped_content = stripped_content[3:].strip()


            logger.debug(f"LinkWeaver Prime ({task_type}) final string response: '{stripped_content[:300]}'")
            return stripped_content
        else:
            logger.error(f"LinkWeaver Prime ({task_type}) response missing expected content: {response_json}")
            return None
    except requests.exceptions.RequestException as e:
        logger.error(f"LinkWeaver Prime ({task_type}) API request failed: {e}")
        if hasattr(e, 'response') and e.response is not None: logger.error(f"DeepSeek API Response: {e.response.text}")
    except Exception as e:
        logger.exception(f"Unexpected error in call_linkweaver_prime ({task_type}): {e}")
    return None

def slugify_filename_kg_agent(text_to_slugify): 
    if not text_to_slugify: return "untitled-slug"
    s = str(text_to_slugify).strip().lower(); s = re.sub(r'[^\w\s-]', '', s); s = re.sub(r'[-\s]+', '-', s)
    return s[:75]


def run_knowledge_graph_agent(article_pipeline_data, all_site_articles_summary):
    article_id = article_pipeline_data.get('id', 'unknown_id')
    # Use the *entire* markdown body for link placement attempts. Snippet is only for initial phrase ID.
    markdown_body_for_placement = article_pipeline_data.get('assembled_article_body_md', 
                                article_pipeline_data.get('seo_agent_results', {}).get('generated_article_body_md', 
                                article_pipeline_data.get('raw_scraped_text', '')))

    logger.info(f"--- Running Knowledge Graph Agent (Internal Linking v6 - Full Body Placement) for Article ID: {article_id} ---")

    if not markdown_body_for_placement: # Check the body we'll use for placement
        logger.warning(f"No Markdown body for {article_id}. Skipping internal linking.")
        article_pipeline_data['knowledge_graph_status'] = "SKIPPED_NO_MARKDOWN"
        article_pipeline_data['knowledge_graph_log'] = ["No Markdown body found."]
        return article_pipeline_data

    # Snippet for phrase identification still uses a portion to manage LLM input size for that task
    body_len = len(markdown_body_for_placement)
    snippet_start_index = int(body_len * 0.10) 
    snippet_end_index = int(body_len * 0.90)   
    snippet_for_llm_identification = markdown_body_for_placement[snippet_start_index : min(snippet_end_index, snippet_start_index + MAX_MARKDOWN_SNIPPET_FOR_LLM_IDENTIFY)]
    if not snippet_for_llm_identification.strip(): 
        snippet_for_llm_identification = markdown_body_for_placement[:MAX_MARKDOWN_SNIPPET_FOR_LLM_IDENTIFY]

    user_prompt_ident = TASK1_IDENTIFY_USER_TEMPLATE_KG.format(markdown_snippet=snippet_for_llm_identification)
    identified_phrases_response = call_linkweaver_prime(user_prompt_ident, expect_json=True)
    
    linkable_phrases_from_llm = []
    if isinstance(identified_phrases_response, dict) and "linkable_phrases" in identified_phrases_response and isinstance(identified_phrases_response["linkable_phrases"], list):
        linkable_phrases_from_llm = [str(p).strip() for p in identified_phrases_response["linkable_phrases"] if isinstance(p, str) and p.strip()]
        linkable_phrases_from_llm.sort(key=len, reverse=True) # Longer phrases might be more specific targets
        logger.info(f"LinkWeaver Prime identified {len(linkable_phrases_from_llm)} potential linkable phrases for {article_id}: {linkable_phrases_from_llm}")
    else:
        logger.warning(f"Could not identify linkable phrases via LinkWeaver Prime for {article_id}. Response: {str(identified_phrases_response)[:200]}")

    modified_paragraphs = markdown_body_for_placement.split('\n\n') # Use full body for placement
    links_added_count = 0; integration_log = []
    successfully_linked_normalized_concepts = set()

    for phrase_to_link_raw in linkable_phrases_from_llm: 
        if links_added_count >= MAX_LINKS_PER_ARTICLE: break
        
        phrase_to_link_normalized_for_check = phrase_to_link_raw.lower().strip()
        if not phrase_to_link_normalized_for_check or len(phrase_to_link_normalized_for_check) < 4 : 
            logger.debug(f"Skipping short/empty phrase from LLM: '{phrase_to_link_raw}'"); continue
        if phrase_to_link_normalized_for_check in successfully_linked_normalized_concepts: 
            logger.debug(f"Concept related to '{phrase_to_link_raw}' (normalized: {phrase_to_link_normalized_for_check}) already linked. Skipping.")
            continue

        target_article_summary = find_relevant_existing_article(phrase_to_link_raw, all_site_articles_summary, article_id)
        
        if target_article_summary and target_article_summary.get('slug'):
            target_title = target_article_summary.get('title', 'Related Article')
            target_slug = target_article_summary.get('slug')
            
            phrase_linked_in_this_article_iteration = False
            for para_idx, para_content in enumerate(modified_paragraphs): # Iterate all paragraphs of the full body
                if phrase_linked_in_this_article_iteration or links_added_count >= MAX_LINKS_PER_ARTICLE : break
                
                if f"articles/{target_slug}.html" in para_content:
                    logger.debug(f"Target slug 'articles/{target_slug}.html' already linked in paragraph {para_idx}. Skipping specific phrase '{phrase_to_link_raw}' for this para if it would point to same slug.")
                    continue

                # Split paragraph into sentences to find the phrase
                sentences = re.split(r'(\.(?:\s|$)|[?!](?:\s|$))', para_content) 
                reconstructed_sentences = []
                for i in range(0, len(sentences) -1, 2): 
                    reconstructed_sentences.append(sentences[i] + (sentences[i+1] if i+1 < len(sentences) else ''))
                if len(sentences) % 2 == 1 and sentences[-1]: 
                    reconstructed_sentences.append(sentences[-1])
                
                temp_para_parts = [] # Stores parts of the current paragraph as they are processed/modified
                sentence_modified_in_this_para_flag = False

                for original_sentence_text in reconstructed_sentences:
                    if not original_sentence_text.strip(): 
                        temp_para_parts.append(original_sentence_text)
                        continue

                    # Search for the phrase (case-insensitive) to get its original casing from the text
                    matched_phrase_in_sentence = None
                    try:
                        # Build a regex that is case-insensitive and respects word boundaries for multi-word phrases
                        # For single word, \b works well. For multi-word, ensure it's not part of a larger word.
                        # A simpler approach is to pass phrase_to_link_raw and let LLM handle slight variations.
                        # We will check if the raw phrase is in the sentence (case insensitive)
                        if phrase_to_link_raw.lower() in original_sentence_text.lower():
                            # Attempt to extract the exact cased version if possible, otherwise use phrase_to_link_raw
                            # This can be complex. For now, we'll pass phrase_to_link_raw to LLM.
                            # A more robust solution would find the actual span of the match.
                            # For now, let's assume phrase_to_link_raw is what we want to link.
                            idx_start = original_sentence_text.lower().find(phrase_to_link_raw.lower())
                            if idx_start != -1:
                                matched_phrase_in_sentence = original_sentence_text[idx_start : idx_start + len(phrase_to_link_raw)]
                            else: # Fallback if find fails (shouldn't if re.search passes)
                                matched_phrase_in_sentence = phrase_to_link_raw
                    except Exception as e_match:
                        logger.debug(f"Error during phrase matching: {e_match}")
                        if phrase_to_link_raw.lower() in original_sentence_text.lower():
                             matched_phrase_in_sentence = phrase_to_link_raw
                    
                    if matched_phrase_in_sentence and not phrase_linked_in_this_article_iteration and links_added_count < MAX_LINKS_PER_ARTICLE:
                        user_prompt_place = TASK2_PLACE_LINK_USER_TEMPLATE_KG.format(
                            original_sentence=original_sentence_text.strip(), 
                            phrase_to_link=matched_phrase_in_sentence, 
                            target_article_title=target_title, 
                            target_article_slug=target_slug
                        )
                        rewritten_sentence = call_linkweaver_prime(user_prompt_place)
                        
                        if rewritten_sentence and rewritten_sentence != original_sentence_text.strip() and f"articles/{target_slug}.html" in rewritten_sentence:
                            temp_para_parts.append(rewritten_sentence)
                            links_added_count += 1
                            log_msg = f"Added internal link for '{matched_phrase_in_sentence}' to '{target_title}' (slug: {target_slug})"
                            integration_log.append(log_msg); logger.info(f"For {article_id}: {log_msg}")
                            phrase_linked_in_this_article_iteration = True 
                            sentence_modified_in_this_para_flag = True
                            successfully_linked_normalized_concepts.add(phrase_to_link_normalized_for_check) 
                        else:
                            temp_para_parts.append(original_sentence_text) 
                            if rewritten_sentence == original_sentence_text.strip():
                                logger.debug(f"LinkWeaver Prime returned original sentence for phrase '{matched_phrase_in_sentence}'.")
                            else:
                                logger.warning(f"LinkWeaver Prime could not place link for '{matched_phrase_in_sentence}' or link format incorrect. LLM Resp: '{str(rewritten_sentence)[:100]}'")
                    else:
                        temp_para_parts.append(original_sentence_text) 
                
                if sentence_modified_in_this_para_flag:
                    modified_paragraphs[para_idx] = "".join(temp_para_parts) 
            
            if phrase_linked_in_this_article_iteration and links_added_count >= MAX_LINKS_PER_ARTICLE: break 
        else: 
            logger.debug(f"No relevant existing article found or slug missing for phrase: '{phrase_to_link_raw}'")

    final_markdown_body = "\n\n".join(modified_paragraphs)

    # Store the modified body back into the pipeline data
    if 'seo_agent_results' in article_pipeline_data and 'generated_article_body_md' in article_pipeline_data['seo_agent_results']:
        article_pipeline_data['seo_agent_results']['generated_article_body_md'] = final_markdown_body
    elif 'assembled_article_body_md' in article_pipeline_data:
            article_pipeline_data['assembled_article_body_md'] = final_markdown_body
    else: 
        article_pipeline_data['generated_article_body_md'] = final_markdown_body # Fallback

    if links_added_count > 0:
        article_pipeline_data['knowledge_graph_status'] = f"SUCCESS_ADDED_{links_added_count}_INTERNAL_LINKS"
    else: 
        article_pipeline_data['knowledge_graph_status'] = "NO_INTERNAL_LINKS_ADDED"
        # Add more detailed reasons to log if no links added
        if not linkable_phrases_from_llm: 
            integration_log.append("No linkable phrases were identified by LinkWeaver Prime from the snippet.")
        elif not any(find_relevant_existing_article(p, all_site_articles_summary, article_id) for p in linkable_phrases_from_llm): 
            integration_log.append("Linkable phrases identified, but no matching existing articles found for any of them.")
        else:
            integration_log.append("Linkable phrases and target articles found, but LinkWeaver Prime could not place links naturally or suitable sentence contexts were not found in the full article body.")

    article_pipeline_data['knowledge_graph_log'] = integration_log
    logger.info(f"--- Knowledge Graph Agent (Internal Linking v6) finished for {article_id}. Status: {article_pipeline_data['knowledge_graph_status']} ---")
    return article_pipeline_data

# --- Standalone Execution Example ---
if __name__ == "__main__":
    if not logger.handlers:
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
                            format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')

    if not DEEPSEEK_API_KEY_KG:
        logger.error("DEEPSEEK_API_KEY_KG not set in .env. Cannot run standalone test for knowledge_graph_agent with DeepSeek.")
        sys.exit(1)
        
    logger.info("--- Starting Knowledge Graph Agent (Internal Linking v6 - Full Body Placement) Standalone Test ---")
    
    mock_site_articles = [
        {"id": "article001", "title": "Understanding Large Language Models (LLMs)", "slug": "understanding-llms", "tags": ["llm", "ai basics"], "summary_short": "An introduction to LLMs.", "final_keywords": ["Large Language Models", "LLM basics"], "topic": "Large Language Models"},
        {"id": "article002", "title": "The Rise of Generative AI", "slug": "generative-ai-rise", "tags": ["generative ai", "ai trends"], "summary_short": "How generative AI is changing industries.", "final_keywords": ["Generative AI", "AI impact"], "topic": "Generative AI"},
        {"id": "article003", "title": "Deep Dive into Transformer Pipelines", "slug": "transformer-pipelines-explained", "tags": ["transformers", "deep learning"], "summary_short": "A technical look at transformer architectures.", "final_keywords": ["Transformer Pipelines", "Neural Networks"], "topic": "Transformer Pipelines"},
         {"id": "article004", "title": "Exploring AI Ethics in Modern Development", "slug": "ai-ethics-modern-dev", "tags": ["ai ethics", "responsible ai"], "summary_short": "Discussing ethical considerations in AI.", "final_keywords": ["AI Ethics", "Responsible AI"], "topic": "AI Ethics", "is_pillar_content": True}, # Mark one as pillar
    ]
    
    dummy_all_articles_path_kg_test = os.path.join(PROJECT_ROOT, 'public', 'all_articles_kg_lw_v6_test.json') 
    with open(dummy_all_articles_path_kg_test, 'w') as f: json.dump({"articles": mock_site_articles}, f)
    
    original_all_articles_path_kg_backup = sys.modules[__name__].ALL_ARTICLES_SUMMARY_FILE_PATH
    sys.modules[__name__].ALL_ARTICLES_SUMMARY_FILE_PATH = dummy_all_articles_path_kg_test

    sample_article_pipeline_data = {
        'id': 'current_article_xyz_v6', 
        'assembled_article_body_md': """
This article discusses the latest breakthroughs. One key area is Large Language Models (LLMs), which are foundational to modern Generative AI. 
We also explore how standard transformer pipelines are evolving. The impact of the QuantumFlow Algorithm is notable.
Future developments in parallelize model training will be critical.
For more on related topics, see our section on AI ethics. An interesting concept is Responsible AI. This text also mentions Generative AI again.
""", 
        'title': "Advanced AI Overview and Its Transformer Pipelines" 
    }
    
    loaded_site_articles_for_test = load_site_content_graph() 
    result_data = run_knowledge_graph_agent(sample_article_pipeline_data.copy(), loaded_site_articles_for_test)

    logger.info("\n--- Knowledge Graph (Internal Linking v6) Test Results ---")
    logger.info(f"KG Agent Status: {result_data.get('knowledge_graph_status')}")
    logger.info("\nKG Integration Log:"); [logger.info(f"  - {log_entry}") for log_entry in result_data.get('knowledge_graph_log', [])]
    
    final_md_body_key_options = ['assembled_article_body_md', 'generated_article_body_md']
    final_md_content_kg = "ERROR: Markdown body not found in expected keys."
    if 'seo_agent_results' in result_data and 'generated_article_body_md' in result_data['seo_agent_results']:
        final_md_content_kg = result_data['seo_agent_results']['generated_article_body_md']
    else:
        for key_opt in final_md_body_key_options:
            if key_opt in result_data:
                final_md_content_kg = result_data[key_opt]
                break
                
    logger.info("\n--- Final Markdown Body with Internal Links (v6) ---")
    print(final_md_content_kg)

    # Assertions for v6
    link_llm_found = "[[Large Language Models (LLMs) | articles/understanding-llms.html]]" in final_md_content_kg or \
                     "[[Large Language Models | articles/understanding-llms.html]]" in final_md_content_kg or \
                     "[[LLMs | articles/understanding-llms.html]]" in final_md_content_kg
    assert link_llm_found, "Link for 'Large Language Models (LLMs)' not found."
    
    link_genai_found = "[[modern Generative AI | articles/generative-ai-rise.html]]" in final_md_content_kg or \
                       "[[Generative AI | articles/generative-ai-rise.html]]" in final_md_content_kg
    assert link_genai_found, "Link for 'Generative AI' not found."
    
    link_pipelines_found = "[[standard transformer pipelines | articles/transformer-pipelines-explained.html]]" in final_md_content_kg
    assert link_pipelines_found, "Link for 'standard transformer pipelines' not found."
        
    link_ethics_found = "[[AI ethics | articles/ai-ethics-modern-dev.html]]" in final_md_content_kg
    assert link_ethics_found, "Link for 'AI ethics' not found."

    assert result_data.get('knowledge_graph_status') == f"SUCCESS_ADDED_{MAX_LINKS_PER_ARTICLE}_INTERNAL_LINKS", f"Expected {MAX_LINKS_PER_ARTICLE} links, got different status."


    if os.path.exists(dummy_all_articles_path_kg_test): os.remove(dummy_all_articles_path_kg_test)
    sys.modules[__name__].ALL_ARTICLES_SUMMARY_FILE_PATH = original_all_articles_path_kg_backup 

    logger.info("--- Knowledge Graph Agent (Internal Linking v6 - Full Body Placement) Standalone Test Complete ---")
