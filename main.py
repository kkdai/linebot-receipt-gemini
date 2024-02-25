# -*- coding: utf-8 -*-

#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#       https://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.

from linebot.models import (
    MessageEvent, TextSendMessage, FlexSendMessage
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
from flex import get_receipt_flex_msg

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

 Receipt(ReceiptID, PurchaseStore, PurchaseChineseStore, PurchaseDate, PurchaseAddress, PurchaseChineseAddress, TotalAmount) and 
 Items(ItemID, ReceiptID, ItemName, ItemChineseName, ItemPrice). 

Data format as follow:
- ReceiptID, using PurchaseDate, but Represent the year, month, day, hour, and minute without any separators.
- ItemID, using ReceiptID and sequel number in that receipt. 
Otherwise, if any information is unclear, fill in with 'N/A'. 
All json data need to translate into zh-tw and put in PurchaseChineseStore, PurchaseChineseAddress, ItemChineseName columns.
'''

if channel_secret is None:
    print('Specify LINE_CHANNEL_SECRET as environment variable.')
    sys.exit(1)
if channel_access_token is None:
    print('Specify LINE_CHANNEL_ACCESS_TOKEN as environment variable.')
    sys.exit(1)

# Initialize the FastAPI app for LINEBot
app = FastAPI()
session = aiohttp.ClientSession()
async_http_client = AiohttpAsyncHttpClient(session)
line_bot_api = AsyncLineBotApi(channel_access_token, async_http_client)
parser = WebhookParser(channel_secret)
user_receipt_path = f''
user_item_path = f''

# Initialize the Firebase Database
fdb = firebase.FirebaseApplication(firebase_url, None)
# Initialize the Gemini Pro API
genai.configure(api_key=gemini_key)


@app.post("/callback")
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

        if (event.message.type == "text"):
            user_chat_path = f'chat/{user_id}'
            chatgpt = fdb.get(user_chat_path, None)

            if chatgpt is None:
                messages = []
            else:
                messages = chatgpt

            # Provide a default value for reply_msg
            reply_msg = TextSendMessage(text='No message to reply with')

            msg = event.message.text
            if msg == '!清空':
                reply_msg = TextSendMessage(text='對話歷史紀錄已經清空！')
                fdb.delete(user_chat_path, None)
            elif msg == '!flex':
                # 使用範例
                flex_msg = {
                    "type": "bubble",
                    "body": {
                        "type": "box",
                        "layout": "vertical",
                        "contents": [
                            {
                                "type": "text",
                                "text": "Hello, World!"
                            }
                        ]
                    }
                }
                reply_msg = FlexSendMessage(
                    alt_text="Hello, World!", contents=flex_msg)

            elif msg == '!qq':
                # 使用範例
                items_and_total_on_date = find_items_and_total_on_date(
                    '2023-12-25')
                print(f"Items and total on 12/25: {items_and_total_on_date}")
                reply_msg = TextSendMessage(
                    text=f"Items and total on 12/25: {items_and_total_on_date}")
            else:
                messages.append({"role": "user", "parts": msg})
                model = genai.GenerativeModel('gemini-pro')
                response = model.generate_content(messages)
                messages.append({"role": "model", "parts": response.text})
                reply_msg = TextSendMessage(text=response.text)
                fdb.put_async(user_chat_path, None, messages)

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

            # 處理圖片並取得回傳結果
            result = generate_json_from_receipt_image(
                img, imgage_prompt)

            # Convert the JSON string to a Python object using parse_receipt_json
            receipt_json_obj = parse_receipt_json(result.text)
            print(f"Receipt data: >{receipt_json_obj}<")

            # Check if receipt_data is not None
            if receipt_json_obj:
                # Extract the necessary information from receipt_data
                print(f"----Extract Receipt data----")
                receipt_obj = receipt_json_obj.get('Receipt')
                print(f"Receipt: {receipt_obj}")
                if receipt_obj:
                    if isinstance(receipt_obj, list):
                        print("receipt_obj is a list.")
                        receipt_obj = receipt_obj[0]
                    else:
                        print("receipt_obj is not a list.")

                    receipt_id = receipt_obj.get('ReceiptID')
                    print(f"Receipt ID: {receipt_id}")
                    purchase_date = receipt_obj.get('PurchaseDate')
                    print(f"Purchase Date: {purchase_date}")
                    total_amount = receipt_obj.get('TotalAmount')
                    print(f"Total Amount: {total_amount}")

                items = receipt_json_obj.get('Items', [])
                print(f"Items: {items}")

                # Call the add_receipt function with the extracted information
                add_receipt(receipt_data=receipt_obj,
                            items=items)
                reply_msg = get_receipt_flex_msg(receipt_obj, items)

                await line_bot_api.reply_message(
                    event.reply_token,
                    reply_msg)
                return 'OK'

            else:
                print("Failed to parse the receipt JSON.")

            # 創建回復消息
            reply_msg = TextSendMessage(text=result.text)

            # 使用 LINE Bot API 回復消息
            await line_bot_api.reply_message(
                event.reply_token,
                reply_msg
            )
        else:
            continue

    return 'OK'


def find_items_and_total_on_date(date):
    """
    查找特定日期購買的所有物品和總金額。
    """
    try:
        receipts = fdb.get(
            user_receipt_path, None, params={'orderBy': '"PurchaseDate"', 'equalTo': f'"{date}"'})
        items_and_total = {'items': [], 'total': 0}
        if receipts:
            for receipt_id, receipt in receipts.items():
                items = fdb.get(
                    user_item_path, None, params={'orderBy': '4$ID"', 'equalTo': receipt_id})
                if items:
                    for item_id, item in items.items():
                        items_and_total['items'].append(item)
                        items_and_total['total'] += item['ItemPrice']
        return items_and_total
    except Exception as e:
        print(f"Error in find_items_and_total_on_date: {e}")
        return None


def find_purchase_details_of_item(item_name):
    """
    查找購買特定物品的日期和花費的金額。
    """
    try:
        items = fdb.get(
            user_item_path, None, params={'orderBy': '"ItemName"', 'equalTo': f'"{item_name}"'})
        purchase_details = []
        if items:
            for item_id, item in items.items():
                receipt = fdb.get(
                    f'{user_item_path}/{item["ReceiptID"]}', None)
                if receipt:
                    purchase_details.append({
                        'date': receipt['PurchaseDate'],
                        'price': item['ItemPrice']
                    })
        return purchase_details
    except Exception as e:
        print(f"Error in find_purchase_details_of_item: {e}")
        return None


def generate_json_from_receipt_image(img, prompt):
    """
    Generate a JSON representation of the receipt data from the image using the generative model.

    :param img: image of the receipt.
    :param prompt: prompt for the generative model.
    :return: the generated JSON representation of the receipt data.
    """
    model = genai.GenerativeModel('gemini-pro-vision')
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
