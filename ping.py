import time
import requests

URL = "https://omolrelay-render.onrender.com/status"

while True:
    try:
        r = requests.get(URL, timeout=10)
        print("PING ->", r.status_code)
    except Exception as e:
        print("Ping Error:", e)

    time.sleep(300)
