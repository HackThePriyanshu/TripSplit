# TripSplit

TripSplit is a small full-stack expense splitter for the CodeNicely A05 assessment.

## Features

- Create a trip
- Add members
- Add expenses
- Equal split among selected members
- Paid-by member
- Balance screen: Paid, Share, Net
- Settlement suggestions
- Mark settlement as done
- Settlement updates balances
- Demo data: 5 members + 8 expenses
- Expense categories

## Run on Windows

Open terminal in this folder:

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn app:app --reload
```

Open:

http://127.0.0.1:8000

## 5-minute demo

1. Click `Load Demo`.
2. Show the 5 members.
3. Add an expense such as `Dinner`, ₹1500.
4. Select only 3 members.
5. Show the balance calculation.
6. Show settlement suggestions.
7. Click `Mark as Done`.
8. Show the updated balances.

## Project structure

```text
tripsplit/
├── app.py
├── requirements.txt
├── README.md
├── tripsplit.db        # created automatically
└── static/
    ├── index.html
    ├── style.css
    └── app.js
```
