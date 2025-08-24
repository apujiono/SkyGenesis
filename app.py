import random
from string import ascii_letters
from flask import Flask, request, render_template, redirect, url_for, session, jsonify, send_file
from flask_socketio import SocketIO, join_room, leave_room, send, emit
from pymongo import MongoClient
from gridfs import GridFS
from datetime import datetime
import os
from dotenv import load_dotenv
from io import BytesIO
from werkzeug.utils import secure_filename

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY")
socketio = SocketIO(app)

# MongoDB setup
mongo_client = MongoClient(os.getenv("MONGO_URI"))
db = mongo_client.skygenesis
users_collection = db.users
room_messages_collection = db.room_messages
private_messages_collection = db.private_messages
notifications_collection = db.notifications
fs = GridFS(db)  # GridFS untuk avatar

# In-memory storage untuk rooms
rooms = {}

def generate_room_code(length: int, existing_codes: list[str]) -> str:
    while True:
        code_chars = [random.choice(ascii_letters) for _ in range(length)]
        code = ''.join(code_chars)
        if code not in existing_codes:
            return code

@app.route('/', methods=["GET", "POST"])
def home():
    session.clear()
    if request.method == "POST":
        username = request.form.get('username')
        code_length = int(request.form.get('code_length', 6))
        create = request.form.get('create', False)
        code = request.form.get('code')
        join = request.form.get('join', False)
        if not username:
            return render_template('home.html', error="Nama diperlukan", code=code)
        user = users_collection.find_one({"username": username})
        if not user:
            users_collection.insert_one({
                "username": username,
                "online": True,
                "rooms": [],
                "avatar": None,  # Akan diisi setelah upload
                "last_seen": datetime.utcnow()
            })
        else:
            users_collection.update_one(
                {"username": username},
                {"$set": {"online": True, "last_seen": datetime.utcnow()}}
            )
        if create != False:
            room_code = generate_room_code(code_length, list(rooms.keys()))
            rooms[room_code] = {'members': 0}
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
        if join != False:
            if not code:
                return render_template('home.html', error="Masukkan code room", username=username)
            if code not in rooms:
                return render_template('home.html', error="Code room salah", username=username)
            room_code = code
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
        session['room'] = room_code
        session['username'] = username
        return redirect(url_for('dashboard'))
    return render_template('home.html')

@app.route('/dashboard')
def dashboard():
    username = session.get('username')
    if not username:
        return redirect(url_for('home'))
    user = users_collection.find_one({"username": username})
    online_users = list(users_collection.find({"online": True}))
    notifications = list(notifications_collection.find({"username": username}).sort("timestamp", -1).limit(10))
    return render_template('dashboard.html', username=username, user=user, online_users=online_users, notifications=notifications)

@app.route('/refresh_users')
def refresh_users():
    username = session.get('username')
    if not username:
        return redirect(url_for('home'))
    user = users_collection.find_one({"username": username})
    online_users = list(users_collection.find({"online": True}))
    notifications = list(notifications_collection.find({"username": username}).sort("timestamp", -1).limit(10))
    return render_template('dashboard.html', username=username, user=user, online_users=online_users, notifications=notifications)

@app.route('/search_users', methods=["POST"])
def search_users():
    query = request.form.get('query', '')
    users = list(users_collection.find({"username": {"$regex": query, "$options": "i"}}))
    return jsonify([{
        "username": u["username"],
        "avatar": f"/avatar/{u['username']}" if u.get("avatar") else "https://via.placeholder.com/40",
        "last_seen": u["last_seen"].strftime("%Y-%m-%d %H:%M:%S")
    } for u in users])

@app.route('/avatar/<username>')
def get_avatar(username):
    user = users_collection.find_one({"username": username})
    if user and user.get("avatar"):
        file = fs.get(user["avatar"])
        return send_file(BytesIO(file.read()), mimetype=file.content_type)
    return redirect("https://via.placeholder.com/40")

@app.route('/upload_avatar', methods=["POST"])
def upload_avatar():
    username = session.get('username')
    if not username:
        return redirect(url_for('home'))
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
    return redirect(url_for('dashboard'))

@app.route('/room/<room_code>')
def room(room_code):
    username = session.get('username')
    if not username or room_code not in rooms:
        return redirect(url_for('home'))
    session['room'] = room_code
    messages = room_messages_collection.find({"room": room_code}).sort("timestamp", -1).limit(50)
    return render_template('room.html', room=room_code, username=username, messages=messages)

@app.route('/room/<room_code>/more/<int:page>')
def room_more(room_code, page):
    username = session.get('username')
    if not username or room_code not in rooms:
        return jsonify([])
    skip = page * 50
    messages = room_messages_collection.find({"room": room_code}).sort("timestamp", -1).skip(skip).limit(50)
    return jsonify([{
        "sender": m["sender"],
        "message": m["message"],
        "reactions": m.get("reactions", {})
    } for m in messages])

@app.route('/private/<receiver>')
def private_chat(receiver):
    username = session.get('username')
    if not username or not users_collection.find_one({"username": receiver}):
        return redirect(url_for('dashboard'))
    session['private_receiver'] = receiver
    messages = private_messages_collection.find({
        "$or": [
            {"sender": username, "receiver": receiver},
            {"sender": receiver, "receiver": username}
        ]
    }).sort("timestamp", -1).limit(50)
    return render_template('private.html', username=username, receiver=receiver, messages=messages)

@app.route('/private/<receiver>/more/<int:page>')
def private_more(receiver, page):
    username = session.get('username')
    if not username:
        return jsonify([])
    skip = page * 50
    messages = private_messages_collection.find({
        "$or": [
            {"sender": username, "receiver": receiver},
            {"sender": receiver, "receiver": username}
        ]
    }).sort("timestamp", -1).skip(skip).limit(50)
    return jsonify([{
        "sender": m["sender"],
        "message": m["message"],
        "reactions": m.get("reactions", {})
    } for m in messages])

@app.route('/react/<message_type>/<message_id>', methods=["POST"])
def react(message_type, message_id):
    username = session.get('username')
    if not username:
        return jsonify({"error": "Unauthorized"}), 401
    emoji = request.form.get('emoji')
    collection = room_messages_collection if message_type == "room" else private_messages_collection
    collection.update_one(
        {"_id": ObjectId(message_id)},
        {"$addToSet": {f"reactions.{emoji}": username}},
        upsert=True
    )
    return jsonify({"success": True})

@socketio.on('connect')
def handle_connect():
    username = session.get('username')
    room = session.get('room')
    private_receiver = session.get('private_receiver')
    if not username:
        return
    if room and room in rooms:
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
        emit('notification', {"message": f"{username} bergabung di room {room}"}, broadcast=True)
        rooms[room]["members"] += 1
    if private_receiver:
        private_room = f"private_{min(username, private_receiver)}_{max(username, private_receiver)}"
        join_room(private_room)
        notifications_collection.insert_one({
            "username": username,
            "message": f"Kamu memulai chat pribadi dengan {private_receiver}",
            "timestamp": datetime.utcnow(),
            "read": False
        })
        emit('notification', {"message": f"{username} memulai chat pribadi dengan {private_receiver}"}, to=private_room)

@socketio.on('room_message')
def handle_room_message(payload):
    room = session.get('room')
    username = session.get('username')
    if room not in rooms:
        return
    message = {
        "sender": username,
        "message": payload["message"],
        "room": room,
        "timestamp": datetime.utcnow(),
        "reactions": {}
    }
    msg_id = room_messages_collection.insert_one(message).inserted_id
    send({"_id": str(msg_id), **message}, to=room)
    notifications_collection.insert_one({
        "username": username,
        "message": f"Pesan baru di room {room}",
        "timestamp": datetime.utcnow(),
        "read": False
    })
    emit('notification', {"message": f"Pesan baru di room {room}"}, broadcast=True)

@socketio.on('private_message')
def handle_private_message(payload):
    username = session.get('username')
    receiver = session.get('private_receiver')
    if not receiver:
        return
    private_room = f"private_{min(username, receiver)}_{max(username, receiver)}"
    message = {
        "sender": username,
        "receiver": receiver,
        "message": payload["message"],
        "timestamp": datetime.utcnow(),
        "reactions": {}
    }
    msg_id = private_messages_collection.insert_one(message).inserted_id
    emit('private_message', {"_id": str(msg_id), **message}, to=private_room)
    notifications_collection.insert_one({
        "username": receiver,
        "message": f"Pesan pribadi baru dari {username}",
        "timestamp": datetime.utcnow(),
        "read": False
    })
    emit('notification', {"message": f"Pesan pribadi baru dari {username}"}, to=private_room)

@socketio.on('typing')
def handle_typing(data):
    username = session.get('username')
    room = session.get('room')
    private_receiver = session.get('private_receiver')
    if room and room in rooms:
        emit('typing', {"username": username, "isTyping": data["isTyping"]}, to=room, include_self=False)
    if private_receiver:
        private_room = f"private_{min(username, private_receiver)}_{max(username, private_receiver)}"
        emit('typing', {"username": username, "isTyping": data["isTyping"]}, to=private_room, include_self=False)

@socketio.on('disconnect')
def handle_disconnect():
    username = session.get('username')
    room = session.get('room')
    private_receiver = session.get('private_receiver')
    if username:
        users_collection.update_one(
            {"username": username},
            {"$set": {"online": False, "last_seen": datetime.utcnow()}}
        )
    if room and room in rooms:
        rooms[room]["members"] -= 1
        if rooms[room]["members"] <= 0:
            del rooms[room]
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
        emit('notification', {"message": f"{username} keluar dari room {room}"}, broadcast=True)
        leave_room(room)
    if private_receiver:
        private_room = f"private_{min(username, private_receiver)}_{max(username, private_receiver)}"
        leave_room(private_room)

if __name__ == "__main__":
    socketio.run(app, debug=True)