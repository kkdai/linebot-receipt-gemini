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

import aiohttp
from firebase import firebase

# get channel_secret and channel_access_token from your environment variable
channel_secret = os.getenv('ChannelSecret', None)
channel_access_token = os.getenv('ChannelAccessToken', None)
gemini_key = os.getenv('GEMINI_API_KEY')
firebase_url = os.getenv('FIREBASE_URL')

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
        if not isinstance(event.message, TextMessage):
            continue

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
