from parnya import app, start_bot, set_leverage

if __name__ == "__main__":
    set_leverage()
    start_bot()
    app.run(host="0.0.0.0", port=5000)
