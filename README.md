# SkyGenesis Chat

A real-time chat application built with Python, Flask, Flask-SocketIO, and MongoDB. Supports group chats, private chats, user profiles with avatars, persistent notifications, typing indicators, message reactions, and last seen status.

## Features
- Simple login with username (no password).
- Create/join rooms with variable-length codes (6 or 8 characters).
- Real-time group and private chats.
- Upload avatars (stored in MongoDB GridFS).
- Persistent notifications stored in MongoDB.
- Typing indicators for group/private chats.
- Message reactions (😊, 👍).
- Last seen status for users.
- User search and pagination for chat history.

## Prerequisites
- Python 3.8+
- MongoDB Atlas account
- Railway account (for deployment)

## Setup
1. Clone the repository:
   ```bash
   git clone https://github.com/<your-username>/SkyGenesis.git
   cd SkyGenesis