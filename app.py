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

@app.route('/', methods=["GET", "POST"])
def home():
    """Handle login and room creation/joining."""
    session.clear()
    if request.method == "POST":
        try:
            username = request.form.get('username')
            code_length = int(request.form.get('code_length', 6))
            create = request.form.get('create', False)
            code = request.form.get('code')
            join = request.form.get('join', False)
            
            if not username:
                logger.warning("Username missing in POST request")
                return render_template('home.html', error="Nama diperlukan", code=code)
            
            logger.info(f"Processing request for user: {username}")
            user = users_collection.find_one({"username": username})
            if not user:
                logger.info(f"Creating new user: {username}")
                users_collection.insert_one({
                    "username": username,
                    "online": True,
                    "rooms": [],
                    "friends": [],
                    "avatar": None,
                    "last_seen": datetime.utcnow(),
                    "status": "Hey, I'm using SkyGenesis!"
                })
            else:
                logger.info(f"Updating existing user: {username}")
                users_collection.update_one(
                    {"username": username},
                    {"$set": {"online": True, "last_seen": datetime.utcnow()}}
                )
            
            if create != False:
                logger.info(f"Creating new room for user: {username}")
                room_code = generate_room_code(code_length)
                rooms_collection.insert_one({
                    "code": room_code,
                    "creator": username,
                    "created_at": datetime.utcnow(),
                    "members": [username]
                })
                users_collection.update_one(
                    {"username": username},
                    {"$addToSet": {"rooms": room_code}}
                )
                notifications_collection.insert_one({
                    "username": username,
                    "message": f"Kamu membuat room {room_code}",
                    "timestamp": datetime.utcnow(),
                    "read": False
                })
                emit('notification', {"message": f"Kamu membuat room {room_code}"}, to=username)
                logger.info(f"Room created: {room_code} by {username}")
            elif join != False:
                if not code:
                    logger.warning("Room code missing in join request")
                    return render_template('home.html', error="Masukkan code room", username=username)
                room = rooms_collection.find_one({"code": code})
                if not room:
                    logger.warning(f"Invalid room code: {code}")
                    return render_template('home.html', error="Code room salah", username=username)
                room_code = code
                rooms_collection.update_one(
                    {"code": room_code},
                    {"$addToSet": {"members": username}}
                )
                users_collection.update_one(
                    {"username": username},
                    {"$addToSet": {"rooms": room_code}}
                )
                notifications_collection.insert_one({
                    "username": username,
                    "message": f"Kamu bergabung ke room {room_code}",
                    "timestamp": datetime.utcnow(),
                    "read": False
                })
                emit('notification', {"message": f"Kamu bergabung ke room {room_code}"}, to=username)
                logger.info(f"User {username} joined room: {room_code}")
            else:
                logger.warning("Neither create nor join action specified")
                return render_template('home.html', error="Aksi tidak valid", username=username)
            
            session['room'] = room_code
            session['username'] = username
            logger.info(f"Redirecting {username} to dashboard")
            return redirect(url_for('dashboard'))
        except Exception as e:
            logger.error(f"Error in home route: {str(e)}")
            return render_template('home.html', error=f"Terjadi kesalahan server: {str(e)}", username=username), 500
    return render_template('home.html')

# Include the rest of the routes and SocketIO handlers from the previous app.py
# (Omitted here for brevity, but ensure they are included as provided)

if __name__ == "__main__":
    port = int(os.getenv('PORT', 5000))
    logger.info(f"Starting Flask app on port {port}")
    socketio.run(app, debug=True, host='0.0.0.0', port=port)