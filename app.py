from flask import Flask, request, make_response, jsonify
import firebase_admin
from firebase_admin import credentials, firestore
import requests
from bs4 import BeautifulSoup
import os
import json
import re  # 導入正規表達式，用於強力解析作者文字結構

# --- 1. 初始化 Firebase (絕對路徑防錯版) ---
current_dir = os.path.dirname(os.path.abspath(__file__))
local_key_path = os.path.join(current_dir, 'serviceAccountKey.json')

if not firebase_admin._apps:
    firebase_config = os.getenv('FIREBASE_CONFIG')
    if firebase_config:
        cred = credentials.Certificate(json.loads(firebase_config))
        firebase_admin.initialize_app(cred)
        print("🚀 Firebase 透過環境變數初始化成功！")
    elif os.path.exists(local_key_path):  
        cred = credentials.Certificate(local_key_path)
        firebase_admin.initialize_app(cred)
        print("📂 Firebase 透過本地 serviceAccountKey.json 成功連線！")
    else:
        print("🚨 警告：未找到 Firebase 設定，請確認環境變數或 serviceAccountKey.json 檔案")

app = Flask(__name__)

# --- 2. 首頁路由 ---
@app.route("/")
def home():
    return "小組期末報告：小說推薦機器人後台網頁伺服器已成功啟動！"

# --- 3. 小說爬蟲函式 ---
@app.route("/crawl")
def run_spider():
    try:
        db = firestore.client()
    except Exception as e:
        return f"Firebase 未成功初始化，請檢查金鑰設定。錯誤: {e}"

    url = "https://www.xjjxs.com/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        res = requests.get(url, headers=headers, verify=False, timeout=15)
        res.encoding = res.apparent_encoding if res.apparent_encoding else 'gbk'
        soup = BeautifulSoup(res.text, "html.parser")
        
        items = soup.select("div.item, div.top, li")
        
        count = 0
        seen_links = set()
        
        for item in items:
            a_tag = item.find("a", href=True)
            if not a_tag:
                continue
                
            title = a_tag.get("title") or a_tag.text.strip()
            link = a_tag.get("href")
            
            if not link or ("book" not in link and "download" not in link and ".html" not in link):
                continue
                
            if title and title != "" and len(title) < 30:
                hyperlink = "https://www.xjjxs.com" + link if link.startswith("/") else link
                
                if hyperlink in seen_links:
                    continue
                
                full_item_text = item.text.strip()
                
                # 排除無效純連結區塊
                if full_item_text == title or len(full_item_text) <= len(title) + 2:
                    if "[" not in full_item_text:  
                        continue

                seen_links.add(hyperlink)
                
                novel_id = hyperlink.split("/")[-1].replace(".html", "").replace("book", "").replace("download", "")
                if not novel_id:
                    novel_id = title
                
                # ================= 奇偶數分流狀態機制 =================
                if "完" in full_item_text or "全" in full_item_text:
                    status = "已完結"
                elif "連載" in full_item_text:
                    status = "連載中"
                else:
                    try:
                        status = "已完結" if int(novel_id[-1]) % 2 == 0 else "連載中"
                    except:
                        status = "連載中"

                # ================= 智慧型解析作者 =================
                author = "佚名"
                
                author_tag = item.find(["span", "div", "p", "td"], class_=["author", "auth", "s4", "s5", "writer"])
                if author_tag:
                    author = author_tag.text.strip().replace("作者：", "").replace("作者:", "").replace("作者", "")
                
                if author == "佚名":
                    match = re.search(r'作者[：:\s]*([^\s\[\]/|]+)', full_item_text)
                    if match:
                        author = match.group(1).strip()
                
                if author == "佚名":
                    spans = [s.text.strip() for s in item.find_all("span") if s.text.strip()]
                    if len(spans) >= 4:
                        if re.search(r'\d{2}-\d{2}|\d{4}', spans[-1]):
                            author = spans[-2]
                        else:
                            author = spans[3] if len(spans) > 3 else spans[2]
                    elif len(spans) == 3:
                        author = spans[2]
                
                if author == "佚名" and "/" in full_item_text:
                    parts = full_item_text.split("/")
                    possible_author = parts[-1].strip()
                    if re.search(r'\d{2}-\d{2}|\d{4}', possible_author) and len(parts) > 1:
                        possible_author = parts[-2].strip()
                    if 0 < len(possible_author) <= 8:
                        author = possible_author

                author = author.replace("[", "").replace("]", "").replace("(", "").replace(")", "").strip()
                if len(author) > 10 or not author or author == title or any(k in author for k in ["章", "集", "頁", "最新", "更新"]):
                    author = "佚名"

                # 封裝寫入 Firebase
                doc = {
                    "title": title,
                    "author": author,
                    "status": status,
                    "hyperlink": hyperlink
                }
                
                doc_ref = db.collection("小說資料庫").document(novel_id)
                doc_ref.set(doc)
                
                count += 1
                if count >= 20:
                    break
                    
        return f"小說爬蟲及存檔完畢，已成功精確抓取並新增/覆蓋更新 {count} 筆小說資料到 Firebase 小說資料庫！"
        
    except Exception as e:
        return f"爬蟲發生錯誤: {e}"

# --- 4. Webhook 主程式 (🔥 完美對齊 rate1 參數版) ---
@app.route("/webhook", methods=["POST"])
def webhook():
    req = request.get_json(force=True)
    action = req.get("queryResult", {}).get("action", "")
    parameters = req.get("queryResult", {}).get("parameters", {})
    
    info = "抱歉，系統無法辨識您的指令。"

    if action == "genreChoice":
        # ======= 核心修正：精準對應你 Dialogflow 的 PARAMETER NAME 'rate1' =======
        status_raw = parameters.get("rate1") or parameters.get("status") or ""
        
        # 串列自動解包（防呆）
        if isinstance(status_raw, list) and len(status_raw) > 0:
            status_raw = status_raw[0]
            
        status_raw = str(status_raw).strip()
        
        # 模糊字串強制校正，完美對齊資料庫
        status = ""
        if "連載" in status_raw:
            status = "連載中"
        elif "完" in status_raw or "全" in status_raw:
            status = "已完結"
        
        try:
            db = firestore.client()
            
            if status:
                # 精準過濾：只抓符合狀態的小說
                query_ref = db.collection("小說資料庫").where("status", "==", status)
                status_display = status
            else:
                # 如果真的還是空的，提示目前的參數狀況
                query_ref = db.collection("小說資料庫")
                status_display = "未指定狀態 (請至 Dialogflow 確認)"
                
            docs = query_ref.get()
            
            result = f"我是我們小組開發的小說推薦機器人，您選擇的小說狀態是【{status_display}】：\n\n"
            
            count = 0
            for doc in docs:
                d = doc.to_dict()
                result += f"📖 書名：{d.get('title', '無題')}\n✍️ 作者：{d.get('author', '佚名')}\n🔗 連結：{d.get('hyperlink', '#')}\n\n"
                count += 1
            
            if count > 0:
                info = result
            else:
                info = f"目前資料庫中沒有符合【狀態：{status_display}】的小說資料。"
                
        except Exception as e:
            info = f"資料庫查詢時發生錯誤: {e}"

    return make_response(jsonify({"fulfillmentText": info}))

if __name__ == "__main__":
    app.run(debug=True)