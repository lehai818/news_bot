# %%
import time
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import os
import re
import json


load_dotenv("tk_key.env") #nếu cần file cụ thể thì cứ thêm "" vào trong ngoặc là được 
# Bây giờ bạn lấy các thông tin bảo mật ra xài bằng os.getenv('TÊN_BIẾN')
BOT_TOKEN = os.getenv("news_bot_token")
TELEGRAM_CHAT_ID = os.getenv("tk_chatid")


# %%
# print (BOT_TOKEN)

# %%

# ==========================================
# 1. CẤU HÌNH ĐỊNH TUYẾN KÊNH NGUỒN VÀ THREAD_ID
# ==========================================
BOT_TOKEN = BOT_TOKEN
TARGET_CHAT_ID = TELEGRAM_CHAT_ID  # ID Nhóm/Kênh đích (phải dạng số -100xxx)
TARGET_THREAD_ID = 202            # ID của Topic / Thread trong nhóm
onchain_thread = 146

# Khai báo dạng: "Username_Kênh_Nguồn": Thread_ID_Đích
# Danh sách username kênh công khai (không có dấu @)
# (Nếu không dùng Topic cho kênh nào đó, bạn để giá trị là None)
SOURCE_CHANNELS = {
    "DecryptNews": TARGET_THREAD_ID,
    "cointelegraph": TARGET_THREAD_ID,
    "CoinMarketCapAnnouncements": TARGET_THREAD_ID,
    "unfolded_defi": TARGET_THREAD_ID,
    "lookonchainchannel": onchain_thread
    # "crypto_channel_khac": None  # Ví dụ kênh gửi vào ô Chat chính
}

# DANH SÁCH TỪ KHÓA LINK CẦN LỌC (Blacklist)
# Hễ link nào chứa một trong các từ khóa này sẽ bị xử lý:
LINK_BLACKLIST = [
    "t.me/",             # Link dẫn sang các kênh Telegram khác
    "bit.ly",            # Link rút gọn
    "binance.com/ref",   # Link giới thiệu (ref)
    "cointelegraph.com",   # Tên miền website bất kỳ bạn không muốn xuất hiện
    "cointelegraph.com",
    "@cointelegraph",   # Tên miền website bất kỳ bạn không muốn xuất hiện
    "coindesk.com",
    "decrypt",
    "CoinMarketCap",
    "theblock.co",
    "1inch.com",
    "coinmarketcap.com",
    "coinmarketcap.com/academy",
    
    
]

# 2. DANH SÁCH TỪ KHÓA / USERNAME BỊ XÓA KHỎI TEXT THUẦN
TEXT_KEYWORDS_TO_REMOVE = [
    "1inch",
    # "@DecryptNews",
    "@CoinMarketCapAnnouncements",
    "CoinMarketCap",
    "CoinMarketCap"
]

# Lưu ID bài viết cuối cùng của từng kênh để lọc bài cũ & bài trùng
last_seen_posts = {}
is_first_run = True  # Cờ đánh dấu lần chạy đầu tiên


# %%
# ==========================================
# 1. LỌC TIN NHẮN HỆ THỐNG (SERVICE MESSAGE)
# ==========================================
def is_service_message(post_div, text_content):
    """Bỏ qua các tin nhắn hệ thống như 'pinned a photo', 'pinned a message',..."""
    # Check class của Telegram Web
    if post_div.find('div', class_='tgme_widget_message_service_message'):
        return True
    
    # Check từ khóa thông báo hệ thống
    service_keywords = [
        "pinned a photo",
        "pinned a message",
        "pinned an audio",
        "pinned a video",
        "unpinned a message",
        "joined the channel",
        "changed channel photo"
    ]
    if any(keyword in text_content.lower() for keyword in service_keywords):
        return True
        
    return False


# ==========================================
# 2. CHUẨN HÓA HTML & LỌC TỪ KHÓA / LINK
# ==========================================
def sanitize_telegram_html(text_div):
    """Gỡ link xấu nhưng giữ nguyên tiêu đề, gỡ thẻ HTML lỗi và xóa Username thừa"""
    if not text_div:
        return ""
    
    # --- Bước A: Xử lý thẻ link <a href="..."> ---
    for a_tag in text_div.find_all('a'):
        href = a_tag.get('href', '').lower()
        anchor_text = a_tag.text.strip().lower()
        
        if any(bad.lower() in href for bad in LINK_BLACKLIST):
            # Nếu thẻ <a> bọc tiêu đề/văn bản dài -> bóc thẻ <a> ra, GIỮ NGUYÊN CHỮ
            if len(anchor_text) > 15 or not any(kw in anchor_text for kw in ["t.me", "http", "click", "join"]):
                a_tag.unwrap()  
            else:
                # Nếu chỉ là nút/link quảng cáo ngắn -> Xóa hẳn cả thẻ lẫn chữ
                a_tag.decompose()

    # --- Bước B: Xóa URL thô hiện ra dưới dạng text ---
    raw_html = text_div.decode_contents()
    for bad_domain in LINK_BLACKLIST:
        if "." in bad_domain or "/" in bad_domain:
            url_pattern = re.compile(r'https?://[^\s<]*' + re.escape(bad_domain) + r'[^\s<]*', re.IGNORECASE)
            raw_html = url_pattern.sub('', raw_html)

    # --- Bước C: Chuẩn hóa xuống dòng & thẻ HTML hợp lệ Telegram ---
    soup = BeautifulSoup(raw_html, 'html.parser')
    for tag in soup.find_all(['br', 'p', 'div']):
        tag.insert_after('\n')

    allowed_tags = ['a', 'b', 'strong', 'i', 'em', 'u', 'ins', 's', 'strike', 'del', 'code', 'pre']
    for tag in soup.find_all(True):
        if tag.name not in allowed_tags:
            tag.unwrap()

    final_text = soup.decode_contents().strip()

    # --- Bước D: Xóa các Username / Từ khóa thương hiệu dạng text thuần ---
    for bad_kw in TEXT_KEYWORDS_TO_REMOVE:
        pattern = re.compile(re.escape(bad_kw), re.IGNORECASE)
        final_text = pattern.sub("", final_text)

    # Dọn dẹp dòng trống thừa
    final_text = re.sub(r'\n\s*\n', '\n\n', final_text)

    return final_text.strip()


# ==========================================
# 3. TẢI VÀ XÓA FILE ẢNH TẠM (CLEANUP)
# ==========================================
def download_photos(photo_urls):
    """Tải ảnh về máy để gửi dữ liệu dạng file bytes chuẩn"""
    saved_files = []
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    for idx, url in enumerate(photo_urls):
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200 and res.content:
                file_path = f"temp_{int(time.time())}_{idx}.jpg"
                with open(file_path, "wb") as f:
                    f.write(res.content)
                saved_files.append(file_path)
        except Exception as e:
            print(f"⚠️ Lỗi khi tải ảnh: {e}")
            
    return saved_files


def cleanup_files(file_paths):
    """Xóa ảnh tạm sau khi gửi xong"""
    for fp in file_paths:
        try:
            if os.path.exists(fp):
                os.remove(fp)
        except Exception as e:
            print(f"⚠️ Không thể xóa file {fp}: {e}")


# ==========================================
# 4. GỬI TIN BẰNG TELEGRAM API (RETRY 1 LẦN)
# ==========================================
def send_to_telegram(text, photo_urls, thread_id=None):
    
    """Gửi bài + Retry 1 lần dạng Plain Text nếu lỗi HTML + Cleanup ảnh"""
    saved_files = download_photos(photo_urls)
    
    caption_text = text
    if saved_files and len(caption_text) > 1000:
        caption_text = caption_text[:990] + "..."

    def create_request_payload(use_html=True, plain_text_override=None):
        current_text = plain_text_override if plain_text_override is not None else (caption_text if saved_files else text)
        opened_files = {}

        payload = {
            "chat_id": TARGET_CHAT_ID,
            "disable_web_page_preview": True  # Tắt khung Preview Link ở cuối bài
        }
        
        if thread_id is not None:
            payload["message_thread_id"] = thread_id

        # Gửi Album nhiều ảnh
        if len(saved_files) > 1:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMediaGroup"
            media = []
            for idx, fp in enumerate(saved_files):
                key = f"photo_{idx}"
                opened_files[key] = open(fp, "rb")
                item = {"type": "photo", "media": f"attach://{key}"}
                if idx == 0 and current_text:
                    item["caption"] = current_text
                    if use_html:
                        item["parse_mode"] = "HTML"
                media.append(item)
            payload["media"] = json.dumps(media)
            return url, payload, opened_files

        # Gửi 1 ảnh
        elif len(saved_files) == 1:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
            opened_files["photo"] = open(saved_files[0], "rb")
            payload["caption"] = current_text
            if use_html:
                payload["parse_mode"] = "HTML"
            return url, payload, opened_files

        # Gửi Text thuần
        else:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            payload["text"] = current_text
            if use_html:
                payload["parse_mode"] = "HTML"
            return url, payload, {}

    try:
        time_now = time.strftime('%H:%M:%S %d/%m/%Y')
        # --- LẦN 1: GỬI ĐỊNH DẠNG HTML ---
        url, payload, opened_files = create_request_payload(use_html=True)
        res = requests.post(url, data=payload, files=opened_files if opened_files else None)
        
        for f in opened_files.values():
            f.close()

        res_json = res.json()
        if res_json.get("ok"):
            print(f"🚀 [SUCCESS] Đã gửi tới Topic #{thread_id}! at {time_now}")
            return True

        # --- LẦN 2 (RETRY 1 LẦN DUY NHẤT): GỬI DẠNG PLAIN TEXT ---
        print(f"❌ [LẦN 1 THẤT BẠI]: {res_json.get('description')}")
        print("🔄 RETRY (1 LẦN DUY NHẤT): Chuyển sang gửi dạng Text thuần...")

        plain_text = BeautifulSoup(text, 'html.parser').text
        plain_caption = plain_text[:990] + "..." if saved_files and len(plain_text) > 1000 else plain_text

        url_fb, payload_fb, opened_files_fb = create_request_payload(use_html=False, plain_text_override=plain_caption)
        res_fb = requests.post(url_fb, data=payload_fb, files=opened_files_fb if opened_files_fb else None)

        for f in opened_files_fb.values():
            f.close()

        if res_fb.json().get("ok"):
            print(f"🚀 [SUCCESS] Retry thành công dạng Text thuần tới Topic #{thread_id}!")
            return True
        else:
            print(f"❌ [RETRY THẤT BẠI]: {res_fb.json().get('description')}")
            return False

    except Exception as e:
        print(f"⚠️ Lỗi ngoại lệ trong quá trình gửi: {e}")
        return False

    finally:
        cleanup_files(saved_files)


# ==========================================
# 5. QUY TRÌNH QUÉT VA VÀ BẮT TIN TƯƠNG LAI
# ==========================================
def fetch_latest_news(channel, thread_id):
    global is_first_run
    
    url = f"https://t.me/s/{channel}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return

        soup = BeautifulSoup(response.text, 'html.parser')
        posts = soup.find_all('div', class_='tgme_widget_message')
        
        if not posts:
            return

        latest_post = posts[-1]
        post_id = latest_post.get('data-post')

        # Khởi tạo mốc lần đầu -> Không gửi tin cũ
        if channel not in last_seen_posts:
            last_seen_posts[channel] = post_id
            print(f"📌 Đã khởi tạo mốc cho [{channel}] (Post ID: {post_id}) -> Định tuyến Topic #{thread_id}")
            return

        if last_seen_posts.get(channel) == post_id:
            return

        text_div = latest_post.find('div', class_='tgme_widget_message_text')
        raw_text_content = text_div.text if text_div else ""

        # LỌC TIN HỆ THỐNG (Service Message)
        if is_service_message(latest_post, raw_text_content):
            print(f"⏭️ Bỏ qua tin nhắn hệ thống (Pinned/Service) trên [{channel}]")
            last_seen_posts[channel] = post_id
            return

        clean_text = sanitize_telegram_html(text_div)

        # Trích xuất URL ảnh
        photo_urls = []
        photo_tags = latest_post.find_all('a', class_='tgme_widget_message_photo_wrap')
        for tag in photo_tags:
            if tag.get('style'):
                match = re.search(r"background-image:url\(['\"]?(.*?)['\"]?\)", tag['style'])
                if match:
                    photo_urls.append(match.group(1))

        if clean_text or photo_urls:
            print(f"\n🔍 [TIN MỚI XUẤT HIỆN] Bài [{post_id}] từ kênh: {channel}")
            send_to_telegram(text=clean_text, photo_urls=photo_urls, thread_id=thread_id)
            
            # Cập nhật mốc đã xử lý
            last_seen_posts[channel] = post_id

    except Exception as e:
        print(f"⚠️ Lỗi xử lý kênh {channel}: {e}")



# %%

# ==========================================
# MAIN LOOP
# ==========================================
if __name__ == "__main__":
    print("🚀 Bot Cào Tin Telegram (Bản Hoàn Chỉnh All-in-One) đang chạy...")
    
    while True:
        for channel, thread_id in SOURCE_CHANNELS.items():
            fetch_latest_news(channel, thread_id)
                
        if is_first_run:
            is_first_run = False
            print("\n✅ Đã đồng bộ xong tất cả mốc kênh! Bot bắt đầu chờ tin MỚI TƯƠNG LAI...\n")
            
        time.sleep(15)

# %%



# %%




