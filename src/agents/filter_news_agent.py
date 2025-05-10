import os
import sys
import requests
import json
import logging
import re
from dotenv import load_dotenv
from datetime import datetime, timezone

# --- Path Setup ---
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

# --- Load Environment Variables & Config ---
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"

AGENT_MODEL = "deepseek-chat" 
MAX_TOKENS_RESPONSE = 350 
TEMPERATURE = 0.05 
JSON_MODE_FOR_DEEPSEEK = {"type": "json_object"} 

# --- REFINED ALLOWED TOPICS ---
ALLOWED_TOPICS = [
    "Core AI Model Development", "Novel AI Architectures", "AI Hardware & Semiconductors", 
    "AI Software & Platforms", "Robotics & Embodied AI", "AI Compute Infrastructure", 
    "Fundamental AI Research", "AI Algorithms & Techniques", "Open Source AI Initiatives",
    "AI in Business & Enterprise", "AI Startups & Venture Capital", "AI Market Analysis & Finance",
    "AI in Healthcare & Biotechnology", "AI: Societal & Economic Impact", "AI Ethics & Responsible AI", 
    "AI Governance & Regulation", "AI Policy & Geopolitics",
    "Generative AI Applications", "AI in Creative Industries", "AI for Climate & Sustainability", 
    "AI in Education & Workforce", "Cybersecurity & AI", "AI in Autonomous Systems", 
    "Quantum Computing for AI", "AGI/ASI Research & Safety", "Specialized AI Applications", 
    "Other Emerging AI Trends" # More generic catch-all
]
IMPORTANT_ENTITIES_FILE = os.path.join(PROJECT_ROOT, 'data', 'important_entities.json')

def load_important_entities():
    try:
        with open(IMPORTANT_ENTITIES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            people = [p.lower() for p in data.get("people", [])]
            companies_products = [cp.lower() for cp in data.get("companies_products", [])]
            all_entities = list(set(people + companies_products)) 
            logger.info(f"Loaded {len(people)} important people and {len(companies_products)} companies/products.")
            return people, companies_products, all_entities
    except Exception as e:
        logger.error(f"CRITICAL: Failed to load/parse {IMPORTANT_ENTITIES_FILE}: {e}. Override rule integrity compromised.")
        return [], [], []

IMPORTANT_PEOPLE_LIST, IMPORTANT_COMPANIES_PRODUCTS_LIST, _ = load_important_entities()

# --- ADVANCED Agent Prompts (Reinforced) ---
FILTER_PROMPT_SYSTEM_ADVANCED = """
You are an **Apex AI News Intelligence Analyst and Master Content Gatekeeper**. Your mandate is to perform a rigorous, multi-faceted critical evaluation of incoming news article content (title and summary). Your objective is to discern profound significance, irrefutable factual basis, and direct, substantive relevance to a highly discerning audience focused on transformative AI, cutting-edge Technology, and pivotal related global/industry developments.

Your primary function is to **aggressively filter out** all trivial, speculative, rehashed, or non-substantive content UNLESS it involves a *verifiable, significant new action, statement, or product launch* by entities on the provided CRITICAL OVERRIDE lists. You must avoid using hype words like "groundbreaking", "revolutionary", "game-changing" in your reasoning or keywords unless the source itself uses such direct quotes AND the claim is truly exceptional and well-supported within the summary.

You MUST identify only truly **Paradigm-Shifting (Breaking)** or genuinely **Insightful & Consequential (Interesting)** developments. These must be based on verifiable events, concrete data, or major strategic announcements detailed within the provided summary.

Classification Schema:
1.  **Importance Level:** Exactly ONE of "Breaking", "Interesting", or "Boring".
2.  **Topic:** The SINGLE most precise and relevant topic from the extended Allowed Topics list.
3.  **Primary Topic Keyword:** A concise (3-7 words) semantic phrase capturing the absolute core event/concept.
4.  **Reasoning Summary:** A structured, brief justification.

**Output STRICTLY in the specified JSON format. NO extraneous text, explanations, or conversational remarks.** Your internal analysis must be meticulous, but the output is purely JSON.
"""

FILTER_PROMPT_USER_TEMPLATE_ADVANCED = """
Perform a critical analysis of the following news article content:
Title: {article_title}
Summary (may be truncated if very long): {article_summary}

**ALLOWED TOPICS (Select the SINGLE most precise fit):**
{allowed_topics_list_str}

**CRITICAL OVERRIDE ENTITIES (Significant news involving these entities is at least 'Interesting'):**
-   **Key Individuals (Sample from dynamic list):** {key_individuals_examples_str}
-   **Key Companies/Products (Sample from dynamic list):** {key_companies_products_examples_str}
    *Evaluation Note:* Mere mention is insufficient. The entity must be central to a *new, factual development* detailed in the summary.

**DETAILED IMPORTANCE LEVEL CRITERIA (Apply *after* CRITICAL OVERRIDE check):**

*   **"Breaking" (Score 9-10/10 Significance):**
    *   **Definition:** Reserved EXCLUSIVELY for verified, urgent, high-impact, and broadly consequential factual events demanding immediate, widespread attention within the global AI/Tech sphere. Must represent a *paradigm shift, major disruption, or foundational breakthrough.* Avoid using subjective hype in your reasoning.
    *   **Strict Examples (Illustrative, not exhaustive):**
        *   Confirmation of a new SOTA AI model release that *demonstrably and substantially* surpasses existing benchmarks across multiple key tasks (e.g., a true GPT-5 level jump with evidence in summary).
        *   Discovery and verified exploitation of a critical, widespread AI system vulnerability with immediate large-scale security implications.
        *   Landmark, globally impactful AI legislation/treaty enacted with clear, immediate, and widespread consequences for the AI industry.
        *   A confirmed major acquisition or merger between Tier-1 AI companies that fundamentally reshapes the competitive landscape.
        *   Credible, verifiable announcements related to AGI/ASI milestones from highly reputable research institutions if detailed with substance in the summary. Extreme skepticism applied.
    *   **Typically NOT Breaking:** Standard product launches by key entities, new feature announcements, most funding rounds, typical research papers unless truly transformative and widely validated *within the summary*.

*   **"Interesting" (Score 6-8/10 Significance):**
    *   **Definition:** News that presents *new, verifiable information of demonstrable significance* to the AI/Tech field OR involves a CRITICAL OVERRIDE ENTITY in a new, factual development. Must offer genuine insight, indicate a notable trend, or detail a consequential event/product.
    *   **Strict Examples:**
        *   Notable new AI model releases with clear improvements or unique capabilities.
        *   Significant strategic shifts by major AI players.
        *   Verified major ethical controversies or security incidents directly involving key AI systems/companies with clear impact.
        *   Landmark legal rulings or significant regulatory proposals directly impacting a large segment of the tech/AI industry.
        *   Substantial or strategically crucial funding rounds for companies developing *foundational* AI technologies.
        *   Significant, factual, and newsworthy product launches, policy statements, or strategic actions by individuals/companies on the CRITICAL OVERRIDE lists.
        *   Peer-reviewed research papers from top-tier venues presenting *significant, verifiable advances*.
    *   **Typically NOT Interesting (unless CRITICAL OVERRIDE applies with new facts):** General market analysis, minor software/app updates, most product reviews, routine PR, standard personnel changes, most opinion pieces, unverified rumors, listicles, 'explainer' articles on common knowledge.

*   **"Boring" (Score <6/10 Significance):**
    *   **Definition:** All other content. This includes news that is trivial, rehashed, overly speculative without basis in the summary, primarily opinion-driven (if not from a key override entity on a new matter), clickbait, or irrelevant to a sophisticated AI/Tech audience. **FILTER AGGRESSIVELY.**

**ANALYSIS WORKFLOW (Internal Thought Process):**
1.  **Entity Check:** Is a CRITICAL OVERRIDE entity central to a *new, factual* event in the summary?
2.  **Core Claim Identification:** What is the central assertion or news event?
3.  **Factuality Assessment (Based SOLELY on summary):** Does the summary present claims as verified facts, announcements, or as speculation/opinion? Are there indicators of sourcing or evidence?
4.  **Novelty Assessment:** Is this genuinely new information?
5.  **Impact Assessment:** What is the potential scope and magnitude of this news?
6.  **Final Importance Level:** Based on all above, assign "Breaking", "Interesting", or "Boring".
7.  **Topic Selection:** If not "Boring", choose the single most precise topic from the ALLOWED TOPICS.
8.  **Primary Topic Keyword Extraction:** Extract a concise (3-7 words) semantic phrase reflecting the core news event. Avoid hype words like "groundbreaking" unless directly and prominently quoted as such from a credible source within the summary for an exceptional event.

**JSON OUTPUT (Strictly Adhere to this format, no other text):**
{{
  "importance_level": "string",
  "topic": "string",
  "reasoning_summary": {{
    "override_entity_check": "string", 
    "factuality_novelty": "string", 
    "impact_assessment": "string", 
    "final_justification": "string" 
  }},
  "primary_topic_keyword": "string"
}}
"""

# (API Call Function and rest of the script remains the same as your last provided version)
# ... call_deepseek_api_filter, run_filter_agent, and __main__ block ...

# --- API Call Function ---
def call_deepseek_api_filter(system_prompt, user_prompt):
    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY missing for filter agent.")
        return None
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Accept": "application/json"
    }
    payload = {
        "model": AGENT_MODEL,
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        "max_tokens": MAX_TOKENS_RESPONSE,
        "temperature": TEMPERATURE,
        "response_format": JSON_MODE_FOR_DEEPSEEK, 
        "stream": False
    }
    try:
        logger.debug(f"Sending ADVANCED filter request (model: {AGENT_MODEL}).")
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=90) 
        response.raise_for_status()
        result = response.json()
        if result.get("choices") and result["choices"][0].get("message"):
            content_str = result["choices"][0]["message"].get("content","").strip()
            try:
                parsed_content = json.loads(content_str)
                required_top_keys = ["importance_level", "topic", "reasoning_summary", "primary_topic_keyword"]
                if not all(key in parsed_content for key in required_top_keys):
                    logger.error(f"DeepSeek JSON output missing required top-level keys: {content_str}")
                    return None
                if not isinstance(parsed_content.get("reasoning_summary"), dict):
                    logger.error(f"DeepSeek JSON 'reasoning_summary' is not a dict: {content_str}")
                    return None 
                return parsed_content 
            except json.JSONDecodeError as jde:
                logger.error(f"Failed to parse JSON from DeepSeek (even in JSON mode): {jde}. Response: {content_str}")
                return None
        logger.error(f"DeepSeek API response malformed (filter): {result}")
        return None
    except Exception as e:
        logger.exception(f"DeepSeek API call failed (filter): {e}")
        return None

# --- Main Agent Function ---
def run_filter_agent(article_data):
    if not isinstance(article_data, dict) or not article_data.get('title') or not article_data.get('summary'):
        logger.error("Invalid article_data for ADVANCED filter agent.")
        if isinstance(article_data, dict): article_data['filter_error'] = "Invalid input format";
        return article_data

    article_title = article_data['title']
    article_summary_full = article_data.get('content_for_processing', article_data.get('summary', ''))
    article_id = article_data.get('id', 'N/A')

    max_summary_for_prompt = 2000 
    prompt_summary = article_summary_full
    if len(article_summary_full) > max_summary_for_prompt:
        logger.warning(f"Truncating summary for filter prompt (> {max_summary_for_prompt} chars) for ID: {article_id}")
        prompt_summary = article_summary_full[:max_summary_for_prompt] + "..."

    allowed_topics_str = "\n".join([f"- {topic}" for topic in ALLOWED_TOPICS])
    
    key_individuals_examples_str = ", ".join(IMPORTANT_PEOPLE_LIST[:10]) + (", etc." if len(IMPORTANT_PEOPLE_LIST) > 10 else "")
    key_companies_products_examples_str = ", ".join(IMPORTANT_COMPANIES_PRODUCTS_LIST[:15]) + (", etc." if len(IMPORTANT_COMPANIES_PRODUCTS_LIST) > 15 else "")

    try:
        user_prompt = FILTER_PROMPT_USER_TEMPLATE_ADVANCED.format(
            article_title=article_title,
            article_summary=prompt_summary,
            allowed_topics_list_str=allowed_topics_str,
            key_individuals_examples_str=key_individuals_examples_str,
            key_companies_products_examples_str=key_companies_products_examples_str
        )
    except KeyError as e:
        logger.exception(f"KeyError formatting ADVANCED filter prompt template (ID: {article_id}): {e}")
        article_data['filter_verdict'] = None
        article_data['filter_error'] = f"Prompt template formatting error: {e}"
        return article_data

    logger.info(f"Running ADVANCED filter agent for article ID: {article_id} Title: {article_title[:70]}...")
    
    filter_verdict_dict = call_deepseek_api_filter(FILTER_PROMPT_SYSTEM_ADVANCED, user_prompt)

    if not filter_verdict_dict:
        logger.error(f"ADVANCED Filter agent API call or JSON parsing failed for article ID: {article_id}.")
        article_data['filter_verdict'] = None
        article_data['filter_error'] = "API call/JSON parse failed"
        return article_data

    try:
        required_keys = ["importance_level", "topic", "reasoning_summary", "primary_topic_keyword"]
        if not all(k in filter_verdict_dict for k in required_keys):
            raise ValueError("Missing required keys in filter verdict JSON from API")
        
        reasoning_summary_obj = filter_verdict_dict.get("reasoning_summary")
        if not isinstance(reasoning_summary_obj, dict) or not all(k in reasoning_summary_obj for k in ["override_entity_check", "factuality_novelty", "impact_assessment", "final_justification"]):
             raise ValueError("Reasoning summary object is malformed or missing keys.")

        valid_levels = ["Breaking", "Interesting", "Boring"]
        if filter_verdict_dict['importance_level'] not in valid_levels:
            logger.warning(f"Invalid importance_level '{filter_verdict_dict['importance_level']}' from LLM. Forcing to 'Boring'. ID: {article_id}")
            filter_verdict_dict['importance_level'] = "Boring"
        
        if filter_verdict_dict['topic'] not in ALLOWED_TOPICS:
            logger.warning(f"Invalid topic '{filter_verdict_dict['topic']}' from LLM. Forcing to 'Other Emerging AI Trends'. ID: {article_id}")
            filter_verdict_dict['topic'] = "Other Emerging AI Trends"
        
        if not filter_verdict_dict.get('primary_topic_keyword') or len(filter_verdict_dict['primary_topic_keyword'].split()) > 7:
            logger.warning(f"Primary topic keyword missing or too long: '{filter_verdict_dict.get('primary_topic_keyword','None')}'. ID: {article_id}. Attempting to generate a fallback.")
            filter_verdict_dict['primary_topic_keyword'] = ' '.join(article_title.split()[:5]) 

        logger.info(f"ADVANCED Filter verdict for ID {article_id}: Level='{filter_verdict_dict['importance_level']}', Topic='{filter_verdict_dict['topic']}', Keyword='{filter_verdict_dict['primary_topic_keyword']}'")
        logger.debug(f"Reasoning for {article_id}: {json.dumps(filter_verdict_dict['reasoning_summary'])}")

        article_data['filter_verdict'] = filter_verdict_dict 
        article_data['filter_error'] = None
        article_data['filtered_at_iso'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        return article_data

    except ValueError as ve: 
        logger.error(f"Validation error on filter verdict for ID {article_id}: {ve}. Response: {filter_verdict_dict}")
        article_data['filter_verdict'] = None
        article_data['filter_error'] = f"Verdict validation failed: {ve}"
        return article_data
    except Exception as e:
        logger.exception(f"Unexpected error processing filter response for ID {article_id}: {e}")
        article_data['filter_verdict'] = None
        article_data['filter_error'] = "Unexpected processing error post-API call"
        return article_data

# --- Example Usage (for standalone testing) ---
if __name__ == "__main__":
    logging.getLogger().setLevel(logging.DEBUG) 
    logger.setLevel(logging.DEBUG) 

    test_article_truly_breaking = {
        'id': 'test-breaking-001',
        'title': "OpenAI Confirms GPT-5 Achieves Near-Human Performance on All Major Reasoning Benchmarks, Cites Verifiable Public Data",
        'summary': "OpenAI today officially announced that its upcoming GPT-5 model has demonstrated performance nearly indistinguishable from human experts across a comprehensive suite of reasoning benchmarks, including complex mathematics, advanced coding, and nuanced ethical dilemmas. The company released a detailed technical paper with verifiable benchmark scores and methodologies, citing specific datasets like MATH, HumanEval, and MMLU where GPT-5 shows >95th percentile human-level results. This marks a pivotal moment in AI development, potentially accelerating AGI timelines. The announcement included plans for staged deployment with rigorous safety protocols.",
        'content_for_processing': "OpenAI today officially announced that its upcoming GPT-5 model has demonstrated performance nearly indistinguishable from human experts across a comprehensive suite of reasoning benchmarks, including complex mathematics, advanced coding, and nuanced ethical dilemmas. The company released a detailed technical paper with verifiable benchmark scores and methodologies, citing specific datasets like MATH, HumanEval, and MMLU where GPT-5 shows >95th percentile human-level results. This marks a pivotal moment in AI development, potentially accelerating AGI timelines. The announcement included plans for staged deployment with rigorous safety protocols. The implications for various industries are immense, from automated scientific discovery to highly personalized education."
    }

    test_article_interesting_key_entity = {
        'id': 'test-interesting-override-002',
        'title': "Elon Musk Announces Tesla Will Open Source Full Self-Driving (FSD) v13 Codebase by End of Year",
        'summary': "In a surprise tweet, Elon Musk declared that Tesla intends to open source the entire codebase for its Full Self-Driving (FSD) version 13 by December 2025. Musk stated this move is to accelerate autonomous vehicle safety and development globally. The decision follows increased scrutiny of FSD's capabilities and is seen as a major strategic shift for the company. Specific licensing details were not provided.",
        'content_for_processing': "In a surprise tweet, Elon Musk declared that Tesla intends to open source the entire codebase for its Full Self-Driving (FSD) version 13 by December 2025. Musk stated this move is to accelerate autonomous vehicle safety and development globally. The decision follows increased scrutiny of FSD's capabilities and is seen as a major strategic shift for the company. Specific licensing details were not provided. This could impact competitors and the wider AV software landscape."
    }
    
    test_article_boring_update = {
        'id': 'test-boring-update-003',
        'title': "Popular Photo Editing App 'PixelMagic' Releases Version 5.2 with New UI Color Themes and Minor Bug Fixes",
        'summary': "PixelMagic, a widely used mobile photo editing application, today rolled out version 5.2. The update primarily features a refreshed set of user interface color themes and addresses several minor bugs reported by users in the previous version. Performance remains largely unchanged.",
        'content_for_processing': "PixelMagic, a widely used mobile photo editing application, today rolled out version 5.2. The update primarily features a refreshed set of user interface color themes and addresses several minor bugs reported by users in the previous version. Performance remains largely unchanged. Users can download the update from the App Store and Google Play."
    }

    logger.info("\n--- Running ADVANCED Filter Agent Standalone Test ---")

    logger.info("\nTesting TRULY BREAKING article...")
    result_breaking = run_filter_agent(test_article_truly_breaking.copy())
    print("Result (Truly Breaking):", json.dumps(result_breaking.get('filter_verdict'), indent=2))

    logger.info("\nTesting INTERESTING article involving KEY ENTITY...")
    result_interesting_override = run_filter_agent(test_article_interesting_key_entity.copy())
    print("Result (Interesting Override):", json.dumps(result_interesting_override.get('filter_verdict'), indent=2))
    
    logger.info("\nTesting BORING article (minor update, no key entity)...")
    result_boring = run_filter_agent(test_article_bqoring_update.copy())
    print("Result (Boring Update):", json.dumps(result_boring.get('filter_verdict'), indent=2))

    logger.info("\n--- ADVANCED Filter Agent Standalone Test Complete ---")