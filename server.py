from parnya import app, start_bot, set_leverage
import threading

if __name__ == "__main__":
    set_leverage()
    
    # Run trading bot in a background thread that survives Flask reloads
    t = threading.Thread(target=start_bot, daemon=True)
    t.start()

    app.run(host="0.0.0.0", port=5000, use_reloader=False)
