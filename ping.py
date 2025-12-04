import time
import requests

URL = "https://your-render-service.onrender.com/"

while True:
    try:
        requests.get(URL)
    except:
        pass
    time.sleep(60)
