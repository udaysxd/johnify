import google.generativeai as genai
import os

# Configure with your API key
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# List available models
try:
    models = genai.list_models()
    print('Available Gemini models with generateContent support:')
    for model in models:
        if 'generateContent' in model.supported_generation_methods:
            print(f'  {model.name} - {model.display_name}')
except Exception as e:
    print(f'Error: {e}')
