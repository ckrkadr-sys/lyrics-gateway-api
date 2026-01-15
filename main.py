import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
import time

app = FastAPI()

# --- CORS AYARLARI ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Cache
lyric_cache = {}
CACHE_DURATION = 3600 * 24 * 7 

# --- DATA MODELLERİ ---
class LyricRequest(BaseModel):
    artist: str
    title: str

class CleanRequest(BaseModel):
    text: str

# --- YARDIMCI FONKSİYONLAR ---
def clean_with_gemini(dirty_text):
    if not GEMINI_API_KEY:
        return dirty_text
    
    # Model: gemini-pro (Daha kararlı)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY}"
    
    prompt = f"""
    Aşağıdaki metin bir fotoğraftan OCR ile okundu. Satır kaymaları ve gürültü olabilir.
    Bu metni ŞARKI SÖZÜ formatında temizle, düzelt ve kıtalara ayır.
    Başlık yazma, yorum yapma. Sadece sözler.
    
    METİN:
    {dirty_text[:8000]}
    """
    
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    
    try:
        response = requests.post(url, json=payload, headers={'Content-Type': 'application/json'})
        if response.status_code == 200:
            data = response.json()
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
        if not results: return None
        url = results[0]['href']
        print(f"Hedef Site: {url}")
        headers = {'User-Agent': 'Mozilla/5.0'}
        page = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(page.content, 'html.parser')
        for script in soup(["script", "style"]): script.decompose()
        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        return '\n'.join(chunk for chunk in chunks if chunk)
    except Exception as e:
        print(f"Scrape Hatası: {e}")
        return None

# --- ENDPOINTLER ---
@app.get("/")
def read_root():
    return {"status": "LyricMaster API with OCR Support Running"}

@app.get("/get_lyrics")
def get_lyrics(artist: str, title: str):
    cache_key = f"{artist.lower().strip()}_{title.lower().strip()}"
    if cache_key in lyric_cache:
        if time.time() - lyric_cache[cache_key]['timestamp'] < CACHE_DURATION:
            return {"lyrics": lyric_cache[cache_key]['lyrics'], "source": "cache"}

    raw_lyrics = scrape_lyrics(artist, title)
    if not raw_lyrics:
        raise HTTPException(status_code=404, detail="Lyrics not found")
    
    final_lyrics = clean_with_gemini(raw_lyrics)
    lyric_cache[cache_key] = {"lyrics": final_lyrics, "timestamp": time.time()}
    return {"lyrics": final_lyrics, "source": "web"}

# YENİ EKLENEN ENDPOINT: OCR TEMİZLİKÇİSİ
@app.post("/clean_raw_text")
def clean_raw_text(request: CleanRequest):
    cleaned_text = clean_with_gemini(request.text)
    return {"cleaned_text": cleaned_text}
