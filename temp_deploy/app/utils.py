# utils.py
from bs4 import BeautifulSoup
import markdown2
from pathlib import Path
import shutil

def markdown_to_plain_text(md: str) -> str:
    return BeautifulSoup(markdown2.markdown(md), "html.parser").get_text(separator=" ", strip=True)

def fresh_dir(path: str | Path):
    p = Path(path)
    if p.exists():
        shutil.rmtree(p)
    p.mkdir(parents=True, exist_ok=True)
    return p
