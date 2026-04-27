"""

Usage:
    python admin_cli.py generate-key
    python admin_cli.py encrypt-db
    python admin_cli.py decrypt-db
    python admin_cli.py stats
    python admin_cli.py list participants
    python admin_cli.py list events
    python admin_cli.py list registrations
    python admin_cli.py search participants <keyword>
    python admin_cli.py search events <keyword>
    python admin_cli.py search registrations <keyword>
"""

import sys
import os
from dotenv import load_dotenv
from cryptography.fernet import Fernet, InvalidToken
import mysql.connector
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

load_dotenv()

console = Console()

# ─────────────────────────────────────────
# Database Connection
# ─────────────────────────────────────────

def get_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "cultural_fest")
    )


# ─────────────────────────────────────────
# Encryption Helpers
# ─────────────────────────────────────────

ENCRYPTED_FIELDS = ["name", "email", "phone"]


def get_fernet():
    key = os.getenv("ENCRYPTION_KEY")
    if not key:
        console.print("[bold red]✖ ENCRYPTION_KEY not set in .env[/]")
        console.print("  Run [cyan]python admin_cli.py generate-key[/] to create one.")
        sys.exit(1)
    return Fernet(key.encode())


def is_encrypted(value: str, fernet: Fernet) -> bool:
    """Check if a value is already Fernet-encrypted."""
    if not value:
        return False
    try:
        fernet.decrypt(value.encode())
        return True
    except (InvalidToken, Exception):
        return False


def encrypt_value(value: str, fernet: Fernet) -> str:
    if not value:
        return value
    return fernet.encrypt(value.encode()).decode()


def decrypt_value(value: str, fernet: Fernet) -> str:
    if not value:
        return value
    try:
        return fernet.decrypt(value.encode()).decode()
    except (InvalidToken, Exception):
        return value  # Already plaintext


# ═════════════════════════════════════════
# COMMANDS
# ═════════════════════════════════════════


def cmd_generate_key():
    """Generate a new Fernet encryption key."""
    key = Fernet.generate_key().decode()
    console.print()
    console.print(Panel(
        f"[bold green]{key}[/]",
        title="[bold][KEY] New Encryption Key Generated[/]",
        subtitle="Copy this into your .env file as ENCRYPTION_KEY",
        border_style="green",
        padding=(1, 2)
    ))
    console.print()
    console.print("[dim]WARNING: Store this key safely. If lost, encrypted data is unrecoverable.[/]")


def cmd_encrypt_db():
    """Encrypt all plaintext sensitive fields in the participants table."""
    fernet = get_fernet()
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    # Widen columns to fit Fernet-encrypted tokens (~200 chars)
    console.print("[dim]Preparing columns for encrypted data...[/]")
    cursor.execute("ALTER TABLE participants MODIFY COLUMN name VARCHAR(500)")
    cursor.execute("ALTER TABLE participants MODIFY COLUMN email VARCHAR(500)")
    cursor.execute("ALTER TABLE participants MODIFY COLUMN phone VARCHAR(500)")
    conn.commit()

    cursor.execute("SELECT participant_id, name, email, phone FROM participants")
    rows = cursor.fetchall()

    encrypted_count = 0
    skipped_count = 0

    for row in rows:
        updates = {}
        for field in ENCRYPTED_FIELDS:
            val = row.get(field, "")
            if val and not is_encrypted(val, fernet):
                updates[field] = encrypt_value(val, fernet)

        if updates:
            set_clause = ", ".join(f"{k}=%s" for k in updates.keys())
            values = list(updates.values()) + [row["participant_id"]]
            cursor.execute(
                f"UPDATE participants SET {set_clause} WHERE participant_id=%s",
                values
            )
            encrypted_count += 1
        else:
            skipped_count += 1

    conn.commit()
    cursor.close()
    conn.close()

    console.print()
    console.print(Panel(
        f"[bold green][OK] {encrypted_count} participant(s) encrypted[/]\n"
        f"[dim]{skipped_count} already encrypted -- skipped[/]",
        title="[bold][LOCKED] Database Encryption Complete[/]",
        border_style="green",
        padding=(1, 2)
    ))


def cmd_decrypt_db():
    """Decrypt all encrypted sensitive fields back to plaintext."""
    fernet = get_fernet()
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT participant_id, name, email, phone FROM participants")
    rows = cursor.fetchall()

    decrypted_count = 0
    skipped_count = 0

    for row in rows:
        updates = {}
        for field in ENCRYPTED_FIELDS:
            val = row.get(field, "")
            if val and is_encrypted(val, fernet):
                updates[field] = decrypt_value(val, fernet)

        if updates:
            set_clause = ", ".join(f"{k}=%s" for k in updates.keys())
            values = list(updates.values()) + [row["participant_id"]]
            cursor.execute(
                f"UPDATE participants SET {set_clause} WHERE participant_id=%s",
                values
            )
            decrypted_count += 1
        else:
            skipped_count += 1

    conn.commit()
    cursor.close()
    conn.close()

    console.print()
    console.print(Panel(
        f"[bold yellow][OK] {decrypted_count} participant(s) decrypted[/]\n"
        f"[dim]{skipped_count} already plaintext -- skipped[/]",
        title="[bold][UNLOCKED] Database Decryption Complete[/]",
        border_style="yellow",
        padding=(1, 2)
    ))


def cmd_stats():
    """Show database statistics."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT COUNT(*) as c FROM participants")
    p_count = cursor.fetchone()["c"]

    cursor.execute("SELECT COUNT(*) as c FROM events")
    e_count = cursor.fetchone()["c"]

    cursor.execute("SELECT COUNT(*) as c FROM registrations")
    r_count = cursor.fetchone()["c"]

    # Check encryption status
    fernet = None
    key = os.getenv("ENCRYPTION_KEY")
    if key:
        fernet = Fernet(key.encode())

    enc_status = "[dim]No key set[/]"
    if fernet and p_count > 0:
        cursor.execute("SELECT name FROM participants LIMIT 1")
        sample = cursor.fetchone()
        if sample and is_encrypted(sample["name"], fernet):
            enc_status = "[bold green]ENCRYPTED[/]"
        else:
            enc_status = "[bold yellow]PLAINTEXT[/]"
    elif fernet and p_count == 0:
        enc_status = "[dim]No data to check[/]"

    cursor.close()
    conn.close()

    table = Table(
        title="Cultural Fest Database Statistics",
        box=box.DOUBLE_EDGE,
        title_style="bold cyan",
        border_style="cyan"
    )
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    table.add_row("[P] Participants", str(p_count))
    table.add_row("[E] Events", str(e_count))
    table.add_row("[R] Registrations", str(r_count))
    table.add_row("[*] Encryption Status", enc_status)

    console.print()
    console.print(table)
    console.print()


def cmd_list_participants():
    """List all participants with decrypted data."""
    fernet = get_fernet()
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM participants ORDER BY participant_id")
    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    if not rows:
        console.print("\n[dim]No participants found.[/]\n")
        return

    table = Table(
        title="Participant Registry",
        box=box.ROUNDED,
        title_style="bold magenta",
        border_style="magenta",
        show_lines=True
    )
    table.add_column("ID", style="dim", justify="center")
    table.add_column("Name", style="bold")
    table.add_column("College")
    table.add_column("Department")
    table.add_column("Year", justify="center")
    table.add_column("Phone")
    table.add_column("Email", style="cyan")

    for row in rows:
        name = decrypt_value(str(row.get("name", "")), fernet)
        email = decrypt_value(str(row.get("email", "")), fernet)
        phone = decrypt_value(str(row.get("phone", "")), fernet)

        table.add_row(
            str(row.get("participant_id", "")),
            name,
            str(row.get("college", "")),
            str(row.get("department", "")),
            str(row.get("year", "")),
            phone,
            email
        )

    console.print()
    console.print(table)
    console.print(f"\n[dim]Total: {len(rows)} participant(s)[/]\n")


def cmd_list_events():
    """List all events."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM events ORDER BY event_id")
    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    if not rows:
        console.print("\n[dim]No events found.[/]\n")
        return

    table = Table(
        title="Event Catalogue",
        box=box.ROUNDED,
        title_style="bold blue",
        border_style="blue",
        show_lines=True
    )
    table.add_column("ID", style="dim", justify="center")
    table.add_column("Event Name", style="bold")
    table.add_column("Category")
    table.add_column("Type")
    table.add_column("Fee (₹)", justify="right", style="green")
    table.add_column("Prize (₹)", justify="right", style="yellow")

    for row in rows:
        table.add_row(
            str(row.get("event_id", "")),
            str(row.get("event_name", "")),
            str(row.get("category", "")),
            str(row.get("type", "")),
            str(row.get("registration_fee", "")),
            str(row.get("prize_pool", ""))
        )

    console.print()
    console.print(table)
    console.print(f"\n[dim]Total: {len(rows)} event(s)[/]\n")


def cmd_list_registrations():
    """List all registrations with joins."""
    fernet = get_fernet()
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT p.name, e.event_name, r.reg_date, r.payment_status
        FROM registrations r
        JOIN participants p ON r.participant_id = p.participant_id
        JOIN events e ON r.event_id = e.event_id
        ORDER BY r.reg_date DESC
    """)
    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    if not rows:
        console.print("\n[dim]No registrations found.[/]\n")
        return

    table = Table(
        title="Event Enrollment Ledger",
        box=box.ROUNDED,
        title_style="bold green",
        border_style="green",
        show_lines=True
    )
    table.add_column("Participant", style="bold")
    table.add_column("Event")
    table.add_column("Date", justify="center")
    table.add_column("Payment", justify="center")

    for row in rows:
        name = decrypt_value(str(row.get("name", "")), fernet)
        status = str(row.get("payment_status", ""))
        status_style = "bold green" if status.lower() == "paid" else "bold red"

        table.add_row(
            name,
            str(row.get("event_name", "")),
            str(row.get("reg_date", "")),
            Text(status, style=status_style)
        )

    console.print()
    console.print(table)
    console.print(f"\n[dim]Total: {len(rows)} registration(s)[/]\n")


def cmd_search_participants(keyword: str):
    """Search participants by keyword across all fields (decrypted)."""
    fernet = get_fernet()
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM participants")
    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    keyword_lower = keyword.lower()
    matches = []

    for row in rows:
        decrypted = {
            "participant_id": row.get("participant_id", ""),
            "name": decrypt_value(str(row.get("name", "")), fernet),
            "college": str(row.get("college", "")),
            "department": str(row.get("department", "")),
            "year": str(row.get("year", "")),
            "phone": decrypt_value(str(row.get("phone", "")), fernet),
            "email": decrypt_value(str(row.get("email", "")), fernet),
        }

        searchable = " ".join(str(v) for v in decrypted.values()).lower()
        if keyword_lower in searchable:
            matches.append(decrypted)

    if not matches:
        console.print(f"\n[dim]No participants matching '{keyword}'.[/]\n")
        return

    table = Table(
        title=f"Search Results: '{keyword}' in Participants",
        box=box.ROUNDED,
        title_style="bold magenta",
        border_style="magenta",
        show_lines=True
    )
    table.add_column("ID", style="dim", justify="center")
    table.add_column("Name", style="bold")
    table.add_column("College")
    table.add_column("Department")
    table.add_column("Year", justify="center")
    table.add_column("Phone")
    table.add_column("Email", style="cyan")

    for m in matches:
        table.add_row(
            str(m["participant_id"]),
            m["name"],
            m["college"],
            m["department"],
            m["year"],
            m["phone"],
            m["email"]
        )

    console.print()
    console.print(table)
    console.print(f"\n[dim]{len(matches)} match(es) found.[/]\n")


def cmd_search_events(keyword: str):
    """Search events by keyword."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM events")
    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    keyword_lower = keyword.lower()
    matches = []

    for row in rows:
        searchable = " ".join(str(v) for v in row.values()).lower()
        if keyword_lower in searchable:
            matches.append(row)

    if not matches:
        console.print(f"\n[dim]No events matching '{keyword}'.[/]\n")
        return

    table = Table(
        title=f"Search Results: '{keyword}' in Events",
        box=box.ROUNDED,
        title_style="bold blue",
        border_style="blue",
        show_lines=True
    )
    table.add_column("ID", style="dim", justify="center")
    table.add_column("Event Name", style="bold")
    table.add_column("Category")
    table.add_column("Type")
    table.add_column("Fee (₹)", justify="right", style="green")
    table.add_column("Prize (₹)", justify="right", style="yellow")

    for m in matches:
        table.add_row(
            str(m.get("event_id", "")),
            str(m.get("event_name", "")),
            str(m.get("category", "")),
            str(m.get("type", "")),
            str(m.get("registration_fee", "")),
            str(m.get("prize_pool", ""))
        )

    console.print()
    console.print(table)
    console.print(f"\n[dim]{len(matches)} match(es) found.[/]\n")


def cmd_search_registrations(keyword: str):
    """Search registrations by keyword."""
    fernet = get_fernet()
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT p.name, e.event_name, r.reg_date, r.payment_status
        FROM registrations r
        JOIN participants p ON r.participant_id = p.participant_id
        JOIN events e ON r.event_id = e.event_id
    """)
    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    keyword_lower = keyword.lower()
    matches = []

    for row in rows:
        decrypted_name = decrypt_value(str(row.get("name", "")), fernet)
        searchable = f"{decrypted_name} {row.get('event_name', '')} {row.get('payment_status', '')}".lower()
        if keyword_lower in searchable:
            matches.append({
                "name": decrypted_name,
                "event_name": row.get("event_name", ""),
                "reg_date": str(row.get("reg_date", "")),
                "payment_status": row.get("payment_status", "")
            })

    if not matches:
        console.print(f"\n[dim]No registrations matching '{keyword}'.[/]\n")
        return

    table = Table(
        title=f"Search Results: '{keyword}' in Registrations",
        box=box.ROUNDED,
        title_style="bold green",
        border_style="green",
        show_lines=True
    )
    table.add_column("Participant", style="bold")
    table.add_column("Event")
    table.add_column("Date", justify="center")
    table.add_column("Payment", justify="center")

    for m in matches:
        status = m["payment_status"]
        status_style = "bold green" if status.lower() == "paid" else "bold red"
        table.add_row(
            m["name"],
            m["event_name"],
            m["reg_date"],
            Text(status, style=status_style)
        )

    console.print()
    console.print(table)
    console.print(f"\n[dim]{len(matches)} match(es) found.[/]\n")


# ═════════════════════════════════════════
# MAIN — CLI Entry Point
# ═════════════════════════════════════════

HELP_TEXT = """
[bold cyan]Cultural Fest — CLI Admin Tool[/]

[bold]Usage:[/]
  python admin_cli.py [green]<command>[/] [dim][args][/]

[bold]Commands:[/]
  [green]generate-key[/]                      Generate a new encryption key
  [green]encrypt-db[/]                        Encrypt all plaintext participant data
  [green]decrypt-db[/]                        Decrypt all participant data to plaintext
  [green]stats[/]                             Show database statistics
  [green]list[/] [cyan]participants|events|registrations[/]    List all records
  [green]search[/] [cyan]participants|events|registrations[/] [yellow]<keyword>[/]   Search records

[bold]Examples:[/]
  python admin_cli.py generate-key
  python admin_cli.py encrypt-db
  python admin_cli.py stats
  python admin_cli.py list participants
  python admin_cli.py search participants aston
  python admin_cli.py search events dance
"""


def main():
    args = sys.argv[1:]

    if not args:
        console.print(HELP_TEXT)
        return

    command = args[0].lower()

    if command == "generate-key":
        cmd_generate_key()

    elif command == "encrypt-db":
        cmd_encrypt_db()

    elif command == "decrypt-db":
        cmd_decrypt_db()

    elif command == "stats":
        cmd_stats()

    elif command == "list":
        if len(args) < 2:
            console.print("[red]Specify what to list: participants, events, or registrations[/]")
            return
        target = args[1].lower()
        if target == "participants":
            cmd_list_participants()
        elif target == "events":
            cmd_list_events()
        elif target == "registrations":
            cmd_list_registrations()
        else:
            console.print(f"[red]Unknown list target: {target}[/]")

    elif command == "search":
        if len(args) < 3:
            console.print("[red]Usage: python admin_cli.py search <participants|events|registrations> <keyword>[/]")
            return
        target = args[1].lower()
        keyword = " ".join(args[2:])
        if target == "participants":
            cmd_search_participants(keyword)
        elif target == "events":
            cmd_search_events(keyword)
        elif target == "registrations":
            cmd_search_registrations(keyword)
        else:
            console.print(f"[red]Unknown search target: {target}[/]")

    else:
        console.print(f"[red]Unknown command: {command}[/]")
        console.print(HELP_TEXT)


if __name__ == "__main__":
    main()
