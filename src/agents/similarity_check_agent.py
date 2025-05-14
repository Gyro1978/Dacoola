# src/agents/similarity_check_agent.py

import os
import sys
import json
import logging
import glob
import numpy as np

# --- Path Setup ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
# --- End Path Setup ---

# --- Sentence Transformer Setup ---
SENTENCE_MODEL_NAME = 'all-MiniLM-L6-v2'
sentence_model = None
st_util = None # For sentence_transformers.util

try:
    from sentence_transformers import SentenceTransformer, util as sentence_transformers_util
    st_util = sentence_transformers_util
    # Model will be loaded lazily by _load_sentence_model()
    SENTENCE_MODEL_AVAILABLE = True
except ImportError:
    SENTENCE_MODEL_AVAILABLE = False
    logging.warning(
        f"sentence-transformers library not found. Text similarity checks will be basic (title match only). "
        f"Install with: pip install sentence-transformers"
    )
# --- End Sentence Transformer Setup ---

# --- Configuration ---
SIMILARITY_THRESHOLD = 0.90  # Cosine similarity threshold for "HIGHLY_SIMILAR"
EXACT_TITLE_SIMILARITY_THRESHOLD = 0.98 # If titles are extremely similar, content threshold might be lower
CONTENT_SIMILARITY_FOR_EXACT_TITLE = 0.80
MIN_CONTENT_LENGTH_FOR_EMBEDDING = 50 # Minimum characters to attempt embedding

# --- Setup Logging ---
logger = logging.getLogger(__name__)
if not logging.getLogger().hasHandlers():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

def _load_sentence_model():
    global sentence_model
    if not SENTENCE_MODEL_AVAILABLE:
        return False
    if sentence_model is None:
        try:
            logger.info(f"Loading sentence transformer model: {SENTENCE_MODEL_NAME}...")
            sentence_model = SentenceTransformer(SENTENCE_MODEL_NAME)
            logger.info("Sentence transformer model loaded successfully.")
            return True
        except Exception as e:
            logger.error(f"Failed to load sentence transformer model '{SENTENCE_MODEL_NAME}': {e}")
            return False
    return True

def _get_text_to_compare(article_data_dict):
    """Extracts relevant text for comparison from article data."""
    title = article_data_dict.get('title', '').strip()
    # Prefer 'content_for_processing', fallback to 'summary', then 'full_text_content'
    content = article_data_dict.get('content_for_processing', '') or \
              article_data_dict.get('summary', '') or \
              article_data_dict.get('full_text_content', '')
    content = content.strip()

    # Concatenate title and content for a more comprehensive comparison string
    # Give title more weight by repeating it or placing it strategically if desired (simple concat for now)
    combined_text = f"{title}. {content}"
    return title, combined_text


def run_similarity_check_agent(current_article_data, processed_json_dir, current_run_processed_articles_data_list=None):
    """
    Checks if the current article is too similar to previously processed articles or those in the current run.

    Args:
        current_article_data (dict): The article data to check.
        processed_json_dir (str): Path to the directory containing historical processed JSON files.
        current_run_processed_articles_data_list (list, optional): List of full article data dicts
                                                                  processed earlier in the same run. Defaults to None.

    Returns:
        dict: The current_article_data, updated with 'similarity_verdict' and 'similar_article_id'.
    """
    article_id = current_article_data.get('id', 'N/A')
    current_title, current_text_for_comparison = _get_text_to_compare(current_article_data)

    if not current_title and not current_text_for_comparison:
        logger.warning(f"Article {article_id} has no title or content for similarity check. Marking as OKAY.")
        current_article_data['similarity_verdict'] = "OKAY_NO_CONTENT"
        return current_article_data

    # Attempt to load sentence model if available and not already loaded
    model_loaded_successfully = _load_sentence_model() if SENTENCE_MODEL_AVAILABLE and sentence_model is None else (sentence_model is not None)

    current_embedding = None
    if model_loaded_successfully and len(current_text_for_comparison) >= MIN_CONTENT_LENGTH_FOR_EMBEDDING:
        try:
            current_embedding = sentence_model.encode(current_text_for_comparison, convert_to_tensor=True)
        except Exception as e:
            logger.error(f"Error encoding current article {article_id} text: {e}")
            model_loaded_successfully = False # Fallback to basic check for this article

    comparison_sources = []
    # 1. Articles processed earlier in the current run
    if current_run_processed_articles_data_list:
        for prev_article_data in current_run_processed_articles_data_list:
            if prev_article_data.get('id') != article_id : # Don't compare to self if somehow in list
                 comparison_sources.append(prev_article_data)

    # 2. Historically processed articles from PROCESSED_JSON_DIR
    # Avoid re-reading files if their data is already in current_run_processed_articles_data_list
    current_run_ids = {art.get('id') for art in (current_run_processed_articles_data_list or [])}
    
    historical_files = glob.glob(os.path.join(processed_json_dir, '*.json'))
    for f_path in historical_files:
        hist_article_id = os.path.basename(f_path).replace('.json', '')
        if hist_article_id == article_id or hist_article_id in current_run_ids:
            continue # Skip self or already considered from current run
        try:
            with open(f_path, 'r', encoding='utf-8') as f:
                historical_article_data = json.load(f)
            if historical_article_data.get('id'): # Basic check
                comparison_sources.append(historical_article_data)
        except Exception as e:
            logger.warning(f"Could not load or parse historical JSON {f_path} for similarity: {e}")

    if not comparison_sources:
        logger.info(f"No historical or current-run articles to compare against for {article_id}. Marking as OKAY.")
        current_article_data['similarity_verdict'] = "OKAY_NO_COMPARISON_DATA"
        return current_article_data

    logger.info(f"Checking similarity for article {article_id} ('{current_title[:50]}...') against {len(comparison_sources)} other articles.")

    for comp_article_data in comparison_sources:
        comp_article_id = comp_article_data.get('id')
        comp_title, comp_text_for_comparison = _get_text_to_compare(comp_article_data)

        # Basic check: Exact or very similar title (case-insensitive)
        # This is a quick check before potentially expensive embedding
        is_title_very_similar = False
        if current_title.lower() == comp_title.lower():
            is_title_very_similar = True
            logger.info(f"Article {article_id} has EXACT title match with {comp_article_id}.")
        elif model_loaded_successfully and len(current_title) >= MIN_CONTENT_LENGTH_FOR_EMBEDDING and len(comp_title) >= MIN_CONTENT_LENGTH_FOR_EMBEDDING:
            # If titles are not exact, check their embedding similarity
            try:
                title_embeddings = sentence_model.encode([current_title, comp_title], convert_to_tensor=True)
                title_sim_score = st_util.pytorch_cos_sim(title_embeddings[0], title_embeddings[1]).item()
                if title_sim_score >= EXACT_TITLE_SIMILARITY_THRESHOLD:
                    is_title_very_similar = True
                    logger.info(f"Article {article_id} title similarity with {comp_article_id} is {title_sim_score:.4f} (>= {EXACT_TITLE_SIMILARITY_THRESHOLD}).")
            except Exception as e:
                logger.warning(f"Error encoding titles for {article_id} vs {comp_article_id}: {e}")


        # Semantic similarity check for content if sentence model is available
        if model_loaded_successfully and current_embedding is not None and len(comp_text_for_comparison) >= MIN_CONTENT_LENGTH_FOR_EMBEDDING:
            try:
                comp_embedding = sentence_model.encode(comp_text_for_comparison, convert_to_tensor=True)
                content_sim_score = st_util.pytorch_cos_sim(current_embedding, comp_embedding).item()

                threshold_to_use = SIMILARITY_THRESHOLD
                if is_title_very_similar:
                    threshold_to_use = CONTENT_SIMILARITY_FOR_EXACT_TITLE
                    logger.debug(f"Using lower content similarity threshold ({threshold_to_use}) due to very similar titles.")

                if content_sim_score >= threshold_to_use:
                    verdict = "DUPLICATE_SEMANTIC" if is_title_very_similar else "HIGHLY_SIMILAR_CONTENT"
                    logger.warning(
                        f"Article {article_id} ('{current_title[:30]}...') is {verdict} to "
                        f"{comp_article_id} ('{comp_title[:30]}...'). "
                        f"Content Similarity: {content_sim_score:.4f} (Threshold: {threshold_to_use:.2f})"
                    )
                    current_article_data['similarity_verdict'] = verdict
                    current_article_data['similar_article_id'] = comp_article_id
                    current_article_data['similarity_score'] = content_sim_score
                    return current_article_data
            except Exception as e:
                logger.error(f"Error calculating content similarity between {article_id} and {comp_article_id}: {e}")
                # Fallback to only title check if embedding fails for comparison article

        # If content similarity check wasn't performed (e.g. model failed, short content) but titles were exact matches
        elif is_title_very_similar: # and content check didn't run or didn't find similarity above its threshold
            # This path is usually for when content sim is below CONTENT_SIMILARITY_FOR_EXACT_TITLE
            # or if one of the contents was too short for embedding.
            # An exact title match is a strong signal. For now, we let the content similarity be the decider
            # if embeddings were possible. If embeddings were *not* possible (e.g. short content for one),
            # an exact title match might be enough to flag as duplicate.
            # Let's refine: if titles are exact and content check could not be performed reliably, consider it a duplicate.
            if not model_loaded_successfully or current_embedding is None or len(comp_text_for_comparison) < MIN_CONTENT_LENGTH_FOR_EMBEDDING:
                logger.warning(
                    f"Article {article_id} ('{current_title[:30]}...') has EXACT title match with "
                    f"{comp_article_id} ('{comp_title[:30]}...') and full content similarity check was not conclusive/possible. "
                    f"Marking as DUPLICATE_BY_TITLE."
                )
                current_article_data['similarity_verdict'] = "DUPLICATE_BY_TITLE_ONLY"
                current_article_data['similar_article_id'] = comp_article_id
                current_article_data['similarity_score'] = 1.0 # For title
                return current_article_data


    logger.info(f"Article {article_id} passed similarity checks.")
    current_article_data['similarity_verdict'] = "OKAY"
    return current_article_data


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG) # Enable DEBUG for standalone test
    logger.setLevel(logging.DEBUG)

    if not SENTENCE_MODEL_AVAILABLE:
        logger.error("Standalone test requires sentence-transformers. Please install it.")
        sys.exit(1)
    
    # Create dummy processed_json directory and files for testing
    test_processed_dir = os.path.join(PROJECT_ROOT, 'data', 'test_processed_json_sim')
    os.makedirs(test_processed_dir, exist_ok=True)

    dummy_article_1 = {
        "id": "hist001", "title": "Old Tech Advances",
        "content_for_processing": "This is an old article about significant technological advancements from last year. It covers various aspects of AI.",
        "summary": "Old tech article summary."
    }
    dummy_article_2 = {
        "id": "hist002", "title": "AI Ethics Discussed",
        "content_for_processing": "A detailed discussion on the ethical implications of artificial intelligence and machine learning. The importance of responsible AI is highlighted.",
        "summary": "Ethics in AI discussion."
    }
    with open(os.path.join(test_processed_dir, "hist001.json"), "w") as f: json.dump(dummy_article_1, f)
    with open(os.path.join(test_processed_dir, "hist002.json"), "w") as f: json.dump(dummy_article_2, f)

    current_article_new = {
        "id": "new001", "title": "Future of AI",
        "content_for_processing": "An article exploring the future prospects of artificial intelligence, including potential breakthroughs and societal impact. It also touches upon challenges.",
        "summary": "Future AI prospects."
    }
    current_article_duplicate = {
        "id": "new002", "title": "AI Ethics Discussed", # Exact title match
        "content_for_processing": "An in-depth look at ethical concerns surrounding AI and ML. Responsible AI development is crucial. This is very similar to another article.",
        "summary": "AI ethics detailed look."
    }
    current_article_similar_content = {
        "id": "new003", "title": "Tech Progress Report", # Different title
        "content_for_processing": "This piece reviews major tech progress from the past year, focusing on AI applications. It's quite like an old article.", # Similar content to hist001
        "summary": "Tech progress summary."
    }


    current_run_processed_list = [
        {"id": "run001", "title": "Intra-Run Test Original", "content_for_processing": "This is an original article processed earlier in this very same execution run. It talks about unique cloud computing solutions.", "summary":"Cloud solutions article."}
    ]
    current_article_intra_run_dup = {
         "id": "run002", "title": "Intra-Run Test Original", # Exact title
         "content_for_processing": "This is an original article processed earlier in this very same execution run. It talks about unique cloud computing solutions, almost identically.",
         "summary":"Cloud solutions duplicate article."
    }


    print("\n--- Test 1: New Unique Article ---")
    result1 = run_similarity_check_agent(current_article_new.copy(), test_processed_dir, current_run_processed_list)
    print(f"Verdict: {result1.get('similarity_verdict')}")

    print("\n--- Test 2: Article with Exact Title and Similar Content to Historical ---")
    result2 = run_similarity_check_agent(current_article_duplicate.copy(), test_processed_dir, current_run_processed_list)
    print(f"Verdict: {result2.get('similarity_verdict')}, Similar ID: {result2.get('similar_article_id')}, Score: {result2.get('similarity_score')}")

    print("\n--- Test 3: Article with Different Title but Similar Content to Historical ---")
    result3 = run_similarity_check_agent(current_article_similar_content.copy(), test_processed_dir, current_run_processed_list)
    print(f"Verdict: {result3.get('similarity_verdict')}, Similar ID: {result3.get('similar_article_id')}, Score: {result3.get('similarity_score')}")

    print("\n--- Test 4: Article Similar to one from Current Run ---")
    # Add result1 to current_run_processed_list for the next check IF it was "OKAY"
    if result1.get('similarity_verdict', '').startswith("OKAY"):
        # For testing, we'd pass the full data object as it would be after processing
        current_run_processed_list_updated = current_run_processed_list + [current_article_new.copy()] # Or result1 if it's modified in place
    else:
        current_run_processed_list_updated = current_run_processed_list

    result4 = run_similarity_check_agent(current_article_intra_run_dup.copy(), test_processed_dir, current_run_processed_list_updated) # Pass original data of run001
    print(f"Verdict: {result4.get('similarity_verdict')}, Similar ID: {result4.get('similar_article_id')}, Score: {result4.get('similarity_score')}")


    # Cleanup test files
    for f_name in ["hist001.json", "hist002.json"]:
        os.remove(os.path.join(test_processed_dir, f_name))
    os.rmdir(test_processed_dir)
    print("\n--- Similarity Check Agent Standalone Test Complete ---")