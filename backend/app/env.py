import os
from typing import Optional
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def get_deepseek_client() -> OpenAI:
    """
    Get a configured API client using OpenAI's package (which works with Deepseek).
    
    Returns:
        OpenAI: Configured API client
    """
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY environment variable is not set")
    
    # Initialize OpenAI client with Deepseek API key
    client = OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com/v1"
    )
    return client