# GitHub Issues Chatbot for LINE

This repository contains the code for a chatbot that integrates GitHub Issues with LINE messaging platform. The bot is designed to retrieve information from GitHub Issues and provide responses to user queries on LINE.

## Features

- Load GitHub Issues from a specified repository.
- Use environmental variables for configuration.
- Integrate with LINE messaging platform using the LINE Bot API.
- Split and process text data using Langchain.
- Retrieve and rank relevant documents using vector embeddings and FAISS.
- Provide responses to LINE messages with information from GitHub Issues.

## Requirements

- Python 3.6 or higher
- aiohttp
- fastapi
- line-bot-sdk
- python-dotenv
- langchain
- langchain_openai
- langchain_core
- langchain_community

## Installation

Before running the chatbot, you need to install the required dependencies:

```bash
pip install aiohttp fastapi line-bot-sdk python-dotenv langchain langchain_openai langchain_core langchain_community
```

## Configuration

Set the following environment variables:

- `GITHUB_TOKEN`: Your GitHub access token.
- `ChannelSecret`: Your LINE channel secret.
- `ChannelAccessToken`: Your LINE channel access token.
- `OPENAI_API_KEY`: Your OpenAI API key.

You can set these variables in a `.env` file or export them directly into your environment.

## Deploy this on Web Platform

You can choose [Heroku](https://www.heroku.com/) or [Render](http://render.com/)

### Deploy this on Heroku

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy)

### Deploy this on Render.com

[![Deploy to Render](http://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

## Usage

To start the chatbot, run the FastAPI server:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

The server will start and listen for incoming webhook events from LINE.

## Webhook Endpoint

The webhook endpoint `/callback` is used by LINE to send events to the chatbot. The chatbot processes these events, retrieves information from GitHub Issues, and sends responses back to the user on LINE.

## License

This project is licensed under the Apache License, Version 2.0. See the [LICENSE](https://www.apache.org/licenses/LICENSE-2.0) for more information.

## Disclaimer

This project is not officially associated with LINE Corporation or GitHub, Inc.

## Contributions

Contributions are welcome! Please feel free to submit a pull request or open an issue if you have any improvements or find any bugs.

## Contact

For any queries or support, please open an issue in this repository.

---

Please note that this README is a template and should be customized to fit the specifics of your project and environment.

```

This README provides a basic template for setting up and running the GitHub Issues Chatbot for LINE. It includes sections for features, requirements, installation, configuration, usage, the webhook endpoint, license, disclaimer, contributions, and contact information. Adjust the content as necessary to match the actual functionality and setup of your project.
