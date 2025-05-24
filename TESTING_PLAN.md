# Testing Plan: Modal and DeepSeek R1 Integration

This document outlines the testing strategy to ensure the successful integration of Modal for hosting the DeepSeek R1 model and its usage by the various AI agents within the pipeline.

## 1. Prerequisite: Modal Endpoint Verification

Before testing the individual agents or the full pipeline, it's crucial to verify that the Modal endpoint itself is functioning correctly and adheres to the expected contract.

*   **Deploy the Modal Script**:
    *   Ensure your Modal deployment script (e.g., `modal_script.py`, which contains the `DeepSeekModel` class or similar) is updated as per the `MODAL_INTEGRATION_GUIDE.md`.
    *   Deploy it to your Modal workspace:
        ```bash
        modal deploy modal_script.py 
        ```
        (Replace `modal_script.py` with the actual name of your script if different.)

*   **Verify `generate` Method Output**:
    *   The `DeepSeekModel` class's `generate` method (or the equivalent method called by the agents) **MUST** return a JSON object (Python dictionary) with the following structure:
        ```json
        {
            "choices": [
                {
                    "message": {
                        "content": "YOUR_GENERATED_TEXT_HERE"
                    }
                }
            ]
        }
        ```
    *   **Testing Methods**:
        *   **Using `modal run ...::main` (if you have a local test function in your Modal script):**
            If your `modal_script.py` has a local test function (e.g., a `main()` function decorated with `@stub.local_entrypoint()`) that calls the `generate` method, you can invoke it:
            ```bash
            modal run modal_script.py 
            ```
            Inspect the output to ensure it matches the required JSON structure.
        *   **Using `curl` (if deployed as a web endpoint)**:
            If your `DeepSeekModel`'s `generate` method is exposed as a web endpoint (e.g., via `@stub.web_endpoint()`):
            ```bash
            curl -X POST -H "Content-Type: application/json" \
                 -d '{"messages": [{"role": "user", "content": "Test prompt"}], "max_new_tokens": 50}' \
                 <YOUR_MODAL_WEB_ENDPOINT_URL>
            ```
            Replace `<YOUR_MODAL_WEB_ENDPOINT_URL>` with the actual URL provided after deployment. Check the response.
        *   **Using Modal Python Client in a separate script**:
            ```python
            import modal

            # Ensure MODAL_APP_NAME and MODAL_CLASS_NAME match your Modal script
            MODAL_APP_NAME = "deepseek-inference-app" 
            MODAL_CLASS_NAME = "DeepSeekModel"

            try:
                ModelClass = modal.Function.lookup(MODAL_APP_NAME, MODAL_CLASS_NAME)
                if not ModelClass:
                    print(f"Could not find Modal function {MODAL_APP_NAME}/{MODAL_CLASS_NAME}.")
                else:
                    model_instance = ModelClass()
                    test_messages = [{"role": "user", "content": "Hello DeepSeek on Modal!"}]
                    result = model_instance.generate.remote(messages=test_messages, max_new_tokens=50)
                    print("Modal Endpoint Response:")
                    print(json.dumps(result, indent=2))
                    
                    # Basic validation
                    if (isinstance(result, dict) and 
                        "choices" in result and isinstance(result["choices"], list) and
                        len(result["choices"]) > 0 and
                        isinstance(result["choices"][0], dict) and
                        "message" in result["choices"][0] and isinstance(result["choices"][0]["message"], dict) and
                        "content" in result["choices"][0]["message"] and isinstance(result["choices"][0]["message"]["content"], str)):
                        print("\nSUCCESS: Output structure appears correct.")
                    else:
                        print("\nERROR: Output structure is INCORRECT.")

            except Exception as e:
                print(f"Error testing Modal endpoint: {e}")
            ```
    *   **Focus**: Confirm that the `content` field contains the actual generated text and that the nested structure is exactly as specified.

## 2. Individual Agent Testing

Once the Modal endpoint is verified, test each agent that was modified to use Modal.

*   **Modified Agents**:
    *   `src/agents/article_review_agent.py`
    *   `src/agents/description_generator_agent.py`
    *   `src/agents/filter_news_agent.py`
    *   `src/agents/keyword_generator_agent.py`
    *   `src/agents/markdown_generator_agent.py`
    *   `src/agents/section_writer_agent.py`
    *   `src/agents/seo_review_agent.py`
    *   `src/agents/title_generator_agent.py`

*   **Instructions**:
    *   For each agent file listed above, navigate to the project root directory in your terminal.
    *   Run its standalone test block:
        ```bash
        python src/agents/your_agent_name_here.py
        ```
        (e.g., `python src/agents/article_review_agent.py`)

*   **Expected Outcomes**:
    *   The script should execute without Python errors.
    *   Logs should indicate successful calls to the Modal endpoint (e.g., "Modal call successful...").
    *   The agent should correctly parse the response from the Modal service.
    *   The agent should produce its expected output (e.g., a review JSON, generated titles, keywords, etc.).
    *   There should be no errors related to API keys or direct HTTP requests for the LLM calls handled by Modal.
    *   Review any warnings or errors printed to the console, especially those related to "Modal API response missing content or malformed" or "Could not find Modal function".

## 3. Full Pipeline Testing

After individual agents are confirmed to be working with Modal, test the entire article generation pipeline.

*   **Instruction**:
    *   From the project root directory, run the main pipeline script:
        ```bash
        python src/main.py --news-feed-url <your_test_rss_feed_url> 
        ```
        (Or any other arguments your `main.py` script typically uses for testing.)

*   **Expected Outcomes**:
    *   The pipeline should complete successfully, generating one or more articles.
    *   There should be no LLM-related errors in the logs from any of the modified agents.
    *   The quality of the generated content (titles, descriptions, keywords, article body sections, reviews) should be consistent with expectations for the DeepSeek R1 model.
    *   Final output files (e.g., Markdown, JSON data files) should be correctly generated and populated.

## 4. Error Handling and Retry Logic (Optional)

This section is for more advanced testing if you have the capability to simulate transient network issues or temporary Modal service unavailability.

*   **Simulating Errors**: This can be challenging. Potential methods (use with caution):
    *   Temporarily undeploying the Modal app (`modal app stop <MODAL_APP_NAME>`) while an agent is about to make a call.
    *   If your network allows, briefly interrupting network connectivity for the machine running the agent script.
*   **Expected Behavior**:
    *   The agent's logs should show retry attempts (e.g., "Modal API call failed (attempt 1/3)... Retrying in Xs.").
    *   If the "error" persists beyond the configured number of retries, the agent should fail gracefully (e.g., return a fallback value or error message as designed, rather than crashing).

## 5. Reporting Issues

If you encounter issues during testing, please provide the following information to help with debugging:

*   **Agent Name**: Specify which agent script was being tested (e.g., `article_review_agent.py`).
*   **Phase of Testing**: Indicate if the issue occurred during "Modal Endpoint Verification," "Individual Agent Testing," or "Full Pipeline Testing."
*   **Error Messages**: Copy the full error message and any relevant traceback from the console or logs.
*   **Log Snippets**: Provide relevant snippets from the agent's log output, especially lines around the error or unexpected behavior.
*   **Input Data (if relevant)**: For individual agent tests, if the issue seems data-dependent, provide the sample input data being used (e.g., the `test_article_data` dictionary from the `if __name__ == "__main__":` block).
*   **Modal Application Logs**: If the issue seems to stem from the Modal endpoint itself, check the logs for your Modal application:
    ```bash
    modal app logs <MODAL_APP_NAME> 
    ```
    (Replace `<MODAL_APP_NAME>` with the actual name of your deployed Modal application, e.g., `deepseek-inference-app`). Provide any relevant errors from these logs.
*   **Steps Taken**: Briefly describe the steps you took leading up to the error.

Clear and detailed reports will facilitate faster resolution of any problems.Okay, I have generated the `TESTING_PLAN.md` file with the outlined strategy.
