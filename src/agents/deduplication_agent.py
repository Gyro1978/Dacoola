# src/agents/deduplication_agent.py

import os
import sys
import json
import logging
import numpy as np
import time
import re 
from datetime import datetime, timezone # Corrected import, ensure timezone is available

# --- Path Setup ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
# --- End Path Setup ---

# --- Setup Logging ---
logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
logger.setLevel(logging.DEBUG)

# --- Configuration ---
ST_MODEL_NAME = os.getenv('DEDUPLICATION_SENTENCE_TRANSFORMER_MODEL', 'all-mpnet-base-v2') 
USE_ST_LIBRARY_DIRECTLY = True 

HISTORICAL_EMBEDDINGS_FILE = os.path.join(DATA_DIR, 'historical_embeddings.json')
SIMILARITY_THRESHOLD_DUPLICATE = float(os.getenv('DEDUPLICATION_THRESHOLD_DUPLICATE', 0.92)) 
SIMILARITY_THRESHOLD_NEARDUPLICATE = float(os.getenv('DEDUPLICATION_THRESHOLD_NEARDUPLICATE', 0.82))
MIN_TEXT_LENGTH_FOR_EMBEDDING = int(os.getenv('DEDUPLICATION_MIN_TEXT_LENGTH', 75)) 
MAX_TEXT_SNIPPET_FOR_EMBEDDING = int(os.getenv('DEDUPLICATION_MAX_TEXT_SNIPPET', 2000)) 


# --- Sentence Transformer Model ---
sentence_transformer_model_direct = None
if USE_ST_LIBRARY_DIRECTLY:
    try:
        from sentence_transformers import SentenceTransformer
        logger.info(f"Attempting to load SentenceTransformer model: {ST_MODEL_NAME}")
        sentence_transformer_model_direct = SentenceTransformer(ST_MODEL_NAME)
        logger.info(f"Successfully loaded SentenceTransformer model (direct): {ST_MODEL_NAME}")
    except ImportError:
        logger.error("SentenceTransformer library not found, but USE_ST_LIBRARY_DIRECTLY is True. Deduplication will be IMPAIRED.")
        USE_ST_LIBRARY_DIRECTLY = False 
    except Exception as e:
        logger.error(f"Error loading SentenceTransformer model (direct) '{ST_MODEL_NAME}': {e}. Deduplication IMPAIRED.")
        USE_ST_LIBRARY_DIRECTLY = False


# --- Helper Functions ---
def _cosine_similarity(vec1, vec2):
    vec1_np = np.asarray(vec1, dtype=np.float32) 
    vec2_np = np.asarray(vec2, dtype=np.float32)
    if vec1_np.shape != vec2_np.shape:
        logger.error(f"Cannot compute cosine similarity for vectors with different shapes: {vec1_np.shape} vs {vec2_np.shape}")
        return 0.0
    if np.all(vec1_np == 0) or np.all(vec2_np == 0): return 0.0 
    dot_product = np.dot(vec1_np, vec2_np)
    norm_vec1 = np.linalg.norm(vec1_np)
    norm_vec2 = np.linalg.norm(vec2_np)
    if norm_vec1 == 0 or norm_vec2 == 0: return 0.0 
    similarity_val = dot_product / (norm_vec1 * norm_vec2)
    return float(similarity_val) 

def advanced_text_cleaner(text_content: str) -> str:
    if not text_content: return ""
    text_content = re.sub(r'\s+', ' ', text_content).strip()
    text_content = re.sub(r'Image credit:.*$', '', text_content, flags=re.IGNORECASE | re.MULTILINE)
    text_content = re.sub(r'Photo by .* on Unsplash.*$', '', text_content, flags=re.IGNORECASE | re.MULTILINE)
    return text_content


def get_embedding_st_direct(text_content_for_embedding):
    if not sentence_transformer_model_direct:
        logger.error("SentenceTransformer direct model not loaded. Cannot get direct embedding.")
        return None
    if not text_content_for_embedding or len(text_content_for_embedding.strip()) < MIN_TEXT_LENGTH_FOR_EMBEDDING:
        logger.debug(f"Text content too short ({len(text_content_for_embedding.strip())} chars) for direct ST embedding, returning None.")
        return None
    try:
        logger.debug(f"Requesting direct ST embedding for text (model: {ST_MODEL_NAME}). Length: {len(text_content_for_embedding)}")
        embedding = sentence_transformer_model_direct.encode(text_content_for_embedding, show_progress_bar=False)
        logger.debug(f"Direct ST embedding received. Vector length: {len(embedding)}")
        return embedding.tolist() 
    except Exception as e:
        logger.exception(f"Unexpected error in get_embedding_st_direct: {e}")
        return None

def get_embedding_for_dedup(text_for_dedup): 
    if USE_ST_LIBRARY_DIRECTLY and sentence_transformer_model_direct:
        return get_embedding_st_direct(text_for_dedup)
    else:
        logger.error("Deduplication embedding generation failed: No valid embedding method configured/available.")
        return None

def load_historical_embeddings():
    if not os.path.exists(HISTORICAL_EMBEDDINGS_FILE): return {} 
    try:
        with open(HISTORICAL_EMBEDDINGS_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
        logger.info(f"Loaded {len(data)} historical embeddings from {HISTORICAL_EMBEDDINGS_FILE}")
        return data
    except json.JSONDecodeError: logger.error(f"Error decoding JSON from {HISTORICAL_EMBEDDINGS_FILE}. Returning empty."); return {}
    except Exception as e: logger.error(f"Error loading historical embeddings: {e}"); return {}

def save_historical_embeddings(embeddings_data):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(HISTORICAL_EMBEDDINGS_FILE, 'w', encoding='utf-8') as f: json.dump(embeddings_data, f) 
        logger.info(f"Saved {len(embeddings_data)} total embeddings to {HISTORICAL_EMBEDDINGS_FILE}")
    except Exception as e: logger.error(f"Error saving historical embeddings: {e}")

def run_deduplication_agent(article_pipeline_data, historical_embeddings_data):
    article_id = article_pipeline_data.get('id', 'unknown_id')
    title = article_pipeline_data.get('initial_title_from_web', article_pipeline_data.get('final_page_h1',''))
    summary = article_pipeline_data.get('processed_summary', article_pipeline_data.get('generated_meta_description',''))
    raw_text = article_pipeline_data.get('raw_scraped_text', '')

    body_snippet = (raw_text.strip()[:MAX_TEXT_SNIPPET_FOR_EMBEDDING] + "...") if raw_text and len(raw_text.strip()) > 20 else ""
    
    text_parts_for_embedding = [title, summary, body_snippet]
    combined_text_for_embedding = ". ".join(filter(None, text_parts_for_embedding))
    
    cleaned_text_for_embedding = advanced_text_cleaner(combined_text_for_embedding)

    if len(cleaned_text_for_embedding) < MIN_TEXT_LENGTH_FOR_EMBEDDING:
        article_pipeline_data.update({'is_duplicate': False, 'near_duplicates_found': [], 'similarity_score_to_highest': 0.0, 'highest_similar_article_id': None, 'deduplication_status': f"SKIPPED_TEXT_TOO_SHORT_{len(cleaned_text_for_embedding)}chars"})
        logger.warning(f"Deduplication for {article_id} skipped: text too short after cleaning ({len(cleaned_text_for_embedding)} chars). Min required: {MIN_TEXT_LENGTH_FOR_EMBEDDING}.")
        return article_pipeline_data

    logger.info(f"--- Running Deduplication Agent for Article ID: {article_id} (Model: {ST_MODEL_NAME}) ---")
    logger.debug(f"Text for embedding (first 300 chars): {cleaned_text_for_embedding[:300]}...")
    current_article_embedding = get_embedding_for_dedup(cleaned_text_for_embedding)

    if not current_article_embedding:
        article_pipeline_data.update({'is_duplicate': False, 'near_duplicates_found': [], 'similarity_score_to_highest': 0.0, 'highest_similar_article_id': None, 'deduplication_status': "FAILED_EMBEDDING_CURRENT"})
        return article_pipeline_data

    article_pipeline_data.update({'is_duplicate': False, 'near_duplicates_found': [], 'similarity_score_to_highest': 0.0, 'highest_similar_article_id': None})
    
    all_near_duplicates_info = []

    if not historical_embeddings_data:
        logger.info(f"No historical embeddings found. Marking article {article_id} as unique by default.")
        # Corrected: When adding new, store as dict with 'embedding' key
        historical_embeddings_data[article_id] = {
            "embedding": current_article_embedding,
            "title": title[:150],
            "date_added_utc": datetime.now(timezone.utc).isoformat() # Changed from datetime.utcnow()
        }
        article_pipeline_data['deduplication_status'] = "UNIQUE_NO_HISTORY"
        return article_pipeline_data

    highest_similarity_overall = 0.0
    id_of_highest_similar = None

    for hist_id, hist_data in historical_embeddings_data.items():
        if hist_id == article_id: continue
        
        hist_embedding_vector = hist_data if isinstance(hist_data, list) else hist_data.get('embedding')
        if not hist_embedding_vector:
            logger.warning(f"Skipping historical entry {hist_id} due to missing embedding vector.")
            continue

        similarity = _cosine_similarity(current_article_embedding, hist_embedding_vector)

        if similarity > highest_similarity_overall:
            highest_similarity_overall = similarity
            id_of_highest_similar = hist_id

        if similarity >= SIMILARITY_THRESHOLD_DUPLICATE:
            logger.warning(f"Article {article_id} is DUPLICATE of {hist_id}. Similarity: {similarity:.4f}")
            article_pipeline_data.update({'is_duplicate': True, 'highest_similar_article_id': hist_id, 'similarity_score_to_highest': float(similarity), 'deduplication_status': f"DUPLICATE_OF_{hist_id}"})
        
        elif similarity >= SIMILARITY_THRESHOLD_NEARDUPLICATE:
            logger.info(f"Article {article_id} is NEAR-DUPLICATE of {hist_id}. Similarity: {similarity:.4f}")
            all_near_duplicates_info.append({'id': hist_id, 'score': float(similarity)})

    article_pipeline_data['similarity_score_to_highest'] = float(highest_similarity_overall)
    article_pipeline_data['highest_similar_article_id'] = id_of_highest_similar
    
    if article_pipeline_data['is_duplicate']: 
        if all_near_duplicates_info:
            sorted_near_dups = sorted([nd for nd in all_near_duplicates_info if nd['id'] != article_pipeline_data['highest_similar_article_id']], key=lambda x: x['score'], reverse=True)
            article_pipeline_data['near_duplicates_found'] = sorted_near_dups[:3] 
    elif all_near_duplicates_info: 
        sorted_near_dups = sorted(all_near_duplicates_info, key=lambda x: x['score'], reverse=True)
        article_pipeline_data['near_duplicates_found'] = sorted_near_dups[:3] 
        article_pipeline_data['deduplication_status'] = f"NEAR_DUPLICATE_HIGHEST_WITH_{id_of_highest_similar}_{highest_similarity_overall:.2f}"
    else: 
        logger.info(f"Article {article_id} is unique. Highest similarity overall: {highest_similarity_overall:.4f} with {id_of_highest_similar or 'N/A'}.")
        article_pipeline_data['deduplication_status'] = f"UNIQUE_HIGHEST_SIM_{highest_similarity_overall:.2f}"

    if not article_pipeline_data['is_duplicate']:
        historical_embeddings_data[article_id] = {
            "embedding": current_article_embedding,
            "title": title[:150], 
            "date_added_utc": datetime.now(timezone.utc).isoformat() # Changed from datetime.utcnow()
        }
        logger.debug(f"Added/Updated embedding for article {article_id} to historical data.")
    
    return article_pipeline_data

# --- Standalone Execution Example ---
if __name__ == "__main__":
    if not logger.handlers:
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
                            format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')
    
    logger.info(f"--- Starting Deduplication Agent Standalone Test (Model: {ST_MODEL_NAME}) ---")

    if not USE_ST_LIBRARY_DIRECTLY or not sentence_transformer_model_direct:
        logger.error(f"SentenceTransformer model '{ST_MODEL_NAME}' could not be loaded. Cannot run standalone test effectively.")
        sys.exit(1)

    if os.path.exists(HISTORICAL_EMBEDDINGS_FILE):
        os.remove(HISTORICAL_EMBEDDINGS_FILE)
        logger.info(f"Removed old {HISTORICAL_EMBEDDINGS_FILE} for fresh test.")

    current_historical_embeddings = load_historical_embeddings()

    article1_data = {
        'id': 'test_dup_001',
        'initial_title_from_web': "AI Breakthrough: New Model Achieves Human-Level Understanding in Complex Reasoning",
        'processed_summary': "A significant advancement in artificial intelligence was announced today as a new model, Cognito-7, demonstrates capabilities previously unseen, matching human performance on several complex reasoning tasks. Researchers are excited by the potential.",
        'raw_scraped_text': "Detailed text about the AI breakthrough focusing on its architecture and training data, implications for various industries, and quotes from experts. The model, named 'Cognito-7', was developed by Universal AI Corp. It excels at multi-hop reasoning and commonsense understanding."
    }
    article2_data_similar = {
        'id': 'test_dup_002',
        'initial_title_from_web': "Major AI Milestone: Cognito-7 Model Reaches Human-Like Comprehension and Reasoning",
        'processed_summary': "Universal AI Corp today revealed Cognito-7, an AI model achieving human-level comprehension. This breakthrough matches human scores on reasoning benchmarks, sparking excitement about its future applications in science and beyond.",
        'raw_scraped_text': "Further information on Cognito-7, its development timeline, the specific benchmarks it excelled on (e.g., GLUE, SuperGLUE), and statements from Universal AI Corp's CEO regarding its impact on the field. It also touched upon the energy requirements."
    }
    article3_data_different = {
        'id': 'test_dup_003',
        'initial_title_from_web': "New Quantum Computing Chip 'Quasar-X' Unveiled by QuantumLeap Inc.",
        'processed_summary': "QuantumLeap Inc. has introduced a novel quantum computing processor, 'Quasar-X', promising to solve complex calculations currently intractable for classical supercomputers. This could revolutionize fields like drug discovery and materials science with its unique qubit architecture.",
        'raw_scraped_text': "Technical specifications of the Quasar-X chip, its qubit architecture, error correction mechanisms, and potential applications in scientific research and cryptography. The company aims for commercial availability by 2027."
    }
    article4_data_short = {
        'id': 'test_dup_004',
        'initial_title_from_web': "Brief Update",
        'processed_summary': "A quick note.",
        'raw_scraped_text': "This is too short."
    }


    logger.info("\nProcessing Article 1 (Original)...")
    article1_data = run_deduplication_agent(article1_data, current_historical_embeddings)
    logger.info(f"Article 1 Result: Status='{article1_data.get('deduplication_status')}', Score='{article1_data.get('similarity_score_to_highest'):.4f}', Dup='{article1_data.get('is_duplicate')}', NearDups='{len(article1_data.get('near_duplicates_found',[]))}'")
    
    logger.info("\nProcessing Article 2 (Similar to Article 1)...")
    article2_data_similar = run_deduplication_agent(article2_data_similar, current_historical_embeddings)
    logger.info(f"Article 2 Result: Status='{article2_data_similar.get('deduplication_status')}', Score='{article2_data_similar.get('similarity_score_to_highest'):.4f}', Dup='{article2_data_similar.get('is_duplicate')}', SimilarID='{article2_data_similar.get('highest_similar_article_id')}', NearDups='{len(article2_data_similar.get('near_duplicates_found',[]))}'")

    logger.info("\nProcessing Article 3 (Different from Article 1 & 2)...")
    article3_data_different = run_deduplication_agent(article3_data_different, current_historical_embeddings)
    logger.info(f"Article 3 Result: Status='{article3_data_different.get('deduplication_status')}', Score='{article3_data_different.get('similarity_score_to_highest'):.4f}', Dup='{article3_data_different.get('is_duplicate')}', NearDups='{len(article3_data_different.get('near_duplicates_found',[]))}'")
    
    logger.info("\nProcessing Article 4 (Too Short)...")
    article4_data_short = run_deduplication_agent(article4_data_short, current_historical_embeddings)
    logger.info(f"Article 4 Result: Status='{article4_data_short.get('deduplication_status')}', Score='{article4_data_short.get('similarity_score_to_highest'):.4f}', Dup='{article4_data_short.get('is_duplicate')}', NearDups='{len(article4_data_short.get('near_duplicates_found',[]))}'")


    save_historical_embeddings(current_historical_embeddings)
    logger.info(f"Final historical embeddings saved. Total entries: {len(current_historical_embeddings)}")
    
    try:
        with open(os.path.join(DATA_DIR, "dedup_agent_test_output.json"), 'w') as f:
            json.dump([article1_data, article2_data_similar, article3_data_different, article4_data_short], f, indent=2)
        logger.info("Successfully serialized deduplication agent outputs to JSON.")
        # os.remove(os.path.join(DATA_DIR, "dedup_agent_test_output.json")) 
    except TypeError as e:
        logger.error(f"JSON SERIALIZATION FAILED for deduplication agent output: {e}")

    logger.info("--- Deduplication Agent Standalone Test Complete ---")