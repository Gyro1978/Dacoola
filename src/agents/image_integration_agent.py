# src/agents/image_integration_agent.py
"""
Image Integration Agent - ASI-Level Refined
Replaces placeholders in Markdown with image tags and captions,
with enhanced context-aware placement and robust matching.
"""

import os
import sys
import logging
import re
import string # For punctuation stripping
import json 

# --- Path Setup ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
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

# --- Configuration ---
ENABLE_FUZZY_PLACEHOLDER_MATCHING = True
MAX_CAPTION_LENGTH = 250
IMAGE_CAPTION_STYLE = os.getenv("IMAGE_CAPTION_STYLE", "markdown_italic") 
ALLOW_CANDIDATE_REUSE_FOR_DUPLICATE_PLACEHOLDERS = True 
MAX_REUSE_COUNT_PER_CANDIDATE = 2 

def get_caption_markdown(caption_text):
    if not caption_text: return ""
    caption_text = caption_text.strip()
    if IMAGE_CAPTION_STYLE == "markdown_italic":
        return f"*{caption_text}*" 
    elif IMAGE_CAPTION_STYLE == "html_figcaption":
        return f"<figcaption>{caption_text}</figcaption>"
    elif IMAGE_CAPTION_STYLE == "plain":
        return caption_text
    return f"*{caption_text}*" 

def normalize_placeholder_text_enhanced(text: str | None) -> str:
    if not text: return ""
    text = text.strip().lower()
    text = text.translate(str.maketrans('', '', string.punctuation))
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def get_alnum_key(text: str | None) -> str: 
    if not text: return ""
    return re.sub(r'[^a-z0-9]', '', text.lower())


def run_image_integration_agent(article_pipeline_data: dict) -> dict:
    article_id = article_pipeline_data.get('id', 'unknown_id')
    logger.info(f"--- Running Image Integration Agent for Article ID: {article_id} (ASI-Refined Logic v10) ---")

    integration_log = []
    structured_integration_log = [] 
    article_pipeline_data['image_integration_status'] = "NO_ACTION_NEEDED"

    markdown_body_source_dict = article_pipeline_data.get('seo_agent_results', article_pipeline_data)
    markdown_body = markdown_body_source_dict.get('generated_article_body_md')

    if not markdown_body or not isinstance(markdown_body, str):
        logger.warning(f"No 'generated_article_body_md' for {article_id}. Skipping integration.")
        article_pipeline_data['image_integration_status'] = "SKIPPED_NO_MARKDOWN_BODY"
        article_pipeline_data['image_integration_log'] = ["No Markdown body to process."]
        article_pipeline_data['image_integration_log_structured'] = []
        return article_pipeline_data

    media_candidates = article_pipeline_data.get('media_candidates_for_body')
    if not media_candidates or not isinstance(media_candidates, list):
        media_candidates = []
    
    all_md_placeholders_data = []
    if markdown_body: 
        for match in re.finditer(r'<!--\s*IMAGE_PLACEHOLDER:\s*(.*?)\s*-->', markdown_body, re.IGNORECASE):
            all_md_placeholders_data.append({
                "original_text": match.group(0), 
                "description": match.group(1).strip(),
                "normalized_description_enhanced": normalize_placeholder_text_enhanced(match.group(1).strip()),
                "alnum_key": get_alnum_key(normalize_placeholder_text_enhanced(match.group(1).strip()))
            })
    
    unique_md_placeholder_descs_count = len(set(ph['description'] for ph in all_md_placeholders_data))

    if not media_candidates:
        logger.info(f"No media candidates for {article_id}. No in-article images to integrate.")
        if unique_md_placeholder_descs_count > 0:
            logger.warning(f"Markdown for {article_id} has {unique_md_placeholder_descs_count} unique placeholders, but no media candidates.")
            first_desc_example = next((ph['description'] for ph in all_md_placeholders_data), "N/A")[:60]
            article_pipeline_data['image_integration_status'] = "WARNING_PLACEHOLDERS_NO_CANDIDATES"
            integration_log.append(f"Markdown has placeholders (e.g., '{first_desc_example}...'), but no images selected.")
        else:
            article_pipeline_data['image_integration_status'] = "NO_PLACEHOLDERS_AND_NO_CANDIDATES"
        article_pipeline_data['image_integration_log'] = integration_log
        article_pipeline_data['image_integration_log_structured'] = []
        return article_pipeline_data

    logger.info(f"Processing {len(media_candidates)} media candidates for {article_id} against {unique_md_placeholder_descs_count} unique placeholder descriptions in Markdown.")
    
    integrations_done = 0
    candidate_use_counts = {} 
    exact_matches_count = 0
    fuzzy_matches_count = 0
    
    normalized_media_candidates = []
    for idx, mc in enumerate(media_candidates): 
        orig_desc = mc.get('placeholder_description_original')
        normalized_media_candidates.append({
            **mc,
            "original_candidate_index": idx, 
            "normalized_description_enhanced": normalize_placeholder_text_enhanced(orig_desc),
            "alnum_key": get_alnum_key(normalize_placeholder_text_enhanced(orig_desc))
        })

    original_markdown_lines = markdown_body.splitlines(keepends=True)
    new_markdown_lines = list(original_markdown_lines) 

    for line_idx, line_content_orig in enumerate(original_markdown_lines):
        line_content = new_markdown_lines[line_idx] 
        
        placeholder_matches_on_line = list(re.finditer(r'(<!--\s*IMAGE_PLACEHOLDER:\s*(.*?)\s*-->)', line_content, re.IGNORECASE))

        if not placeholder_matches_on_line:
            continue
        
        placeholder_match_obj = placeholder_matches_on_line[0]
        
        full_placeholder_comment = placeholder_match_obj.group(1) 
        current_md_placeholder_desc = placeholder_match_obj.group(2).strip() 
        
        normalized_md_ph_desc_enhanced = normalize_placeholder_text_enhanced(current_md_placeholder_desc)
        alnum_md_ph_key = get_alnum_key(normalized_md_ph_desc_enhanced)
        
        logger.debug(f"Found placeholder on line {line_idx + 1}: '{current_md_placeholder_desc[:60]}...' (Normalized: '{normalized_md_ph_desc_enhanced[:60]}...')")

        best_candidate_info = None; best_candidate_original_idx = -1; match_type = None
        
        def check_candidate_usability(cand_idx_norm_local, original_idx_cand_local): 
            if not ALLOW_CANDIDATE_REUSE_FOR_DUPLICATE_PLACEHOLDERS and original_idx_cand_local in candidate_use_counts:
                return False
            if original_idx_cand_local in candidate_use_counts and candidate_use_counts[original_idx_cand_local] >= MAX_REUSE_COUNT_PER_CANDIDATE:
                return False
            return True

        for cand_idx_norm, candidate_info in enumerate(normalized_media_candidates):
            original_idx_cand = candidate_info["original_candidate_index"] 
            if not check_candidate_usability(cand_idx_norm, original_idx_cand): continue
            if candidate_info["normalized_description_enhanced"] == normalized_md_ph_desc_enhanced:
                best_candidate_info = candidate_info; best_candidate_original_idx = original_idx_cand; match_type="exact_enhanced"; break
        
        if not best_candidate_info and ENABLE_FUZZY_PLACEHOLDER_MATCHING:
            for cand_idx_norm, candidate_info in enumerate(normalized_media_candidates):
                original_idx_cand = candidate_info["original_candidate_index"] 
                if not check_candidate_usability(cand_idx_norm, original_idx_cand): continue
                if alnum_md_ph_key and candidate_info["alnum_key"] == alnum_md_ph_key: 
                    best_candidate_info = candidate_info; best_candidate_original_idx = original_idx_cand; match_type="fuzzy_alnum"; break
        
        if best_candidate_info:
            is_reused = best_candidate_original_idx in candidate_use_counts
            candidate_use_counts[best_candidate_original_idx] = candidate_use_counts.get(best_candidate_original_idx, 0) + 1
            
            if match_type == "exact_enhanced": exact_matches_count +=1
            elif match_type == "fuzzy_alnum": fuzzy_matches_count +=1
            
            image_url = best_candidate_info.get('best_image_url')
            alt_text = best_candidate_info.get('alt_text', f"Image: {current_md_placeholder_desc[:50]}")
            vlm_caption = best_candidate_info.get('vlm_image_description', '')

            if not image_url:
                log_msg_skip = f"Matched candidate for '{current_md_placeholder_desc[:60]}' has no image URL."; integration_log.append(log_msg_skip); logger.warning(f"For {article_id}: {log_msg_skip}"); continue

            safe_alt_text = alt_text.replace('"', "'").replace('[','(').replace(']',')').strip()
            image_markdown_tag = f"![{safe_alt_text}]({image_url})"
            caption_md_formatted = ""
            if vlm_caption and isinstance(vlm_caption, str) and len(vlm_caption.strip()) > 10 and \
               vlm_caption.strip().lower() not in ["n/a", "analysis n/a", "image selected based on search query match."] and \
               "placeholder" not in vlm_caption.lower() and "simulated" not in vlm_caption.lower():
                safe_caption_text = vlm_caption.strip().replace('\n', ' ')[:MAX_CAPTION_LENGTH]
                if safe_caption_text.lower() != safe_alt_text.lower() and safe_alt_text.lower() not in safe_caption_text.lower():
                    caption_md_formatted = get_caption_markdown(safe_caption_text).strip()
            
            is_standalone_placeholder_line = line_content.strip() == full_placeholder_comment
            leading_whitespace_match = re.match(r'^(\s*(?:[-*+>]\s*|\d+\.\s+)?)\s*', line_content)
            indentation_prefix = leading_whitespace_match.group(1) if leading_whitespace_match else ""

            if is_standalone_placeholder_line:
                # Corrected blockquote handling
                prefix_for_block = indentation_prefix.rstrip()
                if prefix_for_block.endswith(">") and not prefix_for_block.endswith(" "):
                     prefix_for_block += " " # Ensure "> " for blockquotes
                
                image_line = f"{prefix_for_block}{image_markdown_tag}"
                caption_line_str = f"{prefix_for_block}{caption_md_formatted}" if caption_md_formatted else ""
                
                new_line_content_str = "\n".join(filter(None, [image_line, caption_line_str]))
            else: 
                inline_parts = [image_markdown_tag]
                if caption_md_formatted:
                    inline_parts.append(f" {caption_md_formatted}") 
                
                inline_block_str = "".join(inline_parts)
                new_line_content_str = line_content.replace(full_placeholder_comment, inline_block_str, 1)

            if line_content_orig.endswith('\r\n'): 
                new_markdown_lines[line_idx] = new_line_content_str.rstrip('\n\r') + '\r\n'
            elif line_content_orig.endswith('\n'):
                new_markdown_lines[line_idx] = new_line_content_str.rstrip('\n\r') + '\n'
            else:
                new_markdown_lines[line_idx] = new_line_content_str.rstrip('\n\r')

            integrations_done += 1
            reuse_log_note = "(Reused)" if is_reused else ""
            log_msg_success = f"Integrated image '{image_url}' {reuse_log_note} (Match: {match_type}) on line ~{line_idx+1} for placeholder: '{current_md_placeholder_desc[:60]}...'"; 
            integration_log.append(log_msg_success); 
            logger.info(f"For {article_id}: {log_msg_success}")
            structured_integration_log.append({
                "placeholder_description": current_md_placeholder_desc,
                "line_number": line_idx + 1,
                "image_url": image_url,
                "alt_text": safe_alt_text,
                "caption_used": bool(caption_md_formatted),
                "caption_text": caption_md_formatted if caption_md_formatted else None,
                "match_type": match_type,
                "is_reused": is_reused
            })
        else:
            log_msg_notfound = f"No matching media candidate for placeholder on line ~{line_idx+1}: '{current_md_placeholder_desc[:60]}...'"; 
            integration_log.append(log_msg_notfound); 
            logger.warning(f"For {article_id}: {log_msg_notfound}")
            structured_integration_log.append({
                "placeholder_description": current_md_placeholder_desc,
                "line_number": line_idx + 1,
                "status": "unmatched"
            })


    final_markdown_body = "".join(new_markdown_lines)

    if 'generated_article_body_md' in article_pipeline_data.get('seo_agent_results', {}):
        article_pipeline_data['seo_agent_results']['generated_article_body_md'] = final_markdown_body
    else:
        article_pipeline_data['generated_article_body_md'] = final_markdown_body

    placeholders_remaining_count = len(re.findall(r'<!--\s*IMAGE_PLACEHOLDER:\s*.*?\s*-->', final_markdown_body, re.IGNORECASE))
    
    logger.info(f"Placeholder Matching Summary: Total unique detected: {unique_md_placeholder_descs_count}, Integrated: {integrations_done} (Exact: {exact_matches_count}, Fuzzy: {fuzzy_matches_count}), Remaining: {placeholders_remaining_count}")

    if integrations_done > 0:
        if placeholders_remaining_count > 0: article_pipeline_data['image_integration_status'] = f"SUCCESS_PARTIAL_{integrations_done}_IMAGES_{placeholders_remaining_count}_REMAIN"; 
        else: article_pipeline_data['image_integration_status'] = f"SUCCESS_INTEGRATED_{integrations_done}_IMAGES_ALL"; 
    elif unique_md_placeholder_descs_count > 0 : article_pipeline_data['image_integration_status'] = "NO_MATCHES_PH_EXIST"; integration_log.append("Placeholders found, but no integrations made.")
    else: article_pipeline_data['image_integration_status'] = "NO_PH_NO_INTEGRATIONS"
        
    if article_pipeline_data['image_integration_status'].startswith("SUCCESS_PARTIAL") or article_pipeline_data['image_integration_status'] == "NO_MATCHES_PH_EXIST":
        logger.warning(f"Image Integration Status for {article_id}: {article_pipeline_data['image_integration_status']}")
    else:
        logger.info(f"Image Integration Status for {article_id}: {article_pipeline_data['image_integration_status']}")

    article_pipeline_data['image_integration_log'] = integration_log
    article_pipeline_data['image_integration_log_structured'] = structured_integration_log
    logger.info(f"--- Image Integration Agent finished for {article_id}. ---")
    return article_pipeline_data

if __name__ == "__main__":
    logger.info("--- Starting Image Integration Agent Standalone Test (ASI-Refined Logic v10) ---") 
    sample_article_data_for_integration = {
        'id': 'test_img_integ_asi_001_v10', 
        'seo_agent_results': {
            'generated_article_body_md': """## Amazing New Gadget

This new gadget is revolutionary. Here's a look at its design.
<!-- IMAGE_PLACEHOLDER: A sleek product shot of the new gadget -->
It features advanced AI capabilities.

### Performance Metrics
The performance is off the charts.
- Point one.
  <!-- IMAGE_PLACEHOLDER: A graph showing benchmark scores of the gadget -->
- Point two with an inline <!-- IMAGE_PLACEHOLDER: Tiny icon representing speed --> placeholder.

> <!-- IMAGE_PLACEHOLDER: Quote background image of an abstract tech pattern -->
> This is a blockquote.

<!-- IMAGE_PLACEHOLDER: This placeholder has no matching candidate -->
Some other text here.
<!-- IMAGE_PLACEHOLDER: a sleek product shot of the new gadget -->
Another instance of the first placeholder.
<!-- IMAGE_PLACEHOLDER: complex item: flowchart of neural network -->
Test with punctuation & case: <!-- IMAGE_PLACEHOLDER: Complex Item, Flowchart of Neural Network... -->
"""
        },
        'media_candidates_for_body': [
            {'placeholder_id_ref': "ph1", 'placeholder_description_original': "A sleek product shot of the new gadget ", 'best_image_url': 'https://example.com/images/gadget_sleek.jpg', 'alt_text': 'Sleek new AI gadget', 'vlm_image_description': 'Detailed photo of the new AI-powered gadget in silver, on a white background.'},
            {'placeholder_id_ref': "ph2", 'placeholder_description_original': "A graph showing benchmark scores of the gadget", 'best_image_url': 'https://example.com/images/gadget_benchmarks.png', 'alt_text': 'Gadget benchmark performance graph', 'vlm_image_description': ''}, 
            {'placeholder_id_ref': "ph3", 'placeholder_description_original': "Quote background image of an abstract tech pattern", 'best_image_url': 'https://example.com/images/abstract_pattern.jpg', 'alt_text': 'Abstract technology pattern background', 'vlm_image_description': 'A mesmerizing blue and green abstract technological pattern.'},
            {'placeholder_id_ref': "ph4", 'placeholder_description_original': "Tiny icon representing speed", 'best_image_url': 'https://example.com/icons/speed_icon.svg', 'alt_text': 'Speed icon', 'vlm_image_description': 'A small icon depicting speed.'},
            {'placeholder_id_ref': "ph5", 'placeholder_description_original': "Complex Item: Flowchart of Neural Network!!!", 'best_image_url': 'https://example.com/images/nn_flowchart.jpg', 'alt_text': 'Neural Network Flowchart', 'vlm_image_description': 'A detailed flowchart of a neural network architecture.'}
        ]
    }
    result_data = run_image_integration_agent(sample_article_data_for_integration.copy())
    logger.info("\n--- Image Integration Test Results (ASI-Refined v10) ---")
    logger.info(f"Integration Status: {result_data.get('image_integration_status')}")
    logger.info("\nIntegration Log (Plain Text):"); [logger.info(f"  - {log_entry}") for log_entry in result_data.get('image_integration_log', [])]
    logger.info("\nIntegration Log (Structured JSON):")
    print(json.dumps(result_data.get('image_integration_log_structured', []), indent=2))
    
    final_md_body = result_data.get('seo_agent_results', {}).get('generated_article_body_md', "ERROR")
    logger.info("\n--- Final Markdown Body ---"); print(final_md_body)

    # --- Assertions for v10 ---
    normalized_final_md_body = final_md_body.replace('\r\n', '\n')

    assert "![Sleek new AI gadget](https://example.com/images/gadget_sleek.jpg)\n*Detailed photo of the new AI-powered gadget in silver, on a white background.*" in normalized_final_md_body
    
    expected_list_item_image_pattern = re.compile(
        r"-\s*Point one\.\s*\n" 
        r"\s*!\[Gadget benchmark performance graph\]\(https://example.com/images/gadget_benchmarks.png\)" 
    )
    assert expected_list_item_image_pattern.search(normalized_final_md_body), "List item image for 'A graph showing...' not formatted as expected."

    expected_inline_replacement_pattern = re.compile(
        r"- Point two with an inline !\[Speed icon\]\(https://example.com/icons/speed_icon.svg\) \**A small icon depicting speed\.\** placeholder\."
    )
    assert expected_inline_replacement_pattern.search(normalized_final_md_body), f"Inline replacement for 'Tiny icon' not as expected. Check output:\n{normalized_final_md_body}"

    # Updated blockquote assertion for v10
    expected_quote_image_pattern = re.compile(
        r">\s!\[Abstract technology pattern background\]\(https://example.com/images/abstract_pattern.jpg\)\n" 
        r">\s*\*A mesmerizing blue and green abstract technological pattern\.\*" 
    )
    assert expected_quote_image_pattern.search(normalized_final_md_body), f"Blockquoted image not formatted as expected. Actual:\n'''{normalized_final_md_body}'''"

    assert "<!-- IMAGE_PLACEHOLDER: This placeholder has no matching candidate -->" in normalized_final_md_body
    
    if ALLOW_CANDIDATE_REUSE_FOR_DUPLICATE_PLACEHOLDERS and MAX_REUSE_COUNT_PER_CANDIDATE >=2 :
        sleek_img_tag_count = normalized_final_md_body.count("![Sleek new AI gadget](https://example.com/images/gadget_sleek.jpg)")
        sleek_caption_count = normalized_final_md_body.count("*Detailed photo of the new AI-powered gadget in silver, on a white background.*")
        assert sleek_img_tag_count == 2, f"Expected reuse of 'Sleek new AI gadget' image tag did not occur or occurred incorrect number of times ({sleek_img_tag_count})."
        assert sleek_caption_count == 2, f"Expected reuse of 'Sleek new AI gadget' caption did not occur or occurred incorrect number of times ({sleek_caption_count})."
        assert normalized_final_md_body.count("<!-- IMAGE_PLACEHOLDER: a sleek product shot of the new gadget -->") == 0
    else:
        assert "<!-- IMAGE_PLACEHOLDER: a sleek product shot of the new gadget -->" in normalized_final_md_body, "Second instance of 'sleek product shot' should remain if reuse is off or limit hit."
    
    assert "![Neural Network Flowchart](https://example.com/images/nn_flowchart.jpg)\n*A detailed flowchart of a neural network architecture.*" in normalized_final_md_body
    assert "Test with punctuation & case: ![Neural Network Flowchart](https://example.com/images/nn_flowchart.jpg) *A detailed flowchart of a neural network architecture.*" in normalized_final_md_body

    logger.info("Standalone assertions passed for image integration (v10).")
    logger.info("--- Image Integration Agent Standalone Test Complete ---")