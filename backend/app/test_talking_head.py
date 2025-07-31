from talking_head import SadTalker, install_sadtalker

def main():
    # First-time setup
    install_sadtalker()
    
    # Initialize the talking head generator
    talker = SadTalker()
    
    # Example usage
    image_path = "path_to_your_image.jpg"  # Replace with your image
    audio_path = "path_to_your_audio.mp3"  # Replace with your audio
    
    print("🚀 Generating talking head video...")
    result = talker.generate_talking_head(image_path, audio_path)
    
    if result:
        print(f"🎥 Video generated at: {result}")

if __name__ == "__main__":
    main()