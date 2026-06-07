import requests
from bs4 import BeautifulSoup
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def crawl_and_classify(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    res = requests.get(url, headers=headers, verify=False, timeout=10)
    res.encoding = 'gbk'
    soup = BeautifulSoup(res.text, "html.parser")
    
    items = soup.find_all("div", class_="item") 
    
    finished_books = []
    serial_books = []

    for item in items:
        a_tag = item.find("a", href=True)
        span_tag = item.find("span")
        author_tag = item.find("dd", class_="author")
        
        if a_tag and span_tag:
            title = a_tag.get("title", "無標題")
            link = a_tag.get("href")
            status = span_tag.text.strip()
            # 抓取作者文字，並去除前後空白
            author = author_tag.text.strip() if author_tag else "作者未知"
            
            # 【修正點】在這裡把 author 變數加進去顯示
            book_info = f"書名: {title}\n作者: {author}\n連結: {link}\n" + "-"*30
            
            if "完結" in status or "完结" in status:
                finished_books.append(book_info)
            elif "連載" in status or "连载" in status:
                serial_books.append(book_info)

    print("\n【已完結小說】")
    for book in finished_books:
        print(book)

    print("\n【連載中小說】")
    for book in serial_books:
        print(book)

if __name__ == "__main__":
    crawl_and_classify("https://www.xjjxs.com/")