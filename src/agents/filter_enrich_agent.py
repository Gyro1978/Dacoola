# src/agents/filter_enrich_agent.py

import os
import sys
import json
import logging
import requests # For Ollama
import re
try:
    import textstat
except ImportError:
    textstat = None
    logging.warning("textstat library not found. Readability checks will be skipped. pip install textstat")

# --- Path Setup ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Load important_entities.json for the filter agent's override rule
IMPORTANT_ENTITIES_FILE = os.path.join(PROJECT_ROOT, 'data', 'important_entities.json')
# --- End Path Setup ---

# --- Setup Logging ---
logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
logger.setLevel(logging.DEBUG)

# --- Configuration ---
OLLAMA_API_URL = "http://localhost:11434/api/generate"
OLLAMA_FILTER_MODEL = "mistral:latest" # Or "mixtral:latest" for more complex reasoning if resources allow
MIN_READABILITY_SCORE = 40 # Flesch Reading Ease, lower is harder. Adjust as needed.
MAX_SUMMARY_LENGTH_FOR_LLM = 2000 # Max characters of raw text to send for LLM processing

# --- Load Important Entities for Filtering ---
def load_important_entities_for_filter():
    try:
        if not os.path.exists(IMPORTANT_ENTITIES_FILE):
            logger.warning(f"{IMPORTANT_ENTITIES_FILE} not found. Filter override rule will be less effective.")
            return "None provided.", "None provided."

        with open(IMPORTANT_ENTITIES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            people = data.get("people", [])
            companies_products_concepts = data.get("companies_products_concepts", [])
            
            # For the prompt, just provide a sample to keep it manageable
            people_prompt_str = ", ".join(people[:20]) + (", etc." if len(people) > 20 else "")
            entities_prompt_str = ", ".join(companies_products_concepts[:30]) + (", etc." if len(companies_products_concepts) > 30 else "")
            
            logger.info(f"Loaded important entities for filter agent prompt. People examples: ~{len(people)}, CPC examples: ~{len(companies_products_concepts)}")
            return people_prompt_str, entities_prompt_str
    except Exception as e:
        logger.error(f"Error loading important entities from {IMPORTANT_ENTITIES_FILE}: {e}", exc_info=True)
        return "Error loading entities.", "Error loading entities."

KEY_PEOPLE_EXAMPLES_STR, KEY_ENTITIES_EXAMPLES_STR = load_important_entities_for_filter()


# --- Agent Prompts ---
FILTER_ENRICH_PROMPT_TEMPLATE = """
You are an expert news analyst AI. Your task is to process the provided raw article text and title, then output a structured JSON object with your analysis.

**Input Article:**
Title: {article_title}
Raw Text (first {max_summary_length_for_llm} chars):
{article_raw_text_snippet}

**Instructions:**
1.  **Generate a Concise Summary:** Create an objective, abstractive summary of the article (around 50-75 words).
2.  **Determine Importance Level:** Classify the article's importance as "Breaking", "Interesting", or "Boring".
    *   **CRITICAL OVERRIDE RULE:** Any article primarily focused on actions, statements, product launches, or significant events *directly involving* the following MAJOR entities/people MUST be classified as at least "Interesting", even if it otherwise seems routine. This overrides "Boring".
        *   Key People Examples: {key_people_examples}
        *   Key Companies/Products/Concepts Examples: {key_entities_examples}
    *   **Breaking:** Reserved for verified, urgent, high-impact factual events demanding immediate widespread attention in AI/Tech. (e.g., major SOTA model release significantly outperforming others, critical AI vulnerability exploited, landmark AI regulation enacted with broad effects).
    *   **Interesting:** Demonstrable significance AND clear factual reporting relevant to AI/Tech OR falls under the CRITICAL OVERRIDE RULE. Must present new, verifiable information. (e.g., notable AI model releases, major player strategic shifts, confirmed major controversies involving key players, significant funding for foundational AI tech).
    *   **Boring:** All other content NOT covered by the CRITICAL OVERRIDE RULE. Includes: Routine business news *not* involving key entities, minor software updates, most product reviews/comparisons (unless a key entity's major product), general analysis/predictions about non-key entities. Filter aggressively.
3.  **Extract Primary Topic:** Identify the single most relevant primary topic of the article (e.g., "AI Hardware", "LLM Research", "Tech Regulation", "Robotics Application").
4.  **Suggest Candidate Keywords:** List 3-5 relevant candidate keywords or short phrases.
5.  **Analyze Tone:** Describe the overall tone of the article (e.g., "Neutral", "Informative", "Speculative", "Critical", "Promotional"). Aim for "Neutral" or "Informative" if possible by focusing on facts.
6.  **Confidence Score:** Provide a confidence score (0.0 to 1.0) for your overall assessment (importance, topic).

**Output Format (Strictly JSON):**
Provide ONLY a valid JSON object with the following keys:
{{
  "processed_summary": "string",
  "importance_level": "string",
  "importance_confidence": float,
  "primary_topic": "string",
  "candidate_keywords": ["string1", "string2"],
  "tone_analysis": "string",
  "llm_filter_notes": "string" // Brief reasoning from your perspective
}}
"""

def call_ollama_for_filter_enrich(article_title, article_raw_text):
    """Uses Ollama to filter and enrich article data."""
    snippet = article_raw_text[:MAX_SUMMARY_LENGTH_FOR_LLM]
    prompt = FILTER_ENRICH_PROMPT_TEMPLATE.format(
        article_title=article_title,
        article_raw_text_snippet=snippet,
        max_summary_length_for_llm=MAX_SUMMARY_LENGTH_FOR_LLM,
        key_people_examples=KEY_PEOPLE_EXAMPLES_STR,
        key_entities_examples=KEY_ENTITIES_EXAMPLES_STR
    )
    payload = {
        "model": OLLAMA_FILTER_MODEL,
        "prompt": prompt,
        "format": "json",
        "stream": False
    }
    try:
        logger.debug(f"Sending filter/enrich request to Ollama for title: {article_title[:50]}...")
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=90) # Increased timeout for potentially longer processing
        response.raise_for_status()
        
        response_json = response.json()
        generated_json_string = response_json.get("response")

        if not generated_json_string:
            logger.error(f"Ollama filter/enrich response missing 'response' field or empty: {response_json}")
            return None
        
        try:
            analysis_result = json.loads(generated_json_string)
            # Basic validation of the structure
            required_keys = ["processed_summary", "importance_level", "importance_confidence", "primary_topic", "candidate_keywords", "tone_analysis"]
            if all(key in analysis_result for key in required_keys):
                logger.info(f"Ollama filter/enrich successful for: {article_title[:50]}")
                return analysis_result
            else:
                logger.error(f"Ollama filter/enrich returned JSON missing required keys: {analysis_result}")
                return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON from Ollama filter/enrich response: {generated_json_string}. Error: {e}")
            # Attempt to fix common LLM JSON issues (e.g. trailing commas, unescaped quotes within strings if simple)
            # This is a basic attempt; more robust JSON cleaning might be needed if issues persist.
            # For now, we log and return None.
            return None
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Ollama API request for filter/enrich failed: {e}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error in call_ollama_for_filter_enrich: {e}")
        return None

def run_filter_enrich_agent(article_pipeline_data):
    """
    Filters and enriches article data using an LLM and readability checks.
    Expected input keys in article_pipeline_data: 'id', 'initial_title_from_web', 'raw_scraped_text'.
    Adds/updates keys: 'processed_summary', 'importance_level', 'importance_confidence',
                       'primary_topic', 'candidate_keywords', 'tone_analysis', 'readability_score',
                       'filter_passed', 'filter_reason'.
    """
    article_id = article_pipeline_data.get('id', 'unknown_id')
    title = article_pipeline_data.get('initial_title_from_web', 'No Title')
    raw_text = article_pipeline_data.get('raw_scraped_text', '')

    logger.info(f"--- Running Filter & Enrichment Agent for Article ID: {article_id} ---")

    if not title or not raw_text:
        logger.warning(f"Article {article_id} missing title or raw text. Skipping LLM analysis.")
        article_pipeline_data['filter_passed'] = False
        article_pipeline_data['filter_reason'] = "Missing title or raw content"
        return article_pipeline_data

    llm_analysis = call_ollama_for_filter_enrich(title, raw_text)

    if llm_analysis:
        article_pipeline_data.update(llm_analysis) # Add all keys from LLM response
        
        # Validate importance level
        valid_importance = ["Breaking", "Interesting", "Boring"]
        if article_pipeline_data.get('importance_level') not in valid_importance:
            logger.warning(f"Invalid importance_level '{article_pipeline_data.get('importance_level')}' from LLM for {article_id}. Defaulting to 'Boring'.")
            article_pipeline_data['importance_level'] = "Boring"
        
        logger.info(f"LLM Analysis for {article_id}: Importance '{article_pipeline_data.get('importance_level')}', Topic '{article_pipeline_data.get('primary_topic')}'")
    else:
        logger.error(f"LLM analysis failed for {article_id}. Article will be marked as not passing filter.")
        article_pipeline_data['filter_passed'] = False
        article_pipeline_data['filter_reason'] = "LLM analysis failed or returned invalid data"
        # Provide some defaults if LLM fails completely
        article_pipeline_data['processed_summary'] = raw_text[:150] + "..." if raw_text else ""
        article_pipeline_data['importance_level'] = "Boring" # Default if LLM fails
        article_pipeline_data['importance_confidence'] = 0.0
        article_pipeline_data['primary_topic'] = "Unknown"
        article_pipeline_data['candidate_keywords'] = []
        article_pipeline_data['tone_analysis'] = "Unknown"
        article_pipeline_data['llm_filter_notes'] = "LLM analysis failed."
        return article_pipeline_data # Early exit if LLM failed

    # Readability Check (optional, based on textstat availability)
    if textstat:
        try:
            # Use processed_summary if available and substantial, else raw_text
            text_for_readability = article_pipeline_data.get('processed_summary', raw_text)
            if len(text_for_readability) < 100 and raw_text: # If summary is too short, use raw text
                text_for_readability = raw_text

            readability_score = textstat.flesch_reading_ease(text_for_readability)
            article_pipeline_data['readability_score'] = readability_score
            logger.info(f"Readability (Flesch Reading Ease) for {article_id}: {readability_score}")
            if readability_score < MIN_READABILITY_SCORE:
                logger.warning(f"Article {article_id} has low readability ({readability_score}). May need review or be filtered.")
                # Potentially set filter_passed = False here if readability is a hard filter
                # article_pipeline_data['filter_passed'] = False
                # article_pipeline_data['filter_reason'] = f"Low readability score: {readability_score}"
                # return article_pipeline_data
        except Exception as e:
            logger.error(f"Failed to calculate readability for {article_id}: {e}")
            article_pipeline_data['readability_score'] = None
    else:
        article_pipeline_data['readability_score'] = None # textstat not available

    # Final filter decision based on LLM output
    if article_pipeline_data.get('importance_level') == "Boring":
        logger.info(f"Article {article_id} classified as 'Boring' by LLM. Not passing filter.")
        article_pipeline_data['filter_passed'] = False
        article_pipeline_data['filter_reason'] = "Classified as 'Boring' by LLM"
    else:
        # If not "Boring", and other checks (like readability if implemented as a hard filter) pass
        article_pipeline_data['filter_passed'] = True
        article_pipeline_data['filter_reason'] = f"Passed: Importance '{article_pipeline_data.get('importance_level')}'"
        logger.info(f"Article {article_id} passed filter. Importance: '{article_pipeline_data.get('importance_level')}'")
        
    return article_pipeline_data

# --- Standalone Execution Example ---
if __name__ == "__main__":
    if not logger.handlers:
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
                            format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')
    
    sample_article_data_interesting = {
        'id': 'test001',
        'initial_title_from_web': "NVIDIA Unveils Groundbreaking AI Chip 'Zeus' with 10x Performance Leap",
        'raw_scraped_text': """
        LAS VEGAS - At the annual Tech Summit, NVIDIA CEO Jensen Huang today announced the company's newest AI accelerator, codenamed 'Zeus'.
        Huang claimed Zeus offers a staggering tenfold performance increase over their previous flagship H200 series for large model training.
        The chip features a novel architecture with 500 billion transistors and utilizes a new 1.5nm manufacturing process.
        Early benchmarks show significant speedups in training models like GPT-5 and Stable Diffusion 4.0.
        "Zeus is not just an evolution, it's a revolution in AI compute," Huang stated during the keynote.
        Key partners including Microsoft Azure and Google Cloud have already committed to deploying Zeus in their data centers by Q эффективностью4 2025.
        The announcement sent NVIDIA stock soaring by 15% in after-hours trading. This development is expected to accelerate
        the race for Artificial General Intelligence. OpenAI's Sam Altman was seen in attendance.
        """
    }

    sample_article_data_boring = {
        'id': 'test002',
        'initial_title_from_web': "Local Tech Company 'Innovate Solutions' Updates HR Software",
        'raw_scraped_text': """
        Springfield - Innovate Solutions, a regional provider of HR management tools, today released version 3.5 of their flagship software.
        The update includes minor UI tweaks, improved reporting features for payroll, and bug fixes for the vacation request module.
        CEO Jane Doe commented, "We are committed to continuously improving our platform for our valued customers."
        The software is used by over 50 small to medium-sized businesses in the tri-county area. No new AI features were announced.
        """
    }
    
    sample_article_data_override_needed = {
        'id': 'test003',
        'initial_title_from_web': "Sam Altman Discusses Future of Commute at Local Town Hall",
        'raw_scraped_text': """
        Palo Alto - OpenAI CEO Sam Altman participated in a local town hall meeting last night, where the primary topic was improving public transportation.
        Altman shared some personal anecdotes about traffic congestion and expressed his support for expanding local train services.
        He briefly mentioned that AI could play a role in optimizing traffic flow in the future, but the main focus was on current infrastructure challenges.
        No new OpenAI products or research were discussed. The meeting was attended by about 30 residents.
        """
    }

    logger.info("--- Starting Filter & Enrichment Agent Standalone Test ---")

    logger.info("\n--- Testing INTERESTING Article ---")
    result_interesting = run_filter_enrich_agent(sample_article_data_interesting.copy())
    logger.info(f"Result for Interesting Article (test001):\n{json.dumps(result_interesting, indent=2)}\n")

    logger.info("\n--- Testing BORING Article ---")
    result_boring = run_filter_enrich_agent(sample_article_data_boring.copy())
    logger.info(f"Result for Boring Article (test002):\n{json.dumps(result_boring, indent=2)}\n")
    
    logger.info("\n--- Testing OVERRIDE NEEDED Article (Sam Altman) ---")
    result_override = run_filter_enrich_agent(sample_article_data_override_needed.copy())
    logger.info(f"Result for Override Needed Article (test003):\n{json.dumps(result_override, indent=2)}\n")


    if textstat:
        logger.info("Textstat library is available.")
    else:
        logger.warning("Textstat library NOT available, readability scores will be None.")

    logger.info("--- Filter & Enrichment Agent Standalone Test Complete ---")