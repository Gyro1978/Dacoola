"""
Keyword Generator Agent: Produces a comprehensive list of SEO keywords for articles.

This agent uses a multi-stage LLM process, enhanced with NLP techniques,
to identify core subjects, user intent, and specific entities within article content.
It generates a diverse, semantically unique, and hyper-relevant set of search keywords,
focusing on natural language and a mix of broad and long-tail terms for maximum discoverability.
"""

import os
import sys
import json
import logging
import re
# import requests # Commented out for Modal integration
import modal # Added for Modal integration
import time # For retry delays

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
# --- End Setup Logging ---

# --- NLP Libraries Setup (Lazy Loading) ---
SPACY_MODEL = None
SENTENCE_MODEL = None
SENTENCE_UTIL = None # For cos_sim

try:
    import spacy
    try:
        # Attempt to load the small English model
        SPACY_MODEL = spacy.load("en_core_web_sm")
        logger.info("SpaCy model 'en_core_web_sm' loaded successfully for NER.")
    except OSError:
        # If model not found, provide instructions
        logger.warning("SpaCy model 'en_core_web_sm' not found. Run 'python -m spacy download en_core_web_sm' to enable entity extraction.")
        SPACY_MODEL = None # Ensure it's None if loading fails
except ImportError:
    logger.warning("SpaCy library not found. Named Entity Recognition (NER) will be disabled. Run 'pip install spacy'.")

try:
    from sentence_transformers import SentenceTransformer, util as sentence_transformers_util
    SENTENCE_MODEL = SentenceTransformer('all-MiniLM-L6-v2')
    SENTENCE_UTIL = sentence_transformers_util
    logger.info("Sentence Transformer model 'all-MiniLM-L6-v2' loaded successfully for semantic deduplication.")
except ImportError:
    logger.warning("Sentence-transformers library not found. Semantic keyword deduplication will be disabled. Run 'pip install sentence-transformers'.")
except Exception as e:
    logger.error(f"Error loading Sentence Transformer model: {e}. Semantic deduplication disabled.")


# --- Configuration & Constants ---
# LLM_API_KEY = os.getenv('LLM_API_KEY') # Commented out, Modal handles auth
# LLM_API_URL = os.getenv('LLM_API_URL', "https://api.deepseek.com/chat/completions") # Commented out, Modal endpoint used
LLM_MODEL_NAME = os.getenv('KEYWORD_AGENT_MODEL', "deepseek-R1") # Updated model name
SUMMARY_AGENT_MODEL_NAME = os.getenv('SUMMARY_AGENT_MODEL', "deepseek-R1") # For internal summary, updated

MODAL_APP_NAME = "deepseek-inference-app" # Name of the Modal app
MODAL_CLASS_NAME = "DeepSeekModel" # Name of the class in the Modal app

API_TIMEOUT = 90 # Retained for Modal call options if applicable
MAX_RETRIES = 3 # Retained for application-level retries with Modal
RETRY_DELAY_BASE = 5 # seconds

TARGET_NUM_KEYWORDS = 20 # Final desired number of keywords
MIN_KEYWORD_LENGTH = 2
MIN_REQUIRED_KEYWORDS_FALLBACK = 5 # Used if LLM fails or returns too few
MAX_CONTENT_SNIPPET_LEN = 1500 # Max chars of article content to send to LLM for context
FULL_SUMMARY_THRESHOLD_CHARS = 3000 # If raw_text_full exceeds this, generate a dedicated full summary
MAX_FULL_SUMMARY_TOKENS = 500 # Max tokens for the full article summary LLM call
SEMANTIC_SIMILARITY_THRESHOLD = 0.95 # Threshold for semantic deduplication (0.0-1.0)

# --- Agent Prompts ---

# Stage 0: Full Article Summarization Prompt (Internal)
FULL_SUMMARY_SYSTEM_PROMPT = """
You are an expert AI summarizer. Your task is to condense the provided raw article text into a highly dense, comprehensive, and factual summary. Ensure it captures all key entities, facts, and nuanced points from the original text. The summary should be approximately 300-400 words.
Output ONLY the summary text, no conversational filler or extra formatting.
"""

# Stage 1: Broad Keyword Generation Prompt
KEYWORD_STAGE1_SYSTEM_PROMPT = """
You are an AI agent with ASI-level capabilities in semantic search prediction. Your function is to generate an **expansive, highly relevant, and semantically diverse list of search keyword phrases** for a tech news article. These keywords should represent every conceivable user intent and query a human might realistically type into a search engine to find the given article, encompassing its immediate and future relevance.

**Output Format Constraint:** Your entire output MUST be a JSON list of strings. Do NOT include any other text, explanations, conversational filler, apologies, disclaimers, or formatting outside of this JSON structure. The output must be ONLY the JSON array.

**Instructions & Guidelines for Expansive Keyword Generation:**
1.  **Goal:** Generate a list of **30-40 distinct keyword phrases**. Prioritize breadth and raw diversity.
2.  **Hyper-Relevance & Exhaustive User Intent:** Every keyword MUST demonstrate profound relevance to the provided article content. Anticipate and capture ALL plausible user intents: informational (who, what, when, where), investigational (analysis, impact, reviews), comparative (X vs Y), problem-solving (how-to, troubleshooting), commercial (price, buy, release), and future-oriented (roadmap, future, next-gen). Extrapolate logically within the broader tech domain based on article implications; do NOT invent unrelated topics.
3.  **Semantic Diversity & Predictive Scope:**
    *   **Core Entities:** Prioritize and extract main topics, specific products, precise company names, and key individuals.
    *   **Specificity Spectrum Mastery:** Skillfully blend foundational, broad entry points with precise mid-tail and highly targeted, long-tail (3-5+ words) phrases that address niche user queries and specific data points.
    *   **LSI & Thematic Clusters:** Infer and include latent semantic indexing (LSI) keywords, precise synonyms, hypernyms, hyponyms, and related concepts that construct rich, interconnected thematic clusters around the article's subject matter. Identify underlying topics implied but not explicitly stated.
    *   **Action & Problem/Solution Queries:** If the article discusses a problem, solution, or a process, formulate keywords reflecting these practical applications (e.g., "optimize AI performance," "reduce data center costs," "implement generative AI").
    *   **Comparative & Future-Oriented Queries:** Generate keywords for explicit or implicit comparisons (e.g., "NVIDIA Blackwell B200 vs. Hopper H100," "AI chip benchmark 2024") and for future-looking information (e.g., "Blackwell B200 availability," "NVIDIA next-gen GPU," "AI hardware roadmap").
4.  **Natural Language & Searcher Empathy:** Keywords must flawlessly emulate authentic human search queries, including common industry acronyms, established product names, and relevant colloquialisms if they represent common search patterns. Think with the deepest empathy for a user actively seeking specific information or solutions.
5.  **Uniqueness (Stage 1):** While aiming for breadth, try to ensure keywords are distinct. Semantic deduplication will occur in a later stage.
6.  **Context Provided:** You will receive the following JSON object:
    ```json
    {{
      "Article Title": "SEO H1 / Final Title of the article",
      "Primary Topic Keyword": "Core filtered topic keyword",
      "Processed Summary": "1-2 sentence concise summary of the article",
      "Article Content Snippet": "First 1000-1500 words of the article content for detailed context",
      "Extracted Entities": ["List of key named entities from the full article"],
      "Full Article Summary": "Highly dense summary of the entire article (if article was very long)"
    }}
    ```

**Strict Adherence Rules:**
*   Absolutely no conversational filler.
*   Absolutely no apologies, disclaimers, or any introductory/concluding remarks.
*   Strictly adhere to the JSON list format: `["keyword phrase 1", "keyword phrase 2", "specific entity keyword"]`.
*   Assume the highest level of tech expertise and industry knowledge.
*   The generated output must consist *solely* of the JSON array containing the keyword phrases.
"""

# Stage 2: Keyword Refinement/Selection Prompt
KEYWORD_STAGE2_SYSTEM_PROMPT = """
You are an ASI-level SEO Keyword Curator. Your task is to refine a provided **broad list of keywords** and select the **top {TARGET_NUM_KEYWORDS} hyper-relevant, semantically unique, and impactful keyword phrases**. These selected keywords must fully capture the article's essence, anticipate every user intent, and maximize discoverability.

**Output Format Constraint:** Your entire output MUST be a JSON list of strings. Do NOT include any other text, explanations, conversational filler, apologies, disclaimers, or formatting outside of this JSON structure. The output must be ONLY the JSON array.

**Instructions & Guidelines for Keyword Refinement:**
1.  **Goal:** Select and output **exactly {TARGET_NUM_KEYWORDS} distinct keyword phrases** from the provided broad list, or generate new ones ONLY if absolutely necessary to meet the target count and maintain quality, and they are directly derivable from the original article context.
2.  **Selection Criteria (Prioritized):**
    *   **Semantic Uniqueness:** Eliminate all semantic duplicates or trivial variations. Each selected keyword must target a demonstrably different user intent, semantic angle, or level of specificity.
    *   **Impact & Ranking Power:** Prioritize keywords that are most likely to drive high-quality traffic and represent strong ranking opportunities.
    *   **Comprehensive Coverage:** Ensure the final list covers all core subjects, key entities, and diverse user intents (informational, comparative, future-oriented, problem-solving) as thoroughly as possible from the original article context.
    *   **Relevance:** All selected keywords MUST be directly and profoundly relevant to the original article content.
    *   **Natural Language:** Keywords must flawlessly emulate authentic human search queries.
3.  **Context Provided:** You will receive the following JSON object:
    ```json
    {{
      "Original Article Context": {{
        "Article Title": "SEO H1 / Final Title of the article",
        "Primary Topic Keyword": "Core filtered topic keyword",
        "Processed Summary": "1-2 sentence concise summary of the article",
        "Article Content Snippet": "First 1000-1500 words of the article content for detailed context",
        "Extracted Entities": ["List of key named entities from the full article"],
        "Full Article Summary": "Highly dense summary of the entire article (if article was very long)"
      }},
      "Broad Keyword List for Refinement": ["keyword A", "keyword B", "keyword C", ...]
    }}
    ```

**Strict Adherence Rules:**
*   Absolutely no conversational filler.
*   Absolutely no apologies, disclaimers, or any introductory/concluding remarks.
*   Strictly adhere to the JSON list format: `["keyword phrase 1", "keyword phrase 2", "specific entity keyword"]`.
*   You MUST output exactly {TARGET_NUM_KEYWORDS} keywords. If the broad list is insufficient after deduplication and selection, generate new ones based on the original context until the target is met.
*   Assume the highest level of tech expertise and industry knowledge.
*   The generated output must consist *solely* of the JSON array containing the keyword phrases.
"""
# --- End Agent Prompts ---

# --- Helper Functions ---
def _extract_named_entities(text: str) -> list:
    """Extracts named entities from text using SpaCy."""
    if SPACY_MODEL is None:
        logger.warning("SpaCy model not loaded. Skipping entity extraction.")
        return []
    
    entities = set()
    try:
        doc = SPACY_MODEL(text)
        for ent in doc.ents:
            if ent.label_ in ["ORG", "PERSON", "PRODUCT", "LOC", "GPE", "NORP", "EVENT", "WORK_OF_ART", "FACILITY", "LANGUAGE"]:
                entity_text = ent.text.strip().replace('\n', ' ').replace('\r', '').replace('  ', ' ')
                if entity_text and len(entity_text) > 1:
                    entities.add(entity_text)
    except Exception as e:
        logger.error(f"Error during SpaCy entity extraction: {e}")
    return list(entities)

def _semantically_deduplicate_keywords(keywords_list: list, primary_topic_keyword: str, similarity_threshold: float = SEMANTIC_SIMILARITY_THRESHOLD) -> list:
    """
    Deduplicates a list of keywords based on semantic similarity using Sentence Transformers.
    Prioritizes keywords based on containing the primary topic keyword or being shorter.
    """
    if SENTENCE_MODEL is None or SENTENCE_UTIL is None or not keywords_list:
        logger.warning("Sentence Transformer not loaded or keyword list is empty. Skipping semantic deduplication.")
        return keywords_list

    primary_topic_lower = primary_topic_keyword.lower()
    final_unique_keywords = []
    
    try:
        embeddings = SENTENCE_MODEL.encode(keywords_list, convert_to_tensor=True, show_progress_bar=False)
        cosine_scores = SENTENCE_UTIL.pytorch_cos_sim(embeddings, embeddings)

        # Map original indices to their current status (True = keep, False = remove)
        keep_status = [True] * len(keywords_list)

        for i in range(len(keywords_list)):
            if not keep_status[i]: continue

            for j in range(i + 1, len(keywords_list)):
                if not keep_status[j]: continue

                if cosine_scores[i][j] >= similarity_threshold:
                    kw_i = keywords_list[i]
                    kw_j = keywords_list[j]
                    
                    # Heuristic: Prioritize keyword containing primary_topic_keyword
                    i_has_pk = primary_topic_lower in kw_i.lower()
                    j_has_pk = primary_topic_lower in kw_j.lower()

                    if i_has_pk and not j_has_pk:
                        keep_status[j] = False
                        logger.debug(f"Removed semantically similar (PK preference): '{kw_j}' (similar to '{kw_i}' score: {cosine_scores[i][j]:.2f})")
                    elif j_has_pk and not i_has_pk:
                        keep_status[i] = False
                        logger.debug(f"Removed semantically similar (PK preference): '{kw_i}' (similar to '{kw_j}' score: {cosine_scores[i][j]:.2f})")
                        break # j replaced i, so re-evaluate j against others
                    else: # Both or neither contain PK, prefer shorter
                        if len(kw_i) <= len(kw_j):
                            keep_status[j] = False
                            logger.debug(f"Removed semantically similar (Length preference): '{kw_j}' (similar to '{kw_i}' score: {cosine_scores[i][j]:.2f})")
                        else:
                            keep_status[i] = False
                            logger.debug(f"Removed semantically similar (Length preference): '{kw_i}' (similar to '{kw_j}' score: {cosine_scores[i][j]:.2f})")
                            break # j replaced i, so re-evaluate j against others
        
        for i, keyword in enumerate(keywords_list):
            if keep_status[i]:
                final_unique_keywords.append(keyword)

    except Exception as e:
        logger.error(f"Error during semantic deduplication: {e}. Returning original list. Error: {e}")
        return keywords_list
    
    logger.info(f"Semantic deduplication reduced {len(keywords_list)} to {len(final_unique_keywords)} keywords.")
    return final_unique_keywords

def _format_user_prompt_content(user_data_dict: dict) -> str:
    """Formats a dictionary into a human-readable string for the LLM user message."""
    user_prompt_content = ""
    for key, value in user_data_dict.items():
        user_prompt_content += f"**{key}**:\n"
        if isinstance(value, list) or isinstance(value, dict):
            user_prompt_content += f"{json.dumps(value, indent=2)}\n\n"
        else:
            user_prompt_content += f"{value}\n\n"
    user_prompt_content += "Strictly adhere to the JSON list output format as instructed in your system prompt."
    return user_prompt_content

def _call_llm(system_prompt: str, user_prompt_data: dict, max_tokens: int, temperature: float, model_name: str) -> str | None:
    """Generic function to call LLM API using Modal with retry logic."""
    # LLM_API_KEY check not needed for Modal

    user_prompt_string = _format_user_prompt_content(user_prompt_data)

    messages_for_modal = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt_string}
    ]

    # Temperature and response_format are assumed to be handled by the Modal class
    # or can be passed to generate.remote if the Modal class supports them.
    # model_name (e.g. "deepseek-R1") is for logging/config; actual model used is defined in Modal class.

    for attempt in range(MAX_RETRIES):
        try:
            logger.debug(f"Modal API call attempt {attempt + 1}/{MAX_RETRIES} for keywords (model config: {model_name})")
            
            ModelClass = modal.Function.lookup(MODAL_APP_NAME, MODAL_CLASS_NAME)
            if not ModelClass:
                logger.error(f"Could not find Modal function {MODAL_APP_NAME}/{MODAL_CLASS_NAME}. Ensure it's deployed.")
                if attempt == MAX_RETRIES - 1: return None # Last attempt
                delay = min(RETRY_DELAY_BASE * (2 ** attempt), 60) # Using global RETRY_DELAY_BASE
                logger.info(f"Waiting {delay}s for Modal function lookup before retry...")
                time.sleep(delay)
                continue
            
            model_instance = ModelClass()

            result = model_instance.generate.remote(
                messages=messages_for_modal,
                max_new_tokens=max_tokens
                # temperature=temperature, # If Modal class supports it
                # response_format={"type": "json_object"} # If Modal class supports it
            )

            if result and result.get("choices") and result["choices"][0].get("message") and \
               isinstance(result["choices"][0]["message"].get("content"), str):
                content = result["choices"][0]["message"]["content"].strip()
                logger.info(f"Modal call successful for keywords (Attempt {attempt+1}/{MAX_RETRIES})")
                return content
            else:
                logger.error(f"Modal API response missing content or malformed (attempt {attempt + 1}/{MAX_RETRIES}): {str(result)[:500]}")
                if attempt == MAX_RETRIES - 1: return None
        
        except Exception as e:
            logger.exception(f"Error during Modal API call for keywords (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt == MAX_RETRIES - 1:
                logger.error("All Modal API attempts for keywords failed due to errors.")
                return None
        
        delay = min(RETRY_DELAY_BASE * (2 ** attempt), 60) # Using global RETRY_DELAY_BASE
        logger.warning(f"Modal API call for keywords failed or returned unexpected data (attempt {attempt+1}/{MAX_RETRIES}). Retrying in {delay}s.")
        time.sleep(delay)
        
    logger.error(f"Modal LLM API call for keywords failed after {MAX_RETRIES} attempts.")
    return None

def _parse_llm_keyword_response(json_string: str) -> list | None:
    """Parses LLM JSON response and extracts keyword list."""
    if not json_string: return None
    try:
        match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', json_string, re.DOTALL | re.IGNORECASE)
        json_to_parse = match.group(1) if match else json_string
        
        parsed_json = json.loads(json_to_parse)
        if isinstance(parsed_json, list):
            return parsed_json
        if isinstance(parsed_json, dict) and "keywords" in parsed_json and isinstance(parsed_json["keywords"], list):
            return parsed_json["keywords"]
        logger.warning(f"LLM returned JSON, but not in expected list or {{'keywords': list}} format: {json_string}")
        return None
    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON from LLM keyword response: {json_string}")
        return None
    except Exception as e:
        logger.error(f"Error parsing LLM keyword response: {e}")
        return None

def _generate_full_summary(raw_text_full: str, article_id: str) -> str:
    """Generates a comprehensive summary of a very long article using an LLM."""
    logger.info(f"Generating full summary for very long article {article_id}...")
    summary_user_prompt_data = {"Article Content": raw_text_full}
    summary_raw_response = _call_llm(
        system_prompt=FULL_SUMMARY_SYSTEM_PROMPT,
        user_prompt_data=summary_user_prompt_data,
        max_tokens=MAX_FULL_SUMMARY_TOKENS,
        temperature=0.3, # Low temperature for factual summary
        model_name=SUMMARY_AGENT_MODEL_NAME
    )
    if summary_raw_response:
        logger.info(f"Full summary generated for {article_id}.")
        return summary_raw_response
    else:
        logger.error(f"Failed to generate full summary for {article_id}. Using original processed_summary.")
        return ""


# --- Main Agent Function ---
def run_keyword_generator_agent(article_pipeline_data: dict) -> dict:
    article_id = article_pipeline_data.get('id', 'unknown_id')
    logger.info(f"--- Running Keyword Generator Agent for Article ID: {article_id} ---")

    # 1. Prepare input data
    article_title = article_pipeline_data.get('generated_seo_h1', article_pipeline_data.get('initial_title_from_web', "No Title Provided"))
    raw_text_full = article_pipeline_data.get('raw_scraped_text', article_pipeline_data.get('processed_summary', ''))
    processed_summary = article_pipeline_data.get('processed_summary', '')
    primary_topic_keyword = article_pipeline_data.get('primary_topic_keyword', article_title)
    if not primary_topic_keyword: primary_topic_keyword = article_title

    # Generate full article summary if article is very long
    full_article_summary = ""
    if len(raw_text_full) > FULL_SUMMARY_THRESHOLD_CHARS:
        full_article_summary = _generate_full_summary(raw_text_full, article_id)
    else:
        logger.debug(f"Article {article_id} is not long enough ({len(raw_text_full)} chars) for dedicated full summary. Using processed summary for extended context.")

    # Extract entities from the full text for deeper context
    extracted_entities = _extract_named_entities(raw_text_full)
    if not extracted_entities:
        logger.info(f"No named entities extracted for {article_id}. This is okay if text is short/generic.")

    # Prepare article content snippet for LLM (main context for keyword generation)
    content_snippet_for_llm = raw_text_full
    if len(raw_text_full) > MAX_CONTENT_SNIPPET_LEN:
        content_snippet_for_llm = raw_text_full[:MAX_CONTENT_SNIPPET_LEN] + "..."
        logger.debug(f"Truncated raw article content snippet for LLM keyword prompt (ID: {article_id})")

    # Combine input data for LLM
    llm_input_context = {
        "Article Title": article_title,
        "Primary Topic Keyword": primary_topic_keyword,
        "Processed Summary": processed_summary,
        "Article Content Snippet": content_snippet_for_llm,
        "Extracted Entities": extracted_entities,
        "Full Article Summary": full_article_summary # Will be empty string if not generated
    }

    # 2. Stage 1: Broad Keyword Generation
    logger.info(f"Stage 1: Generating broad keyword list for {article_id}...")
    stage1_raw_response = _call_llm(
        system_prompt=KEYWORD_STAGE1_SYSTEM_PROMPT,
        user_prompt_data=llm_input_context,
        max_tokens=800, # More tokens for broader list
        temperature=0.7, # Slightly higher for more diversity
        model_name=LLM_MODEL_NAME
    )
    broad_keywords = _parse_llm_keyword_response(stage1_raw_response)
    if not broad_keywords:
        logger.error(f"Stage 1 failed to generate broad keywords for {article_id}. Skipping Stage 2.")
        article_pipeline_data['keyword_agent_error'] = "Stage 1 keyword generation failed."
        broad_keywords = []

    # 3. Stage 2: Keyword Refinement/Selection
    logger.info(f"Stage 2: Refining and selecting top keywords for {article_id}...")
    if broad_keywords:
        llm_refinement_input = {
            "Original Article Context": llm_input_context,
            "Broad Keyword List for Refinement": broad_keywords
        }
        stage2_raw_response = _call_llm(
            system_prompt=KEYWORD_STAGE2_SYSTEM_PROMPT.format(TARGET_NUM_KEYWORDS=TARGET_NUM_KEYWORDS),
            user_prompt_data=llm_refinement_input,
            max_tokens=500,
            temperature=0.6, # Lower temperature for precision
            model_name=LLM_MODEL_NAME
        )
        refined_keywords = _parse_llm_keyword_response(stage2_raw_response)
        if not refined_keywords:
            logger.error(f"Stage 2 failed to refine keywords for {article_id}. Using broad list if available.")
            article_pipeline_data['keyword_agent_error'] = (article_pipeline_data.get('keyword_agent_error', '') + "Stage 2 refinement failed.").strip()
            refined_keywords = broad_keywords # Fallback to broad list if refinement fails
    else:
        refined_keywords = []
        logger.warning(f"No broad keywords from Stage 1 for {article_id}, skipping Stage 2.")

    # 4. Semantic Deduplication and Final Selection
    final_keyword_list = []
    if refined_keywords:
        semantically_unique_keywords = _semantically_deduplicate_keywords(refined_keywords, primary_topic_keyword, SEMANTIC_SIMILARITY_THRESHOLD)
        
        # Ensure primary topic keyword is at the start if not already included
        if primary_topic_keyword:
            ptk_lower = primary_topic_keyword.lower()
            if not any(fk.lower() == ptk_lower for fk in semantically_unique_keywords):
                semantically_unique_keywords.insert(0, primary_topic_keyword.strip())

        # Trim or pad to TARGET_NUM_KEYWORDS
        if len(semantically_unique_keywords) > TARGET_NUM_KEYWORDS:
            final_keyword_list = semantically_unique_keywords[:TARGET_NUM_KEYWORDS]
            logger.info(f"Trimmed keywords to {TARGET_NUM_KEYWORDS} for {article_id}.")
        elif len(semantically_unique_keywords) < TARGET_NUM_KEYWORDS:
            final_keyword_list = semantically_unique_keywords
            logger.warning(f"Less than {TARGET_NUM_KEYWORDS} unique keywords found for {article_id} ({len(final_keyword_list)}). Supplementing.")
            title_summary_phrases = re.findall(r'\b[a-zA-Z0-9\s-]{3,}\b', (article_title + " " + processed_summary).lower())
            for phrase in list(dict.fromkeys(title_summary_phrases)):
                if len(final_keyword_list) >= TARGET_NUM_KEYWORDS: break
                clean_phrase = phrase.strip()
                if len(clean_phrase) >= MIN_KEYWORD_LENGTH and clean_phrase.lower() not in (k.lower() for k in final_keyword_list):
                    final_keyword_list.append(clean_phrase)
        else:
            final_keyword_list = semantically_unique_keywords

    # 5. Fallback if no LLM-generated keywords at all
    if not final_keyword_list:
        logger.warning(f"No LLM-generated keywords for {article_id}. Applying robust fallback.")
        article_pipeline_data['keyword_agent_error'] = (article_pipeline_data.get('keyword_agent_error', '') + "No keywords from LLM. Fallback applied.").strip()
        
        if primary_topic_keyword and primary_topic_keyword.strip():
            final_keyword_list.append(primary_topic_keyword.strip())

        for entity in extracted_entities:
            if len(final_keyword_list) >= MIN_REQUIRED_KEYWORDS_FALLBACK: break
            if entity.lower() not in (k.lower() for k in final_keyword_list):
                final_keyword_list.append(entity)

        title_phrases = re.findall(r'\b[a-zA-Z0-9\s-]{3,}\b', article_title.lower())
        for phrase in list(dict.fromkeys(title_phrases)):
            if len(final_keyword_list) >= MIN_REQUIRED_KEYWORDS_FALLBACK: break
            clean_phrase = phrase.strip()
            if len(clean_phrase) >= MIN_KEYWORD_LENGTH and clean_phrase.lower() not in (k.lower() for k in final_keyword_list):
                final_keyword_list.append(clean_phrase)
        
        if not final_keyword_list:
            final_keyword_list.append("Tech News")
            final_keyword_list.append("AI Update")
            logger.warning(f"Extreme fallback: Added generic keywords for {article_id}.")

    # Final cleanup and update pipeline data
    final_keyword_list = list(dict.fromkeys(final_keyword_list))[:TARGET_NUM_KEYWORDS] # Final literal dedupe and trim
    article_pipeline_data['final_keywords'] = final_keyword_list
    article_pipeline_data['keyword_agent_status'] = "SUCCESS" if not article_pipeline_data.get('keyword_agent_error') else "FAILED_WITH_FALLBACK"

    logger.info(f"Keyword Generator Agent for {article_id} status: {article_pipeline_data['keyword_agent_status']}.")
    logger.info(f"  Final keywords ({len(article_pipeline_data['final_keywords'])}): {article_pipeline_data['final_keywords']}")
    return article_pipeline_data

# --- Standalone Execution ---
if __name__ == "__main__":
    logger.info("--- Starting Keyword Generator Agent Standalone Test ---")
    
    # IMPORTANT: Ensure SpaCy model is downloaded for full functionality!
    # Run this command in your terminal if you see 'SpaCy model not found' warnings:
    # python -m spacy download en_core_web_sm

    # if not os.getenv('LLM_API_KEY'): # Modal handles auth
    #     logger.error("LLM_API_KEY env var not set. Test aborted.")
    #     sys.exit(1)

    test_article_data = {
        'id': 'test_kw_gen_001_multi_stage',
        'generated_seo_h1': "Pope Francis Warns G7 Leaders About AI's 'Ethical Deterioration' and Impact on Humanity",
        'raw_scraped_text': """
Pope Francis took his call for artificial intelligence to be developed and used ethically to the Group of Seven industrialized nations Friday, telling leaders that AI must never be allowed to get the upper hand over humans. He also renewed his warning about its use in warfare.
Francis became the first pope to address a G7 summit. He was invited by host Italy to speak at a special session on the perils and promises of AI.
He told leaders of the U.S., Britain, Canada, France, Germany, Japan and Italy that AI is an “exciting” and “frightening” tool that requires urgent political action to ensure it remains human-centric.
“We would condemn humanity to a future without hope if we took away people’s ability to make decisions about themselves and their lives, by dooming them to depend on the choices of machines,” Francis said. “We need to ensure and safeguard a space for proper human control over the choices made by artificial intelligence programs: Human dignity itself depends on it.”
The pope has spoken about AI multiple times. He believes it offers great potential for good, but also risks exacerbating inequalities and could have a devastating impact if its development isn’t guided by ethics and a sense of the common good.
He brought those concerns to the G7, where he also warned against AI's use in the military. “No machine should ever choose to take the life of a human being,” he said, adding that people must never let algorithms decide such fundamental questions.
He urged politicians to take the lead in making AI human-centric, so that “decision-making, even when it comes to the different and oftentimes complex choices that this entails, always remains with the human person.”
His remarks came as G7 leaders pledged to coordinate their approaches to governing AI to make sure it is "human-centered, trustworthy, and responsible."
The pope was also expected to raise the issue of AI's impact on the Global South, where developing countries often bear the brunt of environmental damage caused by resource extraction needed for tech manufacturing, and where algorithms can perpetuate biases.
        """,
        'primary_topic_keyword': 'Pope AI ethics warning',
        'processed_summary': "Pope Francis addresses G7 summit on AI ethics, warning against AI overpowering humans and urging human-centric development."
    }

    test_long_text_data = {
        'id': 'test_kw_gen_002_long_text',
        'generated_seo_h1': "Breakthrough in Quantum Computing Achieves Stable Qubit Coherence for Longer Periods",
        'raw_scraped_text': """
In a monumental stride for quantum computing, researchers at the Quantum Innovation Labs (QIL) have announced a breakthrough in maintaining qubit coherence for unprecedented durations. This achievement, detailed in a paper published in 'Nature Physics', pushes the boundaries of what was previously thought possible in scaling quantum systems. The team, led by Dr. Anya Sharma, utilized a novel superconducting circuit design combined with advanced cryogenic cooling techniques to shield qubits from environmental decoherence.

Traditional quantum processors struggle with coherence times, which often limit the complexity and reliability of computations. By extending coherence from microseconds to several milliseconds, QIL's new approach significantly reduces error rates and opens the door for more complex algorithms. This could accelerate the development of practical quantum computers, impacting fields from drug discovery to financial modeling. Competitors like Google Quantum AI and IBM Quantum have also been making significant progress in this area, but QIL's method appears to offer a distinct advantage in coherence longevity.

The new design focuses on a "protected qubit" architecture, where superconducting transmon qubits are integrated into a unique 3D cavity resonator. This resonator acts as a natural shield against stray electromagnetic fields, a primary source of decoherence. Furthermore, the team implemented a pulsed-laser calibration system that continuously monitors and corrects phase errors in real-time, without collapsing the superposition states. This real-time error mitigation is a crucial step towards fault-tolerant quantum computing.

Dr. Sharma emphasized that while the current experiment involved a small number of qubits (initially 5, scaled to 10 for demonstration), the principles are highly scalable. "This isn't just about longer coherence; it's about a foundational understanding of how to engineer quantum states with unprecedented control," she stated in a press conference. She highlighted the potential for scaling to hundreds or thousands of qubits in the next decade, a necessary step for tackling truly transformative problems.

The implications for industries are vast. In pharmaceuticals, it could lead to the simulation of molecular interactions with unparalleled accuracy, designing new drugs faster and more efficiently. For materials science, it promises to unlock new properties for next-generation batteries and catalysts. Financial institutions could use it for complex optimization problems, such as portfolio management and risk assessment, far beyond classical computing capabilities. Even cybersecurity could see a paradigm shift, as quantum computers pose both threats and potential solutions to current encryption methods.

The research was supported by a substantial grant from the National Science Foundation and various private sector partners interested in accelerating quantum technology. The team plans to open-source aspects of their calibration software to foster broader community collaboration and accelerate further research. This collaborative spirit, according to Dr. Sharma, is essential for reaching quantum advantage sooner. The next steps involve integrating more qubits and testing the architecture's performance on known quantum algorithms like Shor's algorithm for factoring and Grover's algorithm for database search. The challenges ahead include perfecting fabrication techniques at larger scales and developing new error correction codes optimized for their protected qubit design. This truly represents a significant leap forward in the quest for a practical quantum computer.
        """,
        'primary_topic_keyword': 'Quantum Computing Coherence Breakthrough',
        'processed_summary': "Researchers achieve breakthrough in quantum computing, maintaining qubit coherence for unprecedented durations, paving way for practical quantum computers."
    }

    result_data_1 = run_keyword_generator_agent(test_article_data.copy())
    logger.info("\n--- Keyword Generator Results (Test 1) ---")
    logger.info(f"Status: {result_data_1.get('keyword_agent_status')}")
    if result_data_1.get('keyword_agent_error'):
        logger.error(f"Error: {result_data_1.get('keyword_agent_error')}")
    logger.info(f"Final Keywords ({len(result_data_1.get('final_keywords', []))}): {result_data_1.get('final_keywords')}")

    logger.info("\n--- Keyword Generator Results (Test 2: Long Text) ---")
    result_data_2 = run_keyword_generator_agent(test_long_text_data.copy())
    logger.info(f"Status: {result_data_2.get('keyword_agent_status')}")
    if result_data_2.get('keyword_agent_error'):
        logger.error(f"Error: {result_data_2.get('keyword_agent_error')}")
    logger.info(f"Final Keywords ({len(result_data_2.get('final_keywords', []))}): {result_data_2.get('final_keywords')}")

    logger.info("--- Keyword Generator Agent Standalone Test Complete ---")