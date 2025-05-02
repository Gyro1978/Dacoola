# src/agents/filter_news_agent.py
import os
import requests
import json
import logging
from dotenv import load_dotenv
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

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

# --- REFINED PROMPT (v4) ---
FILTER_PROMPT_SYSTEM = """
You are an **Expert News Analyst and Content Curator AI**, powered by DeepSeek. Your core competency is to **critically evaluate** news article summaries/headlines to discern importance, **factual basis**, and direct relevance for an audience interested in **substantive AI, Technology, and major related industry/world news**. Your primary function is to **aggressively filter out** non-essential content (routine updates, marketing, basic financial reports, opinion, speculation, satire). You MUST identify only truly **Breaking** or genuinely **Interesting** developments based on verifiable events, data, or significant announcements presented in the summary. Mundane, routine, low-impact, non-factual, purely speculative, or clearly off-topic updates **must** be classified as **Boring**. You operate based on strict criteria focusing on novelty, significance, impact, verifiable claims, and major players/events. Classify news into **exactly one** level: "Breaking", "Interesting", or "Boring". Select the **single most relevant topic** from the provided list. Employ step-by-step reasoning internally but **ONLY output the final JSON**. Your output must strictly adhere to the specified JSON format and contain NO other text, explanations, or formatting.
"""

FILTER_PROMPT_USER_TEMPLATE = """
Task: Critically analyze the provided news article content. Determine its importance level (Breaking, Interesting, Boring) based on factual substance and relevance to the AI/Tech/Major News field. Assign the single most appropriate topic. Filter aggressively.

Allowed Topics (Select ONE):
{allowed_topics_list_str}

Importance Level Criteria:
- **Breaking**: Reserved for **verified, urgent, high-impact factual events** demanding immediate widespread attention. MUST BE TRULY EXCEPTIONAL in the AI/Tech sphere (e.g., verified SOTA model release significantly outperforming others, critical exploited AI vulnerability, landmark AI regulation enacted affecting many, confirmed huge tech acquisition/shutdown with clear industry-wide effects like Broadcom/VMware). Standard product launches are **never** Breaking.
- **Interesting**: Requires *demonstrable significance* AND *clear factual reporting* within the summary, relevant to AI, Tech, or major related industry news. Must present *new, verifiable information*. Examples: Notable AI model releases *with specific verifiable performance claims/novel capabilities*, high-impact AI/Tech research papers *with novel findings*, major player strategic shifts *with concrete actions* (e.g., major open-sourcing, significant policy change like Apple allowing external payments), *confirmed* major controversy/ethical incident (e.g., large-scale AI misuse), landmark legal rulings impacting the tech industry (e.g., Epic vs Apple outcome), significant *late-stage* funding (>~$100M) for *foundational* AI tech. **General analysis, interviews, opinion pieces, predictions, satire, or unverified rumors are NOT Interesting.** If unsure, **default to Boring.** Consider the implied source if possible (is it likely factual reporting or opinion/satire?).
- **Boring**: All other content. Includes: Routine business news (standard earnings reports *without major surprises*, stock price analysis, generic partnerships, *most funding rounds*, conference summaries *without major releases*), minor software/model updates, UI tweaks, feature additions without significant capability change, PR announcements, standard personnel changes, *satire/parody*, *opinion/editorials/blog posts*, *speculation/predictions*, most 'explainer' or 'how-to' articles, news clearly unrelated to AI/Tech/Major Industry events (e.g., sports scores, local events unless tech/AI related). **Filter Aggressively.**

Input News Article Content (Title and Summary):
Title: {article_title}
Summary: {article_summary}

--- START FEW-SHOT EXAMPLES ---

(Example 1 - Breaking)
Title: "Anthropic Releases Claude 3.5 Sonnet, Outperforms GPT-4o and Gemini Ultra on Key Benchmarks"
Summary: "Anthropic unexpectedly launched Claude 3.5 Sonnet today. Internal benchmarks show it surpassing OpenAI's GPT-4o and Google's Gemini Ultra in graduate-level reasoning (GPQA), coding (HumanEval), and multimodal tasks..."
Expected JSON:
```json
{{
  "importance_level": "Breaking",
  "topic": "AI Models",
  "reasoning_summary": "Verified SOTA model release from major player with specific, significant benchmark claims surpassing top competitors.",
  "primary_topic_keyword": "Claude 3.5 Sonnet release"
}}


(Example 2 - Interesting - Legal/Business)
Title: "Epic Games Prevails Over Apple, Court Rules App Store Must Allow External Payment Options"
Summary: "A federal judge ruled today in the Epic Games v. Apple case, issuing an injunction that requires Apple to permit developers to include links and buttons directing users to external payment systems, bypassing Apple's commission."
Expected JSON:

{{
  "importance_level": "Interesting",
  "topic": "Business",
  "reasoning_summary": "Landmark court ruling with significant, direct impact on major tech platform (Apple) and app developers.",
  "primary_topic_keyword": "Epic v Apple ruling"
}}

(Example 3 - Boring - Funding Round)
Title: "AI Startup 'InnovateAI' Secures $5M Seed Funding for Marketing Tools"
Summary: "InnovateAI, a company developing AI tools for marketing automation, announced it has closed a $5 million seed funding round led by Venture Partners..."
Expected JSON:

{{
  "importance_level": "Boring",
  "topic": "Startups",
  "reasoning_summary": "Routine early-stage funding round for a niche AI application; lacks broad impact.",
  "primary_topic_keyword": "InnovateAI seed funding"
}}

(Example 4 - Boring - Satire/Unverified Claim)
Title: "Zuckerberg Says in Response to Loneliness Epidemic, He Will Create Most of Your Friends Using AI"
Summary: "Reports indicate Mark Zuckerberg announced a new Meta initiative where advanced AI companions will be generated... Details remain scarce."
Expected JSON:

{{
  "importance_level": "Boring",
  "topic": "Society",
  "reasoning_summary": "Likely satire or unverified claim lacking concrete details/evidence; not factual reporting.",
  "primary_topic_keyword": "Zuckerberg AI friends claim"
}}

(Example 5 - Boring - Opinion/General Discussion)
Title: "Expert: Why Responsible AI Deployment is Crucial for the Future"
Summary: "Leading AI ethicist Dr. Jane Smith argues in a new blog post that careful consideration of bias... She reiterates the need for ongoing dialogue."
Expected JSON:

{{
  "importance_level": "Boring",
  "topic": "Ethics",
  "reasoning_summary": "Opinion piece discussing general concepts without new factual developments or events.",
  "primary_topic_keyword": "Responsible AI discussion"
}}

--- END FEW-SHOT EXAMPLES ---

Based on your internal step-by-step reasoning for the current input article (NOT the examples above):

Determine the core news event or claim.

Evaluate its factual basis and source nature (if possible) based only on the summary. Is it reporting a concrete event/release/finding/ruling, or is it likely opinion/satire/speculation/PR?

Assess its impact and novelty against the strict criteria for AI/Tech/Major News. Assign ONE importance level: "Breaking", "Interesting", or "Boring". Default to Boring if unsure or non-factual.

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