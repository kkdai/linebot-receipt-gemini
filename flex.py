from linebot.models import FlexSendMessage


# Get receipt flex message data from the receipt data and items
def get_receipt_flex_msg(receipt_data, items):
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
                            "text": "#743289384279",
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
