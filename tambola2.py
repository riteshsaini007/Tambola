import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import random
import os, json

# --- Initialize Firebase ---
if not firebase_admin._apps:

    # First try local JSON (for your laptop)
    local_path = r"D:\OneDrive\Desktop\streamlit project\MamlaStremlit\tambola-2ad18-firebase-adminsdk-fbsvc-ded93605df.json"

    if os.path.exists(local_path):
        cred = credentials.Certificate(local_path)
    else:
        # Render will use this ENV variable
        firebase_key = os.environ.get("FIREBASE_KEY")
        cred_dict = json.loads(firebase_key)
        cred = credentials.Certificate(cred_dict)

    firebase_admin.initialize_app(cred)

# ✅ ADD THIS (VERY IMPORTANT)
db = firestore.client()


# --- Firestore Functions ---
def add_user(username, password):
    db.collection("users").document(username).set({
        "username": username, "password": password
    })

def validate_user(username, password):
    doc = db.collection("users").document(username).get()
    if doc.exists:
        data = doc.to_dict()
        return data["password"] == password
    return False

def create_room(host, max_players):
    code = str(random.randint(100000, 999999))
    db.collection("rooms").document(code).set({
        "host": host,
        "max_players": max_players,
        "players": [],
        "status": "waiting"
    })
    return code

def join_room(username, room_code):
    room_ref = db.collection("rooms").document(room_code)
    doc = room_ref.get()

    if not doc.exists:  # ✅ fix here
        return "❌ Invalid room code!"

    data = doc.to_dict()
    if len(data["players"]) >= data["max_players"]:
        return "🚫 Room full!"
    if username in data["players"]:
        return "⚠️ Already joined!"

    data["players"].append(username)
    room_ref.update({"players": data["players"]})
    return "✅ Joined successfully!"


# --- Streamlit UI ---
st.set_page_config(page_title="Tambola Game", page_icon="🔥")
st.title("🎯 Tambola Game Login (Firebase)")

# Session State Setup
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "role" not in st.session_state:
    st.session_state.role = None
if "username" not in st.session_state:
    st.session_state.username = None
if "room_code" not in st.session_state:
    st.session_state.room_code = None

# --- LOGIN SCREEN ---
if not st.session_state.logged_in:
    menu = ["Login", "Sign Up"]
    choice = st.sidebar.selectbox("Menu", menu)

    # SIGNUP
    if choice == "Sign Up":
        st.subheader("📝 Create Account")
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")

        if st.button("Sign Up"):
            add_user(u, p)
            st.success("✅ Account created!")

    # LOGIN
    else:
        st.subheader("🔐 Login")
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")

        if st.button("Login"):
            if validate_user(u, p):
                st.session_state.logged_in = True
                st.session_state.username = u
                st.session_state.role = None  # choose after login
                st.rerun()
            else:
                st.error("❌ Wrong credentials!")

# -------- AFTER LOGIN: SELECT ROLE --------
elif st.session_state.role is None:
    st.success(f"Welcome {st.session_state.username}! 👋")
    st.subheader("Choose your mode")
    role = st.radio("Login as:", ["Admin", "Player"])
    if st.button("Continue"):
        st.session_state.role = role
        st.rerun()

# -------- DASHBOARD --------
else:
    username = st.session_state.username
    role = st.session_state.role

    st.sidebar.success(f"🎮 Logged in as {username} ({role})")
    if st.sidebar.button("Logout"):
        st.session_state.clear()
        st.rerun()

    # ✅ ADMIN SCREEN
    if role == "Admin":
        st.header("👑 Admin Panel - Create Room")
        max_players = st.number_input("Max Players", 2, 100, step=1)

        if st.button("Generate Room Code"):
            room_code = create_room(username, max_players)
            st.session_state.room_code = room_code
            st.success(f"✅ Room Created — Code: **{room_code}**")

        if st.session_state.room_code:
            st.info(f"Room Code: **{st.session_state.room_code}**")
            st.subheader("👥 Players joined:")
            room_data = db.collection("rooms").document(st.session_state.room_code).get().to_dict()
            for p in room_data["players"]:
                st.write(f"✅ {p}")
            st.info("⏳ Waiting for players...")

    # ✅ USER SCREEN
    else:
        st.header("🎮 Join Room")

        if st.session_state.room_code is None:
            room_code = st.text_input("Enter Room Code")
            if st.button("Join"):
                result = join_room(username, room_code)
                if "✅" in result:
                    st.session_state.room_code = room_code
                    st.success(result)
                    st.rerun()
                else:
                    st.error(result)

        else:
            st.success(f"✅ Joined Room: {st.session_state.room_code}")
            data = db.collection("rooms").document(st.session_state.room_code).get().to_dict()
            st.subheader("👥 Players in room:")
            for p in data["players"]:
                st.write(f"• {p}")
            st.info("⏳ Waiting for host to start game...")
