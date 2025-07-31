from importlib import metadata
__all__ = ["env", "quiz", "slidegen", "pptx_gen", "tts", "video", "utils"]
__version__ = metadata.version("johnify-backend") if metadata.packages_distributions().get("johnify-backend") else "0.0.0"
