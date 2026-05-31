# import finnhub
# import time

# # 1. Apni Finnhub API Key yahan dalein
# FINNHUB_API_KEY = "d8e8anpr01qm5f80dff0d8e8anpr01qm5f80dffg"

# # 2. Client initialize karein
# finnhub_client = finnhub.Client(api_key=FINNHUB_API_KEY)

# # 3. Un stocks ki list jinhe aap scan karna chahte hain
# stocks_to_scan = ["NVDA", "MU", "AMD", "SNDK", "ARM"]

# def scan_prices():
#     print("\n--- Fetching Latest Prices ---")
#     for symbol in stocks_to_scan:
#         try:
#             # quote() function real-time/latest price lata hai
#             res = finnhub_client.quote(symbol)
            
#             current_price = res['c']  # 'c' ka matlab hota hai Current Price
#             high_price = res['h']     # 'h' ka matlab High of the day
#             low_price = res['l']      # 'l' ka matlab Low of the day
            
#             print(f"{symbol}: Current: ${current_price} | High: ${high_price} | Low: ${low_price}")
#         except Exception as e:
#             print(f"Error fetching {symbol}: {e}")

# # Test karne ke liye hum ise har 1 minute (60 seconds) me run karenge
# try:
#     while True:
#         scan_prices()
#         time.sleep(60)  # 1 minute ka wait
# except KeyboardInterrupt:
#     print("\nScanning stopped by user.")



import requests
import time

# 1. Apni Twelve Data API Key yahan dalein
TWELVE_DATA_API_KEY = "0bec98c23b3142a590d4f9efe7520fe1"

# 2. Un stocks ki list jinhe aap scan karna chahte hain (Comma separated string)
# Twelve Data ki khubsurati: Ek saath saare stocks ka data mil jata hai
stocks_list = "AAPL,MSFT,AMZN,TSLA,NVDA"

def scan_twelve_data():
    print("\n--- Fetching Latest Prices from Twelve Data ---")
    
    # Hum 'price' endpoint use kar rahe hain jo latest ticker value deta hai
    url = f"https://api.twelvedata.com/price?symbol={stocks_list}&apikey={TWELVE_DATA_API_KEY}"
    
    try:
        response = requests.get(url)
        data = response.json()
        
        # Agar single stock hota hai toh output alag hota hai, multiple me alag
        if "status" in data and data["status"] == "error":
            print(f"API Error: {data['message']}")
            return

        # Saare stocks ka data print karna
        for symbol, info in data.items():
            print(f"{symbol}: ${info['price']}")
            
    except Exception as e:
        print(f"Error fetching data: {e}")

# Chaliye ise locally test karte hain (Har 5 minute me chalane ke liye)
try:
    while True:
        scan_twelve_data()
        time.sleep(300)  # 300 seconds = 5 minutes
except KeyboardInterrupt:
    print("\nScanning stopped locally.")