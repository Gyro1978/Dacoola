# src/agents/adjudicator_prime_agent.py

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
DEEPSEEK_API_KEY_ADJUDICATOR = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_CHAT_API_URL_ADJUDICATOR = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL_ADJUDICATOR_AGENT = "deepseek-chat" # Needs to be highly capable
API_TIMEOUT_ADJUDICATOR_AGENT = 200 # Allow ample time for comprehensive synthesis

# --- AdjudicatorPrimeAgent System Prompt ---
ADJUDICATORPRIMEAGENT_SYSTEM_PROMPT = """
You are **AdjudicatorPrimeAgent**, an ASI-level Chief Editor AI tasked with delivering a single, definitive publication verdict on a tech article by synthesizing multiple upstream specialist analyses. You must integrate all provided assessments into:

1. A final decision: “Publish Immediately”, “Publish with Minor Edits (Automated)”, “Flag for Human Review (Specific Concerns)”, or “Reject (Clear Reasons)”.
2. An **overall_value_excitement_score** (0–100).
3. A concise **decision_rationale_summary** citing key agent findings.
4. Up to three **key_strengths**.
5. Up to three **key_weaknesses_or_concerns**.
6. If not “Publish Immediately”, a list of **suggested_next_steps_for_human_editor**.

**Decision & Scoring Guidelines**
- **85–100 (High)**: Breaking/Revolutionary novelty, Transformative impact, top-tier corroboration, low hype, expert-level style. → Publish Immediately
- **70–84 (Good)**: Significant novelty, Substantial impact, solid corroboration, acceptable hype/style. → Publish with Minor Edits
- **50–69 (Moderate)**: Incremental novelty, Moderate impact, mixed signals (e.g. caution on hype/style). → Flag for Human Review
- **<50 (Low)**: No real novelty, Minor/Negligible impact, poor corroboration, high hype, unsuitable style. → Reject

**Decision Logic**
- **Publish Immediately** if score ≥ 85 **and** no “Proceed with Caution” flags from HypeDetector or StyleAgent **and** corroboration ≥ “Moderately Corroborated.”
- **Publish with Minor Edits** if 70–84 **and** only minor stylistic or factual tweaks needed (e.g., StyleAgent recommends "Minor Edits" but HypeDetector is "Proceed As Is").
- **Flag for Human Review** if score is 50–69 **or** there are significant mixed signals (e.g., HypeDetector says "Proceed with Caution," StyleAgent says "Substantial Rewrite," Corroboration is "Weakly Corroborated"). List specific concerns for the human editor.
- **Reject** if score < 50 **or** critical failures are identified (e.g., Corroboration is "Isolated Claim/Uncorroborated," HypeDetector recommends "Reject (Primarily Hype/PR)", EditorialPrime assessed as "Boring" without strong override and subsequent positive signals).

**Output Schema (Strict JSON Only)**
```json
{
  "final_publication_decision": "Publish Immediately|Publish with Minor Edits (Automated)|Flag for Human Review (Specific Concerns)|Reject (Clear Reasons)",
  "overall_value_excitement_score": 0,
  "decision_rationale_summary": "string",
  "key_strengths": ["string1","string2",…],
  "key_weaknesses_or_concerns": ["string1","string2",…],
  "suggested_next_steps_for_human_editor": ["string1","string2",…]
}
```

Output *only* this JSON object—no extra commentary or keys.
"""

# --- AdjudicatorPrimeAgent User Prompt Template (Conceptual) ---
# The actual user prompt content will be a JSON string of the input dictionary.
ADJUDICATORPRIMEAGENT_USER_TEMPLATE_CONCEPT = """
You will receive a single JSON object containing all prior agent assessments. Analyze and synthesize these into the final output specified in your system prompt.
```json
{
  "article_id": "{article_id}",
  "article_title": "{article_title}",
  "editorial_prime_assessment": { /* EditorialPrime output */ },
  "novelty_assessment":        { /* NoveltyAgent output */ },
  "impact_scope_assessment":   { /* ImpactScopeAgent output */ },
  "hype_assessment":           { /* HypeDetectorAgent output */ },
  "style_assessment":          { /* SophisticationStylistAgent output */ },
  "corroboration_assessment":  { /* CorroborationCognitoAgent output */ }
}
```
"""

# --- LLM Call Function ---
def call_adjudicator_prime_agent_llm(adjudicator_input_data_dict: dict):
    if not DEEPSEEK_API_KEY_ADJUDICATOR:
        logger.error("DEEPSEEK_API_KEY_ADJUDICATOR not found for AdjudicatorPrimeAgent.")
        return None

    user_prompt_content_str = json.dumps(adjudicator_input_data_dict)
    
    payload = {
        "model": DEEPSEEK_MODEL_ADJUDICATOR_AGENT,
        "messages": [
            {"role": "system", "content": ADJUDICATORPRIMEAGENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt_content_str} 
        ],
        "temperature": 0.1, # Very low for deterministic final judgment
        "response_format": {"type": "json_object"} 
    }
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY_ADJUDICATOR}", "Content-Type": "application/json"}

    try:
        logger.debug(f"Sending AdjudicatorPrimeAgent request. User data (first 100 for article_id '{adjudicator_input_data_dict.get('article_id')}'): {user_prompt_content_str[:100]}...")
        response = requests.post(DEEPSEEK_CHAT_API_URL_ADJUDICATOR, headers=headers, json=payload, timeout=API_TIMEOUT_ADJUDICATOR_AGENT)
        response.raise_for_status()
        response_json_api = response.json()
        
        if response_json_api.get("choices") and response_json_api["choices"][0].get("message") and response_json_api["choices"][0]["message"].get("content"):
            generated_json_string = response_json_api["choices"][0]["message"]["content"]
            try:
                analysis_result = json.loads(generated_json_string)
                expected_keys = [
                    "final_publication_decision", "overall_value_excitement_score",
                    "decision_rationale_summary", "key_strengths", 
                    "key_weaknesses_or_concerns", "suggested_next_steps_for_human_editor"
                ]
                if all(key in analysis_result for key in expected_keys):
                    logger.info("AdjudicatorPrimeAgent analysis successful.")
                    return analysis_result
                else:
                    missing_keys = [key for key in expected_keys if key not in analysis_result]
                    logger.error(f"AdjudicatorPrimeAgent returned JSON missing required keys: {missing_keys}. Response: {analysis_result}")
                    return None
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode JSON from AdjudicatorPrimeAgent: {generated_json_string}. Error: {e}")
                match = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', generated_json_string, re.DOTALL)
                if match:
                    try:
                        analysis_result = json.loads(match.group(1))
                        if all(key in analysis_result for key in expected_keys):
                             logger.info("AdjudicatorPrimeAgent (fallback extraction) successful.")
                             return analysis_result
                    except Exception as fallback_e:
                        logger.error(f"AdjudicatorPrimeAgent fallback JSON extraction also failed: {fallback_e}")
                return None
        else:
            logger.error(f"AdjudicatorPrimeAgent response missing expected content: {response_json_api}")
            return None
            
    except requests.exceptions.RequestException as e:
        logger.error(f"AdjudicatorPrimeAgent API request failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
             logger.error(f"AdjudicatorPrimeAgent API Response Content: {e.response.text}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error in call_adjudicator_prime_agent_llm: {e}")
        return None

# --- Main Agent Function ---
def run_adjudicator_prime_agent(article_pipeline_data: dict):
    article_id = article_pipeline_data.get('id', 'unknown_id')
    logger.info(f"--- Running AdjudicatorPrimeAgent for Article ID: {article_id} ---")

    # Consolidate all previous agent outputs into the expected input structure
    adjudicator_input = {
        "article_id": article_id,
        "article_title": article_pipeline_data.get('final_page_h1', article_pipeline_data.get('initial_title_from_web', 'N/A')),
        "editorial_prime_assessment": {
            "preliminary_importance_level": article_pipeline_data.get("preliminary_importance_level", "Boring"),
            "tech_relevance_score": article_pipeline_data.get("tech_relevance_score", 0.0),
            "critical_override_triggered": article_pipeline_data.get("critical_override_triggered", False),
            "critical_override_entity_reason": article_pipeline_data.get("critical_override_entity_reason", ""),
            "core_subject_event": article_pipeline_data.get("core_subject_event", "N/A"),
            "preliminary_novelty_impact_statement": article_pipeline_data.get("preliminary_novelty_impact_statement", ""),
            "preliminary_key_entities": article_pipeline_data.get("preliminary_key_entities", []),
            "first_pass_summary": article_pipeline_data.get("first_pass_summary", ""), # From EditorialPrime
            "editorial_prime_notes": article_pipeline_data.get("editorial_prime_notes", "")
        },
        "novelty_assessment": article_pipeline_data.get("novelty_assessment", {}),
        "impact_scope_assessment": article_pipeline_data.get("impact_scope_assessment", {}),
        "hype_assessment": article_pipeline_data.get("hype_assessment", {}),
        "style_assessment": article_pipeline_data.get("style_assessment", {}),
        "corroboration_assessment": article_pipeline_data.get("corroboration_assessment", {})
    }
    
    # Ensure all nested assessment dicts have default values if they are missing from pipeline_data
    # This prevents errors if an upstream agent failed to produce its output block.
    default_novelty = {"novelty_level": "None", "novelty_confidence": 0.0, "breakthrough_evidence": []}
    default_impact = {"estimated_impact_scale": "Uncertain/Too Early", "impact_magnitude_qualifier": "Negligible", "impact_confidence_score": 0.0, "primary_affected_sectors": [], "secondary_affected_sectors_or_domains": [], "target_audience_relevance": {}, "timeframe_for_significant_impact": "Speculative", "impact_rationale_summary": "Upstream impact assessment missing."}
    default_hype = {"hype_score": 0.5, "substantiation_level": "Partially Substantiated", "identified_hype_phrases_or_claims": [], "evidence_gaps_summary": "Upstream hype assessment missing.", "overall_content_tone_evaluation": "Neutral", "recommendation_for_publication": "Proceed with Caution (verify claims)"}
    default_style = {"technical_depth_level": "Uncertain", "language_sophistication": "Uncertain", "tone_suitability_for_experts": "Uncertain", "clarity_of_explanation_score": 0.0, "jargon_usage_evaluation": "Uncertain", "key_observations_on_style": "Upstream style assessment missing.", "overall_stylistic_recommendation": "Minor Edits for Clarity/Tone"}
    default_corroboration = {"corroboration_level": "Unable to Determine", "corroboration_confidence_score": 0.0, "supporting_source_domains_tier1": [], "supporting_source_domains_tier2": [], "conflicting_information_flag": False, "corroboration_summary_notes": "Upstream corroboration assessment missing."}

    for key, default_val in [
        ("novelty_assessment", default_novelty),
        ("impact_scope_assessment", default_impact),
        ("hype_assessment", default_hype),
        ("style_assessment", default_style),
        ("corroboration_assessment", default_corroboration)
    ]:
        if not adjudicator_input[key]: # If it's an empty dict or None
            adjudicator_input[key] = default_val
            logger.warning(f"Adjudicator input for '{key}' was missing/empty for article {article_id}, using defaults.")


    final_adjudication_result = call_adjudicator_prime_agent_llm(adjudicator_input)

    if final_adjudication_result:
        article_pipeline_data['final_adjudication'] = final_adjudication_result
        article_pipeline_data['adjudicator_prime_agent_status'] = "SUCCESS"
        logger.info(f"AdjudicatorPrimeAgent for {article_id} SUCCESS. Final Decision: {final_adjudication_result.get('final_publication_decision')}, Score: {final_adjudication_result.get('overall_value_excitement_score')}")
    else:
        logger.error(f"AdjudicatorPrimeAgent FAILED for article {article_id}.")
        article_pipeline_data['final_adjudication'] = {
            "final_publication_decision": "Flag for Human Review (Specific Concerns)", # Default to human review on failure
            "overall_value_excitement_score": 30, # Low score
            "decision_rationale_summary": "AdjudicatorPrime LLM call failed or returned invalid data. Manual review required.",
            "key_strengths": [],
            "key_weaknesses_or_concerns": ["AdjudicatorPrime LLM failure"],
            "suggested_next_steps_for_human_editor": ["Full manual review of all agent outputs and article content needed due to AdjudicatorPrime failure."]
        }
        article_pipeline_data['adjudicator_prime_agent_status'] = "FAILED_LLM_CALL"
        
    return article_pipeline_data

# --- Standalone Execution Example ---
if __name__ == "__main__":
    if not logger.handlers:
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
                            format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')
    
    if not DEEPSEEK_API_KEY_ADJUDICATOR:
        logger.error("DEEPSEEK_API_KEY_ADJUDICATOR not set in .env. Cannot run standalone test for AdjudicatorPrimeAgent.")
        sys.exit(1)

    logger.info("--- Starting AdjudicatorPrimeAgent Standalone Test ---")

    # Mock data simulating outputs from all previous agents for a high-quality article
    mock_full_pipeline_data_publish = {
        'id': 'test_adjudicate_001_publish',
        'final_page_h1': "NVIDIA's 'Zeus' Chip Redefines AI Quantum Frontiers",
        'editorial_prime_assessment': {
            "preliminary_importance_level": "Breaking", "tech_relevance_score": 1.0,
            "critical_override_triggered": True, "critical_override_entity_reason": "NVIDIA - Major chip announcement",
            "core_subject_event": "NVIDIA 'Zeus' Quantum AI Chip launch",
            "preliminary_novelty_impact_statement": "Potential to unlock AGI with 1000x speedup.",
            "preliminary_key_entities": ["NVIDIA", "Zeus", "Quantum AI", "Jensen Huang"],
            "first_pass_summary": "NVIDIA announced Zeus, a quantum AI chip with transformative performance.",
            "editorial_prime_notes": "Verify 1000x claim if possible."
        },
        'novelty_assessment': {
            "novelty_level": "Revolutionary", "novelty_confidence": 0.95,
            "breakthrough_evidence": ["1000x performance increase", "hybrid architecture with 1024 physical qubits"]
        },
        'impact_scope_assessment': {
            "estimated_impact_scale": "Global & Cross-Industry",
            "primary_affected_sectors": ["AI Research", "Pharmaceuticals", "Materials Science", "Cloud Computing"],
            "secondary_affected_sectors_or_domains": ["Finance", "Logistics"],
            "target_audience_relevance": {"researchers_academics": 1.0, "technical_leads_architects": 0.9, "investors_financial_analysts": 0.9, "c_suite_executives": 0.8},
            "timeframe_for_significant_impact": "Medium-term (1.5-3 years)",
            "impact_magnitude_qualifier": "Transformative",
            "impact_confidence_score": 0.9,
            "impact_rationale_summary": "Revolutionary performance jump set to redefine multiple research and industrial sectors globally."
        },
        'hype_assessment': {
            "hype_score": 0.2, "substantiation_level": "Well-Substantiated",
            "identified_hype_phrases_or_claims": [], "evidence_gaps_summary": "Performance claims are bold but cited from official announcements and CEO statements.",
            "overall_content_tone_evaluation": "Balanced but Optimistic",
            "recommendation_for_publication": "Proceed As Is"
        },
        'style_assessment': {
            "technical_depth_level": "Deeply Technical", "language_sophistication": "High (Precise & Nuanced)",
            "tone_suitability_for_experts": "Highly Suitable", "clarity_of_explanation_score": 0.85,
            "jargon_usage_evaluation": "Well-Explained",
            "key_observations_on_style": "Excellent balance of technical detail and accessible explanation of impact.",
            "overall_stylistic_recommendation": "Publish As Is (Style)"
        },
        'corroboration_assessment': {
            "corroboration_level": "Strongly Corroborated", "corroboration_confidence_score": 0.95,
            "supporting_source_domains_tier1": ["reuters.com", "techcrunch.com", "wired.com"],
            "supporting_source_domains_tier2": ["nvidia-research-blog.com"],
            "conflicting_information_flag": False,
            "corroboration_summary_notes": "Widely reported by Tier 1 tech and news media, aligning with official NVIDIA announcements."
        }
    }

    logger.info(f"\n--- Testing AdjudicatorPrimeAgent with High-Quality Article Data ---")
    result_data_publish = run_adjudicator_prime_agent(mock_full_pipeline_data_publish.copy())
    
    logger.info(f"\nAdjudicatorPrimeAgent Status (High-Quality): {result_data_publish.get('adjudicator_prime_agent_status')}")
    logger.info("Full Adjudication:")
    print(json.dumps(result_data_publish.get('final_adjudication'), indent=2))
    assert result_data_publish.get('adjudicator_prime_agent_status') == "SUCCESS"
    assert result_data_publish.get('final_adjudication', {}).get('final_publication_decision') == "Publish Immediately"
    assert result_data_publish.get('final_adjudication', {}).get('overall_value_excitement_score', 0) >= 85


    # Mock data for an article that should be rejected
    mock_full_pipeline_data_reject = {
        'id': 'test_adjudicate_002_reject',
        'final_page_h1': "My New Blog About Tech Ideas",
        'editorial_prime_assessment': {
            "preliminary_importance_level": "Boring", "tech_relevance_score": 0.1,
            "critical_override_triggered": False, "critical_override_entity_reason": "",
            "core_subject_event": "Personal blog launch",
            "preliminary_novelty_impact_statement": "No discernible novelty or impact.",
            "preliminary_key_entities": ["My Blog"], "first_pass_summary": "Author launched a new blog.",
            "editorial_prime_notes": "Seems like self-promotion, not news."
        },
        'novelty_assessment': {"novelty_level": "None", "novelty_confidence": 0.9},
        'impact_scope_assessment': {"estimated_impact_scale": "Localized/Limited", "impact_magnitude_qualifier": "Negligible", "impact_confidence_score": 0.2},
        'hype_assessment': {"hype_score": 0.1, "substantiation_level": "Well-Substantiated", "recommendation_for_publication": "Proceed As Is"}, # Hype might be low if it's just factual about a blog
        'style_assessment': {"technical_depth_level": "Surface-Level", "language_sophistication": "Basic (Lacks Nuance)", "tone_suitability_for_experts": "Not Suitable (Too basic/promotional)", "overall_stylistic_recommendation": "Reject (Style Unsuitable)"},
        'corroboration_assessment': {"corroboration_level": "Isolated Claim/Uncorroborated", "corroboration_confidence_score": 0.1}
    }
    logger.info(f"\n--- Testing AdjudicatorPrimeAgent with Low-Quality Article Data ---")
    result_data_reject = run_adjudicator_prime_agent(mock_full_pipeline_data_reject.copy())

    logger.info(f"\nAdjudicatorPrimeAgent Status (Low-Quality): {result_data_reject.get('adjudicator_prime_agent_status')}")
    logger.info("Full Adjudication (Low-Quality):")
    print(json.dumps(result_data_reject.get('final_adjudication'), indent=2))
    assert result_data_reject.get('adjudicator_prime_agent_status') == "SUCCESS"
    assert result_data_reject.get('final_adjudication', {}).get('final_publication_decision') == "Reject (Clear Reasons)"
    assert result_data_reject.get('final_adjudication', {}).get('overall_value_excitement_score', 100) < 50


    logger.info("--- AdjudicatorPrimeAgent Standalone Test Complete ---")
