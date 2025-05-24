# deepseek_modal_app.py
import os
import sys
import json
import logging
import time
from typing import List, Dict, Any, Optional
import torch

import modal # Corrected: import the modal module directly

# Configure basic logging for the Modal app
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(name)s] - %(message)s')
logger = logging.getLogger("deepseek_modal_app")

# Define the Modal App name
MODAL_APP_NAME = "deepseek-gpu-inference-app" # Renamed for clarity, explicitly indicates GPU inference
app = modal.App(MODAL_APP_NAME) # Corrected: Use modal.App instead of Stub

# Define the Hugging Face model to load
# Using a publicly available DeepSeek Coder model that can run on an A10G
HF_MODEL_NAME = "deepseek-ai/deepseek-coder-6.7b-instruct"
HF_TRUST_REMOTE_CODE = True # Necessary for some Hugging Face models

# Define the image for the Modal app
# It must include:
# - PyTorch (for GPU inference)
# - Transformers (to load and use the LLM)
# - Accelerate (for efficient model loading/inference)
# - BitsAndBytes (for 4-bit quantization, if desired, to fit larger models)
# - SentencePiece (common tokenizer dependency)
# - requests (for any internal HTTP calls, though not for DeepSeek API in this setup)
# - git (for cloning repositories if needed, though HF handles most model downloads)
deepseek_gpu_image = modal.Image.debian_slim(python_version="3.10").apt_install(
    "git" # Just in case for some model dependencies
).pip_install(
    "torch==2.1.2", # Specific PyTorch version compatible with recent CUDA/transformers
    "transformers==4.38.1", # Specific transformers version
    "accelerate==0.27.2",  # Specific accelerate version for compatibility
    "bitsandbytes==0.42.0", # For 4-bit quantization if needed
    "sentencepiece==0.1.99", # Tokenizer dependency
    "requests", # For general HTTP needs, not DeepSeek API
    "python-dotenv", # If .env is read within the Modal function itself
).run_commands(
    # Optional: Pre-download model weights into the image to speed up cold starts
    # This assumes the model is small enough or can be partially downloaded.
    # For large models, direct loading in __enter__ is better.
    # "pip install huggingfaceface-hub", # For huggingface-cli
    # f"huggingface-cli download {HF_MODEL_NAME} --cache-dir /root/.cache/huggingface" # Pre-download to image
)


# Define the Modal class for the DeepSeek LLM service
# This class name must match MODAL_CLASS_NAME used in your agents
# The GPU type and count are specified here.
MODAL_CLASS_NAME = "DeepSeekModel" # This is the class name your agents will lookup

@app.cls(image=deepseek_gpu_image, gpu="A10G") # Corrected: Use app.cls()
class DeepSeekModel:
    def __enter__(self):
        # This method runs once when the container starts
        # It loads the pre-trained model and tokenizer onto the GPU.
        logger.info(f"Loading model '{HF_MODEL_NAME}' onto GPU...")
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        import torch

        # Configuration for 4-bit quantization (optional, but helps fit models on smaller GPUs)
        # You might need to adjust this based on the model size and A10G's memory.
        # If the model fits without quantization, you can remove quant_config.
        quant_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=False,
        )

        self.tokenizer = AutoTokenizer.from_pretrained(HF_MODEL_NAME, trust_remote_code=HF_TRUST_REMOTE_CODE)
        self.model = AutoModelForCausalLM.from_pretrained(
            HF_MODEL_NAME,
            quantization_config=quant_config, # Apply quantization
            torch_dtype=torch.float16, # Use float16 for efficiency
            device_map="auto", # Automatically map layers to available devices (GPU/CPU)
            trust_remote_code=HF_TRUST_REMOTE_CODE,
            offload_folder="offload_dir" # For offloading parts of the model to CPU/disk if GPU memory is tight
        )
        self.model.eval() # Set model to evaluation mode
        logger.info(f"Model '{HF_MODEL_NAME}' loaded successfully on GPU.")

    @modal.method() # Corrected: Use modal.method()
    def generate(self, messages: List[Dict[str, str]], max_new_tokens: int, temperature: float = 0.05, model: str = HF_MODEL_NAME) -> Dict[str, Any]:
        """
        Generates a response using the locally hosted DeepSeek LLM.

        Args:
            messages: A list of message dictionaries (e.g., [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]).
            max_new_tokens: The maximum number of tokens to generate.
            temperature: Sampling temperature for generation.
            model: The specific DeepSeek model name, for logging/context (HF_MODEL_NAME is used internally).

        Returns:
            A dictionary representing the LLM's response, similar to OpenAI API format:
            {"choices": [{"message": {"content": "..."}}], "usage": {...}}
        """
        logger.info(f"Received request for generating with '{model}' (internal: {HF_MODEL_NAME}). Max tokens: {max_new_tokens}, Temperature: {temperature}")
        
        # Apply chat template if available
        if hasattr(self.tokenizer, 'apply_chat_template') and self.tokenizer.chat_template:
            input_text = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        else:
            # Fallback for models without a specific chat template (simple concatenation)
            input_text = ""
            for msg in messages:
                role = msg.get("role", "user").capitalize()
                content = msg.get("content", "")
                input_text += f"{role}: {content}\n"
            input_text += "Assistant:" # Standard prompt for a response

        input_ids = self.tokenizer.encode(input_text, return_tensors="pt").to(self.model.device)

        with torch.no_grad(): # Disable gradient calculation for inference
            output = self.model.generate(
                input_ids,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                do_sample=temperature > 0.001, # Only sample if temperature is > 0
                pad_token_id=self.tokenizer.eos_token_id # Important for generation
            )
        
        # Decode the generated tokens
        generated_tokens = output[0, input_ids.shape[1]:] # Exclude prompt tokens
        generated_text = self.tokenizer.decode(generated_tokens, skip_special_tokens=True)

        logger.info(f"Generation successful. Generated text length: {len(generated_text)} chars.")
        
        # Format output to match the expected structure of your agents
        # (similar to OpenAI API responses)
        return {
            "choices": [{"message": {"content": generated_text}}],
            "usage": {
                "prompt_tokens": input_ids.shape[1],
                "completion_tokens": generated_tokens.shape[0],
                "total_tokens": input_ids.shape[1] + generated_tokens.shape[0]
            }
        }

@app.local_entrypoint() # Corrected: Use app.local_entrypoint()
def main():
    """
    Local entrypoint to test the Modal DeepSeekModel.
    When you run `modal run deepseek_modal_app.py`, this executes.
    It calls the remote `generate` method on Modal.
    """
    logger.info("Running local entrypoint for DeepSeekModel test deployment.")
    
    # Example messages for a simple test
    test_messages = [
        {"role": "system", "content": "You are a helpful AI assistant specialized in coding and technical concepts. Be concise."},
        {"role": "user", "content": "Explain the concept of 'tree shaking' in JavaScript in one sentence."}
    ]
    
    # Get a reference to the remote class
    remote_model = DeepSeekModel() # This creates a local handle to the remote class
    
    # Call the remote method
    logger.info("Calling remote DeepSeekModel.generate function...")
    try:
        response = remote_model.generate.remote(
            messages=test_messages,
            max_new_tokens=100, # Max tokens for response
            temperature=0.01, # Low temperature for factual, consistent response
            model=HF_MODEL_NAME # Pass the model name for consistency
        )
        
        if response and response.get("choices"):
            generated_text = response["choices"][0]["message"]["content"]
            logger.info(f"Successfully received response from DeepSeekModal:\n{generated_text}")
        else:
            logger.error(f"Remote DeepSeekModel returned no choices or malformed response: {response}")
    except Exception as e:
        logger.error(f"Error calling remote DeepSeekModel: {e}")

