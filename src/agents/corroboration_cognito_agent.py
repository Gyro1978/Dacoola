# src/agents/corroboration_cognito_agent.py

import os
import sys
import json
import logging
import requests 
import re
from urllib.parse import urlparse # To extract domain from article_source_url

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
DEEPSEEK_API_KEY_CORROB = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_CHAT_API_URL_CORROB = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL_CORROB_AGENT = "deepseek-chat" 
API_TIMEOUT_CORROB_AGENT = 180
MAX_SIMULATED_SEARCH_RESULTS = 7 # Number of mock search results to generate for the LLM

# --- CorroborationCognitoAgent System Prompt ---
CORROBORATIONCOGNITOAGENT_SYSTEM_PROMPT = """
You are **CorroborationCognitoAgent**, an ASI-level Fact‐Verification and Source Analysis Specialist. Your sole mission is to evaluate how well a reported tech event is corroborated by external, authoritative publications. You will receive a core subject/event, key entities, the original article’s source domain, and a list of simulated news search results. Analyze only those inputs and output *only* the JSON object defined below—no extra keys, no commentary.

**Your Analysis Tasks**

1. **Match Relevance**
   - Confirm each search result title/snippet pertains to the same `core_subject_event` and involves at least one of the `preliminary_key_entities`.

2. **Tier Classification**
   - **Tier 1**: Global, high-authority outlets (e.g., Reuters, AP, Bloomberg, NYT, WSJ, BBC) *and* top tech publications (TechCrunch, The Verge, Wired, Ars Technica).
   - **Tier 2**: Reputable niche tech sites, industry-specific blogs, non-primary official company blogs of *other* involved entities.
   - Exclude the `article_source_domain` from corroboration counts.

3. **Corroboration Level**
   - **Strongly Corroborated**: ≥ 3 distinct Tier 1 sources reporting the same event.
   - **Moderately Corroborated**: ≥ 2 sources across Tier 1/2, or ≥ 3 Tier 2 sources.
   - **Weakly Corroborated**: 1–2 Tier 2 sources only.
   - **Isolated Claim/Uncorroborated**: No relevant Tier 1/2 corroboration.
   - **Unable to Determine**: Results ambiguous or off-topic.

4. **Conflicting Information**
   - If different sources directly contradict key facts (e.g. date, specifications, performance claims), set `conflicting_information_flag` = `true`.

5. **Confidence Scoring**
   - Assign `corroboration_confidence_score` (0.0–1.0) based on clarity, number, and authority of corroborating results.

6. **Summary Notes**
   - Concisely explain your reasoning, naming key tier-1/2 domains or noting the lack thereof and any conflicts.

**Output Schema (strict JSON only)**
```json
{
  "corroboration_level": "Strongly Corroborated|Moderately Corroborated|Weakly Corroborated|Isolated Claim/Uncorroborated|Unable to Determine",
  "corroboration_confidence_score": 0.0,
  "supporting_source_domains_tier1": ["string1.com","string2.net",…],
  "supporting_source_domains_tier2": ["string1.org","string2.dev",…],
  "conflicting_information_flag": true|false,
  "corroboration_summary_notes": "string"
}
```
"""

# --- CorroborationCognitoAgent User Prompt Template (Conceptual) ---
# The actual user prompt content will be a JSON string of the input dictionary.
CORROBORATIONCOGNITOAGENT_USER_TEMPLATE_CONCEPT = """
Analyze the following JSON input and return *only* the JSON corroboration assessment as specified in your system prompt:
```json
{
  "core_subject_event": "{core_subject_event}",
  "preliminary_key_entities": ["{key_entity_1}", "{key_entity_2}"],
  "article_source_domain": "{article_source_domain}",
  "simulated_news_search_results": [
    {
      "title": "{result1_title}",
      "link": "{result1_link}",
      "source_domain": "{result1_domain}",
      "snippet": "{result1_snippet}",
      "date_approx": "{result1_date}"
    }
    // ... more results
  ]
}
```
"""

# --- LLM Call Function ---
def call_corroboration_cognito_agent_llm(input_data_dict: dict):
    if not DEEPSEEK_API_KEY_CORROB:
        logger.error("DEEPSEEK_API_KEY_CORROB not found for CorroborationCognitoAgent.")
        return None

    user_prompt_content_str = json.dumps(input_data_dict)
    
    payload = {
        "model": DEEPSEEK_MODEL_CORROB_AGENT,
        "messages": [
            {"role": "system", "content": CORROBORATIONCOGNITOAGENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt_content_str} 
        ],
        "temperature": 0.1, # Very low temperature for factual analysis
        "response_format": {"type": "json_object"} 
    }
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY_CORROB}", "Content-Type": "application/json"}

    try:
        logger.debug(f"Sending CorroborationCognitoAgent request. User data (first 100): {user_prompt_content_str[:100]}...")
        response = requests.post(DEEPSEEK_CHAT_API_URL_CORROB, headers=headers, json=payload, timeout=API_TIMEOUT_CORROB_AGENT)
        response.raise_for_status()
        response_json_api = response.json()
        
        if response_json_api.get("choices") and response_json_api["choices"][0].get("message") and response_json_api["choices"][0]["message"].get("content"):
            generated_json_string = response_json_api["choices"][0]["message"]["content"]
            try:
                analysis_result = json.loads(generated_json_string)
                expected_keys = [
                    "corroboration_level", "corroboration_confidence_score", 
                    "supporting_source_domains_tier1", "supporting_source_domains_tier2",
                    "conflicting_information_flag", "corroboration_summary_notes"
                ]
                if all(key in analysis_result for key in expected_keys):
                    logger.info("CorroborationCognitoAgent analysis successful.")
                    return analysis_result
                else:
                    missing_keys = [key for key in expected_keys if key not in analysis_result]
                    logger.error(f"CorroborationCognitoAgent returned JSON missing required keys: {missing_keys}. Response: {analysis_result}")
                    return None
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode JSON from CorroborationCognitoAgent: {generated_json_string}. Error: {e}")
                match = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', generated_json_string, re.DOTALL)
                if match:
                    try:
                        analysis_result = json.loads(match.group(1))
                        if all(key in analysis_result for key in expected_keys):
                             logger.info("CorroborationCognitoAgent (fallback extraction) successful.")
                             return analysis_result
                    except Exception as fallback_e:
                        logger.error(f"CorroborationCognitoAgent fallback JSON extraction also failed: {fallback_e}")
                return None
        else:
            logger.error(f"CorroborationCognitoAgent response missing expected content: {response_json_api}")
            return None
            
    except requests.exceptions.RequestException as e:
        logger.error(f"CorroborationCognitoAgent API request failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
             logger.error(f"CorroborationCognitoAgent API Response Content: {e.response.text}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error in call_corroboration_cognito_agent_llm: {e}")
        return None

# --- Main Agent Function ---
def run_corroboration_cognito_agent(article_pipeline_data: dict, simulated_search_results: list = None):
    article_id = article_pipeline_data.get('id', 'unknown_id')
    logger.info(f"--- Running CorroborationCognitoAgent for Article ID: {article_id} ---")

    core_subject_event = article_pipeline_data.get('core_subject_event', 'N/A')
    prelim_key_entities = article_pipeline_data.get('preliminary_key_entities', [])
    
    article_source_url = article_pipeline_data.get('original_source_url', '')
    article_source_domain = ""
    if article_source_url:
        try:
            article_source_domain = urlparse(article_source_url).netloc.replace('www.', '')
        except Exception:
            logger.warning(f"Could not parse domain from article_source_url: {article_source_url}")

    default_corroboration_assessment = {
        "corroboration_level": "Unable to Determine",
        "corroboration_confidence_score": 0.0,
        "supporting_source_domains_tier1": [],
        "supporting_source_domains_tier2": [],
        "conflicting_information_flag": False,
        "corroboration_summary_notes": "Corroboration LLM call failed or input was insufficient."
    }

    if not core_subject_event or core_subject_event == 'N/A':
        logger.warning(f"Insufficient data (core subject event) for CorroborationCognitoAgent on article {article_id}. Skipping.")
        article_pipeline_data['corroboration_assessment'] = default_corroboration_assessment
        article_pipeline_data['corroboration_cognito_agent_status'] = "SKIPPED_INSUFFICIENT_INPUT"
        return article_pipeline_data
    
    # In a real system, `simulated_search_results` would come from a live search tool.
    # For now, it's passed in, especially for testing.
    if simulated_search_results is None:
        logger.warning(f"No search results provided for CorroborationCognitoAgent on {article_id}. Simulating empty or relying on LLM's general knowledge if any.")
        simulated_search_results_for_llm = [] # Pass empty if none provided
    else:
        simulated_search_results_for_llm = simulated_search_results[:MAX_SIMULATED_SEARCH_RESULTS]


    corroboration_agent_input = {
        "core_subject_event": core_subject_event,
        "preliminary_key_entities": prelim_key_entities,
        "article_source_domain": article_source_domain,
        "simulated_news_search_results": simulated_search_results_for_llm 
    }

    corroboration_assessment_result = call_corroboration_cognito_agent_llm(corroboration_agent_input)

    if corroboration_assessment_result:
        article_pipeline_data['corroboration_assessment'] = corroboration_assessment_result
        article_pipeline_data['corroboration_cognito_agent_status'] = "SUCCESS"
        logger.info(f"CorroborationCognitoAgent for {article_id} SUCCESS. Level: {corroboration_assessment_result.get('corroboration_level')}")
    else:
        logger.error(f"CorroborationCognitoAgent FAILED for article {article_id}.")
        article_pipeline_data['corroboration_assessment'] = default_corroboration_assessment
        article_pipeline_data['corroboration_cognito_agent_status'] = "FAILED_LLM_CALL"
        
    return article_pipeline_data

# --- Standalone Execution Example ---
if __name__ == "__main__":
    if not logger.handlers:
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
                            format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')
    
    if not DEEPSEEK_API_KEY_CORROB:
        logger.error("DEEPSEEK_API_KEY_CORROB not set in .env. Cannot run standalone test for CorroborationCognitoAgent.")
        sys.exit(1)

    logger.info("--- Starting CorroborationCognitoAgent Standalone Test ---")

    # Mock data from previous agents
    mock_pipeline_data_from_editorial_prime = {
        'id': 'test_corrob_001',
        'original_source_url': 'https://myblog.example.com/exclusive-agi-achieved',
        'core_subject_event': "Startup 'FutureAI' Claims AGI Achieved with New 'OmegaMind' Model",
        'preliminary_key_entities': ["FutureAI", "OmegaMind", "AGI", "Dr. Enigma"],
    }

    # Simulate news search results
    mock_search_results_strong = [
        {"title": "FutureAI Announces OmegaMind: Is This AGI?", "link": "https://techcrunch.com/futureai-omegamind-agi", "source_domain": "techcrunch.com", "snippet": "FutureAI today claims a breakthrough with OmegaMind, described as achieving AGI. Details remain sparse.", "date_approx": "1 hour ago"},
        {"title": "AGI Claim by Newcomer FutureAI Shakes AI World", "link": "https://www.reuters.com/technology/futureai-claims-agi-with-omegamind", "source_domain": "reuters.com", "snippet": "A startup named FutureAI has made bold claims about its OmegaMind model achieving Artificial General Intelligence.", "date_approx": "2 hours ago"},
        {"title": "OmegaMind: FutureAI's Audacious AGI Proclamation", "link": "https://www.wired.com/story/futureai-omegamind-agi-claims/", "source_domain": "wired.com", "snippet": "FutureAI's CEO Dr. Enigma presented OmegaMind as sentient AI, but experts urge caution pending peer review.", "date_approx": "30 minutes ago"},
        {"title": "FutureAI - AGI Achieved (Official Press Release)", "link": "https://futureai.example.com/press/omegamind-agi", "source_domain": "futureai.example.com", "snippet": "FutureAI is proud to announce OmegaMind, the world's first true AGI.", "date_approx": "4 hours ago"}
    ]
    
    mock_search_results_weak = [
        {"title": "OmegaMind - New AI?", "link": "https://someforum.example.net/thread123", "source_domain": "someforum.example.net", "snippet": "Heard about FutureAI and OmegaMind, anyone got info? Sounds like hype.", "date_approx": "1 day ago"},
        {"title": "My Thoughts on FutureAI's AGI claims", "link": "https://personalblog.example.org/my-agi-thoughts", "source_domain": "personalblog.example.org", "snippet": "FutureAI says they have AGI with OmegaMind. I'm not so sure, seems like a PR stunt for funding.", "date_approx": "5 hours ago"}
    ]

    logger.info(f"\n--- Testing CorroborationCognitoAgent with Strong Corroboration ---")
    result_data_strong = run_corroboration_cognito_agent(mock_pipeline_data_from_editorial_prime.copy(), mock_search_results_strong)
    
    logger.info(f"\nCorroborationCognitoAgent Status (Strong): {result_data_strong.get('corroboration_cognito_agent_status')}")
    logger.info("Full Corroboration Assessment (Strong):")
    print(json.dumps(result_data_strong.get('corroboration_assessment'), indent=2))
    assert result_data_strong.get('corroboration_cognito_agent_status') == "SUCCESS"
    assert result_data_strong.get('corroboration_assessment', {}).get('corroboration_level') == "Strongly Corroborated"
    assert len(result_data_strong.get('corroboration_assessment', {}).get('supporting_source_domains_tier1', [])) >= 3

    logger.info(f"\n--- Testing CorroborationCognitoAgent with Weak Corroboration ---")
    result_data_weak = run_corroboration_cognito_agent(mock_pipeline_data_from_editorial_prime.copy(), mock_search_results_weak)

    logger.info(f"\nCorroborationCognitoAgent Status (Weak): {result_data_weak.get('corroboration_cognito_agent_status')}")
    logger.info("Full Corroboration Assessment (Weak):")
    print(json.dumps(result_data_weak.get('corroboration_assessment'), indent=2))
    assert result_data_weak.get('corroboration_cognito_agent_status') == "SUCCESS"
    assert result_data_weak.get('corroboration_assessment', {}).get('corroboration_level') in ["Weakly Corroborated", "Isolated Claim/Uncorroborated"]


    logger.info("--- CorroborationCognitoAgent Standalone Test Complete ---")
