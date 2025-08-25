#### `app.py`
```python
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

socketio = SocketIO(app, cors_allowed_origins="*")

# MongoDB setup with automatic collection creation
try:
    mongo_client = MongoClient(os.getenv("MONGO_URI"), serverSelectionTimeoutMS=5000)
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

@app.route('/dashboard')
def dashboard():
    """Render user dashboard with profile, notifications, friends, and rooms."""
    username = session.get('username')
    if not username:
        logger.warning("No username in session for dashboard")
        return redirect(url_for('home'))
    try:
        user = users_collection.find_one({"username": username})
        if not user:
            logger.error(f"User {username} not found in database")
            return redirect(url_for('home'))
        users_collection.update_one(
            {"username": username},
            {"$set": {"online": True, "last_seen": datetime.utcnow()}}
        )
        online_users = list(users_collection.find({"online": True}))
        notifications = list(notifications_collection.find({"username": username}).sort("timestamp", -1).limit(10))
        friends = list(users_collection.find({"username": {"$in": user.get("friends", [])}}))
        logger.info(f"Rendering dashboard for {username}")
        return render_template(
            'dashboard.html',
            username=username,
            user=user,
            online_users=online_users,
            notifications=notifications,
            friends=friends
        )
    except Exception as e:
        logger.error(f"Error in dashboard route: {str(e)}")
        return render_template('home.html', error=f"Terjadi kesalahan server: {str(e)}"), 500

@app.route('/refresh_users')
def refresh_users():
    """Refresh user list and notifications."""
    username = session.get('username')
    if not username:
        logger.warning("No username in session for refresh_users")
        return redirect(url_for('home'))
    try:
        user = users_collection.find_one({"username": username})
        if not user:
            logger.error(f"User {username} not found in database")
            return redirect(url_for('home'))
        users_collection.update_one(
            {"username": username},
            {"$set": {"online": True, "last_seen": datetime.utcnow()}}
        )
        online_users = list(users_collection.find({"online": True}))
        notifications = list(notifications_collection.find({"username": username}).sort("timestamp", -1).limit(10))
        friends = list(users_collection.find({"username": {"$in": user.get("friends", [])}}))
        logger.info(f"Refreshing users for {username}")
        return render_template(
            'dashboard.html',
            username=username,
            user=user,
            online_users=online_users,
            notifications=notifications,
            friends=friends
        )
    except Exception as e:
        logger.error(f"Error in refresh_users route: {str(e)}")
        return render_template('home.html', error=f"Terjadi kesalahan server: {str(e)}"), 500

@app.route('/search_users', methods=["POST"])
def search_users():
    """Search users by username with autocomplete."""
    try:
        query = request.form.get('query', '')
        logger.info(f"Searching users with query: {query}")
        users = list(users_collection.find(
            {"username": {"$regex": query, "$options": "i"}},
            {"username": 1, "avatar": 1, "last_seen": 1, "status": 1}
        ).limit(10))
        logger.info(f"Found {len(users)} users for query: {query}")
        return jsonify([{
            "username": u["username"],
            "avatar": f"/avatar/{u['username']}" if u.get("avatar") else "https://via.placeholder.com/40",
            "last_seen": u["last_seen"].strftime("%Y-%m-%d %H:%M:%S"),
            "status": u.get("status", "No status")
        } for u in users])
    except Exception as e:
        logger.error(f"Error in search_users: {str(e)}")
        return jsonify({"error": "Search failed"}), 500

@app.route('/add_friend/<friend_username>', methods=["POST"])
def add_friend(friend_username):
    """Add a friend directly to the user's friend list."""
    username = session.get('username')
    if not username:
        logger.warning("No username in session for add_friend")
        return jsonify({"error": "Unauthorized"}), 401
    try:
        if username == friend_username:
            logger.warning("Cannot add self as friend")
            return jsonify({"error": "Tidak bisa menambah diri sendiri"}), 400
        if not users_collection.find_one({"username": friend_username}):
            logger.warning(f"User {friend_username} not found")
            return jsonify({"error": "Pengguna tidak ditemukan"}), 404
        users_collection.update_one(
            {"username": username},
            {"$addToSet": {"friends": friend_username}}
        )
        users_collection.update_one(
            {"username": friend_username},
            {"$addToSet": {"friends": username}}
        )
        notifications_collection.insert_one({
            "username": friend_username,
            "message": f"{username} menambahkan kamu sebagai teman",
            "timestamp": datetime.utcnow(),
            "read": False
        })
        emit('notification', {"message": f"{username} menambahkan kamu sebagai teman"}, to=friend_username)
        logger.info(f"Friend added: {friend_username} by {username}")
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error in add_friend: {str(e)}")
        return jsonify({"error": "Gagal menambah teman"}), 500

@app.route('/avatar/<username>')
def get_avatar(username):
    """Serve user avatar from GridFS."""
    try:
        logger.info(f"Fetching avatar for {username}")
        user = users_collection.find_one({"username": username})
        if user and user.get("avatar"):
            file = fs.get(user["avatar"])
            return send_file(BytesIO(file.read()), mimetype=file.content_type)
        logger.info(f"No avatar found for {username}, using default")
        return redirect("https://via.placeholder.com/40")
    except Exception as e:
        logger.error(f"Error fetching avatar for {username}: {str(e)}")
        return redirect("https://via.placeholder.com/40")

@app.route('/upload_avatar', methods=["POST"])
def upload_avatar():
    """Upload user avatar to GridFS."""
    username = session.get('username')
    if not username:
        logger.warning("No username in session for avatar upload")
        return redirect(url_for('home'))
    try:
        if 'avatar' in request.files:
            avatar = request.files['avatar']
            if avatar.filename != '':
                filename = secure_filename(avatar.filename)
                content_type = avatar.content_type
                avatar_id = fs.put(avatar, filename=filename, content_type=content_type)
                users_collection.update_one(
                    {"username": username},
                    {"$set": {"avatar": avatar_id}}
                )
                notifications_collection.insert_one({
                    "username": username,
                    "message": "Avatar berhasil diupload",
                    "timestamp": datetime.utcnow(),
                    "read": False
                })
                emit('notification', {"message": "Avatar berhasil diupload"}, to=username)
                logger.info(f"Avatar uploaded for {username}")
        return redirect(url_for('dashboard'))
    except Exception as e:
        logger.error(f"Error uploading avatar: {str(e)}")
        return redirect(url_for('dashboard'))

@app.route('/update_status', methods=["POST"])
def update_status():
    """Update user status message."""
    username = session.get('username')
    if not username:
        logger.warning("No username in session for update_status")
        return jsonify({"error": "Unauthorized"}), 401
    try:
        status = request.form.get('status')
        if not status:
            return jsonify({"error": "Status required"}), 400
        users_collection.update_one(
            {"username": username},
            {"$set": {"status": status}}
        )
        notifications_collection.insert_one({
            "username": username,
            "message": "Status berhasil diperbarui",
            "timestamp": datetime.utcnow(),
            "read": False
        })
        emit('notification', {"message": "Status berhasil diperbarui"}, to=username)
        logger.info(f"Status updated for {username}")
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error updating status: {str(e)}")
        return jsonify({"error": "Failed to update status"}), 500

@app.route('/room/<room_code>')
def room(room_code):
    """Render group chat room."""
    username = session.get('username')
    if not username:
        logger.warning("No username in session for room access")
        return redirect(url_for('home'))
    try:
        room = rooms_collection.find_one({"code": room_code})
        if not room:
            logger.warning(f"Invalid room code: {room_code}")
            return redirect(url_for('dashboard'))
        session['room'] = room_code
        messages = room_messages_collection.find({"room": room_code}).sort("timestamp", -1).limit(50)
        logger.info(f"Rendering room {room_code} for {username}")
        return render_template('room.html', room=room_code, username=username, messages=messages)
    except Exception as e:
        logger.error(f"Error in room route: {str(e)}")
        return render_template('dashboard.html', error=f"Terjadi kesalahan server: {str(e)}"), 500

@app.route('/room/<room_code>/more/<int:page>')
def room_more(room_code, page):
    """Load more messages for group chat."""
    username = session.get('username')
    if not username:
        logger.warning("No username in session for room more")
        return jsonify([])
    try:
        room = rooms_collection.find_one({"code": room_code})
        if not room:
            logger.warning(f"Invalid room code: {room_code}")
            return jsonify([])
        skip = page * 50
        messages = room_messages_collection.find({"room": room_code}).sort("timestamp", -1).skip(skip).limit(50)
        logger.info(f"Loading more messages for room {room_code}, page {page}")
        return jsonify([{
            "sender": m["sender"],
            "message": m["message"],
            "_id": str(m["_id"]),
            "reactions": m.get("reactions", {}),
            "read_by": m.get("read_by", [])
        } for m in messages])
    except Exception as e:
        logger.error(f"Error loading more messages: {str(e)}")
        return jsonify([]), 500

@app.route('/private/<receiver>')
def private_chat(receiver):
    """Render private chat."""
    username = session.get('username')
    if not username or not users_collection.find_one({"username": receiver}):
        logger.warning(f"Invalid private chat access: {receiver} by {username}")
        return redirect(url_for('dashboard'))
    try:
        session['private_receiver'] = receiver
        messages = private_messages_collection.find({
            "$or": [
                {"sender": username, "receiver": receiver},
                {"sender": receiver, "receiver": username}
            ]
        }).sort("timestamp", -1).limit(50)
        logger.info(f"Rendering private chat with {receiver} for {username}")
        return render_template('private.html', username=username, receiver=receiver, messages=messages)
    except Exception as e:
        logger.error(f"Error in private_chat route: {str(e)}")
        return render_template('dashboard.html', error=f"Terjadi kesalahan server: {str(e)}"), 500

@app.route('/private/<receiver>/more/<int:page>')
def private_more(receiver, page):
    """Load more private messages."""
    username = session.get('username')
    if not username:
        logger.warning("No username in session for private more")
        return jsonify([])
    try:
        skip = page * 50
        messages = private_messages_collection.find({
            "$or": [
                {"sender": username, "receiver": receiver},
                {"sender": receiver, "receiver": username}
            ]
        }).sort("timestamp", -1).skip(skip).limit(50)
        logger.info(f"Loading more private messages for {username} and {receiver}, page {page}")
        return jsonify([{
            "sender": m["sender"],
            "message": m["message"],
            "_id": str(m["_id"]),
            "reactions": m.get("reactions", {}),
            "read_by": m.get("read_by", [])
        } for m in messages])
    except Exception as e:
        logger.error(f"Error loading more private messages: {str(e)}")
        return jsonify([]), 500

@app.route('/react/<message_type>/<message_id>', methods=["POST"])
def react(message_type, message_id):
    """Add reaction to a message."""
    username = session.get('username')
    if not username:
        logger.warning("No username in session for reaction")
        return jsonify({"error": "Unauthorized"}), 401
    try:
        emoji = request.form.get('emoji')
        if not emoji:
            logger.warning("No emoji provided for reaction")
            return jsonify({"error": "Emoji required"}), 400
        collection = room_messages_collection if message_type == "room" else private_messages_collection
        collection.update_one(
            {"_id": ObjectId(message_id)},
            {"$addToSet": {f"reactions.{emoji}": username}},
            upsert=True
        )
        emit('reaction', {"message_id": message_id, "emoji": emoji, "username": username}, broadcast=True)
        logger.info(f"Reaction added: {emoji} to {message_id} by {username}")
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error adding reaction: {str(e)}")
        return jsonify({"error": "Reaction failed"}), 500

@app.route('/delete_message/<message_type>/<message_id>', methods=["POST"])
def delete_message(message_type, message_id):
    """Delete a message (only by sender)."""
    username = session.get('username')
    if not username:
        logger.warning("No username in session for delete_message")
        return jsonify({"error": "Unauthorized"}), 401
    try:
        collection = room_messages_collection if message_type == "room" else private_messages_collection
        message = collection.find_one({"_id": ObjectId(message_id), "sender": username})
        if not message:
            logger.warning(f"Message {message_id} not found or not owned by {username}")
            return jsonify({"error": "Message not found or unauthorized"}), 403
        collection.delete_one({"_id": ObjectId(message_id)})
        emit('message_deleted', {"message_id": message_id, "message_type": message_type}, broadcast=True)
        logger.info(f"Message {message_id} deleted by {username}")
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error deleting message: {str(e)}")
        return jsonify({"error": "Failed to delete message"}), 500

@app.route('/check_status')
def check_status():
    """Check user online status."""
    username = session.get('username')
    if not username:
        logger.warning("No username in session for check_status")
        return jsonify({"error": "No user in session"}), 401
    try:
        user = users_collection.find_one({"username": username})
        return jsonify({
            "username": username,
            "online": user.get("online", False),
            "last_seen": user.get("last_seen", datetime.utcnow()).strftime("%Y-%m-%d %H:%M:%S"),
            "status": user.get("status", "No status")
        })
    except Exception as e:
        logger.error(f"Error checking status: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/init_data', methods=["GET"])
def init_data():
    """Initialize dummy data for testing."""
    try:
        if not users_collection.find_one({"username": "testuser"}):
            users_collection.insert_one({
                "username": "testuser",
                "online": False,
                "rooms": [],
                "friends": [],
                "avatar": None,
                "last_seen": datetime.utcnow(),
                "status": "Hey, I'm using SkyGenesis!"
            })
            logger.info("Created dummy user: testuser")
        if not rooms_collection.find_one({"code": "TestRoom"}):
            rooms_collection.insert_one({
                "code": "TestRoom",
                "creator": "testuser",
                "created_at": datetime.utcnow(),
                "members": ["testuser"]
            })
            users_collection.update_one(
                {"username": "testuser"},
                {"$addToSet": {"rooms": "TestRoom"}}
            )
            logger.info("Created dummy room: TestRoom")
        return jsonify({"success": True, "message": "Dummy data initialized"})
    except Exception as e:
        logger.error(f"Error initializing data: {str(e)}")
        return jsonify({"error": "Failed to initialize data"}), 500

@socketio.on('connect')
def handle_connect():
    """Handle SocketIO connection."""
    username = session.get('username')
    room = session.get('room')
    private_receiver = session.get('private_receiver')
    if not username:
        logger.warning("No username in session on connect")
        return
    try:
        users_collection.update_one(
            {"username": username},
            {"$set": {"online": True, "last_seen": datetime.utcnow()}}
        )
        emit('status_update', {"username": username, "online": True}, broadcast=True)
        logger.info(f"User {username} connected to SocketIO")
        if room:
            room_data = rooms_collection.find_one({"code": room})
            if room_data:
                join_room(room)
                send({
                    "sender": "",
                    "message": f"{username} telah masuk chat"
                }, to=room)
                notifications_collection.insert_one({
                    "username": username,
                    "message": f"Kamu bergabung di room {room}",
                    "timestamp": datetime.utcnow(),
                    "read": False
                })
                emit('notification', {"message": f"Kamu bergabung di room {room}"}, to=username)
                rooms_collection.update_one(
                    {"code": room},
                    {"$addToSet": {"members": username}}
                )
                logger.info(f"User {username} connected to room {room}")
        if private_receiver:
            private_room = f"private_{min(username, private_receiver)}_{max(username, private_receiver)}"
            join_room(private_room)
            notifications_collection.insert_one({
                "username": username,
                "message": f"Kamu memulai chat pribadi dengan {private_receiver}",
                "timestamp": datetime.utcnow(),
                "read": False
            })
            emit('notification', {"message": f"Kamu memulai chat pribadi dengan {private_receiver}"}, to=username)
            logger.info(f"User {username} connected to private chat with {private_receiver}")
    except Exception as e:
        logger.error(f"Error on connect: {str(e)}")

@socketio.on('room_message')
def handle_room_message(payload):
    """Handle group chat messages."""
    room = session.get('room')
    username = session.get('username')
    if not room or not rooms_collection.find_one({"code": room}):
        logger.warning(f"Invalid room message attempt: {room} by {username}")
        return
    try:
        message = {
            "sender": username,
            "message": payload["message"],
            "room": room,
            "timestamp": datetime.utcnow(),
            "reactions": {},
            "read_by": [username]
        }
        msg_id = room_messages_collection.insert_one(message).inserted_id
        send({"_id": str(msg_id), **message}, to=room)
        for member in rooms_collection.find_one({"code": room})["members"]:
            if member != username:
                notifications_collection.insert_one({
                    "username": member,
                    "message": f"Pesan baru di room {room} dari {username}",
                    "timestamp": datetime.utcnow(),
                    "read": False
                })
                emit('notification', {"message": f"Pesan baru di room {room} dari {username}"}, to=member)
        logger.info(f"Message sent in room {room} by {username}")
    except Exception as e:
        logger.error(f"Error sending room message: {str(e)}")

@socketio.on('private_message')
def handle_private_message(payload):
    """Handle private chat messages."""
    username = session.get('username')
    receiver = session.get('private_receiver')
    if not receiver:
        logger.warning("No receiver for private message")
        return
    try:
        private_room = f"private_{min(username, receiver)}_{max(username, receiver)}"
        message = {
            "sender": username,
            "receiver": receiver,
            "message": payload["message"],
            "timestamp": datetime.utcnow(),
            "reactions": {},
            "read_by": [username]
        }
        msg_id = private_messages_collection.insert_one(message).inserted_id
        emit('private_message', {"_id": str(msg_id), **message}, to=private_room)
        notifications_collection.insert_one({
            "username": receiver,
            "message": f"Pesan pribadi baru dari {username}",
            "timestamp": datetime.utcnow(),
            "read": False
        })
        emit('notification', {"message": f"Pesan pribadi baru dari {username}"}, to=receiver)
        logger.info(f"Private message sent from {username} to {receiver}")
    except Exception as e:
        logger.error(f"Error sending private message: {str(e)}")

@socketio.on('typing')
def handle_typing(data):
    """Handle typing indicator events."""
    username = session.get('username')
    room = session.get('room')
    private_receiver = session.get('private_receiver')
    try:
        if room and rooms_collection.find_one({"code": room}):
            emit('typing', {"username": username, "isTyping": data["isTyping"]}, to=room, include_self=False)
        if private_receiver:
            private_room = f"private_{min(username, private_receiver)}_{max(username, private_receiver)}"
            emit('typing', {"username": username, "isTyping": data["isTyping"]}, to=private_room, include_self=False)
        logger.info(f"Typing event from {username}")
    except Exception as e:
        logger.error(f"Error handling typing: {str(e)}")

@socketio.on('message_read')
def handle_message_read(data):
    """Handle message read events."""
    username = session.get('username')
    if not username:
        logger.warning("No username in session for message_read")
        return
    try:
        message_id = data['message_id']
        message_type = data['message_type']
        collection = room_messages_collection if message_type == 'room' else private_messages_collection
        collection.update_one(
            {"_id": ObjectId(message_id)},
            {"$addToSet": {"read_by": username}}
        )
        emit('message_read', {"message_id": message_id, "username": username, "message_type": message_type}, broadcast=True)
        logger.info(f"Message {message_id} read by {username}")
    except Exception as e:
        logger.error(f"Error handling message read: {str(e)}")

@socketio.on('disconnect')
def handle_disconnect():
    """Handle SocketIO disconnection."""
    username = session.get('username')
    room = session.get('room')
    private_receiver = session.get('private_receiver')
    try:
        if username:
            users_collection.update_one(
                {"username": username},
                {"$set": {"online": False, "last_seen": datetime.utcnow()}}
            )
            emit('status_update', {"username": username, "online": False}, broadcast=True)
            logger.info(f"User {username} set to offline")
        if room and rooms_collection.find_one({"code": room}):
            rooms_collection.update_one(
                {"code": room},
                {"$pull": {"members": username}}
            )
            room_data = rooms_collection.find_one({"code": room})
            if not room_data["members"]:
                rooms_collection.delete_one({"code": room})
                logger.info(f"Room {room} deleted because it has no members")
            else:
                send({
                    "sender": "",
                    "message": f"{username} telah keluar chat"
                }, to=room)
                notifications_collection.insert_one({
                    "username": username,
                    "message": f"Kamu keluar dari room {room}",
                    "timestamp": datetime.utcnow(),
                    "read": False
                })
                emit('notification', {"message": f"Kamu keluar dari room {room}"}, to=username)
                leave_room(room)
                logger.info(f"User {username} disconnected from room {room}")
        if private_receiver:
            private_room = f"private_{min(username, private_receiver)}_{max(username, private_receiver)}"
            leave_room(private_room)
            logger.info(f"User {username} disconnected from private chat with {private_receiver}")
    except Exception as e:
        logger.error(f"Error on disconnect: {str(e)}")

if __name__ == "__main__":
    socketio.run(app, debug=True, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))