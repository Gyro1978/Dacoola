# src/agents/tags_generator_agent.py

import os
import requests
import json
import logging
from dotenv import load_dotenv
from datetime import datetime, timezone

# --- Load Environment Variables ---
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '..', '.env'))
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"

# --- Configuration ---
AGENT_MODEL = "deepseek-chat"
MAX_TOKENS_RESPONSE = 150 # Shorter response for just tags
TEMPERATURE = 0.2         # Relatively deterministic for tag generation

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
# --- End Setup Logging ---


# --- Tags Generator Prompt (Prompt 3) ---
TAGS_PROMPT_SYSTEM = """
You are an expert AI SEO Analyst and Taxonomist, powered by DeepSeek. Your core function is to meticulously analyze the provided article text to identify the most salient entities, concepts, themes, and related topics that are highly relevant for search engine optimization (SEO) and content discovery. You must distill the essence of the article into a concise list of 5-10 SEO-appropriate tags. Your output must be strictly a valid JSON array of strings, containing NO other text, explanations, or formatting.
"""

TAGS_PROMPT_USER_TEMPLATE = """
Task: Read the following article text thoroughly. Generate a list of 5-10 highly relevant SEO tags (related topics) that accurately represent the main subjects and key themes discussed.

Internal Analysis Process (Simulated):
1. Identify Core Subject(s).
2. Extract Key Entities (Companies, Products, People, Tech).
3. Determine Underlying Themes (Ethics, Competition, Impact, Trends).
4. Select 5-10 SEO-Relevant Tags: Specific, descriptive, include key entities/concepts, reflect core themes, user search intent. Avoid generics unless essential.

Input Article Text:
{full_article_text}

Required Output Format (Strict JSON Array ONLY):
Output only a valid JSON array containing 5-10 generated string tags. Do not include any text before or after the JSON array.
Example: ["AI Model Release", "OpenAI", "GPT-5 Speculation", "Large Language Models", "AI Safety Concerns"]

(Error Handling): If the input text is clearly insufficient (e.g., less than ~50 words), output only the following exact JSON array: ["Error: Input text missing or insufficient"]
"""
# --- End Tags Generator Prompt ---

# --- Re-use API Call Function ---
# (Assume call_deepseek_api is defined similarly to other agents or imported)
def call_deepseek_api(system_prompt, user_prompt, max_tokens=MAX_TOKENS_RESPONSE, temperature=TEMPERATURE):
    """Calls the DeepSeek API."""
    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY not found.")
        return None
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
    payload = {
        "model": AGENT_MODEL,
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False
    }
    try:
        logger.debug(f"Sending tags generation request to DeepSeek API.")
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()
        if result.get("choices") and len(result["choices"]) > 0:
            message_content = result["choices"][0].get("message", {}).get("content")
            # Clean potential markdown ```json ... ``` markers
            if message_content and message_content.strip().startswith("```json"):
                message_content = message_content.strip()[7:-3].strip()
            elif message_content and message_content.strip().startswith("```"):
                 message_content = message_content.strip()[3:-3].strip()
            return message_content.strip() if message_content else None
        else:
            logger.error(f"API response did not contain expected 'choices' structure: {result}")
            return None
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed: {e}")
        return None
    except Exception as e:
        logger.exception(f"An unexpected error occurred during API call: {e}")
        return None
# --- End API Call ---


def run_tags_generator_agent(article_data):
    """
    Takes article data (containing the generated markdown body), runs the tags agent,
    parses the JSON list, and adds it back to article_data.
    """
    if not article_data or not article_data.get('seo_agent_results') or not article_data['seo_agent_results'].get('generated_article_body_md'):
        logger.error("Missing generated article body markdown needed for tags agent.")
        article_data['generated_tags'] = None
        article_data['tags_agent_error'] = "Missing article body input"
        return article_data

    article_body_md = article_data['seo_agent_results']['generated_article_body_md']

    # Basic check for sufficient content length
    if len(article_body_md) < 50: # Check against a minimum length
         logger.warning(f"Article body seems too short ({len(article_body_md)} chars) for meaningful tag generation. Skipping tags agent.")
         article_data['generated_tags'] = [] # Empty list for insufficient content
         article_data['tags_agent_error'] = "Input text too short"
         return article_data

    user_prompt = TAGS_PROMPT_USER_TEMPLATE.format(full_article_text=article_body_md)

    logger.info(f"Running tags generator agent for article ID: {article_data.get('id', 'N/A')}...")
    raw_response_content = call_deepseek_api(TAGS_PROMPT_SYSTEM, user_prompt)

    if not raw_response_content:
        logger.error("Tags agent failed to get a response from the API.")
        article_data['generated_tags'] = None
        article_data['tags_agent_error'] = "API call failed"
        return article_data

    try:
        # Parse the JSON array response string
        generated_tags = json.loads(raw_response_content)

        # Validate response is a list and not the error message
        if isinstance(generated_tags, list):
             if generated_tags == ["Error: Input text missing or insufficient"]:
                  logger.error("Tags agent returned an error message (insufficient input).")
                  article_data['generated_tags'] = []
                  article_data['tags_agent_error'] = "Agent reported insufficient input"
             else:
                  # Optional: Filter out empty strings if the API sometimes adds them
                  generated_tags = [tag for tag in generated_tags if isinstance(tag, str) and tag.strip()]
                  logger.info(f"Successfully generated {len(generated_tags)} tags for article ID: {article_data.get('id', 'N/A')}")
                  article_data['generated_tags'] = generated_tags
                  article_data['tags_agent_error'] = None # Clear previous error
        else:
             logger.error(f"Tags agent response was not a JSON list: {raw_response_content}")
             raise ValueError("Response is not a JSON list.")

        return article_data

    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON response from tags agent: {raw_response_content}")
        article_data['generated_tags'] = None
        article_data['tags_agent_error'] = "Invalid JSON response"
        return article_data
    except ValueError as ve:
         article_data['generated_tags'] = None
         article_data['tags_agent_error'] = str(ve)
         return article_data
    except Exception as e:
        logger.exception(f"An unexpected error occurred processing tags response: {e}")
        article_data['generated_tags'] = None
        article_data['tags_agent_error'] = "Unexpected processing error"
        return article_data

# --- Example Usage ---
if __name__ == "__main__":
    # Example data AFTER SEO agent has run
    test_article_data = {
        'id': 'test-interesting-001',
        # ... other fields ...
        'seo_agent_results': {
            'generated_title_tag': 'OpenAI GPT-5 Release: Groundbreaking AI Reasoning Here',
            'generated_meta_description': 'Explore the OpenAI GPT-5 release, featuring major leaps in AI reasoning and problem-solving capabilities compared to previous models.',
            'generated_article_body_md': """## OpenAI Unveils GPT-5 Model

OpenAI today announced the much-anticipated OpenAI GPT-5 release, its next-generation large language model. The company highlights significant progress in logical reasoning and complex problem-solving abilities.

Early benchmarks indicate GPT-5 surpasses existing models, including its predecessor GPT-4, on various demanding tasks. This represents a major step forward in artificial intelligence capabilities. Further details on availability are expected soon.
""", # Note: Added keyword 'OpenAI GPT-5 Release' here
            'generated_json_ld': '<script type="application/ld+json">...</script>'
        }
    }

    logger.info("\n--- Running Tags Generator Agent Test ---")
    result_data = run_tags_generator_agent(test_article_data.copy())

    if result_data and result_data.get('generated_tags') is not None:
        print("\n--- Generated Tags ---")
        print(result_data.get('generated_tags'))
        # Example Assertion: assert isinstance(result_data.get('generated_tags'), list)
    elif result_data:
         print(f"\nTags Agent FAILED. Error: {result_data.get('tags_agent_error')}")
    else:
         print("\nTags Agent FAILED critically.")


    logger.info("\n--- Tags Generator Agent Test Complete ---")