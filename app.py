import datetime
import io
import os
import random
from functools import wraps
from pathlib import Path

import click
from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   send_file, session, url_for)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from sqlalchemy.orm import joinedload
from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///inventory.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = "change-me"
app.config["UPLOAD_FOLDER"] = str(Path(__file__).resolve().parent / "static" / "uploads")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

db = SQLAlchemy(app)

ADMIN_ROLES = {"admin", "procurement_manager"}
MANAGER_ROLES = ADMIN_ROLES | {"manager"}
PROCUREMENT_APPROVER_ROLES = {"procurement_manager", "admin"}
ROLE_LABELS = {
    "admin": "Admin",
    "procurement_manager": "Satınalma Yöneticisi",
    "manager": "Yönetici",
    "user": "Kullanıcı",
}
ROLE_CHOICES = [
    ("user", ROLE_LABELS["user"]),
    ("manager", ROLE_LABELS["manager"]),
    ("procurement_manager", ROLE_LABELS["procurement_manager"]),
    ("admin", ROLE_LABELS["admin"]),
]

STATUS_LABELS = {
    "pending": "1. onay bekliyor",
    "pending_procurement": "1. onay bekliyor",
    "pending_manager": "2. onay bekliyor",
    "approved": "onaylandı",
    "rejected": "reddedildi",
    "tamamlandı": "tamamlandı",
}

TURKISH_ASCII_MAP = str.maketrans(
    {
        "ç": "c",
        "Ç": "C",
        "ş": "s",
        "Ş": "S",
        "İ": "I",
        "ı": "i",
        "ö": "o",
        "Ö": "O",
        "ü": "u",
        "Ü": "U",
        "ğ": "g",
        "Ğ": "G",
    }
)

APP_TIMEZONE = datetime.timezone(datetime.timedelta(hours=3))


def to_local_datetime(value: datetime.datetime | None) -> datetime.datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(APP_TIMEZONE)


def format_decimal_value(value, places: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    formatted = f"{number:,.{places}f}"
    formatted = formatted.replace(",", "¬").replace(".", ",").replace("¬", ".")
    return formatted


def local_today() -> datetime.date:
    return datetime.datetime.now(APP_TIMEZONE).date()


def format_local_datetime(value, fmt: str = "%d.%m.%Y %H:%M") -> str:
    localized = to_local_datetime(value)
    if localized is None:
        return "-"
    return localized.strftime(fmt)


def normalize_turkish_ascii(value: str | None, default: str = "-") -> str:
    if value is None:
        return default
    return str(value).translate(TURKISH_ASCII_MAP)


@app.template_filter("status_label")
def status_label_filter(value: str | None) -> str:
    if not value:
        return "-"
    normalized = value.lower()
    return STATUS_LABELS.get(normalized, value)


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


@app.template_filter("decimal")
def decimal_filter(value, places: int = 2) -> str:
    if value in ("", None):
        return "-"
    return format_decimal_value(value, places)


@app.template_filter("local_datetime")
def local_datetime_filter(value, fmt: str = "%d.%m.%Y %H:%M") -> str:
    return format_local_datetime(value, fmt)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(255), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="user")
    manager_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)

    manager = db.relationship("User", remote_side=[id], uselist=False)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self) -> bool:
        return self.role in ADMIN_ROLES

    @property
    def is_manager(self) -> bool:
        return self.role in MANAGER_ROLES


class Warehouse(db.Model):
    __tablename__ = "warehouses"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)


class Project(db.Model):
    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    location = db.Column(db.String(255), nullable=True)
    manager_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    manager = db.relationship("User", foreign_keys=[manager_id])


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)


class Unit(db.Model):
    __tablename__ = "units"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    abbreviation = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    sku = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    reorder_level = db.Column(db.Integer, default=0)
    image_filename = db.Column(db.String(255), nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=True)
    unit_id = db.Column(db.Integer, db.ForeignKey("units.id"), nullable=True)

    category = db.relationship("Category")
    unit = db.relationship("Unit")
    images = db.relationship(
        "ProductImage",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ProductImage.uploaded_at.desc()",
    )

    def available_quantity(self) -> float:
        entries = StockEntry.query.filter_by(product_id=self.id).all()
        return sum(entry.remaining_quantity for entry in entries)

    def last_unit_cost(self) -> float:
        entry = (
            StockEntry.query.filter_by(product_id=self.id)
            .order_by(StockEntry.timestamp.desc())
            .first()
        )
        return entry.unit_cost if entry else 0

    def average_unit_cost(self) -> float:
        entries = StockEntry.query.filter_by(product_id=self.id).all()
        total_qty = sum(entry.quantity for entry in entries)
        if not entries or total_qty == 0:
            return 0
        total_cost = sum(entry.quantity * entry.unit_cost for entry in entries)
        return total_cost / total_qty

    def current_stock_value(self) -> float:
        entries = StockEntry.query.filter_by(product_id=self.id).all()
        return sum(entry.remaining_quantity * entry.unit_cost for entry in entries)


class ProductImage(db.Model):
    __tablename__ = "product_images"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    product = db.relationship("Product", back_populates="images")
    uploader = db.relationship("User")


class StockEntry(db.Model):
    __tablename__ = "stock_entries"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    remaining_quantity = db.Column(db.Float, nullable=False)
    unit_cost = db.Column(db.Float, nullable=False)
    supplier = db.Column(db.String(120), nullable=True)
    invoice_number = db.Column(db.String(120), nullable=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey("warehouses.id"), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    product = db.relationship("Product")
    warehouse = db.relationship("Warehouse")
    creator = db.relationship("User")


class StockExit(db.Model):
    __tablename__ = "stock_exits"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=True)
    total_cost = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    product = db.relationship("Product")
    project = db.relationship("Project")
    creator = db.relationship("User")


class StockAdjustment(db.Model):
    __tablename__ = "stock_adjustments"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    quantity_change = db.Column(db.Float, nullable=False)
    reason = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    product = db.relationship("Product")
    creator = db.relationship("User")


class StockMovementLog(db.Model):
    __tablename__ = "stock_movement_logs"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    movement_type = db.Column(db.String(50), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    details = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    cost = db.Column(db.Float, nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=True)

    product = db.relationship("Product")
    user = db.relationship("User")
    project = db.relationship("Project")


class StockRequest(db.Model):
    __tablename__ = "stock_requests"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    requester_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    status = db.Column(db.String(30), default="pending_procurement")
    manager_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    first_approver_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    notes = db.Column(db.Text, nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    order_number = db.Column(db.String(40), nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=True)
    fulfilled_quantity = db.Column(db.Float, nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    first_approved_at = db.Column(db.DateTime, nullable=True)

    product = db.relationship("Product")
    requester = db.relationship("User", foreign_keys=[requester_id])
    manager = db.relationship("User", foreign_keys=[manager_id])
    approver = db.relationship("User", foreign_keys=[approved_by])
    first_approver = db.relationship("User", foreign_keys=[first_approver_id])
    project = db.relationship("Project")


class PurchaseOrder(db.Model):
    __tablename__ = "purchase_orders"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    supplier = db.Column(db.String(120), nullable=False)
    expected_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default="pending")
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    product = db.relationship("Product")
    creator = db.relationship("User")


class UserActivityLog(db.Model):
    __tablename__ = "user_activity_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    action = db.Column(db.String(255), nullable=False)
    details = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    user = db.relationship("User")


def ensure_schema_upgrades() -> None:
    """Ensure older SQLite databases have the latest columns and tables."""

    def add_column(table: str, column: str, ddl: str) -> None:
        inspector = inspect(db.engine)
        existing = {col["name"] for col in inspector.get_columns(table)}
        if column in existing:
            return
        with db.engine.begin() as connection:
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))

    db.create_all()
    add_column("products", "image_filename", "VARCHAR(255)")
    add_column("products", "category_id", "INTEGER")
    add_column("products", "notes", "TEXT")
    add_column("products", "unit_id", "INTEGER")
    add_column("stock_movement_logs", "cost", "FLOAT")
    add_column("stock_movement_logs", "project_id", "INTEGER")
    add_column("stock_requests", "due_date", "DATE")
    add_column("stock_requests", "order_number", "VARCHAR(40)")
    add_column("stock_requests", "project_id", "INTEGER")
    add_column("stock_requests", "notes", "TEXT")
    add_column("stock_requests", "approved_at", "DATETIME")
    add_column("stock_requests", "first_approver_id", "INTEGER")
    add_column("stock_requests", "first_approved_at", "DATETIME")
    add_column("stock_requests", "fulfilled_quantity", "FLOAT")
    add_column("purchase_orders", "expected_date", "DATE")
    add_column("users", "last_login", "DATETIME")
    add_column("users", "email", "VARCHAR(255)")
    add_column("projects", "manager_id", "INTEGER")
    add_column("projects", "location", "VARCHAR(255)")

    with db.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE stock_requests SET approved_at = updated_at "
                "WHERE approved_at IS NULL AND status IN ('approved', 'tamamlandı')"
            )
        )
        connection.execute(
            text(
                "UPDATE stock_requests SET status = 'pending_procurement' "
                "WHERE status = 'pending'"
            )
        )

    inspector = inspect(db.engine)
    if not inspector.has_table("units"):
        Unit.__table__.create(db.engine)

    if not inspector.has_table("product_images"):
        ProductImage.__table__.create(db.engine)

    # Backfill gallery records for products with legacy single-image data.
    legacy_rows = db.session.execute(
        text(
            "SELECT id, image_filename FROM products "
            "WHERE image_filename IS NOT NULL AND image_filename <> ''"
        )
    ).all()
    created = False
    for product_id, filename in legacy_rows:
        if not ProductImage.query.filter_by(
            product_id=product_id, filename=filename
        ).first():
            db.session.add(
                ProductImage(product_id=product_id, filename=filename)
            )
            created = True
    if created:
        db.session.commit()

    if Unit.query.count() == 0:
        defaults = [
            ("Adet", None),
            ("Kutu", None),
            ("Paket", None),
        ]
        for name, abbreviation in defaults:
            db.session.add(Unit(name=name, abbreviation=abbreviation))
        db.session.commit()


with app.app_context():
    ensure_schema_upgrades()


@app.before_request
def load_current_user():
    user_id = session.get("user_id")
    g.user = User.query.get(user_id) if user_id else None


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Lütfen giriş yapın", "warning")
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return wrapped


def admin_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if g.user is None or not g.user.is_admin:
            abort(403)
        return view_func(*args, **kwargs)

    return wrapped


def manager_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if g.user is None or not g.user.is_manager:
            abort(403)
        return view_func(*args, **kwargs)

    return wrapped


def is_procurement_approver(user) -> bool:
    return user is not None and user.role in PROCUREMENT_APPROVER_ROLES


def record_movement(
    product_id: int,
    movement_type: str,
    quantity: float,
    details: str = "",
    *,
    cost: float | None = None,
    project_id: int | None = None,
) -> None:
    log = StockMovementLog(
        product_id=product_id,
        movement_type=movement_type,
        quantity=quantity,
        details=details,
        user_id=g.user.id if g.user else None,
        cost=cost,
        project_id=project_id,
    )
    db.session.add(log)


def record_user_activity(action: str, details: str = "") -> None:
    log = UserActivityLog(
        user_id=g.user.id if g.user else None,
        action=action,
        details=details,
    )
    db.session.add(log)


def generate_order_number() -> str:
    today = local_today().strftime("%Y%m%d")
    base = f"TAL-{today}"
    while True:
        suffix = random.randint(0, 9999)
        order_number = f"{base}-{suffix:04d}"
        if not StockRequest.query.filter_by(order_number=order_number).first():
            return order_number


def generate_product_code() -> str:
    """Return the next sequential product code in #0001 format."""
    last_number = 0
    for (sku,) in db.session.query(Product.sku).all():
        if not sku:
            continue
        if isinstance(sku, str) and sku.startswith("#"):
            numeric_part = sku[1:]
            if numeric_part.isdigit():
                last_number = max(last_number, int(numeric_part))
    return f"#{last_number + 1:04d}"


def get_default_procurement_approver() -> User | None:
    """Return a procurement approver for automatic first approvals."""

    if g.user and g.user.role in PROCUREMENT_APPROVER_ROLES:
        return g.user
    approver = (
        User.query.filter(User.role == "procurement_manager")
        .order_by(User.username.asc())
        .first()
    )
    if approver:
        return approver
    return (
        User.query.filter(User.role == "admin")
        .order_by(User.username.asc())
        .first()
    )


def resolve_status_summary(statuses: set[str]) -> tuple[str, str]:
    normalized = {status.lower() for status in statuses}
    if "rejected" in normalized:
        return ("Reddedildi", "bg-danger")
    if "pending_procurement" in normalized or "pending" in normalized:
        return ("1. onay bekliyor", "bg-warning text-dark")
    if "pending_manager" in normalized:
        return ("2. onay bekliyor", "bg-warning text-dark")
    if "tamamlandı" in normalized and "approved" in normalized:
        return ("Kısmen Tamamlandı", "bg-info text-dark")
    if "tamamlandı" in normalized:
        return ("Tamamlandı", "bg-success")
    if "approved" in normalized:
        return ("Onaylandı", "bg-primary")
    return ("Kaydedildi", "bg-secondary")


def summarize_request_groups(requests: list[StockRequest]) -> list[dict]:
    groups: dict[str, dict] = {}
    for req in requests:
        key = req.order_number or f"id-{req.id}"
        group = groups.get(key)
        if group is None:
            group = {
                "key": key,
                "display_number": req.order_number or f"Talep #{req.id}",
                "requester": req.requester,
                "manager": req.manager,
                "notes": req.notes,
                "created_at": req.created_at,
                "lines": [],
                "statuses": set(),
                "approval_times": [],
            }
            groups[key] = group
        else:
            if req.created_at < group["created_at"]:
                group["created_at"] = req.created_at
            if not group.get("notes") and req.notes:
                group["notes"] = req.notes
        group["lines"].append(
            {
                "product": req.product,
                "quantity": req.quantity,
                "project": req.project,
                "due_date": req.due_date,
                "status": req.status,
                "first_approver": req.first_approver,
                "first_approved_at": req.first_approved_at,
                "approver": req.approver,
                "approved_at": req.approved_at,
            }
        )
        group["statuses"].add(req.status)
        if req.approved_at:
            group["approval_times"].append(req.approved_at)
    summarized: list[dict] = []
    for group in groups.values():
        status_label, badge = resolve_status_summary(group["statuses"])
        group["status_label"] = status_label
        group["status_badge"] = badge
        approval_times = group.pop("approval_times", [])
        group["approved_at"] = max(approval_times) if approval_times else None
        group.pop("statuses", None)
        summarized.append(group)
    summarized.sort(key=lambda item: item["created_at"], reverse=True)
    return summarized


def load_request_group_records(group_key: str) -> list[StockRequest]:
    query = StockRequest.query.options(
        joinedload(StockRequest.product),
        joinedload(StockRequest.project),
        joinedload(StockRequest.requester),
        joinedload(StockRequest.manager),
        joinedload(StockRequest.first_approver),
        joinedload(StockRequest.approver),
    )
    if group_key.startswith("id-"):
        try:
            request_id = int(group_key.split("-", 1)[1])
        except ValueError:
            return []
        record = query.filter_by(id=request_id).first()
        return [record] if record else []
    return query.filter_by(order_number=group_key).all()


def apply_fifo_deduction(product: Product, quantity: float) -> tuple[float, list[str]]:
    """Apply FIFO deduction on stock entries and return total cost and notes."""
    remaining = quantity
    total_cost = 0.0
    notes = []
    entries = (
        StockEntry.query.filter_by(product_id=product.id)
        .filter(StockEntry.remaining_quantity > 0)
        .order_by(StockEntry.timestamp.asc())
        .all()
    )

    for entry in entries:
        if remaining <= 0:
            break
        take_qty = min(entry.remaining_quantity, remaining)
        entry.remaining_quantity -= take_qty
        remaining -= take_qty
        cost = take_qty * entry.unit_cost
        total_cost += cost
        notes.append(
            f"{take_qty} adet {entry.timestamp.strftime('%Y-%m-%d %H:%M')} girişinden düşüldü (birim maliyet {entry.unit_cost:.2f})"
        )
    if remaining > 0:
        raise ValueError("Yeterli stok bulunmuyor")

    return total_cost, notes


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session["user_id"] = user.id
            g.user = user
            user.last_login = datetime.datetime.utcnow()
            record_user_activity("login", f"Kullanıcı {username} giriş yaptı")
            db.session.commit()
            flash("Hoş geldiniz", "success")
            return redirect(url_for("dashboard"))
        flash("Geçersiz kullanıcı adı veya şifre", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    username = g.user.username if g.user else ""
    session.pop("user_id", None)
    flash("Çıkış yapıldı", "info")
    if username:
        record_user_activity("logout", f"Kullanıcı {username} çıkış yaptı")
        db.session.commit()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    show_summary = g.user.is_admin
    products = []
    low_stock = []
    if show_summary:
        products = Product.query.order_by(Product.name).all()
        low_stock = [
            p for p in products if p.available_quantity() <= p.reorder_level
        ]
    my_requests_query = (
        StockRequest.query.filter_by(requester_id=g.user.id)
        .order_by(StockRequest.created_at.desc())
    )
    my_requests = my_requests_query.limit(10).all()
    my_requests_total = my_requests_query.count()
    approvals = []
    approvals_total = 0
    if g.user.is_manager:
        approvals_query = None
        if is_procurement_approver(g.user):
            approvals_query = (
                StockRequest.query.filter(StockRequest.status == "pending_procurement")
                .order_by(StockRequest.created_at.asc())
            )
        elif g.user.role == "manager":
            approvals_query = (
                StockRequest.query.filter(
                    StockRequest.manager_id == g.user.id,
                    StockRequest.status == "pending_manager",
                ).order_by(StockRequest.created_at.asc())
            )
        if approvals_query is not None:
            approvals = approvals_query.limit(10).all()
            approvals_total = approvals_query.count()
    return render_template(
        "dashboard.html",
        products=products,
        low_stock=low_stock,
        show_summary=show_summary,
        my_requests=my_requests,
        approvals=approvals,
        my_requests_has_more=my_requests_total > len(my_requests),
        approvals_has_more=approvals_total > len(approvals),
    )


@app.route("/settings")
@admin_required
def settings():
    return render_template("settings.html")


@app.route("/products")
@login_required
def list_products():
    products = Product.query.order_by(Product.name.asc()).all()
    warehouses = Warehouse.query.all()
    categories = Category.query.order_by(Category.name.asc()).all()
    units = Unit.query.order_by(Unit.name.asc()).all()
    next_product_code = generate_product_code()
    return render_template(
        "products.html",
        products=products,
        warehouses=warehouses,
        categories=categories,
        units=units,
        next_product_code=next_product_code,
    )


@app.route("/products/new", methods=["POST"])
@login_required
def create_product():
    name = request.form.get("name", "").strip()
    try:
        reorder_level = int(request.form.get("reorder_level", 0) or 0)
    except (TypeError, ValueError):
        reorder_level = 0
    category_id_raw = request.form.get("category_id")
    category_id = int(category_id_raw) if category_id_raw else None
    unit_id_raw = request.form.get("unit_id")
    notes = request.form.get("notes", "").strip()
    image_files = request.files.getlist("images")
    if not image_files and "image" in request.files:
        image = request.files.get("image")
        image_files = [image] if image and image.filename else []
    if not name:
        flash("Ürün adı zorunludur", "danger")
        return redirect(url_for("list_products"))
    if not unit_id_raw:
        flash("Lütfen bir birim seçin", "danger")
        return redirect(url_for("list_products"))
    try:
        unit_id = int(unit_id_raw)
    except (TypeError, ValueError):
        flash("Geçerli bir birim seçin", "danger")
        return redirect(url_for("list_products"))
    unit = Unit.query.get(unit_id)
    if not unit:
        flash("Seçilen birim bulunamadı", "danger")
        return redirect(url_for("list_products"))
    duplicate = Product.query.filter(Product.name == name).first()
    if duplicate:
        flash("Bu isimde bir ürün zaten mevcut", "warning")
        return redirect(url_for("list_products"))
    validated_images: list = []
    for image_file in image_files:
        if not image_file or not image_file.filename:
            continue
        if not allowed_file(image_file.filename):
            flash("Desteklenmeyen dosya formatı", "danger")
            return redirect(url_for("list_products"))
        validated_images.append(image_file)
    sku = generate_product_code()
    while Product.query.filter_by(sku=sku).first():
        if sku.startswith("#") and sku[1:].isdigit():
            next_number = int(sku[1:]) + 1
            sku = f"#{next_number:04d}"
        else:
            sku = f"#{random.randint(1, 9999):04d}"
    product = Product(
        name=name,
        sku=sku,
        reorder_level=reorder_level,
        category_id=category_id,
        unit_id=unit.id,
        notes=notes or None,
    )
    db.session.add(product)
    saved_paths: list[Path] = []
    try:
        db.session.flush()
        for idx, image_file in enumerate(validated_images):
            filename = secure_filename(image_file.filename)
            ext = Path(filename).suffix
            unique_name = (
                f"product_{product.id}_{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
                f"_{idx}{ext}"
            )
            save_path = Path(app.config["UPLOAD_FOLDER"]) / unique_name
            image_file.save(save_path)
            saved_paths.append(save_path)
            db.session.add(
                ProductImage(
                    product_id=product.id,
                    filename=unique_name,
                    uploaded_by=g.user.id if g.user else None,
                )
            )
            if idx == 0 and not product.image_filename:
                product.image_filename = unique_name
    except Exception:
        for path in saved_paths:
            if path.exists():
                path.unlink()
        db.session.rollback()
        flash("Ürün kaydedilirken bir hata oluştu", "danger")
        return redirect(url_for("list_products"))
    record_user_activity("product_create", f"{name} ürünü oluşturuldu")
    db.session.commit()
    flash("Ürün oluşturuldu", "success")
    return redirect(url_for("list_products"))


@app.route("/products/<int:product_id>")
@login_required
def product_detail(product_id: int):
    product = Product.query.get_or_404(product_id)
    entries = (
        StockEntry.query.filter_by(product_id=product_id)
        .order_by(StockEntry.timestamp.desc())
        .all()
    )
    exits = (
        StockExit.query.filter_by(product_id=product_id)
        .order_by(StockExit.timestamp.desc())
        .all()
    )
    adjustments = (
        StockAdjustment.query.filter_by(product_id=product_id)
        .order_by(StockAdjustment.timestamp.desc())
        .all()
    )
    requests = (
        StockRequest.query.filter_by(product_id=product_id)
        .order_by(StockRequest.created_at.desc())
        .all()
    )
    available = product.available_quantity()
    categories = Category.query.order_by(Category.name.asc()).all()
    units = Unit.query.order_by(Unit.name.asc()).all()
    gallery_images = [image.filename for image in product.images]
    if product.image_filename and product.image_filename not in gallery_images:
        gallery_images.insert(0, product.image_filename)
    primary_image = gallery_images[0] if gallery_images else None
    return render_template(
        "product_detail.html",
        product=product,
        entries=entries,
        exits=exits,
        adjustments=adjustments,
        requests=requests,
        available=available,
        categories=categories,
        units=units,
        gallery_images=gallery_images,
        primary_image=primary_image,
    )


@app.route("/stock/entry", methods=["GET", "POST"])
@admin_required
def stock_entry():
    products = Product.query.order_by(Product.name).all()
    warehouses = Warehouse.query.order_by(Warehouse.name).all()
    if request.method == "POST":
        product_ids = request.form.getlist("product_id[]")
        quantities = request.form.getlist("quantity[]")
        unit_costs = request.form.getlist("unit_cost[]")
        suppliers = request.form.getlist("supplier[]")
        invoices = request.form.getlist("invoice_number[]")
        warehouse_ids = request.form.getlist("warehouse_id[]")
        entries_to_create = []
        for idx, product_raw in enumerate(product_ids):
            product_raw = (product_raw or "").strip()
            if not product_raw:
                continue
            try:
                product_id = int(product_raw)
                quantity = float((quantities[idx] or "0").replace(",", "."))
                unit_cost = float((unit_costs[idx] or "0").replace(",", "."))
            except (ValueError, IndexError):
                db.session.rollback()
                flash("Lütfen tüm satırlar için geçerli miktar ve birim maliyet girin", "danger")
                return redirect(url_for("stock_entry"))
            if quantity <= 0 or unit_cost < 0:
                db.session.rollback()
                flash("Miktar sıfırdan büyük olmalı ve maliyet negatif olamaz", "danger")
                return redirect(url_for("stock_entry"))
            supplier = (suppliers[idx].strip() if idx < len(suppliers) and suppliers[idx] else None)
            invoice = (
                invoices[idx].strip() if idx < len(invoices) and invoices[idx] else None
            )
            warehouse_raw = warehouse_ids[idx] if idx < len(warehouse_ids) else None
            warehouse_id = int(warehouse_raw) if warehouse_raw else None
            entries_to_create.append(
                {
                    "product_id": product_id,
                    "quantity": quantity,
                    "unit_cost": unit_cost,
                    "supplier": supplier,
                    "invoice": invoice,
                    "warehouse_id": warehouse_id,
                }
            )
        if not entries_to_create:
            flash("En az bir satır seçiniz", "warning")
            return redirect(url_for("stock_entry"))
        total_cost_all = 0.0
        try:
            for item in entries_to_create:
                entry = StockEntry(
                    product_id=item["product_id"],
                    quantity=item["quantity"],
                    remaining_quantity=item["quantity"],
                    unit_cost=item["unit_cost"],
                    supplier=item["supplier"],
                    invoice_number=item["invoice"],
                    warehouse_id=item["warehouse_id"],
                    created_by=g.user.id if g.user else None,
                )
                db.session.add(entry)
                line_cost = item["quantity"] * item["unit_cost"]
                total_cost_all += line_cost
                detail = f"Tedarikçi: {item['supplier'] or '-'}, Fatura: {item['invoice'] or '-'}"
                record_movement(
                    item["product_id"],
                    "giriş",
                    item["quantity"],
                    detail,
                    cost=line_cost,
                )
        except Exception:
            db.session.rollback()
            raise
        record_user_activity(
            "stock_entry",
            f"{len(entries_to_create)} satır için toplam {total_cost_all:.2f} maliyetli stok girişi",
        )
        db.session.commit()
        flash("Stok girişleri kaydedildi", "success")
        return redirect(url_for("stock_entry"))
    return render_template("stock_entry.html", products=products, warehouses=warehouses)


@app.route("/warehouses", methods=["GET", "POST"])
@manager_required
def manage_warehouses():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip() or None
        if not name:
            flash("Depo adı zorunludur", "danger")
            return redirect(url_for("manage_warehouses"))
        if Warehouse.query.filter_by(name=name).first():
            flash("Bu isimde bir depo zaten mevcut", "warning")
            return redirect(url_for("manage_warehouses"))
        warehouse = Warehouse(name=name, description=description)
        db.session.add(warehouse)
        record_user_activity("warehouse_create", f"{name} adlı depo oluşturuldu")
        db.session.commit()
        flash("Depo eklendi", "success")
        return redirect(url_for("manage_warehouses"))
    warehouses = Warehouse.query.order_by(Warehouse.name.asc()).all()
    return render_template("warehouses.html", warehouses=warehouses)


@app.route("/warehouses/<int:warehouse_id>/update", methods=["POST"])
@manager_required
def update_warehouse(warehouse_id: int):
    warehouse = Warehouse.query.get_or_404(warehouse_id)
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip() or None
    if not name:
        flash("Depo adı zorunludur", "danger")
        return redirect(url_for("manage_warehouses"))
    duplicate = (
        Warehouse.query.filter(Warehouse.id != warehouse_id)
        .filter(Warehouse.name == name)
        .first()
    )
    if duplicate:
        flash("Bu depo adı başka bir kayıt tarafından kullanılıyor", "danger")
        return redirect(url_for("manage_warehouses"))
    warehouse.name = name
    warehouse.description = description
    record_user_activity("warehouse_update", f"{warehouse.name} deposu güncellendi")
    db.session.commit()
    flash("Depo güncellendi", "success")
    return redirect(url_for("manage_warehouses"))


@app.route("/stock/exit", methods=["GET", "POST"])
@admin_required
def stock_exit():
    products = Product.query.order_by(Product.name).all()
    projects = Project.query.order_by(Project.name).all()
    if request.method == "POST":
        fulfill_request_id = request.form.get("fulfill_request_id")
        if fulfill_request_id:
            try:
                request_id = int(fulfill_request_id)
            except (TypeError, ValueError):
                flash("Geçerli bir talep seçimi bulunamadı", "danger")
                return redirect(url_for("stock_exit"))
            stock_request = (
                StockRequest.query.options(joinedload(StockRequest.product))
                .filter_by(id=request_id)
                .first()
            )
            if not stock_request:
                flash("Talep kaydı bulunamadı", "danger")
                return redirect(url_for("stock_exit"))
            if stock_request.status != "approved":
                flash("Bu talep satırı için stok çıkışı zaten yapılmış", "info")
                return redirect(url_for("stock_exit"))
            quantity_raw = request.form.get("fulfill_quantity", "0")
            try:
                fulfill_quantity = float(quantity_raw.replace(",", "."))
            except ValueError:
                flash("Geçerli bir miktar girin", "danger")
                return redirect(url_for("stock_exit"))
            if fulfill_quantity <= 0:
                flash("Çıkış miktarı sıfırdan büyük olmalıdır", "danger")
                return redirect(url_for("stock_exit"))
            if fulfill_quantity > stock_request.quantity:
                flash("Talep edilen miktardan fazla stok çıkışı yapılamaz", "danger")
                return redirect(url_for("stock_exit"))
            try:
                complete_stock_request(stock_request, fulfill_quantity)
            except ValueError as exc:
                db.session.rollback()
                flash(str(exc), "danger")
                return redirect(url_for("stock_exit"))
            db.session.commit()
            flash(
                f"{stock_request.order_number or stock_request.id} numaralı talep için {format_decimal_value(fulfill_quantity)} birim stoktan çıkış yapıldı",
                "success",
            )
            return redirect(url_for("stock_exit"))
        product_ids = request.form.getlist("product_id[]")
        quantities = request.form.getlist("quantity[]")
        project_ids = request.form.getlist("project_id[]")
        processed_items = []
        for idx, product_raw in enumerate(product_ids):
            product_raw = (product_raw or "").strip()
            if not product_raw:
                continue
            try:
                product_id = int(product_raw)
                quantity = float((quantities[idx] or "0").replace(",", "."))
            except (ValueError, IndexError):
                db.session.rollback()
                flash("Lütfen tüm satırlar için geçerli bir miktar seçin", "danger")
                return redirect(url_for("stock_exit"))
            if quantity <= 0:
                db.session.rollback()
                flash("Çıkış miktarı sıfırdan büyük olmalıdır", "danger")
                return redirect(url_for("stock_exit"))
            project_raw = project_ids[idx] if idx < len(project_ids) else None
            project_id = int(project_raw) if project_raw else None
            product = Product.query.get_or_404(product_id)
            try:
                total_cost, notes = apply_fifo_deduction(product, quantity)
            except ValueError as exc:
                db.session.rollback()
                flash(str(exc), "danger")
                return redirect(url_for("stock_exit"))
            processed_items.append(
                {
                    "product_id": product_id,
                    "quantity": quantity,
                    "project_id": project_id,
                    "total_cost": total_cost,
                    "notes": notes,
                }
            )
        if not processed_items:
            flash("En az bir satır seçiniz", "warning")
            return redirect(url_for("stock_exit"))
        total_cost_all = 0.0
        for item in processed_items:
            project = Project.query.get(item["project_id"]) if item["project_id"] else None
            exit_record = StockExit(
                product_id=item["product_id"],
                quantity=item["quantity"],
                project_id=item["project_id"],
                total_cost=item["total_cost"],
                created_by=g.user.id if g.user else None,
            )
            db.session.add(exit_record)
            total_cost_all += item["total_cost"]
            notes_text = "; ".join(item["notes"]) if item["notes"] else ""
            detail = f"Proje: {project.name if project else '-'}"
            if notes_text:
                detail += f" | {notes_text}"
            record_movement(
                item["product_id"],
                "çıkış",
                -item["quantity"],
                detail,
                cost=item["total_cost"],
                project_id=item["project_id"],
            )
        record_user_activity(
            "stock_exit",
            f"{len(processed_items)} satır için toplam {total_cost_all:.2f} maliyetli stok çıkışı",
        )
        db.session.commit()
        flash("Stok çıkışları kaydedildi", "success")
        return redirect(url_for("stock_exit"))
    approved_requests = (
        StockRequest.query.options(
            joinedload(StockRequest.product),
            joinedload(StockRequest.project).joinedload(Project.manager),
            joinedload(StockRequest.requester),
        )
        .filter(StockRequest.status.in_(["approved", "tamamlandı"]))
        .order_by(StockRequest.updated_at.desc(), StockRequest.created_at.desc())
        .all()
    )
    return render_template(
        "stock_exit.html",
        products=products,
        projects=projects,
        approved_requests=approved_requests,
    )


@app.route("/stock/adjust", methods=["GET", "POST"])
@manager_required
def stock_adjust():
    products = Product.query.order_by(Product.name).all()
    if request.method == "POST":
        product_id = int(request.form.get("product_id"))
        quantity_change = float(request.form.get("quantity_change"))
        reason = request.form.get("reason", "").strip()
        product = Product.query.get_or_404(product_id)
        if not reason:
            flash("Düzeltme nedeni zorunludur", "danger")
            return redirect(url_for("stock_adjust"))
        if quantity_change < 0:
            try:
                total_cost, notes = apply_fifo_deduction(product, abs(quantity_change))
                detail = f"{reason} nedeniyle {abs(quantity_change)} adet düşüldü. {', '.join(notes)}"
            except ValueError as exc:
                db.session.rollback()
                flash(str(exc), "danger")
                return redirect(url_for("stock_adjust"))
            record_movement(
                product_id,
                "düzeltme",
                quantity_change,
                detail,
                cost=total_cost,
            )
        else:
            entry = StockEntry(
                product_id=product_id,
                quantity=quantity_change,
                remaining_quantity=quantity_change,
                unit_cost=0,
                supplier="Manuel Düzeltme",
                invoice_number=None,
                warehouse_id=None,
                created_by=g.user.id if g.user else None,
            )
            db.session.add(entry)
            detail = f"{reason} nedeniyle {quantity_change} adet eklendi"
            record_movement(
                product_id,
                "düzeltme",
                quantity_change,
                detail,
                cost=0,
            )
        adjustment = StockAdjustment(
            product_id=product_id,
            quantity_change=quantity_change,
            reason=reason,
            created_by=g.user.id if g.user else None,
        )
        db.session.add(adjustment)
        record_user_activity("stock_adjust", detail)
        db.session.commit()
        flash("Stok düzeltmesi kaydedildi", "success")
        return redirect(url_for("stock_adjust"))
    return render_template("stock_adjust.html", products=products)


@app.route("/requests", methods=["GET", "POST"])
@login_required
def stock_requests():
    products = Product.query.order_by(Product.name).all()
    projects = Project.query.order_by(Project.name).all()
    default_due_date_value = local_today() + datetime.timedelta(days=3)
    default_due_date_str = default_due_date_value.isoformat()
    min_due_date_value = local_today()
    min_due_date = min_due_date_value.isoformat()
    if request.method == "POST":
        product_ids = request.form.getlist("product_id[]")
        quantities = request.form.getlist("quantity[]")
        notes = request.form.get("notes", "").strip()
        project_ids = request.form.getlist("project_id[]")
        due_dates = request.form.getlist("due_date[]")
        request_items = []
        available_cache: dict[int, float] = {}
        for idx, product_raw in enumerate(product_ids):
            product_raw = (product_raw or "").strip()
            if not product_raw:
                continue
            try:
                product_id = int(product_raw)
                quantity = float((quantities[idx] or "0").replace(",", "."))
            except (ValueError, IndexError):
                flash("Lütfen talep satırları için geçerli ürün ve miktar girin", "danger")
                return redirect(url_for("stock_requests"))
            if quantity <= 0:
                flash("Talep miktarı sıfırdan büyük olmalıdır", "danger")
                return redirect(url_for("stock_requests"))
            product = Product.query.get(product_id)
            if not product:
                flash("Seçilen ürün bulunamadı", "danger")
                return redirect(url_for("stock_requests"))
            project_raw = project_ids[idx] if idx < len(project_ids) else ""
            if not project_raw:
                flash(
                    f"Satır {idx + 1} için bir proje seçimi yapınız", "danger"
                )
                return redirect(url_for("stock_requests"))
            try:
                project_id = int(project_raw)
            except ValueError:
                flash(
                    f"Satır {idx + 1} için geçerli bir proje seçimi yapınız", "danger"
                )
                return redirect(url_for("stock_requests"))
            project = Project.query.get(project_id)
            if not project:
                flash(
                    f"Satır {idx + 1} için seçilen proje bulunamadı", "danger"
                )
                return redirect(url_for("stock_requests"))
            if not project.manager_id:
                flash(
                    f"{project.name} projesi için yönetici tanımlı değil", "danger"
                )
                return redirect(url_for("stock_requests"))
            due_date_value = default_due_date_value
            due_date_raw = due_dates[idx].strip() if idx < len(due_dates) else ""
            if due_date_raw:
                try:
                    due_date_value = datetime.datetime.strptime(
                        due_date_raw, "%Y-%m-%d"
                    ).date()
                except ValueError:
                    flash(
                        f"Satır {idx + 1} için geçerli bir termin tarihi seçiniz", "danger"
                    )
                    return redirect(url_for("stock_requests"))
                if due_date_value < local_today():
                    flash(
                        f"Satır {idx + 1} için termin tarihi bugünden itibaren ileri bir tarih olmalıdır",
                        "danger",
                    )
                    return redirect(url_for("stock_requests"))
            elif due_date_value < local_today():
                due_date_value = default_due_date_value
            available_amount = available_cache.get(product_id)
            if available_amount is None:
                available_amount = product.available_quantity()
            auto_first = available_amount >= quantity
            if auto_first:
                available_cache[product_id] = max(0.0, available_amount - quantity)
            else:
                available_cache[product_id] = available_amount
            request_items.append(
                {
                    "product_id": product_id,
                    "quantity": quantity,
                    "project_id": project_id,
                    "due_date": due_date_value,
                    "manager_id": project.manager_id,
                    "auto_first": auto_first,
                }
            )
        if not request_items:
            flash("En az bir ürün seçiniz", "warning")
            return redirect(url_for("stock_requests"))
        order_number = generate_order_number()
        default_first_approver = get_default_procurement_approver()
        now = datetime.datetime.utcnow()
        auto_first_count = 0
        for item in request_items:
            status_value = "pending_procurement"
            first_approver_id = None
            first_approved_at = None
            if item["auto_first"]:
                status_value = "pending_manager"
                auto_first_count += 1
                first_approved_at = now
                if default_first_approver:
                    first_approver_id = default_first_approver.id
            request_record = StockRequest(
                product_id=item["product_id"],
                quantity=item["quantity"],
                requester_id=g.user.id,
                manager_id=item["manager_id"],
                notes=notes,
                due_date=item["due_date"],
                order_number=order_number,
                project_id=item["project_id"],
                status=status_value,
                first_approver_id=first_approver_id,
                first_approved_at=first_approved_at,
            )
            if item["auto_first"]:
                request_record.updated_at = now
            db.session.add(request_record)
        activity_message = (
            f"{order_number} numaralı talep için {len(request_items)} satır eklendi"
        )
        if auto_first_count:
            activity_message += f"; {auto_first_count} satır otomatik 1. onay aldı"
        record_user_activity("stock_request_create", activity_message)
        db.session.commit()
        if auto_first_count:
            pending_first = len(request_items) - auto_first_count
            if pending_first > 0:
                flash(
                    f"{order_number} sipariş numaralı talebiniz oluşturuldu. {auto_first_count} satır stokta bulunduğu için 1. onay otomatik tamamlandı ve proje yöneticisine iletildi. {pending_first} satır 1. onayı bekliyor.",
                    "success",
                )
            else:
                flash(
                    f"{order_number} sipariş numaralı talebiniz oluşturuldu. Tüm satırlar stokta bulunduğu için 1. onay otomatik tamamlandı ve proje yöneticisine iletildi.",
                    "success",
                )
        else:
            flash(
                f"{order_number} sipariş numaralı talebiniz Satınalma Yöneticisi onayına gönderildi",
                "success",
            )
        return redirect(url_for("stock_requests"))
    my_requests_query = (
        StockRequest.query.options(
            joinedload(StockRequest.product),
            joinedload(StockRequest.project).joinedload(Project.manager),
            joinedload(StockRequest.manager),
        )
        .filter_by(requester_id=g.user.id)
        .order_by(StockRequest.created_at.desc())
    )
    my_requests = my_requests_query.limit(10).all()
    my_requests_total = my_requests_query.count()
    to_approve = []
    approvals_total = 0
    approvals_title = None
    approval_stage = None
    if g.user.is_manager:
        base_query = (
            StockRequest.query.options(
                joinedload(StockRequest.product),
                joinedload(StockRequest.project),
                joinedload(StockRequest.requester),
            )
            .order_by(StockRequest.created_at.asc())
        )
        approvals_query = None
        if is_procurement_approver(g.user):
            approvals_query = base_query.filter(StockRequest.status == "pending_procurement")
            approvals_title = "1. Onay Bekleyenler"
            approval_stage = "procurement"
        elif g.user.role == "manager":
            approvals_query = base_query.filter(
                StockRequest.manager_id == g.user.id,
                StockRequest.status == "pending_manager",
            )
            approvals_title = "2. Onay Bekleyenler"
            approval_stage = "manager"
        if approvals_query is not None:
            to_approve = approvals_query.limit(10).all()
            approvals_total = approvals_query.count()
    project_approvers = {
        project.id: project.manager.username
        if project.manager
        else "-"
        for project in projects
    }
    return render_template(
        "stock_requests.html",
        products=products,
        my_requests=my_requests,
        to_approve=to_approve,
        min_due_date=min_due_date,
        default_due_date=default_due_date_str,
        projects=projects,
        my_requests_has_more=my_requests_total > len(my_requests),
        approvals_has_more=approvals_total > len(to_approve),
        project_approvers=project_approvers,
        approvals_title=approvals_title,
        approval_stage=approval_stage,
    )


@app.route("/requests/mine/all")
@login_required
def all_my_requests():
    requests = (
        StockRequest.query.filter_by(requester_id=g.user.id)
        .order_by(StockRequest.created_at.desc())
        .all()
    )
    return render_template(
        "request_list.html",
        title="Benim Taleplerim",
        requests=requests,
        show_requester=False,
        show_actions=False,
    )


@app.route("/requests/approvals/all")
@manager_required
def all_pending_approvals():
    base_query = (
        StockRequest.query.options(
            joinedload(StockRequest.product),
            joinedload(StockRequest.project),
            joinedload(StockRequest.requester),
        )
        .order_by(StockRequest.created_at.asc())
    )
    title = "Onay Listesi"
    requests = []
    is_procurement = is_procurement_approver(g.user)
    if is_procurement:
        requests = base_query.filter(StockRequest.status == "pending_procurement").all()
        title = "1. Onay Bekleyenler"
    elif g.user.role == "manager":
        requests = (
            base_query.filter(
                StockRequest.manager_id == g.user.id,
                StockRequest.status == "pending_manager",
            ).all()
        )
        title = "2. Onay Bekleyenler"
    return render_template(
        "request_list.html",
        title=title,
        requests=requests,
        show_requester=True,
        show_actions=True,
        approval_stage="procurement" if is_procurement else "manager",
    )


@app.route("/requests/<int:request_id>/approve", methods=["POST"])
@manager_required
def approve_request(request_id: int):
    stock_request = StockRequest.query.get_or_404(request_id)
    now = datetime.datetime.utcnow()
    if stock_request.status == "pending_procurement":
        if not is_procurement_approver(g.user):
            abort(403)
        stock_request.status = "pending_manager"
        stock_request.first_approver_id = g.user.id
        stock_request.first_approved_at = now
        stock_request.approved_by = None
        stock_request.approved_at = None
        stock_request.updated_at = now
        record_user_activity(
            "stock_request_first_approve",
            f"{stock_request.order_number or stock_request.id} numaralı talep satırı 1. onaydan geçti",
        )
        flash("Talep 1. onaydan geçti", "success")
    elif stock_request.status == "pending_manager":
        if stock_request.manager_id != g.user.id:
            abort(403)
        stock_request.status = "approved"
        stock_request.approved_by = g.user.id
        stock_request.approved_at = now
        stock_request.updated_at = now
        record_user_activity(
            "stock_request_second_approve",
            f"{stock_request.order_number or stock_request.id} numaralı talep satırı 2. onaydan geçti",
        )
        flash("Talep 2. onaydan geçti", "success")
    else:
        flash("Bu talep için onay süreci tamamlanmış", "warning")
        return redirect(url_for("stock_requests"))
    db.session.commit()
    return redirect(url_for("stock_requests"))


@app.route("/requests/<int:request_id>/reject", methods=["POST"])
@manager_required
def reject_request(request_id: int):
    stock_request = StockRequest.query.get_or_404(request_id)
    if stock_request.status == "pending_procurement":
        if not is_procurement_approver(g.user):
            abort(403)
        stage_label = "1. onay"
    elif stock_request.status == "pending_manager":
        if stock_request.manager_id != g.user.id:
            abort(403)
        stage_label = "2. onay"
    else:
        flash("Talep için reddedilecek bir aşama bulunmuyor", "warning")
        return redirect(url_for("stock_requests"))
    stock_request.status = "rejected"
    stock_request.approved_at = None
    stock_request.approved_by = None
    if stage_label == "1. onay":
        stock_request.first_approver_id = None
        stock_request.first_approved_at = None
    stock_request.updated_at = datetime.datetime.utcnow()
    record_user_activity(
        "stock_request_reject",
        f"{stock_request.order_number or stock_request.id} numaralı talep satırı {stage_label} aşamasında reddedildi",
    )
    db.session.commit()
    flash("Talep reddedildi", "info")
    return redirect(url_for("stock_requests"))


def complete_stock_request(stock_request: StockRequest, quantity: float) -> tuple[float, list[str]]:
    if stock_request.status != "approved":
        raise ValueError("Sadece onaylı talepler karşılanabilir")
    if quantity <= 0:
        raise ValueError("Çıkış miktarı sıfırdan büyük olmalıdır")
    if quantity > stock_request.quantity:
        raise ValueError("Talep edilen miktardan fazla stok çıkışı yapılamaz")
    product = stock_request.product
    total_cost, notes = apply_fifo_deduction(product, quantity)
    exit_record = StockExit(
        product_id=product.id,
        quantity=quantity,
        project_id=stock_request.project_id,
        total_cost=total_cost,
        created_by=g.user.id if g.user else None,
    )
    db.session.add(exit_record)
    stock_request.status = "tamamlandı"
    stock_request.fulfilled_quantity = quantity
    stock_request.updated_at = datetime.datetime.utcnow()
    notes_text = "; ".join(notes) if notes else ""
    detail_text = f"Talep {stock_request.order_number or stock_request.id} karşılandı."
    if abs(quantity - stock_request.quantity) > 1e-9:
        detail_text += (
            f" Talep miktarı: {format_decimal_value(stock_request.quantity)},"
            f" çıkış miktarı: {format_decimal_value(quantity)}."
        )
    if notes_text:
        detail_text += f" {notes_text}"
    record_movement(
        product.id,
        "talep-karşılama",
        -quantity,
        detail_text,
        cost=total_cost,
        project_id=stock_request.project_id,
    )
    record_user_activity(
        "stock_request_fulfill",
        f"{stock_request.order_number or stock_request.id} numaralı talep satırı için {format_decimal_value(quantity)} birim stoktan çıkış yapıldı",
    )
    return total_cost, notes


@app.route("/requests/<int:request_id>/fulfill", methods=["POST"])
@manager_required
def fulfill_request(request_id: int):
    stock_request = StockRequest.query.get_or_404(request_id)
    try:
        complete_stock_request(stock_request, stock_request.quantity)
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
        return redirect(url_for("stock_requests"))
    db.session.commit()
    flash("Talep karşılandı", "success")
    return redirect(url_for("stock_requests"))


@app.route("/projects", methods=["GET", "POST"])
@manager_required
def manage_projects():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip() or None
        location = request.form.get("location", "").strip() or None
        manager_id_raw = request.form.get("manager_id")
        if not name:
            flash("Proje adı zorunludur", "danger")
            return redirect(url_for("manage_projects"))
        if Project.query.filter_by(name=name).first():
            flash("Bu isimde bir proje zaten mevcut", "warning")
            return redirect(url_for("manage_projects"))
        manager_id = None
        if manager_id_raw:
            try:
                manager_id = int(manager_id_raw)
            except (TypeError, ValueError):
                flash("Geçerli bir yönetici seçin", "danger")
                return redirect(url_for("manage_projects"))
            if not User.query.get(manager_id):
                flash("Seçilen yönetici bulunamadı", "danger")
                return redirect(url_for("manage_projects"))
        project = Project(
            name=name,
            description=description,
            location=location,
            manager_id=manager_id,
        )
        db.session.add(project)
        record_user_activity("project_create", f"{name} projesi oluşturuldu")
        db.session.commit()
        flash("Proje eklendi", "success")
        return redirect(url_for("manage_projects"))
    projects = Project.query.order_by(Project.name.asc()).all()
    users = User.query.order_by(User.username.asc()).all()
    return render_template("projects.html", projects=projects, users=users)


@app.route("/projects/<int:project_id>", methods=["POST"])
@manager_required
def update_project(project_id: int):
    project = Project.query.get_or_404(project_id)
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip() or None
    location = request.form.get("location", "").strip() or None
    manager_id_raw = request.form.get("manager_id")
    if not name:
        flash("Proje adı zorunludur", "danger")
        return redirect(url_for("manage_projects"))
    duplicate = Project.query.filter(Project.id != project.id, Project.name == name).first()
    if duplicate:
        flash("Bu isimde başka bir proje bulunuyor", "warning")
        return redirect(url_for("manage_projects"))
    manager_id = None
    if manager_id_raw:
        try:
            manager_id = int(manager_id_raw)
        except (TypeError, ValueError):
            flash("Geçerli bir yönetici seçin", "danger")
            return redirect(url_for("manage_projects"))
        if not User.query.get(manager_id):
            flash("Seçilen yönetici bulunamadı", "danger")
            return redirect(url_for("manage_projects"))
    project.name = name
    project.description = description
    project.location = location
    project.manager_id = manager_id
    record_user_activity("project_update", f"{project.name} projesi güncellendi")
    db.session.commit()
    flash("Proje güncellendi", "success")
    return redirect(url_for("manage_projects"))


@app.route("/categories", methods=["GET", "POST"])
@admin_required
def manage_categories():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Kategori adı zorunludur", "danger")
            return redirect(url_for("manage_categories"))
        if Category.query.filter_by(name=name).first():
            flash("Bu isimde bir kategori zaten mevcut", "warning")
            return redirect(url_for("manage_categories"))
        category = Category(name=name)
        db.session.add(category)
        record_user_activity("category_create", f"{name} kategorisi oluşturuldu")
        db.session.commit()
        flash("Kategori eklendi", "success")
        return redirect(url_for("manage_categories"))
    categories = Category.query.order_by(Category.name.asc()).all()
    return render_template("categories.html", categories=categories)


@app.route("/categories/<int:category_id>", methods=["POST"])
@admin_required
def update_category(category_id: int):
    category = Category.query.get_or_404(category_id)
    name = request.form.get("name", "").strip()
    if not name:
        flash("Kategori adı zorunludur", "danger")
        return redirect(url_for("manage_categories"))
    duplicate = Category.query.filter(Category.id != category.id, Category.name == name).first()
    if duplicate:
        flash("Bu isimde başka bir kategori bulunuyor", "warning")
        return redirect(url_for("manage_categories"))
    category.name = name
    record_user_activity("category_update", f"{name} kategorisi güncellendi")
    db.session.commit()
    flash("Kategori güncellendi", "success")
    return redirect(url_for("manage_categories"))


@app.route("/units", methods=["GET", "POST"])
@admin_required
def manage_units():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        abbreviation = request.form.get("abbreviation", "").strip()
        if not name:
            flash("Birim adı zorunludur", "danger")
            return redirect(url_for("manage_units"))
        if Unit.query.filter_by(name=name).first():
            flash("Bu isimde bir birim zaten mevcut", "warning")
            return redirect(url_for("manage_units"))
        unit = Unit(name=name, abbreviation=abbreviation or None)
        db.session.add(unit)
        record_user_activity("unit_create", f"{name} birimi oluşturuldu")
        db.session.commit()
        flash("Birim eklendi", "success")
        return redirect(url_for("manage_units"))
    units = Unit.query.order_by(Unit.name.asc()).all()
    return render_template("units.html", units=units)


@app.route("/units/<int:unit_id>", methods=["POST"])
@admin_required
def update_unit(unit_id: int):
    unit = Unit.query.get_or_404(unit_id)
    name = request.form.get("name", "").strip()
    abbreviation = request.form.get("abbreviation", "").strip()
    if not name:
        flash("Birim adı zorunludur", "danger")
        return redirect(url_for("manage_units"))
    duplicate = Unit.query.filter(Unit.id != unit.id, Unit.name == name).first()
    if duplicate:
        flash("Bu isimde başka bir birim bulunuyor", "warning")
        return redirect(url_for("manage_units"))
    unit.name = name
    unit.abbreviation = abbreviation or None
    record_user_activity("unit_update", f"{name} birimi güncellendi")
    db.session.commit()
    flash("Birim güncellendi", "success")
    return redirect(url_for("manage_units"))


@app.route("/products/<int:product_id>/update", methods=["POST"])
@admin_required
def update_product(product_id: int):
    product = Product.query.get_or_404(product_id)
    name = request.form.get("name", "").strip()
    try:
        reorder_level = int(request.form.get("reorder_level", product.reorder_level) or product.reorder_level)
    except (TypeError, ValueError):
        reorder_level = product.reorder_level
    category_id_raw = request.form.get("category_id")
    category_id = int(category_id_raw) if category_id_raw else None
    unit_id_raw = request.form.get("unit_id")
    notes = request.form.get("notes", "").strip()
    if not name:
        flash("Ürün adı zorunludur", "danger")
        return redirect(url_for("product_detail", product_id=product.id))
    if not unit_id_raw:
        flash("Lütfen bir birim seçin", "danger")
        return redirect(url_for("product_detail", product_id=product.id))
    try:
        unit_id = int(unit_id_raw)
    except (TypeError, ValueError):
        flash("Geçerli bir birim seçin", "danger")
        return redirect(url_for("product_detail", product_id=product.id))
    unit = Unit.query.get(unit_id)
    if not unit:
        flash("Seçilen birim bulunamadı", "danger")
        return redirect(url_for("product_detail", product_id=product.id))
    duplicate = Product.query.filter(
        Product.id != product.id,
        Product.name == name,
    ).first()
    if duplicate:
        flash("Bu isimde başka bir ürün mevcut", "warning")
        return redirect(url_for("product_detail", product_id=product.id))
    product.name = name
    product.reorder_level = reorder_level
    product.category_id = category_id
    product.unit_id = unit.id
    product.notes = notes or None
    image_files = request.files.getlist("images")
    if not image_files and "image" in request.files:
        fallback = request.files.get("image")
        image_files = [fallback] if fallback and fallback.filename else []
    validated_images = []
    for image_file in image_files:
        if not image_file or not image_file.filename:
            continue
        if not allowed_file(image_file.filename):
            flash("Desteklenmeyen dosya formatı", "danger")
            db.session.rollback()
            return redirect(url_for("product_detail", product_id=product.id))
        validated_images.append(image_file)
    saved_paths: list[Path] = []
    try:
        for idx, image_file in enumerate(validated_images):
            filename = secure_filename(image_file.filename)
            ext = Path(filename).suffix
            unique_name = (
                f"product_{product.id}_{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
                f"_{idx}{ext}"
            )
            save_path = Path(app.config["UPLOAD_FOLDER"]) / unique_name
            image_file.save(save_path)
            saved_paths.append(save_path)
            db.session.add(
                ProductImage(
                    product_id=product.id,
                    filename=unique_name,
                    uploaded_by=g.user.id if g.user else None,
                )
            )
            if not product.image_filename:
                product.image_filename = unique_name
    except Exception:
        for path in saved_paths:
            if path.exists():
                path.unlink()
        db.session.rollback()
        flash("Fotoğraf yüklenirken bir hata oluştu", "danger")
        return redirect(url_for("product_detail", product_id=product.id))

    record_user_activity("product_update", f"{product.name} ürünü güncellendi")
    db.session.commit()
    flash("Ürün güncellendi", "success")
    return redirect(url_for("product_detail", product_id=product.id))


@app.route("/reports/movements/export")
@admin_required
def export_movements():
    movements = StockMovementLog.query.order_by(StockMovementLog.timestamp.asc()).all()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Hareketler"
    headers = [
        "Tarih",
        "Ürün",
        "Hareket",
        "Miktar",
        "Maliyet",
        "Proje",
        "Detay",
        "Kullanıcı",
    ]
    sheet.append(headers)
    for movement in movements:
        sheet.append(
            [
                movement.timestamp.strftime("%d.%m.%Y %H:%M"),
                movement.product.name if movement.product else "-",
                movement.movement_type,
                movement.quantity,
                round(movement.cost, 2) if movement.cost is not None else "-",
                movement.project.name if movement.project else "-",
                movement.details or "",
                movement.user.username if movement.user else "-",
            ]
        )
    for column_cells in sheet.columns:
        max_length = 0
        column_letter = column_cells[0].column_letter
        for cell in column_cells:
            if cell.value:
                max_length = max(max_length, len(str(cell.value)))
        sheet.column_dimensions[column_letter].width = max_length + 2

    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    filename = f"stok_hareketleri_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/reports")
@admin_required
def reports():
    products = Product.query.order_by(Product.name).all()
    stock_status = []
    price_trends = []
    for product in products:
        available = product.available_quantity()
        last_cost = product.last_unit_cost()
        average_cost = product.average_unit_cost()
        total_cost = product.current_stock_value()
        entries = (
            StockEntry.query.filter_by(product_id=product.id)
            .order_by(StockEntry.timestamp.desc())
            .limit(5)
            .all()
        )
        stock_status.append(
            {
                "product": product,
                "available": available,
                "reorder_level": product.reorder_level,
                "total_cost": total_cost,
            }
        )
        price_trends.append(
            {
                "product": product,
                "last_cost": last_cost,
                "average_cost": average_cost,
                "recent_entries": entries,
            }
        )
    movements = (
        StockMovementLog.query.options(
            joinedload(StockMovementLog.product),
            joinedload(StockMovementLog.project),
            joinedload(StockMovementLog.user),
        )
        .order_by(StockMovementLog.timestamp.desc())
        .limit(50)
        .all()
    )
    return render_template(
        "reports.html",
        stock_status=stock_status,
        price_trends=price_trends,
        movements=movements,
    )


@app.route("/movements")
@manager_required
def movement_history():
    movements = (
        StockMovementLog.query.options(
            joinedload(StockMovementLog.product),
            joinedload(StockMovementLog.project),
            joinedload(StockMovementLog.user),
        )
        .order_by(StockMovementLog.timestamp.desc())
        .limit(100)
        .all()
    )
    return render_template("movements.html", movements=movements)


@app.route("/request-tracking")
@admin_required
def request_tracking():
    requests = (
        StockRequest.query.options(
            joinedload(StockRequest.product),
            joinedload(StockRequest.project),
            joinedload(StockRequest.requester),
            joinedload(StockRequest.manager),
            joinedload(StockRequest.first_approver),
            joinedload(StockRequest.approver),
        )
        .order_by(StockRequest.created_at.desc())
        .all()
    )
    request_groups = summarize_request_groups(requests)
    return render_template("request_tracking.html", request_groups=request_groups)


@app.route("/request-tracking/<string:group_key>/pdf")
@admin_required
def export_request_pdf(group_key: str):
    records = load_request_group_records(group_key)
    if not records:
        abort(404)
    group = summarize_request_groups(records)[0]
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=40,
        bottomMargin=40,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "RequestTitle",
        parent=styles["Heading1"],
        fontName="Helvetica",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#1f2937"),
        alignment=TA_LEFT,
    )
    label_style = ParagraphStyle(
        "RequestLabel",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#4b5563"),
    )
    info_style = ParagraphStyle(
        "RequestInfo",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=11,
        leading=15,
        textColor=colors.HexColor("#111827"),
    )
    table_header_style = ParagraphStyle(
        "RequestTableHeader",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        alignment=TA_CENTER,
        textColor=colors.white,
    )

    def pdf_safe(value: str | None, default: str = "-") -> str:
        if value in (None, ""):
            return default
        return normalize_turkish_ascii(str(value), default)

    story: list = []
    story.append(Paragraph(f"Talep Ozeti - {normalize_turkish_ascii(group['display_number'])}", title_style))
    story.append(Spacer(1, 14))

    created_at = format_local_datetime(group["created_at"])
    requester = group["requester"].username if group["requester"] else "-"
    manager = group["manager"].username if group.get("manager") else "-"
    status_label = group["status_label"]
    notes_value = group.get("notes") or "-"
    approved_at_display = format_local_datetime(group.get("approved_at"))

    metadata_rows = [
        [Paragraph("<b>Olusturma</b>", label_style), Paragraph(pdf_safe(created_at), info_style)],
        [Paragraph("<b>Talep Eden</b>", label_style), Paragraph(pdf_safe(requester), info_style)],
        [Paragraph("<b>Yonetici</b>", label_style), Paragraph(pdf_safe(manager), info_style)],
        [Paragraph("<b>Durum</b>", label_style), Paragraph(pdf_safe(status_label), info_style)],
        [Paragraph("<b>Onay Tarihi</b>", label_style), Paragraph(pdf_safe(approved_at_display), info_style)],
        [Paragraph("<b>Not</b>", label_style), Paragraph(pdf_safe(notes_value, "-"), info_style)],
    ]
    metadata_table = Table(metadata_rows, colWidths=[120, 360])
    metadata_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(metadata_table)
    story.append(Spacer(1, 18))

    line_headers = [
        Paragraph("<b>#</b>", table_header_style),
        Paragraph("<b>Urun</b>", table_header_style),
        Paragraph("<b>Miktar</b>", table_header_style),
        Paragraph("<b>Proje</b>", table_header_style),
        Paragraph("<b>Termin</b>", table_header_style),
        Paragraph("<b>Onay</b>", table_header_style),
        Paragraph("<b>Durum</b>", table_header_style),
        Paragraph("<b>Onaylayanlar</b>", table_header_style),
    ]
    line_data = [line_headers]
    for idx, line in enumerate(group["lines"], start=1):
        product_name = line["product"].name if line.get("product") else "-"
        due_text = line["due_date"].strftime("%d.%m.%Y") if line.get("due_date") else "-"
        project_name = line["project"].name if line.get("project") else "-"
        status_text = STATUS_LABELS.get(line["status"].lower(), line["status"]) if line.get("status") else "-"
        first_display = format_local_datetime(line.get("first_approved_at")) if line.get("first_approved_at") else None
        final_display = format_local_datetime(line.get("approved_at")) if line.get("approved_at") else None
        approval_parts = []
        if first_display:
            approval_parts.append(f"1. {first_display}")
        if final_display:
            approval_parts.append(f"2. {final_display}")
        approval_display = "\n".join(approval_parts) if approval_parts else "-"
        approver_parts = []
        if line.get("first_approver"):
            approver_parts.append(f"Satinalma: {line['first_approver'].username}")
        if line.get("approver"):
            approver_parts.append(f"Proje: {line['approver'].username}")
        approver_display = "\n".join(approver_parts) if approver_parts else "-"
        line_data.append(
            [
                Paragraph(str(idx), info_style),
                Paragraph(pdf_safe(product_name), info_style),
                Paragraph(format_decimal_value(line["quantity"]), info_style),
                Paragraph(pdf_safe(project_name), info_style),
                Paragraph(pdf_safe(due_text), info_style),
                Paragraph(pdf_safe(approval_display), info_style),
                Paragraph(pdf_safe(status_text), info_style),
                Paragraph(pdf_safe(approver_display), info_style),
            ]
        )

    lines_table = Table(
        line_data,
        colWidths=[30, 125, 55, 85, 60, 60, 60, 40],
        hAlign="LEFT",
    )
    lines_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563eb")),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#1d4ed8")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.HexColor("#f8fafc")]),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(lines_table)
    story.append(Spacer(1, 24))

    procurement_manager = None
    if g.user and g.user.role == "procurement_manager":
        procurement_manager = g.user
    if procurement_manager is None:
        procurement_manager = (
            User.query.filter_by(role="procurement_manager")
            .order_by(User.username.asc())
            .first()
        )
    procurement_name = procurement_manager.username if procurement_manager else "-"

    signature_rows = [
        [
            Paragraph("Talep Eden<br/><b>%s</b>" % pdf_safe(requester, "-"), label_style),
            Paragraph("Onaylayan<br/><b>%s</b>" % pdf_safe(manager, "-"), label_style),
            Paragraph("Satinalma Yoneticisi<br/><b>%s</b>" % pdf_safe(procurement_name, "-"), label_style),
        ],
        ["", "", ""],
    ]
    signature_table = Table(
        signature_rows,
        colWidths=[150, 150, 150],
        rowHeights=[None, 45],
        hAlign="LEFT",
    )
    signature_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
                ("GRID", (0, 1), (-1, 1), 0.7, colors.HexColor("#9ca3af")),
            ]
        )
    )
    story.append(signature_table)
    story.append(Spacer(1, 12))
    story.append(Paragraph("Stok Takip Sistemi", label_style))

    doc.build(story)
    buffer.seek(0)
    filename = group["display_number"].replace(" ", "_").replace("#", "") + ".pdf"
    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )


@app.route("/request-tracking/<string:group_key>/note", methods=["POST"])
@admin_required
def update_request_note(group_key: str):
    records = load_request_group_records(group_key)
    if not records:
        abort(404)
    group = summarize_request_groups(records)[0]
    note_text = request.form.get("note", "").strip()
    note_value = note_text or None
    for record in records:
        record.notes = note_value
        record.updated_at = datetime.datetime.utcnow()
    record_user_activity(
        "stock_request_note_update",
        f"{group['display_number']} talep notu güncellendi",
    )
    db.session.commit()
    flash("Talep notu güncellendi", "success")
    return redirect(url_for("request_tracking"))


@app.route("/users", methods=["GET", "POST"])
@admin_required
def manage_users():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "user")
        manager_id = request.form.get("manager_id")
        manager_id = int(manager_id) if manager_id else None
        if not username or not password:
            flash("Kullanıcı adı ve şifre zorunludur", "danger")
            return redirect(url_for("manage_users"))
        if User.query.filter_by(username=username).first():
            flash("Bu kullanıcı adı zaten mevcut", "danger")
            return redirect(url_for("manage_users"))
        if email and User.query.filter(User.email == email).first():
            flash("Bu e-posta başka bir kullanıcı tarafından kullanılıyor", "danger")
            return redirect(url_for("manage_users"))
        user = User(username=username, email=email or None, role=role, manager_id=manager_id)
        user.set_password(password)
        db.session.add(user)
        record_user_activity("user_create", f"{username} kullanıcısı oluşturuldu")
        db.session.commit()
        flash("Kullanıcı oluşturuldu", "success")
        return redirect(url_for("manage_users"))
    users = User.query.order_by(User.username.asc()).all()
    return render_template(
        "users.html",
        users=users,
        role_choices=ROLE_CHOICES,
        role_labels=ROLE_LABELS,
    )


@app.route("/users/<int:user_id>/reset", methods=["POST"])
@admin_required
def reset_password(user_id: int):
    user = User.query.get_or_404(user_id)
    new_password = request.form.get("password", "")
    if not new_password:
        flash("Yeni şifre giriniz", "danger")
        return redirect(url_for("manage_users"))
    user.set_password(new_password)
    db.session.commit()
    record_user_activity("user_reset_password", f"{user.username} şifresi güncellendi")
    flash("Şifre güncellendi", "success")
    return redirect(url_for("manage_users"))


@app.route("/users/<int:user_id>/update", methods=["POST"])
@admin_required
def update_user(user_id: int):
    user = User.query.get_or_404(user_id)
    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip()
    role = request.form.get("role", user.role)
    manager_value = request.form.get("manager_id", "").strip()
    manager_id = int(manager_value) if manager_value else None
    if not username:
        flash("Kullanıcı adı zorunludur", "danger")
        return redirect(url_for("manage_users"))
    existing_username = (
        User.query.filter(User.username == username, User.id != user_id).first()
    )
    if existing_username:
        flash("Bu kullanıcı adı başka bir kullanıcı tarafından kullanılıyor", "danger")
        return redirect(url_for("manage_users"))
    if email:
        existing_email = (
            User.query.filter(User.email == email, User.id != user_id).first()
        )
        if existing_email:
            flash("Bu e-posta başka bir kullanıcı tarafından kullanılıyor", "danger")
            return redirect(url_for("manage_users"))
    user.username = username
    user.email = email or None
    user.role = role
    user.manager_id = manager_id
    db.session.commit()
    record_user_activity("user_update", f"{username} bilgileri güncellendi")
    flash("Kullanıcı bilgileri güncellendi", "success")
    return redirect(url_for("manage_users"))


@app.route("/activity")
@admin_required
def activity_logs():
    logs = (
        UserActivityLog.query.order_by(UserActivityLog.timestamp.desc()).limit(100).all()
    )
    return render_template("activity_logs.html", logs=logs)


def bootstrap_defaults() -> None:
    if not User.query.filter_by(role="admin").first():
        admin = User(username="admin", role="admin")
        admin.set_password("admin123")
        db.session.add(admin)
        db.session.commit()
    if not Warehouse.query.first():
        db.session.add(Warehouse(name="Merkez Depo"))
    if not Project.query.first():
        db.session.add(Project(name="Genel Proje"))
    if not Category.query.first():
        db.session.add(Category(name="Genel"))
    db.session.commit()


@app.cli.command("init-db")
def init_db_command():
    """Initialize the database tables and bootstrap default records."""
    db.create_all()
    bootstrap_defaults()
    print("Veritabanı hazır")


@app.cli.command("create-admin")
@click.option("--username", prompt=True)
@click.option(
    "--password",
    prompt=True,
    hide_input=True,
    confirmation_prompt=True,
)
def create_admin_command(username: str, password: str) -> None:
    """Create or update an administrator account."""

    user = User.query.filter_by(username=username).first()
    if user is None:
        user = User(username=username, role="admin")
        action = "oluşturuldu"
        db.session.add(user)
    else:
        user.role = "admin"
        action = "güncellendi"

    user.set_password(password)
    db.session.flush()

    log = UserActivityLog(
        user_id=user.id,
        action="CLI: create-admin",
        details=f"{username} kullanıcısı {action}.",
    )
    db.session.add(log)
    db.session.commit()

    print(f"{username} kullanıcısı admin olarak {action}.")


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        bootstrap_defaults()
    app.run(debug=True, host="0.0.0.0", port=5000)
