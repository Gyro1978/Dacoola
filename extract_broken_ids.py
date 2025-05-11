# extract_broken_ids.py (Reads from dacola.log)
import re
import os

# --- Configuration ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__)) # Assumes script is in project root
# Point directly to dacola.log in the project root
LOG_FILE_PATH = os.path.join(PROJECT_ROOT, 'dacola.log') 

# Regex to find the lines and capture the JSON filename (which is the ID + .json)
# It looks for "Skipping JSON missing id/slug for HTML regen: " followed by the filename.
# It captures the part before ".json".
# Making it more robust to handle potential variations in log formatting around the ID
regex = r"Skipping JSON missing id/slug for HTML regen:\s*([\w\*\-]+)\.json"

def extract_ids_from_log(log_filepath):
    found_ids = set() # Use a set to store unique IDs
    if not os.path.exists(log_filepath):
        print(f"ERROR: Log file not found at {log_filepath}")
        print("Please ensure 'dacola.log' exists in the project root or modify LOG_FILE_PATH.")
        return []
        
    print(f"Reading log file: {log_filepath}\n")
    try:
        with open(log_filepath, 'r', encoding='utf-8') as f:
            # Read line by line to handle potentially very large log files
            for line in f:
                match = re.search(regex, line)
                if match:
                    article_id = match.group(1)
                    # Skip if the ID contains '***' as it's incomplete from your log paste
                    if '***' not in article_id:
                        found_ids.add(article_id)
            
    except Exception as e:
        print(f"Error reading or processing log file {log_filepath}: {e}")
        return []
            
    if not found_ids:
        print(f"No IDs matching the pattern 'Skipping JSON missing id/slug' were found in {os.path.basename(log_filepath)}.")
    else:
        print(f"Found the following unique IDs from '{os.path.basename(log_filepath)}' that were skipped due to missing id/slug (for HTML regen):")
        
    return sorted(list(found_ids))

if __name__ == "__main__":
    broken_ids = extract_ids_from_log(LOG_FILE_PATH)
    if broken_ids:
        print("\n--- Copy the IDs below and paste them one by one into delete_article.py when prompted ---")
        for article_id in broken_ids:
            print(article_id)
        print("\n--- End of ID list ---")
        print(f"\nTotal unique IDs extracted: {len(broken_ids)}")
    else:
        print(f"\nNo actionable IDs found in {os.path.basename(LOG_FILE_PATH)} for deletion based on the specified pattern.")