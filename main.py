import os
import time
import json
import logging
from typing import Optional, Dict

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
import uvicorn
import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
import google.generative_ai as genai

# Konfigürasyon
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
PORT = int(os.environ.get("PORT", 10000))

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Lyric Gateway API")

# Basit In-Memory Cache (Artist+Title -> {lyrics, timestamp})
# TTL: 7 gün
CACHE_TTL = 7 * 24 * 3600 
lyrics_cache: Dict[str, Dict] = {}

class LyricResponse(BaseModel):
    lyrics: str
    source: str

def get_cache_key(artist: str, title: str) -> str:
    return f"{artist.lower().strip()}_{title.lower().strip()}"

def clean_with_gemini(dirty_text: str) -> str:
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not set, returning dirty text.")
        return dirty_text

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        prompt = f"""
        You are a text cleaner. The input is raw text scraped from a lyric website containing ads, menus, and footer text.
        
        TASK:
        1. Extract ONLY the song lyrics.
        2. Remove [Chorus], [Verse] labels if they are distracting, or keep them if helpful.
        3. Format into clear stanzas with proper spacing.
        4. Do NOT invent new lyrics. The input MUST contain the lyrics.
        5. If the input does not seem to contain lyrics (e.g. just menus or 404 text), return 'LYRICS_NOT_FOUND'.
        
        INPUT TEXT:
        {dirty_text[:10000]}  # Limit input length
        """
        
        response = model.generate_content(prompt)
        cleaned = response.text.strip()
        
        if "LYRICS_NOT_FOUND" in cleaned:
            return ""
            
        return cleaned
    except Exception as e:
        logger.error(f"Gemini cleaning failed: {e}")
        return dirty_text # Fallback to raw text

def scrape_lyrics(artist: str, title: str) -> Optional[str]:
    query = f"{artist} {title} şarkı sözleri lyrics"
    logger.info(f"Searching for: {query}")
    
    try:
        results = DDGS().text(query, max_results=3)
        if not results:
            return None
            
        for result in results:
            url = result['href']
            # Youtube, Spotify vb. linkleri atla
            if any(x in url for x in ['youtube.com', 'spotify.com', 'apple.com']):
                continue
                
            logger.info(f"Scraping URL: {url}")
            try:
                # Gerçekçi User-Agent
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.content, 'html.parser')
                    
                    # Sayfadan metni çıkar (Gereksiz tagleri at)
                    for script in soup(["script", "style", "nav", "footer", "header"]):
                        script.decompose()
                        
                    text = soup.get_text(separator='\n')
                    
                    # Çok kısa ise muhtemelen hatadır
                    if len(text) < 100:
                        continue
                        
                    return text
            except Exception as e:
                logger.error(f"Error scraping {url}: {e}")
                continue
                
        return None
        
    except Exception as e:
        logger.error(f"DDGS failed: {e}")
        return None

@app.get("/")
def health_check():
    return {"status": "running"}

@app.get("/get_lyrics", response_model=LyricResponse)
def get_lyrics(artist: str, title: str):
    key = get_cache_key(artist, title)
    
    # 1. Cache Kontrol
    if key in lyrics_cache:
        entry = lyrics_cache[key]
        if time.time() - entry['timestamp'] < CACHE_TTL:
            logger.info(f"Cache hit for {key}")
            return LyricResponse(lyrics=entry['lyrics'], source="cache")
    
    # 2. Web Scraping
    raw_text = scrape_lyrics(artist, title)
    if not raw_text:
        raise HTTPException(status_code=404, detail="Lyrics not found on the web.")
        
    # 3. AI Cleaning
    cleaned_lyrics = clean_with_gemini(raw_text)
    
    if not cleaned_lyrics or len(cleaned_lyrics) < 20:
         raise HTTPException(status_code=404, detail="Lyrics extracted but validation failed.")
         
    # 4. Cache Update
    lyrics_cache[key] = {
        'lyrics': cleaned_lyrics,
        'timestamp': time.time()
    }
    
    return LyricResponse(lyrics=cleaned_lyrics, source="web_scrape")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
