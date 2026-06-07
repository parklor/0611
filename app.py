from flask import Flask, request, make_response, jsonify
import firebase_admin
from firebase_admin import credentials, firestore
import requests
from bs4 import BeautifulSoup
import os
import json

# --- 1. 初始化 Firebase (絕對路徑防錯版) ---
# 自動鎖定 app.py 旁邊的金鑰，防止因為工作目錄錯誤而找不到檔案
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

# --- 3. 小說爬蟲函式 (完美對齊楊子青老師版本 7 寫法) ---
@app.route("/crawl")
def run_spider():
    try:
        db = firestore.client()
    except Exception as e:
        return f"Firebase 未成功初始化，請檢查金鑰設定。錯誤: {e}"

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
        
        # 抓取該網站首頁最常見的小說區塊標籤 (對齊老師投影片 slide 1)
        items = soup.select("div.item, div.top, li")
        
        count = 0
        seen_links = set()  # 用來記錄這一輪已經抓過的網址，雙重防重機制
        
        for item in items:
            # 尋找含有小說連結與標題的 a 標籤
            a_tag = item.find("a", href=True)
            if not a_tag:
                continue
                
            # 擷取書名 (有些在 title 屬性，有些在純文字)
            title = a_tag.get("title") or a_tag.text.strip()
            link = a_tag.get("href")
            
            # 過濾掉不是小說頁面的非必要連結
            if not link or ("book" not in link and "download" not in link and ".html" not in link):
                continue
                
            if title and title != "" and len(title) < 30:  # 避免抓到整段長文章
                # 補全相對路徑網址
                if link.startswith("/"):
                    hyperlink = "https://www.xjjxs.com" + link
                else:
                    hyperlink = link
                
                if hyperlink in seen_links:
                    continue
                seen_links.add(hyperlink)
                
                # ==================================================================
                # ✨ 核心技術：仿照老師投影片 slide 2 萃取唯一 ID (movie_id) 的手法
                # 從小說網址（例如 /book/12345.html）切出 "12345" 作為自訂唯一 ID
                # ==================================================================
                novel_id = hyperlink.split("/")[-1].replace(".html", "").replace("book", "").replace("download", "")
                if not novel_id:
                    novel_id = title  # 防呆：若切不出來就用書名當 ID
                
                # 動態抓取狀態並清洗 (對齊老師投影片的資料清洗)
                status_tag = item.find("span") or item.find("em")
                status = status_tag.text.strip() if status_tag else "連載中"
                if "完" in status or "全" in status:
                    status = "已完結"
                else:
                    status = "連載中"
                
                # ======= [修正版] 動態抓取作者 =======
                author = "佚名"
                # 優先嘗試網站常見的作者標籤
                author_tag = item.find("span", class_="author") or item.find("span", class_="auth")
                
                if author_tag:
                    author = author_tag.text.strip().replace("作者：", "").replace("作者", "")
                else:
                    # 終極防線：直接從整段文字中尋找「作者」關鍵字進行切割
                    item_text = item.text.strip()
                    if "作者" in item_text:
                        parts = item_text.split("作者")
                        if len(parts) > 1:
                            # 拿後半段，去掉冒號，並只取第一個空白或換行前的文字
                            raw_author = parts[1].replace("：", "").replace(":", "").strip()
                            author = raw_author.split("\n")[0].split(" ")[0].split("/")[0].split("[")[0].strip()

                # 最後防線：如果抓出來的字還是太長（抓到簡介）或流標，才變回佚名
                if len(author) > 10 or author == "":
                    author = "佚名"
                # ====================================
                
                # ================= [修正版] 自動判斷或指派分類 =================
                # 拿取整個 HTML 區塊的文字（包含可能存在的 [都市]、[網游]、[修真] 等標籤文字）
                full_item_text = item.text.strip()
                
                # 預設分類
                genre = "奇幻玄幻"
                
                # 改用全文字範圍（full_item_text）來比對關鍵字，精準度大幅提升！
                if "言情" in full_item_text or "都市" in full_item_text or "現代" in full_item_text:
                    genre = "都市言情"
                elif "武俠" in full_item_text or "修真" in full_item_text or "仙俠" in full_item_text:
                    genre = "武俠仙俠"
                elif "科幻" in full_item_text or "網游" in full_item_text or "網遊" in full_item_text:
                    genre = "科幻網遊"
                elif "歷史" in full_item_text or "軍事" in full_item_text:
                    genre = "歷史軍事"
                # =============================================================
                
                # ==================================================================
                # ✨ 核心技術：完全採用老師投影片 slide 3 的 doc 封裝與指定 ID 寫入法
                # ==================================================================
                doc = {
                    "title": title,
                    "author": author,
                    "status": status,
                    "genre": genre,
                    "hyperlink": hyperlink
                }
                
                # 使用剛才切出來的 novel_id，重複執行時會自動覆蓋更新，達成冪等性 (Idempotence)
                doc_ref = db.collection("小說資料庫").document(novel_id)
                doc_ref.set(doc)
                # ==================================================================
                
                count += 1
                
                # 限制首頁先抓 20 筆，避免 Vercel 執行逾時
                if count >= 20:
                    break
                    
        return f"小說爬蟲及存檔完畢，已成功精確抓取並新增/覆蓋更新 {count} 筆小說資料到 Firebase 小說資料庫！"
        
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
        
        try:
            db = firestore.client()
            
            # 優化：動態查詢。如果 Dialogflow 沒有傳送狀態，就讀取全部
            if status:
                query_ref = db.collection("小說資料庫").where("status", "==", status)
            else:
                query_ref = db.collection("小說資料庫")
                
            docs = query_ref.get()
            
            status_display = status if status else "未指定狀態"
            result = f"我是我們小組開發的小說推薦機器人，您選擇的小說狀態是【{status_display}】"
            if genre:
                result += f"、分類是【{genre}】"
            result += "：\n\n"
            
            count = 0
            for doc in docs:
                d = doc.to_dict()
                # 第二層分類過濾（支援模糊比對）
                if not genre or genre in d.get("genre", ""):
                    result += f"📖 書名：{d.get('title', '無題')}\n✍️ 作者：{d.get('author', '佚名')}\n🏷️ 分類：{d.get('genre', '未分類')}\n🔗 連結：{d.get('hyperlink', '#')}\n\n"
                    count += 1
            
            if count > 0:
                info = result
            else:
                info = f"目前資料庫中沒有符合【狀態：{status_display} / 分類：{genre if genre else '未指定'}】的小說資料。"
                
        except Exception as e:
            info = f"資料庫查詢時發生錯誤: {e}"

    return make_response(jsonify({"fulfillmentText": info}))

if __name__ == "__main__":
    app.run(debug=True)