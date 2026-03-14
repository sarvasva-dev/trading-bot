import requests
import time

def test_request(name, url, headers=None):
    print(f"Testing {name}...")
    try:
        start = time.time()
        r = requests.get(url, headers=headers, timeout=10)
        print(f"  Status: {r.status_code}")
        print(f"  Time: {time.time() - start:.2f}s")
        print(f"  Content Type: {r.headers.get('Content-Type')}")
        return True
    except Exception as e:
        print(f"  Failed {name}: {e}")
        return False

url = "https://www.nseindia.com/api/corporate-announcements?index=equities&from_date=14-03-2026&to_date=14-03-2026"

# Case 1: Bare Request
test_request("Bare Request", url)

# Case 2: Just User-Agent
test_request("Just User-Agent", url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"})

# Case 3: Proper Browser Headers
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9",
}
test_request("Full Browser Headers", url, headers=headers)
