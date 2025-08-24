# ... (kode sebelumnya tetap, tambahkan di bagian yang sesuai)

# Tambah collection friend_requests
friend_requests_collection = db.friend_requests

# Route untuk menambah teman
@app.route('/add_friend/<friend_username>', methods=["POST"])
def add_friend(friend_username):
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
        # Kirim permintaan teman
        existing_request = friend_requests_collection.find_one({
            "from": username,
            "to": friend_username,
            "status": "pending"
        })
        if existing_request:
            logger.info(f"Friend request already exists from {username} to {friend_username}")
            return jsonify({"error": "Permintaan sudah dikirim"}), 400
        friend_requests_collection.insert_one({
            "from": username,
            "to": friend_username,
            "status": "pending",
            "timestamp": datetime.utcnow()
        })
        notifications_collection.insert_one({
            "username": friend_username,
            "message": f"{username} mengirim permintaan teman",
            "timestamp": datetime.utcnow(),
            "read": False
        })
        logger.info(f"Friend request sent from {username} to {friend_username}")
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error in add_friend: {str(e)}")
        return jsonify({"error": "Gagal mengirim permintaan teman"}), 500

# Route untuk menerima permintaan teman
@app.route('/accept_friend_request/<request_id>', methods=["POST"])
def accept_friend_request(request_id):
    username = session.get('username')
    if not username:
        logger.warning("No username in session for accept_friend_request")
        return jsonify({"error": "Unauthorized"}), 401
    try:
        request_data = friend_requests_collection.find_one({"_id": ObjectId(request_id)})
        if not request_data or request_data["to"] != username:
            logger.warning(f"Invalid friend request: {request_id}")
            return jsonify({"error": "Permintaan tidak valid"}), 404
        friend_username = request_data["from"]
        friend_requests_collection.update_one(
            {"_id": ObjectId(request_id)},
            {"$set": {"status": "accepted"}}
        )
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
            "message": f"{username} menerima permintaan temanmu",
            "timestamp": datetime.utcnow(),
            "read": False
        })
        logger.info(f"Friend request accepted: {username} and {friend_username}")
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error in accept_friend_request: {str(e)}")
        return jsonify({"error": "Gagal menerima permintaan teman"}), 500

# Update route search_users untuk autocomplete
@app.route('/search_users', methods=["POST"])
def search_users():
    try:
        query = request.form.get('query', '')
        logger.info(f"Searching users with query: {query}")
        users = list(users_collection.find(
            {"username": {"$regex": query, "$options": "i"}},
            {"username": 1, "avatar": 1, "last_seen": 1}
        ).limit(10))
        logger.info(f"Found {len(users)} users for query: {query}")
        return jsonify([{
            "username": u["username"],
            "avatar": f"/avatar/{u['username']}" if u.get("avatar") else "https://via.placeholder.com/40",
            "last_seen": u["last_seen"].strftime("%Y-%m-%d %H:%M:%S")
        } for u in users])
    except Exception as e:
        logger.error(f"Error in search_users: {str(e)}")
        return jsonify({"error": "Search failed"}), 500

# Update route dashboard untuk menampilkan daftar teman dan permintaan
@app.route('/dashboard')
def dashboard():
    username = session.get('username')
    if not username:
        logger.warning("No username in session for dashboard")
        return redirect(url_for('home'))
    try:
        user = users_collection.find_one({"username": username})
        if not user:
            logger.error(f"User {username} not found in database")
            return redirect(url_for('home'))
        online_users = list(users_collection.find({"online": True}))
        notifications = list(notifications_collection.find({"username": username}).sort("timestamp", -1).limit(10))
        friend_requests = list(friend_requests_collection.find({"to": username, "status": "pending"}))
        friends = users_collection.find({"username": {"$in": user.get("friends", [])}})
        logger.info(f"Rendering dashboard for {username}")
        return render_template(
            'dashboard.html',
            username=username,
            user=user,
            online_users=online_users,
            notifications=notifications,
            friend_requests=friend_requests,
            friends=friends
        )
    except Exception as e:
        logger.error(f"Error in dashboard route: {str(e)}")
        return render_template('home.html', error=f"Terjadi kesalahan server: {str(e)}"), 500