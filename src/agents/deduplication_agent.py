# src/agents/deduplication_agent.py

import os
import sys
import json
import logging
import numpy as np
import requests # For Ollama
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
OLLAMA_API_EMBEDDINGS_URL = "http://localhost:11434/api/embeddings"
OLLAMA_EMBEDDING_MODEL = "bge-m3:latest" # Or "mxbai-embed-large:latest", "e5-large", etc. Make sure it's pulled.
# Fallback to SentenceTransformer library if direct Ollama embedding call fails or for alternative models
ST_MODEL_NAME = 'all-MiniLM-L6-v2' # A common default, change if using something else directly
USE_ST_LIBRARY_DIRECTLY = False # Set to True to use SentenceTransformer library instead of Ollama API endpoint

HISTORICAL_EMBEDDINGS_FILE = os.path.join(DATA_DIR, 'historical_embeddings.json')
SIMILARITY_THRESHOLD_DUPLICATE = 0.90  # If content similarity > this, it's a duplicate
SIMILARITY_THRESHOLD_NEARDUPLICATE = 0.80 # Flag for review or slightly different handling
MIN_TEXT_LENGTH_FOR_EMBEDDING = 50 # Min characters in text to attempt embedding

# --- Sentence Transformer Model (direct library use, optional) ---
sentence_transformer_model_direct = None
if USE_ST_LIBRARY_DIRECTLY:
    try:
        from sentence_transformers import SentenceTransformer
        sentence_transformer_model_direct = SentenceTransformer(ST_MODEL_NAME)
        logger.info(f"Successfully loaded SentenceTransformer model (direct): {ST_MODEL_NAME}")
    except ImportError:
        logger.error("SentenceTransformer library not found, but USE_ST_LIBRARY_DIRECTLY is True. Deduplication will be impaired.")
        USE_ST_LIBRARY_DIRECTLY = False # Fallback to Ollama API if ST lib fails
    except Exception as e:
        logger.error(f"Error loading SentenceTransformer model (direct) '{ST_MODEL_NAME}': {e}")
        USE_ST_LIBRARY_DIRECTLY = False


# --- Helper Functions ---
def _cosine_similarity(vec1, vec2):
    """Computes cosine similarity between two numpy arrays."""
    vec1 = np.asarray(vec1, dtype=np.float32) # Ensure float32 for precision with some models
    vec2 = np.asarray(vec2, dtype=np.float32)
    if vec1.shape != vec2.shape:
        logger.error(f"Cannot compute cosine similarity for vectors with different shapes: {vec1.shape} vs {vec2.shape}")
        return 0.0
    if np.all(vec1 == 0) or np.all(vec2 == 0): # Handle zero vectors
        return 0.0
    dot_product = np.dot(vec1, vec2)
    norm_vec1 = np.linalg.norm(vec1)
    norm_vec2 = np.linalg.norm(vec2)
    if norm_vec1 == 0 or norm_vec2 == 0: # Avoid division by zero
        return 0.0
    return dot_product / (norm_vec1 * norm_vec2)

def get_embedding_ollama(text_content):
    """Gets embedding for text content using Ollama /api/embeddings."""
    if not text_content or len(text_content.strip()) < MIN_TEXT_LENGTH_FOR_EMBEDDING:
        logger.debug("Text content too short for Ollama embedding, returning None.")
        return None
    payload = {
        "model": OLLAMA_EMBEDDING_MODEL,
        "prompt": text_content.strip() # Ollama uses 'prompt' for text to embed
    }
    try:
        logger.debug(f"Requesting Ollama embedding for text (model: {OLLAMA_EMBEDDING_MODEL}). Length: {len(text_content)}")
        response = requests.post(OLLAMA_API_EMBEDDINGS_URL, json=payload, timeout=45)
        response.raise_for_status()
        response_json = response.json()
        embedding = response_json.get("embedding")
        if embedding and isinstance(embedding, list):
            logger.debug(f"Ollama embedding received. Vector length: {len(embedding)}")
            return embedding
        else:
            logger.error(f"Ollama embedding response missing 'embedding' field or not a list: {response_json}")
            return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Ollama API request for embedding failed: {e}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error in get_embedding_ollama: {e}")
        return None

def get_embedding_st_direct(text_content):
    """Gets embedding using SentenceTransformer library directly."""
    if not sentence_transformer_model_direct:
        logger.error("SentenceTransformer direct model not loaded. Cannot get direct embedding.")
        return None
    if not text_content or len(text_content.strip()) < MIN_TEXT_LENGTH_FOR_EMBEDDING:
        logger.debug("Text content too short for direct ST embedding, returning None.")
        return None
    try:
        logger.debug(f"Requesting direct ST embedding for text (model: {ST_MODEL_NAME}). Length: {len(text_content)}")
        embedding = sentence_transformer_model_direct.encode(text_content.strip())
        logger.debug(f"Direct ST embedding received. Vector length: {len(embedding)}")
        return embedding.tolist() # Convert numpy array to list for JSON serialization
    except Exception as e:
        logger.exception(f"Unexpected error in get_embedding_st_direct: {e}")
        return None

def get_embedding(text_content):
    """Unified function to get embedding, trying Ollama first then ST direct as fallback if configured."""
    if USE_ST_LIBRARY_DIRECTLY and sentence_transformer_model_direct:
        # If ST direct is preferred and available, use it
        emb = get_embedding_st_direct(text_content)
        if emb: return emb
        # Fall through to Ollama if ST direct fails for some reason but Ollama might work
        logger.warning("Preferred ST Direct embedding failed, attempting Ollama API as fallback.")
    
    # Default to Ollama API
    return get_embedding_ollama(text_content)


def load_historical_embeddings():
    """Loads historical embeddings from the JSON file."""
    if not os.path.exists(HISTORICAL_EMBEDDINGS_FILE):
        return {} # Return empty dict if file doesn't exist
    try:
        with open(HISTORICAL_EMBEDDINGS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        logger.info(f"Loaded {len(data)} historical embeddings from {HISTORICAL_EMBEDDINGS_FILE}")
        return data
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from historical embeddings file {HISTORICAL_EMBEDDINGS_FILE}. Returning empty.")
        return {}
    except Exception as e:
        logger.error(f"Error loading historical embeddings: {e}")
        return {}

def save_historical_embeddings(embeddings_data):
    """Saves embeddings data to the JSON file."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(HISTORICAL_EMBEDDINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(embeddings_data, f) # No indent for slightly smaller file
        logger.info(f"Saved {len(embeddings_data)} total embeddings to {HISTORICAL_EMBEDDINGS_FILE}")
    except Exception as e:
        logger.error(f"Error saving historical embeddings: {e}")

def run_deduplication_agent(article_pipeline_data, historical_embeddings_data):
    """
    Checks for duplicates and near-duplicates against historical data.
    Updates article_pipeline_data with 'is_duplicate', 'is_near_duplicate', 'similarity_score', 'similar_article_id'.
    Modifies historical_embeddings_data in-place if the article is unique and gets embedded.
    """
    article_id = article_pipeline_data.get('id', 'unknown_id')
    # Use the processed_summary from filter_enrich_agent if available and substantial,
    # otherwise fall back to raw_scraped_text. Add title for more context.
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
        return article_pipeline_data # No changes to historical_embeddings_data

    logger.info(f"--- Running Deduplication Agent for Article ID: {article_id} ---")
    logger.debug(f"Text for embedding preview (first 100 chars): '{text_for_embedding[:100]}...'")

    current_article_embedding = get_embedding(text_for_embedding)

    if not current_article_embedding:
        logger.error(f"Failed to generate embedding for article {article_id}. Cannot perform deduplication.")
        article_pipeline_data['is_duplicate'] = False # Cannot confirm, assume not duplicate
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

    if not historical_embeddings_data: # If the historical data is empty (e.g. first run)
        logger.info("No historical embeddings to compare against. Marking article as unique.")
        historical_embeddings_data[article_id] = current_article_embedding
        article_pipeline_data['deduplication_status'] = "UNIQUE_NO_HISTORY"
        return article_pipeline_data

    for hist_id, hist_embedding_list in historical_embeddings_data.items():
        if hist_id == article_id: # Should not happen if loading before adding current
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
            # Do not add this duplicate's embedding to historical_embeddings_data
            return article_pipeline_data # Exit early on finding a clear duplicate
        
        elif similarity >= SIMILARITY_THRESHOLD_NEARDUPLICATE:
            logger.info(f"Article {article_id} is a NEAR-DUPLICATE of {hist_id}. Similarity: {similarity:.4f}")
            # Mark as near-duplicate, but continue checking if a stronger duplicate exists
            if not article_pipeline_data['is_duplicate']: # Only set near_duplicate if not already a full duplicate
                article_pipeline_data['is_near_duplicate'] = True
                # Keep track of the strongest near-duplicate found so far
                if similarity > article_pipeline_data.get('similarity_score', 0.0):
                    article_pipeline_data['similar_article_id'] = hist_id
                    article_pipeline_data['similarity_score'] = similarity
                    article_pipeline_data['deduplication_status'] = f"NEAR_DUPLICATE_OF_{hist_id}"


    if not article_pipeline_data['is_duplicate'] and not article_pipeline_data['is_near_duplicate']:
        logger.info(f"Article {article_id} is unique. Highest similarity found: {highest_similarity_score:.4f} with {most_similar_id if most_similar_id else 'N/A'}.")
        article_pipeline_data['deduplication_status'] = f"UNIQUE_HIGHEST_SIM_{highest_similarity_score:.2f}"
        if highest_similarity_score > 0: # Store score even if unique but had some similarity
             article_pipeline_data['similarity_score'] = highest_similarity_score
             article_pipeline_data['similar_article_id'] = most_similar_id


    # If the article is not a duplicate (it could be a near-duplicate or unique), add its embedding to history
    if not article_pipeline_data['is_duplicate']:
        historical_embeddings_data[article_id] = current_article_embedding
        logger.debug(f"Added embedding for unique/near-duplicate article {article_id} to in-memory historical data.")
        # The actual saving of historical_embeddings_data to file should happen once at the end of main.py loop

    return article_pipeline_data

# --- Standalone Execution Example ---
if __name__ == "__main__":
    if not logger.handlers:
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
                            format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')
    
    logger.info("--- Starting Deduplication Agent Standalone Test ---")

    # Ensure Ollama is running with bge-m3:latest (or your chosen model)
    # Or if USE_ST_LIBRARY_DIRECTLY = True, ensure the ST_MODEL_NAME is valid.

    # Clean up old test file if it exists
    if os.path.exists(HISTORICAL_EMBEDDINGS_FILE):
        os.remove(HISTORICAL_EMBEDDINGS_FILE)
        logger.info(f"Removed old {HISTORICAL_EMBEDDINGS_FILE} for fresh test.")

    # Load (empty) historical embeddings
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
    article4_data_short = {
        'id': 'test_dup_004',
        'initial_title_from_web': "Quick Update",
        'processed_summary': "Short news byte.",
        'raw_scraped_text': "This is a very short piece of text."
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

    logger.info("\nProcessing Article 4 (Short Text)...")
    article4_data_short = run_deduplication_agent(article4_data_short, current_historical_embeddings)
    logger.info(f"Article 4 Result: Dup={article4_data_short.get('is_duplicate')}, NearDup={article4_data_short.get('is_near_duplicate')}, Score={article4_data_short.get('similarity_score')}, Status={article4_data_short.get('deduplication_status')}")


    # Save the final historical embeddings (would happen at the end of main.py's loop)
    save_historical_embeddings(current_historical_embeddings)
    logger.info(f"Final historical embeddings saved. Total entries: {len(current_historical_embeddings)}")
    
    # Test reloading
    reloaded_embeddings = load_historical_embeddings()
    logger.info(f"Reloaded embeddings. Total entries: {len(reloaded_embeddings)}")
    assert len(reloaded_embeddings) == len(current_historical_embeddings) # Basic check

    logger.info("--- Deduplication Agent Standalone Test Complete ---")