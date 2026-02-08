import os
import requests
import json
import re
import cloudscraper
from bs4 import BeautifulSoup
from datetime import datetime
import pytz

GIST_ID = os.environ.get('GIST_ID')
GIST_PAT = os.environ.get('GIST_PAT')
WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK_URL')
TARGET_URL = os.environ.get('TARGET_URL')
AUTH_NAME = os.environ.get('AUTH_NAME')
TARGET_PRICE_ENV = os.environ.get('TARGET_PRICE')

GIST_API_URL = f"https://api.github.com/gists/{GIST_ID}"
GIST_HEADERS = {
    "Authorization": f"token {GIST_PAT}",
    "Accept": "application/vnd.github.v3+json",
    "X-GitHub-Api-Version": "2022-11-28"
}
GIST_FILENAME = "database.json"

TRACK_ITEMS = [
    {"label": "100RBX", "amount": 100, "id": "100"},
    {"label": "500RBX", "amount": 500, "id": "500"},
    {"label": "1.000RBX", "amount": 1000, "id": "1000"}
]

scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'ios', 'mobile': True}
)

def get_target_prices():
    if not TARGET_PRICE_ENV: return {}
    try:
        prices = [int(x.strip()) for x in TARGET_PRICE_ENV.split(',')]
        return {
            100: prices[0] if len(prices) > 0 else 0,
            500: prices[1] if len(prices) > 1 else 0,
            1000: prices[2] if len(prices) > 2 else 0
        }
    except: return {100: 0, 500: 0, 1000: 0}

def get_gist_data():
    try:
        r = requests.get(GIST_API_URL, headers=GIST_HEADERS, timeout=10)
        r.raise_for_status()
        content = r.json()['files'][GIST_FILENAME]['content']
        return json.loads(content)
    except Exception as e:
        print(f"Error reading Gist: {e}")
        return {}

def update_gist_data(new_data):
    try:
        payload = {"files": {GIST_FILENAME: {"content": json.dumps(new_data, indent=2)}}}
        requests.patch(GIST_API_URL, headers=GIST_HEADERS, json=payload, timeout=10)
    except Exception as e:
        print(f"Error updating Gist: {e}")

def scrape_site():
    try:
        r = scraper.get(TARGET_URL, timeout=15)
        r.raise_for_status()
        
        if "Just a moment" in r.text or "Challenge" in r.text:
            print("Block detected.")
            return None

        soup = BeautifulSoup(r.text, 'html.parser')
        results = {}
        found_any = False

        for item in TRACK_ITEMS:
            label_pattern = re.compile(re.escape(item["label"]), re.IGNORECASE)
            label_el = soup.find(string=label_pattern)
            
            price_found = 0
            status_found = "Habis"

            if label_el:
                card = label_el.find_parent(lambda tag: tag.name == "div" and "Rp" in tag.get_text())
                
                if card:
                    card_text = card.get_text(separator=" ")
                    match = re.search(r"Rp\s*([\d\.]+)", card_text)
                    
                    if match:
                        clean_price = match.group(1).replace(".", "")
                        if clean_price.isdigit():
                            price_found = int(clean_price)
                            status_found = "Tersedia"
                            found_any = True

            results[item["id"]] = {"price": price_found, "status": status_found}
        
        if not found_any:
            print("No prices found. Saving debug.html")
            with open("debug.html", "w", encoding="utf-8") as f:
                f.write(r.text)

        return results

    except Exception as e:
        print(f"Error scraping: {e}")
        return None

def calculate_best_value(current_data):
    best_item = None
    lowest_ratio = float('inf')
    for item in TRACK_ITEMS:
        item_id = item["id"]
        data = current_data.get(item_id)
        if data and data['status'] == "Tersedia" and data['price'] > 0:
            ratio = data['price'] / item['amount']
            if ratio < lowest_ratio:
                lowest_ratio = ratio
                best_item = {"label": item["label"], "price": data['price'], "ratio": ratio}
    return best_item

def send_notification(current_data, old_data, target_prices):
    utc_now = datetime.now(pytz.utc)
    should_ping = False
    change_detected = False
    title_suffix = []
    embed_fields = []
    
    print("-" * 40)
    print("MARKET STATUS:")
    
    for item in TRACK_ITEMS:
        item_id = item["id"]
        curr = current_data.get(item_id)
        old = old_data.get(item_id, {"price": 0, "status": "Unknown"})
        target = target_prices.get(item["amount"], 0)
        
        status_emoji = "🔴" if curr['status'] == "Habis" else "🟢"
        price_display = f"Rp {curr['price']:,}".replace(",", ".") if curr['price'] > 0 else "-"
        
        print(f"{item['label'].ljust(8)} : {price_display} ({curr['status']})")

        item_alert = ""
        
        if curr['price'] <= target and old['price'] > target and curr['price'] > 0:
            should_ping = True
            change_detected = True
            item_alert = "🔥 **TARGET!**"
            title_suffix.append("TARGET")
        elif curr['status'] == "Tersedia" and old['status'] == "Habis":
            should_ping = True
            change_detected = True
            item_alert = "✅ **RESTOCK**"
            title_suffix.append("RESTOCK")
        elif curr['status'] == "Habis" and old['status'] == "Tersedia":
            change_detected = True
            item_alert = "🚫 **HABIS**"
        elif curr['price'] != old['price'] and curr['price'] > 0 and old['price'] > 0:
            change_detected = True
            arrow = "📉" if curr['price'] < old['price'] else "📈"
            item_alert = f"{arrow} {price_display}"

        field_value = f"Harga: **{price_display}**\nStatus: {status_emoji} {curr['status']}\n{item_alert}"
        embed_fields.append({"name": f"📦 {item['label']}", "value": field_value, "inline": True})

    print("-" * 40)

    if not change_detected:
        print("No changes.")
        return

    color = 3066993
    if "TARGET" in title_suffix: color = 3447003
    elif "HABIS" in str(title_suffix): color = 15158332

    main_title = "🔔 Update Harga Robux"
    if title_suffix: main_title = f"🔔 {' & '.join(list(set(title_suffix)))} DETECTED!"

    best = calculate_best_value(current_data)
    footer_text = f"Created by {AUTH_NAME}"
    if best: footer_text = f"🏆 Best Value: {best['label']} (Rp {best['ratio']:.1f}/rbx) • {footer_text}"

    embed = {
        "title": main_title,
        "url": TARGET_URL,
        "color": color,
        "timestamp": utc_now.isoformat(),
        "fields": embed_fields,
        "footer": {"text": footer_text}
    }
    embed["fields"].append({"name": "Link Toko", "value": f"[Klik di sini untuk beli]({TARGET_URL})", "inline": False})
    
    data = {"content": "@everyone" if should_ping else "", "embeds": [embed], "username": "Robux Multi-Tracker"}
    try:
        requests.post(WEBHOOK_URL, json=data, timeout=10)
        print("Notification sent!")
    except Exception as e:
        print(f"Error discord: {e}")

def main():
    print("Running Multi-Tracker...")
    if not all([GIST_ID, GIST_PAT, WEBHOOK_URL, TARGET_URL, AUTH_NAME, TARGET_PRICE_ENV]):
        print("Missing env vars.")
        return

    current_data = scrape_site()
    if not current_data: return

    old_data = get_gist_data()
    target_prices = get_target_prices()
    send_notification(current_data, old_data, target_prices)
    update_gist_data(current_data)

if __name__ == "__main__":
    main()
