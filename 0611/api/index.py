from flask import Flask, request, make_response, jsonify
import firebase_admin
from firebase_admin import credentials, firestore
import requests
from bs4 import BeautifulSoup
import os
import json

# --- 1. 初始化 Firebase ---
if not firebase_admin._apps:
    firebase_config = os.getenv('FIREBASE_CONFIG')
    if firebase_config:
        cred = credentials.Certificate(json.loads(firebase_config))
        firebase_admin.initialize_app(cred)

app = Flask(__name__)

# --- 2. 首頁路由 ---
@app.route("/")
def home():
    return "小組期末報告：小說推薦機器人後台網頁伺服器已成功啟動！"

# --- 3. 小說爬蟲函式 (全面優化網頁解析結構，確保不為 0 筆) ---
@app.route("/crawl")
def run_spider():
    db = firestore.client()
    url = "https://www.xjjxs.com/"
    
    # 模擬真人瀏覽器，防止網站拒絕連線
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        res = requests.get(url, headers=headers, verify=False, timeout=15)
        # 自動偵測並修正簡體網頁編碼
        res.encoding = res.apparent_encoding if res.apparent_encoding else 'gbk'
        
        soup = BeautifulSoup(res.text, "html.parser")
        
        # 擴大搜尋範圍：同時抓取該網站首頁最常見的小說區塊標籤
        items = soup.select("div.item, div.top, li")
        
        count = 0
        for item in items:
            # 尋找含有小說連結與標題的 a 標籤
            a_tag = item.find("a", href=True)
            if not a_tag:
                continue
                
            # 擷取書名 (有些在 title 屬性，有些在純文字)
            title = a_tag.get("title") or a_tag.text.strip()
            link = a_tag.get("href")
            
            # 過濾掉不是小說頁面的非必要連結（例如分類按鈕、首頁按鈕、服務條款等）
            if not link or "book" not in link and "download" not in link and ".html" not in link:
                continue
                
            if title and title != "" and len(title) < 30:  # 避免抓到整段長文章
                # 補全相對路徑網址
                if link.startswith("/"):
                    link = "https://www.xjjxs.com" + link
                
                # 動態抓取狀態或隨機配置（迎合學長姐的四大欄位需求）
                status_tag = item.find("span") or item.find("em")
                status = status_tag.text.strip() if status_tag else "連載中"
                if "完" in status or "全" in status:
                    status = "已完結"
                elif "連" in status or "著" in status:
                    status = "連載中"
                
                # 動態抓取作者
                author_tag = item.find("span", class_="author") or item.find("p")
                author = author_tag.text.strip().replace("作者：", "") if author_tag else "佚名"
                if len(author) > 10 or author == "": 
                    author = "佚名"
                
                # 自動判斷或指派分類
                genre = "奇幻玄幻"
                if "言情" in title or "都市" in title:
                    genre = "都市言情"
                elif "武俠" in title or "修真" in title:
                    genre = "武俠仙俠"
                
                # ====== 完全採用學長姐圖一的資料庫輸入寫法 ======
                doc = {
                    "title": title,
                    "author": author,
                    "status": status,
                    "genre": genre,
                    "hyperlink": link
                }
                
                # 自動產生亂碼 ID
                doc_ref = db.collection("小說資料庫").document()
                doc_ref.set(doc)
                # ==================================================
                
                count += 1
                
                # 限制首頁先抓 15-20 筆精彩資料即可，避免 Vercel 執行逾時
                if count >= 20:
                    break
                    
        return f"小說爬蟲及存檔完畢，已成功精確抓取並新增 {count} 筆小說資料到 Firebase 小說資料庫！"
        
    except Exception as e:
        return f"爬蟲發生錯誤: {e}"

# --- 4. Webhook 主程式 (接收 Dialogflow 指令) ---
@app.route("/webhook", methods=["POST"])
def webhook():
    req = request.get_json(force=True)
    action = req.get("queryResult", {}).get("action", "")
    parameters = req.get("queryResult", {}).get("parameters", {})
    
    info = "抱歉，系統無法辨識您的指令。"

    if action == "genreChoice":
        status = parameters.get("status", "")  
        genre = parameters.get("genre", "")    
        
        db = firestore.client()
        docs = db.collection("小說資料庫").where("status", "==", status).get()
        
        result = f"我是我們小組開發的小說推薦機器人，您選擇的小說狀態是【{status}】：\n\n"
        count = 0
        for doc in docs:
            d = doc.to_dict()
            if genre == "" or genre in d.get("genre", ""):
                result += f"📖 書名：{d['title']}\n✍️ 作者：{d['author']}\n🏷️ 分類：{d['genre']}\n🔗 連結：{d['hyperlink']}\n\n"
                count += 1
            
        info = result if count > 0 else f"目前資料庫中沒有符合【{status}】的小說資料。"

    return make_response(jsonify({"fulfillmentText": info}))

if __name__ == "__main__":
    app.run(debug=True)