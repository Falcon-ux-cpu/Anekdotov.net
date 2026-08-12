import os
import re
import time
import random
import shutil
import tempfile
import smtplib
from urllib.parse import urljoin
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
import requests
from bs4 import BeautifulSoup

# --- Настройки SMTP для Яндекс.Почты ---
SMTP_SERVER = "smtp.yandex.ru"
SMTP_PORT = 465

# Настройки из переменных окружения (GitHub Secrets)
YANDEX_USER = os.environ.get("GMAIL_USER")       
YANDEX_PASSWORD = os.environ.get("GMAIL_APP_PASS") 
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", YANDEX_USER)

BASE_URL = "https://anekdotov.net"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def fetch_page(url):
    """Скачивает страницу с правильной кодировкой cp1251."""
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        res.encoding = 'cp1251'
        return res.text
    except Exception as e:
        print(f"Ошибка при загрузке {url}: {e}")
        return ""

def parse_text_category(url):
    """Парсит текстовые категории, группируя абзацы одного контента по ID из href."""
    html = fetch_page(url)
    if not html:
        return []
    
    soup = BeautifulSoup(html, 'html.parser')
    grouped_items = {}
    
    for p in soup.find_all('p'):
        a_tag = p.find('a', href=True)
        if a_tag and ('/anekdot/all/' in a_tag['href'] or '/story/all/' in a_tag['href']):
            # Извлекаем уникальный ID публикации из href (например, hstkpdvdnschnbl.htm)
            item_id = a_tag['href'].split('/')[-1]
            
            text = p.get_text().replace('\xa0', ' ').strip()
            text = re.sub(r'\s+', ' ', text)
            
            if text:
                if item_id not in grouped_items:
                    grouped_items[item_id] = []
                if text not in grouped_items[item_id]:
                    grouped_items[item_id].append(text)
                
    # Объединяем разрозненные абзацы одной истории/анекдота в единый блок
    final_items = []
    for paragraphs in grouped_items.values():
        full_text = "<br><br>".join(paragraphs)
        final_items.append(full_text)
                
    return final_items

def parse_pictures(url, temp_dir):
    """Скачивает картинки и собирает подписи к ним."""
    html = fetch_page(url)
    if not html:
        return []
    
    soup = BeautifulSoup(html, 'html.parser')
    pictures = []
    img_counter = 0

    for img in soup.find_all('img'):
        src = img.get('src', '')
        if '/pic/photo' in src:
            full_img_url = urljoin(BASE_URL, src)
            
            caption = ""
            next_i = img.find_next_sibling('i')
            if not next_i:
                parent = img.parent
                if parent:
                    next_i = parent.find('i')
            
            if next_i:
                caption = next_i.get_text().strip()
            
            try:
                img_res = requests.get(full_img_url, headers=HEADERS, timeout=15)
                if img_res.status_code == 200:
                    img_counter += 1
                    file_ext = os.path.splitext(src)[1] or '.jpg'
                    file_name = f"image_{img_counter}{file_ext}"
                    file_path = os.path.join(temp_dir, file_name)
                    
                    with open(file_path, 'wb') as f:
                        f.write(img_res.content)
                        
                    pictures.append({
                        'cid': f"img_{img_counter}",
                        'file_path': file_path,
                        'file_name': file_name,
                        'caption': caption
                    })
            except Exception as e:
                print(f"Ошибка скачивания картинки {full_img_url}: {e}")

    return pictures

def build_single_item_html(content_html):
    """Оборачивает единичный элемент в общий HTML-каркас."""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{
                font-family: Arial, Helvetica, sans-serif;
                background-color: #f4f4f9;
                color: #222222;
                margin: 0;
                padding: 15px;
            }}
            .container {{
                max-width: 680px;
                margin: 0 auto;
                background: #ffffff;
                border: 1px solid #dddddd;
                border-radius: 8px;
                padding: 20px;
            }}
            .item-card {{
                background: #fafafa;
                border-left: 4px solid #1976d2;
                padding: 12px 15px;
                border-radius: 0 4px 4px 0;
                font-size: 15px;
                line-height: 1.5;
            }}
            .story-card {{
                border-left-color: #388e3c;
            }}
            .pic-card {{
                text-align: center;
                background: #fafafa;
                padding: 15px;
                border-radius: 6px;
                border: 1px solid #eeeeee;
            }}
            .pic-card img {{
                max-width: 100% !important;
                height: auto !important;
                display: block;
                margin: 0 auto;
                border-radius: 4px;
            }}
            .caption {{
                font-style: italic;
                color: #555555;
                margin-top: 8px;
                font-size: 14px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            {content_html}
        </div>
    </body>
    </html>
    """

def send_single_email(server, subject, html_body, pic=None):
    """Отправляет одно отдельное письмо с динамической темой."""
    msg = MIMEMultipart('related')
    msg['Subject'] = subject
    msg['From'] = YANDEX_USER
    msg['To'] = RECIPIENT_EMAIL

    msg_alternative = MIMEMultipart('alternative')
    msg.attach(msg_alternative)
    msg_alternative.attach(MIMEText(html_body, 'html', 'utf-8'))

    if pic:
        try:
            with open(pic['file_path'], 'rb') as f:
                img_data = f.read()
            
            mime_img = MIMEImage(img_data)
            mime_img.add_header('Content-ID', f"<{pic['cid']}>")
            mime_img.add_header('Content-Disposition', 'inline', filename=pic['file_name'])
            msg.attach(mime_img)
        except Exception as e:
            print(f"Ошибка прикрепления файла {pic['file_path']}: {e}")

    server.sendmail(YANDEX_USER, RECIPIENT_EMAIL, msg.as_string())

def main():
    temp_dir = tempfile.mkdtemp()
    
    try:
        print("Парсинг анекдотов...")
        anekdots = parse_text_category(f"{BASE_URL}/anekdot/today.html")
        
        print("Парсинг историй...")
        stories = parse_text_category(f"{BASE_URL}/story/today.html")
        
        print("Парсинг и скачивание картинок...")
        pictures = parse_pictures(f"{BASE_URL}/pic/today.html", temp_dir)

        total_count = len(anekdots) + len(stories) + len(pictures)
        print(f"Собрано всего элементов: {total_count} (анекдотов: {len(anekdots)}, историй: {len(stories)}, картинок: {len(pictures)}).")

        if total_count > 0:
            print("Подключение к SMTP-серверу Яндекса (SSL:465)...")
            with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
                server.login(YANDEX_USER, YANDEX_PASSWORD)

                # 1. Отправляем анекдоты
                for i, anekdot in enumerate(anekdots, 1):
                    content_html = f'<div class="item-card">{anekdot}</div>'
                    html_body = build_single_item_html(content_html)
                    send_single_email(server, "Anekdotov.net: анекдот", html_body)
                    print(f"Отправлен анекдот {i}/{len(anekdots)}")
                    
                    delay = random.randint(5, 12)
                    time.sleep(delay)

                # 2. Отправляем истории
                for i, story in enumerate(stories, 1):
                    content_html = f'<div class="item-card story-card">{story}</div>'
                    html_body = build_single_item_html(content_html)
                    send_single_email(server, "Anekdotov.net: история", html_body)
                    print(f"Отправлена история {i}/{len(stories)}")
                    
                    delay = random.randint(5, 12)
                    time.sleep(delay)

                # 3. Отправляем картинки
                for i, pic in enumerate(pictures, 1):
                    caption_html = f'<div class="caption">{pic["caption"]}</div>' if pic["caption"] else ""
                    content_html = f"""
                    <div class="pic-card">
                        <img src="cid:{pic['cid']}" alt="Картинка">
                        {caption_html}
                    </div>
                    """
                    html_body = build_single_item_html(content_html)
                    send_single_email(server, "Anekdotov.net: фото", html_body, pic=pic)
                    print(f"Отправлена картинка {i}/{len(pictures)}")
                    
                    delay = random.randint(5, 12)
                    time.sleep(delay)

            print("Все письма успешно отправлены!")
        else:
            print("Контент не найден, письма не отправлялись.")

    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            print("Временные файлы и картинки успешно удалены с сервера.")

if __name__ == "__main__":
    main()
