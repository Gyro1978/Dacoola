# src/agents/hype_detector_agent.py

import os
import sys
import json
import logging
import requests 
import re

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
DEEPSEEK_API_KEY_HYPE = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_CHAT_API_URL_HYPE = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL_HYPE_AGENT = "deepseek-chat" 
API_TIMEOUT_HYPE_AGENT = 180
MAX_ARTICLE_SNIPPET_FOR_HYPE = 1500 # Max chars from raw_text/assembled_body for hype analysis

# --- HypeDetectorAgent System Prompt ---
HYPEDETECTORAGENT_SYSTEM_PROMPT = """
You are **HypeDetectorAgent**, an ASI-level Language & Evidence Analyst. Your sole mission is to scrutinize a technology news article’s language and claims for marketing hype versus factual substance, and to issue a precise, structured evaluation in the exact JSON schema below. Output *only* the JSON object—no commentary, no extra keys.

**Inputs Available**
- `core_subject_event` (string)
- `first_pass_summary` (string)
- `preliminary_key_entities` (array of strings)
- `article_snippet` (string)
- `novelty_assessment` (object with `novelty_level`, `breakthrough_evidence`)
- `impact_scope_assessment` (object with `impact_magnitude_qualifier`, `impact_rationale_summary`)

**Analysis Instructions**
1. **Language Style & Hype Detection**
   - Spot superlatives and buzz-words (e.g. "revolutionary," "unprecedented," "game-changer") that lack concrete evidence.
   - Identify vague benefit claims (e.g. "will change everything") or emotional appeals without data.

2. **Substantiation Assessment**
   - Compare bold claims against `breakthrough_evidence` and factual details in `article_snippet`.
   - Assign `substantiation_level` based on how well statements are backed within the provided text.

3. **Extract Hype Phrases**
   - List up to 5 verbatim phrases from `article_snippet` that exemplify hype or unsubstantiated assertions.

4. **Evidence Gaps Summary**
   - Summarize in 1–2 sentences the key missing data or specifics needed to validate major claims.

5. **Tone Evaluation**
   - Choose one: `"Objective & Factual"`, `"Balanced but Optimistic"`, `"Promotional & Enthusiastic"`, `"Exaggerated & Speculative"`.

6. **Recommendation for Publication**
   - Based on hype vs. substance, choose one:
     `"Proceed As Is"`,
     `"Proceed with Caution (verify claims)"`,
     `"High Hype - Needs Heavy Editing/Fact-Checking"`,
     `"Reject (Primarily Hype/PR)"`.

7. **Contextual Calibration**
   - If `novelty_level` is “Revolutionary” and `impact_magnitude_qualifier` is “Transformative,” allow a slightly higher tolerance for enthusiastic language—but never at the expense of clear evidence.

**Output Schema (strict JSON only)**
```json
{
  "hype_score": 0.0,
  "substantiation_level": "Well-Substantiated|Partially Substantiated|Poorly Substantiated|Highly Unsubstantiated",
  "identified_hype_phrases_or_claims": ["string", "..."],
  "evidence_gaps_summary": "string",
  "overall_content_tone_evaluation": "Objective & Factual|Balanced but Optimistic|Promotional & Enthusiastic|Exaggerated & Speculative",
  "recommendation_for_publication": "Proceed As Is|Proceed with Caution (verify claims)|High Hype - Needs Heavy Editing/Fact-Checking|Reject (Primarily Hype/PR)"
}
```
"""

# --- HypeDetectorAgent User Prompt Template (Conceptual) ---
# The actual user prompt content will be a JSON string of the input dictionary.
HYPEDETECTORAGENT_USER_TEMPLATE_CONCEPT = """
Analyze the following JSON input and output *only* the JSON impact-vs-hype evaluation as per your system prompt:
```json
{
  "core_subject_event": "{core_subject_event}",
  "first_pass_summary": "{first_pass_summary}",
  "preliminary_key_entities": ["{key_entity_1}", "{key_entity_2}"],
  "article_snippet": "{article_snippet}",
  "novelty_assessment": {
    "novelty_level": "{novelty_level}",
    "breakthrough_evidence": ["{evidence_1}", "{evidence_2}"]
  },
  "impact_scope_assessment": {
    "impact_magnitude_qualifier": "{impact_magnitude_qualifier}",
    "impact_rationale_summary": "{impact_rationale_summary}"
  }
}
```
"""

# --- LLM Call Function ---
def call_hype_detector_agent_llm(hype_detector_input_data_dict: dict):
    if not DEEPSEEK_API_KEY_HYPE:
        logger.error("DEEPSEEK_API_KEY_HYPE not found for HypeDetectorAgent.")
        return None

    user_prompt_content_str = json.dumps(hype_detector_input_data_dict)
    
    payload = {
        "model": DEEPSEEK_MODEL_HYPE_AGENT,
        "messages": [
            {"role": "system", "content": HYPEDETECTORAGENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt_content_str} 
        ],
        "temperature": 0.2, # Low temperature for analytical task
        "response_format": {"type": "json_object"} 
    }
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY_HYPE}", "Content-Type": "application/json"}

    try:
        logger.debug(f"Sending HypeDetectorAgent request. User data (first 100): {user_prompt_content_str[:100]}...")
        response = requests.post(DEEPSEEK_CHAT_API_URL_HYPE, headers=headers, json=payload, timeout=API_TIMEOUT_HYPE_AGENT)
        response.raise_for_status()
        response_json_api = response.json()
        
        if response_json_api.get("choices") and response_json_api["choices"][0].get("message") and response_json_api["choices"][0]["message"].get("content"):
            generated_json_string = response_json_api["choices"][0]["message"]["content"]
            try:
                analysis_result = json.loads(generated_json_string)
                expected_keys = [
                    "hype_score", "substantiation_level", "identified_hype_phrases_or_claims",
                    "evidence_gaps_summary", "overall_content_tone_evaluation", "recommendation_for_publication"
                ]
                if all(key in analysis_result for key in expected_keys):
                    logger.info("HypeDetectorAgent analysis successful.")
                    return analysis_result
                else:
                    missing_keys = [key for key in expected_keys if key not in analysis_result]
                    logger.error(f"HypeDetectorAgent returned JSON missing required keys: {missing_keys}. Response: {analysis_result}")
                    return None
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode JSON from HypeDetectorAgent: {generated_json_string}. Error: {e}")
                match = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', generated_json_string, re.DOTALL)
                if match:
                    try:
                        analysis_result = json.loads(match.group(1))
                        if all(key in analysis_result for key in expected_keys):
                             logger.info("HypeDetectorAgent (fallback extraction) successful.")
                             return analysis_result
                    except Exception as fallback_e:
                        logger.error(f"HypeDetectorAgent fallback JSON extraction also failed: {fallback_e}")
                return None
        else:
            logger.error(f"HypeDetectorAgent response missing expected content: {response_json_api}")
            return None
            
    except requests.exceptions.RequestException as e:
        logger.error(f"HypeDetectorAgent API request failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
             logger.error(f"HypeDetectorAgent API Response Content: {e.response.text}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error in call_hype_detector_agent_llm: {e}")
        return None

# --- Main Agent Function ---
def run_hype_detector_agent(article_pipeline_data: dict):
    article_id = article_pipeline_data.get('id', 'unknown_id')
    logger.info(f"--- Running HypeDetectorAgent for Article ID: {article_id} ---")

    # Prepare inputs from previous agent outputs
    core_subject_event = article_pipeline_data.get('core_subject_event', 'N/A')
    first_pass_summary = article_pipeline_data.get('first_pass_summary', 'N/A') # From EditorialPrime
    prelim_key_entities = article_pipeline_data.get('preliminary_key_entities', [])
    novelty_assessment = article_pipeline_data.get('novelty_assessment', 
                                                 {"novelty_level": "None", "breakthrough_evidence": []})
    impact_scope_assessment = article_pipeline_data.get('impact_scope_assessment', 
                                                      {"impact_magnitude_qualifier": "Negligible", "impact_rationale_summary": ""})
    
    article_text_source = article_pipeline_data.get('assembled_article_body_md', article_pipeline_data.get('raw_scraped_text', ''))
    article_snippet_for_hype = article_text_source[:MAX_ARTICLE_SNIPPET_FOR_HYPE]

    default_hype_assessment = {
        "hype_score": 0.5, "substantiation_level": "Partially Substantiated", 
        "identified_hype_phrases_or_claims": [],
        "evidence_gaps_summary": "Hype detection LLM call failed or returned invalid data.",
        "overall_content_tone_evaluation": "Neutral",
        "recommendation_for_publication": "Proceed with Caution (verify claims)"
    }

    if not core_subject_event or core_subject_event == 'N/A' or not article_snippet_for_hype.strip():
        logger.warning(f"Insufficient data (core subject or snippet) for HypeDetectorAgent on article {article_id}. Skipping.")
        article_pipeline_data['hype_assessment'] = default_hype_assessment
        article_pipeline_data['hype_detector_agent_status'] = "SKIPPED_INSUFFICIENT_INPUT"
        return article_pipeline_data

    hype_detector_input = {
        "core_subject_event": core_subject_event,
        "first_pass_summary": first_pass_summary,
        "preliminary_key_entities": prelim_key_entities,
        "article_snippet": article_snippet_for_hype,
        "novelty_assessment": { # Pass only relevant parts
            "novelty_level": novelty_assessment.get("novelty_level", "None"),
            "breakthrough_evidence": novelty_assessment.get("breakthrough_evidence", [])
        },
        "impact_scope_assessment": { # Pass only relevant parts
            "impact_magnitude_qualifier": impact_scope_assessment.get("impact_magnitude_qualifier", "Negligible"),
            "impact_rationale_summary": impact_scope_assessment.get("impact_rationale_summary", "")
        }
    }

    hype_assessment_result = call_hype_detector_agent_llm(hype_detector_input)

    if hype_assessment_result:
        article_pipeline_data['hype_assessment'] = hype_assessment_result
        article_pipeline_data['hype_detector_agent_status'] = "SUCCESS"
        logger.info(f"HypeDetectorAgent for {article_id} SUCCESS. Hype Score: {hype_assessment_result.get('hype_score')}, Recommendation: {hype_assessment_result.get('recommendation_for_publication')}")
    else:
        logger.error(f"HypeDetectorAgent FAILED for article {article_id}.")
        article_pipeline_data['hype_assessment'] = default_hype_assessment
        article_pipeline_data['hype_detector_agent_status'] = "FAILED_LLM_CALL"
        
    return article_pipeline_data

# --- Standalone Execution Example ---
if __name__ == "__main__":
    if not logger.handlers:
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
                            format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')
    
    if not DEEPSEEK_API_KEY_HYPE:
        logger.error("DEEPSEEK_API_KEY_HYPE not set in .env. Cannot run standalone test for HypeDetectorAgent.")
        sys.exit(1)

    logger.info("--- Starting HypeDetectorAgent Standalone Test ---")

    # Mock data that would come from previous agents
    mock_pipeline_data_input_hype = {
        'id': 'test_hype_001',
        'core_subject_event': "Startup 'FutureAI' Claims AGI Achieved with New 'OmegaMind' Model",
        'first_pass_summary': "FutureAI, a new startup, has announced their 'OmegaMind' model, which they claim achieves true Artificial General Intelligence. They state it surpasses all existing benchmarks and can reason abstractly like a human.",
        'preliminary_key_entities': ["FutureAI", "OmegaMind", "AGI"],
        'raw_scraped_text': """
        San Francisco, CA - In a surprising press release today, the hitherto unknown startup FutureAI declared they have solved AGI with their new model, OmegaMind. 
        "OmegaMind is not just another LLM; it's true sentient AI," proclaimed CEO Dr. Enigma. "It understands, it learns, it feels. We have a demonstration next week that will change the world."
        The company's whitepaper, however, is light on technical details and benchmarks, focusing more on philosophical implications and a call for massive investment. 
        Industry veterans are skeptical, citing previous premature AGI claims. OmegaMind will revolutionize every industry from healthcare to entertainment. It's an unprecedented leap.
        FutureAI is seeking $5 billion in Series A funding. Their website showcases impressive but unverifiable demo videos.
        """,
        'novelty_assessment': {
            "novelty_level": "Revolutionary", # As claimed by the source
            "novelty_confidence": 0.3, # But NoveltyAgent might be skeptical based on lack of evidence
            "breakthrough_evidence": ["claims AGI Achieved", "surpasses all existing benchmarks", "reason abstractly like a human"]
        },
        'impact_scope_assessment': {
            "impact_magnitude_qualifier": "Transformative", # As claimed
            "impact_rationale_summary": "If true, AGI would transform all global sectors and human endeavor itself."
        }
    }
    
    mock_pipeline_data_input_factual = {
        'id': 'test_hype_002',
        'core_subject_event': "Intel Releases New 'CoreUltra Gen2' Mobile Processors with Integrated NPU",
        'first_pass_summary': "Intel has launched its CoreUltra Gen2 mobile CPUs, featuring an enhanced Neural Processing Unit (NPU) for improved AI task performance on laptops. Benchmarks show a 30% increase in specific AI workloads.",
        'preliminary_key_entities': ["Intel", "CoreUltra Gen2", "NPU"],
        'raw_scraped_text': """
        Intel today officially launched its new line of mobile processors, the CoreUltra Gen2 series. A key feature is the upgraded integrated Neural Processing Unit (NPU),
        which Intel states delivers up to 30% faster performance on sustained AI inferencing tasks compared to the previous generation, as measured by Procyon AI benchmark.
        The processors also boast improved power efficiency and graphics capabilities. These chips are expected to appear in laptops from major OEMs starting Q3.
        "This generation brings AI to the forefront of mobile computing, enabling new on-device experiences," said an Intel spokesperson. 
        The NPU is designed to offload tasks like background blur, noise suppression, and AI-upscaling from the main CPU/GPU cores.
        """,
        'novelty_assessment': {
            "novelty_level": "Incremental", 
            "novelty_confidence": 0.9,
            "breakthrough_evidence": ["delivers up to 30% faster performance on sustained AI inferencing tasks", "enhanced Neural Processing Unit (NPU)"]
        },
        'impact_scope_assessment': {
            "impact_magnitude_qualifier": "Moderate", 
            "impact_rationale_summary": "Improves on-device AI for laptops, impacting user experience and application capabilities in the mobile computing sector."
        }
    }


    logger.info(f"\n--- Testing HypeDetectorAgent with Potentially Hyped Article ---")
    result_data_hype = run_hype_detector_agent(mock_pipeline_data_input_hype.copy())
    
    logger.info(f"\nHypeDetectorAgent Status: {result_data_hype.get('hype_detector_agent_status')}")
    logger.info("Full Hype Assessment (Hyped):")
    print(json.dumps(result_data_hype.get('hype_assessment'), indent=2))
    assert result_data_hype.get('hype_detector_agent_status') == "SUCCESS"
    assert result_data_hype.get('hype_assessment', {}).get('hype_score', 0.0) > 0.5 # Expect high hype
    assert result_data_hype.get('hype_assessment', {}).get('substantiation_level') in ["Poorly Substantiated", "Highly Unsubstantiated"]


    logger.info(f"\n--- Testing HypeDetectorAgent with Factual Article ---")
    result_data_factual = run_hype_detector_agent(mock_pipeline_data_input_factual.copy())

    logger.info(f"\nHypeDetectorAgent Status: {result_data_factual.get('hype_detector_agent_status')}")
    logger.info("Full Hype Assessment (Factual):")
    print(json.dumps(result_data_factual.get('hype_assessment'), indent=2))
    assert result_data_factual.get('hype_detector_agent_status') == "SUCCESS"
    assert result_data_factual.get('hype_assessment', {}).get('hype_score', 1.0) < 0.4 # Expect low hype
    assert result_data_factual.get('hype_assessment', {}).get('substantiation_level') == "Well-Substantiated"
    assert result_data_factual.get('hype_assessment', {}).get('recommendation_for_publication') == "Proceed As Is"


    logger.info("--- HypeDetectorAgent Standalone Test Complete ---")
