# Integrating Modal for LLM Calls: Environment and Deployment Guide

This document outlines the necessary changes to your environment variables (`.env` file) and Modal deployment script (`modal_script.py` or similar) to transition LLM calls from direct API requests to a Modal-hosted service.

## 1. `.env` File Modifications

The following adjustments should be made to your `.env` file:

*   **`LLM_API_KEY` and `LLM_API_URL`**:
    *   These variables, previously used for direct API calls to services like DeepSeek, are **no longer directly used by the agents** that have been updated to use Modal.
    *   If no other parts of your system rely on these variables, you can **comment them out or remove them** to avoid confusion.
    *   Example:
        ```env
        # LLM_API_KEY=your_previous_api_key
        # LLM_API_URL=your_previous_api_url
        ```

*   **Modal Authentication (`MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`)**:
    *   To deploy and run applications on Modal, you typically need to authenticate. This is usually done by setting `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` as environment variables in the environment where you run `modal deploy` or `modal run`.
    *   These are obtained when you set up your Modal account and configure the Modal CLI. They are often stored in a Modal-specific configuration file (`~/.modal.toml`) or can be set as environment variables, especially in CI/CD environments.
    *   Ensure these are correctly configured in any environment that will interact with Modal for deployment or execution.
        ```env
        # Ensure these are set in your deployment environment or ~/.modal.toml
        # MODAL_TOKEN_ID=ak-xxxxxxxxxxxxxxxxxxxxxxx
        # MODAL_TOKEN_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
        ```

*   **Agent-Specific Model Names (e.g., `ARTICLE_REVIEW_AGENT_MODEL`)**:
    *   The default model names for agents like `ArticleReviewAgent`, `DescriptionGeneratorAgent`, etc., have been updated in the agent code to typically default to `"deepseek-R1"` (or a similar generic identifier).
    *   This signifies that the primary model selection logic now resides within the Modal deployment script.
    *   However, you can **still override these defaults via the `.env` file** if you wish to pass a different model identifier or configuration string to the Modal class (though the Modal class itself will ultimately determine which Hugging Face model it loads based on its internal `MODEL_ID`).
    *   Example:
        ```env
        # ARTICLE_REVIEW_AGENT_MODEL=deepseek-R1 # Default, can be overridden
        # TITLE_AGENT_MODEL=deepseek-R1-creative # Example override
        ```

## 2. Modal Deployment Script (`modal_script.py`) Changes

Your Modal deployment script (e.g., the one containing the `DeepSeekModel` class) is central to this integration. Ensure the following:

*   **`generate` Method Output Format**:
    *   This is a **critical change**. The `generate` method within your Modal class (e.g., `DeepSeekModel`) **must** return a JSON object (Python dictionary) with the following structure to be compatible with the updated agents:
        ```python
        {
            "choices": [
                {
                    "message": {
                        "content": generated_text_string 
                    }
                }
            ]
        }
        ```
    *   **Example return statement in your Modal `generate` method:**
        ```python
        # Inside your Modal DeepSeekModel class's generate method:
        # ... (generate text using your loaded model) ...
        # generated_text = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        
        return {
            "choices": [
                {
                    "message": {
                        "content": generated_text 
                    }
                }
            ]
        }
        ```

*   **Model Identifier (`MODEL_ID`)**:
    *   Within your Modal script, the `MODEL_ID` variable (or however you store the Hugging Face model identifier) must be set to the correct identifier for the DeepSeek R1 model you intend to use.
    *   *Verification of the exact DeepSeek R1 model ID on Hugging Face is crucial.* For example, it might be something like `"deepseek-ai/DeepSeek-V1-R1"` or another specific variant. **Please verify the correct model ID.**
    *   Example:
        ```python
        # In your modal_script.py
        MODEL_ID = "deepseek-ai/VERIFY_CORRECT_DEEPSEEK_R1_MODEL_ID" 
        ```

*   **`trust_remote_code=True`**:
    *   If the specific DeepSeek R1 model requires it (as many advanced models do), ensure `trust_remote_code=True` is used when loading the model with `AutoModelForCausalLM.from_pretrained` and `AutoTokenizer.from_pretrained`.
    *   Example:
        ```python
        # In your Modal DeepSeekModel class's __enter__ or load_model method:
        self.model = AutoModelForCausalLM.from_pretrained(
            model_weights_path, # Path from Volume
            trust_remote_code=True, 
            # ... other parameters like torch_dtype ...
        )
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_weights_path, # Path from Volume
            trust_remote_code=True
        )
        ```

*   **GPU Configuration**:
    *   Ensure the `@stub.cls()` or `@stub.function()` decorator for your Modal model class/function requests an appropriate GPU. For large models like DeepSeek R1, this might be an "L4", "A10G", "A100", or "H100" GPU, depending on the model size and performance requirements.
    *   Example:
        ```python
        # In your modal_script.py
        @stub.cls(gpu="A10G", container_idle_timeout=300, volumes={MODEL_DIR: volume})
        class DeepSeekModel:
            # ...
        ```

*   **Modal Volumes for Model Weights**:
    *   It is highly recommended to use Modal Volumes for storing model weights. This ensures weights are downloaded once and persisted across container starts, speeding up cold starts.
    *   Your Modal script should include logic to download weights to a Volume if they don't already exist, typically within an `@stub.function()` decorated for this purpose or in the `__enter__` method of your class if run on demand.

*   **Faster Hugging Face Downloads**:
    *   To speed up the initial download of model weights into your Modal Volume or Image, include `hf_transfer` in your Modal Image definition.
    *   Example:
        ```python
        # In your modal_script.py
        image = (
            modal.Image.debian_slim()
            .pip_install(
                "transformers",
                "torch",
                "huggingface_hub[hf_transfer]", # For faster downloads
                "accelerate"
            )
            .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"}) 
        )
        ```

## 3. General Advice

*   **Independent Endpoint Testing**:
    *   After making the necessary changes to your Modal deployment script, deploy it and **test the Modal endpoint independently**.
    *   Use tools like `curl`, Postman, or a simple Python script with the `modal` client library to send test requests to your Modal `generate` endpoint.
    *   Verify that it correctly processes inputs and, most importantly, returns the JSON in the exact `{"choices": [{"message": {"content": "..."}}]}` format.
    *   This ensures the Modal service is working as expected before integrating it into the full agent pipeline, simplifying debugging.

By following these guidelines, you can successfully transition your agents to use a Modal-hosted LLM service, improving scalability, manageability, and potentially performance.
