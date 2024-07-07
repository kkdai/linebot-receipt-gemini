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
from firebase import firebase


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
fdb = firebase.FirebaseApplication(firebase_url, None)

# Initialize the Gemini Pro API
genai.configure(api_key=gemini_key)


@app.post("/")
async def handle_callback(request: Request):
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = await request.body()
    body = body.decode()

    try:
        events = parser.parse(body, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    for event in events:
        if not isinstance(event, MessageEvent):
            continue

        user_id = event.source.user_id

        global user_receipt_path
        user_receipt_path = f'receipt_helper/{user_id}/Receipts'
        global user_item_path
        user_item_path = f'receipt_helper/{user_id}/Items'
        global user_all_receipts_path
        user_all_receipts_path = f'receipt_helper/{user_id}'

        if (event.message.type == "text"):
            all_receipts = fdb.get(user_all_receipts_path, None)

            # Provide a default value for reply_msg
            reply_msg = TextSendMessage(text='No message to reply with')

            msg = event.message.text
            if msg == '!清空':
                reply_msg = TextSendMessage(text='對話歷史紀錄已經清空！')
                fdb.delete(user_all_receipts_path, None)
            else:
                # fmt: off
                prompt_msg = f'Here is my entire receipt list during my travel: {all_receipts}; please answer my question based on this information. {msg}. Reply in zh_tw.'
                # fmt: on
                messages = []
                messages.append(
                    {"role": "user", "parts": prompt_msg})
                response = generate_gemini_text_complete(messages)
                reply_msg = TextSendMessage(text=response.text)

            await line_bot_api.reply_message(
                event.reply_token,
                reply_msg
            )
        elif (event.message.type == "image"):
            message_content = await line_bot_api.get_message_content(
                event.message.id)
            image_content = b''
            async for s in message_content.iter_content():
                image_content += s
            img = PIL.Image.open(BytesIO(image_content))

            # Using Gemini-Vision process image and get the JSON representation of the receipt data.
            result = generate_json_from_receipt_image(
                img, imgage_prompt)
            print(f"Before Translate Result: {result.text}")
            tw_result = generate_gemini_text_complete(
                result.text + "\n --- " + json_translate_from_nonchinese_prompt)
            print(f"After Translate Result: {tw_result.text}")

            # Check if receipt_data is not None
            items, receipt = extract_receipt_data(
                parse_receipt_json(result.text))
            tw_items, tw_receipt = extract_receipt_data(
                parse_receipt_json(tw_result.text))

            # Check if receipt exists, skip if it does
            if check_if_receipt_exists(receipt.get('ReceiptID')):
                reply_msg = get_receipt_flex_msg(receipt, items)
                chinese_reply_msg = get_receipt_flex_msg(
                    tw_receipt, tw_items)

                await line_bot_api.reply_message(
                    event.reply_token,
                    [TextSendMessage(
                        text="這個收據已經存在資料庫中。"), reply_msg, chinese_reply_msg]
                )
                return 'OK'

            # Call the add_receipt function with the extracted information
            add_receipt(receipt_data=tw_receipt,
                        items=tw_items)

            # Get receipt flex message data from the receipt data and items
            reply_msg = get_receipt_flex_msg(receipt, items)
            chinese_reply_msg = get_receipt_flex_msg(
                tw_receipt, tw_items)

            await line_bot_api.reply_message(
                event.reply_token,
                [reply_msg, chinese_reply_msg])
            return 'OK'
        else:
            continue

    return 'OK'


def generate_gemini_text_complete(prompt):
    """
    Generate a text completion using the generative model.
    """
    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content(prompt)
    return response


def generate_json_from_receipt_image(img, prompt):
    """
    Generate a JSON representation of the receipt data from the image using the generative model.

    :param img: image of the receipt.
    :param prompt: prompt for the generative model.
    :return: the generated JSON representation of the receipt data.
    """
    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content([prompt, img], stream=True)
    response.resolve()
    return response


def add_receipt(receipt_data, items):
    """
    Adds a new receipt and its associated items to the Firebase database using the firebase package.

    :param receipt_data: A dictionary containing the receipt details.
    :param items: A list of dictionaries, each containing the item details.
    """
    try:
        # Add the receipt to the 'Receipts' collection
        receipt_id = receipt_data.get('ReceiptID')
        fdb.put(user_receipt_path, receipt_id, receipt_data)

        # Add each item to the 'Items' collection
        for item in items:
            item_id = item.get('ItemID')
            fdb.put(user_item_path, item_id, item)

        print(f"Add ReceiptID: {receipt_id} completed.")
    except Exception as e:
        print(f"Error in add_receipt: {e}")


def parse_receipt_json(receipt_json_str):
    """
    Parses a JSON string representing a receipt and returns a Python dictionary.
    Removes the first and last lines of the input string before parsing.

    :param receipt_json_str: A JSON string representing the receipt.
    :return: A Python dictionary representing the receipt.
    """
    try:
        # Split the string into lines
        lines = receipt_json_str.strip().split('\n')
        # Remove the first and last lines
        json_str = '\n'.join(lines[1:-1])
        # Convert JSON string to Python dictionary
        receipt_data = json.loads(json_str)
        return receipt_data
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}")
        return None


def extract_receipt_data(receipt_json_obj):
    receipt_obj = None
    items = []

    if receipt_json_obj:
        receipt_obj = receipt_json_obj.get('Receipt')

        if receipt_obj:
            if isinstance(receipt_obj, list):
                receipt_obj = receipt_obj[0]

            print(f"ReceiptID: {receipt_obj.get('ReceiptID')}")
            print(f"PurchaseDate: {receipt_obj.get('PurchaseDate')}")
            print(f"TotalAmount: {receipt_obj.get('TotalAmount')}")
            print(f"PurchaseStore: {receipt_obj.get('PurchaseStore')}")

        items = receipt_json_obj.get('Items', [])

    return items, receipt_obj


def check_if_receipt_exists(receipt_id):
    """
    Check if a receipt with the given receipt ID exists in the database.

    :param receipt_id: The ID of the receipt to check.
    :return: True if the receipt exists, False otherwise.
    """
    try:
        receipt = fdb.get(user_receipt_path, receipt_id)
        return receipt is not None
    except Exception as e:
        print(f"Error in check_if_receipt_exists: {e}")
        return False


def get_receipt_flex_msg(receipt_data, items):
    ''''
    Generate a Flex Message for the receipt data and items.
    '''
    # Using Templat
    items_contents = []
    for item in items:
        items_contents.append(
            {
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    {
                        "type": "text",
                        "text": f"{item.get('ItemName')}",
                        "size": "sm",
                        "color": "#555555",
                        "flex": 0
                    },
                    {
                        "type": "text",
                        "text": f"${item.get('ItemPrice')}",
                        "size": "sm",
                        "color": "#111111",
                        "align": "end"
                    }
                ]
            }
        )

    print("items_contents:", items_contents)
    flex_msg = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "RECEIPT",
                    "weight": "bold",
                    "color": "#1DB446",
                    "size": "sm"
                },
                {
                    "type": "text",
                    "text": f"{receipt_data.get('PurchaseStore')}",
                    "weight": "bold",
                    "size": "xxl",
                    "margin": "md"
                },
                {
                    "type": "text",
                    "text": f"{receipt_data.get('PurchaseAddress')}",
                    "size": "xs",
                    "color": "#aaaaaa",
                    "wrap": True
                },
                {
                    "type": "separator",
                    "margin": "xxl"
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "margin": "xxl",
                    "spacing": "sm",
                    "contents": items_contents
                },
                {
                    "type": "separator",
                    "margin": "xxl"
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "margin": "md",
                    "contents": [
                        {
                            "type": "text",
                            "text": "RECEIPT ID",
                            "size": "xs",
                            "color": "#aaaaaa",
                            "flex": 0
                        },
                        {
                            "type": "text",
                            "text": f"{receipt_data.get('ReceiptID')}",
                            "color": "#aaaaaa",
                            "size": "xs",
                            "align": "end"
                        }
                    ]
                }
            ]
        },
        "styles": {
            "footer": {
                "separator": True
            }
        }
    }

    print("flex:", flex_msg)
    return FlexSendMessage(
        alt_text="Receipt Data", contents=flex_msg)
