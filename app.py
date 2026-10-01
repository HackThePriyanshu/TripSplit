from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import List, Optional
import sqlite3
from pathlib import Path
from contextlib import closing

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "tripsplit.db"

app = FastAPI(title="TripSplit", version="1.0.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with closing(get_db()) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS trips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            FOREIGN KEY (trip_id) REFERENCES trips(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            amount REAL NOT NULL CHECK(amount > 0),
            paid_by INTEGER NOT NULL,
            category TEXT DEFAULT 'Other',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (trip_id) REFERENCES trips(id) ON DELETE CASCADE,
            FOREIGN KEY (paid_by) REFERENCES members(id)
        );

        CREATE TABLE IF NOT EXISTS expense_splits (
            expense_id INTEGER NOT NULL,
            member_id INTEGER NOT NULL,
            share REAL NOT NULL CHECK(share >= 0),
            PRIMARY KEY (expense_id, member_id),
            FOREIGN KEY (expense_id) REFERENCES expenses(id) ON DELETE CASCADE,
            FOREIGN KEY (member_id) REFERENCES members(id)
        );

        CREATE TABLE IF NOT EXISTS settlements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id INTEGER NOT NULL,
            from_member INTEGER NOT NULL,
            to_member INTEGER NOT NULL,
            amount REAL NOT NULL CHECK(amount > 0),
            done INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (trip_id) REFERENCES trips(id) ON DELETE CASCADE,
            FOREIGN KEY (from_member) REFERENCES members(id),
            FOREIGN KEY (to_member) REFERENCES members(id)
        );
        """)
        db.commit()


init_db()


class TripCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class MemberCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ExpenseCreate(BaseModel):
    description: str = Field(min_length=1, max_length=200)
    amount: float = Field(gt=0)
    paid_by: int
    member_ids: List[int]
    category: str = "Other"


class SettlementCreate(BaseModel):
    from_member: int
    to_member: int
    amount: float = Field(gt=0)


def trip_exists(db, trip_id):
    row = db.execute("SELECT id FROM trips WHERE id=?", (trip_id,)).fetchone()
    return row is not None


def member_belongs(db, trip_id, member_id):
    row = db.execute(
        "SELECT id FROM members WHERE id=? AND trip_id=?",
        (member_id, trip_id)
    ).fetchone()
    return row is not None


def get_balances(db, trip_id):
    members = db.execute(
        "SELECT id, name FROM members WHERE trip_id=? ORDER BY id",
        (trip_id,)
    ).fetchall()

    balances = {
        m["id"]: {"member_id": m["id"], "name": m["name"], "paid": 0.0, "share": 0.0}
        for m in members
    }

    expenses = db.execute("""
        SELECT id, amount, paid_by
        FROM expenses
        WHERE trip_id=?
    """, (trip_id,)).fetchall()

    for e in expenses:
        balances[e["paid_by"]]["paid"] += e["amount"]

        splits = db.execute("""
            SELECT member_id, share
            FROM expense_splits
            WHERE expense_id=?
        """, (e["id"],)).fetchall()

        for s in splits:
            balances[s["member_id"]]["share"] += s["share"]

    # A completed settlement changes the net position:
    # payer moves toward zero; receiver moves toward zero.
    settlements = db.execute("""
        SELECT from_member, to_member, amount
        FROM settlements
        WHERE trip_id=? AND done=1
    """, (trip_id,)).fetchall()

    for s in settlements:
        balances[s["from_member"]]["paid"] += s["amount"]
        balances[s["to_member"]]["paid"] -= s["amount"]

    result = []
    for b in balances.values():
        net = round(b["paid"] - b["share"], 2)
        result.append({
            "member_id": b["member_id"],
            "name": b["name"],
            "paid": round(b["paid"], 2),
            "share": round(b["share"], 2),
            "net": net
        })
    return result


def calculate_settlements(balance_rows):
    # Greedy matching of creditors and debtors.
    # For ordinary expense splitting this gives a minimum number
    # of transfers for the current positive/negative balances.
    creditors = [
        {"member_id": b["member_id"], "name": b["name"], "amount": round(b["net"], 2)}
        for b in balance_rows if b["net"] > 0.009
    ]
    debtors = [
        {"member_id": b["member_id"], "name": b["name"], "amount": round(-b["net"], 2)}
        for b in balance_rows if b["net"] < -0.009
    ]

    i = j = 0
    result = []

    while i < len(debtors) and j < len(creditors):
        pay = round(min(debtors[i]["amount"], creditors[j]["amount"]), 2)

        result.append({
            "from_member": debtors[i]["member_id"],
            "from_name": debtors[i]["name"],
            "to_member": creditors[j]["member_id"],
            "to_name": creditors[j]["name"],
            "amount": pay
        })

        debtors[i]["amount"] = round(debtors[i]["amount"] - pay, 2)
        creditors[j]["amount"] = round(creditors[j]["amount"] - pay, 2)

        if debtors[i]["amount"] <= 0.009:
            i += 1
        if creditors[j]["amount"] <= 0.009:
            j += 1

    return result


@app.get("/")
def home():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.post("/api/trips")
def create_trip(data: TripCreate):
    with closing(get_db()) as db:
        cur = db.execute("INSERT INTO trips(name) VALUES(?)", (data.name.strip(),))
        db.commit()
        return {"id": cur.lastrowid, "name": data.name.strip()}


@app.get("/api/trips")
def list_trips():
    with closing(get_db()) as db:
        rows = db.execute(
            "SELECT id, name FROM trips ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


@app.post("/api/trips/{trip_id}/members")
def add_member(trip_id: int, data: MemberCreate):
    with closing(get_db()) as db:
        if not trip_exists(db, trip_id):
            raise HTTPException(404, "Trip not found")

        name = data.name.strip()
        if not name:
            raise HTTPException(400, "Member name is required")

        cur = db.execute(
            "INSERT INTO members(trip_id, name) VALUES(?, ?)",
            (trip_id, name)
        )
        db.commit()
        return {"id": cur.lastrowid, "trip_id": trip_id, "name": name}


@app.get("/api/trips/{trip_id}")
def get_trip(trip_id: int):
    with closing(get_db()) as db:
        trip = db.execute(
            "SELECT id, name FROM trips WHERE id=?", (trip_id,)
        ).fetchone()

        if not trip:
            raise HTTPException(404, "Trip not found")

        members = db.execute("""
            SELECT id, name FROM members
            WHERE trip_id=? ORDER BY id
        """, (trip_id,)).fetchall()

        expenses = db.execute("""
            SELECT e.id, e.description, e.amount, e.category,
                   e.paid_by, m.name AS paid_by_name
            FROM expenses e
            JOIN members m ON m.id=e.paid_by
            WHERE e.trip_id=?
            ORDER BY e.id DESC
        """, (trip_id,)).fetchall()

        expense_list = []
        for e in expenses:
            splits = db.execute("""
                SELECT es.member_id, m.name, es.share
                FROM expense_splits es
                JOIN members m ON m.id=es.member_id
                WHERE es.expense_id=?
            """, (e["id"],)).fetchall()

            expense_list.append({
                "id": e["id"],
                "description": e["description"],
                "amount": round(e["amount"], 2),
                "category": e["category"],
                "paid_by": e["paid_by"],
                "paid_by_name": e["paid_by_name"],
                "splits": [
                    {
                        "member_id": s["member_id"],
                        "name": s["name"],
                        "share": round(s["share"], 2)
                    }
                    for s in splits
                ]
            })

        balances = get_balances(db, trip_id)
        settlements = calculate_settlements(balances)

        done = db.execute("""
            SELECT s.id, s.amount,
                   fm.name AS from_name,
                   tm.name AS to_name
            FROM settlements s
            JOIN members fm ON fm.id=s.from_member
            JOIN members tm ON tm.id=s.to_member
            WHERE s.trip_id=? AND s.done=1
            ORDER BY s.id DESC
        """, (trip_id,)).fetchall()

        return {
            "trip": dict(trip),
            "members": [dict(m) for m in members],
            "expenses": expense_list,
            "balances": balances,
            "settlements": settlements,
            "completed_settlements": [dict(x) for x in done]
        }


@app.post("/api/trips/{trip_id}/expenses")
def add_expense(trip_id: int, data: ExpenseCreate):
    with closing(get_db()) as db:
        if not trip_exists(db, trip_id):
            raise HTTPException(404, "Trip not found")

        member_ids = list(dict.fromkeys(data.member_ids))
        if not member_ids:
            raise HTTPException(400, "Select at least one member")

        if not member_belongs(db, trip_id, data.paid_by):
            raise HTTPException(400, "Paid-by member does not belong to this trip")

        for member_id in member_ids:
            if not member_belongs(db, trip_id, member_id):
                raise HTTPException(400, "One or more split members are invalid")

        share = round(data.amount / len(member_ids), 2)

        # Fix rounding difference so shares add exactly to the expense amount.
        shares = [share] * len(member_ids)
        difference = round(data.amount - sum(shares), 2)
        shares[-1] = round(shares[-1] + difference, 2)

        cur = db.execute("""
            INSERT INTO expenses(trip_id, description, amount, paid_by, category)
            VALUES(?, ?, ?, ?, ?)
        """, (
            trip_id,
            data.description.strip(),
            data.amount,
            data.paid_by,
            data.category
        ))
        expense_id = cur.lastrowid

        db.executemany("""
            INSERT INTO expense_splits(expense_id, member_id, share)
            VALUES(?, ?, ?)
        """, [
            (expense_id, member_id, shares[i])
            for i, member_id in enumerate(member_ids)
        ])

        db.commit()

        return {
            "id": expense_id,
            "description": data.description.strip(),
            "amount": data.amount,
            "share": share,
            "member_ids": member_ids
        }


@app.post("/api/trips/{trip_id}/settlements")
def complete_settlement(trip_id: int, data: SettlementCreate):
    with closing(get_db()) as db:
        if not trip_exists(db, trip_id):
            raise HTTPException(404, "Trip not found")

        if data.from_member == data.to_member:
            raise HTTPException(400, "Payer and receiver must be different")

        if not member_belongs(db, trip_id, data.from_member):
            raise HTTPException(400, "Payer is not a member of this trip")

        if not member_belongs(db, trip_id, data.to_member):
            raise HTTPException(400, "Receiver is not a member of this trip")

        balances = get_balances(db, trip_id)
        suggestions = calculate_settlements(balances)

        # Only allow completing a currently suggested transaction.
        matching = None
        for s in suggestions:
            if (
                s["from_member"] == data.from_member
                and s["to_member"] == data.to_member
                and abs(s["amount"] - data.amount) <= 0.01
            ):
                matching = s
                break

        if matching is None:
            raise HTTPException(
                400,
                "This payment does not match the current settlement suggestion"
            )

        db.execute("""
            INSERT INTO settlements(trip_id, from_member, to_member, amount, done)
            VALUES(?, ?, ?, ?, 1)
        """, (
            trip_id,
            data.from_member,
            data.to_member,
            data.amount
        ))
        db.commit()

        return {"message": "Settlement marked as done"}


@app.post("/api/demo")
def seed_demo():
    """Creates one demo trip with 5 members and 8 expenses."""
    with closing(get_db()) as db:
        cur = db.execute("INSERT INTO trips(name) VALUES(?)", ("Goa Trip Demo",))
        trip_id = cur.lastrowid

        names = ["Rahul", "Priya", "Amit", "Neha", "Rohit"]
        member_ids = {}
        for name in names:
            c = db.execute(
                "INSERT INTO members(trip_id, name) VALUES(?, ?)",
                (trip_id, name)
            )
            member_ids[name] = c.lastrowid

        expenses = [
            ("Hotel", 5000, "Rahul", ["Rahul", "Priya", "Amit", "Neha", "Rohit"], "Stay"),
            ("Dinner", 1500, "Rahul", ["Rahul", "Priya", "Amit"], "Food"),
            ("Cab", 1200, "Amit", ["Rahul", "Amit", "Neha"], "Travel"),
            ("Breakfast", 600, "Priya", ["Priya", "Amit", "Neha", "Rohit"], "Food"),
            ("Tickets", 2500, "Neha", ["Rahul", "Priya", "Neha", "Rohit"], "Travel"),
            ("Lunch", 1800, "Rohit", ["Rahul", "Priya", "Amit", "Neha", "Rohit"], "Food"),
            ("Taxi", 900, "Priya", ["Priya", "Neha", "Rohit"], "Travel"),
            ("Snacks", 500, "Amit", ["Rahul", "Amit", "Rohit"], "Food"),
        ]

        for desc, amount, paid_name, split_names, category in expenses:
            c = db.execute("""
                INSERT INTO expenses(trip_id, description, amount, paid_by, category)
                VALUES(?, ?, ?, ?, ?)
            """, (
                trip_id,
                desc,
                amount,
                member_ids[paid_name],
                category
            ))
            expense_id = c.lastrowid
            base = round(amount / len(split_names), 2)
            shares = [base] * len(split_names)
            shares[-1] = round(amount - sum(shares[:-1]), 2)

            for i, name in enumerate(split_names):
                db.execute("""
                    INSERT INTO expense_splits(expense_id, member_id, share)
                    VALUES(?, ?, ?)
                """, (expense_id, member_ids[name], shares[i]))

        db.commit()
        return {"trip_id": trip_id, "message": "Demo trip created"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
