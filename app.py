import random
from string import ascii_letters
from flask import Flask, request, render_template, redirect, url_for, session, jsonify, send_file
from flask_socketio import SocketIO, join_room, leave_room, send, emit
from pymongo import MongoClient
from gridfs import GridFS
from bson.objectid import ObjectId
from datetime import datetime
import os
from dotenv import load_dotenv
from io import BytesIO
from werkzeug.utils import secure_filename
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY")
if not app.config["SECRET_KEY"]:
    logger.error("FLASK_SECRET_KEY is not set")
    raise ValueError("FLASK_SECRET_KEY is not set")

socketio = SocketIO(app, cors_allowed_origins="*", engineio_logger=True)

# MongoDB setup with automatic collection creation
try:
    mongo_uri = os.getenv("MONGO_URI")
    if not mongo_uri:
        logger.error("MONGO_URI is not set")
        raise ValueError("MONGO_URI is not set")
    mongo_client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    mongo_client.server_info()  # Test connection
    db = mongo_client.skygenesis
    users_collection = db.users
    room_messages_collection = db.room_messages
    private_messages_collection = db.private_messages
    notifications_collection = db.notifications
    rooms_collection = db.rooms
    fs = GridFS(db)
    collections_to_create = ["users", "rooms", "room_messages", "private_messages", "notifications"]
    for collection in collections_to_create:
        if collection not in db.list_collection_names():
            db.create_collection(collection)
            logger.info(f"Created collection: {collection}")
    logger.info("Successfully connected to MongoDB")
except Exception as e:
    logger.error(f"Failed to connect to MongoDB: {str(e)}")
    raise

def generate_room_code(length: int) -> str:
    """Generate a unique room code of specified length."""
    try:
        logger.info(f"Generating room code with length {length}")
        existing_codes = [r["code"] for r in rooms_collection.find()]
        while True:
            code_chars = [random.choice(ascii_letters) for _ in range(length)]
            code = ''.join(code_chars)
            if code not in existing_codes:
                logger.info(f"Generated unique room code: {code}")
                return code
    except Exception as e:
        logger.error(f"Error generating room code: {str(e)}")
        raise

# Rest of the routes and SocketIO handlers remain the same as in your original code
# (Omitted here for brevity but should be included as provided above)

if __name__ == "__main__":
    port = int(os.getenv('PORT', 5000))
    logger.info(f"Starting Flask app on port {port}")
    socketio.run(app, debug=True, host='0.0.0.0', port=port)