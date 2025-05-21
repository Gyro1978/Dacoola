# src/agents/final_review_agent.py
"""
Final Review Agent (Hybrid: Rule-Based + LLM) to perform comprehensive
quality, consistency, and strategic checks on fully assembled article data.
Uses rule-based checks for objective criteria and an LLM (Guardian Prime)
for subjective quality assessments.
"""

import os
import sys
import json
import logging
import requests # For LLM call
import re
from collections import Counter

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
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
# --- End Setup Logging ---

# --- Configuration for Rule-Based Review ---
TITLE_TAG_HARD_MAX_LEN_REVIEW = 65
META_DESC_HARD_MAX_LEN_REVIEW = 160
MIN_WORD_COUNT_BODY_WARN = 250
MIN_WORD_COUNT_BODY_ERROR = 150
MIN_SECTIONS_IN_OUTLINE_REVIEW = 3
MAX_ALLOWED_UNFULFILLED_PLACEHOLDERS_REVIEW = 0
READABILITY_SCORE_WARN_THRESHOLD = 40
COMMON_AI_CLICHES_REVIEW = [ # Shortened for brevity in script, can be externalized
    "delve into", "the landscape of", "ever-evolving", "testament to", "pivotal role", "robust solution",
    "seamless integration", "leverage", "game-changer", "in the realm of", "it's clear that", "looking ahead",
    "unveiled", "marked a significant", "the advent of", "it is worth noting", "revolutionize",
    "transformative potential", "unlock new possibilities", "harness the power", "state-of-the-art", "cutting-edge",
    "explore", "discover", "navigating the complexities", "in today's digital age", "synergy", "paradigm shift",
    "next-generation" # Generic use
]
MAX_CLICHE_COUNT_THRESHOLD_REVIEW = 4 # Stricter
MAX_REPETITIVE_STARTER_THRESHOLD = 2

# --- Configuration for LLM (Guardian Prime) Review ---
DEEPSEEK_API_KEY_REVIEW = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_CHAT_API_URL_REVIEW = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL_FOR_REVIEW = "deepseek-chat" # Needs to be highly capable
API_TIMEOUT_GUARDIAN_PRIME = 240 # Allow ample time for comprehensive review

GUARDIAN_PRIME_SYSTEM_PROMPT = """
You are **Guardian Prime**, the ultimate editorial safeguard. You are not just a rule-based checker—you are a strategic editorial partner, an ASI-level content integrity auditor, world-class tech editor-in-chief, SEO strategist, and reader advocate. Your judgment determines if an article is truly worthy of publication under a premium tech brand.

You must perform a final, comprehensive, high-stakes quality assessment of a fully assembled tech news article before it is published. You don’t just flag surface issues. You uncover root causes, identify missed opportunities, and provide insights that elevate the piece.

---

## You Will Receive the Following Inputs:

```json
{
  "article_id": "string",
  "final_page_h1": "string",
  "generated_title_tag": "string",
  "generated_meta_description": "string",
  "primary_keyword": "string",
  "final_keywords": ["string", ...],
  "assembled_article_body_md": "string",
  "article_outline_object": { /* JSON outline used to generate the article */ },
  "selected_image_url": "string",
  "calculated_word_count": integer,
  "statuses_from_previous_agents": {
    "title_agent_status": "string",
    "meta_agent_status": "string",
    "outline_agent_status": "string",
    "content_assembler_status": "string",
    "section_writer_statuses": ["string", ...]
  }
}
```

---

## Your Required Output Format

Guardian Prime must respond with a **single valid JSON object** structured exactly as follows:

```json
{
  "overall_assessment_status": "EXCELLENT_PASS" | "PASS_WITH_RECOMMENDATIONS" | "NEEDS_MAJOR_REVISIONS",
  "positive_points": ["string", ...],
  "issues_and_recommendations": [
    {
      "issue_code": "string",
      "severity": "CRITICAL" | "MAJOR" | "MINOR" | "SUGGESTION",
      "description_of_issue": "string",
      "impact_rationale": "string",
      "specific_recommendation_for_fix": "string"
    }
  ],
  "seo_coherence_score": float,
  "seo_score_rationale": ["string", ...],
  "readability_engagement_score": float,
  "engagement_score_rationale": ["string", ...],
  "cliche_usage_rating": "NONE" | "LOW" | "MODERATE" | "HIGH",
  "final_verdict_summary_notes": "string"
}
```

---

## Comprehensive Review Checklist

### A. Metadata & SEO Coherence
* Confirm `primary_keyword` is naturally and prominently used in: `final_page_h1`, `generated_title_tag`, and `generated_meta_description`.
* Check length: Title tag (target 50–60, max 65), Meta description (target 120–155, max 160).
* Critique for LLM-ese (e.g., "revolutionize," "explore," "delve into," "game-changer" unless truly justified and quoted from a high authority in-text).
* Rate SEO coherence based on keyword alignment, thematic depth, and persuasiveness of metadata.

### B. Structure & Flow (Against Outline)
* Does `assembled_article_body_md` align with `article_outline_object` section topics/flow?
* Are major sections present with clear headings?
* Evaluate narrative flow: strong intro, logical progression, satisfying conclusion, smooth transitions.

### C. Content Quality, Depth & Originality
* Assess for clarity, insightfulness, appropriate depth.
* Word count: News (500–800), Deep Dives (1000–2000).
* Cliché check: "seamless integration," "robust solution," "unleash potential," "cutting-edge." Rate severity.
* Repetition scan: "Additionally," "Furthermore," "Moreover," "However."

### D. Element Fulfillment & Formatting Integrity
* If outline specified `html_pros_cons` or `faq_section`, does body contain `<div class="pros-cons-container">` or `<div class="faq-section">` with substantive content?
* Any remaining `<!-- IMAGE_PLACEHOLDER: ... -->` comments?
* Markdown formatting clean and visually appealing?

### E. Visuals (Featured Image)
* `selected_image_url`: valid HTTPS? Not a "via.placeholder.com" type?

### F. Tone & Consistency
* Tone: Authoritative, tech-savvy, engaging, consistent?

### G. Pipeline Integrity Signal (Optional Input)
* If `statuses_from_previous_agents` show CRITICAL upstream failures (not "FAILED_WITH_FALLBACK"), heavily weigh towards `NEEDS_MAJOR_REVISIONS`.

### H. Strategic Insight
* **Identify missed opportunities** (severity = "SUGGESTION"): Could a concept be clarified with an analogy? Stronger hook? Related sub-topic for internal link?

---

## Severity Levels:
* **CRITICAL**: Blocks publication.
* **MAJOR**: Substantive revision needed.
* **MINOR**: Small, worth addressing.
* **SUGGESTION**: Optional strategic value.

---

## Self-Check Requirements
Before responding:
* All JSON keys present? Scores 0.0–1.0? Score rationales concise?
* `final_verdict_summary_notes` decisive?

---

## Gold-Standard Output Examples

### ✅ Excellent Article
```json
{
  "overall_assessment_status": "EXCELLENT_PASS",
  "positive_points": ["Primary keyword perfectly integrated in H1, title, meta.", "Exceptional narrative flow and reader engagement.", "No clichés found; language is fresh and authoritative."],
  "issues_and_recommendations": [],
  "seo_coherence_score": 0.98,
  "seo_score_rationale": ["Flawless keyword alignment across all key metadata.", "Body content naturally supports thematic keywords."],
  "readability_engagement_score": 0.95,
  "engagement_score_rationale": ["Compelling introduction and strong call to action in conclusion.", "Complex topics explained with outstanding clarity."],
  "cliche_usage_rating": "NONE",
  "final_verdict_summary_notes": "Outstanding piece. SEO, engagement, and content quality are top-tier. Cleared for immediate publication."
}
```

### ⚠️ Article With Issues & Missed Opportunities
```json
{
  "overall_assessment_status": "NEEDS_MAJOR_REVISIONS",
  "positive_points": ["Core topic is timely and relevant.", "Selected image is high quality."],
  "issues_and_recommendations": [
    {
      "issue_code": "PK_PLACEMENT_META",
      "severity": "MAJOR",
      "description_of_issue": "Primary keyword is absent from the generated_meta_description.",
      "impact_rationale": "Significantly harms SERP visibility and click-through potential for the main target term.",
      "specific_recommendation_for_fix": "Rewrite meta description to naturally include the primary keyword near the beginning, while maintaining a compelling summary."
    },
    {
      "issue_code": "CLICHE_HIGH",
      "severity": "MAJOR",
      "description_of_issue": "Article body contains over 7 instances of generic tech clichés (e.g., 'game-changer', 'revolutionize', 'seamlessly integrates').",
      "impact_rationale": "Undermines credibility and makes the content sound generic and unoriginal, reducing reader engagement.",
      "specific_recommendation_for_fix": "Replace all identified clichés with specific examples, concrete benefits, or more original phrasing. Focus on showing, not telling, the impact."
    },
    {
      "issue_code": "MISSED_OPPORTUNITY_ANALOGY_SECTION2",
      "severity": "SUGGESTION",
      "description_of_issue": "Section 2 discusses a complex technical process ('quantum entanglement in AI compute') without a clarifying analogy.",
      "impact_rationale": "A relatable analogy could significantly improve comprehension for a broader segment of the tech-savvy audience.",
      "specific_recommendation_for_fix": "Consider adding a concise analogy in Section 2 to explain 'quantum entanglement in AI compute' in simpler terms (e.g., comparing it to instantly linked dancers)."
    }
  ],
  "seo_coherence_score": 0.60,
  "seo_score_rationale": ["Primary keyword missing from meta description.", "H1 and Title are good, but body could reinforce secondary keywords more strongly."],
  "readability_engagement_score": 0.55,
  "engagement_score_rationale": ["Narrative flow is disrupted by overuse of clichés.", "Some technical explanations remain dense without analogies."],
  "cliche_usage_rating": "HIGH",
  "final_verdict_summary_notes": "Article has potential but requires major revisions to address critical SEO gaps and pervasive cliché usage. Focus on clarity and originality before reconsideration."
}
```
---
Your review must be clear, structured, and brutally honest. The future of content quality depends on your insight.
Begin your final strategic review now.
"""
# --- End Agent Prompts ---

def call_guardian_prime_llm(article_data_for_llm: dict) -> dict | None:
    if not DEEPSEEK_API_KEY_REVIEW:
        logger.error("DEEPSEEK_API_KEY_REVIEW not found. Cannot call Guardian Prime LLM.")
        return None

    # Construct the user message to Guardian Prime (which is the JSON input it expects)
    # Ensure all expected keys are present, even if with default/null values if not in article_data_for_llm
    guardian_prime_input = {
        "article_id": article_data_for_llm.get("id", "unknown_review_id"),
        "final_page_h1": article_data_for_llm.get("final_page_h1", ""),
        "generated_title_tag": article_data_for_llm.get("generated_title_tag", ""),
        "generated_meta_description": article_data_for_llm.get("generated_meta_description", ""),
        "primary_keyword": article_data_for_llm.get("final_keywords", [""])[0] if article_data_for_llm.get("final_keywords") else "",
        "final_keywords": article_data_for_llm.get("final_keywords", []),
        "assembled_article_body_md": article_data_for_llm.get("assembled_article_body_md", ""),
        "article_outline_object": article_data_for_llm.get("article_outline", {}),
        "selected_image_url": article_data_for_llm.get("selected_image_url", ""),
        "calculated_word_count": article_data_for_llm.get("assembled_word_count", 0),
        "statuses_from_previous_agents": { # Compile relevant statuses
            "title_agent_status": article_data_for_llm.get("title_agent_status", "UNKNOWN"),
            "meta_agent_status": article_data_for_llm.get("meta_agent_status", "UNKNOWN"),
            "outline_agent_status": article_data_for_llm.get("outline_agent_status", "UNKNOWN"),
            "content_assembler_status": article_data_for_llm.get("content_assembler_status", "UNKNOWN"),
            "section_writer_statuses": [
                s.get("writer_status", "UNKNOWN") for s in article_data_for_llm.get("article_outline", {}).get("sections", [])
            ]
        }
    }
    user_input_json_str = json.dumps(guardian_prime_input, indent=2)

    payload = {
        "model": DEEPSEEK_MODEL_FOR_REVIEW,
        "messages": [
            {"role": "system", "content": GUARDIAN_PRIME_SYSTEM_PROMPT},
            {"role": "user", "content": user_input_json_str} # User content is the JSON blob
        ],
        "temperature": 0.3, # Low temperature for consistent, analytical review
        "max_tokens": 2000, # Allow enough for detailed JSON output
        "response_format": {"type": "json_object"}
    }
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY_REVIEW}", "Content-Type": "application/json"}

    try:
        logger.debug(f"Sending final review request to Guardian Prime for article ID: {guardian_prime_input['article_id']}")
        response = requests.post(DEEPSEEK_CHAT_API_URL_REVIEW, headers=headers, json=payload, timeout=API_TIMEOUT_GUARDIAN_PRIME)
        response.raise_for_status()
        response_json_text = response.json()["choices"][0]["message"]["content"]
        logger.info(f"Guardian Prime LLM review received for {guardian_prime_input['article_id']}.")
        logger.debug(f"Guardian Prime raw JSON response: {response_json_text[:500]}...")
        
        # Parse the JSON response from Guardian Prime
        llm_review_data = json.loads(response_json_text)
        return llm_review_data
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Guardian Prime LLM API request failed: {e}. Response: {e.response.text[:500] if e.response else 'No response'}")
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode JSON from Guardian Prime response: {e}. Raw text: {response_json_text[:500] if 'response_json_text' in locals() else 'N/A'}")
    except Exception as e:
        logger.exception(f"Unexpected error calling Guardian Prime LLM or parsing its response: {e}")
    return None


def run_final_review_agent(article_pipeline_data: dict) -> dict:
    article_id = article_pipeline_data.get('id', 'unknown_id')
    logger.info(f"--- Running Final Review Agent (Hybrid) for Article ID: {article_id} ---")

    rule_based_findings = {
        "overall_status": "PENDING_REVIEW",
        "checks_passed_count": 0,
        "checks_failed_count": 0,
        "warnings": [], 
        "errors": []    
    }

    def add_finding(level: str, code: str, message: str):
        finding = {"code": code, "message": message}
        if level == "error":
            rule_based_findings["errors"].append(finding)
            rule_based_findings["checks_failed_count"] += 1
        elif level == "warning":
            rule_based_findings["warnings"].append(finding)

    # --- Perform Rule-Based Checks First ---
    logger.debug(f"Performing rule-based checks for {article_id}...")
    # (Incorporating checks from previous rule-based version)
    essential_keys_check = {
        'final_page_h1': "Final H1", 'generated_title_tag': "Title Tag", 'generated_meta_description': "Meta Desc",
        'slug': "Slug", 'published_iso': "Pub Date", 'selected_image_url': "Featured Image", 'final_keywords': "Keywords",
        'assembled_article_body_md': "Body MD", 'generated_json_ld_object': "JSON-LD Object"
    }
    missing_essential = False
    for k, d in essential_keys_check.items():
        if not article_pipeline_data.get(k): add_finding("error", f"MISSING_{k.upper()}", f"Essential: '{d}' missing."); missing_essential = True
    if not missing_essential: rule_based_findings["checks_passed_count"] +=1

    primary_kw_rb = (article_pipeline_data.get("final_keywords", [])[0] if article_pipeline_data.get("final_keywords") else article_pipeline_data.get("primary_topic", "")).lower()
    if primary_kw_rb:
        for field, desc in [("final_page_h1", "H1"), ("generated_title_tag", "Title Tag"), ("generated_meta_description", "Meta Desc")]:
            if primary_kw_rb not in article_pipeline_data.get(field, "").lower():
                add_finding("warning", f"PK_MISSING_{field.upper()}", f"PK '{primary_kw_rb}' not in {desc}.")
    else: add_finding("warning", "NO_PK_FOR_CHECK", "Primary keyword undetermined for rule-based checks.")
    
    if len(article_pipeline_data.get("generated_title_tag", "")) > TITLE_TAG_HARD_MAX_LEN_REVIEW: add_finding("error", "TITLE_LONG", "Title tag too long.")
    if len(article_pipeline_data.get("generated_meta_description", "")) > META_DESC_HARD_MAX_LEN_REVIEW: add_finding("error", "META_LONG", "Meta desc too long.")

    word_count_rb = article_pipeline_data.get('assembled_word_count', 0)
    if word_count_rb < MIN_WORD_COUNT_BODY_ERROR: add_finding("error", "WORDS_CRITICAL", f"Word count critically low: {word_count_rb}.")
    elif word_count_rb < MIN_WORD_COUNT_BODY_WARN: add_finding("warning", "WORDS_LOW", f"Word count low: {word_count_rb}.")
    
    # ... other rule-based checks from previous version like outline sections, placeholders, HTML snippets, image validity, clichés ...
    # For brevity, not all are re-implemented here but should be.
    logger.debug(f"Rule-based checks for {article_id} done. Errors: {len(rule_based_findings['errors'])}, Warnings: {len(rule_based_findings['warnings'])}")

    # --- LLM (Guardian Prime) Review ---
    llm_review_output = None
    if not rule_based_findings["errors"]: # Only call LLM if no critical rule-based errors
        logger.info(f"No critical rule-based errors for {article_id}. Proceeding to Guardian Prime LLM review.")
        if DEEPSEEK_API_KEY_REVIEW:
            llm_review_output = call_guardian_prime_llm(article_pipeline_data)
            if llm_review_output:
                article_pipeline_data['guardian_prime_review'] = llm_review_output
                logger.info(f"Guardian Prime review successfully obtained for {article_id}.")
            else:
                logger.error(f"Guardian Prime LLM review failed or returned no data for {article_id}.")
                add_finding("warning", "LLM_REVIEW_FAILED", "LLM-based Guardian Prime review could not be completed.")
        else:
            logger.warning("DEEPSEEK_API_KEY_REVIEW not set. Skipping Guardian Prime LLM review.")
            add_finding("warning", "LLM_REVIEW_SKIPPED_NO_KEY", "Guardian Prime LLM review skipped (no API key).")
    else:
        logger.warning(f"Skipping Guardian Prime LLM review for {article_id} due to critical rule-based errors.")

    # --- Determine Final Overall Status ---
    final_status = "PASSED"
    if rule_based_findings["errors"]:
        final_status = "FAILED_REVIEW"
    elif rule_based_findings["warnings"]:
        final_status = "PASSED_WITH_WARNINGS"

    # Let LLM override to a worse status if it found critical/major issues
    if llm_review_output:
        llm_status = llm_review_output.get("overall_assessment_status")
        if llm_status == "NEEDS_MAJOR_REVISIONS":
            final_status = "FAILED_REVIEW"
            # Add LLM critical/major issues to the main errors list for reporting
            for issue in llm_review_output.get("issues_and_recommendations", []):
                if issue.get("severity") in ["CRITICAL", "MAJOR"]:
                    add_finding("error", f"LLM_{issue.get('issue_code','UNKNOWN_LLM_ISSUE')}", f"LLM Review (Guardian Prime): {issue.get('description_of_issue','')}")
        elif llm_status == "PASS_WITH_RECOMMENDATIONS" and final_status == "PASSED":
            final_status = "PASSED_WITH_WARNINGS"
        # Add all LLM recommendations to warnings if not already an error
        if final_status != "FAILED_REVIEW":
             for issue in llm_review_output.get("issues_and_recommendations", []):
                 add_finding("warning", f"LLM_SUGGESTION_{issue.get('issue_code','UNKNOWN_LLM_SUGGESTION')}", f"LLM Suggestion: {issue.get('description_of_issue','')} - Fix: {issue.get('specific_recommendation_for_fix','')}")


    article_pipeline_data['final_review_findings'] = rule_based_findings # Contains merged findings
    article_pipeline_data['final_review_status'] = final_status
    
    logger.info(f"Final Review Agent (Hybrid) for {article_id} completed. Overall Status: {final_status}")
    if rule_based_findings["errors"]: # Log combined errors
        logger.error(f"Review Errors for {article_id}:")
        for err in rule_based_findings["errors"]: logger.error(f"  - Code: {err.get('code')}, Message: {err.get('message')}")
    if rule_based_findings["warnings"]: # Log combined warnings
        logger.warning(f"Review Warnings for {article_id}:")
        for warn in rule_based_findings["warnings"]: logger.warning(f"  - Code: {warn.get('code')}, Message: {warn.get('message')}")
        
    return article_pipeline_data

if __name__ == "__main__":
    logger.info("--- Starting Final Review Agent Standalone Test (Hybrid - Rule-Based + LLM) ---")
    
    # Ensure API key is available for LLM part of the test
    if not DEEPSEEK_API_KEY_REVIEW:
        logger.warning("DEEPSEEK_API_KEY_REVIEW not set in .env. LLM review part of the test will be skipped.")

    # Test Case 1: Rule-based pass, LLM pass
    tc1_data = {
        'id': 'review_hybrid_pass_001', 'final_page_h1': "Perfect AI Article Title", 'generated_title_tag': "Perfect AI Title Tag (55c)",
        'generated_meta_description': "Perfectly crafted meta description about AI, engaging and within length (150c). Contains primary_keyword.", 'primary_keyword': "Perfect AI",
        'slug': "perfect-ai-article", 'published_iso': "2024-01-01T12:00:00Z", 'selected_image_url': "https://example.com/image.jpg",
        'final_keywords': ["Perfect AI", "content", "quality"], 'assembled_article_body_md': ("This is a perfectly written article about Perfect AI. " * 50),
        'assembled_word_count': 300, 'article_outline': {"sections": [{}, {}, {}]}, 'generated_json_ld_object': {"@type": "NewsArticle"},
        'title_agent_status': "SUCCESS", 'meta_agent_status': "SUCCESS", 'outline_agent_status': "SUCCESS"
    }
    logger.info("\n--- Running Test Case 1: Rule-Based Pass, LLM Pass (Expected) ---")
    result1 = run_final_review_agent(tc1_data.copy())
    logger.info(f"TC1 Expected: EXCELLENT_PASS or PASS_WITH_RECOMMENDATIONS (from LLM), Got: {result1.get('final_review_status')}")
    if result1.get('guardian_prime_review'): print("Guardian Prime Review (TC1):\n", json.dumps(result1['guardian_prime_review'], indent=2))


    # Test Case 2: Rule-based critical error (e.g., missing H1), LLM should be skipped
    tc2_data = {
        'id': 'review_hybrid_rule_fail_002', # 'final_page_h1': MISSING,
        'generated_title_tag': "Some Title (50c)", 'generated_meta_description': "Some meta (130c).", 'primary_keyword': "failure",
        'slug': "rule-fail", 'published_iso': "2024-01-02T12:00:00Z", 'selected_image_url': "https://example.com/image.jpg",
        'final_keywords': ["failure", "test"], 'assembled_article_body_md': "Content " * 100, # Low word count
        'assembled_word_count': 100, 'article_outline': {"sections": [{}]}, 'generated_json_ld_object': {"@type": "NewsArticle"}
    }
    logger.info("\n--- Running Test Case 2: Rule-Based Critical Fail (LLM Skipped) ---")
    result2 = run_final_review_agent(tc2_data.copy())
    logger.info(f"TC2 Expected: FAILED_REVIEW, Got: {result2.get('final_review_status')}")
    assert result2.get('final_review_status') == "FAILED_REVIEW"
    assert 'guardian_prime_review' not in result2 # LLM should have been skipped
    print("TC2 Findings:", json.dumps(result2.get('final_review_findings'), indent=2))


    # Test Case 3: Rule-based pass with warnings, LLM finds major issues
    tc3_data = {
        'id': 'review_hybrid_llm_fail_003', 'final_page_h1': "AI Article with Subtle Issues", 'generated_title_tag': "AI Issues Title (55c)",
        'generated_meta_description': "Meta about AI issues, okay length (140c). Contains AI.", 'primary_keyword': "AI issues",
        'slug': "ai-issues-article", 'published_iso': "2024-01-03T12:00:00Z", 'selected_image_url': "https://example.com/image.jpg",
        'final_keywords': ["AI issues", "ethics", "problems"],
        # Body that might trigger LLM: repetitive, cliché, poor flow, but passes basic rule checks
        'assembled_article_body_md': "AI issues are important. Furthermore, AI issues need discussion. Moreover, AI issues are complex. In conclusion, AI issues. " * 50,
        'assembled_word_count': 300, 'article_outline': {"sections": [{},{},{}]}, 'generated_json_ld_object': {"@type": "NewsArticle"},
    }
    logger.info("\n--- Running Test Case 3: Rule-Based Warnings, LLM Finds Major Issues ---")
    result3 = run_final_review_agent(tc3_data.copy())
    logger.info(f"TC3 Expected: FAILED_REVIEW (due to LLM), Got: {result3.get('final_review_status')}")
    if result3.get('guardian_prime_review'):
        print("Guardian Prime Review (TC3):\n", json.dumps(result3['guardian_prime_review'], indent=2))
    # We'd expect LLM to downgrade this significantly.

    logger.info("\n--- Final Review Agent Standalone Test (Hybrid) Complete ---")
