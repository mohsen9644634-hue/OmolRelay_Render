###################################################################
#                 PARNYA FUTURES BOT — ULTRA+                    #
#     AI‑CONFIDENCE ENGINE + 3TF (M5/M15/H1) + TRAILING SYSTEM   #
#  SMART BREAKEVEN + REAL STOP ORDERS + DYNAMIC RISK MANAGEMENT  #
#        MULTI‑STAGE EXIT + AI Signal Filter + Render Safe       #
###################################################################

import time, hmac, hashlib, requests, os
from threading import Thread
from flask import Flask, jsonify
import statistics

# =================== CONFIG ====================
BASE_URL = "https://api.coinex.com/perpetual/v1"
SPOT_URL = "https://api.coinex.com/v1"
SYMBOL = "BTCUSDT"
AMOUNT = 0.01
LEVERAGE = 10
RISK_PER_TRADE = 0.01  # 1% risk of balance

API_KEY = os.getenv("COINEX_KEY")
API_SECRET = os.getenv("COINEX_SECRET").encode()

position = None
entry_price = None
sl_price = None
tp_price = None
confidence = 0.0
partials_done = [False, False, False]


# ---------- SIGN ----------
def sign(params):
    s = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
    return hmac.new(API_SECRET, s.encode(), hashlib.sha256).hexdigest()

def private_req(method, endpoint, params=None):
    if params is None: params={}
    params["access_id"]=API_KEY
    params["timestamp"]=int(time.time()*1000)
    params["tonce"]=int(time.time()*1000)
    params["signature"]=sign(params)
    url=BASE_URL+endpoint
    try:
        if method=="GET": r=requests.get(url,params=params,timeout=8)
        else: r=requests.post(url,data=params,timeout=8)
        return r.json()
    except: return {"code":500}


# ---------- INDICATORS ----------
def ema(values, p):
    if len(values)<p: return [values[-1]]
    k=2/(p+1)
    e=[values[0]]
    for v in values[1:]: e.append(v*k+e[-1]*(1-k))
    return e

def macd(c):
    closes=[float(x[2]) for x in c]
    e12=ema(closes,12); e26=ema(closes,26)
    m=[a-b for a,b in zip(e12,e26)]
    s=ema(m,9)
    h=[i-j for i,j in zip(m,s)]
    return m[-1], s[-1], h[-1]

def atr(c,p=14):
    trs=[]
    for i in range(1,len(c)):
        h=float(c[i][0]); l=float(c[i][1]); pc=float(c[i-1][2])
        trs.append(max(h-l,abs(h-pc),abs(l-pc)))
    return sum(trs[-p:])/p if trs else 0

def supertrend(c, p=10, m=3):
    h=[float(x[0]) for x in c]; l=[float(x[1]) for x in c]; cl=[float(x[2]) for x in c]
    a=atr(c,p)
    up=(h[-1]+l[-1])/2+m*a; dn=(h[-1]+l[-1])/2-m*a
    return "LONG" if cl[-1]>up else "SHORT" if cl[-1]<dn else None

def rsi(c, p=14):
    cl=[float(x[2]) for x in c]
    if len(cl)<p: return 50
    d=[cl[i]-cl[i-1] for i in range(1,len(cl))]
    g=[x for x in d if x>0]; l=[-x for x in d if x<0]
    ag=sum(g[-p:])/p if g else 0; al=sum(l[-p:])/p if l else 0
    return 100-(100/(1+(ag/al if al>0 else 9999)))


# ---------- MARKET ----------
def candles(tf="5min", limit=160):
    try:
        r=requests.get(f"{SPOT_URL}/market/kline?market={SYMBOL}&type={tf}&limit={limit}",timeout=6).json()
        return r.get("data",[])
    except: return []

def price():
    try:
        r=requests.get(f"{BASE_URL}/market/ticker?market={SYMBOL}",timeout=6).json()
        return float(r["data"]["ticker"]["last"])
    except: return None

def balance():
    try:
        d=private_req("GET","/account/query")
        return float(d["data"]["balance"]["USDT"])
    except: return 100


# ---------- ORDERS ----------
def open_pos(side):
    direction="buy" if side=="LONG" else "sell"
    r=private_req("POST","/order/put_market",{
        "market":SYMBOL,"side":direction,"amount":AMOUNT,"type":"market","leverage":LEVERAGE
    })
    try: return float(r["data"]["price"])
    except: return price()

def stop_loss(side, pr):
    return private_req("POST","/order/put_stop",{
        "market":SYMBOL,
        "side":"sell" if side=="LONG" else "buy",
        "amount":AMOUNT,"stop_price":pr,"type":"market"
    })

def take_profit(side, pr):
    return private_req("POST","/order/put_stop",{
        "market":SYMBOL,
        "side":"sell" if side=="LONG" else "buy",
        "amount":AMOUNT,"stop_price":pr,"type":"market"
    })

def partial_close(side, amt):
    return private_req("POST","/position/close",{
        "market":SYMBOL,"side":"close","amount":amt
    })


# ---------- AI CONFIDENCE ----------
def ai_confidence():
    c5=candles("5min"); c15=candles("15min"); c60=candles("60min")
    if not c5 or not c15 or not c60: return 0, "NONE"

    m5=macd(c5)[2]; m15=macd(c15)[2]; m60=macd(c60)[2]
    st5=supertrend(c5); st15=supertrend(c15); st60=supertrend(c60)
    r5=rsi(c5); r15=rsi(c15); r60=rsi(c60)

    longScore=sum([
        m5>0,m15>0,m60>0,
        st5=="LONG",st15=="LONG",st60=="LONG",
        r5>50,r15>50,r60>50
    ])
    shortScore=sum([
        m5<0,m15<0,m60<0,
        st5=="SHORT",st15=="SHORT",st60=="SHORT",
        r5<50,r15<50,r60<50
    ])

    if longScore>shortScore:
        conf=longScore/9
        return conf,"LONG"
    elif shortScore>longScore:
        conf=shortScore/9
        return conf,"SHORT"
    return 0,"NONE"


# ---------- MANAGER ----------
def manager(sig, conf):
    global position, entry_price, sl_price, tp_price, partials_done

    c=candles("5min"); a=atr(c); p=price()
    if not c or not p: return

    bal=balance()
    risk_amt=bal*RISK_PER_TRADE
    stop_dist=2*a if a>0 else 100
    global AMOUNT
    AMOUNT = abs(risk_amt / stop_dist / p)

    # Entry
    if position is None and sig in ["LONG","SHORT"] and conf>=0.7:
        entry=open_pos(sig)
        if sig=="LONG":
            sl_price=entry-2*a; tp_price=entry+5*a
        else:
            sl_price=entry+2*a; tp_price=entry-5*a
        stop_loss(sig,sl_price)
        take_profit(sig,tp_price)
        position=sig
        partials_done=[False,False,False]
        return

    if position:
        # Breakeven
        if position=="LONG" and p>=entry_price+1.5*a and sl_price<entry_price:
            sl_price=entry_price; stop_loss(position,sl_price)
        if position=="SHORT" and p<=entry_price-1.5*a and sl_price>entry_price:
            sl_price=entry_price; stop_loss(position,sl_price)

        # Trailing
        if position=="LONG":
            ns=p-2*a
            if ns>sl_price: sl_price=ns; stop_loss(position,sl_price)
        if position=="SHORT":
            ns=p+2*a
            if ns<sl_price: sl_price=ns; stop_loss(position,sl_price)

        # Partial 50%
        if not partials_done[0]:
            if position=="LONG" and p>=entry_price+2*a:
                partial_close(position,AMOUNT*0.5)
                partials_done[0]=True
            if position=="SHORT" and p<=entry_price-2*a:
                partial_close(position,AMOUNT*0.5)
                partials_done[0]=True

        # Partial 25%
        if not partials_done[1]:
            if position=="LONG" and p>=entry_price+3.5*a:
                partial_close(position,AMOUNT*0.25)
                partials_done[1]=True
            if position=="SHORT" and p<=entry_price-3.5*a:
                partial_close(position,AMOUNT*0.25)
                partials_done[1]=True

        # Reverse
        if position=="LONG" and conf>0.6 and sig=="SHORT":
            partial_close(position,AMOUNT); position=None
        if position=="SHORT" and conf>0.6 and sig=="LONG":
            partial_close(position,AMOUNT); position=None


# ---------- WEB ----------
app=Flask(__name__)
@app.route("/")
def home(): return "ULTRA+ ACTIVE"
@app.route("/status")
def st():
    return jsonify({
        "position":position,"entry":entry_price,
        "sl":sl_price,"tp":tp_price,"confidence":confidence
    })


# ---------- LOOP ----------
def loop():
    global confidence
    while True:
        conf,sig=ai_confidence()
        confidence=conf
        manager(sig,conf)
        time.sleep(10)

if __name__=="__main__":
    Thread(target=loop).start()
    from waitress import serve
    serve(app,host="0.0.0.0",port=int(os.getenv("PORT",10000)))
