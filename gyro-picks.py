# gyro-picks.py (v2.1 - Streamlined Advanced Add, Auto-Trending for Breaking)

import sys
import os
import json
import hashlib
import logging
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

# --- Path Setup & Project Root ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv

dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)

# --- Configuration ---
DATA_DIR_GYRO = os.path.join(PROJECT_ROOT, 'data')
RAW_WEB_RESEARCH_OUTPUT_DIR_GYRO = os.path.join(DATA_DIR_GYRO, 'raw_web_research')
AUTHOR_NAME_DEFAULT_GYRO = os.getenv('AUTHOR_NAME', 'Gyro Pick Team')
YOUR_WEBSITE_NAME_GYRO = os.getenv('YOUR_WEBSITE_NAME', 'Dacoola')

# --- Logging Setup ---
log_file_path_gyro = os.path.join(PROJECT_ROOT, 'gyro-picks.log')
gyro_logger = logging.getLogger('GyroPicksTool_v2.1') # Version bump
if not gyro_logger.handlers:
    gyro_logger.propagate = False
    gyro_logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    ch.setFormatter(ch_formatter)
    gyro_logger.addHandler(ch)
    try:
        os.makedirs(os.path.dirname(log_file_path_gyro), exist_ok=True)
        fh = logging.FileHandler(log_file_path_gyro, encoding='utf-8', mode='a')
        fh.setLevel(logging.DEBUG)
        fh_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')
        fh.setFormatter(fh_formatter)
        gyro_logger.addHandler(fh)
    except Exception as e:
        gyro_logger.error(f"Failed to set up file logging for GyroPicks: {e}")


# --- GyroPicks Helper Functions ---
def ensure_gyro_directories_gyro():
    dirs_to_check = [DATA_DIR_GYRO, RAW_WEB_RESEARCH_OUTPUT_DIR_GYRO]
    for d_path in dirs_to_check:
        os.makedirs(d_path, exist_ok=True)
    gyro_logger.info(f"Ensured GyroPicks directories. Raw output to: {RAW_WEB_RESEARCH_OUTPUT_DIR_GYRO}")

def generate_gyro_article_id_gyro(url_for_hash):
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')
    url_hash_part = hashlib.sha1(url_for_hash.encode('utf-8')).hexdigest()[:10]
    return f"gyro-{timestamp}-{url_hash_part}"

# --- UI Input Functions ---
def get_quick_add_urls_gyro():
    urls = []
    print("\n--- Gyro Pick - Quick Add Mode ---")
    print("Enter article URL(s). Press Enter after each URL. Type 'done' when finished.")
    print("Optionally, add a title after the URL separated by '||'. Example: https://example.com/article || My Awesome Title")
    while True:
        raw_input_str = input(f"Quick Add URL & Optional Title {len(urls) + 1} (or 'done'): ").strip()
        if raw_input_str.lower() == 'done':
            if not urls:
                print("No URLs entered. Exiting Quick Add.")
                return []
            break

        url_input = raw_input_str
        title_input = None
        if "||" in raw_input_str:
            parts = raw_input_str.split("||", 1)
            url_input = parts[0].strip()
            title_input = parts[1].strip()

        if not (url_input.startswith('http://') or url_input.startswith('https://')):
            print("Error: URL must start with http:// or https://. Please try again.")
            continue
        try:
            parsed = urlparse(url_input)
            assert parsed.scheme and parsed.netloc
            urls.append({'url': url_input, 'title': title_input})
            print(f"Added URL: {url_input}" + (f" with Title: {title_input}" if title_input else ""))
        except Exception:
            print(f"Error: Invalid URL format for '{url_input}'. Please enter a valid URL.")
    return urls

def get_advanced_add_inputs_gyro():
    urls_data = []
    print("\n--- Gyro Pick - Advanced Add Mode ---")
    primary_url = ""
    primary_title_input = None
    while not primary_url:
        raw_primary_input = input("Enter PRIMARY article URL (Optional: || Title for this URL): ").strip()
        url_input_temp = raw_primary_input
        title_input_temp = None
        if "||" in raw_primary_input:
            parts = raw_primary_input.split("||", 1)
            url_input_temp = parts[0].strip()
            title_input_temp = parts[1].strip()

        if not (url_input_temp.startswith('http://') or url_input_temp.startswith('https://')):
            print("Error: Primary URL must start with http:// or https://.")
            continue
        try:
            urlparse(url_input_temp)
            primary_url = url_input_temp
            primary_title_input = title_input_temp
            urls_data.append({'url': primary_url, 'title': primary_title_input})
        except Exception:
            print("Error: Invalid primary URL format.")

    print("Enter any SECONDARY URLs (Optional: || Title for this URL). Type 'done' when finished.")
    while True:
        raw_secondary_input = input(f"Secondary URL {len(urls_data)} (or 'done'): ").strip()
        if raw_secondary_input.lower() == 'done': break

        url_input_temp_sec = raw_secondary_input
        title_input_temp_sec = None
        if "||" in raw_secondary_input:
            parts = raw_secondary_input.split("||", 1)
            url_input_temp_sec = parts[0].strip()
            title_input_temp_sec = parts[1].strip()

        if not (url_input_temp_sec.startswith('http://') or url_input_temp_sec.startswith('https://')):
            print("Error: URL must start with http:// or https://.")
            continue
        try:
            urlparse(url_input_temp_sec)
            urls_data.append({'url': url_input_temp_sec, 'title': title_input_temp_sec})
            print(f"Added secondary URL: {url_input_temp_sec}" + (f" with Title: {title_input_temp_sec}" if title_input_temp_sec else ""))
        except Exception: print("Error: Invalid secondary URL format.")

    user_importance = "Interesting"
    while True:
        choice = input("Mark article as (1) Interesting or (2) Breaking [Default: 1-Interesting]: ").strip()
        if choice == '1' or not choice: user_importance = "Interesting"; break
        elif choice == '2': user_importance = "Breaking"; break
        else: print("Invalid choice. Please enter 1 or 2.")

    # --- MODIFIED LOGIC FOR TRENDING AND MANUAL CONTENT ---
    is_trending = (user_importance == "Breaking") # Auto-set trending if breaking
    if is_trending:
        print("Article marked as 'Breaking', so 'Trending Pick' is automatically set to YES.")
    else: # Ask only if not breaking
        is_trending = input("Mark as 'Trending Pick' (highlight in banner)? (yes/no) [Default: no]: ").strip().lower() == 'yes'

    manual_content_input = None # Default to no manual content
    print("Article content will be scraped automatically by the pipeline.")
    # --- END OF MODIFIED LOGIC ---

    user_img = None
    if input("Provide a direct image URL (for featured image)? (yes/no) [Default: no, pipeline will search]: ").strip().lower() == 'yes':
        img_input = input("Paste direct image URL: ").strip()
        if img_input.startswith('http://') or img_input.startswith('https://'): user_img = img_input
        else: print("Warning: Invalid image URL provided. Pipeline will attempt to search instead.")

    return urls_data, user_importance, is_trending, user_img, manual_content_input


def get_manual_content_input(prompt_message): # This function is now effectively unused by get_advanced_add_inputs_gyro
    print(f"\n{prompt_message}")
    print("Enter/Paste your content. Type 'END_CONTENT' (all caps) on a new line when done.")
    lines = []
    while True:
        line = input()
        if line == "END_CONTENT":
            break
        lines.append(line)
    return "\n".join(lines)

# --- Gyro Pick Specific Data Preparation ---
def save_raw_gyro_pick_for_pipeline_gyro(article_id, data):
    filepath = os.path.join(RAW_WEB_RESEARCH_OUTPUT_DIR_GYRO, f"{article_id}.json")
    try:
        with open(filepath, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
        gyro_logger.info(f"SAVED RAW GYRO PICK (Data Prep Mode): {os.path.basename(filepath)} for main pipeline processing.")
        return True
    except Exception as e:
        gyro_logger.error(f"Failed to save raw Gyro Pick JSON {os.path.basename(filepath)}: {e}")
        return False

def create_raw_gyro_pick_file_gyro(urls_with_titles, mode,
                               user_importance_override=None,
                               user_is_trending_pick=None,
                               user_provided_image_url=None,
                               manual_content_override=None): # manual_content_override will be None now
    if not urls_with_titles:
        gyro_logger.error("No URLs provided for Gyro Pick. Skipping."); return False

    primary_url_data = urls_with_titles[0]
    primary_url = primary_url_data['url']
    primary_title = primary_url_data.get('title')

    gyro_logger.info(f"--- Preparing Gyro Pick Data ({mode} mode) for URL: {primary_url} ---")

    gyro_pick_id = generate_gyro_article_id_gyro(primary_url)
    raw_gyro_filepath = os.path.join(RAW_WEB_RESEARCH_OUTPUT_DIR_GYRO, f"{gyro_pick_id}.json")
    if os.path.exists(raw_gyro_filepath):
        gyro_logger.warning(f"Raw Gyro Pick file for ID {gyro_pick_id} from {primary_url} already exists. Skipping.")
        return False

    final_title_to_use = primary_title if primary_title else f"Content from {urlparse(primary_url).netloc}"
    if not primary_title:
        gyro_logger.info(f"No specific title provided by user for {primary_url}. Using default: '{final_title_to_use}'. TitleAgent will generate final.")

    # Text will always be None here, relying on main.py's web_research_agent
    final_text_to_use = None # Changed from manual_content_override
    gyro_logger.info(f"No manual text collected by GyroPicks. Main pipeline's WebResearchAgent will attempt to scrape for {primary_url}.")

    raw_article_data_for_pipeline = {
        'id': gyro_pick_id,
        'original_source_url': primary_url,
        'all_source_links_gyro': [item['url'] for item in urls_with_titles],
        'initial_title_from_web': final_title_to_use,
        'raw_scraped_text': final_text_to_use, # This will be None
        'research_topic': f"Gyro Pick - {mode}",
        'retrieved_at': datetime.now(timezone.utc).isoformat(),
        'is_gyro_pick': True,
        'gyro_pick_mode': mode,
        'user_importance_override_gyro': user_importance_override,
        'user_is_trending_pick_gyro': user_is_trending_pick,
        'user_provided_image_url_gyro': user_provided_image_url,
        'selected_image_url': user_provided_image_url,
        'author': AUTHOR_NAME_DEFAULT_GYRO,
        'published_iso': datetime.now(timezone.utc).isoformat()
    }

    if save_raw_gyro_pick_for_pipeline_gyro(gyro_pick_id, raw_article_data_for_pipeline):
        gyro_logger.info(f"--- Successfully prepared Gyro Pick Data: {gyro_pick_id} ('{final_title_to_use}') ---")
        return True
    else:
        gyro_logger.error(f"Failed to save raw Gyro Pick data for {gyro_pick_id}.")
        return False

# --- Main Interactive Loop ---
if __name__ == "__main__":
    ensure_gyro_directories_gyro()
    gyro_logger.info("GyroPicks Tool Started (v2.1 - Streamlined Data Prep).") # Version bump
    gyro_logger.info(f"Raw Gyro Pick JSONs will be saved to: {RAW_WEB_RESEARCH_OUTPUT_DIR_GYRO}")
    gyro_logger.info("Run main.py to process these files through the full pipeline.")

    # Selenium driver not needed in this version of gyro-picks.py
    # as it's only a data preparation tool.

    while True:
        print("\n======================================")
        print("       Gyro Pick Input Options        ")
        print("======================================")
        print("(1) Quick Add (URLs + Optional Titles)")
        print("(2) Advanced Add (URLs, Importance, Image Hint)") # Removed "Optional Manual Content"
        print("(0) Exit Gyro Picks Tool")
        print("--------------------------------------")
        mode_choice = input("Choose an option (0-2): ").strip()

        if mode_choice == '0': gyro_logger.info("Exiting Gyro Picks tool."); break
        elif mode_choice == '1':
            urls_data_quick = get_quick_add_urls_gyro()
            if not urls_data_quick: continue
            processed_count_quick = 0
            for i, url_data_item in enumerate(urls_data_quick):
                gyro_logger.info(f"\nProcessing Quick Add Gyro Pick {i+1}/{len(urls_data_quick)}: {url_data_item['url']}")
                # Passing None for manual_content_override
                if create_raw_gyro_pick_file_gyro([url_data_item], mode="Quick", manual_content_override=None):
                    processed_count_quick +=1
                if i < len(urls_data_quick) - 1: gyro_logger.info("Brief pause..."); time.sleep(0.5)
            gyro_logger.info(f"Quick Add finished. Prepared {processed_count_quick}/{len(urls_data_quick)} items.")
        elif mode_choice == '2':
            # get_advanced_add_inputs_gyro now returns: urls_data, importance, trending, user_img, manual_content (which will be None)
            adv_urls_data, imp, trend, img_url_adv, manual_content_result = get_advanced_add_inputs_gyro()
            if not adv_urls_data: continue
            gyro_logger.info(f"\nProcessing Advanced Add Gyro Pick for primary URL: {adv_urls_data[0]['url']}")
            create_raw_gyro_pick_file_gyro(adv_urls_data, mode="Advanced",
                                      user_importance_override=imp,
                                      user_is_trending_pick=trend,
                                      user_provided_image_url=img_url_adv,
                                      manual_content_override=None) # Always pass None
        else: print("Invalid choice. Please enter 0, 1, or 2.")

    gyro_logger.info("--- Gyro Picks tool session finished. ---")
    print("\nGyro Picks tool exited. Run main.py to process any queued picks.")