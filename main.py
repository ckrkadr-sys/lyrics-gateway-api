import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
import time

app = FastAPI()

# API Key'i al
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Cache Ayarları
lyric_cache = {}
CACHE_DURATION = 3600 * 24 * 7  # 7 Gün

class LyricRequest(BaseModel):
    artist: str
    title: str

def clean_with_gemini(dirty_text):
    if not GEMINI_API_KEY:
        return dirty_text
    
    # KÜTÜPHANE YERİNE DOĞRUDAN REST API KULLANIYORUZ
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    prompt = f"""
    Aşağıdaki metin bir web sitesinden çekildi. İçinde menüler, reklamlar olabilir.
    Sadece ŞARKI SÖZLERİNİ ayıkla, temizle ve kıtalara ayır.
    Başlık yazma, yorum yapma. Sadece sözler.
    
    METİN:
    {dirty_text[:8000]}
    """
    
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }]
    }
    
    try:
        response = requests.post(url, json=payload, headers={'Content-Type': 'application/json'})
        if response.status_code == 200:
            data = response.json()
            # Cevabı ayıkla
            return data['candidates'][0]['content']['parts'][0]['text']
        else:
            print(f"Gemini API Hatası: {response.text}")
            return dirty_text
    except Exception as e:
        print(f"Bağlantı Hatası: {e}")
        return dirty_text

def scrape_lyrics(artist, title):
    query = f"{artist} {title} şarkı sözleri"
    print(f"Aranıyor: {query}")
    
    try:
        results = DDGS().text(query, max_results=3)
        if not results:
            return None
            
        first_result = results[0]
        url = first_result['href']
        print(f"Hedef Site: {url}")
        
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0'}
        page = requests.get(url, headers=headers, timeout=10)
        
        soup = BeautifulSoup(page.content, 'html.parser')
        
        for script in soup(["script", "style"]):
            script.decompose()
            
        text = soup.get_text()
        
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        clean_text = '\n'.join(chunk for chunk in chunks if chunk)
        
        return clean_text
        
    except Exception as e:
        print(f"Scrape Hatası: {e}")
        return None

@app.get("/")
def read_root():
    return {"status": "LyricMaster API is running (No-Lib Version)"}

@app.get("/get_lyrics")
def get_lyrics(artist: str, title: str):
    cache_key = f"{artist.lower().strip()}_{title.lower().strip()}"
    
    if cache_key in lyric_cache:
        cached_item = lyric_cache[cache_key]
        if time.time() - cached_item['timestamp'] < CACHE_DURATION:
            return {"lyrics": cached_item['lyrics'], "source": "cache"}

    raw_lyrics = scrape_lyrics(artist, title)
    
    if not raw_lyrics:
        raise HTTPException(status_code=404, detail="Lyrics not found")
    
    final_lyrics = clean_with_gemini(raw_lyrics)
    
    lyric_cache[cache_key] = {
        "lyrics": final_lyrics,
        "timestamp": time.time()
    }
    
    return {"lyrics": final_lyrics, "source": "web"}
