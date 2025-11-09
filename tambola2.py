import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import os, json, random, time
from datetime import datetime
import ssl, certifi

# ✅ Force Python to use correct SSL certificates
ssl_context = ssl.create_default_context(cafile=certifi.where())

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
os.environ["GRPC_DEFAULT_SSL_ROOTS_FILE_PATH"] = certifi.where()

# ✅ Fix SSL context for Firestore client
ssl_context = ssl.create_default_context(cafile=certifi.where())


# --------------- Firebase init (local JSON or Render ENV) ---------------
if not firebase_admin._apps:

    # ✅ Absolute path to your firebase.json
    local_path = r"D:\OneDrive\Desktop\streamlit project\TambolaFolder\firebase.json"

    if os.path.exists(local_path):
        cred = credentials.Certificate(local_path)
    else:
        firebase_key = os.environ.get("FIREBASE_KEY")
        if not firebase_key:
            raise RuntimeError(
                "Firebase credentials not found. "
                "Place firebase.json next to tambola2.py OR set FIREBASE_KEY env."
            )
        cred_dict = json.loads(firebase_key)
        cred = credentials.Certificate(cred_dict)

    firebase_admin.initialize_app(cred)

# ✅ Now this WILL WORK (only if firebase init is successful)
db = firestore.client()

# --------------- Helpers ---------------
PALETTE = [
    "#e63946","#457b9d","#2a9d8f","#f4a261","#e9c46a",
    "#9b5de5","#00bbf9","#ef476f","#06d6a0","#ffd166"
]

def get_room_ref(room_code):
    return db.collection("rooms").document(room_code)

def get_ticket_ref(room_code, username):
    return get_room_ref(room_code).collection("tickets").document(username)

def range_for_col(c):
    start = c*10 + 1
    end = 90 if c == 8 else (c+1)*10
    return list(range(start, end+1))

def generate_ticket():
    """
    Generates a valid-ish Tambola ticket: 3x9 grid, 15 numbers, 5 per row,
    column ranges respected, columns sorted ascending.
    """
    # pick columns for each row (5 per row, total coverage ~)
    row_cols = []
    all_cols = list(range(9))
    # ensure distribution: start with random 5 for each row
    row_cols.append(sorted(random.sample(all_cols, 5)))
    row_cols.append(sorted(random.sample(all_cols, 5)))
    row_cols.append(sorted(random.sample(all_cols, 5)))

    # ensure total 15 unique (if overlap causing too many empty cols, adjust)
    # simple fix: guarantee at least 1 number in each of 9 columns across rows
    coverage = {c:0 for c in range(9)}
    for r in range(3):
        for c in row_cols[r]:
            coverage[c]+=1
    missing = [c for c,v in coverage.items() if v==0]
    for c in missing:
        r = random.randrange(3)
        # add c to that row, and if that row >5, drop a random other column
        if c not in row_cols[r]:
            row_cols[r].append(c)
        while len(row_cols[r])>5:
            drop = random.choice([x for x in row_cols[r] if coverage[x]>1 and x!=c])
            row_cols[r].remove(drop)
            coverage[drop]-=1
        row_cols[r] = sorted(row_cols[r])
        coverage[c]+=1

    # pick numbers for each selected (row, col)
    grid = [[0]*9 for _ in range(3)]
    col_numbers = {c: range_for_col(c)[:] for c in range(9)}
    for c in range(9):
        random.shuffle(col_numbers[c])

    for r in range(3):
        for c in row_cols[r]:
            # pick smallest remaining to keep ascending in col after sort later
            n = col_numbers[c].pop()
            grid[r][c] = n

    # sort each column ascending top->bottom while keeping blanks as 0
    for c in range(9):
        vals = [(grid[r][c], r) for r in range(3) if grid[r][c]!=0]
        vals_sorted = sorted(vals, key=lambda x:x[0])
        rows_filled = [r for _,r in vals_sorted]
        nums_sorted = [v for v,_ in vals_sorted]
        # clear
        for r in range(3): grid[r][c]=0
        # place back in ascending from top rows of original filled positions
        for idx, r in enumerate(rows_filled):
            grid[r][c] = nums_sorted[idx]

    # ensure each row has exactly 5 numbers (should be)
    assert all(sum(1 for x in row if x!=0)==5 for row in grid), "Row counts off"
    return grid

def draw_next_number(room_doc):
    drawn = room_doc.get("numbers_drawn", [])
    remaining = [n for n in range(1,91) if n not in drawn]
    if not remaining:
        return None
    n = random.choice(remaining)
    drawn.append(n)
    get_room_ref(room_doc["code"]).update({
        "numbers_drawn": drawn,
        "current_number": n,
        "last_draw_ts": datetime.utcnow().isoformat()
    })
    return n

def ensure_colors(room_doc):
    colors = room_doc.get("colors", {})
    changed = False
    for i, username in enumerate(room_doc.get("players", [])):
        if username not in colors:
            colors[username] = PALETTE[i % len(PALETTE)]
            changed = True
    if changed:
        get_room_ref(room_doc["code"]).update({"colors": colors})
    return colors

def issue_tickets_to_all(room_doc):
    room_ref = get_room_ref(room_doc["code"])
    for u in room_doc.get("players", []):
        t_ref = room_ref.collection("tickets").document(u)
        if not t_ref.get().exists:
            t_ref.set({
                "grid": generate_ticket(),
                "marked": []
            })

def get_user_ticket(room_code, username):
    t = get_ticket_ref(room_code, username).get()
    return t.to_dict() if t.exists else None

def toggle_mark(room_code, username, number):
    t_ref = get_ticket_ref(room_code, username)
    doc = t_ref.get()
    if not doc.exists: return
    data = doc.to_dict()
    marked = set(data.get("marked", []))
    if number in marked:
        marked.remove(number)
    else:
        marked.add(number)
    t_ref.update({"marked": sorted(list(marked))})

def cell_html(text, bg="#111", fg="#fff", brd="#333"):
    return f"""<div style="
        display:flex;align-items:center;justify-content:center;
        height:38px;min-width:38px;border:1px solid {brd};
        background:{bg};color:{fg};font-weight:600;border-radius:6px;">{text}</div>"""

def number_grid_1_90(drawn, colors_map=None):
    # colors_map: {n: "#hex"} optional
    html = '<div style="display:grid;grid-template-columns:repeat(10, 1fr);gap:6px;">'
    for n in range(1,91):
        if n in drawn:
            clr = "#3ddc97"
            if colors_map and n in colors_map:
                clr = colors_map[n]
            html += cell_html(n, bg=clr, fg="#000", brd="#0a0")
        else:
            html += cell_html(n, bg="#1e1e1e", fg="#bbb")
    html += "</div>"
    return html

def render_ticket(grid, marked, my_color="#ffd166", clickable=False, on_click=None):
    # grid: 3x9; marked: set/list
    st.markdown(
        "<div style='display:grid;grid-template-columns:repeat(9, 1fr);gap:6px;'>",
        unsafe_allow_html=True
    )
    for r in range(3):
        for c in range(9):
            val = grid[r][c]
            if val == 0:
                st.markdown(cell_html("&nbsp;", bg="#0e0e0f"), unsafe_allow_html=True)
            else:
                is_marked = val in marked
                bg = "#262626"
                brd = my_color if is_marked else "#444"
                fg = "#fff"
                if val in marked:
                    fg = "#000"
                    bg = my_color  # highlight marked cell by user color
                if clickable:
                    btn_key = f"mark_{val}_{r}_{c}"
                    if st.button(str(val), key=btn_key):
                        if on_click: on_click(val)
                else:
                    st.markdown(cell_html(val, bg=bg, fg=fg, brd=brd), unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

# --------------- Existing auth/room utilities from your app ---------------
def add_user(username, password):
    db.collection("users").document(username).set({"username": username, "password": password})

def validate_user(username, password):
    doc = db.collection("users").document(username).get()
    if doc.exists:
        return doc.to_dict().get("password") == password
    return False

def create_room(host, max_players):
    code = str(random.randint(100000, 999999))
    get_room_ref(code).set({
        "code": code,
        "host": host,
        "max_players": max_players,
        "players": [],
        "status": "waiting",
        "numbers_drawn": [],
        "current_number": None,
        "colors": {}
    })
    return code

def join_room(username, room_code):
    rref = get_room_ref(room_code)
    doc = rref.get()
    if not doc.exists:
        return "❌ Invalid room code!"
    data = doc.to_dict()
    if len(data["players"]) >= data["max_players"]:
        return "🚫 Room full!"
    if username in data["players"]:
        return "⚠️ Already joined!"
    data["players"].append(username)
    rref.update({"players": data["players"]})
    return "✅ Joined successfully!"

# --------------- UI ---------------
st.set_page_config(page_title="Tambola Realtime", page_icon="🔥", layout="wide")
st.title("🎯 Tambola Realtime (Render + Firebase)")

# session
ss = st.session_state
for k,v in {"logged_in":False,"role":None,"username":None,"room_code":None,"auto_refresh":True}.items():
    if k not in ss: ss[k]=v

# auth
if not ss.logged_in:
    choice = st.sidebar.selectbox("Menu", ["Login","Sign Up"])
    if choice=="Sign Up":
        st.subheader("📝 Create Account")
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.button("Sign Up"):
            if u and p:
                add_user(u,p); st.success("✅ Account created!")
            else:
                st.error("Enter username & password")
    else:
        st.subheader("🔐 Login")
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.button("Login"):
            if validate_user(u,p):
                ss.logged_in=True; ss.username=u; ss.role=None
                st.rerun()
            else:
                st.error("❌ Wrong credentials!")
    st.stop()

if ss.role is None:
    st.success(f"Welcome {ss.username}! 👋")
    role = st.radio("Login as:", ["Admin","Player"], horizontal=True)
    room_area = st.container()
    if role=="Admin":
        with room_area:
            st.header("👑 Admin Panel - Create Room")
            max_players = st.number_input("Max Players", 2, 100, step=1, value=6)
            if st.button("Generate Room Code"):
                code = create_room(ss.username, max_players)
                ss.role="Admin"; ss.room_code=code; st.rerun()
    else:
        with room_area:
            st.header("🎮 Join Room")
            rc = st.text_input("Enter Room Code")
            if st.button("Join"):
                msg = join_room(ss.username, rc)
                if msg.startswith("✅"):
                    ss.role="Player"; ss.room_code=rc; st.rerun()
                else:
                    st.error(msg)
    st.stop()

# after role
st.sidebar.success(f"🎮 Logged in as {ss.username} ({ss.role})")
if st.sidebar.button("Logout"):
    for k in list(ss.keys()): del ss[k]
    st.rerun()

room_ref = get_room_ref(ss.room_code)
room_doc_s = room_ref.get()
if not room_doc_s.exists:
    st.error("Room not found."); st.stop()
room = room_doc_s.to_dict()
colors = ensure_colors(room)

# ✅ Auto-refresh (Fixed implementation)
auto_refresh = st.sidebar.checkbox("Auto-refresh (2s)", value=ss.auto_refresh)
ss.auto_refresh = auto_refresh

# Show refresh status
if ss.auto_refresh:
    refresh_placeholder = st.sidebar.empty()
    refresh_placeholder.info("🔄 Auto-refresh enabled")
    
    # Add a small delay before refresh
    time.sleep(2)
    st.rerun()
else:
    st.sidebar.info("⏸️ Auto-refresh paused")

colL, colR = st.columns([2,2])

# ---------------- ADMIN SCREEN ----------------
if ss.role=="Admin":
    with colL:
        st.subheader("Room")
        st.write(f"**Code:** `{room['code']}`")
        st.write(f"**Players ({len(room['players'])}/{room['max_players']}):**")
        if room['players']:
            chips = " ".join([f"<span style='padding:6px 10px;border-radius:12px;background:{colors.get(p,'#444')};color:#000;font-weight:700;margin-right:6px'>{p}</span>" for p in room['players']])
            st.markdown(chips, unsafe_allow_html=True)
        else:
            st.info("Waiting for players to join…")

        if room["status"]=="waiting":
            if st.button("🚀 Start Game (Generate Tickets)"):
                issue_tickets_to_all(room)
                room_ref.update({"status":"started","numbers_drawn":[],"current_number":None,"started_ts":datetime.utcnow().isoformat()})
                st.success("Game started! Tickets issued.")
                st.rerun()
        else:
            # draw number section + bag animation
            st.subheader("🎒 Draw Numbers")
            spot = st.empty()
            if st.button("🎲 Draw Next Number"):
                # simple bag animation
                for frame in ["🟡","🟠","🟣","🟢","🔵","🔴"]:
                    spot.markdown(f"<div style='font-size:48px;text-align:center'>{frame}</div>", unsafe_allow_html=True)
                    time.sleep(0.08)
                n = draw_next_number(room_ref.get().to_dict())
                if n is not None:
                    spot.markdown(f"<div style='font-size:54px;text-align:center'>🎉 <b>{n}</b></div>", unsafe_allow_html=True)
                else:
                    st.info("All numbers drawn.")
                st.rerun()

    with colR:
        st.subheader("Common Board (1–90)")
        latest = room_ref.get().to_dict()
        drawn = latest.get("numbers_drawn", [])
        st.markdown(number_grid_1_90(drawn), unsafe_allow_html=True)

        st.divider()
        st.subheader("Tickets Preview")
        for p in room["players"]:
            tdoc = get_user_ticket(room["code"], p)
            if tdoc:
                st.markdown(f"**{p}**")
                render_ticket(tdoc["grid"], set(tdoc.get("marked",[])), my_color=colors.get(p,"#ffd166"))

# ---------------- PLAYER SCREEN ----------------
else:
    with colL:
        st.subheader("Your Ticket")
        tdoc = get_user_ticket(room["code"], ss.username)
        if not tdoc:
            st.info("Admin hasn't started the game yet. Waiting for ticket…")
        else:
            my_color = colors.get(ss.username, "#ffd166")
            # clickable grid to toggle mark
            # render as buttons
            grid = tdoc["grid"]
            marked = set(tdoc.get("marked", []))

            # draw a clickable grid
            # we use a layout of buttons row-wise
            for r in range(3):
                ccols = st.columns(9)
                for c in range(9):
                    val = grid[r][c]
                    if val==0:
                        with ccols[c]:
                            st.markdown(cell_html("&nbsp;", bg="#0e0e0f"), unsafe_allow_html=True)
                    else:
                        with ccols[c]:
                            is_marked = val in marked
                            lbl = f"✖ {val}" if is_marked else str(val)
                            if st.button(lbl, key=f"btn_{val}_{r}_{c}"):
                                toggle_mark(room["code"], ss.username, val)
                                st.rerun()

            st.caption("Tip: Click a number to toggle a soft cross ✖ on your ticket.")

    with colR:
        st.subheader("Common Board (1–90)")
        fresh = room_ref.get().to_dict()
        drawn = fresh.get("numbers_drawn", [])
        # Optional: color per your own marks on common board (outline via your color)
        # For simplicity: just highlight drawn numbers (green)
        st.markdown(number_grid_1_90(drawn), unsafe_allow_html=True)

        cur = fresh.get("current_number")
        if cur:
            st.info(f"Latest draw: **{cur}**")
        else:
            st.info("Waiting for admin to draw…")