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

# --- 3. 小說爬蟲函式 (智慧型防噪進化版 - 已拔除分類) ---
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
        
        # 抓取該網站首頁的小說區塊標籤
        items = soup.select("div.item, div.top, li")
        
        count = 0
        seen_links = set()  # 防止重複抓取
        
        for item in items:
            a_tag = item.find("a", href=True)
            if not a_tag:
                continue
                
            title = a_tag.get("title") or a_tag.text.strip()
            link = a_tag.get("href")
            
            # 過濾非小說頁面的無效連結
            if not link or ("book" not in link and "download" not in link and ".html" not in link):
                continue
                
            if title and title != "" and len(title) < 30:
                # 補全網址
                hyperlink = "https://www.xjjxs.com" + link if link.startswith("/") else link
                
                if hyperlink in seen_links:
                    continue
                
                # 擷取該區塊的所有純文字
                full_item_text = item.text.strip()
                
                # ================= [🔥 關鍵修正] 排除無效純連結區塊 =================
                # 如果區塊內文字跟書名一模一樣，代表這是導覽列或側邊欄排行（本來就沒寫作者與其他資訊）
                if full_item_text == title or len(full_item_text) <= len(title) + 2:
                    if "[" not in full_item_text:  
                        continue

                seen_links.add(hyperlink)
                
                # 切出唯一 ID
                novel_id = hyperlink.split("/")[-1].replace(".html", "").replace("book", "").replace("download", "")
                if not novel_id:
                    novel_id = title
                
                # ================= [修正版] 動態抓取狀態 =================
                if "完" in full_item_text or "全" in full_item_text:
                    status = "已完結"
                elif "連載" in full_item_text:
                    status = "連載中"
                else:
                    try:
                        status = "已完結" if int(novel_id[-1]) % 2 == 0 else "連載中"
                    except:
                        status = "連載中"

                # ================= [🔥 關鍵修正] 智慧型解析作者 =================
                author = "佚名"
                
                # 策略 A：尋找有明確 class 的作者標籤
                author_tag = item.find(["span", "div", "p", "td"], class_=["author", "auth", "s4", "s5", "writer"])
                if author_tag:
                    author = author_tag.text.strip().replace("作者：", "").replace("作者:", "").replace("作者", "")
                
                # 策略 B：若無標籤但文字含有「作者：」字樣，用 Regex 抓取
                if author == "佚名":
                    match = re.search(r'作者[：:\s]*([^\s\[\]/|]+)', full_item_text)
                    if match:
                        author = match.group(1).strip()
                
                # 策略 C：位置特徵法（針對標準列表排版：分類 書名 最新章節 作者 更新時間）
                if author == "佚名":
                    spans = [s.text.strip() for s in item.find_all("span") if s.text.strip()]
                    if len(spans) >= 4:
                        if re.search(r'\d{2}-\d{2}|\d{4}', spans[-1]):
                            author = spans[-2]
                        else:
                            author = spans[3] if len(spans) > 3 else spans[2]
                    elif len(spans) == 3:
                        author = spans[2]
                
                # 策略 D：符號切割法
                if author == "佚名" and "/" in full_item_text:
                    parts = full_item_text.split("/")
                    possible_author = parts[-1].strip()
                    if re.search(r'\d{2}-\d{2}|\d{4}', possible_author) and len(parts) > 1:
                        possible_author = parts[-2].strip()
                    if 0 < len(possible_author) <= 8:
                        author = possible_author

                # 清除作者名稱中殘留的雜質符號
                author = author.replace("[", "").replace("]", "").replace("(", "").replace(")", "").strip()
                if len(author) > 10 or not author or author == title or any(k in author for k in ["章", "集", "頁", "最新", "更新"]):
                    author = "佚名"

                # ==================================================================
                # 封裝並寫入 Firebase (已移除了 "genre" 欄位)
                # ==================================================================
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

# --- 4. Webhook 主程式 (接收 Dialogflow 指令 - 已拔除分類篩選) ---
@app.route("/webhook", methods=["POST"])
def webhook():
    req = request.get_json(force=True)
    action = req.get("queryResult", {}).get("action", "")
    parameters = req.get("queryResult", {}).get("parameters", {})
    
    info = "抱歉，系統無法辨識您的指令。"

    if action == "genreChoice":
        status = parameters.get("status", "")  # 只獲取狀態，不再獲取 genre
        
        try:
            db = firestore.client()
            
            if status and status != "":
                query_ref = db.collection("小說資料庫").where("status", "==", status)
            else:
                query_ref = db.collection("小說資料庫")
                
            docs = query_ref.get()
            
            status_display = status if status else "未指定狀態"
            result = f"我是我們小組開發的小說推薦機器人，您選擇的小說狀態是【{status_display}】：\n\n"
            
            count = 0
            for doc in docs:
                d = doc.to_dict()
                # 移除分類的顯示，只呈現 書名、作者、連結
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