from __future__ import annotations

import argparse

from app.db.session import SessionLocal
from app.models.entities import User
from app.security import get_password_hash
from app.services.auth_service import normalize_email, validate_password_strength


def main() -> None:
    parser = argparse.ArgumentParser(description="Crear o actualizar usuario para login")
    parser.add_argument("--email", required=True)
    parser.add_argument("--full-name", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--inactive", action="store_true")
    args = parser.parse_args()

    email = normalize_email(args.email)
    validate_password_strength(args.password)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        hashed = get_password_hash(args.password)
        if user is None:
            user = User(
                email=email,
                full_name=args.full_name,
                hashed_password=hashed,
                is_active=not args.inactive,
            )
            db.add(user)
        else:
            user.full_name = args.full_name
            user.hashed_password = hashed
            user.is_active = not args.inactive
            db.add(user)
        db.commit()
        print(f"Usuario listo: {email}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
