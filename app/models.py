from datetime import datetime, date
from decimal import Decimal
from typing import Optional

from flask_login import UserMixin
from sqlalchemy import Numeric
from werkzeug.security import generate_password_hash, check_password_hash

from . import db, login_manager


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    receipts = db.relationship("Receipt", back_populates="user", cascade="all, delete-orphan")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Receipt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    purchase_date = db.Column(db.Date, nullable=False, default=date.today)
    store_name = db.Column(db.String(255), nullable=False)
    amount = db.Column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    category = db.Column(db.String(120), nullable=False)
    items = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    image_filename = db.Column(db.String(255), nullable=True)
    ai_summary = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("User", back_populates="receipts")

    def update_from_dict(self, data: dict) -> None:
        for field in ("purchase_date", "store_name", "amount", "category", "items", "notes"):
            if field in data and data[field] is not None:
                setattr(self, field, data[field])


@login_manager.user_loader
def load_user(user_id: str) -> Optional[User]:
    if user_id is None:
        return None
    return User.query.get(int(user_id))
