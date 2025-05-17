# src/agents/keyword_intelligence_agent.py

import os
import sys
import json
import logging
import requests # For Ollama
import re
from collections import Counter

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
# Use a powerful model for nuanced keyword strategy
OLLAMA_KEYWORD_MODEL = "mixtral:latest" # or "llama3:70b" if resources/time allow
# OLLAMA_KEYWORD_MODEL = "mistral:latest" # Faster, less nuanced alternative for testing

MAX_CONTENT_SNIPPET_FOR_LLM = 2000 # Characters of article content to send to LLM
TARGET_PRIMARY_KEYWORDS = 1 # Usually one, but LLM might suggest a very close variant
TARGET_SECONDARY_KEYWORDS = 8
TARGET_LONGTAIL_KEYWORDS = 5
TARGET_ENTITY_KEYWORDS = 4
TOTAL_KEYWORDS_AIM = 15 # Approximate total after deduplication

# --- Agent Prompts ---
KEYWORD_INTELLIGENCE_PROMPT_TEMPLATE = """
You are an ASI-level SEO Keyword Intelligence Strategist. Your task is to analyze the provided article content and generate a comprehensive, highly relevant, and strategically diverse set of keywords.

**Article Information:**
Title: {article_title}
Processed Summary (for context): {processed_summary}
Primary Topic (from earlier filter): {primary_topic_from_filter}
Initial Candidate Keywords (from earlier filter): {initial_candidate_keywords_str}
Full Article Snippet (first {max_content_snippet_for_llm} chars for deep analysis):
{article_content_snippet}

**Instructions for Keyword Generation:**

1.  **Primary Keyword(s) (Target: {target_primary_keywords}):**
    *   Re-evaluate or confirm the `Primary Topic (from earlier filter)`.
    *   Generate the single most dominant, high-intent primary keyword phrase for this article. It should encapsulate the core subject.
    *   Consider if a very close variant is also essential.

2.  **Secondary/LSI Keywords (Target: {target_secondary_keywords}):**
    *   Generate a list of semantically related keywords and Latent Semantic Indexing (LSI) terms.
    *   These should cover sub-topics, related concepts, synonyms, and alternative phrasings.
    *   Think about different facets of the main topic.

3.  **Long-Tail Keywords (Question-Style) (Target: {target_longtail_keywords}):**
    *   Generate keywords in the form of questions that users might ask, which this article answers.
    *   Examples: "What is [topic]?", "How does [technology] work?", "Best [product type] for [use case]?"

4.  **Entity Keywords (People, Orgs, Products) (Target: {target_entity_keywords}):**
    *   Identify and list key named entities (people, organizations, products, technologies, specific events) mentioned in the article that users might search for directly in relation to this news.
    *   Prioritize entities central to the article's narrative.

5.  **Strategic Considerations (Internal Monologue - Apply to all keyword types):**
    *   **User Intent:** Consider informational, navigational, commercial, and transactional intents.
    *   **Search Volume (Simulated):** Prioritize terms likely to have reasonable search interest. (You are simulating expertise here).
    *   **Competition (Simulated):** Balance high-volume terms with more niche, achievable long-tail keywords.
    *   **Relevance & Specificity:** All keywords MUST be directly and highly relevant. Avoid overly broad terms unless they are the core topic.
    *   **Natural Language:** Keywords should be phrases users would actually type.

**Output Format (Strictly JSON):**
Provide ONLY a valid JSON object with the following structure:
{{
  "analyzed_primary_keyword": "string", // Your top choice for the primary keyword
  "secondary_lsi_keywords": ["string1", "string2", ...],
  "long_tail_question_keywords": ["string1", "string2", ...],
  "entity_keywords": ["string1", "string2", ...],
  "keyword_strategy_notes": "Brief notes on your reasoning or any challenges." // e.g., "Focused on informational intent for a new technology."
}}
"""

def call_ollama_for_keywords(article_title, processed_summary, primary_topic_from_filter, initial_candidate_keywords, article_content_snippet):
    """Uses Ollama to generate a structured set of keywords."""
    
    initial_candidate_keywords_str = ", ".join(initial_candidate_keywords) if initial_candidate_keywords else "None provided"
    
    prompt = KEYWORD_INTELLIGENCE_PROMPT_TEMPLATE.format(
        article_title=article_title,
        processed_summary=processed_summary,
        primary_topic_from_filter=primary_topic_from_filter,
        initial_candidate_keywords_str=initial_candidate_keywords_str,
        article_content_snippet=article_content_snippet,
        max_content_snippet_for_llm=MAX_CONTENT_SNIPPET_FOR_LLM,
        target_primary_keywords=TARGET_PRIMARY_KEYWORDS,
        target_secondary_keywords=TARGET_SECONDARY_KEYWORDS,
        target_longtail_keywords=TARGET_LONGTAIL_KEYWORDS,
        target_entity_keywords=TARGET_ENTITY_KEYWORDS
    )
    payload = {
        "model": OLLAMA_KEYWORD_MODEL,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        # "options": {"temperature": 0.5} # Adjust temperature if needed for keyword diversity
    }
    try:
        logger.debug(f"Sending keyword intelligence request to Ollama for title: {article_title[:50]}...")
        # Increased timeout for more complex keyword generation
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=120)
        response.raise_for_status()
        
        response_json = response.json()
        generated_json_string = response_json.get("response")

        if not generated_json_string:
            logger.error(f"Ollama keyword intelligence response missing 'response' field or empty: {response_json}")
            return None
        
        try:
            keyword_analysis_result = json.loads(generated_json_string)
            required_keys = ["analyzed_primary_keyword", "secondary_lsi_keywords", "long_tail_question_keywords", "entity_keywords"]
            if all(key in keyword_analysis_result for key in required_keys):
                logger.info(f"Ollama keyword intelligence successful for: {article_title[:50]}")
                return keyword_analysis_result
            else:
                logger.error(f"Ollama keyword intelligence returned JSON missing required keys: {keyword_analysis_result}")
                return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON from Ollama keyword intelligence response: {generated_json_string}. Error: {e}")
            return None
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Ollama API request for keyword intelligence failed: {e}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error in call_ollama_for_keywords: {e}")
        return None

def clean_and_deduplicate_keywords(keyword_list):
    if not keyword_list:
        return []
    cleaned_list = []
    seen_keywords_lower = set()
    for kw_item in keyword_list:
        if not isinstance(kw_item, str):
            continue
        # Basic cleaning: strip whitespace, remove excessive internal spaces, common punctuation issues
        kw = kw_item.strip()
        kw = re.sub(r'\s{2,}', ' ', kw) # Replace multiple spaces with single
        kw = kw.replace(':', '').replace('"', '').replace("'", "") # Remove some common punc
        kw = kw.rstrip('?.!,;') # Strip trailing punc

        if not kw or len(kw) < 3: # Skip very short or empty keywords
            continue
            
        kw_lower = kw.lower()
        if kw_lower not in seen_keywords_lower:
            cleaned_list.append(kw) # Add original casing
            seen_keywords_lower.add(kw_lower)
    return cleaned_list


def run_keyword_intelligence_agent(article_pipeline_data):
    """
    Generates a comprehensive keyword profile for an article.
    Expected input keys: 'id', 'initial_title_from_web', 'processed_summary', 
                         'primary_topic' (from filter_enrich), 'candidate_keywords' (from filter_enrich),
                         'raw_scraped_text'.
    Adds/updates keys: 'final_keywords', 'keyword_profile' (dict with categorized keywords),
                       'keyword_generation_status'.
    """
    article_id = article_pipeline_data.get('id', 'unknown_id')
    title = article_pipeline_data.get('initial_title_from_web', 'No Title')
    processed_summary = article_pipeline_data.get('processed_summary', '')
    primary_topic_from_filter = article_pipeline_data.get('primary_topic', title) # Fallback
    initial_candidates = article_pipeline_data.get('candidate_keywords', [])
    raw_text = article_pipeline_data.get('raw_scraped_text', '')
    content_snippet = raw_text[:MAX_CONTENT_SNIPPET_FOR_LLM]

    logger.info(f"--- Running Keyword Intelligence Agent for Article ID: {article_id} ---")

    if not title and not processed_summary and not content_snippet:
        logger.warning(f"Article {article_id} has insufficient text content for keyword intelligence. Skipping.")
        article_pipeline_data['final_keywords'] = initial_candidates if initial_candidates else [primary_topic_from_filter or "General"]
        article_pipeline_data['keyword_profile'] = {}
        article_pipeline_data['keyword_generation_status'] = "SKIPPED_INSUFFICIENT_CONTENT"
        return article_pipeline_data

    llm_keyword_profile = call_ollama_for_keywords(
        title, processed_summary, primary_topic_from_filter, initial_candidates, content_snippet
    )

    all_generated_keywords_from_llm = []
    if llm_keyword_profile and isinstance(llm_keyword_profile, dict):
        article_pipeline_data['keyword_profile'] = llm_keyword_profile # Store the raw structured output
        article_pipeline_data['keyword_generation_status'] = "LLM_SUCCESS"
        
        # Consolidate all keywords from LLM analysis
        if isinstance(llm_keyword_profile.get('analyzed_primary_keyword'), str):
            all_generated_keywords_from_llm.append(llm_keyword_profile['analyzed_primary_keyword'])
        if isinstance(llm_keyword_profile.get('secondary_lsi_keywords'), list):
            all_generated_keywords_from_llm.extend(llm_keyword_profile['secondary_lsi_keywords'])
        if isinstance(llm_keyword_profile.get('long_tail_question_keywords'), list):
            all_generated_keywords_from_llm.extend(llm_keyword_profile['long_tail_question_keywords'])
        if isinstance(llm_keyword_profile.get('entity_keywords'), list):
            all_generated_keywords_from_llm.extend(llm_keyword_profile['entity_keywords'])
        
        logger.info(f"LLM generated keyword profile for {article_id}. Notes: {llm_keyword_profile.get('keyword_strategy_notes')}")
    else:
        logger.error(f"LLM keyword intelligence failed for {article_id}. Using initial candidates as fallback.")
        article_pipeline_data['keyword_profile'] = {}
        article_pipeline_data['keyword_generation_status'] = "LLM_FAILED_FALLBACK_TO_INITIAL"
        # Fallback to initial candidates if LLM fails
        all_generated_keywords_from_llm.extend(initial_candidates)
        if primary_topic_from_filter:
             all_generated_keywords_from_llm.append(primary_topic_from_filter)


    # Clean, deduplicate, and finalize the list
    final_cleaned_keywords = clean_and_deduplicate_keywords(all_generated_keywords_from_llm)
    
    # Ensure the primary topic (from filter, or LLM's analyzed one) is prioritized if good
    priority_keyword = llm_keyword_profile.get('analyzed_primary_keyword') if llm_keyword_profile else primary_topic_from_filter
    if priority_keyword and isinstance(priority_keyword, str) and len(priority_keyword.strip()) >=3 :
        priority_kw_clean = priority_keyword.strip()
        # Remove if already present (case-insensitive) then add to front
        final_cleaned_keywords = [kw for kw in final_cleaned_keywords if kw.lower() != priority_kw_clean.lower()]
        final_cleaned_keywords.insert(0, priority_kw_clean)

    # Limit total number of keywords
    article_pipeline_data['final_keywords'] = final_cleaned_keywords[:TOTAL_KEYWORDS_AIM]
    
    logger.info(f"Final keywords for {article_id} ({len(article_pipeline_data['final_keywords'])}): {article_pipeline_data['final_keywords']}")
    return article_pipeline_data


# --- Standalone Execution Example ---
if __name__ == "__main__":
    if not logger.handlers:
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
                            format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')

    logger.info("--- Starting Keyword Intelligence Agent Standalone Test ---")
    # Ensure Ollama is running with your OLLAMA_KEYWORD_MODEL (e.g., mixtral or llama3:70b)

    sample_article_data_for_keywords = {
        'id': 'test_kw_001',
        'initial_title_from_web': "NVIDIA Blackwell B200 GPU: A New Era for AI Supercomputing and Trillion-Parameter Models",
        'processed_summary': "NVIDIA has unveiled its Blackwell B200 GPU, succeeding the H100. It promises massive performance gains for AI training and inference, particularly for trillion-parameter large language models. The new architecture features enhanced tensor cores, significantly more memory bandwidth, and improved energy efficiency. CEO Jensen Huang highlighted its role in powering next-generation data centers and accelerating scientific discovery.",
        'primary_topic': "AI Hardware", # From filter_enrich_agent
        'candidate_keywords': ["NVIDIA Blackwell", "B200 GPU", "AI Supercomputing"], # From filter_enrich_agent
        'raw_scraped_text': """
        NVIDIA's GTC conference today was dominated by the announcement of the Blackwell B200 GPU, the company's next-generation AI accelerator.
        This powerhouse chip is set to replace the highly successful Hopper H100/H200 series.
        CEO Jensen Huang presented benchmarks indicating up to a 4x improvement in training performance and a 30x leap in inference for large language models (LLMs) compared to the H100.
        The Blackwell platform is built on a custom TSMC 4NP process and boasts 208 billion transistors. Each B200 GPU offers up to 20 petaFLOPS of AI performance.
        It integrates two GPU dies connected via a 10 TB/s NVLink C2C interconnect.
        Memory sees a significant upgrade with HBM3e, providing 8 TB/s of memory bandwidth.
        NVIDIA also announced the GB200 Grace Blackwell Superchip, which pairs two B200 GPUs with a Grace CPU.
        These advancements are critical for handling the demands of emerging trillion-parameter models and complex generative AI tasks.
        "Blackwell is not just a chip, it's a platform," Huang emphasized, detailing new networking capabilities with NVLink Switch and Quantum InfiniBand.
        The company expects Blackwell systems, like the DGX B200, to be adopted by major cloud providers and enterprises starting late 2024.
        The focus on energy efficiency was also prominent, with claims of up to 25x better performance per watt over the H100 for LLM inference.
        """
    }

    result_data = run_keyword_intelligence_agent(sample_article_data_for_keywords.copy())

    logger.info("\n--- Keyword Intelligence Test Results ---")
    logger.info(f"Keyword Generation Status: {result_data.get('keyword_generation_status')}")
    logger.info(f"Keyword Profile from LLM:\n{json.dumps(result_data.get('keyword_profile'), indent=2)}")
    logger.info(f"\nFinal Keywords for Article ({len(result_data.get('final_keywords',[]))}):")
    for kw in result_data.get('final_keywords', []):
        logger.info(f"  - {kw}")

    logger.info("--- Keyword Intelligence Agent Standalone Test Complete ---")