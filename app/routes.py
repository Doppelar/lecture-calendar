import os
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.utils import secure_filename

from . import db
from .ai.receipt_parser import parse_receipt
from .models import Receipt, User


ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "txt", "pdf"}
DEFAULT_CATEGORIES = [
    "food",
    "transport",
    "utilities",
    "shopping",
    "entertainment",
    "health",
    "other",
]


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


auth_bp = Blueprint("auth", __name__)
main_bp = Blueprint("main", __name__)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not email or not password:
            flash("メールアドレスとパスワードは必須です。", "danger")
        elif password != confirm:
            flash("パスワードが一致しません。", "danger")
        elif User.query.filter_by(email=email).first():
            flash("このメールアドレスは既に登録されています。", "danger")
        else:
            user = User(email=email)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash("登録が完了しました。ログインしてください。", "success")
            return redirect(url_for("auth.login"))

    return render_template("register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for("main.dashboard"))
        flash("ログイン情報が正しくありません。", "danger")

    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("ログアウトしました。", "info")
    return redirect(url_for("auth.login"))


@main_bp.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return redirect(url_for("auth.login"))


@main_bp.route("/dashboard")
@login_required
def dashboard():
    receipts = (
        Receipt.query.filter_by(user_id=current_user.id)
        .order_by(Receipt.purchase_date.desc())
        .all()
    )

    total = sum((receipt.amount or Decimal("0")) for receipt in receipts)

    totals_by_category = {}
    for receipt in receipts:
        cat = receipt.category or "other"
        totals_by_category.setdefault(cat, Decimal("0"))
        totals_by_category[cat] += receipt.amount or Decimal("0")

    return render_template(
        "dashboard.html",
        receipts=receipts,
        total=total,
        totals_by_category=totals_by_category,
    )


@main_bp.route("/receipts/new", methods=["GET", "POST"])
@login_required
def add_receipt():
    ai_result = None
    if request.method == "POST":
        upload = request.files.get("receipt_image")
        filename = None
        if upload and upload.filename:
            if allowed_file(upload.filename):
                original_name = secure_filename(upload.filename)
                name, ext = os.path.splitext(original_name)
                timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
                filename = f"{timestamp}_{name}{ext}"
                upload_path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
                upload.save(upload_path)
                ai_result = parse_receipt(upload_path)
            else:
                flash("対応していないファイル形式です。", "danger")
                return render_template(
                    "add_receipt.html",
                    categories=DEFAULT_CATEGORIES,
                    ai_result=ai_result,
                    form_data=request.form,
                )
        else:
            upload_path = None

        purchase_date_str = request.form.get("purchase_date") or (
            ai_result.get("purchase_date") if ai_result else None
        )
        store_name = request.form.get("store_name") or (
            ai_result.get("store_name") if ai_result else None
        )
        if store_name:
            store_name = store_name.strip()
        amount_str = request.form.get("amount") or (ai_result.get("amount") if ai_result else None)
        category = request.form.get("category") or (
            ai_result.get("category") if ai_result else "other"
        )
        if isinstance(category, str):
            category = category.strip() or "other"
        items = request.form.get("items") or (ai_result.get("items") if ai_result else None)
        if isinstance(items, str):
            items = items.strip() or None
        notes = request.form.get("notes") or None
        if isinstance(notes, str):
            notes = notes.strip() or None

        errors = []

        if not purchase_date_str:
            errors.append("購入日の入力または認識が必要です。")
        if not store_name:
            errors.append("お店の名称は必須です。")
        if not amount_str:
            errors.append("金額を入力するか認識結果を利用してください。")

        if errors:
            for message in errors:
                flash(message, "danger")
            return render_template(
                "add_receipt.html",
                categories=DEFAULT_CATEGORIES,
                ai_result=ai_result,
                form_data=request.form,
            )

        cleaned_amount = amount_str.replace(",", "") if isinstance(amount_str, str) else amount_str
        if isinstance(cleaned_amount, str):
            cleaned_amount = cleaned_amount.replace("¥", "")
        try:
            amount = Decimal(cleaned_amount)
        except (InvalidOperation, AttributeError):
            flash("金額の形式が正しくありません。", "danger")
            return render_template(
                "add_receipt.html",
                categories=DEFAULT_CATEGORIES,
                ai_result=ai_result,
                form_data=request.form,
            )

        try:
            purchase_date = datetime.strptime(purchase_date_str, "%Y-%m-%d").date()
        except ValueError:
            flash("日付の形式はYYYY-MM-DDで入力してください。", "danger")
            return render_template(
                "add_receipt.html",
                categories=DEFAULT_CATEGORIES,
                ai_result=ai_result,
                form_data=request.form,
            )

        receipt = Receipt(
            user_id=current_user.id,
            purchase_date=purchase_date,
            store_name=store_name,
            amount=amount,
            category=category,
            items=items,
            notes=notes,
            image_filename=filename,
            ai_summary=(ai_result.get("ai_summary") if ai_result else None),
        )

        db.session.add(receipt)
        db.session.commit()
        flash("レシートを登録しました。", "success")
        return redirect(url_for("main.dashboard"))

    return render_template(
        "add_receipt.html",
        categories=DEFAULT_CATEGORIES,
        ai_result=ai_result,
        form_data=None,
    )


@main_bp.route("/receipts/<int:receipt_id>/edit", methods=["GET", "POST"])
@login_required
def edit_receipt(receipt_id: int):
    receipt = Receipt.query.filter_by(id=receipt_id, user_id=current_user.id).first_or_404()

    if request.method == "POST":
        purchase_date_str = request.form.get("purchase_date")
        store_name = (request.form.get("store_name") or "").strip()
        amount_str = request.form.get("amount")
        category = (request.form.get("category") or "other").strip()
        items_raw = request.form.get("items")
        notes_raw = request.form.get("notes")
        items = items_raw.strip() if items_raw else None
        notes = notes_raw.strip() if notes_raw else None

        try:
            purchase_date = datetime.strptime(purchase_date_str, "%Y-%m-%d").date()
        except ValueError:
            flash("日付の形式はYYYY-MM-DDで入力してください。", "danger")
            return render_template(
                "edit_receipt.html",
                receipt=receipt,
                categories=DEFAULT_CATEGORIES,
            )

        cleaned_amount = amount_str.replace(",", "") if isinstance(amount_str, str) else amount_str
        if isinstance(cleaned_amount, str):
            cleaned_amount = cleaned_amount.replace("¥", "")
        try:
            amount = Decimal(cleaned_amount)
        except (InvalidOperation, AttributeError):
            flash("金額の形式が正しくありません。", "danger")
            return render_template(
                "edit_receipt.html",
                receipt=receipt,
                categories=DEFAULT_CATEGORIES,
            )

        receipt.update_from_dict(
            {
                "purchase_date": purchase_date,
                "store_name": store_name,
                "amount": amount,
                "category": category,
                "items": items,
                "notes": notes,
            }
        )
        db.session.commit()
        flash("レシート情報を更新しました。", "success")
        return redirect(url_for("main.dashboard"))

    return render_template(
        "edit_receipt.html",
        receipt=receipt,
        categories=DEFAULT_CATEGORIES,
    )


@main_bp.route("/uploads/<filename>")
@login_required
def uploaded_file(filename: str):
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename)
