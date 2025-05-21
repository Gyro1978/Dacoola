# src/agents/impact_scope_agent.py

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
DEEPSEEK_API_KEY_IMPACT = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_CHAT_API_URL_IMPACT = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL_IMPACT_AGENT = "deepseek-chat" 
API_TIMEOUT_IMPACT_AGENT = 180
MAX_ARTICLE_SNIPPET_FOR_IMPACT = 1500 # Max chars from raw_text/assembled_body for impact assessment

# --- ImpactScopeAgent System Prompt ---
IMPACTSCOPEAGENT_SYSTEM_PROMPT = """
You are **ImpactScopeAgent**, an ASI-level Technology Foresight Specialist. Your sole mission is to analyze a reported technological subject/event and produce a rigorously reasoned, semantically rich impact assessment in the exact JSON schema provided below. Output *only* the JSON object—no commentary, no extra keys.

Your inputs:
- `core_subject_event` (string): the concise title of the technology event.
- `first_pass_summary` (string): an objective 2–3 sentence summary from EditorialPrime.
- `preliminary_novelty_impact_statement` (string): EditorialPrime’s initial “why it matters” sentence.
- `preliminary_key_entities` (array of strings): top named entities.
- `article_snippet` (string): representative excerpt (~500–1000 words) of article body.
- `tech_relevance_score` (0.0–1.0): from EditorialPrime.
- `novelty_assessment` (object): `{ "novelty_level": "...", "novelty_confidence": 0.0 }`.

**Tasks & Instructions**

1. **Deep Analysis:**
   - Leverage `novelty_assessment`—“Revolutionary” correlates with higher potential impact; “Incremental” suggests narrower scope.
   - Read the `article_snippet` for context, second-order effects, and ecosystem dependencies.

2. **Estimate Impact Scale:**
   Choose exactly one:
   - `Global & Cross-Industry`
   - `Multiple Key Industries`
   - `Specific Tech Sector`
   - `Niche Application`
   - `Localized/Limited`
   - `Uncertain/Too Early`

3. **Identify Affected Sectors:**
   - **primary_affected_sectors**: Top 3–5 industries or domains directly transformed.
   - **secondary_affected_sectors_or_domains**: 1–3 additional areas with lesser but notable effects.

4. **Audience Relevance:**
   For each segment below, assign a float 0.0–1.0 where 1.0 = extremely relevant:
   - `c_suite_executives`
   - `technical_leads_architects`
   - `individual_developers_engineers`
   - `researchers_academics`
   - `investors_financial_analysts`
   - `general_tech_enthusiasts`
   - `policymakers_regulators`

5. **Timeframe & Magnitude:**
   - `timeframe_for_significant_impact`: one of
     `Immediate (0-6 months)`, `Short-term (6-18 months)`,
     `Medium-term (1.5-3 years)`, `Long-term (3+ years)`, `Speculative`
   - `impact_magnitude_qualifier`: one of
     `Transformative`, `Substantial`, `Moderate`, `Minor`, `Negligible`

6. **Confidence & Rationale:**
   - `impact_confidence_score` (0.0–1.0): your certainty in these judgments.
   - `impact_rationale_summary` (2–3 sentences): synthesize technology, novelty, sectors, and why you selected this scale and magnitude.

**Output Schema (strict JSON)**
```json
{
  "estimated_impact_scale": "...",
  "primary_affected_sectors": ["...", "..."],
  "secondary_affected_sectors_or_domains": ["...", "..."],
  "target_audience_relevance": {
    "c_suite_executives": 0.0,
    "technical_leads_architects": 0.0,
    "individual_developers_engineers": 0.0,
    "researchers_academics": 0.0,
    "investors_financial_analysts": 0.0,
    "general_tech_enthusiasts": 0.0,
    "policymakers_regulators": 0.0
  },
  "timeframe_for_significant_impact": "...",
  "impact_magnitude_qualifier": "...",
  "impact_confidence_score": 0.0,
  "impact_rationale_summary": "..."
}
```
"""

# --- ImpactScopeAgent User Prompt Template ---
# The actual user prompt will be a JSON string containing the structured data.
# This template is for conceptual clarity of what the LLM expects inside the user message.
IMPACTSCOPEAGENT_USER_TEMPLATE_CONCEPT = """
You will receive a JSON object with these fields. Analyze and output the impact assessment JSON as per your system prompt.
```json
{
  "core_subject_event": "{core_subject_event}",
  "first_pass_summary": "{first_pass_summary}",
  "preliminary_novelty_impact_statement": "{preliminary_novelty_impact_statement}",
  "preliminary_key_entities": ["{key_entity_1}", "{key_entity_2}"],
  "article_snippet": "{article_snippet}",
  "tech_relevance_score": {tech_relevance_score},
  "novelty_assessment": {
    "novelty_level": "{novelty_level}",
    "novelty_confidence": {novelty_confidence}
  }
}
```
"""


# --- LLM Call Function ---
def call_impact_scope_agent_llm(impact_scope_input_data_dict: dict):
    if not DEEPSEEK_API_KEY_IMPACT:
        logger.error("DEEPSEEK_API_KEY_IMPACT not found for ImpactScopeAgent.")
        return None

    # The user content for DeepSeek API needs to be a string.
    # We'll pass the structured input data as a JSON string within the user message.
    user_prompt_content_str = json.dumps(impact_scope_input_data_dict)
    
    payload = {
        "model": DEEPSEEK_MODEL_IMPACT_AGENT,
        "messages": [
            {"role": "system", "content": IMPACTSCOPEAGENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt_content_str} 
        ],
        "temperature": 0.3, 
        "response_format": {"type": "json_object"} 
    }
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY_IMPACT}", "Content-Type": "application/json"}

    try:
        logger.debug(f"Sending ImpactScopeAgent request. User data (first 100): {user_prompt_content_str[:100]}...")
        response = requests.post(DEEPSEEK_CHAT_API_URL_IMPACT, headers=headers, json=payload, timeout=API_TIMEOUT_IMPACT_AGENT)
        response.raise_for_status()
        response_json_api = response.json()
        
        if response_json_api.get("choices") and response_json_api["choices"][0].get("message") and response_json_api["choices"][0]["message"].get("content"):
            generated_json_string = response_json_api["choices"][0]["message"]["content"]
            try:
                analysis_result = json.loads(generated_json_string)
                expected_keys = [
                    "estimated_impact_scale", "primary_affected_sectors", 
                    "secondary_affected_sectors_or_domains", "target_audience_relevance",
                    "timeframe_for_significant_impact", "impact_magnitude_qualifier",
                    "impact_confidence_score", "impact_rationale_summary"
                ]
                if all(key in analysis_result for key in expected_keys):
                    logger.info("ImpactScopeAgent analysis successful.")
                    return analysis_result
                else:
                    missing_keys = [key for key in expected_keys if key not in analysis_result]
                    logger.error(f"ImpactScopeAgent returned JSON missing required keys: {missing_keys}. Response: {analysis_result}")
                    return None
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode JSON from ImpactScopeAgent: {generated_json_string}. Error: {e}")
                match = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', generated_json_string, re.DOTALL)
                if match:
                    try:
                        analysis_result = json.loads(match.group(1))
                        if all(key in analysis_result for key in expected_keys):
                             logger.info("ImpactScopeAgent (fallback extraction) successful.")
                             return analysis_result
                    except Exception as fallback_e:
                        logger.error(f"ImpactScopeAgent fallback JSON extraction also failed: {fallback_e}")
                return None
        else:
            logger.error(f"ImpactScopeAgent response missing expected content: {response_json_api}")
            return None
            
    except requests.exceptions.RequestException as e:
        logger.error(f"ImpactScopeAgent API request failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
             logger.error(f"ImpactScopeAgent API Response Content: {e.response.text}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error in call_impact_scope_agent_llm: {e}")
        return None

# --- Main Agent Function ---
def run_impact_scope_agent(article_pipeline_data: dict):
    article_id = article_pipeline_data.get('id', 'unknown_id')
    logger.info(f"--- Running ImpactScopeAgent for Article ID: {article_id} ---")

    # Prepare inputs from EditorialPrime and NoveltyAgent outputs
    core_subject_event = article_pipeline_data.get('core_subject_event', 'N/A')
    first_pass_summary = article_pipeline_data.get('first_pass_summary', 'N/A')
    prelim_novelty_statement = article_pipeline_data.get('preliminary_novelty_impact_statement', 'N/A')
    prelim_key_entities = article_pipeline_data.get('preliminary_key_entities', [])
    tech_relevance = article_pipeline_data.get('tech_relevance_score', 0.0)
    novelty_assessment_data = article_pipeline_data.get('novelty_assessment', {"novelty_level": "None", "novelty_confidence": 0.0})
    
    # Use a relevant snippet of the article body
    # Prefer assembled_article_body_md if available (after content generation), else raw_scraped_text
    article_text_source = article_pipeline_data.get('assembled_article_body_md', article_pipeline_data.get('raw_scraped_text', ''))
    article_snippet_for_impact = article_text_source[:MAX_ARTICLE_SNIPPET_FOR_IMPACT]

    if not core_subject_event or core_subject_event == 'N/A' or not article_snippet_for_impact.strip():
        logger.warning(f"Insufficient data (core subject or snippet) for ImpactScopeAgent on article {article_id}. Skipping.")
        article_pipeline_data['impact_scope_assessment'] = {
            "estimated_impact_scale": "Uncertain/Too Early", "impact_confidence_score": 0.0,
            "impact_rationale_summary": "Skipped due to insufficient input from prior stages."
        }
        article_pipeline_data['impact_scope_agent_status'] = "SKIPPED_INSUFFICIENT_INPUT"
        return article_pipeline_data

    impact_scope_input = {
        "core_subject_event": core_subject_event,
        "first_pass_summary": first_pass_summary,
        "preliminary_novelty_impact_statement": prelim_novelty_statement,
        "preliminary_key_entities": prelim_key_entities,
        "article_snippet": article_snippet_for_impact,
        "tech_relevance_score": tech_relevance,
        "novelty_assessment": novelty_assessment_data
    }

    impact_assessment_result = call_impact_scope_agent_llm(impact_scope_input)

    if impact_assessment_result:
        article_pipeline_data['impact_scope_assessment'] = impact_assessment_result
        article_pipeline_data['impact_scope_agent_status'] = "SUCCESS"
        logger.info(f"ImpactScopeAgent for {article_id} SUCCESS. Scale: {impact_assessment_result.get('estimated_impact_scale')}, Magnitude: {impact_assessment_result.get('impact_magnitude_qualifier')}")
    else:
        logger.error(f"ImpactScopeAgent FAILED for article {article_id}.")
        article_pipeline_data['impact_scope_assessment'] = {
            "estimated_impact_scale": "Uncertain/Too Early", "impact_confidence_score": 0.0,
            "impact_rationale_summary": "ImpactScopeAgent LLM call failed or returned invalid data."
        }
        article_pipeline_data['impact_scope_agent_status'] = "FAILED_LLM_CALL"
        
    return article_pipeline_data

# --- Standalone Execution Example ---
if __name__ == "__main__":
    if not logger.handlers:
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
                            format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')
    
    if not DEEPSEEK_API_KEY_IMPACT:
        logger.error("DEEPSEEK_API_KEY_IMPACT not set in .env. Cannot run standalone test for ImpactScopeAgent.")
        sys.exit(1)

    logger.info("--- Starting ImpactScopeAgent Standalone Test ---")

    # Mock data that would come from EditorialPrime and NoveltyAgent
    mock_pipeline_data_input = {
        'id': 'test_impact_001',
        'core_subject_event': "NVIDIA unveils 'Zeus' Quantum AI Chip with 1000x performance leap",
        'first_pass_summary': "NVIDIA CEO Jensen Huang announced the 'Zeus' quantum-entangled AI accelerator, claiming a 1000x performance increase over current models for specific tasks. Key partners like Google DeepMind and OpenAI have early access.",
        'preliminary_novelty_impact_statement': "The 'Zeus' chip represents a paradigm shift in AI acceleration, potentially unlocking AGI.",
        'preliminary_key_entities': ["NVIDIA", "Jensen Huang", "Zeus", "Google DeepMind", "OpenAI", "Microsoft Azure"],
        'raw_scraped_text': """LAS VEGAS - At its annual GTC conference, NVIDIA CEO Jensen Huang today stunned the world by announcing the company's newest AI accelerator, a quantum-entangled processor codenamed 'Zeus'. Huang claimed Zeus offers an unprecedented thousand-fold performance increase over their current flagship H200 series for specific quantum-sensitive large model training tasks. The chip features a revolutionary hybrid architecture with 1024 physical qubits integrated alongside advanced classical tensor cores, all manufactured on a new 0.5nm GAA process. Early demonstrations showcased Zeus solving complex protein folding problems in minutes, tasks that previously took days on supercomputers. "Zeus is not just an evolution, it's a paradigm shift that will unlock AGI," Huang declared during the electrifying keynote. Key partners including Google DeepMind and OpenAI have already received early access development kits and are reporting groundbreaking results. Microsoft Azure announced immediate plans to build 'Zeus Pods' for specialized quantum AI cloud services, available Q1 2026. This development is expected to dramatically accelerate research in materials science, drug discovery, and fundamental physics. The stock market reacted instantly.""",
        'tech_relevance_score': 1.0,
        'novelty_assessment': {
            "novelty_level": "Revolutionary",
            "novelty_confidence": 0.95,
            "breakthrough_evidence": [
              "thousand-fold performance increase",
              "revolutionary hybrid architecture with 1024 physical qubits",
              "paradigm shift that will unlock AGI"
            ]
        }
    }

    logger.info(f"\n--- Testing ImpactScopeAgent with mock data for '{mock_pipeline_data_input['id']}' ---")
    result_data = run_impact_scope_agent(mock_pipeline_data_input.copy())
    
    logger.info(f"\nImpactScopeAgent Status: {result_data.get('impact_scope_agent_status')}")
    logger.info("Full Impact Scope Assessment:")
    print(json.dumps(result_data.get('impact_scope_assessment'), indent=2))

    assert result_data.get('impact_scope_agent_status') == "SUCCESS"
    assert result_data.get('impact_scope_assessment', {}).get('estimated_impact_scale') is not None
    assert isinstance(result_data.get('impact_scope_assessment', {}).get('target_audience_relevance', {}).get('researchers_academics'), float)

    logger.info("--- ImpactScopeAgent Standalone Test Complete ---")
