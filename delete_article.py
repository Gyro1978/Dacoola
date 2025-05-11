# delete_article.py (Now handles URL or ID)
import os
import sys
import json
import argparse
from urllib.parse import urlparse, urljoin # Added urljoin
import traceback
import logging

# Configure logging
logger = logging.getLogger(__name__)

# --- Configuration ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
PUBLIC_DIR = os.path.join(PROJECT_ROOT, 'public')
OUTPUT_HTML_DIR = os.path.join(PUBLIC_DIR, 'articles')
PROCESSED_JSON_DIR = os.path.join(DATA_DIR, 'processed_json')
ALL_ARTICLES_FILE = os.path.join(PUBLIC_DIR, 'all_articles.json')
# --- End Configuration ---

def find_article_by_id(article_id_to_find, all_articles_data):
    """Finds an article by its ID.
       Returns a tuple: (relative_link_path, index_in_list, found_article_dict) or (None, -1, None)"""
    if not all_articles_data or 'articles' not in all_articles_data:
        return None, -1, None
    articles = all_articles_data['articles']
    for index, article in enumerate(articles):
        if isinstance(article, dict) and article.get('id') == article_id_to_find:
            # Ensure link is a relative path starting with 'articles/'
            link = article.get('link', '')
            if not link.startswith('articles/'):
                logger.warning(f"Article ID {article_id_to_find} found, but link '{link}' is not in expected format. Cannot determine HTML path reliably.")
                # You might still want to remove it from all_articles.json if the link is bad
                # but deleting HTML would be risky. For now, we'll proceed assuming it can be derived if present.
            return link, index, article # link might be empty string
    return None, -1, None


def find_articles_by_link(link_path_to_find, all_articles_data):
    """Finds ALL articles matching the relative link path.
       Returns a list of tuples: [(id, index_in_list, relative_link_path_from_entry), ...]"""
    matches = []
    if not all_articles_data or 'articles' not in all_articles_data:
        return matches
    articles = all_articles_data['articles']
    for index, article in enumerate(articles):
        article_link = article.get('link', '')
        if isinstance(article, dict) and isinstance(article_link, str) and article_link.lower() == link_path_to_find.lower():
            matches.append((article.get('id'), index, article_link)) # Store the link from the entry too
    return matches

def remove_file_if_exists(filepath, context="File"):
    """Removes a file if it exists, logs outcome."""
    if not filepath or not isinstance(filepath, str) or not filepath.strip(): # Basic check for valid filepath
        print(f"  - Invalid or empty filepath provided for {context}. Skipping deletion.")
        return True # Treat as "not found" or "nothing to do"

    # Normalize path for safety and consistency
    abs_filepath = os.path.abspath(os.path.join(PROJECT_ROOT, filepath.lstrip('/\\')))
    
    # Security check: Ensure we are deleting within known project subdirectories
    # This is a basic check; more robust path validation might be needed for production systems.
    allowed_delete_roots = [
        os.path.abspath(OUTPUT_HTML_DIR),
        os.path.abspath(PROCESSED_JSON_DIR)
    ]
    
    is_safe_to_delete = False
    for allowed_root in allowed_delete_roots:
        if os.path.commonpath([abs_filepath, allowed_root]) == allowed_root:
            is_safe_to_delete = True
            break
            
    if not is_safe_to_delete:
        print(f"  - SECURITY WARNING: Attempt to delete file outside allowed directories: {filepath}. Operation aborted for this file.")
        return False


    if os.path.exists(abs_filepath):
        try:
            os.remove(abs_filepath)
            print(f"  - Deleted {context}: {os.path.relpath(abs_filepath, PROJECT_ROOT)}")
            return True
        except OSError as e:
            print(f"  - ERROR deleting {context} {abs_filepath}: {e}")
            return False
    else:
        print(f"  - {context} not found: {os.path.relpath(abs_filepath, PROJECT_ROOT)}")
        return True # File not found is not an error in deletion context for this script

def update_all_articles_json(indices_to_remove):
    """Removes articles from all_articles.json by their indices."""
    if not indices_to_remove:
        print("  - No indices provided to remove from all_articles.json.")
        return True
    try:
        if not os.path.exists(ALL_ARTICLES_FILE):
            print(f"  - ERROR: {ALL_ARTICLES_FILE} not found. Cannot update.")
            return False
        with open(ALL_ARTICLES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if 'articles' not in data or not isinstance(data['articles'], list):
            print(f"  - ERROR: Invalid format in {ALL_ARTICLES_FILE}. Expected 'articles' list.")
            return False
            
        current_article_count = len(data['articles'])
        removed_ids_log = []
        
        # Sort indices in descending order to prevent shifting issues
        valid_indices_to_remove = sorted([idx for idx in indices_to_remove if 0 <= idx < current_article_count], reverse=True)
        
        if not valid_indices_to_remove:
            print(f"  - No valid indices to remove from all_articles.json (Total articles: {current_article_count}, Indices given: {indices_to_remove}).")
            return True

        for index_to_pop in valid_indices_to_remove:
            removed_article = data['articles'].pop(index_to_pop)
            removed_ids_log.append(removed_article.get('id', f'at_index_{index_to_pop}'))
            
        if removed_ids_log:
            print(f"  - Removed {len(removed_ids_log)} entries from {os.path.basename(ALL_ARTICLES_FILE)} (IDs/Indices: {', '.join(removed_ids_log)}).")
            with open(ALL_ARTICLES_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"  - Saved changes to {os.path.basename(ALL_ARTICLES_FILE)}.")
        else:
            print(f"  - No articles were actually removed from {os.path.basename(ALL_ARTICLES_FILE)} based on provided indices.")
        return True
    except Exception as e:
        print(f"  - ERROR processing {ALL_ARTICLES_FILE}: {e}")
        traceback.print_exc()
        return False


def delete_article_procedure(user_input_identifier):
    """Handles deletion by URL or ID."""
    print(f"\nProcessing identifier: {user_input_identifier}")
    
    is_url_input = user_input_identifier.startswith('http://') or user_input_identifier.startswith('https://')
    all_ops_ok = True
    
    # Load all_articles.json data once
    try:
        if not os.path.exists(ALL_ARTICLES_FILE):
            print(f"  - CRITICAL ERROR: {ALL_ARTICLES_FILE} not found. Cannot proceed."); return False
        with open(ALL_ARTICLES_FILE, 'r', encoding='utf-8') as f:
            all_articles_data = json.load(f)
        if 'articles' not in all_articles_data or not isinstance(all_articles_data.get('articles'), list):
            print(f"  - CRITICAL ERROR: {ALL_ARTICLES_FILE} has invalid format. Expected 'articles' list."); return False
    except Exception as e:
        print(f"  - CRITICAL ERROR loading {ALL_ARTICLES_FILE}: {e}"); return False

    articles_to_delete_info = [] # List of tuples: (article_id, index_in_all_articles, relative_html_path)

    if is_url_input:
        print(f"  - Input is a URL.")
        try:
            parsed_url = urlparse(user_input_identifier)
            if not parsed_url.path.startswith('/articles/'):
                print(f"  - ERROR: URL path '{parsed_url.path}' must start with '/articles/'.")
                return False
            relative_link_path = parsed_url.path.lstrip('/') # e.g., "articles/slug.html"
        except Exception as e:
            print(f"  - ERROR parsing URL: {e}"); return False
        print(f"  - Target relative HTML path: {relative_link_path}")
        
        matches_by_link = find_articles_by_link(relative_link_path, all_articles_data)
        if not matches_by_link:
            print(f"  - No articles found in {os.path.basename(ALL_ARTICLES_FILE)} with link '{relative_link_path}'."); return True
        
        if len(matches_by_link) == 1:
            article_id, index, link_from_entry = matches_by_link[0]
            articles_to_delete_info.append((article_id, index, link_from_entry))
            print(f"  - Found 1 article by link (ID: {article_id}).")
        else: # Multiple articles share the same HTML link path - problematic data
            print(f"\n  - WARNING: Found {len(matches_by_link)} articles in {os.path.basename(ALL_ARTICLES_FILE)} sharing the link '{relative_link_path}':")
            for art_id, art_idx, art_link in matches_by_link: print(f"    - ID: {art_id} (index {art_idx})")
            # For safety, when multiple articles share a link, only target the first one for deletion from all_articles.json
            # to avoid unintended mass deletion based on a potentially corrupted link. User can re-run for others.
            # However, the HTML file will be deleted once.
            print("  - For safety with duplicate links, will process deletion for the first match. Re-run for others if intended.")
            article_id, index, link_from_entry = matches_by_link[0]
            articles_to_delete_info.append((article_id, index, link_from_entry))

    else: # Input is assumed to be an ID
        article_id_input = user_input_identifier
        print(f"  - Input is an ID: {article_id_input}")
        link_from_entry, index, found_article_dict = find_article_by_id(article_id_input, all_articles_data)
        
        if index == -1:
            print(f"  - Article with ID '{article_id_input}' not found in {os.path.basename(ALL_ARTICLES_FILE)}.")
            # Still try to delete the processed JSON if it exists by ID convention
            processed_json_path_by_id = os.path.join(PROCESSED_JSON_DIR, f"{article_id_input}.json")
            if not remove_file_if_exists(processed_json_path_by_id, "Processed JSON by ID"): all_ops_ok = False
            return all_ops_ok # No HTML to delete if not in all_articles

        print(f"  - Found article by ID. Link from entry: '{link_from_entry}'.")
        articles_to_delete_info.append((article_id_input, index, link_from_entry))

    # --- Perform Deletions based on collected info ---
    if not articles_to_delete_info:
        print("  - No articles identified for deletion.")
        return True

    print("\nStarting deletion process for identified items:")
    indices_to_remove_from_all_articles = []

    for article_id, index_in_list, relative_html_path in articles_to_delete_info:
        print(f"\nProcessing deletion for Article ID: {article_id}")
        indices_to_remove_from_all_articles.append(index_in_list)

        # Delete HTML file
        if relative_html_path and relative_html_path.startswith('articles/'):
            full_html_path = os.path.join(PUBLIC_DIR, relative_html_path)
            if not remove_file_if_exists(full_html_path, "HTML file"): all_ops_ok = False
        elif relative_html_path: # Link exists but is not in expected articles/ format
            print(f"  - WARNING: HTML file path '{relative_html_path}' for ID {article_id} is not in 'articles/' subdirectory. HTML file not deleted by this script for safety.")
        else: # No link_path from all_articles.json entry
            print(f"  - No HTML file path found in {os.path.basename(ALL_ARTICLES_FILE)} for ID {article_id}. Cannot delete HTML.")

        # Delete Processed JSON file
        processed_json_file_path = os.path.join(PROCESSED_JSON_DIR, f"{article_id}.json")
        if not remove_file_if_exists(processed_json_file_path, "Processed JSON"): all_ops_ok = False
        
    # Update all_articles.json (once, after collecting all indices)
    if indices_to_remove_from_all_articles:
        print(f"\nUpdating {os.path.basename(ALL_ARTICLES_FILE)}...")
        if not update_all_articles_json(indices_to_remove_from_all_articles): all_ops_ok = False

    print("-" * 30)
    return all_ops_ok


def main_loop():
    """Runs the deletion process in a loop, accepting URL or ID."""
    print("--- Dacoola Article Deletion Tool ---")
    print("Deletes HTML, processed JSON, and entry from all_articles.json.")
    print("Enter the full article URL (e.g., https://yoursite.com/articles/slug.html) OR just the Article ID.")
    print("Type 'exit' or 'quit' to finish.")

    while True:
        try:
            user_input = input("\nArticle URL or ID (or 'exit'): ").strip()
            if user_input.lower() in ['exit', 'quit']:
                print("Exiting tool."); break
            if not user_input:
                continue

            success = delete_article_procedure(user_input)
            if success:
                print("-> Deletion process for this identifier completed (check logs above for details).")
            else:
                print("-> Deletion process for this identifier encountered errors (check logs above).")

        except KeyboardInterrupt:
            print("\nExiting due to Ctrl+C."); break
        except Exception:
            print("\n--- UNEXPECTED SCRIPT ERROR ---")
            traceback.print_exc()
            print("-------------------------------")

    print("\nRemember to commit changes to your Git repository if deletions were successful.")


if __name__ == "__main__":
    # Setup basic logging for the script itself if needed, distinct from the main app's logger
    # This is useful if functions called (like remove_file_if_exists) use their own module's logger
    # For this script, simple prints are used, but if importing modules that log, configure here.
    # logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    main_loop()