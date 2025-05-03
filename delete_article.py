# delete_article.py
import os
import sys
import json
import argparse
from urllib.parse import urlparse
import traceback

# --- Configuration ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
PUBLIC_DIR = os.path.join(PROJECT_ROOT, 'public')
OUTPUT_HTML_DIR = os.path.join(PUBLIC_DIR, 'articles')
PROCESSED_JSON_DIR = os.path.join(DATA_DIR, 'processed_json')
ALL_ARTICLES_FILE = os.path.join(PUBLIC_DIR, 'all_articles.json')
# PROCESSED_IDS_FILE is removed as we don't modify it here anymore
# --- End Configuration ---

def find_articles_by_link(link_path, all_articles_data):
    """Finds ALL articles matching the relative link path.
       Returns a list of tuples: [(id, index), (id, index), ...]"""
    matches = []
    if not all_articles_data or 'articles' not in all_articles_data:
        return matches
    articles = all_articles_data['articles']
    for index, article in enumerate(articles):
        article_link = article.get('link', '')
        # Case-insensitive comparison
        if isinstance(article, dict) and isinstance(article_link, str) and article_link.lower() == link_path.lower():
            matches.append((article.get('id'), index))
    return matches

def remove_file_if_exists(filepath):
    """Removes a file if it exists, logs outcome."""
    if os.path.exists(filepath):
        try:
            os.remove(filepath); print(f"  - Deleted file: {os.path.relpath(filepath, PROJECT_ROOT)}")
            return True
        except OSError as e: print(f"  - ERROR deleting file {filepath}: {e}"); return False
    else: print(f"  - File not found: {os.path.relpath(filepath, PROJECT_ROOT)}"); return True

def update_all_articles(indices_to_remove):
    """Removes articles from all_articles.json by their indices."""
    if not indices_to_remove: return True
    try:
        with open(ALL_ARTICLES_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
        if 'articles' not in data or not isinstance(data['articles'], list): print(f"  - ERROR: Invalid format {ALL_ARTICLES_FILE}"); return False
        removed_count = 0
        # Process indices in descending order to avoid messing up subsequent indices
        for index in sorted(indices_to_remove, reverse=True):
            if 0 <= index < len(data['articles']):
                removed_article = data['articles'].pop(index); print(f"  - Removed entry ID {removed_article.get('id', 'N/A')} from {os.path.basename(ALL_ARTICLES_FILE)}")
                removed_count += 1
            else: print(f"  - WARNING: Invalid index {index} skipped.")
        if removed_count > 0:
            with open(ALL_ARTICLES_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"  - Saved changes to {os.path.basename(ALL_ARTICLES_FILE)}")
        return True
    except Exception as e: print(f"  - ERROR processing {ALL_ARTICLES_FILE}: {e}"); return False


def delete_article_procedure(article_url):
    """Handles the deletion logic for a single URL input."""
    print(f"\nProcessing URL: {article_url}")
    # Extract relative path
    try:
        parsed_url = urlparse(article_url)
        # Ensure path starts with /articles/ but store without leading / for joins
        if not parsed_url.path.startswith('/articles/'):
            print(f"  - ERROR: URL path '{parsed_url.path}' must start with '/articles/'.")
            return False
        relative_link_path = parsed_url.path.lstrip('/') # e.g., "articles/slug.html"
    except Exception as e: print(f"  - ERROR parsing URL: {e}"); return False
    print(f"  - Relative path: {relative_link_path}")

    # Load data
    try:
        if not os.path.exists(ALL_ARTICLES_FILE): print(f"  - ERROR: {ALL_ARTICLES_FILE} not found."); return False
        with open(ALL_ARTICLES_FILE, 'r', encoding='utf-8') as f: all_articles_data = json.load(f)
    except Exception as e: print(f"  - ERROR loading {ALL_ARTICLES_FILE}: {e}"); return False

    # Find matches
    matches = find_articles_by_link(relative_link_path, all_articles_data)
    if not matches: print(f"  - Article not found for path '{relative_link_path}'."); return True

    items_to_delete_info = [] # List to hold tuples of (id, index)
    if len(matches) == 1:
        print(f"  - Found 1 article.")
        items_to_delete_info.append(matches[0])
    else:
        print(f"\n  - WARNING: Found {len(matches)} articles with link '{relative_link_path}':")
        for article_id, article_index in matches: print(f"    - ID: {article_id} (index {article_index})")
        while True:
            choice = input("  - Delete only the FIRST (1) or ALL matching entries (2)? [1/2]: ").strip()
            if choice == '1':
                print("  - Selecting first entry for deletion."); items_to_delete_info.append(matches[0]); break
            elif choice == '2':
                print("  - Selecting ALL matching entries for deletion."); items_to_delete_info.extend(matches); break
            else: print("  - Invalid choice.")

    # --- Perform Deletions ---
    print("\nStarting deletion process:")
    all_ops_ok = True
    indices_to_remove_from_json = [item[1] for item in items_to_delete_info] # Get indices

    # Delete HTML file(s)
    html_file_path = os.path.join(PUBLIC_DIR, relative_link_path)
    print(f"\nProcessing HTML file: {os.path.relpath(html_file_path, PROJECT_ROOT)}")
    if not remove_file_if_exists(html_file_path): all_ops_ok = False

    # --- SKIPPED ---
    print(f"\nSkipping deletion of processed JSON files in {os.path.relpath(PROCESSED_JSON_DIR, PROJECT_ROOT)} as requested.")

    # Update JSON list file
    print(f"\nUpdating {os.path.basename(ALL_ARTICLES_FILE)}...")
    if not update_all_articles(indices_to_remove_from_json): all_ops_ok = False

    # --- SKIPPED ---
    # Removed the print statement referencing the deleted variable
    print(f"\nSkipping update of processed_article_ids.txt as requested.")

    print("-" * 20)
    return all_ops_ok


def main_loop():
    """Runs the deletion process in a loop."""
    print("--- Dacoola Article Deletion Tool ---")
    print("Removes HTML file and entry from all_articles.json.")
    print("Keeps processed JSON and entry in processed_ids.txt.")
    print("Enter the full URL of the article to delete.")
    print("Type 'exit' or 'quit' to finish.")

    while True:
        try:
            user_input = input("\nArticle URL (or 'exit'): ").strip()
            if user_input.lower() in ['exit', 'quit']: print("Exiting."); break
            if not user_input: continue
            if not (user_input.startswith('http://') or user_input.startswith('https://')): print("  - ERROR: Please enter a full URL."); continue

            success = delete_article_procedure(user_input)
            if success: print("-> Deletion process completed for this URL (check logs for details).")
            else: print("-> Deletion process encountered errors for this URL.")

        except KeyboardInterrupt: print("\nExiting due to Ctrl+C."); break
        except Exception: print("\n--- UNEXPECTED ERROR ---"); traceback.print_exc(); print("------------------------")

    print("\nRemember to commit any changes made (deleted HTML, updated all_articles.json).")


if __name__ == "__main__":
    main_loop()