# src/agents/tts_generator_agent.py
import os
import glob # <<< ADD THIS LINE
import sys
import requests
import logging
import time
import json
import re # For cleaning text
from dotenv import load_dotenv
from urllib.parse import urljoin

# Load Env Vars specific to this agent
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '..', '.env'))
CAMB_AI_API_KEY = os.getenv('CAMB_AI_API_KEY')

# --- CORRECTED Endpoints based on Camb AI Docs ---
BASE_URL = "https://client.camb.ai/apis"
TTS_CREATE_ENDPOINT = f"{BASE_URL}/tts"
TTS_STATUS_ENDPOINT_TEMPLATE = f"{BASE_URL}/tts/{{task_id}}" # Use task_id
TTS_RESULT_ENDPOINT_TEMPLATE = f"{BASE_URL}/tts-result/{{run_id}}" # Use run_id for result

# Config
TTS_VOICE_ID_ALICE = 6104 # Defaulting Alice to example ID 6104 - CHECK /list-voices FOR CORRECT ID
TTS_VOICE_ID = int(os.getenv('CAMB_AI_VOICE_ID_ALICE', TTS_VOICE_ID_ALICE)) # Get from env or default
TTS_LANGUAGE_ID = 1 # 1 seems to be English (US) from docs - VERIFY THIS
TTS_GENDER = 2 # 2 is FEMALE from docs
TTS_AGE = 0 # 0 is default from docs

POLLING_INTERVAL_SECONDS = 3 # Poll more frequently as example uses 1.5s
MAX_POLLING_ATTEMPTS = 60 # Max times to check (e.g., 60 * 3s = 3 mins)

# --- Setup Logging (Keep as before) ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
# --- End Logging ---

def trigger_tts_generation(text_to_speak):
    """Sends request to Camb AI to start TTS generation. Returns task_id."""
    if not CAMB_AI_API_KEY:
        logger.error("CAMB_AI_API_KEY not found.")
        return None, "API key missing"

    headers = {
        "x-api-key": CAMB_AI_API_KEY, # Use x-api-key header
        "Content-Type": "application/json",
        "Accept": "application/json" # Good practice to include Accept
    }
    # --- Payload based on Camb AI Docs ---
    payload = {
        "text": text_to_speak,
        "voice_id": TTS_VOICE_ID, # Using Alice (check ID is correct)
        "language": TTS_LANGUAGE_ID,
        "gender": TTS_GENDER,
        "age": TTS_AGE
    }

    try:
        logger.info(f"Requesting TTS generation from {TTS_CREATE_ENDPOINT} for voice {TTS_VOICE_ID}")
        logger.debug(f"TTS Payload (text truncated): {{'text': '{text_to_speak[:50]}...', 'voice_id': {TTS_VOICE_ID}, ...}}")
        response = requests.post(TTS_CREATE_ENDPOINT, headers=headers, json=payload, timeout=30)

        logger.debug(f"TTS Create API Raw Status: {response.status_code}")
        try: logger.debug(f"TTS Create API Raw Body: {response.text[:500]}")
        except Exception: pass

        response.raise_for_status() # Check for HTTP errors
        result = response.json()

        # --- Get task_id from response ---
        task_id = result.get('task_id') # Docs say 'task_id'

        if not task_id:
            logger.error(f"TTS create successful but no 'task_id' found in response: {result}")
            return None, f"No task_id received. API Response: {result}"

        logger.info(f"TTS generation job started. Task ID: {task_id}")
        return task_id, None

    except requests.exceptions.HTTPError as http_err:
        err_msg = f"HTTP Error ({http_err.response.status_code}) calling TTS Create API"
        try: err_detail = http_err.response.json().get('message', http_err.response.text[:200])
        except Exception: err_detail = http_err.response.text[:200]
        logger.error(f"{err_msg}: {err_detail}")
        return None, f"{err_msg}: {err_detail}"
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error during TTS create request: {e}")
        return None, f"API Network request error: {e}"
    except json.JSONDecodeError as e:
         logger.error(f"Failed to decode JSON from TTS create API: {e}. Response: {response.text[:500] if response else 'N/A'}")
         return None, "Invalid JSON response from create API"
    except Exception as e:
        logger.exception(f"Unexpected error triggering TTS generation: {e}")
        return None, f"Unexpected error: {e}"

def poll_tts_status_and_get_result_url(task_id):
    """Polls Camb AI job status using task_id. Returns download URL when ready."""
    if not CAMB_AI_API_KEY or not task_id:
        logger.error("Cannot poll TTS status: API key or task ID missing.")
        return None, "API key or task ID missing"

    headers = {"x-api-key": CAMB_AI_API_KEY, "Accept": "application/json"}
    status_url_template = TTS_STATUS_ENDPOINT_TEMPLATE # e.g., ".../tts/{task_id}"

    logger.info(f"Polling status for TTS Task ID: {task_id}")
    for attempt in range(MAX_POLLING_ATTEMPTS):
        logger.debug(f"Polling attempt {attempt + 1}/{MAX_POLLING_ATTEMPTS} for task {task_id}")
        status_url = status_url_template.format(task_id=task_id)
        try:
            response = requests.get(status_url, headers=headers, timeout=30)
            logger.debug(f"TTS Status API Raw Status: {response.status_code}")
            try: logger.debug(f"TTS Status API Raw Body: {response.text[:500]}")
            except Exception: pass

            # Handle potential rate limits or temp errors without failing immediately
            if response.status_code == 429: # Too Many Requests
                 logger.warning(f"Rate limited polling task {task_id}. Waiting longer...")
                 time.sleep(POLLING_INTERVAL_SECONDS * 3) # Wait longer if rate limited
                 continue
            elif response.status_code >= 500: # Server error
                 logger.warning(f"Server error ({response.status_code}) polling task {task_id}. Retrying...")
                 time.sleep(POLLING_INTERVAL_SECONDS * 2)
                 continue

            response.raise_for_status() # Raise for other client errors (4xx)
            result = response.json()
            status = result.get('status', '').upper() # Use upper case like docs example
            run_id = result.get('run_id') # Get run_id needed for download

            logger.info(f"Task {task_id} status: '{status}' (Run ID: {run_id})")

            if status == 'SUCCESS': # Docs example uses 'SUCCESS'
                if not run_id:
                     logger.error(f"TTS task {task_id} SUCCESS but no 'run_id' found: {result}")
                     return None, "Task SUCCESS but missing run_id"

                # Now fetch the result URL using the run_id
                result_url = TTS_RESULT_ENDPOINT_TEMPLATE.format(run_id=run_id)
                logger.info(f"Task {task_id} succeeded. Fetching result URL from: {result_url}")
                try:
                    result_response = requests.get(result_url, headers=headers, timeout=30)
                    result_response.raise_for_status()
                    result_data = result_response.json()
                    # --- Check ACTUAL key for audio download URL in result response ---
                    audio_url = result_data.get('url', result_data.get('output_url', result_data.get('audio_url')))

                    if not audio_url:
                        logger.error(f"Fetched result for run {run_id} but no audio URL found: {result_data}")
                        return None, "Result fetched but no audio URL"

                    logger.info(f"Obtained audio download URL for run {run_id}")
                    return audio_url, None # Return the download URL

                except requests.exceptions.RequestException as res_e:
                     logger.error(f"Failed to fetch result URL for run {run_id}: {res_e}")
                     return None, f"Failed to fetch result URL: {res_e}"
                except json.JSONDecodeError as json_e:
                     logger.error(f"Failed to decode JSON from result URL for run {run_id}: {json_e}. Response: {result_response.text[:500] if result_response else 'N/A'}")
                     return None, "Invalid JSON from result API"


            elif status == 'FAILURE' or status == 'FAILED': # Check potential failure statuses
                error_message = result.get('error', 'Unknown API error')
                logger.error(f"TTS task {task_id} failed. API Reason: {error_message}")
                return None, f"TTS task failed: {error_message}"

            elif status in ['PENDING', 'PROCESSING', 'QUEUED']: # Check intermediate statuses
                logger.debug(f"Task {task_id} status '{status}'. Waiting {POLLING_INTERVAL_SECONDS}s...")
                time.sleep(POLLING_INTERVAL_SECONDS)
            else:
                logger.warning(f"Unknown TTS task status '{status}' for task {task_id}. Waiting. Response: {result}")
                time.sleep(POLLING_INTERVAL_SECONDS)

        except requests.exceptions.HTTPError as http_err:
             # Log client errors but might continue polling for transient issues
             logger.warning(f"HTTP error polling TTS status for task {task_id}: {http_err} - Status: {http_err.response.status_code}. Retrying...")
             time.sleep(POLLING_INTERVAL_SECONDS * 2)
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error polling TTS status for task {task_id}: {e}. Retrying...")
            time.sleep(POLLING_INTERVAL_SECONDS * 2)
        except json.JSONDecodeError as e:
             logger.error(f"Failed to decode JSON from TTS status API: {e}. Response: {response.text[:500] if response else 'N/A'}. Retrying...")
             time.sleep(POLLING_INTERVAL_SECONDS * 2)
        except Exception as e:
             logger.exception(f"Unexpected error during TTS polling for task {task_id}: {e}. Retrying...")
             time.sleep(POLLING_INTERVAL_SECONDS * 2)

    # If loop finishes without success
    logger.error(f"TTS task {task_id} did not complete successfully after {MAX_POLLING_ATTEMPTS} attempts.")
    return None, "TTS task polling timed out"


def download_audio(audio_url, output_audio_dir, article_id):
     """Downloads audio from URL and saves it."""
     logger.info(f"Downloading audio for {article_id} from URL.")
     try:
         # Add headers if needed by the storage provider (e.g., user-agent)
         headers = {'User-Agent': 'DacoolaAudioDownloader/1.0'}
         audio_response = requests.get(audio_url, headers=headers, timeout=180, stream=True) # Longer timeout for download
         audio_response.raise_for_status()

         os.makedirs(output_audio_dir, exist_ok=True)
         # Try to get extension, default to .wav as per example
         file_extension = os.path.splitext(audio_url)[1].split('?')[0] # Get extension before query params
         if not file_extension or len(file_extension) > 5:
             file_extension = ".wav"
             logger.warning("Could not determine audio extension, defaulting to .wav")

         audio_filename = f"{article_id}{file_extension}"
         audio_filepath = os.path.join(output_audio_dir, audio_filename)

         with open(audio_filepath, 'wb') as f:
             for chunk in audio_response.iter_content(chunk_size=8192):
                 f.write(chunk)

         logger.info(f"Audio downloaded and saved to: {audio_filepath}")
         relative_audio_path = f"audio/{audio_filename}" # Relative path for HTML/site_data
         return relative_audio_path, None

     except requests.exceptions.RequestException as download_err:
          logger.error(f"Failed to download audio file from {audio_url}: {download_err}")
          return None, f"Audio download failed: {download_err}"
     except IOError as io_err:
          logger.error(f"Failed to save audio file to {audio_filepath}: {io_err}")
          return None, f"File save error: {io_err}"
     except Exception as e:
          logger.exception(f"Unexpected error downloading audio for {article_id}: {e}")
          return None, f"Unexpected download error: {e}"


def run_tts_generator_agent(article_data, text_to_speak, output_audio_dir):
    """Orchestrates TTS generation: triggers, polls, downloads."""
    article_id = article_data.get('id', 'unknown_tts_article')
    # Clean text slightly
    text_cleaned = text_to_speak.replace('##', '').replace('###', '').replace('*', '').replace('_', '').strip()
    text_cleaned = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text_cleaned) # Remove markdown links

    if not text_cleaned:
        logger.warning(f"No substantial text for TTS for article {article_id}.")
        article_data['tts_agent_error'] = "Input text was empty after cleaning"
        article_data['audio_url'] = None
        return article_data

    # Check text length limit (Adjust 4500 based on API docs)
    MAX_TTS_CHARS = 4500
    if len(text_cleaned) > MAX_TTS_CHARS:
         logger.warning(f"Truncating text for TTS (>{MAX_TTS_CHARS} chars) for article {article_id}")
         text_cleaned = text_cleaned[:MAX_TTS_CHARS]

    # 1. Trigger Generation
    task_id, error = trigger_tts_generation(text_cleaned)
    if error or not task_id:
        article_data['tts_agent_error'] = f"Trigger failed: {error}"
        article_data['audio_url'] = None
        return article_data

    # 2. Poll Status and get Result URL
    audio_download_url, error = poll_tts_status_and_get_result_url(task_id)
    if error or not audio_download_url:
        article_data['tts_agent_error'] = f"Polling failed: {error}"
        article_data['audio_url'] = None
        return article_data

    # 3. Download the audio file
    relative_audio_path, error = download_audio(audio_download_url, output_audio_dir, article_id)
    if error or not relative_audio_path:
        article_data['tts_agent_error'] = f"Download failed: {error}"
        article_data['audio_url'] = None
        return article_data

    # 4. Success
    article_data['audio_url'] = relative_audio_path
    article_data['tts_agent_error'] = None # Clear errors on success
    logger.info(f"TTS process successful for {article_id}. Audio path: {relative_audio_path}")
    return article_data


# --- Add standalone execution logic ---
# (Keep the __main__ block and update_site_data_audio function from the previous answer)
# --- Add this function to update site_data.json ---
def update_site_data_audio(article_id, audio_url):
    """Updates only the audio_url for a specific article in site_data.json"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(script_dir))
    public_dir = os.path.join(project_root, 'public')
    site_data_file = os.path.join(public_dir, 'site_data.json')
    max_home_page_articles = int(os.getenv('MAX_HOME_PAGE_ARTICLES', 20))

    site_data = {"articles": []}
    updated = False
    try:
        if os.path.exists(site_data_file):
            with open(site_data_file, 'r', encoding='utf-8') as f:
                site_data = json.load(f)
                if not isinstance(site_data.get('articles'), list):
                     logger.warning(f"{site_data_file} format invalid. Resetting.")
                     site_data = {"articles": []}
    except Exception as e:
        logger.warning(f"Could not load {site_data_file} for audio update: {e}.")
        site_data = {"articles": []}

    for i, article in enumerate(site_data["articles"]):
        if article.get("id") == article_id:
            site_data["articles"][i]["audio_url"] = audio_url
            logger.info(f"Updated audio_url for {article_id} in site_data.json")
            updated = True
            break

    if not updated:
         logger.warning(f"Article {article_id} not found in current site_data.json (top {max_home_page_articles}). Cannot update audio URL there.")

    try:
        with open(site_data_file, 'w', encoding='utf-8') as f:
            json.dump(site_data, f, indent=2, ensure_ascii=False)
        if updated: logger.info(f"Saved updated {site_data_file}")
    except Exception as e:
        logger.error(f"Failed to save {site_data_file} after audio update: {e}")

# --- Main execution block ---
if __name__ == "__main__":
    print("--- Running Standalone TTS Generator/Retry ---")
    logger.info("--- Running Standalone TTS Generator/Retry ---")

    if not CAMB_AI_API_KEY:
        print("ERROR: CAMB_AI_API_KEY environment variable not set. Exiting.")
        logger.error("CAMB_AI_API_KEY environment variable not set. Exiting.")
        sys.exit(1)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(script_dir))
    data_dir = os.path.join(project_root, 'data')
    processed_json_dir = os.path.join(data_dir, 'processed_json')
    public_dir = os.path.join(project_root, 'public')
    output_audio_dir = os.path.join(public_dir, 'audio')

    os.makedirs(processed_json_dir, exist_ok=True)
    os.makedirs(output_audio_dir, exist_ok=True)

    processed_files = glob.glob(os.path.join(processed_json_dir, '*.json'))
    print(f"Found {len(processed_files)} processed JSON files to check.")
    logger.info(f"Found {len(processed_files)} processed JSON files to check.")

    generated_count = 0
    failed_count = 0

    for filepath in processed_files:
        filename = os.path.basename(filepath)
        logger.info(f"Checking file: {filename}")
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                article_data = json.load(f)

            should_generate = False
            if not article_data.get('audio_url'):
                 # Only retry if there was NO previous error recorded, or if the previous error was specifically a network/timeout one we might recover from
                 last_error = article_data.get('tts_agent_error')
                 if last_error is None or "Network request error" in last_error or "timed out" in last_error:
                      should_generate = True
                 else:
                      logger.info(f"Skipping {filename} due to previous non-recoverable TTS error: {last_error}")

            if should_generate:
                article_id = article_data.get('id', filename.replace('.json',''))
                logger.info(f"Found article needing TTS: {article_id}")

                text_to_speak = article_data.get('seo_agent_results', {}).get('generated_article_body_md', '')

                if text_to_speak:
                    updated_article_data = run_tts_generator_agent(
                        article_data.copy(),
                        text_to_speak,
                        output_audio_dir
                    )

                    try: # Save updated data regardless of TTS success/failure to record errors
                        with open(filepath, 'w', encoding='utf-8') as f_out:
                            json.dump(updated_article_data, f_out, indent=4, ensure_ascii=False)
                        logger.info(f"Updated processed file: {filename}")

                        if not updated_article_data.get('tts_agent_error') and updated_article_data.get('audio_url'):
                            update_site_data_audio(article_id, updated_article_data['audio_url'])
                            generated_count += 1
                        else:
                             failed_count += 1
                    except Exception as save_err:
                        logger.error(f"Failed to save updated JSON for {filename}: {save_err}")
                        failed_count += 1
                    time.sleep(2) # Delay between API calls
                else:
                    logger.warning(f"Skipping {filename}: No 'generated_article_body_md' found.")
                    # Optionally mark it with an error so we don't keep checking?
                    # article_data['tts_agent_error'] = "Missing source text"
                    # with open(filepath, 'w', encoding='utf-8') as f_out: json.dump(article_data, f_out, indent=4, ensure_ascii=False)

            else:
                 logger.debug(f"Skipping {filename}: Audio URL exists or previous non-recoverable error recorded.")

        except json.JSONDecodeError:
            logger.error(f"Skipping invalid JSON file: {filename}")
        except Exception as e:
            logger.exception(f"Unexpected error processing file {filename}: {e}")

    print(f"--- Standalone TTS Run Complete ---")
    print(f"Successfully generated/updated: {generated_count}")
    print(f"Failed attempts this run: {failed_count}")
    logger.info(f"--- Standalone TTS Run Complete. Generated: {generated_count}, Failed: {failed_count} ---")