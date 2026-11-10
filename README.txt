# FinTrack

## Deploy to Render
1. Upload `app.py`, `requirements.txt`, and `render.yaml` to the root of your GitHub repository.
2. In Render, create a Blueprint from this repository (recommended) so Render creates the PostgreSQL database and web service.
3. If configuring manually, create a PostgreSQL database and set `DATABASE_URL` on the web service to its Internal Database URL.
4. Set `SECRET_KEY` to a long random secret (or let Render generate it).
5. Build command: `pip install -r requirements.txt`
6. Start command: `gunicorn app:app`

## Features
- Individual user accounts and password hashing
- Default UZS and USD balances for every new user
- Additional wallets in UZS, USD, EUR, RUB, KZT, TRY, SAR, AED
- Income, expense and same-currency transfers
- Balance-specific transaction history and filters
- Savings goals tracked separately from account balances
- CSRF protection on forms
- PostgreSQL on Render; SQLite fallback for local development

Important: balances in different currencies are deliberately not combined into one total. No exchange rate is guessed or applied. Cross-currency exchange is not implemented as a transfer.
