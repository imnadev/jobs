# Telegram Bot

A basic Telegram bot built with Python and the `python-telegram-bot` library.

## Setup

1. **Get a Bot Token**
   - Open Telegram and search for `@BotFather`
   - Send `/newbot` command
   - Follow the instructions to create your bot
   - Copy the bot token

2. **Configure Environment**
   - Open the `.env` file
   - Replace `YOUR_BOT_TOKEN_HERE` with your actual bot token

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the Bot**
   ```bash
   python bot.py
   ```

## Features

- `/start` command - Welcome message
- Message echo - Replies with the same message you send
- Error handling and logging

## Project Structure

```
.
├── bot.py              # Main bot logic
├── requirements.txt    # Python dependencies
├── .env               # Environment variables (token)
├── .gitignore         # Git ignore file
└── README.md          # This file
```

## Commands

- `/start` - Start the bot and get welcome message

## Development

The bot is built using:
- `python-telegram-bot` - Telegram Bot API wrapper
- `python-dotenv` - Environment variable management
