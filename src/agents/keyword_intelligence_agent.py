# src/agents/keyword_intelligence_agent.py

import os
import sys
import json
import logging
import requests # For DeepSeek API
import re
from collections import Counter

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
logger.setLevel(logging.DEBUG)

# --- Configuration ---
DEEPSEEK_API_KEY_KW = os.getenv('DEEPSEEK_API_KEY') # KW for Keyword
DEEPSEEK_CHAT_API_URL_KW = "https://api.deepseek.com/chat/completions"
# For keyword strategy, a more capable model is good.
# "deepseek-chat" is a strong general model.
DEEPSEEK_MODEL_FOR_KEYWORDS = "deepseek-chat" 

MAX_CONTENT_SNIPPET_FOR_LLM = 2000 
TARGET_PRIMARY_KEYWORDS = 1
TARGET_SECONDARY_KEYWORDS = 8
TARGET_LONGTAIL_KEYWORDS = 5
TARGET_ENTITY_KEYWORDS = 4
TOTAL_KEYWORDS_AIM = 15 
API_TIMEOUT_KEYWORD_GEN = 180 # Increased timeout for potentially complex keyword generation

# --- Agent Prompts ---
KEYWORD_INTELLIGENCE_SYSTEM_MESSAGE_KW = "You are an ASI-level SEO Keyword Intelligence Strategist. Analyze the provided article content and generate a comprehensive, strategically diverse set of keywords. Respond ONLY with the JSON object."

KEYWORD_INTELLIGENCE_USER_TEMPLATE_KW = """
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
    *   Generate the single most dominant, high-intent primary keyword phrase for this article.
2.  **Secondary/LSI Keywords (Target: {target_secondary_keywords}):**
    *   Generate a list of semantically related keywords and Latent Semantic Indexing (LSI) terms.
3.  **Long-Tail Keywords (Question-Style) (Target: {target_longtail_keywords}):**
    *   Generate keywords in the form of questions that users might ask.
4.  **Entity Keywords (People, Orgs, Products) (Target: {target_entity_keywords}):**
    *   Identify and list key named entities mentioned.
5.  **Strategic Considerations:** Focus on user intent, simulated search volume, relevance, and natural language.

**Output Format (Strictly JSON - provide ONLY the JSON object):**
{{
  "analyzed_primary_keyword": "string",
  "secondary_lsi_keywords": ["string1", "string2", ...],
  "long_tail_question_keywords": ["string1", "string2", ...],
  "entity_keywords": ["string1", "string2", ...],
  "keyword_strategy_notes": "Brief notes on your reasoning."
}}
"""

def call_deepseek_for_keywords(article_title, processed_summary, primary_topic_from_filter, initial_candidate_keywords, article_content_snippet):
    """Uses DeepSeek API to generate a structured set of keywords."""
    if not DEEPSEEK_API_KEY_KW:
        logger.error("DEEPSEEK_API_KEY not found. Cannot call DeepSeek API for keywords.")
        return None
    
    initial_candidate_keywords_str = ", ".join(initial_candidate_keywords) if initial_candidate_keywords else "None provided"
    
    user_prompt = KEYWORD_INTELLIGENCE_USER_TEMPLATE_KW.format(
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
        "model": DEEPSEEK_MODEL_FOR_KEYWORDS,
        "messages": [
            {"role": "system", "content": KEYWORD_INTELLIGENCE_SYSTEM_MESSAGE_KW},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.5, # Moderate temperature for keyword generation
        "response_format": {"type": "json_object"}
    }
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY_KW}",
        "Content-Type": "application/json"
    }

    try:
        logger.debug(f"Sending keyword intelligence request to DeepSeek for title: {article_title[:50]}...")
        response = requests.post(DEEPSEEK_CHAT_API_URL_KW, headers=headers, json=payload, timeout=API_TIMEOUT_KEYWORD_GEN)
        response.raise_for_status()
        
        response_json = response.json()

        if response_json.get("choices") and response_json["choices"][0].get("message") and response_json["choices"][0]["message"].get("content"):
            generated_json_string = response_json["choices"][0]["message"]["content"]
            try:
                keyword_analysis_result = json.loads(generated_json_string)
                required_keys = ["analyzed_primary_keyword", "secondary_lsi_keywords", "long_tail_question_keywords", "entity_keywords"]
                if all(key in keyword_analysis_result for key in required_keys):
                    logger.info(f"DeepSeek keyword intelligence successful for: {article_title[:50]}")
                    return keyword_analysis_result
                else:
                    logger.error(f"DeepSeek keyword intelligence returned JSON missing required keys: {keyword_analysis_result}")
                    return None
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode JSON from DeepSeek keyword intelligence response: {generated_json_string}. Error: {e}")
                match = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', generated_json_string, re.DOTALL)
                if match:
                    try:
                        keyword_analysis_result = json.loads(match.group(1))
                        if all(key in keyword_analysis_result for key in required_keys):
                             logger.info(f"DeepSeek keyword (fallback extraction) successful for: {article_title[:50]}")
                             return keyword_analysis_result
                    except Exception as fallback_e:
                        logger.error(f"DeepSeek keyword fallback JSON extraction also failed: {fallback_e}")
                return None
        else:
            logger.error(f"DeepSeek keyword intelligence response missing expected content: {response_json}")
            return None
            
    except requests.exceptions.RequestException as e:
        logger.error(f"DeepSeek API request for keyword intelligence failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"DeepSeek API Response Content: {e.response.text}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error in call_deepseek_for_keywords: {e}")
        return None

def clean_and_deduplicate_keywords(keyword_list):
    if not keyword_list:
        return []
    cleaned_list = []
    seen_keywords_lower = set()
    for kw_item in keyword_list:
        if not isinstance(kw_item, str):
            continue
        kw = kw_item.strip()
        kw = re.sub(r'\s{2,}', ' ', kw) 
        kw = kw.replace(':', '').replace('"', '').replace("'", "") 
        kw = kw.rstrip('?.!,;') 
        if not kw or len(kw) < 3: 
            continue
        kw_lower = kw.lower()
        if kw_lower not in seen_keywords_lower:
            cleaned_list.append(kw) 
            seen_keywords_lower.add(kw_lower)
    return cleaned_list


def run_keyword_intelligence_agent(article_pipeline_data):
    article_id = article_pipeline_data.get('id', 'unknown_id')
    title = article_pipeline_data.get('initial_title_from_web', 'No Title')
    processed_summary = article_pipeline_data.get('processed_summary', '')
    primary_topic_from_filter = article_pipeline_data.get('primary_topic', title) 
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

    llm_keyword_profile = call_deepseek_for_keywords( # Changed function call
        title, processed_summary, primary_topic_from_filter, initial_candidates, content_snippet
    )

    all_generated_keywords_from_llm = []
    if llm_keyword_profile and isinstance(llm_keyword_profile, dict):
        article_pipeline_data['keyword_profile'] = llm_keyword_profile 
        article_pipeline_data['keyword_generation_status'] = "LLM_SUCCESS"
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
        all_generated_keywords_from_llm.extend(initial_candidates)
        if primary_topic_from_filter:
             all_generated_keywords_from_llm.append(primary_topic_from_filter)

    final_cleaned_keywords = clean_and_deduplicate_keywords(all_generated_keywords_from_llm)
    priority_keyword = llm_keyword_profile.get('analyzed_primary_keyword') if llm_keyword_profile else primary_topic_from_filter
    if priority_keyword and isinstance(priority_keyword, str) and len(priority_keyword.strip()) >=3 :
        priority_kw_clean = priority_keyword.strip()
        final_cleaned_keywords = [kw for kw in final_cleaned_keywords if kw.lower() != priority_kw_clean.lower()]
        final_cleaned_keywords.insert(0, priority_kw_clean)

    article_pipeline_data['final_keywords'] = final_cleaned_keywords[:TOTAL_KEYWORDS_AIM]
    
    logger.info(f"Final keywords for {article_id} ({len(article_pipeline_data['final_keywords'])}): {article_pipeline_data['final_keywords']}")
    return article_pipeline_data


# --- Standalone Execution Example ---
if __name__ == "__main__":
    if not logger.handlers:
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
                            format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')

    if not DEEPSEEK_API_KEY_KW:
        logger.error("DEEPSEEK_API_KEY not set in .env. Cannot run standalone test for keyword_intelligence_agent with DeepSeek.")
        sys.exit(1)
        
    logger.info("--- Starting Keyword Intelligence Agent Standalone Test (with DeepSeek) ---")
    
    sample_article_data_for_keywords = {
        'id': 'test_kw_001',
        'initial_title_from_web': "NVIDIA Blackwell B200 GPU: A New Era for AI Supercomputing and Trillion-Parameter Models",
        'processed_summary': "NVIDIA has unveiled its Blackwell B200 GPU, succeeding the H100. It promises massive performance gains for AI training and inference, particularly for trillion-parameter large language models. The new architecture features enhanced tensor cores, significantly more memory bandwidth, and improved energy efficiency. CEO Jensen Huang highlighted its role in powering next-generation data centers and accelerating scientific discovery.",
        'primary_topic': "AI Hardware", 
        'candidate_keywords': ["NVIDIA Blackwell", "B200 GPU", "AI Supercomputing"], 
        'raw_scraped_text': "NVIDIA's GTC conference today was dominated by the announcement of the Blackwell B200 GPU..." # Shortened
    }

    result_data = run_keyword_intelligence_agent(sample_article_data_for_keywords.copy())

    logger.info("\n--- Keyword Intelligence Test Results ---")
    logger.info(f"Keyword Generation Status: {result_data.get('keyword_generation_status')}")
    logger.info(f"Keyword Profile from LLM:\n{json.dumps(result_data.get('keyword_profile'), indent=2)}")
    logger.info(f"\nFinal Keywords for Article ({len(result_data.get('final_keywords',[]))}):")
    for kw in result_data.get('final_keywords', []):
        logger.info(f"  - {kw}")

    logger.info("--- Keyword Intelligence Agent Standalone Test Complete ---")