from fastapi import FastAPI, Request, Response, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from pydantic import BaseModel
from typing import List, Optional
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from cryptography.fernet import Fernet
from dotenv import load_dotenv
import mysql.connector
import os
import random
import hashlib
import hmac
import time
import secrets

# Load environment variables from .env
load_dotenv()

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Static Files and Templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# -----------------------------
# Encryption Helpers
# -----------------------------
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
_fernet = Fernet(ENCRYPTION_KEY.encode()) if ENCRYPTION_KEY else None

ENCRYPTED_FIELDS = ["name", "email", "phone"]


def encrypt_value(value: str) -> str:
    """Encrypt a string value using Fernet (AES-128-CBC under the hood)."""
    if not _fernet or not value:
        return value
    return _fernet.encrypt(value.encode()).decode()


def decrypt_value(value: str) -> str:
    """Decrypt a Fernet-encrypted string. Returns the original if decryption fails (plaintext data)."""
    if not _fernet or not value:
        return value
    try:
        return _fernet.decrypt(value.encode()).decode()
    except Exception:
        # Value is likely still plaintext (not yet encrypted)
        return value


def encrypt_participant(data: dict) -> dict:
    """Encrypt sensitive fields in a participant dict before storing."""
    encrypted = dict(data)
    for field in ENCRYPTED_FIELDS:
        if field in encrypted and encrypted[field]:
            encrypted[field] = encrypt_value(str(encrypted[field]))
    return encrypted


def decrypt_participant(data: dict) -> dict:
    """Decrypt sensitive fields in a participant dict for reading."""
    decrypted = dict(data)
    for field in ENCRYPTED_FIELDS:
        if field in decrypted and decrypted[field]:
            decrypted[field] = decrypt_value(str(decrypted[field]))
    return decrypted


# -----------------------------
# DB Connection
# -----------------------------
def get_a():
    config = {
        "host": os.getenv("DB_HOST", "localhost"),
        "user": os.getenv("DB_USER", "root"),
        "password": os.getenv("DB_PASSWORD", ""),
        "database": os.getenv("DB_NAME", "cultural_fest")
    }
    
    # Enable SSL for PlanetScale or if DB_SSL is set
    if "planetscale" in config["host"].lower() or os.getenv("DB_SSL") == "true":
        config["ssl_disabled"] = False
        # Common CA cert path on Linux (e.g., Render)
        if os.path.exists("/etc/ssl/certs/ca-certificates.crt"):
            config["ssl_ca"] = "/etc/ssl/certs/ca-certificates.crt"
            
    return mysql.connector.connect(**config)

# Home route replaced by HTML template below

# -----------------------------
# Get All Participants
# -----------------------------
@app.get("/participants")
def get_participants():
    a = get_a()
    cursor = a.cursor(dictionary=True)

    cursor.execute("SELECT * FROM participants")
    data = cursor.fetchall()

    cursor.close()
    a.close()

    # Decrypt sensitive fields before returning
    data = [decrypt_participant(p) for p in data]

    return {"participants": data}


# -----------------------------
# Register Participant
# -----------------------------

def _generate_participant_id(cursor) -> int:
    while True:
        pid = random.randint(100000, 999999)
        cursor.execute("SELECT participant_id FROM participants WHERE participant_id = %s", (pid,))
        if not cursor.fetchone():
            return pid

@app.post("/participants")
def add_participant(
    name: str,
    college: str,
    department: str,
    year: int,
    email: str,
    phone: str
):
    a = get_a()
    cursor = a.cursor(dictionary=True)

    # For duplicate check, we need to encrypt the email and check,
    # or fetch all and decrypt. Since emails are encrypted, fetch & compare.
    cursor.execute("SELECT * FROM participants")
    all_participants = cursor.fetchall()

    for p in all_participants:
        decrypted_email = decrypt_value(p.get("email", ""))
        if decrypted_email == email:
            cursor.close()
            a.close()
            return {"message": "Participant already exists"}

    # Encrypt sensitive fields before storing
    enc_name = encrypt_value(name)
    enc_email = encrypt_value(email)
    enc_phone = encrypt_value(phone)

    pid = _generate_participant_id(cursor)

    cursor.execute("""
        INSERT INTO participants
        (participant_id, name, college, department, year, email, phone)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
    """, (pid, enc_name, college, department, year, enc_email, enc_phone))

    a.commit()

    cursor.close()
    a.close()

    return {"message": f"Participant registered successfully! Your Participant ID is: {pid}", "participant_id": pid}


# -----------------------------
# Get All Events
# -----------------------------
@app.get("/events")
def get_events():
    a = get_a()
    cursor = a.cursor(dictionary=True)

    cursor.execute("SELECT * FROM events")
    data = cursor.fetchall()

    cursor.close()
    a.close()

    return {"events": data}


# -----------------------------
# (Old Add Event route removed, moved to admin api)
# -----------------------------

# -----------------------------
# Register Participant in Event
# -----------------------------
@app.post("/register-event")
def register_event(
    participant_id: int,
    event_id: int
):
    a = get_a()
    cursor = a.cursor(dictionary=True)

    cursor.execute("""
        INSERT INTO registrations
        (participant_id, event_id, reg_date, payment_status)
        VALUES (%s,%s,CURDATE(),'Paid')
    """, (participant_id, event_id))

    a.commit()

    cursor.close()
    a.close()

    return {"message": "Registered for event successfully"}


# -----------------------------
# Get Registrations with Join
# -----------------------------
@app.get("/registrations")
def get_registrations():
    a = get_a()
    cursor = a.cursor(dictionary=True)

    cursor.execute("""
        SELECT p.name, e.event_name, r.reg_date, r.payment_status
        FROM registrations r
        JOIN participants p
        ON r.participant_id = p.participant_id
        JOIN events e
        ON r.event_id = e.event_id
    """)

    data = cursor.fetchall()

    cursor.close()
    a.close()

    # Decrypt the participant name in registration records
    for record in data:
        if "name" in record:
            record["name"] = decrypt_value(record["name"])

    return {"registrations": data}

# -----------------------------
# Group Registration Model
# -----------------------------
class GroupMember(BaseModel):
    name: str
    college: str
    department: str
    year: int
    email: str
    phone: str

class GroupRegistration(BaseModel):
    members: List[GroupMember]


# -----------------------------
# Group Register Participants
# -----------------------------
@app.post("/participants/group")
def add_group_participants(group: GroupRegistration):
    a = get_a()
    cursor = a.cursor(dictionary=True)

    # Fetch all existing participants for duplicate check (encrypted emails)
    cursor.execute("SELECT email FROM participants")
    all_existing = cursor.fetchall()
    existing_emails = set()
    for p in all_existing:
        existing_emails.add(decrypt_value(p.get("email", "")))

    registered = []
    skipped = []

    for member in group.members:
        if member.email in existing_emails:
            skipped.append(member.name)
            continue

        # Encrypt sensitive fields
        enc_name = encrypt_value(member.name)
        enc_email = encrypt_value(member.email)
        enc_phone = encrypt_value(member.phone)

        pid = _generate_participant_id(cursor)

        cursor.execute("""
            INSERT INTO participants
            (participant_id, name, college, department, year, email, phone)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, (pid, enc_name, member.college, member.department,
              member.year, enc_email, enc_phone))
        registered.append({"name": member.name, "id": pid})
        existing_emails.add(member.email)

    a.commit()
    cursor.close()
    a.close()

    if registered:
        msg = f"{len(registered)} member(s) registered successfully! IDs generated: " + ", ".join([f"{r['name']}: {r['id']}" for r in registered])
    else:
        msg = "No members were registered."
        
    if skipped:
        msg += f". {len(skipped)} skipped (already registered)."

    return {"message": msg, "registered": registered, "skipped": skipped}


# -----------------------------
# Frontend Routes
# -----------------------------
@app.get("/", response_class=HTMLResponse)
async def serve_index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/page/participants", response_class=HTMLResponse)
async def serve_participants(request: Request):
    return templates.TemplateResponse("participants.html", {"request": request})

@app.get("/page/events", response_class=HTMLResponse)
async def serve_events(request: Request):
    return templates.TemplateResponse("events.html", {"request": request})

@app.get("/page/registrations", response_class=HTMLResponse)
async def serve_registrations(request: Request):
    return templates.TemplateResponse("registrations.html", {"request": request})


# ═══════════════════════════════════════
# ADMIN PANEL — Session & Auth
# ═══════════════════════════════════════

# Derive a signing secret from ENCRYPTION_KEY (never expose the key itself)
_admin_sign_secret = hashlib.sha256(
    (ENCRYPTION_KEY or "fallback").encode()
).hexdigest()


def _sign_session(timestamp: str) -> str:
    """Create an HMAC signature for the session timestamp."""
    return hmac.new(
        _admin_sign_secret.encode(),
        timestamp.encode(),
        hashlib.sha256
    ).hexdigest()


def _verify_admin(request: Request) -> bool:
    """Verify the admin session cookie is valid."""
    cookie = request.cookies.get("admin_session")
    if not cookie or not ENCRYPTION_KEY:
        return False
    try:
        parts = cookie.split(".")
        if len(parts) != 2:
            return False
        ts, sig = parts
        expected = _sign_session(ts)
        if not hmac.compare_digest(sig, expected):
            return False
        # Session valid for 24 hours
        if time.time() - float(ts) > 86400:
            return False
        return True
    except Exception:
        return False


# ─────────────────────────────────────────
# Admin Page & Auth Routes
# ─────────────────────────────────────────

@app.get("/admin", response_class=HTMLResponse)
async def serve_admin(request: Request):
    """Serve the admin panel. JS handles login/dashboard states."""
    return templates.TemplateResponse("admin.html", {"request": request})


@app.post("/admin/login")
async def admin_login(request: Request):
    """Verify the encryption key and set a session cookie."""
    body = await request.json()
    submitted_key = body.get("key", "")

    if not ENCRYPTION_KEY:
        return JSONResponse(
            {"ok": False, "error": "No encryption key configured on server."},
            status_code=500
        )

    if not hmac.compare_digest(submitted_key, ENCRYPTION_KEY):
        return JSONResponse(
            {"ok": False, "error": "Invalid key. Access denied."},
            status_code=403
        )

    # Create signed session cookie
    ts = str(int(time.time()))
    sig = _sign_session(ts)
    token = f"{ts}.{sig}"

    response = JSONResponse({"ok": True})
    response.set_cookie(
        key="admin_session",
        value=token,
        httponly=True,
        samesite="strict",
        max_age=86400  # 24 hours
    )
    return response


@app.post("/admin/logout")
async def admin_logout():
    """Clear the admin session cookie."""
    response = JSONResponse({"ok": True})
    response.delete_cookie("admin_session")
    return response


@app.get("/admin/api/verify")
async def admin_verify(request: Request):
    """Check if the current session is valid (used by JS on page load)."""
    return {"authenticated": _verify_admin(request)}


# ─────────────────────────────────────────
# Admin API Endpoints (all session-protected)
# ─────────────────────────────────────────

@app.get("/admin/api/stats")
async def admin_stats(request: Request):
    if not _verify_admin(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    conn = get_a()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT COUNT(*) as c FROM participants")
    p_count = cursor.fetchone()["c"]
    cursor.execute("SELECT COUNT(*) as c FROM events")
    e_count = cursor.fetchone()["c"]
    cursor.execute("SELECT COUNT(*) as c FROM registrations")
    r_count = cursor.fetchone()["c"]

    # Check encryption status
    enc_status = "no_key"
    if _fernet and p_count > 0:
        cursor.execute("SELECT name FROM participants LIMIT 1")
        sample = cursor.fetchone()
        if sample:
            try:
                _fernet.decrypt(sample["name"].encode())
                enc_status = "encrypted"
            except Exception:
                enc_status = "plaintext"
    elif _fernet and p_count == 0:
        enc_status = "no_data"

    cursor.close()
    conn.close()

    return {
        "participants": p_count,
        "events": e_count,
        "registrations": r_count,
        "encryption": enc_status
    }


@app.get("/admin/api/participants")
async def admin_participants(request: Request):
    if not _verify_admin(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    conn = get_a()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM participants ORDER BY participant_id")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return {"data": [decrypt_participant(p) for p in rows]}


@app.get("/admin/api/events")
async def admin_events(request: Request):
    if not _verify_admin(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    conn = get_a()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM events ORDER BY event_id")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return {"data": rows}


@app.get("/admin/api/registrations")
async def admin_registrations(request: Request):
    if not _verify_admin(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    conn = get_a()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT r.registration_id, p.participant_id, p.name, p.email,
               e.event_id, e.event_name, r.reg_date, r.payment_status
        FROM registrations r
        JOIN participants p ON r.participant_id = p.participant_id
        JOIN events e ON r.event_id = e.event_id
        ORDER BY r.reg_date DESC
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    for row in rows:
        if "name" in row:
            row["name"] = decrypt_value(row["name"])
        if "email" in row:
            row["email"] = decrypt_value(row["email"])

    return {"data": rows}


@app.post("/admin/api/events/add")
async def admin_add_event(
    request: Request,
    event_name: str,
    category: str,
    type: str,
    registration_fee: float,
    prize_pool: float,
    event_id: Optional[int] = None
):
    if not _verify_admin(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    a = get_a()
    cursor = a.cursor(dictionary=True)

    try:
        if event_id:
            cursor.execute("""
                INSERT INTO events
                (event_id, event_name, category, type, registration_fee, prize_pool)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, (event_id, event_name, category, type, registration_fee, prize_pool))
        else:
            cursor.execute("""
                INSERT INTO events
                (event_name, category, type, registration_fee, prize_pool)
                VALUES (%s,%s,%s,%s,%s)
            """, (event_name, category, type, registration_fee, prize_pool))

        a.commit()
        return {"message": "Event added successfully"}
    except mysql.connector.Error as err:
        return JSONResponse({"error": str(err)}, status_code=400)
    finally:
        cursor.close()
        a.close()

@app.get("/admin/api/search")
async def admin_search(request: Request, q: str = Query(""), table: str = Query("all")):
    if not _verify_admin(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    if not q.strip():
        return {"results": {"participants": [], "events": [], "registrations": []}}

    keyword = q.strip().lower()
    results = {"participants": [], "events": [], "registrations": []}

    conn = get_a()
    cursor = conn.cursor(dictionary=True)

    # Search participants
    if table in ("all", "participants"):
        cursor.execute("SELECT * FROM participants")
        for row in cursor.fetchall():
            dec = decrypt_participant(row)
            searchable = " ".join(str(v) for v in dec.values()).lower()
            if keyword in searchable:
                results["participants"].append(dec)

    # Search events
    if table in ("all", "events"):
        cursor.execute("SELECT * FROM events")
        for row in cursor.fetchall():
            searchable = " ".join(str(v) for v in row.values()).lower()
            if keyword in searchable:
                results["events"].append(row)

    # Search registrations
    if table in ("all", "registrations"):
        cursor.execute("""
            SELECT p.name, e.event_name, r.reg_date, r.payment_status
            FROM registrations r
            JOIN participants p ON r.participant_id = p.participant_id
            JOIN events e ON r.event_id = e.event_id
        """)
        for row in cursor.fetchall():
            dec_name = decrypt_value(row.get("name", ""))
            searchable = f"{dec_name} {row.get('event_name', '')} {row.get('payment_status', '')}".lower()
            if keyword in searchable:
                results["registrations"].append({
                    "name": dec_name,
                    "event_name": row["event_name"],
                    "reg_date": str(row.get("reg_date", "")),
                    "payment_status": row["payment_status"]
                })

    cursor.close()
    conn.close()

    return {"results": results}


if __name__ == "__main__":
    import uvicorn
    # In production (Render), bind to 0.0.0.0 and use the PORT environment variable.
    port = int(os.environ.get("PORT", 8000))
    # Disable reload in production
    is_dev = os.environ.get("ENVIRONMENT") != "production"
    uvicorn.run("aston:app", host="0.0.0.0", port=port, reload=is_dev)