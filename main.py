from linebot.models import FlexSendMessage
from linebot.models import (
    MessageEvent, TextSendMessage
)
from linebot.exceptions import (
    InvalidSignatureError
)
from linebot.aiohttp_async_http_client import AiohttpAsyncHttpClient
from linebot import (
    AsyncLineBotApi, WebhookParser
)
from fastapi import Request, FastAPI, HTTPException
import google.generativeai as genai
import os
import sys
from io import BytesIO
import json

import aiohttp
import PIL.Image
import firebase_admin
from firebase_admin import credentials, db


# get channel_secret and channel_access_token from your environment variable
channel_secret = os.getenv('ChannelSecret', None)
channel_access_token = os.getenv('ChannelAccessToken', None)
gemini_key = os.getenv('GEMINI_API_KEY')
firebase_url = os.getenv('FIREBASE_URL')
imgage_prompt = '''
This is a receipt, and you are a secretary. 
Please organize the details from the receipt into JSON format for me. 
I only need the JSON representation of the receipt data. Eventually, 
I will need to input it into a database with the following structure:

 Receipt(ReceiptID, PurchaseStore, PurchaseDate, PurchaseAddress, TotalAmount) and 
 Items(ItemID, ReceiptID, ItemName, ItemPrice). 

Data format as follow:
- ReceiptID, using PurchaseDate, but Represent the year, month, day, hour, and minute without any separators.
- ItemID, using ReceiptID and sequel number in that receipt. 
Otherwise, if any information is unclear, fill in with 'N/A'. 
'''

json_translate_from_nonchinese_prompt = '''
This is a JSON representation of a receipt.
Please translate the non-Chinese characters into Chinese for me.
Using format as follow:
    non-Chinese(Chinese)
All the Chinese will use in zh_tw.
Please response with the translated JSON.
'''

if channel_secret is None:
    print('Specify LINE_CHANNEL_SECRET as environment variable.')
    sys.exit(1)
if channel_access_token is None:
    print('Specify LINE_CHANNEL_ACCESS_TOKEN as environment variable.')
    sys.exit(1)
if gemini_key is None:
    print('Specify GEMINI_API_KEY as environment variable.')
    sys.exit(1)
if firebase_url is None:
    print('Specify FIREBASE_URL as environment variable.')
    sys.exit(1)

# Initialize the FastAPI app for LINEBot
app = FastAPI()
session = aiohttp.ClientSession()
async_http_client = AiohttpAsyncHttpClient(session)
line_bot_api = AsyncLineBotApi(channel_access_token, async_http_client)
parser = WebhookParser(channel_secret)

# Initialize the Firebase Database
user_receipt_path = f''
user_item_path = f''
user_all_receipts_path = f''

# Initialize Firebase Admin
cred = credentials.ApplicationDefault()
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {"databaseURL": firebase_url})

# Initialize the Gemini Pro API
genai.configure(api_key=gemini_key)


# ================= Gemini 相關 =================
def generate_gemini_text_complete(prompt: str):
    """
    使用 Gemini 產生文字回應。
    :param prompt: 輸入提示文字
    :return: Gemini 回應物件
    """
    model = genai.GenerativeModel('gemini-2.0-flash')
    response = model.generate_content(prompt)
    return response


def generate_json_from_receipt_image(img, prompt: str):
    """
    使用 Gemini 處理發票圖片，回傳 JSON 格式資料。
    :param img: 發票圖片
    :param prompt: 輸入提示文字
    :return: Gemini 回應物件
    """
    model = genai.GenerativeModel('gemini-2.0-flash')
    response = model.generate_content([prompt, img], stream=True)
    response.resolve()
    return response


# ================= Firebase 相關 =================
def add_receipt(receipt_data: dict, items: list, user_receipt_path: str, user_item_path: str):
    """
    新增發票與品項至 Firebase。
    :param receipt_data: 發票資料 dict
    :param items: 品項資料 list
    :param user_receipt_path: Firebase 路徑
    :param user_item_path: Firebase 路徑
    """
    try:
        receipt_id = receipt_data.get('ReceiptID')
        db.reference(user_receipt_path).child(receipt_id).set(receipt_data)
        for item in items:
            item_id = item.get('ItemID')
            db.reference(user_item_path).child(item_id).set(item)
        print(f"Add ReceiptID: {receipt_id} completed.")
    except Exception as e:
        print(f"Error in add_receipt: {e}")


def check_if_receipt_exists(receipt_id: str, user_receipt_path: str) -> bool:
    """
    檢查發票是否已存在。
    :param receipt_id: 發票 ID
    :param user_receipt_path: Firebase 路徑
    :return: 是否存在
    """
    try:
        receipt = db.reference(user_receipt_path).child(receipt_id).get()
        return receipt is not None
    except Exception as e:
        print(f"Error in check_if_receipt_exists: {e}")
        return False


# ================= 資料處理 =================
def parse_receipt_json(receipt_json_str: str):
    """
    將收據 JSON 字串轉為 dict。
    :param receipt_json_str: JSON 字串
    :return: dict
    """
    try:
        lines = receipt_json_str.strip().split('\n')
        json_str = '\n'.join(lines[1:-1])
        receipt_data = json.loads(json_str)
        return receipt_data
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}")
        return None


def extract_receipt_data(receipt_json_obj: dict):
    """
    從 JSON dict 取出發票與品項資料。
    :param receipt_json_obj: dict
    :return: (items, receipt_obj)
    """
    receipt_obj = None
    items = []
    if receipt_json_obj:
        receipt_obj = receipt_json_obj.get('Receipt')
        if receipt_obj:
            if isinstance(receipt_obj, list):
                receipt_obj = receipt_obj[0]
        items = receipt_json_obj.get('Items', [])
    return items, receipt_obj


# ================= Flex Message 組裝 =================
def get_receipt_flex_msg(receipt_data: dict, items: list) -> FlexSendMessage:
    """
    產生 Flex Message。
    :param receipt_data: 發票 dict
    :param items: 品項 list
    :return: FlexSendMessage
    """
    items_contents = [
        {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {"type": "text", "text": f"{item.get('ItemName')}",
                 "size": "sm", "color": "#555555", "flex": 0},
                {"type": "text", "text": f"${item.get('ItemPrice')}",
                 "size": "sm", "color": "#111111", "align": "end"}
            ]
        } for item in items
    ]
    flex_msg = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "RECEIPT", "weight": "bold",
                    "color": "#1DB446", "size": "sm"},
                {"type": "text", "text": f"{receipt_data.get('PurchaseStore')}",
                 "weight": "bold", "size": "xxl", "margin": "md"},
                {"type": "text", "text": f"{receipt_data.get('PurchaseAddress')}",
                 "size": "xs", "color": "#aaaaaa", "wrap": True},
                {"type": "separator", "margin": "xxl"},
                {"type": "box", "layout": "vertical", "margin": "xxl",
                    "spacing": "sm", "contents": items_contents},
                {"type": "separator", "margin": "xxl"},
                {"type": "box", "layout": "horizontal", "margin": "md", "contents": [
                    {"type": "text", "text": "RECEIPT ID",
                        "size": "xs", "color": "#aaaaaa", "flex": 0},
                    {"type": "text", "text": f"{receipt_data.get('ReceiptID')}",
                     "color": "#aaaaaa", "size": "xs", "align": "end"}
                ]}
            ]
        },
        "styles": {"footer": {"separator": True}}
    }
    return FlexSendMessage(alt_text="Receipt Data", contents=flex_msg)


# ================= 主流程 =================
@app.post("/")
async def handle_callback(request: Request):
    signature = request.headers['X-Line-Signature']
    body = (await request.body()).decode()
    try:
        events = parser.parse(body, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    for event in events:
        if not isinstance(event, MessageEvent):
            continue
        user_id = event.source.user_id
        user_receipt_path = f'receipt_helper/{user_id}/Receipts'
        user_item_path = f'receipt_helper/{user_id}/Items'
        user_all_receipts_path = f'receipt_helper/{user_id}'
        if event.message.type == "text":
            all_receipts = db.reference(user_all_receipts_path).get()
            reply_msg = TextSendMessage(text='No message to reply with')
            msg = event.message.text
            if msg == '!清空':
                reply_msg = TextSendMessage(text='對話歷史紀錄已經清空！')
                db.reference(user_all_receipts_path).delete()
            else:
                prompt_msg = f'Here is my entire receipt list during my travel: {all_receipts}; please answer my question based on this information. {msg}. Reply in zh_tw.'
                response = generate_gemini_text_complete(prompt_msg)
                reply_msg = TextSendMessage(text=response.text)
            await line_bot_api.reply_message(event.reply_token, reply_msg)
        elif event.message.type == "image":
            message_content = await line_bot_api.get_message_content(event.message.id)
            image_content = b''
            async for s in message_content.iter_content():
                image_content += s
            img = PIL.Image.open(BytesIO(image_content))
            result = generate_json_from_receipt_image(img, imgage_prompt)
            tw_result = generate_gemini_text_complete(
                result.text + "\n --- " + json_translate_from_nonchinese_prompt)
            items, receipt = extract_receipt_data(
                parse_receipt_json(result.text))
            tw_items, tw_receipt = extract_receipt_data(
                parse_receipt_json(tw_result.text))
            if check_if_receipt_exists(receipt.get('ReceiptID'), user_receipt_path):
                reply_msg = get_receipt_flex_msg(receipt, items)
                chinese_reply_msg = get_receipt_flex_msg(tw_receipt, tw_items)
                await line_bot_api.reply_message(event.reply_token, [TextSendMessage(text="這個收據已經存在資料庫中。"), reply_msg, chinese_reply_msg])
                return 'OK'
            add_receipt(tw_receipt, tw_items,
                        user_receipt_path, user_item_path)
            reply_msg = get_receipt_flex_msg(receipt, items)
            chinese_reply_msg = get_receipt_flex_msg(tw_receipt, tw_items)
            await line_bot_api.reply_message(event.reply_token, [reply_msg, chinese_reply_msg])
            return 'OK'
        else:
            continue
    return 'OK'
