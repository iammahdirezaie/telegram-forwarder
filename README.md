# Telegram Restricted Media Fetcher

A lightweight, robust Telegram userbot built with Pyrogram to extract media from restricted/private channels and post it into designated target channels without worker deadlocks.

## Features
- **Bypass Media Restrictions**: Fetches videos, audios, photos, and albums from restricted channels.
- **Link Detection**: Supports standard public links, private channel links, and forum topic link formats.
- **Dual Channel Delivery**: Delivers to the primary monitored channel and optionally mirrors/forwards to a secondary backup channel.
- **Zero Deadlocks**: Single-worker architecture tailored for shared hostings (cPanel) and VPS environments.
- **Live Progress Updates**: Reports real-time download and upload progress.

## Installation

1. Clone this repository:
   ```bash
   git clone [https://github.com/your-username/telegram-restricted-fetcher.git](https://github.com/your-username/telegram-restricted-fetcher.git)
   cd telegram-restricted-fetcher