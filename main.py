import os
import requests
import json
import re
import cloudscraper
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import pytz

GIST_ID = os.environ.get('GIST_ID')
GIST_PAT = os.environ.get('GIST_PAT')
GIST_API_URL = f"https://api.github.com/gists/{GIST_ID}"
GIST_HEADERS = {
    "Authorization": f"token {GIST_PAT}",
    "Accept": "application/vnd.github.v3+json",
    "X-GitHub-Api-Version": "2022-11-28"
}
GIST_FILENAME = "database.json"

WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK_URL')
TARGET_URL = os.environ.get('TARGET_URL')
AUTH_NAME = os.environ.get('AUTH_NAME')
TARGET_PRICE = os.environ.get('TARGET_PRICE')

scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'mobile': False
    }
)

def get_gist_data():
    try:
        r = requests.get(GIST_API_URL, headers=GIST_HEADERS, timeout=10)
        r.raise_for_status()
        data = r.json()
        content = data['files'][GIST_FILENAME]['content']
        return json.loads(content)
    except Exception as e:
        print(f"Error reading Gist: {e}")
        return None

def update_gist_data(new_data):
    try:
        payload = {
            "files": {
                GIST_FILENAME: {
                    "content": json.dumps(new_data, indent=2)
                }
            }
        }
        r = requests.patch(GIST_API_URL, headers=GIST_HEADERS, json=payload, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"Error updating Gist: {e}")

def scrape_site():
    try:
        r = scraper.get(TARGET_URL, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        
        price_text = soup.find(string=re.compile(r"Rp[\d\.]+/100\s*Robux"))
        if not price_text:
            raise ValueError("Price element not found")
        
        match = re.search(r"Rp([\d\.]+)/100", price_text)
        if not match:
            raise ValueError("Price regex failed")
        
        current_price = int(match.group(1).replace(".", ""))
        
        stock_status = "Habis"
        stock_available_span = soup.find("span", string=re.compile(r"Stok\s*Tersedia"))
        
        if stock_available_span:
            stock_status = "Tersedia"
            parent_div = stock_available_span.find_parent("div")
            if parent_div:
                number_span = parent_div.find("span", class_="font-bold")
                if number_span:
                    number_text = number_span.get_text(strip=True).replace(".", "")
                    if number_text.isdigit():
                        stock_number = int(number_text)
                        stock_status = f"{stock_number:,} Tersedia".replace(",", ".")
        else:
            timer_anchor = soup.find("span", string=re.compile(r'Stok\s*selanjutnya\s*dalam'))
            if timer_anchor:
                parent_span = timer_anchor.find_parent("span")
                if parent_span:
                    timer_span = parent_span.find("span", class_="font-bold")
                    if timer_span:
                        timer = timer_span.get_text(strip=True)
                        stock_status = f"Habis (Restock: {timer})"
                    else:
                        stock_status = "Habis (Info timer tidak ditemukan)"
                else:
                    stock_status = "Habis (Info timer tidak ditemukan)"
            else:
                stock_status = "Habis (Info restock tidak ada)"
                
        return current_price, stock_status
    
    except cloudscraper.exceptions.CloudflareException as e:
        print(f"Cloudflare block detected: {e}")
        return None, None
    except Exception as e:
        print(f"Error scraping site: {e}")
        return None, None

def send_discord_notification(new_price, old_price, new_stock, old_stock, ping_everyone=False, title=""):
    content = "@everyone" if ping_everyone else ""
    
    color = 3066993
    if "TARGET TERCAPAI" in title:
        color = 3447003
    elif "HARGA NAIK" in title or "STOK HABIS" in title:
        color = 15158332
    elif "RESTOCK" in title:
        color = 3447003
    elif new_price != old_price:
        color = 15844367
    
    utc_now = datetime.now(pytz.utc)
    
    embed = {
        "title": title,
        "description": f"Harga baru Robux telah terdeteksi.",
        "url": TARGET_URL,
        "color": color,
        "timestamp": utc_now.isoformat(),
        "fields": [
            {"name": "Harga Sekarang (per 100 Robux)", "value": f"**Rp {new_price:,}**".replace(",", "."), "inline": True},
            {"name": "Harga Sebelumnya", "value": f"Rp {old_price:,}".replace(",", "."), "inline": True},
            {"name": "Stok Sekarang", "value": new_stock, "inline": False}
        ],
        "footer": {
            "text": f"Created by {AUTH_NAME}"
        }
    }
    
    embed["fields"].append({"name": "Link Toko", "value": f"[Klik di sini]({TARGET_URL})", "inline": False})
    
    if "TARGET TERCAPAI" in title:
        embed["description"] = "Harga Robux telah mencapai atau di bawah target!"
    elif "STOK HABIS" in title:
        embed["description"] = "Stok Robux saat ini telah habis."
    
    data = {
        "content": content,
        "embeds": [embed],
        "username": "Robux Price Monitor"
    }
    
    try:
        r = requests.post(WEBHOOK_URL, json=data, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"Error sending Discord notification: {e}")

def main():
    print("Running Robux Monitor...")
    
    if not all([GIST_ID, GIST_PAT, WEBHOOK_URL, TARGET_URL, AUTH_NAME, TARGET_PRICE]):
        print("Missing one or more critical environment variables (GIST_ID, GIST_PAT, WEBHOOK_URL, TARGET_URL, AUTH_NAME, TARGET_PRICE).")
        return

    try:
        target_price_int = int(TARGET_PRICE)
    except ValueError:
        print(f"Invalid TARGET_PRICE. Must be a number. Got: {TARGET_PRICE}")
        return

    old_data = get_gist_data()
    if not old_data:
        print("Failed to get old data, initializing...")
        old_data = {"harga_terakhir": 0, "status_stok_terakhir": "Unknown"}
    
    old_price = old_data.get("harga_terakhir", 0)
    old_stock = old_data.get("status_stok_terakhir", "Unknown")
    
    new_price, new_stock = scrape_site()
    
    if new_price is None or new_stock is None:
        print("Scraping failed, skipping this run.")
        return

    old_stock_is_available = not old_stock.startswith("Habis")
    new_stock_is_available = not new_stock.startswith("Habis")

    if new_price == old_price and old_stock_is_available == new_stock_is_available:
        print(f"No changes. Price: {new_price}, Stock: {new_stock}")
        return

    print(f"Change detected! New Price: {new_price}, New Stock: {new_stock}")
    
    title = "Perubahan Harga/Stok"
    ping = False
    
    if new_price <= target_price_int and old_price > target_price_int:
        title = "🔥 TARGET TERCAPAI 🔥"
        ping = True
    elif new_price > target_price_int and old_price <= target_price_int and old_price != 0:
        title = "📈 HARGA NAIK MELEWATI TARGET 📈"
        ping = True
    elif new_stock.startswith("Habis") and not old_stock.startswith("Habis"):
        title = "🚫 STOK HABIS 🚫"
        ping = True
    elif not new_stock.startswith("Habis") and old_stock.startswith("Habis"):
        title = "✅ RESTOCK ✅"
        ping = True
    elif new_price != old_price:
        title = "🔔 Perubahan Harga 🔔"
    elif new_stock != old_stock:
        title = "🔔 Perubahan Stok 🔔"

    send_discord_notification(new_price, old_price, new_stock, old_stock, ping, title)
    
    update_gist_data({
        "harga_terakhir": new_price,
        "status_stok_terakhir": new_stock
    })
    
    print("Notification sent and Gist updated.")

if __name__ == "__main__":
    main()
