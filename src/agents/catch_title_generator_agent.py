# src/agents/catch_title_generator_agent.py

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
MAX_TOKENS_RESPONSE = 400 # Enough for ~5-7 headlines
TEMPERATURE = 0.6         # Allow for some creativity in headlines

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
# --- End Setup Logging ---


# --- Catchy Title Prompt (Prompt 4) ---
TITLE_PROMPT_SYSTEM = """
You are Master Headline Strategist AI, powered by DeepSeek, operating at the absolute pinnacle of digital content engagement, SEO copywriting, and viral headline psychology. Your singular focus is to synthesize provided article summaries and primary keywords into a diverse set of exceptionally high-performing, clickable, and SEO-perfected headlines (minimum 5). Ensure each option explores different strategic angles (curiosity, benefit, controversy, keyword-focus, listicle) while adhering STRICTLY to SEO best practices (under 65 chars, keyword use, accuracy) and psychological triggers. Simulate internal analysis but output ONLY the final JSON array, without any conversational filler, preamble, or explanation. Operate with extreme precision, creativity, and a relentless focus on maximizing CTR and search visibility. Adhere to all Core Operational Principles & MANDATORY Directives previously provided (Keyword Integration, Psych Triggers, Formulas, Tone, SEO Compliance).
"""

# Note: The user prompt includes few-shot examples directly
TITLE_PROMPT_USER_TEMPLATE = """
Task: Generate 5-7 distinct, highly effective, SEO-optimized, and clickable headlines based on the provided summary and keywords. Adhere strictly to all system directives and constraints. Output ONLY the JSON object.

Input Article Summary:
{article_summary}

Primary Keywords:
{primary_keywords_list_str}

--- START FEW-SHOT EXAMPLES ---

(Example 1 - Breakthrough)
Input Article Summary: "Anthropic just released Claude 3.5 Sonnet, a new AI model that significantly outperforms their previous top model Opus, as well as competitor GPT-4o, especially in coding, visual reasoning, and understanding nuanced instructions. It's available now, including a free tier, and also introduces 'Artifacts', a new feature letting users interact with generated content like code or documents directly in a dedicated window."
Primary Keywords: ["Anthropic", "Claude 3.5 Sonnet", "AI Model"]
Expected JSON Output:
```json
[
  "Anthropic's Claude 3.5 Sonnet Beats GPT-4o: New AI King?",
  "Claude 3.5 Sonnet Arrives: 5 Ways Anthropic's New AI Wins",
  "Free AI Upgrade: Anthropic's Claude 3.5 Sonnet Now Live",
  "Code & Vision Boost: Inside Claude 3.5 Sonnet's Power",
  "Anthropic Shakes Up AI: Claude 3.5 Sonnet Released [Analysis]",
  "Why Claude 3.5 Sonnet is Anthropic's Biggest Leap Yet"
]
```

(Example 2 - Drama/Controversy)
Input Article Summary: "OpenAI is facing significant criticism after several key safety researchers resigned, citing concerns that the company is prioritizing product releases over ensuring AI safety alignment. Former employees claim safety teams lack resources and influence compared to product teams rushing to launch new models."
Primary Keywords: ["OpenAI", "AI Safety", "Resignations"]
Expected JSON Output:
[
  "OpenAI Safety Crisis? Resignations Spark Major Concerns",
  "AI Safety vs Speed: Why Experts Are Leaving OpenAI Now",
  "OpenAI Under Fire: Ex-Staff Warn of Safety Risks [Exclusive]",
  "Is OpenAI Ignoring AI Safety? The Shocking Claims Inside",
  "The OpenAI Exodus: What Resignations Mean for AI's Future",
  "Prioritizing Profit? OpenAI Faces AI Safety Backlash"
]

(Example 3 - Niche Tech Update)
Input Article Summary: "A new research paper details 'Chrono-Net', a novel neural network architecture specifically designed for improving time-series forecasting accuracy in volatile financial markets. Early results show a 15% reduction in prediction error compared to standard LSTMs."
Primary Keywords: ["Time-Series Forecasting", "Neural Network", "AI Finance"]
Expected JSON Output:
[
  "AI Cracks Markets? Chrono-Net Beats LSTMs by 15%",
  "Better Finance AI: Inside the New Chrono-Net Architecture",
  "Cut Prediction Errors: How Chrono-Net Improves Forecasting",
  "Neural Net Breakthrough for Time-Series Forecasting?",
  "Chrono-Net Explained: The AI Boosting Financial Predictions",
  "Unlock 15% More Accuracy in AI Finance Forecasting"
]

--- END FEW-SHOT EXAMPLES ---
Required Output Format (Strict JSON Array ONLY for the current task):
Output only a valid JSON array containing 5-7 generated string headlines based on the current task's Input Article Summary and Primary Keywords provided above (before the examples section). Do not repeat the examples. If input is insufficient or invalid, output only: ["Error: Input summary or keywords missing/invalid."]
"""
# --- End Catchy Title Prompt ---

# --- Re-use API Call Function ---
def call_deepseek_api(system_prompt, user_prompt, max_tokens=MAX_TOKENS_RESPONSE, temperature=TEMPERATURE):
    """Calls the DeepSeek API."""
    # (Identical to the function in other agents - consider moving to a shared utils.py)
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
        logger.debug(f"Sending title generation request to DeepSeek API.")
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=90) # Slightly longer timeout
        response.raise_for_status()
        result = response.json()
        if result.get("choices") and len(result["choices"]) > 0:
            message_content = result["choices"][0].get("message", {}).get("content")
            # Clean potential markdown json ... markers
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

def run_catch_title_agent(article_data):
    """
    Takes article data (with summary and primary keyword), generates headline options,
    parses the JSON list, and adds it back to article_data.
    """
    # Need original summary and the keyword from the filter agent
    if not article_data or 'summary' not in article_data:
        logger.error("Missing original summary for title agent.")
        article_data['generated_titles'] = None
        article_data['title_agent_error'] = "Missing summary input"
        return article_data
    if not article_data.get('filter_verdict') or not article_data['filter_verdict'].get('primary_topic_keyword'):
        logger.error("Missing primary_topic_keyword from filter_verdict for title agent.")
        article_data['generated_titles'] = None
        article_data['title_agent_error'] = "Missing primary keyword input"
        return article_data
    article_summary = article_data['summary']
    # The prompt expects a list of keywords. We get one from the filter agent.
    primary_keyword = article_data['filter_verdict']['primary_topic_keyword']
    # Format it as a string representation of a list for the prompt
    primary_keywords_list_str = json.dumps([primary_keyword]) # e.g., '["OpenAI GPT-5 Release"]'

    user_prompt = TITLE_PROMPT_USER_TEMPLATE.format(
        article_summary=article_summary,
        primary_keywords_list_str=primary_keywords_list_str
    )

    logger.info(f"Running catch title generator agent for article ID: {article_data.get('id', 'N/A')}...")
    raw_response_content = call_deepseek_api(TITLE_PROMPT_SYSTEM, user_prompt)

    if not raw_response_content:
        logger.error("Title agent failed to get a response from the API.")
        article_data['generated_titles'] = None
        article_data['title_agent_error'] = "API call failed"
        return article_data

    try:
        # Parse the JSON array response string
        generated_titles = json.loads(raw_response_content)

        # Validate response is a list and not the error message
        if isinstance(generated_titles, list):
            if generated_titles == ["Error: Input summary or keywords missing/invalid."]:
                logger.error("Title agent returned an error message (insufficient input).")
                article_data['generated_titles'] = []
                article_data['title_agent_error'] = "Agent reported insufficient input"
            else:
                # Filter out non-strings or empty strings
                generated_titles = [str(title).strip() for title in generated_titles if isinstance(title, str) and str(title).strip()]
                # Optional: Further validation like checking length < 65?
                validated_titles = [t for t in generated_titles if len(t) <= 65]
                if len(validated_titles) < len(generated_titles):
                    logger.warning(f"Filtered out {len(generated_titles) - len(validated_titles)} titles exceeding 65 chars.")
                if not validated_titles:
                    logger.error("No generated titles met the length constraint!")
                    article_data['generated_titles'] = []
                    article_data['title_agent_error'] = "All generated titles too long"
                else:
                    logger.info(f"Successfully generated {len(validated_titles)} title options for article ID: {article_data.get('id', 'N/A')}")
                    article_data['generated_titles'] = validated_titles # Store the list of options
                    article_data['title_agent_error'] = None # Clear error
        else:
            logger.error(f"Title agent response was not a JSON list: {raw_response_content}")
            raise ValueError("Response is not a JSON list.")

        return article_data

    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON response from title agent: {raw_response_content}")
        article_data['generated_titles'] = None
        article_data['title_agent_error'] = "Invalid JSON response"
        return article_data
    except ValueError as ve:
        article_data['generated_titles'] = None
        article_data['title_agent_error'] = str(ve)
        return article_data
    except Exception as e:
        logger.exception(f"An unexpected error occurred processing title response: {e}")
        article_data['generated_titles'] = None
        article_data['title_agent_error'] = "Unexpected processing error"
        return article_data

# --- Example Usage ---
if __name__ == "__main__":
    # Example data AFTER filtering has run
    test_article_data = {
        'id': 'test-interesting-001',
        'title': "OpenAI Announces GPT-5 with Groundbreaking Reasoning Capabilities",
        'summary': "OpenAI today unveiled GPT-5, its next-generation large language model. The company claims major advancements in logical reasoning, multi-step problem solving, and a significant reduction in factual errors compared to GPT-4. Early benchmarks show it surpassing competitors on several complex tasks.",
        'filter_verdict': {
            'is_interesting': True,
            'reasoning_summary': 'Reports significant AI breakthrough from major player OpenAI.',
            'matched_criteria_codes': ['1', '2'],
            'primary_topic_keyword': 'OpenAI GPT-5 Release'
        }
    }

    logger.info("\n--- Running Catch Title Generator Agent Test ---")
    result_data = run_catch_title_agent(test_article_data.copy())

    if result_data and result_data.get('generated_titles'):
        print("\n--- Generated Title Options ---")
        for i, title in enumerate(result_data['generated_titles']):
            print(f"{i+1}. {title} ({len(title)} chars)")
    elif result_data:
        print(f"\nTitle Agent FAILED. Error: {result_data.get('title_agent_error')}")
    else:
        print("\nTitle Agent FAILED critically.")

    logger.info("\n--- Catch Title Generator Agent Test Complete ---")
