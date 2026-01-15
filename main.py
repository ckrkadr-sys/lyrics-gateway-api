import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
import time

app = FastAPI()

# --- CORS AYARLARI (Web ve Mobil erişimi için şart) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Basit Cache Sistemi (Hafıza)
lyric_cache = {}
CACHE_DURATION = 3600 * 24 * 7  # 7 Gün

# --- Veri Modelleri ---
class CleanRequest(BaseModel):
    text: str

# --- Yardımcı Fonksiyonlar ---

def clean_with_gemini(dirty_text):
    """
    OCR veya Scraping ile gelen kirli metni Gemini 1.5 Flash kullanarak temizler.
    """
    if not GEMINI_API_KEY:
        print("HATA: API Key bulunamadı!")
        return dirty_text
    
    # DÜZELTME BURADA: Model ismini 'gemini-1.5-flash' yaptık.
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    prompt = f"""
    Sen profesyonel bir müzisyen asistanısın. Aşağıdaki metin bir şarkı sözü fotoğrafından (OCR) okundu.
    Metin çok bozuk, içinde "Sayfa 1", menü yazıları, reklamlar veya anlamsız harfler olabilir.
    
    GÖREVİN:
    1. Sadece ve sadece ŞARKI SÖZLERİNİ ayıkla.
    2. Gereksiz tüm başlıkları, sayıları, web linklerini SİL.
    3. Yazım hatalarını düzelt.
    4. Şarkı sözlerini kıtalara ayır (her kıta arasına bir boş satır koy).
    5. Başka hiçbir yorum yapma (Örn: "İşte temizlenmiş metin" DEME). Sadece sözleri ver.
    
    İŞLENECEK METİN:
    {dirty_text[:9000]}
    """
    
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }]
    }
    
    try:
        # Timeout süresini 30 saniyeye çıkardık
        response = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            # Cevabı güvenli bir şekilde al
            try:
                cleaned = data['candidates'][0]['content']['parts'][0]['text']
                return cleaned.strip()
            except (KeyError, IndexError):
                print(f"Gemini Cevap Formatı Beklenmedik: {data}")
                return dirty_text
        else:
            print(f"Gemini API Hatası ({response.status_code}): {response.text}")
            return dirty_text # Hata olursa orijinal metni döndür
            
    except Exception as e:
        print(f"Bağlantı Hatası: {e}")
        return dirty_text

def scrape_lyrics(artist, title):
    """
    İnternetten şarkı sözü arar ve bulur.
    """
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

# --- API Endpointleri ---

@app.get("/")
def read_root():
    return {"status": "LyricMaster API (Gemini Flash) is Running"}

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

@app.post("/clean_raw_text")
def clean_raw_text(request: CleanRequest):
    # OCR'dan gelen metni temizleme noktası
    cleaned = clean_with_gemini(request.text)
    return {"cleaned_text": cleaned}
