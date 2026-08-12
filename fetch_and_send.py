import os
import re
import shutil
import tempfile
import smtplib
from urllib.parse import urljoin
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
import requests
from bs4 import BeautifulSoup

# --- Настройки из переменных окружения (GitHub Secrets) ---
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
GMAIL_USER = os.environ.get("GMAIL_USER")       # Ваш Gmail (например, user@gmail.com)
GMAIL_PASSWORD = os.environ.get("GMAIL_APP_PASS") # Пароль приложения Gmail (16 символов)
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", GMAIL_USER)

BASE_URL = "https://anekdotov.net"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def fetch_page(url):
    """Скачивает страницу с правильной кодировкой cp1251."""
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        res.encoding = 'cp1251' # anekdotov.net использует cp1251 (windows-1251)
        return res.text
    except Exception as e:
        print(f"Ошибка при загрузке {url}: {e}")
        return ""

def parse_text_category(url):
    """Парсит текстовые категории (анекдоты и истории)."""
    html = fetch_page(url)
    if not html:
        return []
    
    soup = BeautifulSoup(html, 'html.parser')
    items = []
    
    # Ищем теги <p>, содержащие ссылки на анекдоты/истории
    for p in soup.find_all('p'):
        a_tag = p.find('a', href=True)
        if a_tag and ('/anekdot/all/' in a_tag['href'] or '/story/all/' in a_tag['href']):
            # Получаем весь текст внутри <p>, убирая неразрывные пробелы \xa0
            text = p.get_text().replace('\xa0', ' ').strip()
            # Убираем возможные дублирующиеся пробелы
            text = re.sub(r'\s+', ' ', text)
            if text:
                items.append(text)
                
    return items

def parse_pictures(url, temp_dir):
    """Скачивает картинки и собирает подписи к ним."""
    html = fetch_page(url)
    if not html:
        return []
    
    soup = BeautifulSoup(html, 'html.parser')
    pictures = []
    
    img_tags = soup.find_all('img')
    img_counter = 0

    for img in img_tags:
        src = img.get('src', '')
        if '/pic/photo' in src:
            full_img_url = urljoin(BASE_URL, src)
            
            # Находим подпись (следующий тег <i>)
            caption = ""
            next_i = img.find_next_sibling('i')
            if not next_i:
                # Если <i> идет чуть дальше в родителе
                parent = img.parent
                if parent:
                    next_i = parent.find('i')
            
            if next_i:
                caption = next_i.get_text().strip()
            
            # Скачиваем изображение во временную папку
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

def build_html_body(anekdots, stories, pictures):
    """Формирует адаптивный HTML-шаблон письма."""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {
                font-family: Arial, Helvetica, sans-serif;
                background-color: #f4f4f9;
                color: #222222;
                margin: 0;
                padding: 15px;
            }
            .container {
                max-width: 680px;
                margin: 0 auto;
                background: #ffffff;
                border: 1px solid #dddddd;
                border-radius: 8px;
                padding: 20px;
            }
            h2 {
                color: #d32f2f;
                border-bottom: 2px solid #d32f2f;
                padding-bottom: 5px;
                margin-top: 25px;
            }
            .item-card {
                background: #fafafa;
                border-left: 4px solid #1976d2;
                margin-bottom: 12px;
                padding: 12px 15px;
                border-radius: 0 4px 4px 0;
                font-size: 15px;
                line-height: 1.5;
            }
            .story-card {
                border-left-color: #388e3c;
            }
            .pic-card {
                text-align: center;
                margin-bottom: 25px;
                background: #fafafa;
                padding: 15px;
                border-radius: 6px;
                border: 1px solid #eeeeee;
            }
            /* Предотвращает выпирание изображений */
            .pic-card img {
                max-width: 100% !important;
                height: auto !important;
                display: block;
                margin: 0 auto;
                border-radius: 4px;
            }
            .caption {
                font-style: italic;
                color: #555555;
                margin-top: 8px;
                font-size: 14px;
            }
        </style>
    </head>
    <body>
        <div class="container">
    """

    # Раздел: Анекдоты
    if anekdots:
        html += "<h2>Свежие анекдоты</h2>"
        for item in anekdots:
            html += f'<div class="item-card">{item}</div>'

    # Раздел: Истории
    if stories:
        html += "<h2>Свежие истории</h2>"
        for item in stories:
            html += f'<div class="item-card story-card">{item}</div>'

    # Раздел: Карикатуры / Картинки
    if pictures:
        html += "<h2>Свежие картинки</h2>"
        for pic in pictures:
            caption_html = f'<div class="caption">{pic["caption"]}</div>' if pic["caption"] else ""
            html += f"""
            <div class="pic-card">
                <img src="cid:{pic['cid']}" alt="Картинка">
                {caption_html}
            </div>
            """

    html += """
        </div>
    </body>
    </html>
    """
    return html

def send_email(html_body, pictures):
    """Отправляет письмо с вложенными CID-картинками."""
    # Требование: Тема письма должна содержать строго "Anekdotov.net"
    msg = MIMEMultipart('related')
    msg['Subject'] = "Anekdotov.net"
    msg['From'] = GMAIL_USER
    msg['To'] = RECIPIENT_EMAIL

    # Добавляем HTML-тело
    msg_alternative = MIMEMultipart('alternative')
    msg.attach(msg_alternative)
    msg_alternative.attach(MIMEText(html_body, 'html', 'utf-8'))

    # Внедряем картинки как CID вложения
    for pic in pictures:
        try:
            with open(pic['file_path'], 'rb') as f:
                img_data = f.read()
            
            mime_img = MIMEImage(img_data)
            mime_img.add_header('Content-ID', f"<{pic['cid']}>")
            mime_img.add_header('Content-Disposition', 'inline', filename=pic['file_name'])
            msg.attach(mime_img)
        except Exception as e:
            print(f"Ошибка прикрепления файла {pic['file_path']}: {e}")

    # Отправка через Gmail SMTP
    print("Подключение к SMTP-серверу Gmail...")
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())
    print("Письмо успешно отправлено!")

def main():
    # Создаем временную папку для загрузки картинок
    temp_dir = tempfile.mkdtemp()
    
    try:
        print("Парсинг анекдотов...")
        anekdots = parse_text_category(f"{BASE_URL}/anekdot/today.html")
        
        print("Парсинг историй...")
        stories = parse_text_category(f"{BASE_URL}/story/today.html")
        
        print("Парсинг и скачивание картинок...")
        pictures = parse_pictures(f"{BASE_URL}/pic/today.html", temp_dir)

        print(f"Собрано: {len(anekdots)} анекдотов, {len(stories)} историй, {len(pictures)} картинок.")

        if anekdots or stories or pictures:
            html_body = build_html_body(anekdots, stories, pictures)
            send_email(html_body, pictures)
        else:
            print("Контент не найден, письмо не отправлено.")

    finally:
        # Требование: После отправки удалить все картинки и временные файлы с сервера
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            print("Временные файлы и картинки успешно удалены с сервера.")

if __name__ == "__main__":
    main()
