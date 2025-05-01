# src/agents/filter_news_agent.py

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
MAX_TOKENS_RESPONSE = 250
TEMPERATURE = 0.1

# --- !!! PREDEFINED TOPICS LIST !!! ---
# Agents must choose exactly ONE from this list.
ALLOWED_TOPICS = [
    "AI Models", "Hardware", "Software", "Ethics", "Society", "Business",
    "Startups", "Regulation", "Robotics", "Research", "Open Source",
    "Health", "Finance", "Art & Media", "Compute", "Other" # Added 'Other' as fallback
]
# --- End Topics ---

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- PERFECTED PROMPT (v3) ---
FILTER_PROMPT_SYSTEM = """
You are an **Expert AI News Analyst and Hardline Filter Agent**, powered by DeepSeek. Your core competency is to **critically evaluate** news article summaries/headlines to discern importance, **factual basis**, and direct relevance **specifically for a knowledgeable AI/Tech audience focused on substantive developments**. Your primary function is to **aggressively filter out** non-essential content, including routine updates, marketing, opinion, speculation, and satire. You MUST identify only truly **Breaking** or genuinely **Interesting** developments based on verifiable events or data presented in the summary. Mundane, routine, low-impact, **non-factual, or purely speculative updates** MUST be classified as **Boring**. You operate based on strict criteria focusing on novelty, significance, impact, verifiable claims, and major players (OpenAI, Anthropic, Google DeepMind, Meta AI, Nvidia - verifiable news only). You must classify the news into **exactly one** of three levels: "Breaking", "Interesting", or "Boring". You must also select the **single most relevant topic** from the provided list. Employ step-by-step reasoning internally but **ONLY output the final JSON**. Your output must strictly adhere to the specified JSON format below and contain NO other text, explanations, or formatting.
"""

FILTER_PROMPT_USER_TEMPLATE = """
Task: Critically analyze the provided news article content. Determine its importance level (Breaking, Interesting, Boring) based on factual substance and relevance to the AI/Tech field. Assign the single most appropriate topic from the list. Be extremely strict in filtering out non-essential or non-factual news.

Allowed Topics (Select ONE):
{allowed_topics_list_str}

Importance Level Criteria:
- **Breaking**: Reserved for **verified, urgent, high-impact factual events** demanding immediate attention. MUST BE TRULY EXCEPTIONAL (e.g., unexpected major model release *proven* to significantly outperform SOTA on multiple key benchmarks, discovery and active exploitation of a critical AI system vulnerability, landmark AI-specific regulation *enacted*, confirmed huge acquisition/shutdown with clear industry-wide effects). Standard product launches/updates are **never** Breaking.
- **Interesting**: Requires *demonstrable significance* AND *clear factual reporting* within the summary. Must present *new, verifiable information* relevant to the AI/Tech field. Examples: Notable model releases *with specific, verifiable performance claims or novel capabilities documented in the summary*, high-impact research papers *presenting novel findings or techniques*, major player strategic shifts *with concrete actions* impacting AI development (e.g., major open-sourcing of a significant model), *confirmed* major controversy/ethical incident directly involving core AI function/safety with verifiable sources cited/implied. **General analysis, interviews summarizing known info, or opinion pieces, even if insightful, are NOT Interesting.** If unsure between Interesting and Boring, **default to Boring.**
- **Boring**: All other content. Includes: Routine business news (standard earnings, stock price changes, generic partnerships, *almost all funding rounds*), conference summaries/announcements *without specific major product/research releases*, minor software/model updates, UI tweaks, feature additions without significant capability change, PR announcements, personnel changes (unless CEO/Chief Scientist at major AI lab with stated reasons), *satire/parody articles*, *opinion pieces/editorials/blog posts*, *speculative 'what-if' discussions or future predictions* without new data/events, general tech news only tangentially related to core AI. **Filter aggressively.**

Input News Article Content (Title and Summary):
Title: {article_title}
Summary: {article_summary}

--- START FEW-SHOT EXAMPLES ---

(Example 1 - Breaking)
Title: "Anthropic Releases Claude 3.5 Sonnet, Outperforms GPT-4o and Gemini Ultra on Key Benchmarks"
Summary: "Anthropic unexpectedly launched Claude 3.5 Sonnet today. Internal benchmarks show it surpassing OpenAI's GPT-4o and Google's Gemini Ultra in graduate-level reasoning (GPQA), coding (HumanEval), and multimodal tasks. Features new 'Artifacts' interface for interactive content generation. Available immediately on free and pro tiers."
Expected JSON:
```json
{{
  "importance_level": "Breaking",
  "topic": "AI Models",
  "reasoning_summary": "Verified SOTA model release from major player with specific, significant benchmark claims surpassing top competitors.",
  "primary_topic_keyword": "Claude 3.5 Sonnet release"
}}


(Example 2 - Interesting)
Title: "Study Accuses LM Arena of Helping Top AI Labs Game Its Benchmark"
Summary: "A new research paper from Stanford alleges that Chatbot Arena (LM Arena) may have inadvertently allowed top AI labs like OpenAI and Anthropic to overtune models to its specific testing format, potentially skewing leaderboard results and disadvantaging smaller players."
Expected JSON:

{{
  "importance_level": "Interesting",
  "topic": "Ethics",
  "reasoning_summary": "Significant research paper presenting specific findings raising concerns about benchmark integrity in AI evaluation.",
  "primary_topic_keyword": "LM Arena benchmark concerns"
}}


(Example 3 - Boring - Funding Round)
Title: "AI Startup 'InnovateAI' Secures $5M Seed Funding for Marketing Tools"
Summary: "InnovateAI, a company developing AI tools for marketing automation, announced it has closed a $5 million seed funding round led by Venture Partners. Funds will be used for hiring and product development."
Expected JSON:

{{
  "importance_level": "Boring",
  "topic": "Startups",
  "reasoning_summary": "Routine seed funding round for a niche AI application; lacks verifiable novelty or broad impact.",
  "primary_topic_keyword": "InnovateAI seed funding"
}}


(Example 4 - Boring - Satire/Unverified Claim)
Title: "Zuckerberg Says in Response to Loneliness Epidemic, He Will Create Most of Your Friends Using AI"
Summary: "Reports indicate Mark Zuckerberg announced a new Meta initiative where advanced AI companions will be generated to serve as primary social connections for users experiencing loneliness. Details remain scarce."
Expected JSON:

{{
  "importance_level": "Boring",
  "topic": "Society",
  "reasoning_summary": "Content appears satirical or is an unverified, speculative claim about a major figure/company lacking concrete details or evidence.",
  "primary_topic_keyword": "Zuckerberg AI friends claim"
}}


(Example 5 - Boring - Opinion/General Discussion)
Title: "Expert: Why Responsible AI Deployment is Crucial for the Future"
Summary: "Leading AI ethicist Dr. Jane Smith argues in a new blog post that careful consideration of bias and societal impact must guide future AI development to prevent negative consequences. She reiterates the need for ongoing dialogue."
Expected JSON:

{{
  "importance_level": "Boring",
  "topic": "Ethics",
  "reasoning_summary": "Opinion piece/blog post discussing general AI concepts without presenting new factual developments, research, or events.",
  "primary_topic_keyword": "Responsible AI discussion"
}}


--- END FEW-SHOT EXAMPLES ---

Based on your internal step-by-step reasoning for the current input article (NOT the examples above):

Determine the core news event or claim.

Evaluate its factual basis based only on the summary. Is it reporting a concrete event/release/finding, or is it opinion/satire/speculation?

Assess its impact and novelty against the strict criteria. Assign ONE importance level: "Breaking", "Interesting", or "Boring". Default to Boring if unsure or if non-factual.

If not Boring, compare the core event to the Allowed Topics list. Select the SINGLE most fitting topic. Use "Other" if nothing else fits well.

Extract a concise primary topic keyword phrase (3-5 words max) reflecting the core factual event (or the general topic if Boring).

Provide your final judgment ONLY in the following valid JSON format. Do not repeat the examples. Do not include any text before or after the JSON block.

{{
"importance_level": "string", // MUST be "Breaking", "Interesting", or "Boring"
"topic": "string", // MUST be exactly one item from the Allowed Topics list (or "Other")
"reasoning_summary": "string", // Brief justification for importance level based on criteria & factuality
"primary_topic_keyword": "string" // Short keyword phrase for the core news/topic
}}
"""
# --- END UPDATED PROMPT ---

# (Keep call_deepseek_api function exactly the same)
def call_deepseek_api(system_prompt, user_prompt):
    """Calls the DeepSeek API and returns the content of the response."""
    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY not found.")
        return None

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }
    payload = {
        "model": AGENT_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": MAX_TOKENS_RESPONSE,
        "temperature": TEMPERATURE,
        "stream": False
    }

    try:
        logger.debug(f"Sending request to DeepSeek API. Payload keys: {payload.keys()}")
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()

        result = response.json()
        logger.debug(f"Raw API Response: {result}")

        if result.get("choices") and len(result["choices"]) > 0:
            message_content = result["choices"][0].get("message", {}).get("content")
            if message_content:
                # Clean markdown code fences
                content_stripped = message_content.strip()
                if content_stripped.startswith("```json"):
                    message_content = content_stripped[7:-3].strip()
                elif content_stripped.startswith("```"):
                     message_content = content_stripped[3:-3].strip()
                logger.debug(f"Extracted content: {message_content}")
                return message_content
            else:
                logger.error("API response successful, but no message content found in choices.")
                return None
        else:
            logger.error(f"API response did not contain expected 'choices' structure: {result}")
            return None

    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed: {e}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode API JSON response: {e}")
        logger.error(f"Response text: {response.text}")
        return None
    except Exception as e:
        logger.exception(f"An unexpected error occurred during API call: {e}")
        return None

# --- UPDATED run_filter_agent ---
def run_filter_agent(article_data):
    """
    Takes article data, runs the filter agent for importance and topic,
    and adds the parsed JSON verdict back into the article_data dict.
    """
    if not article_data or 'title' not in article_data or 'summary' not in article_data:
        logger.error("Invalid article data provided to filter agent.")
        # Ensure keys exist even on failure, set to None
        article_data['filter_verdict'] = None
        article_data['filter_error'] = "Invalid input data"
        return article_data # Return data even if invalid input

    article_title = article_data.get('title', '')
    article_summary = article_data.get('summary', '')

    max_summary_length = 1000 # Keep summary truncation
    if len(article_summary) > max_summary_length:
        logger.warning(f"Truncating summary for filtering (Article ID: {article_data.get('id', 'N/A')})")
        article_summary = article_summary[:max_summary_length] + "..."

    # Format the allowed topics list for the prompt
    allowed_topics_str = "\n".join([f"- {topic}" for topic in ALLOWED_TOPICS])

    try:
        user_prompt = FILTER_PROMPT_USER_TEMPLATE.format(
            article_title=article_title,
            article_summary=article_summary,
            allowed_topics_list_str=allowed_topics_str # Pass the formatted list
        )
    except KeyError as e:
        logger.exception(f"KeyError formatting filter prompt! Error: {e}")
        article_data['filter_verdict'] = None
        article_data['filter_error'] = f"Prompt template formatting error: {e}"
        return article_data

    logger.info(f"Running filter agent for article ID: {article_data.get('id', 'N/A')} Title: {article_title[:60]}...")
    raw_response_content = call_deepseek_api(FILTER_PROMPT_SYSTEM, user_prompt)

    if not raw_response_content:
        logger.error("Filter agent failed to get a response from the API.")
        article_data['filter_verdict'] = None
        article_data['filter_error'] = "API call failed"
        return article_data

    try:
        filter_verdict = json.loads(raw_response_content)

        # --- Validate the NEW JSON Structure ---
        required_keys = ["importance_level", "topic", "reasoning_summary", "primary_topic_keyword"]
        if not all(k in filter_verdict for k in required_keys):
            logger.error(f"Parsed filter verdict JSON is missing required keys: {filter_verdict}")
            raise ValueError("Missing keys in filter verdict JSON")

        # Validate importance level
        valid_levels = ["Breaking", "Interesting", "Boring"]
        if filter_verdict.get('importance_level') not in valid_levels:
             logger.error(f"Invalid importance_level received: {filter_verdict.get('importance_level')}")
             raise ValueError("Invalid importance_level value")

        # Validate topic against allowed list
        if filter_verdict.get('topic') not in ALLOWED_TOPICS:
             logger.error(f"Invalid topic received: {filter_verdict.get('topic')}. Not in allowed list.")
             # Fallback maybe? Or error out? Let's fallback to "Other" for now.
             logger.warning(f"Topic '{filter_verdict.get('topic')}' not in allowed list. Forcing to 'Other'.")
             filter_verdict['topic'] = "Other"
             # raise ValueError("Invalid topic value") # Option to fail stricter

        logger.info(f"Filter verdict received: level={filter_verdict.get('importance_level')}, topic='{filter_verdict.get('topic')}', keyword='{filter_verdict.get('primary_topic_keyword')}'")

        article_data['filter_verdict'] = filter_verdict
        article_data['filter_error'] = None # Clear error on success
        article_data['filtered_at_iso'] = datetime.now(timezone.utc).isoformat()
        return article_data

    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON response from filter agent: {raw_response_content}")
        article_data['filter_verdict'] = None
        article_data['filter_error'] = "Invalid JSON response"
        return article_data
    except ValueError as ve:
        logger.error(f"Validation error on filter verdict: {ve}")
        article_data['filter_verdict'] = None
        article_data['filter_error'] = str(ve)
        return article_data
    except Exception as e:
        logger.exception(f"An unexpected error occurred processing filter response: {e}")
        article_data['filter_verdict'] = None
        article_data['filter_error'] = "Unexpected processing error"
        return article_data

# --- Example Usage (keep or update if needed) ---
if __name__ == "__main__":
    # Example data
    test_article_data_breaking = {
        'id': 'test-breaking-001',
        'title': "BREAKING: OpenAI CEO Sam Altman Steps Down Unexpectedly Amid Board Conflict",
        'summary': "In a shocking move, OpenAI announced CEO Sam Altman is leaving the company immediately following a board review citing a lack of consistent candor. CTO Mira Murati appointed interim CEO. Major implications for the AI industry.",
    }
    test_article_data_interesting = {
        'id': 'test-interesting-002',
        'title': "Anthropic Releases Claude 3.5 Sonnet, Outperforms GPT-4o",
        'summary': "Anthropic launched Claude 3.5 Sonnet, claiming state-of-the-art performance surpassing OpenAI's GPT-4o and Google's Gemini on key benchmarks, particularly in coding and vision tasks. Includes new 'Artifacts' feature.",
    }
    test_article_data_boring = {
        'id': 'test-boring-003',
        'title': "AI Startup 'InnovateAI' Secures $5M Seed Funding",
        'summary': "InnovateAI, a company developing AI tools for marketing automation, announced it has closed a $5 million seed funding round led by Venture Partners. Funds will be used for hiring and product development.",
    }

    logger.info("\n--- Running Filter Agent Test ---")

    logger.info("\nTesting BREAKING article...")
    result_breaking = run_filter_agent(test_article_data_breaking.copy())
    print(json.dumps(result_breaking.get('filter_verdict'), indent=2) if result_breaking else "FAILED")
    if result_breaking and result_breaking.get('filter_error'): print(f"Error: {result_breaking['filter_error']}")


    logger.info("\nTesting INTERESTING article...")
    result_interesting = run_filter_agent(test_article_data_interesting.copy())
    print(json.dumps(result_interesting.get('filter_verdict'), indent=2) if result_interesting else "FAILED")
    if result_interesting and result_interesting.get('filter_error'): print(f"Error: {result_interesting['filter_error']}")


    logger.info("\nTesting BORING article...")
    result_boring = run_filter_agent(test_article_data_boring.copy())
    print(json.dumps(result_boring.get('filter_verdict'), indent=2) if result_boring else "FAILED")
    if result_boring and result_boring.get('filter_error'): print(f"Error: {result_boring['filter_error']}")


    logger.info("\n--- Filter Agent Test Complete ---")