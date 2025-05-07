# src/agents/tags_generator_agent.py

import os
import sys
import requests
import json
import logging
from dotenv import load_dotenv
# from datetime import datetime, timezone # Not directly used here

# --- Path Setup (Ensure src is in path if run standalone) ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
# --- End Path Setup ---

# --- Setup Logging ---
logger = logging.getLogger(__name__)
if not logging.getLogger().hasHandlers():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# --- Load Environment Variables ---
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"

# --- Configuration ---
AGENT_MODEL = "deepseek-chat"
MAX_TOKENS_RESPONSE = 200 # Increased slightly for potentially more tags or longer phrases
TEMPERATURE = 0.25        # Kept relatively low for focus, slight increase for variety
API_TIMEOUT_SECONDS = 75  # Slightly increased timeout

# --- Tags Generator Prompt ---
TAGS_PROMPT_SYSTEM = """
You are an **Ultimate SEO Tagging Specialist and AI Content Analyzer**, powered by DeepSeek. Your primary function is to meticulously dissect the provided article text, its primary keyword, and its assigned topic to generate a highly relevant, diverse, and SEO-optimized set of 7-10 tags. These tags must capture the core essence, key entities, critical concepts, and significant themes for maximum content discoverability and search engine ranking. Your output MUST be strictly a valid JSON array of strings, with NO other text, explanations, or formatting.
"""

TAGS_PROMPT_USER_TEMPLATE = """
Task: Analyze the following article content, its primary identified keyword, and its assigned topic. Generate a list of 7-10 highly relevant, SEO-optimized tags.

**Input Context:**
1.  **Primary Keyword for this Article:** {primary_keyword}
2.  **Assigned Topic for this Article:** {assigned_topic}
3.  **Full Article Text/Content:**
    {full_article_text}

**Tag Generation Guidelines (Strict Adherence Required):**
1.  **Relevance is Paramount:** All tags must be directly and strongly relevant to the provided article content.
2.  **Incorporate Primary Keyword:** At least one tag should closely relate to or include the `Primary Keyword`.
3.  **Leverage Assigned Topic:** Consider the `Assigned Topic` to guide the thematic relevance of some tags.
4.  **Mix of Specificity:**
    *   **Entities:** Include key named entities (companies, products, people, technologies, organizations) mentioned if they are central to the article.
    *   **Concepts/Themes:** Generate tags that capture the core concepts, underlying themes (e.g., "AI Ethics in Healthcare", "Machine Learning Applications", "Quantum Computing Breakthroughs"), and the "user intent" behind searches for this content.
    *   **Long-Tail Potential:** Where appropriate, use 2-4 word phrases that reflect specific search queries (e.g., "future of AI in robotics", "large language model training techniques").
5.  **Avoid Over-Generality:** Only use very broad tags (e.g., "Artificial Intelligence", "Technology") if the article itself is extremely broad and such a tag is truly essential for context. Prefer more granular tags.
6.  **Optimal Number:** Aim for a final list of 7-10 high-quality tags.
7.  **Format:** Tags should be strings. Capitalize appropriately (e.g., proper nouns, acronyms).

**Example of Good Tags for an Article about a new AI model for coding:**
Primary Keyword: "AI coding assistant"
Assigned Topic: "AI Models"
Generated Tags: ["AI Coding Assistant", "Generative AI for Code", "OpenAI Codex Update", "Software Development Automation", "Large Language Models in Programming", "Developer Productivity Tools", "Future of Software Engineering", "AI Code Generation"]

**Required Output Format (Strict JSON Array ONLY):**
Output ONLY a valid JSON array containing 7-10 generated string tags. Do not include any text before or after the JSON array.
Example: ["AI Model Release", "OpenAI", "GPT-5 Speculation", "Large Language Models", "AI Safety Concerns", "AI Ethics", "Tech Industry Trends"]

(Error Handling): If the input text is clearly insufficient (e.g., less than ~75 words), output only the following exact JSON array: ["Error: Input text missing or insufficient"]
"""

# --- API Call Function (remains the same) ---
def call_deepseek_api(system_prompt, user_prompt, max_tokens=MAX_TOKENS_RESPONSE, temperature=TEMPERATURE):
    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY environment variable not set.")
        return None
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Accept": "application/json"
        }
    payload = {
        "model": AGENT_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
            ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False
    }
    try:
        logger.debug(f"Sending tags generation request (model: {AGENT_MODEL}).")
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=API_TIMEOUT_SECONDS)
        response.raise_for_status()
        result = response.json()
        logger.debug("Raw API Response received (Tags Agent).")

        if result.get("choices") and len(result["choices"]) > 0:
            message_content = result["choices"][0].get("message", {}).get("content")
            if message_content:
                content_stripped = message_content.strip()
                if content_stripped.startswith("```json"):
                    message_content = content_stripped[7:-3].strip()
                elif content_stripped.startswith("```"):
                    message_content = content_stripped[3:-3].strip()
                return message_content.strip()
            else:
                logger.error("API response successful, but no message content found.")
                return None
        else:
            logger.error(f"API response missing 'choices' or choices empty: {result}")
            return None
    except requests.exceptions.Timeout:
         logger.error(f"API request timed out after {API_TIMEOUT_SECONDS} seconds.")
         return None
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed: {e}")
        return None
    except json.JSONDecodeError as e:
        response_text = response.text if response else "N/A"
        logger.error(f"Failed to decode API JSON response: {e}. Response text: {response_text[:500]}...")
        return None
    except Exception as e:
        logger.exception(f"An unexpected error occurred during API call: {e}")
        return None

# --- Main Agent Function ---
def run_tags_generator_agent(article_data):
    article_id = article_data.get('id', 'N/A')

    if not isinstance(article_data, dict):
         logger.error(f"Invalid input: article_data is not a dictionary for ID {article_id}.")
         return article_data

    seo_results = article_data.get('seo_agent_results')
    article_body_md = seo_results.get('generated_article_body_md') if isinstance(seo_results, dict) else None
    
    # Get primary keyword and topic from filter_verdict
    filter_verdict = article_data.get('filter_verdict', {})
    primary_keyword = filter_verdict.get('primary_topic_keyword', 'General AI News') # Fallback
    assigned_topic = filter_verdict.get('topic', 'Other') # Fallback

    if not article_body_md:
        error_msg = "Missing 'generated_article_body_md' for tags agent."
        logger.error(f"{error_msg} (ID: {article_id})")
        article_data['generated_tags'] = []
        article_data['tags_agent_error'] = error_msg
        return article_data

    min_body_length = 75 # Slightly increased min length for better tag generation
    if len(article_body_md) < min_body_length:
         warning_msg = f"Article body too short ({len(article_body_md)} < {min_body_length} chars) for meaningful tag generation. Skipping tags agent."
         logger.warning(f"{warning_msg} (ID: {article_id})")
         article_data['generated_tags'] = []
         article_data['tags_agent_error'] = "Input text too short"
         return article_data

    try:
        user_prompt = TAGS_PROMPT_USER_TEMPLATE.format(
            full_article_text=article_body_md,
            primary_keyword=primary_keyword,
            assigned_topic=assigned_topic
        )
    except KeyError as e:
        logger.exception(f"KeyError formatting tags prompt template for ID {article_id}! Error: {e}")
        article_data['generated_tags'] = None
        article_data['tags_agent_error'] = f"Prompt template formatting error: {e}"
        return article_data

    logger.info(f"Running tags generator agent for article ID: {article_id} (Primary Keyword: '{primary_keyword}', Topic: '{assigned_topic}')...")
    raw_response_content = call_deepseek_api(TAGS_PROMPT_SYSTEM, user_prompt)

    if not raw_response_content:
        logger.error(f"Tags agent failed to get a response from the API for ID: {article_id}.")
        article_data['generated_tags'] = None
        article_data['tags_agent_error'] = "API call failed or returned empty"
        return article_data

    try:
        generated_tags = json.loads(raw_response_content)
        if isinstance(generated_tags, list):
             if generated_tags == ["Error: Input text missing or insufficient"]:
                  logger.error(f"Tags agent returned error message (insufficient input) for ID: {article_id}.")
                  article_data['generated_tags'] = []
                  article_data['tags_agent_error'] = "Agent reported insufficient input"
             else:
                  cleaned_tags = [str(tag).strip() for tag in generated_tags if isinstance(tag, str) and str(tag).strip()]
                  # Optional: Ensure primary keyword or a close variant is in the tags if LLM missed it
                  primary_kw_lower = primary_keyword.lower()
                  if not any(primary_kw_lower in tag.lower() for tag in cleaned_tags):
                      cleaned_tags.insert(0, primary_keyword) # Add it to the beginning
                      logger.info(f"Added primary keyword '{primary_keyword}' to tags as it was missing. ID: {article_id}")
                  
                  # Limit to a reasonable number, e.g., top 10, if LLM gives too many
                  final_tags = cleaned_tags[:10]

                  logger.info(f"Successfully generated {len(final_tags)} tags for article ID: {article_id}")
                  article_data['generated_tags'] = final_tags
                  article_data['tags_agent_error'] = None
        else:
             logger.error(f"Tags agent response was not a JSON list for ID {article_id}: {raw_response_content}")
             raise ValueError("Response is not a JSON list.")
        return article_data

    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON response from tags agent for ID {article_id}: {raw_response_content}")
        article_data['generated_tags'] = None
        article_data['tags_agent_error'] = "Invalid JSON response from API"
        return article_data
    except ValueError as ve:
         logger.error(f"Validation error on tags response for ID {article_id}: {ve}")
         article_data['generated_tags'] = None
         article_data['tags_agent_error'] = str(ve)
         return article_data
    except Exception as e:
        logger.exception(f"An unexpected error occurred processing tags response for ID {article_id}: {e}")
        article_data['generated_tags'] = None
        article_data['tags_agent_error'] = "Unexpected processing error"
        return article_data

# --- Standalone Execution (for testing) ---
if __name__ == "__main__":
    logging.getLogger().setLevel(logging.DEBUG)
    logger.setLevel(logging.DEBUG)

    test_article_data_good = {
        'id': 'test-tags-good-001',
        'filter_verdict': { # Added filter_verdict for testing context
            'primary_topic_keyword': 'AI Model Release',
            'topic': 'AI Models'
        },
        'seo_agent_results': {
            'generated_article_body_md': """## OpenAI Unveils GPT-5 Model with Advanced Reasoning

OpenAI today announced the much-anticipated **OpenAI GPT-5 release**, its next-generation large language model. The company highlights significant progress in logical reasoning and complex problem-solving abilities compared to GPT-4. This new model integrates novel attention mechanisms and has been trained on an even larger and more diverse dataset, including specialized code repositories and scientific papers.

Early benchmarks shared internally indicate GPT-5 surpasses existing models, including Google's Gemini and Anthropic's Claude 3, on various demanding tasks like advanced mathematics and scientific literature analysis. This represents a major step forward in artificial intelligence capabilities, potentially impacting fields from software development to drug discovery and even creative content generation.

Further details on public availability, API access, and pricing are expected in the coming weeks. Concerns about AI safety and potential misuse were briefly addressed, with OpenAI stating enhanced safety protocols, developed in collaboration with external ethics boards, are built into the model's architecture. The focus remains on responsible deployment and mitigating potential societal harms.
""",
        }
    }
    # ... (other test cases can be updated similarly) ...

    logger.info("\n--- Running Tags Generator Agent Standalone Test (Perfected) ---")

    logger.info("\nTesting GOOD article body with context...")
    result_good = run_tags_generator_agent(test_article_data_good.copy())
    print("Result (Good with context):", json.dumps(result_good.get('generated_tags', 'ERROR'), indent=2))
    if result_good.get('tags_agent_error'): print(f"Error: {result_good['tags_agent_error']}")

    # ... (other test prints) ...

    logger.info("\n--- Tags Generator Agent Standalone Test Complete ---")