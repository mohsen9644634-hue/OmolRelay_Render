from flask import Flask

app = Flask(__name__)

@app.route('/')
def hello_world():
    return 'سلام پویا! پروژه شما با موفقیت در Render.com مستقر شد.'

if __name__ == '__main__':
    app.run(debug=True)


