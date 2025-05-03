# delete_article.py
import os
import sys
import json
import argparse # Keep argparse for potential single-use later, but loop is primary
from urllib.parse import urlparse
import traceback # For better error printing in loop

# --- Configuration ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
PUBLIC_DIR = os.path.join(PROJECT_ROOT, 'public')
OUTPUT_HTML_DIR = os.path.join(PUBLIC_DIR, 'articles')
PROCESSED_JSON_DIR = os.path.join(DATA_DIR, 'processed_json')
ALL_ARTICLES_FILE = os.path.join(PUBLIC_DIR, 'all_articles.json')
PROCESSED_IDS_FILE = os.path.join(DATA_DIR, 'processed_article_ids.txt')
# --- End Configuration ---

def find_articles_by_link(link_path, all_articles_data):
    """Finds ALL articles matching the relative link path.
       Returns a list of tuples: [(id, index), (id, index), ...]"""
    matches = []
    if not all_articles_data or 'articles' not in all_articles_data:
        return matches
    articles = all_articles_data['articles']
    for index, article in enumerate(articles):
        # Make comparison case-insensitive and handle potential None links
        article_link = article.get('link', '')
        if isinstance(article, dict) and isinstance(article_link, str) and article_link.lower() == link_path.lower():
            matches.append((article.get('id'), index))
    return matches

def remove_file_if_exists(filepath):
    """Removes a file if it exists, logs outcome."""
    if os.path.exists(filepath):
        try: os.remove(filepath); print(f"  - Deleted file: {filepath}"); return True
        except OSError as e: print(f"  - ERROR deleting file {filepath}: {e}"); return False
    else: print(f"  - File not found: {filepath}"); return True

def update_all_articles(indices_to_remove):
    """Removes articles from all_articles.json by their indices."""
    if not indices_to_remove: return True
    try:
        with open(ALL_ARTICLES_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
        if 'articles' not in data or not isinstance(data['articles'], list): print(f"  - ERROR: Invalid format {ALL_ARTICLES_FILE}"); return False
        removed_count = 0
        for index in sorted(indices_to_remove, reverse=True): # Highest index first
            if 0 <= index < len(data['articles']):
                removed_article = data['articles'].pop(index); print(f"  - Removed entry ID {removed_article.get('id', 'N/A')} from {os.path.basename(ALL_ARTICLES_FILE)}")
                removed_count += 1
            else: print(f"  - WARNING: Invalid index {index} skipped.")
        if removed_count > 0:
            with open(ALL_ARTICLES_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"  - Saved changes to {os.path.basename(ALL_ARTICLES_FILE)}")
        return True
    except Exception as e: print(f"  - ERROR processing {ALL_ARTICLES_FILE}: {e}"); return False

def update_processed_ids(article_ids_to_remove):
    """Removes multiple article IDs from processed_article_ids.txt."""
    if not article_ids_to_remove: return True
    if not os.path.exists(PROCESSED_IDS_FILE): print(f"  - File not found: {PROCESSED_IDS_FILE}. Skip."); return True
    try:
        with open(PROCESSED_IDS_FILE, 'r', encoding='utf-8') as f: lines = f.readlines()
        original_count = len(lines); ids_set_to_remove = set(article_ids_to_remove)
        lines = [line for line in lines if line.strip() not in ids_set_to_remove]
        removed_count = original_count - len(lines)
        if removed_count > 0:
            with open(PROCESSED_IDS_FILE, 'w', encoding='utf-8') as f: f.writelines(lines)
            print(f"  - Removed {removed_count} ID(s) {list(ids_set_to_remove)} from {PROCESSED_IDS_FILE}")
        else: print(f"  - IDs {list(ids_set_to_remove)} not found in {PROCESSED_IDS_FILE}")
        return True
    except IOError as e: print(f"  - ERROR processing {PROCESSED_IDS_FILE}: {e}"); return False

def delete_article_procedure(article_url):
    """Handles the deletion logic for a single URL input."""
    print(f"\nProcessing URL: {article_url}")
    # Extract relative path
    try:
        parsed_url = urlparse(article_url)
        relative_link_path = parsed_url.path.lstrip('/')
        if not relative_link_path.startswith('articles/'):
             print(f"  - ERROR: Path '{relative_link_path}' must start with 'articles/'.")
             return False
    except Exception as e: print(f"  - ERROR parsing URL: {e}"); return False
    print(f"  - Relative path: {relative_link_path}")

    # Load data
    try:
        if not os.path.exists(ALL_ARTICLES_FILE): print(f"  - ERROR: {ALL_ARTICLES_FILE} not found."); return False
        with open(ALL_ARTICLES_FILE, 'r', encoding='utf-8') as f: all_articles_data = json.load(f)
    except Exception as e: print(f"  - ERROR loading {ALL_ARTICLES_FILE}: {e}"); return False

    # Find matches
    matches = find_articles_by_link(relative_link_path, all_articles_data)
    if not matches: print(f"  - Article not found for path '{relative_link_path}'."); return True # Not an error, just nothing to do

    items_to_delete = []
    if len(matches) == 1:
        print(f"  - Found 1 article.")
        article_id, article_index = matches[0]
        html_file_path = os.path.join(PUBLIC_DIR, relative_link_path)
        processed_json_path = os.path.join(PROCESSED_JSON_DIR, f"{article_id}.json")
        items_to_delete.append((article_id, article_index, html_file_path, processed_json_path))
    else:
        print(f"\n  - WARNING: Found {len(matches)} articles with link '{relative_link_path}':")
        for article_id, article_index in matches: print(f"    - ID: {article_id} (index {article_index})")
        while True:
            choice = input("  - Delete only the FIRST (1) or ALL entries (2)? [1/2]: ").strip()
            if choice == '1':
                print("  - Selecting first entry for deletion."); article_id, article_index = matches[0]
                html_path = os.path.join(PUBLIC_DIR, relative_link_path); json_path = os.path.join(PROCESSED_JSON_DIR, f"{article_id}.json")
                items_to_delete.append((article_id, article_index, html_path, json_path)); break
            elif choice == '2':
                print("  - Selecting ALL entries for deletion.")
                for article_id, article_index in matches:
                    html_path = os.path.join(PUBLIC_DIR, relative_link_path); json_path = os.path.join(PROCESSED_JSON_DIR, f"{article_id}.json")
                    items_to_delete.append((article_id, article_index, html_path, json_path)); break
            else: print("  - Invalid choice.")

    # Perform deletions
    print("\nStarting deletions:")
    all_ops_ok = True
    indices_to_remove_from_json = [item[1] for item in items_to_delete]
    ids_to_remove_from_processed = [item[0] for item in items_to_delete]

    # Delete files first
    deleted_html_paths = set() # Track unique HTML paths to delete only once
    for article_id, _, html_path, json_path in items_to_delete:
        print(f"\nProcessing files for ID: {article_id}")
        if html_path not in deleted_html_paths: # Only try deleting HTML once per link
             if remove_file_if_exists(html_path): deleted_html_paths.add(html_path)
             else: all_ops_ok = False
        if not remove_file_if_exists(json_path): all_ops_ok = False

    # Update JSON and ID list files if file deletions seemed ok (or file not found)
    if all_ops_ok:
        print(f"\nUpdating {os.path.basename(ALL_ARTICLES_FILE)}...")
        if not update_all_articles(indices_to_remove_from_json): all_ops_ok = False

        print(f"\nUpdating {os.path.basename(PROCESSED_IDS_FILE)}...")
        if not update_processed_ids(ids_to_remove_from_processed): all_ops_ok = False
    else:
         print("\nSkipping JSON/ID file updates due to file deletion errors.")

    print("-" * 20)
    return all_ops_ok


def main_loop():
    """Runs the deletion process in a loop."""
    print("--- Dacoola Article Deletion Tool ---")
    print("Enter the full URL of the article to delete.")
    print("Type 'exit' or 'quit' to finish.")

    while True:
        try:
            user_input = input("\nArticle URL (or 'exit'): ").strip()
            if user_input.lower() in ['exit', 'quit']:
                print("Exiting.")
                break
            if not user_input:
                continue

            if not (user_input.startswith('http://') or user_input.startswith('https://')):
                print("  - ERROR: Please enter a full URL starting with http:// or https://")
                continue

            delete_article_procedure(user_input)

        except KeyboardInterrupt:
            print("\nExiting due to Ctrl+C.")
            break
        except Exception:
            print("\n--- UNEXPECTED ERROR ---")
            traceback.print_exc()
            print("------------------------")
            print("An error occurred. Please check the details above.")

    print("\nRemember to commit any changes made to the JSON/ID files and deleted files.")


if __name__ == "__main__":
    # You could potentially add command-line args back here if needed
    # for single deletions without the loop, but the loop is now default.
    main_loop()