# src/agents/sophistication_stylist_agent.py

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
DEEPSEEK_API_KEY_STYLE = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_CHAT_API_URL_STYLE = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL_STYLE_AGENT = "deepseek-chat" 
API_TIMEOUT_STYLE_AGENT = 180
MAX_ARTICLE_SNIPPET_FOR_STYLE = 1500 # Max chars from raw_text/assembled_body for style analysis

# --- SophisticationStylistAgent System Prompt ---
SOPHISTICATIONSTYLISTAGENT_SYSTEM_PROMPT = """
You are **SophisticationStylistAgent**, an ASI-level Content Style & Depth Critic. Your mission is to evaluate a technology article snippet for its technical depth, language sophistication, and tone appropriateness for a highly knowledgeable tech audience. You will receive raw inputs from upstream agents; your task is to analyze them and output *only* the JSON object defined below—no extra keys or commentary.

**Inputs Available**
- `core_subject_event` (string)
- `first_pass_summary` (string)
- `article_snippet` (string)
- `preliminary_key_entities` (array of strings)
- `tech_relevance_score` (float 0.0–1.0)
- `novelty_level` (string from NoveltyAgent)
- `impact_magnitude_qualifier` (string from ImpactScopeAgent)
- `readability_score_flesch` (float)

**Analysis Instructions**
1. **Technical Depth**
   - Compare detail in `article_snippet` with expectations given `core_subject_event` and `novelty_level`.
   - Categorize as:
     - **Surface-Level**
     - **Moderately In-Depth**
     - **Deeply Technical**
     - **Overly Simplistic**
     - **Excessively Jargony (Unexplained)**

2. **Language Sophistication**
   - Assess vocabulary precision, sentence complexity, and nuance.
   - Choose one:
     - **High (Precise & Nuanced)**
     - **Appropriate (Clear & Professional)**
     - **Basic (Lacks Nuance)**
     - **Colloquial/Informal**

3. **Tone Suitability for Experts**
   - Judge whether tone aligns with expert expectations:
     - **Highly Suitable**
     - **Generally Suitable**
     - **Borderline (May need adjustments)**
     - **Not Suitable (Too basic/promotional)**

4. **Clarity of Explanation**
   - For core technical points, assign a float (0.0–1.0) for how clearly they’re explained.

5. **Jargon Usage Evaluation**
   - Determine if jargon is:
     - **Well-Explained**
     - **Acceptable with Context**
     - **Excessive & Unexplained**

6. **Key Observations on Style**
   - In 1–2 sentences, note specific stylistic strengths or weaknesses.

7. **Overall Stylistic Recommendation**
   - Choose one:
     - **Publish As Is (Style)**
     - **Minor Edits for Clarity/Tone**
     - **Substantial Rewrite for Depth/Sophistication**
     - **Reject (Style Unsuitable)**

8. **Readability Score**
   - Incorporate `readability_score_flesch` as a supporting signal; low scores may be acceptable for “Deeply Technical” if jargon is well-managed, and high scores may reveal oversimplification.

**Output Schema (strict JSON only)**
```json
{
  "technical_depth_level": "Surface-Level|Moderately In-Depth|Deeply Technical|Overly Simplistic|Excessively Jargony (Unexplained)",
  "language_sophistication": "High (Precise & Nuanced)|Appropriate (Clear & Professional)|Basic (Lacks Nuance)|Colloquial/Informal",
  "tone_suitability_for_experts": "Highly Suitable|Generally Suitable|Borderline (May need adjustments)|Not Suitable (Too basic/promotional)",
  "clarity_of_explanation_score": 0.0,
  "jargon_usage_evaluation": "Well-Explained|Acceptable with Context|Excessive & Unexplained",
  "key_observations_on_style": "string",
  "overall_stylistic_recommendation": "Publish As Is (Style)|Minor Edits for Clarity/Tone|Substantial Rewrite for Depth/Sophistication|Reject (Style Unsuitable)"
}
```
"""

# --- SophisticationStylistAgent User Prompt Template (Conceptual) ---
# The actual user prompt content will be a JSON string of the input dictionary.
SOPHISTICATIONSTYLISTAGENT_USER_TEMPLATE_CONCEPT = """
Evaluate the following JSON input and output *only* the JSON style assessment as specified in your system prompt:
```json
{
  "core_subject_event": "{core_subject_event}",
  "first_pass_summary": "{first_pass_summary}",
  "article_snippet": "{article_snippet}",
  "preliminary_key_entities": ["{key_entity_1}", "{key_entity_2}"],
  "tech_relevance_score": {tech_relevance_score},
  "novelty_level": "{novelty_level}",
  "impact_magnitude_qualifier": "{impact_magnitude_qualifier}",
  "readability_score_flesch": {readability_score_flesch}
}
```
"""

# --- LLM Call Function ---
def call_sophistication_stylist_agent_llm(input_data_dict: dict):
    if not DEEPSEEK_API_KEY_STYLE:
        logger.error("DEEPSEEK_API_KEY_STYLE not found for SophisticationStylistAgent.")
        return None

    user_prompt_content_str = json.dumps(input_data_dict)
    
    payload = {
        "model": DEEPSEEK_MODEL_STYLE_AGENT,
        "messages": [
            {"role": "system", "content": SOPHISTICATIONSTYLISTAGENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt_content_str} 
        ],
        "temperature": 0.2, 
        "response_format": {"type": "json_object"} 
    }
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY_STYLE}", "Content-Type": "application/json"}

    try:
        logger.debug(f"Sending SophisticationStylistAgent request. User data (first 100): {user_prompt_content_str[:100]}...")
        response = requests.post(DEEPSEEK_CHAT_API_URL_STYLE, headers=headers, json=payload, timeout=API_TIMEOUT_STYLE_AGENT)
        response.raise_for_status()
        response_json_api = response.json()
        
        if response_json_api.get("choices") and response_json_api["choices"][0].get("message") and response_json_api["choices"][0]["message"].get("content"):
            generated_json_string = response_json_api["choices"][0]["message"]["content"]
            try:
                analysis_result = json.loads(generated_json_string)
                expected_keys = [
                    "technical_depth_level", "language_sophistication", "tone_suitability_for_experts",
                    "clarity_of_explanation_score", "jargon_usage_evaluation", 
                    "key_observations_on_style", "overall_stylistic_recommendation"
                ]
                if all(key in analysis_result for key in expected_keys):
                    logger.info("SophisticationStylistAgent analysis successful.")
                    return analysis_result
                else:
                    missing_keys = [key for key in expected_keys if key not in analysis_result]
                    logger.error(f"SophisticationStylistAgent returned JSON missing required keys: {missing_keys}. Response: {analysis_result}")
                    return None
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode JSON from SophisticationStylistAgent: {generated_json_string}. Error: {e}")
                match = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', generated_json_string, re.DOTALL)
                if match:
                    try:
                        analysis_result = json.loads(match.group(1))
                        if all(key in analysis_result for key in expected_keys):
                             logger.info("SophisticationStylistAgent (fallback extraction) successful.")
                             return analysis_result
                    except Exception as fallback_e:
                        logger.error(f"SophisticationStylistAgent fallback JSON extraction also failed: {fallback_e}")
                return None
        else:
            logger.error(f"SophisticationStylistAgent response missing expected content: {response_json_api}")
            return None
            
    except requests.exceptions.RequestException as e:
        logger.error(f"SophisticationStylistAgent API request failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
             logger.error(f"SophisticationStylistAgent API Response Content: {e.response.text}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error in call_sophistication_stylist_agent_llm: {e}")
        return None

# --- Main Agent Function ---
def run_sophistication_stylist_agent(article_pipeline_data: dict):
    article_id = article_pipeline_data.get('id', 'unknown_id')
    logger.info(f"--- Running SophisticationStylistAgent for Article ID: {article_id} ---")

    # Prepare inputs from previous agent outputs
    core_subject_event = article_pipeline_data.get('core_subject_event', 'N/A')
    first_pass_summary = article_pipeline_data.get('first_pass_summary', 'N/A') # From EditorialPrime
    prelim_key_entities = article_pipeline_data.get('preliminary_key_entities', [])
    tech_relevance = article_pipeline_data.get('tech_relevance_score', 0.0)
    
    novelty_assessment = article_pipeline_data.get('novelty_assessment', {})
    novelty_level = novelty_assessment.get("novelty_level", "None")
    
    impact_scope_assessment = article_pipeline_data.get('impact_scope_assessment', {})
    impact_magnitude = impact_scope_assessment.get("impact_magnitude_qualifier", "Negligible")

    readability_flesch = article_pipeline_data.get('readability_score') # Already calculated
    
    article_text_source = article_pipeline_data.get('assembled_article_body_md', article_pipeline_data.get('raw_scraped_text', ''))
    article_snippet_for_style = article_text_source[:MAX_ARTICLE_SNIPPET_FOR_STYLE]

    default_style_assessment = {
        "technical_depth_level": "Uncertain", "language_sophistication": "Uncertain", 
        "tone_suitability_for_experts": "Uncertain", "clarity_of_explanation_score": 0.0,
        "jargon_usage_evaluation": "Uncertain", 
        "key_observations_on_style": "Style assessment LLM call failed or returned invalid data.",
        "overall_stylistic_recommendation": "Minor Edits for Clarity/Tone" # Default to caution
    }

    if not core_subject_event or core_subject_event == 'N/A' or not article_snippet_for_style.strip():
        logger.warning(f"Insufficient data (core subject or snippet) for SophisticationStylistAgent on article {article_id}. Skipping.")
        article_pipeline_data['style_assessment'] = default_style_assessment
        article_pipeline_data['sophistication_stylist_agent_status'] = "SKIPPED_INSUFFICIENT_INPUT"
        return article_pipeline_data

    style_agent_input = {
        "core_subject_event": core_subject_event,
        "first_pass_summary": first_pass_summary,
        "article_snippet": article_snippet_for_style,
        "preliminary_key_entities": prelim_key_entities,
        "tech_relevance_score": tech_relevance,
        "novelty_level": novelty_level,
        "impact_magnitude_qualifier": impact_magnitude,
        "readability_score_flesch": readability_flesch
    }

    style_assessment_result = call_sophistication_stylist_agent_llm(style_agent_input)

    if style_assessment_result:
        article_pipeline_data['style_assessment'] = style_assessment_result
        article_pipeline_data['sophistication_stylist_agent_status'] = "SUCCESS"
        logger.info(f"SophisticationStylistAgent for {article_id} SUCCESS. Recommendation: {style_assessment_result.get('overall_stylistic_recommendation')}")
    else:
        logger.error(f"SophisticationStylistAgent FAILED for article {article_id}.")
        article_pipeline_data['style_assessment'] = default_style_assessment
        article_pipeline_data['sophistication_stylist_agent_status'] = "FAILED_LLM_CALL"
        
    return article_pipeline_data

# --- Standalone Execution Example ---
if __name__ == "__main__":
    if not logger.handlers:
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
                            format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')
    
    if not DEEPSEEK_API_KEY_STYLE:
        logger.error("DEEPSEEK_API_KEY_STYLE not set in .env. Cannot run standalone test for SophisticationStylistAgent.")
        sys.exit(1)

    logger.info("--- Starting SophisticationStylistAgent Standalone Test ---")

    # Mock data that would come from previous agents
    mock_pipeline_data_input_deep_tech = {
        'id': 'test_style_001',
        'core_subject_event': "New Quantum Entanglement Algorithm for AI Model Parallelization",
        'first_pass_summary': "Researchers have published a novel algorithm leveraging quantum entanglement principles to achieve near-lossless parallelization of large AI model training across distributed GPU clusters, potentially reducing training times by orders of magnitude for models exceeding 10 trillion parameters.",
        'raw_scraped_text': """
        A groundbreaking paper published in 'Nature Quantum Information' details a novel method named "Quantum-Linked Asynchronous Training" (QLAT). 
        The QLAT algorithm utilizes principles of controlled quantum entanglement to create non-local correlations between gradient updates across physically separate GPU nodes. 
        This allows for virtually instantaneous state synchronization without the bandwidth limitations of classical interconnects like NVLink or InfiniBand, especially critical for models with dense parameter matrices.
        The authors demonstrate a theoretical framework and initial simulation results suggesting a 98% reduction in inter-node communication overhead for a 13-trillion parameter mixture-of-experts model.
        Key challenges remain in engineering stable, room-temperature qubit arrays suitable for direct integration into data center hardware. However, the paper posits that even hybrid classical-quantum systems implementing QLAT could offer substantial speedups.
        This research could pave the way for training AI models of unprecedented scale and complexity.
        """,
        'preliminary_key_entities': ["QLAT Algorithm", "Nature Quantum Information", "Quantum Entanglement", "GPU Clusters", "AI Model Parallelization"],
        'tech_relevance_score': 1.0,
        'novelty_assessment': {"novelty_level": "Revolutionary", "novelty_confidence": 0.9},
        'impact_scope_assessment': {"impact_magnitude_qualifier": "Transformative"},
        'readability_score': 15.5 # Example low Flesch score for dense text
    }
    
    mock_pipeline_data_input_general_tech = {
        'id': 'test_style_002',
        'core_subject_event': "TechCorp launches 'ConnectSphere' social app with AI photo filters",
        'first_pass_summary': "TechCorp has released ConnectSphere, a new social networking application featuring AI-powered photo filters and a timeline focused on local events. The app aims to compete with Instagram and TikTok.",
        'raw_scraped_text': """
        Today, TechCorp officially launched ConnectSphere, its new social media app. Users can share photos and short videos. 
        A main selling point is its collection of AI-driven photo filters that can transform your selfies in fun ways. 
        The app also has a "Local Discoveries" feed which uses your location to show nearby events and happenings.
        "We want to bring people together in their communities," said TechCorp's CEO. 
        ConnectSphere is free to download on iOS and Android. It features a clean interface and easy sharing to other platforms.
        Early reviews are mixed, with some praising the local feed and others finding the filters similar to existing apps.
        """,
        'preliminary_key_entities': ["TechCorp", "ConnectSphere", "AI photo filters"],
        'tech_relevance_score': 0.6,
        'novelty_assessment': {"novelty_level": "Incremental", "novelty_confidence": 0.8},
        'impact_scope_assessment': {"impact_magnitude_qualifier": "Minor"},
        'readability_score': 65.2 
    }


    logger.info(f"\n--- Testing SophisticationStylistAgent with Deep Tech Article ---")
    result_data_deep_tech = run_sophistication_stylist_agent(mock_pipeline_data_input_deep_tech.copy())
    
    logger.info(f"\nSophisticationStylistAgent Status (Deep Tech): {result_data_deep_tech.get('sophistication_stylist_agent_status')}")
    logger.info("Full Style Assessment (Deep Tech):")
    print(json.dumps(result_data_deep_tech.get('style_assessment'), indent=2))
    assert result_data_deep_tech.get('sophistication_stylist_agent_status') == "SUCCESS"
    assert result_data_deep_tech.get('style_assessment', {}).get('technical_depth_level') in ["Deeply Technical", "Moderately In-Depth"]
    assert result_data_deep_tech.get('style_assessment', {}).get('tone_suitability_for_experts') == "Highly Suitable"


    logger.info(f"\n--- Testing SophisticationStylistAgent with General Tech Article ---")
    result_data_general_tech = run_sophistication_stylist_agent(mock_pipeline_data_input_general_tech.copy())

    logger.info(f"\nSophisticationStylistAgent Status (General Tech): {result_data_general_tech.get('sophistication_stylist_agent_status')}")
    logger.info("Full Style Assessment (General Tech):")
    print(json.dumps(result_data_general_tech.get('style_assessment'), indent=2))
    assert result_data_general_tech.get('sophistication_stylist_agent_status') == "SUCCESS"
    assert result_data_general_tech.get('style_assessment', {}).get('technical_depth_level') in ["Surface-Level", "Moderately In-Depth"]
    assert result_data_general_tech.get('style_assessment', {}).get('tone_suitability_for_experts') in ["Generally Suitable", "Borderline (May need adjustments)"]


    logger.info("--- SophisticationStylistAgent Standalone Test Complete ---")
