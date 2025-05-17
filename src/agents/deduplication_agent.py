# src/agents/deduplication_agent.py

import os
import sys
import json
import logging
import numpy as np
# import requests # No longer needed for Ollama embeddings
import time

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
# Ollama embedding configuration removed as we switch to sentence-transformers directly.
# OLLAMA_API_EMBEDDINGS_URL = "http://localhost:11434/api/embeddings"
# OLLAMA_EMBEDDING_MODEL = "bge-m3:latest" 

# Using SentenceTransformer library directly
ST_MODEL_NAME = 'all-MiniLM-L6-v2' # A common default, ensure this is suitable for your needs.
                                   # Other options: 'bge-m3' (if you install sentence-transformers[bge]),
                                   # 'multi-qa-MiniLM-L6-cos-v1', etc.
USE_ST_LIBRARY_DIRECTLY = True # Forcing direct library use

HISTORICAL_EMBEDDINGS_FILE = os.path.join(DATA_DIR, 'historical_embeddings.json')
SIMILARITY_THRESHOLD_DUPLICATE = 0.90
SIMILARITY_THRESHOLD_NEARDUPLICATE = 0.80
MIN_TEXT_LENGTH_FOR_EMBEDDING = 50

# --- Sentence Transformer Model (direct library use) ---
sentence_transformer_model_direct = None
if USE_ST_LIBRARY_DIRECTLY:
    try:
        from sentence_transformers import SentenceTransformer
        # Ensure the chosen ST_MODEL_NAME is one that SentenceTransformer can load.
        # If 'bge-m3' is preferred, you might need to install sentence-transformers with BGE support
        # or ensure the model is downloaded from Hugging Face if it's not a default.
        # For simplicity, 'all-MiniLM-L6-v2' is a good general-purpose starting point.
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
    vec1 = np.asarray(vec1, dtype=np.float32)
    vec2 = np.asarray(vec2, dtype=np.float32)
    if vec1.shape != vec2.shape:
        logger.error(f"Cannot compute cosine similarity for vectors with different shapes: {vec1.shape} vs {vec2.shape}")
        return 0.0
    if np.all(vec1 == 0) or np.all(vec2 == 0): return 0.0
    dot_product = np.dot(vec1, vec2)
    norm_vec1 = np.linalg.norm(vec1)
    norm_vec2 = np.linalg.norm(vec2)
    if norm_vec1 == 0 or norm_vec2 == 0: return 0.0
    return dot_product / (norm_vec1 * norm_vec2)

# get_embedding_ollama function removed or commented out

def get_embedding_st_direct(text_content):
    if not sentence_transformer_model_direct:
        logger.error("SentenceTransformer direct model not loaded. Cannot get direct embedding.")
        return None
    if not text_content or len(text_content.strip()) < MIN_TEXT_LENGTH_FOR_EMBEDDING:
        logger.debug("Text content too short for direct ST embedding, returning None.")
        return None
    try:
        logger.debug(f"Requesting direct ST embedding for text (model: {ST_MODEL_NAME}). Length: {len(text_content)}")
        embedding = sentence_transformer_model_direct.encode(text_content.strip(), show_progress_bar=False)
        logger.debug(f"Direct ST embedding received. Vector length: {len(embedding)}")
        return embedding.tolist() 
    except Exception as e:
        logger.exception(f"Unexpected error in get_embedding_st_direct: {e}")
        return None

def get_embedding(text_content):
    """Unified function to get embedding, now defaults to ST direct."""
    if USE_ST_LIBRARY_DIRECTLY and sentence_transformer_model_direct:
        return get_embedding_st_direct(text_content)
    else:
        logger.error("Deduplication embedding generation failed: No valid embedding method configured/available.")
        return None


def load_historical_embeddings():
    if not os.path.exists(HISTORICAL_EMBEDDINGS_FILE):
        return {} 
    try:
        with open(HISTORICAL_EMBEDDINGS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        logger.info(f"Loaded {len(data)} historical embeddings from {HISTORICAL_EMBEDDINGS_FILE}")
        return data
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from {HISTORICAL_EMBEDDINGS_FILE}. Returning empty.")
        return {}
    except Exception as e:
        logger.error(f"Error loading historical embeddings: {e}")
        return {}

def save_historical_embeddings(embeddings_data):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(HISTORICAL_EMBEDDINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(embeddings_data, f) 
        logger.info(f"Saved {len(embeddings_data)} total embeddings to {HISTORICAL_EMBEDDINGS_FILE}")
    except Exception as e:
        logger.error(f"Error saving historical embeddings: {e}")

def run_deduplication_agent(article_pipeline_data, historical_embeddings_data):
    article_id = article_pipeline_data.get('id', 'unknown_id')
    title = article_pipeline_data.get('initial_title_from_web', '')
    summary = article_pipeline_data.get('processed_summary', '')
    raw_text = article_pipeline_data.get('raw_scraped_text', '')

    text_for_embedding = f"{title}. {summary}" if len(summary) > MIN_TEXT_LENGTH_FOR_EMBEDDING / 2 else f"{title}. {raw_text}"
    
    if len(text_for_embedding.strip()) < MIN_TEXT_LENGTH_FOR_EMBEDDING:
        logger.warning(f"Article {article_id} text too short for meaningful deduplication. Marking as not duplicate.")
        article_pipeline_data['is_duplicate'] = False
        article_pipeline_data['is_near_duplicate'] = False
        article_pipeline_data['similarity_score'] = 0.0
        article_pipeline_data['similar_article_id'] = None
        article_pipeline_data['deduplication_status'] = "SKIPPED_SHORT_TEXT"
        return article_pipeline_data

    logger.info(f"--- Running Deduplication Agent for Article ID: {article_id} ---")
    logger.debug(f"Text for embedding preview (first 100 chars): '{text_for_embedding[:100]}...'")

    current_article_embedding = get_embedding(text_for_embedding) # Now uses ST direct

    if not current_article_embedding:
        logger.error(f"Failed to generate embedding for article {article_id}. Cannot perform deduplication.")
        article_pipeline_data['is_duplicate'] = False 
        article_pipeline_data['is_near_duplicate'] = False
        article_pipeline_data['similarity_score'] = 0.0
        article_pipeline_data['similar_article_id'] = None
        article_pipeline_data['deduplication_status'] = "FAILED_EMBEDDING_CURRENT"
        return article_pipeline_data

    article_pipeline_data['is_duplicate'] = False
    article_pipeline_data['is_near_duplicate'] = False
    article_pipeline_data['similarity_score'] = 0.0
    article_pipeline_data['similar_article_id'] = None
    highest_similarity_score = 0.0
    most_similar_id = None

    if not historical_embeddings_data:
        logger.info("No historical embeddings to compare against. Marking article as unique.")
        historical_embeddings_data[article_id] = current_article_embedding
        article_pipeline_data['deduplication_status'] = "UNIQUE_NO_HISTORY"
        return article_pipeline_data

    for hist_id, hist_embedding_list in historical_embeddings_data.items():
        if hist_id == article_id: 
            continue
        
        similarity = _cosine_similarity(current_article_embedding, hist_embedding_list)

        if similarity > highest_similarity_score:
            highest_similarity_score = similarity
            most_similar_id = hist_id

        if similarity >= SIMILARITY_THRESHOLD_DUPLICATE:
            logger.warning(f"Article {article_id} is a DUPLICATE of {hist_id}. Similarity: {similarity:.4f}")
            article_pipeline_data['is_duplicate'] = True
            article_pipeline_data['similar_article_id'] = hist_id
            article_pipeline_data['similarity_score'] = similarity
            article_pipeline_data['deduplication_status'] = f"DUPLICATE_OF_{hist_id}"
            return article_pipeline_data 
        
        elif similarity >= SIMILARITY_THRESHOLD_NEARDUPLICATE:
            logger.info(f"Article {article_id} is a NEAR-DUPLICATE of {hist_id}. Similarity: {similarity:.4f}")
            if not article_pipeline_data['is_duplicate']: 
                article_pipeline_data['is_near_duplicate'] = True
                if similarity > article_pipeline_data.get('similarity_score', 0.0):
                    article_pipeline_data['similar_article_id'] = hist_id
                    article_pipeline_data['similarity_score'] = similarity
                    article_pipeline_data['deduplication_status'] = f"NEAR_DUPLICATE_OF_{hist_id}"

    if not article_pipeline_data['is_duplicate'] and not article_pipeline_data['is_near_duplicate']:
        logger.info(f"Article {article_id} is unique. Highest similarity found: {highest_similarity_score:.4f} with {most_similar_id if most_similar_id else 'N/A'}.")
        article_pipeline_data['deduplication_status'] = f"UNIQUE_HIGHEST_SIM_{highest_similarity_score:.2f}"
        if highest_similarity_score > 0:
             article_pipeline_data['similarity_score'] = highest_similarity_score
             article_pipeline_data['similar_article_id'] = most_similar_id

    if not article_pipeline_data['is_duplicate']:
        historical_embeddings_data[article_id] = current_article_embedding
        logger.debug(f"Added embedding for unique/near-duplicate article {article_id} to in-memory historical data.")

    return article_pipeline_data

# --- Standalone Execution Example ---
if __name__ == "__main__":
    if not logger.handlers:
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
                            format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')
    
    logger.info("--- Starting Deduplication Agent Standalone Test (using SentenceTransformers direct) ---")

    if not USE_ST_LIBRARY_DIRECTLY or not sentence_transformer_model_direct:
        logger.error("SentenceTransformer model could not be loaded. Cannot run standalone test effectively.")
        sys.exit(1)

    if os.path.exists(HISTORICAL_EMBEDDINGS_FILE):
        os.remove(HISTORICAL_EMBEDDINGS_FILE)
        logger.info(f"Removed old {HISTORICAL_EMBEDDINGS_FILE} for fresh test.")

    current_historical_embeddings = load_historical_embeddings()

    article1_data = {
        'id': 'test_dup_001',
        'initial_title_from_web': "AI Breakthrough: New Model Achieves Human-Level Understanding",
        'processed_summary': "A significant advancement in artificial intelligence was announced today as a new model demonstrates capabilities previously unseen, matching human performance on several complex reasoning tasks. Researchers are excited by the potential.",
        'raw_scraped_text': "Detailed text about the AI breakthrough focusing on its architecture and training data, implications for various industries, and quotes from experts. The model, named 'Cognito-7', was developed by Universal AI Corp."
    }
    article2_data_similar = {
        'id': 'test_dup_002',
        'initial_title_from_web': "Major AI Milestone: Cognito-7 Model Reaches Human-Like Comprehension",
        'processed_summary': "Universal AI Corp today revealed Cognito-7, an AI model achieving human-level comprehension. This breakthrough matches human scores on reasoning benchmarks, sparking excitement about its future applications.",
        'raw_scraped_text': "Further information on Cognito-7, its development timeline, the specific benchmarks it excelled on, and statements from Universal AI Corp's CEO regarding its impact."
    }
    article3_data_different = {
        'id': 'test_dup_003',
        'initial_title_from_web': "New Quantum Computing Chip Unveiled by QuantumLeap Inc.",
        'processed_summary': "QuantumLeap Inc. has introduced a novel quantum computing processor, 'Quasar-X', promising to solve complex calculations currently intractable for classical supercomputers. This could revolutionize fields like drug discovery and materials science.",
        'raw_scraped_text': "Technical specifications of the Quasar-X chip, its qubit architecture, error correction mechanisms, and potential applications in scientific research and cryptography."
    }

    logger.info("\nProcessing Article 1 (Original)...")
    article1_data = run_deduplication_agent(article1_data, current_historical_embeddings)
    logger.info(f"Article 1 Result: Dup={article1_data.get('is_duplicate')}, NearDup={article1_data.get('is_near_duplicate')}, Score={article1_data.get('similarity_score')}, Status={article1_data.get('deduplication_status')}")
    
    logger.info("\nProcessing Article 2 (Similar to Article 1)...")
    article2_data_similar = run_deduplication_agent(article2_data_similar, current_historical_embeddings)
    logger.info(f"Article 2 Result: Dup={article2_data_similar.get('is_duplicate')}, NearDup={article2_data_similar.get('is_near_duplicate')}, Score={article2_data_similar.get('similarity_score')}, SimilarID={article2_data_similar.get('similar_article_id')}, Status={article2_data_similar.get('deduplication_status')}")

    logger.info("\nProcessing Article 3 (Different from Article 1 & 2)...")
    article3_data_different = run_deduplication_agent(article3_data_different, current_historical_embeddings)
    logger.info(f"Article 3 Result: Dup={article3_data_different.get('is_duplicate')}, NearDup={article3_data_different.get('is_near_duplicate')}, Score={article3_data_different.get('similarity_score')}, Status={article3_data_different.get('deduplication_status')}")

    save_historical_embeddings(current_historical_embeddings)
    logger.info(f"Final historical embeddings saved. Total entries: {len(current_historical_embeddings)}")
    
    reloaded_embeddings = load_historical_embeddings()
    logger.info(f"Reloaded embeddings. Total entries: {len(reloaded_embeddings)}")
    assert len(reloaded_embeddings) == len(current_historical_embeddings)

    logger.info("--- Deduplication Agent Standalone Test Complete ---")