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
    MessageEvent, TextMessage, TextSendMessage,
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
 Receipts(ReceiptID, PurchaseDate, TotalAmount) and 
 Items(ItemID, ReceiptID, ItemName, ItemPrice). 

if there is no ReceiptID, using PurchaseDate as unique ReceiptID. 
If there is no ItemID, using sequel number in that receipt.
Otherwise, if any information is unclear, fill in with 'N/A'. 
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

        if (event.message.type == "text"):
            user_id = event.source.user_id
            # msg_type = event.source.type
            user_chat_path = f'chat/{user_id}'
            chat_state_path = f'state/{user_id}'
            chatgpt = fdb.get(user_chat_path, None)
            tk = event.reply_token

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

            # 處理圖片並生成博客文章
            result = generate_json_from_receipt_image(
                img, imgage_prompt)

            # Convert the JSON string to a Python object using parse_receipt_json
            receipt_json_obj = parse_receipt_json(result.text)
            print(f"Receipt data: >{receipt_json_data}<")

            # Check if receipt_data is not None
            if receipt_json_obj:
                # Extract the necessary information from receipt_data
                print(f"----Extract Receipt data----")
                receipt_obj = receipt_json_obj.get('Receipt')
                print(f"Receipt: {receipt_obj}")
                if receipt_obj:
                    receipt_id = receipt_obj.get('ReceiptID')
                    purchase_date = receipt_obj.get('PurchaseDate')
                    print(f"Purchase Date: {purchase_date}")
                    total_amount = receipt_obj.get('TotalAmount')
                    print(f"Total Amount: {total_amount}")

                items = receipt_json_obj.get('Items', [])
                # Prepare the items list with the required keys
                items_list = []
                for item in items:
                    item_dict = {
                        'ItemID': item.get('ItemID'),
                        'ItemName': item.get('ItemName'),
                        'ItemPrice': item.get('ItemPrice')
                    }
                    items_list.append(item_dict)

                print(f"Receipt ID: {receipt_id}")
                print(f"Purchase Date: {purchase_date}")
                print(f"Total Amount: {total_amount}")

                # Call the add_receipt function with the extracted information
                add_receipt(
                    receipt_id=receipt_id,
                    purchase_date=purchase_date,
                    total_amount=total_amount,
                    items=items_list)
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
            '/Receipts', None, params={'orderBy': '"PurchaseDate"', 'equalTo': f'"{date}"'})
        items_and_total = {'items': [], 'total': 0}
        if receipts:
            for receipt_id, receipt in receipts.items():
                items = fdb.get(
                    f'/Items', None, params={'orderBy': '"ReceiptID"', 'equalTo': receipt_id})
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
            '/Items', None, params={'orderBy': '"ItemName"', 'equalTo': f'"{item_name}"'})
        purchase_details = []
        if items:
            for item_id, item in items.items():
                receipt = fdb.get(f'/Receipts/{item["ReceiptID"]}', None)
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
    # 創建生成模型的實例
    model = genai.GenerativeModel('gemini-pro-vision')
    # 調用模型生成內容
    response = model.generate_content([prompt, img], stream=True)
    # 等待生成完成
    response.resolve()
    # 返回生成的結果
    return response


def add_receipt(receipt_id, purchase_date, total_amount, items):
    """
    Adds a new receipt and its associated items to the Firebase database using the firebase package.

    :param receipt_id: The unique identifier for the receipt.
    :param purchase_date: The date of the purchase.
    :param total_amount: The total amount of the purchase.
    :param items: A list of dictionaries, each containing the item details.
    """
    try:
        # Add the receipt to the 'Receipts' collection
        receipt_data = {
            'ReceiptID': receipt_id,
            'PurchaseDate': purchase_date,
            'TotalAmount': total_amount
        }
        fdb.put('/Receipts', receipt_id, receipt_data)

        # Add each item to the 'Items' collection
        for item in items:
            item_id = item.get('ItemID')
            item_data = {
                'ItemID': item_id,
                'ReceiptID': receipt_id,
                'ItemName': item.get('ItemName'),
                'ItemPrice': item.get('ItemPrice')
            }
            fdb.put('/Items', item_id, item_data)

        print(f"ReceiptID: {receipt_id}")
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
