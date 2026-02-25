# Bundled Fonts for mLites Text Rendering

This folder is used to supply script-specific fonts that render consistently across dev/prod.

For Hindi (Devanagari), place the following files here (exact filenames):

- NotoSansDevanagari-Regular.ttf
- NotoSansDevanagari-Bold.ttf

Download from Google Fonts:
- https://fonts.google.com/noto/specimen/Noto+Sans+Devanagari

Why this is needed
- The mLites image renderer (Pillow) needs a Devanagari-capable font to draw Hindi text.
- If the OS does not have Devanagari fonts (e.g., Nirmala/Mangal on Windows, Noto on Linux), text may render as boxes or gibberish.

How the code uses these files
- backend/app/mlites.py prefers these bundled paths when language is Hindi:
  - assets/fonts/NotoSansDevanagari-Regular.ttf
  - assets/fonts/NotoSansDevanagari-Bold.ttf
- If these files are not present, it falls back to system fonts (Nirmala/Mangal/Kokila on Windows, Noto on Linux), then to DejaVu as a last resort (which does not support Devanagari).

After placing fonts
- Restart the backend process to ensure the fonts are picked up.
- Re-generate an mLite with Hindi selected in your profile.
