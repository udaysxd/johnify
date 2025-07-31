from google.cloud import texttospeech
from pathlib import Path
import os
import shutil

def fresh_dir(path: str):
    """Create a fresh directory, removing any existing contents."""
    p = Path(path)
    if p.exists():
        shutil.rmtree(p)
    p.mkdir(parents=True, exist_ok=True)
    return p

def narrations_to_mp3(narrations: list[str], out_dir: str = "audio"):
    """Convert narrations to MP3 audio files."""
    out_dir = fresh_dir(out_dir)
    client = texttospeech.TextToSpeechClient()
    
    # Set voice parameters
    voice = texttospeech.VoiceSelectionParams(
        language_code="en-GB",
        name="en-GB-Neural2-D",
    )
    
    # Set audio format
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=1.0,
        pitch=0.0,
    )
    
    # Process each narration
    for i, narration in enumerate(narrations):
        # Create synthesis request
        synthesis_input = texttospeech.SynthesisInput(text=narration)
        
        # Perform the text-to-speech request
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config,
        )
        
        # Save the audio file
        mp3_path = Path(out_dir) / f"s{i+1:03d}.mp3"
        mp3_path.write_bytes(response.audio_content)
        print(f"Created {mp3_path}")
    
    return out_dir