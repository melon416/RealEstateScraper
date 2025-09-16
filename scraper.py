import requests
import hashlib
import time
import csv
from selenium import webdriver
from selenium.webdriver.chromium.options import ChromiumOptions
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.action_chains import ActionChains
import json
import os
import re
import random
import signal
import sys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains

MLX_BASE = "https://api.multilogin.com"
MLX_LAUNCHER = "https://launcher.mlx.yt:45001/api/v1"
MLX_LAUNCHER_V2 = "https://launcher.mlx.yt:45001/api/v2"  # recommended for launching profiles
LOCALHOST = "http://127.0.0.1"
HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}

# Load configuration
def load_config():
    """Load configuration from config.json"""
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
        print("Configuration loaded successfully")
        return config
    except FileNotFoundError:
        print("Error: config.json not found. Please create a configuration file.")
        return None
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in config.json: {str(e)}")
        return None

# Global config variable
CONFIG = load_config()
if not CONFIG:
    exit(1)

# Extract credentials from config
USERNAME = CONFIG['multilogin']['username']
PASSWORD = CONFIG['multilogin']['password']
FOLDER_ID = CONFIG['multilogin']['folder_id']
PROFILE_ID = CONFIG['multilogin']['profile_id']
BASE_URL = CONFIG['scraping']['base_url']
BASE_DOMAIN = "https://www.commercialrealestate.com.au"
CSV_FILE = CONFIG['scraping']['output_csv']

def signin() -> str:
    payload = {
        "email": USERNAME,
        "password": hashlib.md5(PASSWORD.encode()).hexdigest(),
    }
    r = requests.post(f"{MLX_BASE}/user/signin", json=payload)
    if r.status_code != 200:
        print(f"\nError during login: {r.text}\n")
    else:
        response = r.json()["data"]
    token = response["token"]
    return token

def start_profile() -> webdriver:
    r = requests.get(
        f"{MLX_LAUNCHER_V2}/profile/f/{FOLDER_ID}/p/{PROFILE_ID}/start?automation_type=selenium",
        headers=HEADERS,
    )
    response = r.json()
    if r.status_code != 200:
        print(f"\nError while starting profile: {r.text}\n")
    else:
        print(f"\nProfile {PROFILE_ID} started.\n")
    selenium_port = response["data"]["port"]
    chromium_options = ChromiumOptions()
    chromium_options.page_load_strategy = "eager"
    chromium_options.add_argument("--disable-gpu")
    chromium_options.add_argument("--disable-notifications")
    chromium_options.add_argument("--disable-extensions")
    chromium_options.add_argument("--no-sandbox")
    chromium_options.add_argument("--disable-blink-features=AutomationControlled")
    try:
        chromium_options.add_experimental_option(
            "prefs",
            {
                "profile.default_content_setting_values.notifications": 2
            },
        )
    except Exception:
        pass

    driver = webdriver.Remote(
        command_executor=f"{LOCALHOST}:{selenium_port}", options=chromium_options
    )

    # Ensure desktop layout for reliable selectors
    try:
        driver.set_window_size(1400, 900)
    except Exception:
        pass

    # Try to block heavy network types via CDP to avoid long rendering times
    try:
        driver.execute_cdp_cmd("Network.enable", {})
        driver.execute_cdp_cmd(
            "Network.setBlockedURLs",
            {"urls": ["*.woff", "*.ttf", "*.otf", "*.map"]},
        )
    except Exception:
        pass

    return driver

def stop_profile() -> None:
    r = requests.get(f"{MLX_LAUNCHER}/profile/stop/p/{PROFILE_ID}", headers=HEADERS)
    if r.status_code != 200:
        print(f"\nError while stopping profile: {r.text}\n")
    else:
        print(f"\nProfile {PROFILE_ID} stopped.\n")

def get_property_links(driver, page_num):
    """Get property links for a specific page"""
    url = f"{BASE_URL}?pn={page_num}"
    print(f"Fetching: {url}")
    driver.get(url)
    time.sleep(6)

    elements = driver.find_elements(By.CSS_SELECTOR, "a.touchable.css-qbj577")

    page_links = []
    for el in elements:
        href = el.get_attribute("href")
        if href:
            if href.startswith("/"):
                href = BASE_DOMAIN + href
            elif not href.startswith("http"):
                href = BASE_DOMAIN + "/" + href.lstrip("/")
            page_links.append(href)

    return list(set(page_links))  # deduplicate
def get_media(driver):
    media_url = []

    try:
        photos_button = driver.find_element(By.CSS_SELECTOR, "a[data-testid='photos']")
        driver.execute_script("arguments[0].click();", photos_button)

        WebDriverWait(driver, 5).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.image-gallery-image img"))
        )

        # FIXED: use find_elements instead of find_element
        images = driver.find_elements(By.CSS_SELECTOR, "div.image-gallery-image img")
        for img in images:
            src = img.get_attribute("src")
            if src and src not in media_url:
                media_url.append(src)

        try:
            close_btn = driver.find_element(By.CSS_SELECTOR, "button[aria-label='close']")
            close_btn.click()
        except:
            pass
    except Exception as e:
        print(f"No media found: {e}")

    return media_url

def get_agents(driver):
    agents = []

    try:
        container = driver.find_element(By.CSS_SELECTOR, "div.css-t11qww")
        agent_rows = container.find_elements(By.CSS_SELECTOR, "div.agent-row.css-1rz4hxx")
    except:
        return agents  # No agents found

    for row in agent_rows:
        # --- Get agent name ---
        name = ""
        try:
            name_tag = row.find_element(By.CSS_SELECTOR, "div.agent-name a")
            name = name_tag.text.strip()
        except:
            try:
                div_tag = row.find_element(By.CSS_SELECTOR, "div.agent-name.css-tbvndi")
                name = div_tag.text.strip()                                 
            except:
                name = ""

        # --- Get agent phone dynamically after clicking ---
        phone = ""
        try:
            phone_link = row.find_element(By.CSS_SELECTOR, "a.touchable.css-1ulr2bx[data-testid='phone-button']")
            # Scroll into view and click
            ActionChains(driver).move_to_element(phone_link).click(phone_link).perform()

            # Wait until the span with the phone number appears inside div.button-icon
            span = WebDriverWait(phone_link, 3).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.button-icon span.icon-text"))
            )
            phone = span.text.strip()
        except:
            phone = ""

        if name or phone:
            agents.append({
                "name": name,
                "phone": phone
            })
    print(f"Agents:{agents}")
    return agents
def get_price(driver):
    try:
        div = driver.find_element(By.CSS_SELECTOR, "div.css-1bcq2y2")
        span = div.find_element(By.CSS_SELECTOR, "span.icon-text")
        return span.text.strip()
    except:
        return ""
def get_address(driver):
    try:
        h1 = driver.find_element(By.CSS_SELECTOR, "h1.css-1mysost")
        return h1.text.strip()
    except:
        return ""
# def get_floor_space(driver):
#     """Get floor space from the property highlights table."""
#     try:
#         row = driver.find_element(By.CSS_SELECTOR, "tr.css-1bktxj td.css-e14ey")
#         return row.text.strip()
#     except:
#         return ""
def normalize_text(value: str) -> str:
    if not value:
        return ""
    return value.replace("\u00b2", "²")

def get_property_details(driver, url):
    driver.get(url)
    time.sleep(5)

    def safe_get(selector, attr=None):
        try:
            el = driver.find_element(By.CSS_SELECTOR, selector)
            return el.get_attribute(attr) if attr else el.text.strip()
        except:
            return ""
    agent_data = get_agents(driver)

    floor_space = ""
    land_size = ""
    property_id = ""
   
    property_id = safe_get("div.sticky-container.css-n045cl table.css-5a1t3x tbody tr td[data-testid='highlights-row-value Property ID']")
    inspection_time = safe_get("div.sticky-container.css-n045cl table.css-5a1t3x tbody tr td[data-testid='last-updated']")
    floor_space = safe_get("div.sticky-container.css-n045cl table.css-5a1t3x tbody tr td[data-testid='highlights-row-value Floor Area']")
    land_size = safe_get("div.sticky-container.css-n045cl table.css-5a1t3x tbody tr td[data-testid='highlights-row-value Land Area']")
    if not land_size:
        land_size = safe_get("div.sticky-container.css-n045cl table.css-5a1t3x tbody tr td[data-testid='highlights-row-value Land Area'] a")
    auction_data = ""
    try:
        first_tr = driver.find_element(By.CSS_SELECTOR, "tr[data-test-id='child-rows']")
        first_td = first_tr.find_element(By.TAG_NAME, "td")
        auction_data = first_td.text.strip()
    except:
        pass

    # Adjust selectors based on page structure
    key_features = []
    try:
        feature_items = driver.find_elements(By.CSS_SELECTOR, "ul.css-hp4qv li span")
        for f in feature_items:
            text = f.text.strip()
            if text:
                key_features.append(text)
    except:
        pass

    agency = safe_get("div.sticky-container.css-n045cl div.agency-info.css-1s87y25 a")

    property_type = ""
    try:
        property_type = driver.find_element(
            By.CSS_SELECTOR, "ul.css-6f4kvy li:nth-of-type(5) a"
        ).text.strip()
    except:
        pass
    sale_lease = ""
    try:
        sale_lease = driver.find_element(
            By.CSS_SELECTOR, "ul.css-6f4kvy li:nth-of-type(2) a"
        ).text.strip()
    except:
        pass

    details = {
        "floor_space": normalize_text(floor_space),
        "land_size": normalize_text(land_size),
        "property_id": property_id,
        "property_type": property_type,
        "sale_lease": sale_lease,
        "price": get_price(driver),
        "address": get_address(driver),
        "key_features": "; ".join(key_features),
        "media": ";".join(get_media(driver)),
        "agency": agency,
        "inspection_times": inspection_time,
        "auction_date": auction_data,
        "property_url": url,
    }
    for idx, agent in enumerate(agent_data, start=1):
        details[f"agent_name{idx}"] = agent["name"]
        details[f"agent_phone{idx}"] = agent["phone"]
    return details

def save_to_csv(data, filename):
    file_exists = os.path.isfile(filename)
    
    with open(filename, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=data.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(data)


def save_links(page_links_dict, filename="link_state.json"):
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            existing_data = json.load(f)
    else:
        existing_data = {}

    # Merge with existing (overwrite if same page is scraped again)
    existing_data.update(page_links_dict)

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(existing_data, f, indent=2, ensure_ascii=False)

    print(f"Saved links for {len(page_links_dict)} pages to {filename}")

def save_progress(page_num, property_index):
    """Save current progress to config.json"""
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        config['scraping']['page'] = page_num
        config['scraping']['property_index'] = property_index
        
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        
        print(f"💾 Progress saved: Page {page_num}, Property {property_index}")
    except Exception as e:
        print(f"⚠️ Could not save progress: {e}")

def load_progress():
    """Load progress from config.json"""
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        page = config['scraping'].get('page', 1)
        property_index = config['scraping'].get('property_index', 0)
        
        print(f"📖 Resuming from: Page {page}, Property {property_index}")
        return page, property_index
    except Exception as e:
        print(f"⚠️ Could not load progress, starting from beginning: {e}")
        return 1, 0

def get_processed_urls(filename: str) -> set:
    """Read already saved property URLs from CSV into a set"""
    processed = set()
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if "property_url" in row and row["property_url"]:
                        processed.add(row["property_url"])
        except Exception as e:
            print(f"⚠️ Could not read processed URLs: {e}")
    return processed


def main():
    driver = None
    current_page = 1
    current_property_index = 0
    
    try:
        token = signin()
        HEADERS.update({"Authorization": f"Bearer {token}"})
        print("Authentication successful")

        driver = start_profile()
        processed_urls = get_processed_urls(CSV_FILE)
        
        # Load progress from config
        start_page, start_property_index = load_progress()
        total_pages = 450
        
        for page_num in range(start_page, total_pages + 1):
            current_page = page_num
            # Fetch property links for this page
            page_links = get_property_links(driver, page_num)

            print(f"\n📄 Page {page_num}: Found {len(page_links)} property links\n")

            # Save links state
            save_links({f"page_{page_num}": page_links})

            # Determine starting property index for this page
            start_property_index_for_page = start_property_index if page_num == start_page else 0
            
            # Visit each property on this page
            for property_index, property_url in enumerate(page_links):
                current_property_index = property_index
                
                # Skip properties we've already processed on this page
                if property_index < start_property_index_for_page:
                    print(f"⏭️ Skipping already processed property {property_index + 1}: {property_url}")
                    continue
                    
                if property_url in processed_urls:
                    print(f"⏭️ Skipping already processed: {property_url}")
                    continue

                try:
                    details = get_property_details(driver, property_url)

                    # If no details were found, stop everything
                    # if not details or not details.get("address"):
                    #     raise ValueError("No details extracted")
                    if not details or not details.get("address"):
                        print("🚫 Block detected while scraping property – no address found")
                        save_progress(current_page, current_property_index)
                        return  # stop scraping immediately
                    save_to_csv(details, CSV_FILE)
                    processed_urls.add(property_url)
                    print(f"✅ Saved: {details['address']}")
                    
                    # Save progress after each successful property
                    save_progress(page_num, property_index + 1)

                except Exception as e:
                    print(f"❌ Failed to scrape {property_url}: {e}")
                    print("⚠️ Continuing with next property...")
                    continue  # Continue with next property instead of stopping
                
                # Add pause between properties to avoid being detected as a bot
                print("⏸️ Pausing before next property...")
                time.sleep(6)  # Random delay between 3-7 seconds
            
            # Reset property index for next page
            start_property_index = 0

    except KeyboardInterrupt:
        print("\n⚠️ Keyboard interrupt detected! Saving progress...")
        # Save current progress before stopping
        try:
            save_progress(current_page, current_property_index + 1)
        except:
            pass
        print("Stopping profile...")
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        # Save current progress even on error
        try:
            save_progress(current_page, current_property_index + 1)
        except:
            pass
    finally:
        try:
            stop_profile()
        except Exception as e:
            print(f"Error stopping profile: {e}")


if __name__ == "__main__":
    main()