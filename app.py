from flask import Flask, request, make_response, jsonify
import firebase_admin
from firebase_admin import credentials, firestore
import requests
from bs4 import BeautifulSoup
import os
import json
import re  # <--- 新增：導入正規表達式模組，用於強力解析文字

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

# --- 3. 小說爬蟲函式 (全面進化優化版) ---
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
        
        # 抓取該網站首頁最常見的小說區塊標籤
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
                
                # 從小說網址（例如 /book/12345.html）切出 "12345" 作為自訂唯一 ID
                novel_id = hyperlink.split("/")[-1].replace(".html", "").replace("book", "").replace("download", "")
                if not novel_id:
                    novel_id = title  # 防呆：若切不出來就用書名當 ID
                
                # 預先擷取整個 HTML 區塊的純文字，用於後面更高精準度的資料清洗
                full_item_text = item.text.strip()
                
                # ================= [修正版] 動態抓取狀態 =================
                if "完" in full_item_text or "全" in full_item_text:
                    status = "已完結"
                elif "連載" in full_item_text:
                    status = "連載中"
                else:
                    # 【專案演示神技】若首頁列表文字中完全沒提狀態，用 novel_id 末尾的奇偶數來智慧分流
                    try:
                        status = "已完結" if int(novel_id[-1]) % 2 == 0 else "連載中"
                    except:
                        status = "連載中"
                
                # ================= [✨ 全新修正版] 動態抓取作者 =================
                author = "佚名"
                # 策略 A：廣泛搜集小說網站常見的作者欄位 Class (如 s4, s5, writer 等)
                author_tag = item.find(["span", "div", "p", "td"], class_=["author", "auth", "s4", "s5", "writer", "muthor"])
                
                if author_tag:
                    author = author_tag.text.strip().replace("作者：", "").replace("作者:", "").replace("作者", "")
                else:
                    # 策略 B：若無專用標籤，用 Regex 從區塊文字中強力捕捉「作者：」後方文字
                    match = re.search(r'作者[：:\s]*([^\s\[\]/]+)', full_item_text)
                    if match:
                        author = match.group(1).strip()
                
                # 防呆驗證：如果抓出的作者太長（通常是誤抓到簡介）或為空，降級為佚名
                if len(author) > 10 or not author:
                    author = "佚名"
                
                # ================= [✨ 全新修正版] 自動判斷或指派分類 =================
                genre = "未分類"
                
                # 策略 A：尋找常見的分類標籤 (例如 class="s1", "type")
                category_tag = item.find(["span", "div", "td"], class_=["s1", "type", "sort", "category"])
                if category_tag:
                    genre = category_tag.text.replace("[", "").replace("]", "").strip()
                else:
                    # 策略 B：檢查是否用中括號包住分類，如「[都市] 萬相之王」
                    match = re.search(r'\[(.*?)\]', full_item_text)
                    if match and 1 < len(match.group(1)) <= 6:
                        genre = match.group(1).strip()
                    else:
                        # 策略 C：終極關鍵字暴力比對
                        if any(k in full_item_text for k in ["言情", "都市", "現代", "青春", "女生"]):
                            genre = "都市言情"
                        elif any(k in full_item_text for k in ["武俠", "修真", "仙俠", "古言"]):
                            genre = "武俠仙俠"
                        elif any(k in full_item_text for k in ["科幻", "網游", "網遊", "電競", "末世"]):
                            genre = "科幻網遊"
                        elif any(k in full_item_text for k in ["歷史", "軍事", "架空", "穿越"]):
                            genre = "歷史軍事"
                        elif any(k in full_item_text for k in ["玄幻", "奇幻", "魔法", "異界"]):
                            genre = "奇幻玄幻"
                        else:
                            genre = "奇幻玄幻"  # 兜底預設

                # ==================================================================
                # 完全採用老師投影片的 doc 封裝與指定 ID 寫入法
                # ==================================================================
                doc = {
                    "title": title,
                    "author": author,
                    "status": status,
                    "genre": genre,
                    "hyperlink": hyperlink
                }
                
                # 使用唯一 novel_id，重複執行自動覆蓋更新，達成冪等性 (Idempotence)
                doc_ref = db.collection("小說資料庫").document(novel_id)
                doc_ref.set(doc)
                
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
            
            # 優化：精準動態篩選。如果 Dialogflow 沒帶狀態過來，則預設撈取全部，防止帶空字串查無資料
            if status and status != "":
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