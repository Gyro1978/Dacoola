# src/agents/seo_review_agent.py

import os
import sys
import json
import logging
import modal # Added for Modal integration
import re
import time

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
# --- End Setup Logging ---

# --- Configuration & Constants ---
LLM_MODEL_NAME = os.getenv('SEO_REVIEW_AGENT_MODEL', "deepseek-R1") # Updated model name

MODAL_APP_NAME = "deepseek-gpu-inference-app" # Updated: Name of the Modal app
MODAL_CLASS_NAME = "DeepSeekModel" # Name of the class in the Modal app

API_TIMEOUT = 180 # Retained for Modal call options if applicable
MAX_RETRIES = 3 # Retained for application-level retries with Modal
RETRY_DELAY_BASE = 10 # Retained for application-level retries with Modal

EARLY_BODY_WORD_COUNT = 150 # Approx word count for "early in body" check

# --- DeepSeek System Prompt ---
SEO_REVIEW_SYSTEM_PROMPT = """
You are **ApexSEO Analyzer**, an Artificial Superintelligence (ASI)-level SEO Auditor and Content Strategist. Your capabilities encompass deep, nuanced understanding of technical SEO, advanced on-page optimization techniques, cutting-edge content strategy specifically for tech news, search engine algorithms, and user engagement signals. You operate with unparalleled precision and insight.

Your sole mission is to conduct a meticulous and comprehensive SEO review of the provided tech news article content and its associated metadata. Your analysis must be based *exclusively* on the input data. You will not access external websites or tools.

You will receive input as a single JSON object. Your entire response MUST be a single, valid JSON object conforming precisely to the schema detailed below. There must be NO conversational fluff, introductions, explanations, or conclusions outside of this JSON structure.

### Expected Input Data Schema:

You will receive a JSON object with the following structure:

```json
{
  "generated_article_content_md": "string", // The full Markdown content of the article.
  "generated_title_tag": "string",          // The SEO title tag.
  "generated_seo_h1": "string",             // The main H1 heading.
  "generated_meta_description": "string",   // The meta description.
  "primary_keyword": "string",              // The main target keyword.
  "final_keywords": ["string"],             // Array of all relevant keywords (primary + secondary + LSI).
  "article_plan": {                         // The structural plan used to generate the article.
    "sections": [
      {
        "heading_text": "string",           // The planned heading for this section.
        "key_points": ["string"],           // Key points to cover in this section.
        "purpose": "string"                 // The purpose of this section.
      }
      // ... more sections
    ]
  },
  "original_source_url": "string",          // (Optional) URL of the original source, for contextual understanding only.
  "article_link": "string"                  // The final internal link/slug of the generated article.
}
```

### Mandatory Output JSON Schema:

Your entire output MUST be a single, valid JSON object adhering strictly to this schema:

```json
{
  "overall_seo_score": "integer", // A score from 1 (poor) to 100 (excellent) representing overall SEO health. This score should be a holistic assessment derived from all other review components.
  "seo_review_summary": "string", // A 2-3 sentence concise summary highlighting the most critical findings and overall SEO state.
  "keyword_analysis": {
    "primary_keyword_check": {
      "keyword": "string", // The primary_keyword being checked.
      "present_in_title_tag": "boolean",
      "present_in_h1": "boolean",
      "present_in_meta_description": "boolean",
      "present_early_in_body": "boolean", // Check if present within the first ~100-150 words of generated_article_content_md.
      "density_assessment": "string", // e.g., "Optimal", "Slightly Low", "Slightly High", "Acceptable", "Potentially Stuffed". Assess natural integration, not just raw count.
      "notes": "string" // Specific observations or suggestions regarding primary keyword usage.
    },
    "secondary_keywords_usage": [ // Array for each secondary keyword from 'final_keywords' (excluding the primary_keyword). If no secondary keywords, this array should be empty.
      {
        "keyword": "string",
        "found_in_body": "boolean", // Check if present anywhere in generated_article_content_md.
        "in_subheadings": "boolean", // Check if present in any H2/H3/H4. Use article_plan.sections[*].heading_text for planned subheadings and also verify in generated_article_content_md if possible.
        "notes": "string" // e.g., "Well-integrated", "Could be used more naturally in section X", "Consider adding to a relevant subheading from the article_plan".
      }
    ],
    "lsi_and_semantic_richness_notes": "string" // General comments on the use of related terms, synonyms, and overall semantic depth of the content in relation to the keywords.
  },
  "title_tag_review": {
    "text": "string", // The generated_title_tag being reviewed.
    "length_char_count": "integer",
    "length_ok": "boolean", // Optimal: 50-60 characters. Acceptable up to 65 characters.
    "keyword_prominence_ok": "boolean", // Is the primary_keyword present, ideally towards the beginning?
    "clarity_persuasiveness_score": "integer", // Score from 1 (very poor) to 10 (excellent) for clarity and persuasiveness for SERP CTR.
    "is_unique_from_h1": "boolean", // True if generated_title_tag is different from generated_seo_h1.
    "suggestions": "string" // Actionable recommendations for improvement (e.g., "Shorten by X chars", "Front-load keyword", "Improve CTR appeal by...").
  },
  "h1_review": {
    "text": "string", // The generated_seo_h1 being reviewed.
    "length_char_count": "integer",
    "length_ok": "boolean", // Optimal: 60-70 characters. Acceptable up to 75 characters.
    "keyword_prominence_ok": "boolean", // Is the primary_keyword present and prominent?
    "clarity_impact_score": "integer", // Score from 1 (very poor) to 10 (excellent) for clarity and on-page impact.
    "suggestions": "string" // Actionable recommendations.
  },
  "meta_description_review": {
    "text": "string", // The generated_meta_description being reviewed.
    "length_char_count": "integer",
    "length_ok": "boolean", // Optimal: 120-155 characters. Acceptable up to 160 characters.
    "keyword_prominence_ok": "boolean", // Is the primary_keyword present? Are other relevant keywords included naturally?
    "includes_cta_or_uvp": "boolean", // Does it include a clear Call To Action or Unique Value Proposition?
    "clarity_persuasiveness_score": "integer", // Score from 1 (very poor) to 10 (excellent) for encouraging clicks from SERPs.
    "suggestions": "string" // Actionable recommendations.
  },
  "content_and_structure_review": {
    "headings_hierarchy_assessment": "string", // Analyze generated_article_content_md for Markdown headings (H1, H2, H3, etc.) and compare with article_plan.sections[*].heading_text. e.g., "Good structure (H1, H2s, H3s as planned)", "Missing H2s for several sections", "Improper nesting of headings observed", "Headings generally follow the article_plan".
    "readability_assessment": "string", // Based on sentence structure, paragraph length, vocabulary complexity in generated_article_content_md. e.g., "Excellent: Clear, concise, well-suited for tech news audience.", "Fair: Some long sentences or complex jargon could be simplified.", "Needs improvement: Overly complex or dense text."
    "use_of_formatting_elements": "string", // Assess use of Markdown bold, italics, lists, blockquotes in generated_article_content_md. e.g., "Good use of lists and bolding to highlight key info.", "Could benefit from more bullet points or subheadings to break up text.", "Minimal formatting used."
    "internal_linking_opportunities": [ // Suggest 1-3 specific, highly relevant internal linking opportunities based *solely* on the generated_article_content_md.
      {
        "anchor_text_suggestion": "string", // A specific, compelling anchor text.
        "target_keyword_or_concept": "string" // The keyword or concept this anchor text should ideally link to (representing another page on the site).
      }
    ],
    "image_seo_notes": "string", // General reminder: "Ensure all images (especially the main one) have descriptive alt text, ideally incorporating relevant keywords naturally. Filenames should also be descriptive." (You cannot see images, this is a standard best practice reminder).
    "content_depth_and_relevance_notes": "string" // Assess if the content appears to cover the topic (based on keywords and article_plan) with sufficient depth and relevance for a tech news audience. Mention if it seems to fulfill the purpose outlined in article_plan.sections[*].purpose.
  },
  "actionable_recommendations": [ // A list of the top 3-5 most impactful, specific, and actionable SEO recommendations based on your entire analysis.
    "string" // e.g., "Shorten title tag by X characters to ensure full visibility in SERPs.", "Integrate the primary keyword 'X' earlier in the meta description to improve relevance signaling.", "Revise H2 heading for section 'Y' to include secondary keyword 'Z'."
  ]
}
```

### Evaluation Guidelines & SEO Principles:

You must meticulously evaluate the provided data based on the following principles. Your ASI-level understanding should guide your interpretation.

1.  **Keyword Optimization:**
    *   **Primary Keyword (`primary_keyword`):**
        *   **Placement:** Check presence in `generated_title_tag`, `generated_seo_h1`, `generated_meta_description`.
        *   **Prominence:** How early and naturally does it appear in these elements and within the first ~100-150 words of `generated_article_content_md`?
        *   **Density & Naturalness (`density_assessment`):** Assess if the keyword usage in `generated_article_content_md` feels natural and contextually relevant, or if it appears forced, sparse, or stuffed. Avoid rigid percentage rules; focus on semantic integration.
    *   **Secondary & LSI Keywords (`final_keywords` excluding `primary_keyword`):**
        *   **Integration:** Check for natural integration within `generated_article_content_md`.
        *   **Subheading Usage:** Verify if secondary keywords are present in subheadings. Cross-reference Markdown headings in `generated_article_content_md` with `article_plan.sections[*].heading_text`.
    *   **Semantic Richness:** Evaluate the overall use of semantically related terms and concepts that contribute to topic authority, beyond just the listed keywords.

2.  **On-Page Elements:**
    *   **Title Tag (`generated_title_tag`):**
        *   **Length:** Adhere to character count guidelines (Optimal 50-60, Max 65).
        *   **Effectiveness:** Clarity, persuasiveness, CTR potential. Uniqueness from H1.
    *   **H1 Heading (`generated_seo_h1`):**
        *   **Length:** Adhere to character count guidelines (Optimal 60-70, Max 75).
        *   **Clarity & Impact:** Ensure it clearly defines the page content and uses the primary keyword effectively.
    *   **Meta Description (`generated_meta_description`):**
        *   **Length:** Adhere to character count guidelines (Optimal 120-155, Max 160).
        *   **Persuasiveness & CTR:** Keyword inclusion, compelling copy, presence of Call-To-Action (CTA) or Unique Value Proposition (UVP).
    *   **Heading Structure (H2-H6):** Analyze `generated_article_content_md` for a logical and hierarchical heading structure. This should generally align with the `article_plan`. Check for proper nesting and use of keywords in subheadings where appropriate.

3.  **Content Quality & Relevance (within the scope of provided text):**
    *   **Alignment with Keywords:** Does the content effectively address the topics indicated by `primary_keyword` and `final_keywords`?
    *   **Depth and Value:** Based on `generated_article_content_md` and `article_plan`, assess if the content seems to provide substantial value and comprehensive coverage for a tech news audience. Does it fulfill the `purpose` of each section in `article_plan`?
    *   **Readability & User Experience:** Evaluate clarity of language, sentence structure, paragraph length, and use of formatting (bold, lists, etc. from Markdown) for ease of reading.
    *   **Original Source Context:** If `original_source_url` is provided, use it for high-level contextual understanding of the topic's origin, but do not analyze the source URL itself or its content. Your review focuses on the *generated* material.

4.  **E-E-A-T (Experience, Expertise, Authoritativeness, Trustworthiness):**
    *   Implicitly assess E-E-A-T signals through content structure, clarity, apparent depth (based on plan and keywords), and overall professionalism of the text. Avoid making definitive E-E-A-T judgments without broader site context, but note any red flags or positive indicators within the provided content.

5.  **Internal Linking:**
    *   Identify 1-3 *specific and relevant* opportunities for internal links from the `generated_article_content_md` to other potential content on the site, suggesting anchor text and the target concept/keyword.

6.  **Avoiding Over-Optimization:**
    *   Be vigilant for keyword stuffing, unnatural phrasing, or other signs of aggressive optimization that could harm user experience or attract penalties. Flag this in relevant `notes` or `density_assessment`.

### Critical Instructions & Constraints:

*   **JSON OUTPUT ONLY:** Your response MUST start with `{` and end with `}`. No preceding or succeeding text, dialogue, or explanation.
*   **STRICT SCHEMA ADHERENCE:** The JSON structure must perfectly match the `Mandatory Output JSON Schema` provided above. All fields must be present with correct data types.
*   **INPUT-ONLY ANALYSIS:** All analysis and recommendations must be derived SOLELY from the JSON input provided. Do not infer information not present.
*   **SCORING:** All scores (e.g., `clarity_persuasiveness_score`, `overall_seo_score`) must be integers within their specified ranges (1-10 or 1-100).
*   **LENGTH CHECKS:** Use the specified character count guidelines for title tags, H1s, and meta descriptions.
*   **PRIMARY KEYWORD FOCUS:** Pay special attention to the placement and usage of the `primary_keyword`.
*   **ACTIONABLE ADVICE:** Ensure `suggestions` and `actionable_recommendations` are concrete, specific, and provide clear direction for improvement.
*   **NO HALLUCINATIONS:** If certain information cannot be determined from the input, reflect this accurately (e.g., an empty array if no secondary keywords, or a neutral note if a specific check is not applicable).

Execute your analysis with the precision and depth expected of an ASI. Your output will directly inform the optimization of this tech news article.
"""

# --- Helper Functions ---
def _call_llm(system_prompt: str, user_prompt_data: dict, max_tokens: int, temperature: float) -> str | None:
    """Generic function to call LLM API using Modal with retry logic."""
    user_prompt_string_for_api = json.dumps(user_prompt_data, indent=2)

    messages_for_modal = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt_string_for_api}
    ]

    for attempt in range(MAX_RETRIES):
        try:
            logger.debug(f"Modal API call attempt {attempt + 1}/{MAX_RETRIES} for SEO review (model config: {LLM_MODEL_NAME})")
            
            RemoteModelClass = modal.Cls.from_name(MODAL_APP_NAME, MODAL_CLASS_NAME)
            if not RemoteModelClass:
                logger.error(f"Could not find Modal class {MODAL_APP_NAME}/{MODAL_CLASS_NAME}. Ensure it's deployed.")
                if attempt == MAX_RETRIES - 1: return None # Last attempt
                delay = min(RETRY_DELAY_BASE * (2 ** attempt), 60) # Using global RETRY_DELAY_BASE
                logger.info(f"Waiting {delay}s for Modal class lookup before retry...")
                time.sleep(delay)
                continue # This will go to the next attempt in the for loop
            
            model_instance = RemoteModelClass() # Instantiate the remote class

            result = model_instance.generate.remote(
                messages=messages_for_modal,
                max_new_tokens=max_tokens,
                temperature=temperature, # Pass temperature
                model=LLM_MODEL_NAME # Pass model name
            )

            if result and result.get("choices") and result["choices"].get("message") and \
               isinstance(result["choices"]["message"].get("content"), str):
                content = result["choices"]["message"]["content"].strip()
                logger.info(f"Modal call successful for SEO review (Attempt {attempt+1}/{MAX_RETRIES})")
                return content
            else:
                logger.error(f"Modal API response missing content or malformed (attempt {attempt + 1}/{MAX_RETRIES}): {str(result)[:500]}")
                if attempt == MAX_RETRIES - 1: return None
        
        except Exception as e:
            logger.exception(f"Error during Modal API call for SEO review (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt == MAX_RETRIES - 1:
                logger.error("All Modal API attempts for SEO review failed due to errors.")
                return None
        
        delay = min(RETRY_DELAY_BASE * (2 ** attempt), 60) # Using global RETRY_DELAY_BASE
        logger.warning(f"Modal API call for SEO review failed or returned unexpected data (attempt {attempt+1}/{MAX_RETRIES}). Retrying in {delay}s.")
        time.sleep(delay)
        
    logger.error(f"Modal LLM API call for SEO review failed after {MAX_RETRIES} attempts.")
    return None

def _parse_llm_seo_review_response(json_string: str) -> dict | None:
    """Parses LLM JSON response for SEO review, with basic validation."""
    if not json_string:
        logger.error("Empty JSON string provided for parsing SEO review.")
        return None
    try:
        match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', json_string, re.DOTALL | re.IGNORECASE)
        json_to_parse = match.group(1) if match else json_string

        review_data = json.loads(json_to_parse)

        required_top_keys = [
            "overall_seo_score", "seo_review_summary", "keyword_analysis",
            "title_tag_review", "h1_review", "meta_description_review",
            "content_and_structure_review", "actionable_recommendations"
        ]
        for key in required_top_keys:
            if key not in review_data:
                logger.error(f"Missing required top-level key '{key}' in SEO review data.")
                return {"error": f"Missing key: {key}", "raw_response_snippet": json_string[:200]}

        keyword_analysis_value = review_data.get("keyword_analysis")
        if not isinstance(keyword_analysis_value, dict) or "primary_keyword_check" not in keyword_analysis_value:
            logger.warning("Missing or invalid 'primary_keyword_check' in 'keyword_analysis'. SEO review might be incomplete.")
            # Ensure a default structure if it's severely malformed to prevent downstream errors
            if not isinstance(keyword_analysis_value, dict):
                review_data["keyword_analysis"] = {}
            if "primary_keyword_check" not in review_data["keyword_analysis"]:
                 review_data["keyword_analysis"]["primary_keyword_check"] = {
                    "keyword": "N/A", "present_in_title_tag": False, "present_in_h1": False,
                    "present_in_meta_description": False, "present_early_in_body": False,
                    "density_assessment": "Error: Data missing", "notes": "Primary keyword check data missing from LLM."
                }
            if "secondary_keywords_usage" not in review_data["keyword_analysis"]:
                 review_data["keyword_analysis"]["secondary_keywords_usage"] = []


        # Validate score ranges (example for overall_seo_score)
        score = review_data.get("overall_seo_score")
        if not isinstance(score, int) or not (1 <= score <= 100):
            logger.warning(f"Invalid 'overall_seo_score': {score}. Setting to a default low score (e.g., 10).")
            review_data["overall_seo_score"] = 10
        
        # Ensure actionable_recommendations is a list
        if not isinstance(review_data.get("actionable_recommendations"), list):
            logger.warning("'actionable_recommendations' is not a list. Setting to empty list.")
            review_data["actionable_recommendations"] = []


        return review_data

    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON from LLM SEO review response: {json_string[:500]}...")
        return {"error": "JSONDecodeError", "raw_response_snippet": json_string[:200]}
    except Exception as e:
        logger.error(f"Error parsing LLM SEO review response: {e}", exc_info=True)
        return {"error": str(e), "raw_response_snippet": json_string[:200]}


# --- Main Agent Function ---
def run_seo_review_agent(article_pipeline_data: dict) -> dict:
    """
    Runs the SEO Review Agent on the provided article data.
    Expects article_pipeline_data to contain outputs from previous agents.
    """
    article_id = article_pipeline_data.get('id', 'unknown_id')
    logger.info(f"--- Running SEO Review Agent for Article ID: {article_id} ---")

    # CRITICAL FIX: Use 'full_generated_article_body_md' directly from article_pipeline_data
    generated_article_content_md = article_pipeline_data.get('full_generated_article_body_md', '')
    
    generated_title_tag = article_pipeline_data.get('generated_title_tag', '')
    generated_seo_h1 = article_pipeline_data.get('generated_seo_h1', '')
    generated_meta_description = article_pipeline_data.get('generated_meta_description', '')
    primary_keyword = article_pipeline_data.get('primary_topic_keyword', article_pipeline_data.get('primary_keyword', ''))
    final_keywords = article_pipeline_data.get('final_keywords', [])
    article_plan = article_pipeline_data.get('article_plan', {})
    original_source_url = article_pipeline_data.get('link', '') # 'link' usually holds the original source URL
    article_link_slug = article_pipeline_data.get('slug', '')

    if not generated_article_content_md:
        logger.error(f"No generated article Markdown content (full_generated_article_body_md) found for {article_id}. SEO review cannot proceed.")
        article_pipeline_data['seo_review_results'] = {
            "error": "Missing generated_article_content_md",
            "overall_seo_score": 0,
            "seo_review_summary": "SEO review aborted: No article content provided.",
            "actionable_recommendations": ["Ensure article content generation is successful before SEO review."]
        }
        article_pipeline_data['seo_review_status'] = "FAILED_NO_CONTENT"
        return article_pipeline_data

    user_input_context = {
        "generated_article_content_md": generated_article_content_md,
        "generated_title_tag": generated_title_tag,
        "generated_seo_h1": generated_seo_h1,
        "generated_meta_description": generated_meta_description,
        "primary_keyword": primary_keyword,
        "final_keywords": final_keywords,
        "article_plan": article_plan,
        "original_source_url": original_source_url,
        "article_link": f"/articles/{article_link_slug}.html" if article_link_slug else ""
    }

    raw_llm_response = _call_llm(
        system_prompt=SEO_REVIEW_SYSTEM_PROMPT,
        user_prompt_data=user_input_context,
        max_tokens=2000, # Increased slightly as the JSON output can be verbose
        temperature=0.2  # Low temperature for factual, structured output
    )

    seo_review_results = None
    if raw_llm_response:
        seo_review_results = _parse_llm_seo_review_response(raw_llm_response)

    if seo_review_results and "error" not in seo_review_results:
        article_pipeline_data['seo_review_results'] = seo_review_results
        article_pipeline_data['seo_review_status'] = "SUCCESS"
        logger.info(f"SEO Review Agent for {article_id} status: SUCCESS. Overall Score: {seo_review_results.get('overall_seo_score', 'N/A')}")
        logger.debug(f"SEO Review Results for {article_id}:\n{json.dumps(seo_review_results, indent=2)}")
    else:
        fallback_summary = "Automated SEO review failed or returned an error."
        error_info = "Unknown parse error"
        if seo_review_results and isinstance(seo_review_results, dict): # Check if seo_review_results is a dict
            error_info = seo_review_results.get('error', 'Unknown parse error')
            if "raw_response_snippet" in seo_review_results:
                fallback_summary += f" Raw response snippet: {seo_review_results['raw_response_snippet']}"
        else: # Handle if seo_review_results is None or not a dict
             error_info = 'No LLM response or invalid format from LLM parsing'

        logger.error(f"SEO Review Agent for {article_id} FAILED. Error: {error_info}")
        article_pipeline_data['seo_review_status'] = "FAILED_REVIEW_GENERATION"
        # Provide a more complete fallback structure to avoid downstream errors
        article_pipeline_data['seo_review_results'] = {
            "error": error_info,
            "overall_seo_score": 10, # Default low score
            "seo_review_summary": fallback_summary,
            "keyword_analysis": {
                "primary_keyword_check": {"keyword": primary_keyword, "present_in_title_tag": False, "present_in_h1": False, "present_in_meta_description": False, "present_early_in_body": False, "density_assessment": "N/A", "notes": "Review failed."},
                "secondary_keywords_usage": [],
                "lsi_and_semantic_richness_notes": "Review failed."
            },
            "title_tag_review": {"text": generated_title_tag, "length_char_count": len(generated_title_tag), "length_ok": False, "keyword_prominence_ok": False, "clarity_persuasiveness_score": 1, "is_unique_from_h1": False, "suggestions": "Review failed."},
            "h1_review": {"text": generated_seo_h1, "length_char_count": len(generated_seo_h1), "length_ok": False, "keyword_prominence_ok": False, "clarity_impact_score": 1, "suggestions": "Review failed."},
            "meta_description_review": {"text": generated_meta_description, "length_char_count": len(generated_meta_description), "length_ok": False, "keyword_prominence_ok": False, "includes_cta_or_uvp": False, "clarity_persuasiveness_score": 1, "suggestions": "Review failed."},
            "content_and_structure_review": {
                "headings_hierarchy_assessment": "Review failed.", "readability_assessment": "Review failed.",
                "use_of_formatting_elements": "Review failed.", "internal_linking_opportunities": [],
                "image_seo_notes": "Review failed.", "content_depth_and_relevance_notes": "Review failed."
            },
            "actionable_recommendations": ["Manually review SEO aspects. Check LLM API, prompt, and response parsing."]
        }
    return article_pipeline_data

# --- Standalone Execution Example ---
if __name__ == "__main__":
    # Ensure logger is verbose for standalone testing
    logging.getLogger('src.agents.seo_review_agent').setLevel(logging.DEBUG)
    logger.info("--- Starting SEO Review Agent Standalone Test ---")

    # Standalone test data, ensuring `full_generated_article_body_md` is used
    test_article_data = {
        'id': 'test_seo_review_002_standalone',
        'link': 'https://example.com/original-article-v2', # Original source URL
        'slug': 'nvidia-blackwell-b200-gpu-ai-powerhouse-v2', # Article slug
        'primary_topic_keyword': 'NVIDIA Blackwell B200', # Matches key in 'final_keywords'
        'final_keywords': [
            "NVIDIA Blackwell B200", "AI GPU", "AI supercomputing",
            "Jensen Huang", "GTC 2024", "Blackwell architecture benchmarks",
            "Hopper H200 vs Blackwell B200", "AI chip performance", "deep learning hardware"
        ],
        'article_plan': { # Example article plan
            "sections": [
                {"section_type": "introduction", "heading_text": None, "purpose": "Introduce the NVIDIA Blackwell B200 and its significance.", "key_points": ["GTC 2024 announcement", "Successor to Hopper"]},
                {"section_type": "main_body", "heading_text": "Blackwell B200 Architecture Deep Dive", "purpose": "Explain the technical innovations of Blackwell.", "key_points": ["New chiplet design", "Enhanced Tensor Cores", "NVLink advancements"]},
                {"section_type": "main_body", "heading_text": "Performance Benchmarks and Comparisons", "purpose": "Detail performance gains over previous generations.", "key_points": ["Training speed improvements", "Inference efficiency", "Comparison to Hopper H100/H200"]},
                {"section_type": "main_body", "heading_text": "Market Impact and Future Outlook for AI Supercomputing", "purpose": "Discuss the implications for the AI industry.", "key_points": ["Adoption by cloud providers", "New AI application possibilities", "Competitive landscape shifts"]},
                {"section_type": "conclusion", "heading_text": "Conclusion: Blackwell's Transformative Potential", "purpose": "Summarize Blackwell's impact on AI.", "key_points": ["Recap of key advantages", "Future of AI hardware"]}
            ]
        },
        'generated_title_tag': 'NVIDIA Blackwell B200: The AI GPU Redefining Supercomputing', # SEO Title
        'generated_seo_h1': 'NVIDIA Blackwell B200 GPU Unleashed: A New Era for AI Supercomputing', # H1 Heading
        'generated_meta_description': "NVIDIA's new Blackwell B200 GPU sets a new standard for AI speed and efficiency. Discover the Blackwell architecture, benchmarks, and its transformative impact on supercomputing.", # Meta Description
        
        # THIS IS THE KEY: The full Markdown content of the article
        'full_generated_article_body_md': """
NVIDIA's GTC 2024 conference was electrified by the announcement of the **NVIDIA Blackwell B200 GPU**, a monumental leap in AI supercomputing. This new powerhouse chip promises to redefine the boundaries of artificial intelligence, offering significant performance improvements over the already formidable Hopper generation. CEO Jensen Huang passionately detailed its capabilities, particularly for training and deploying trillion-parameter AI models. The Blackwell B200 is not just an upgrade; it's a paradigm shift.

### Blackwell B200 Architecture Deep Dive

At the heart of the NVIDIA Blackwell B200 lies an innovative architecture meticulously engineered for AI's insatiable demands. Key advancements include a sophisticated chiplet design, allowing for unprecedented transistor density and specialized processing units. The new generation of Tensor Cores provides enhanced precision and throughput for complex AI calculations. Furthermore, advancements in NVLink technology ensure ultra-fast interconnects between GPUs, critical for scaling large AI models. Performance benchmarks showcased at GTC 2024 indicate substantial gains in both raw compute power and energy efficiency for AI training workloads. Early tests suggest up to a 4x improvement in training performance for certain large language models compared to the H100.

The memory subsystem has also seen a massive overhaul. With significantly increased high-bandwidth memory (HBM) capacity and throughput, the Blackwell B200 can handle much larger datasets and models directly in memory, drastically reducing I/O bottlenecks. This is crucial for the next wave of generative AI and complex scientific simulations.

### Performance Benchmarks and Comparisons

The NVIDIA Blackwell B200 GPU demonstrates staggering performance gains. Compared to its predecessor, the Hopper H100, the B200 offers:
- Up to **2.5x** the TFLOPs in FP8 precision for AI inference.
- Up to **5x** faster performance for certain LLM training scenarios.
- Significant improvements in energy efficiency, crucial for large-scale data centers.

When benchmarked against the Hopper H200, the Blackwell B200 still shows considerable advantages, particularly in multi-GPU configurations thanks to its enhanced NVLink and NVSwitch capabilities. These benchmarks solidify NVIDIA's leadership in AI chip performance.

### Market Impact and Future Outlook for AI Supercomputing

The introduction of the NVIDIA Blackwell B200 is poised to send ripples across the entire tech industry. Cloud service providers like AWS, Google Cloud, and Microsoft Azure are expected to be among the first adopters, eager to offer its unparalleled performance to their enterprise AI customers. This will likely accelerate research and development in fields ranging from drug discovery and climate modeling to autonomous vehicles and robotics.

The competitive landscape for AI accelerators is fierce, but the Blackwell B200 reinforces NVIDIA's dominant position. While competitors are making strides, the sheer scale of performance uplift and the mature CUDA ecosystem present a formidable challenge. Looking ahead, the B200 platform will likely become the backbone for breakthroughs in general artificial intelligence and more demanding deep learning hardware applications.

### Conclusion: Blackwell's Transformative Potential

In summary, the NVIDIA Blackwell B200 GPU represents more than just an incremental update; it's a landmark achievement in AI hardware. Its cutting-edge architecture, impressive benchmarks, and staggering performance capabilities are set to unlock new frontiers in artificial intelligence, powering the innovations that will shape our future. The era of AI supercomputing has truly arrived with Blackwell.
"""
    }

    logger.info("\n--- Testing SEO Review Agent with detailed sample data ---")
    result = run_seo_review_agent(test_article_data.copy())

    logger.info(f"\n--- SEO Review Agent Test Results (Standalone) ---")
    seo_results_output = result.get('seo_review_results', {})
    
    if seo_results_output.get('error'):
        logger.error(f"Error during review: {seo_results_output['error']}")
        if "raw_response_snippet" in seo_results_output:
            logger.error(f"Raw response snippet: {seo_results_output['raw_response_snippet']}")
    else:
        logger.info(f"Overall SEO Score: {seo_results_output.get('overall_seo_score')}")
        logger.info(f"Review Summary: {seo_results_output.get('seo_review_summary')}")
        
        primary_kw_check = seo_results_output.get('keyword_analysis', {}).get('primary_keyword_check', {})
        logger.info(f"Primary Keyword ('{primary_kw_check.get('keyword')}') Check:")
        logger.info(f"  In Title Tag: {primary_kw_check.get('present_in_title_tag')}")
        logger.info(f"  In H1: {primary_kw_check.get('present_in_h1')}")
        logger.info(f"  In Meta Desc: {primary_kw_check.get('present_in_meta_description')}")
        logger.info(f"  Early in Body: {primary_kw_check.get('present_early_in_body')}")
        logger.info(f"  Density Assessment: {primary_kw_check.get('density_assessment')}")
        logger.info(f"  Notes: {primary_kw_check.get('notes')}")

        title_review = seo_results_output.get('title_tag_review', {})
        logger.info(f"Title Tag Review ('{title_review.get('text')}'):")
        logger.info(f"  Length OK: {title_review.get('length_ok')} (Chars: {title_review.get('length_char_count')})")
        logger.info(f"  Clarity/Persuasiveness Score: {title_review.get('clarity_persuasiveness_score')}")
        logger.info(f"  Suggestions: {title_review.get('suggestions')}")
        
        logger.info(f"Actionable Recommendations: {json.dumps(seo_results_output.get('actionable_recommendations'), indent=2)}")

    logger.info("--- SEO Review Agent Standalone Test Complete ---")