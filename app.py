import datetime
import io
import os
from functools import wraps
from pathlib import Path

import click
from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   send_file, session, url_for)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import joinedload
from openpyxl import Workbook
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


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="user")
    manager_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    manager = db.relationship("User", remote_side=[id], uselist=False)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_manager(self) -> bool:
        return self.role in {"admin", "manager"}


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


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    sku = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    reorder_level = db.Column(db.Integer, default=0)
    image_filename = db.Column(db.String(255), nullable=True)

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
    status = db.Column(db.String(20), default="pending")
    manager_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    notes = db.Column(db.Text, nullable=True)
    due_date = db.Column(db.Date, nullable=True)

    product = db.relationship("Product")
    requester = db.relationship("User", foreign_keys=[requester_id])
    manager = db.relationship("User", foreign_keys=[manager_id])
    approver = db.relationship("User", foreign_keys=[approved_by])


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
    products = Product.query.order_by(Product.name).all()
    low_stock = [p for p in products if p.available_quantity() <= p.reorder_level]
    pending_requests = (
        StockRequest.query.filter_by(status="pending")
        .order_by(StockRequest.created_at.asc())
        .all()
    )
    pending_orders = (
        PurchaseOrder.query.filter(PurchaseOrder.status.in_(["pending", "onaylandı"]))
        .order_by(PurchaseOrder.created_at.desc())
        .all()
    )
    recent_movements = (
        StockMovementLog.query.order_by(StockMovementLog.timestamp.desc()).limit(10).all()
    )
    return render_template(
        "dashboard.html",
        products=products,
        low_stock=low_stock,
        pending_requests=pending_requests,
        pending_orders=pending_orders,
        recent_movements=recent_movements,
    )


@app.route("/products")
@login_required
def list_products():
    products = Product.query.order_by(Product.name.asc()).all()
    warehouses = Warehouse.query.all()
    return render_template("products.html", products=products, warehouses=warehouses)


@app.route("/products/new", methods=["POST"])
@admin_required
def create_product():
    name = request.form.get("name", "").strip()
    sku = request.form.get("sku", "").strip()
    try:
        reorder_level = int(request.form.get("reorder_level", 0) or 0)
    except (TypeError, ValueError):
        reorder_level = 0
    if not name or not sku:
        flash("Ürün adı ve ürün kodu zorunludur", "danger")
        return redirect(url_for("list_products"))
    duplicate = Product.query.filter(
        (Product.name == name) | (Product.sku == sku)
    ).first()
    if duplicate:
        if duplicate.name == name:
            flash("Bu isimde bir ürün zaten mevcut", "warning")
        else:
            flash("Bu ürün kodu başka bir ürün tarafından kullanılıyor", "warning")
        return redirect(url_for("list_products"))
    product = Product(name=name, sku=sku, reorder_level=reorder_level)
    db.session.add(product)
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
    return render_template(
        "product_detail.html",
        product=product,
        entries=entries,
        exits=exits,
        adjustments=adjustments,
        requests=requests,
        available=available,
    )


@app.route("/stock/entry", methods=["GET", "POST"])
@manager_required
def stock_entry():
    products = Product.query.order_by(Product.name).all()
    warehouses = Warehouse.query.order_by(Warehouse.name).all()
    if request.method == "POST":
        product_id = int(request.form.get("product_id"))
        quantity = float(request.form.get("quantity"))
        unit_cost = float(request.form.get("unit_cost"))
        supplier = request.form.get("supplier", "").strip() or None
        invoice_number = request.form.get("invoice_number", "").strip() or None
        warehouse_id = request.form.get("warehouse_id")
        warehouse_id = int(warehouse_id) if warehouse_id else None
        entry = StockEntry(
            product_id=product_id,
            quantity=quantity,
            remaining_quantity=quantity,
            unit_cost=unit_cost,
            supplier=supplier,
            invoice_number=invoice_number,
            warehouse_id=warehouse_id,
            created_by=g.user.id if g.user else None,
        )
        db.session.add(entry)
        total_cost = quantity * unit_cost
        record_movement(
            product_id,
            "giriş",
            quantity,
            f"Tedarikçi: {supplier or '-'}, Fatura: {invoice_number or '-'}",
            cost=total_cost,
        )
        record_user_activity("stock_entry", f"Ürün {product_id} için {quantity} adet stok girişi")
        db.session.commit()
        flash("Stok girişi kaydedildi", "success")
        return redirect(url_for("stock_entry"))
    return render_template("stock_entry.html", products=products, warehouses=warehouses)


@app.route("/stock/exit", methods=["GET", "POST"])
@manager_required
def stock_exit():
    products = Product.query.order_by(Product.name).all()
    projects = Project.query.order_by(Project.name).all()
    if request.method == "POST":
        product_id = int(request.form.get("product_id"))
        quantity = float(request.form.get("quantity"))
        project_id = request.form.get("project_id")
        project_id = int(project_id) if project_id else None
        product = Product.query.get_or_404(product_id)
        try:
            total_cost, notes = apply_fifo_deduction(product, quantity)
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return redirect(url_for("stock_exit"))
        exit_record = StockExit(
            product_id=product_id,
            quantity=quantity,
            project_id=project_id,
            total_cost=total_cost,
            created_by=g.user.id if g.user else None,
        )
        db.session.add(exit_record)
        project_detail = Project.query.get(project_id) if project_id else None
        record_movement(
            product_id,
            "çıkış",
            -quantity,
            f"Proje: {project_detail.name if project_detail else '-'} | {'; '.join(notes)}",
            cost=total_cost,
            project_id=project_id,
        )
        record_user_activity("stock_exit", f"Ürün {product_id} için {quantity} adet stok çıkışı")
        db.session.commit()
        flash("Stok çıkışı kaydedildi", "success")
        return redirect(url_for("stock_exit"))
    return render_template("stock_exit.html", products=products, projects=projects)


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
    min_due_date = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    if request.method == "POST":
        product_id = int(request.form.get("product_id"))
        quantity = float(request.form.get("quantity"))
        notes = request.form.get("notes", "")
        due_date_raw = request.form.get("due_date", "").strip()
        due_date = None
        if due_date_raw:
            try:
                due_date = datetime.datetime.strptime(due_date_raw, "%Y-%m-%d").date()
            except ValueError:
                flash("Geçerli bir termin tarihi seçiniz", "danger")
                return redirect(url_for("stock_requests"))
            if due_date <= datetime.date.today():
                flash("Termin tarihi bugünden sonraki bir tarih olmalıdır", "danger")
                return redirect(url_for("stock_requests"))
        manager_id = g.user.manager_id
        request_record = StockRequest(
            product_id=product_id,
            quantity=quantity,
            requester_id=g.user.id,
            manager_id=manager_id,
            notes=notes,
            due_date=due_date,
        )
        db.session.add(request_record)
        record_user_activity("stock_request_create", f"Ürün {product_id} için {quantity} adet talep")
        db.session.commit()
        flash("Talep oluşturuldu", "success")
        return redirect(url_for("stock_requests"))
    my_requests = (
        StockRequest.query.filter_by(requester_id=g.user.id)
        .order_by(StockRequest.created_at.desc())
        .all()
    )
    to_approve = []
    if g.user.is_manager:
        to_approve = (
            StockRequest.query.filter_by(manager_id=g.user.id, status="pending")
            .order_by(StockRequest.created_at.asc())
            .all()
        )
    return render_template(
        "stock_requests.html",
        products=products,
        my_requests=my_requests,
        to_approve=to_approve,
        min_due_date=min_due_date,
    )


@app.route("/requests/<int:request_id>/approve", methods=["POST"])
@manager_required
def approve_request(request_id: int):
    stock_request = StockRequest.query.get_or_404(request_id)
    if stock_request.manager_id != g.user.id:
        abort(403)
    stock_request.status = "approved"
    stock_request.approved_by = g.user.id
    stock_request.updated_at = datetime.datetime.utcnow()
    record_user_activity("stock_request_approve", f"Talep {request_id} onaylandı")
    db.session.commit()
    flash("Talep onaylandı", "success")
    return redirect(url_for("stock_requests"))


@app.route("/requests/<int:request_id>/reject", methods=["POST"])
@manager_required
def reject_request(request_id: int):
    stock_request = StockRequest.query.get_or_404(request_id)
    if stock_request.manager_id != g.user.id:
        abort(403)
    stock_request.status = "rejected"
    stock_request.updated_at = datetime.datetime.utcnow()
    record_user_activity("stock_request_reject", f"Talep {request_id} reddedildi")
    db.session.commit()
    flash("Talep reddedildi", "info")
    return redirect(url_for("stock_requests"))


@app.route("/requests/<int:request_id>/fulfill", methods=["POST"])
@manager_required
def fulfill_request(request_id: int):
    stock_request = StockRequest.query.get_or_404(request_id)
    if stock_request.status != "approved":
        flash("Sadece onaylı talepler karşılanabilir", "warning")
        return redirect(url_for("stock_requests"))
    product = stock_request.product
    try:
        total_cost, notes = apply_fifo_deduction(product, stock_request.quantity)
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
        return redirect(url_for("stock_requests"))
    exit_record = StockExit(
        product_id=product.id,
        quantity=stock_request.quantity,
        project_id=None,
        total_cost=total_cost,
        created_by=g.user.id if g.user else None,
    )
    db.session.add(exit_record)
    stock_request.status = "tamamlandı"
    stock_request.updated_at = datetime.datetime.utcnow()
    record_movement(
        product.id,
        "talep-karşılama",
        -stock_request.quantity,
        f"Talep #{stock_request.id} karşılandı. {'; '.join(notes)}",
        cost=total_cost,
    )
    record_user_activity("stock_request_fulfill", f"Talep {request_id} karşılandı")
    db.session.commit()
    flash("Talep karşılandı", "success")
    return redirect(url_for("stock_requests"))


@app.route("/orders", methods=["GET", "POST"])
@manager_required
def purchase_orders():
    products = Product.query.order_by(Product.name).all()
    if request.method == "POST":
        product_id = int(request.form.get("product_id"))
        quantity = float(request.form.get("quantity"))
        supplier = request.form.get("supplier", "").strip()
        expected_date_raw = request.form.get("expected_date", "").strip()
        notes = request.form.get("notes", "")
        expected_date = None
        if expected_date_raw:
            expected_date = datetime.datetime.strptime(expected_date_raw, "%Y-%m-%d").date()
        order = PurchaseOrder(
            product_id=product_id,
            quantity=quantity,
            supplier=supplier,
            expected_date=expected_date,
            notes=notes,
            created_by=g.user.id if g.user else None,
        )
        db.session.add(order)
        record_user_activity("purchase_order_create", f"{supplier} tedarikçisinden {quantity} adet sipariş")
        db.session.commit()
        flash("Sipariş oluşturuldu", "success")
        return redirect(url_for("purchase_orders"))
    orders = PurchaseOrder.query.order_by(PurchaseOrder.created_at.desc()).all()
    return render_template("purchase_orders.html", products=products, orders=orders)


@app.route("/orders/<int:order_id>/status", methods=["POST"])
@manager_required
def update_order_status(order_id: int):
    order = PurchaseOrder.query.get_or_404(order_id)
    status = request.form.get("status")
    order.status = status
    db.session.commit()
    record_user_activity("purchase_order_status", f"Sipariş {order_id} durumu {status}")
    flash("Sipariş durumu güncellendi", "success")
    return redirect(url_for("purchase_orders"))


@app.route("/projects", methods=["GET", "POST"])
@manager_required
def manage_projects():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip() or None
        if not name:
            flash("Proje adı zorunludur", "danger")
            return redirect(url_for("manage_projects"))
        if Project.query.filter_by(name=name).first():
            flash("Bu isimde bir proje zaten mevcut", "warning")
            return redirect(url_for("manage_projects"))
        project = Project(name=name, description=description)
        db.session.add(project)
        record_user_activity("project_create", f"{name} projesi oluşturuldu")
        db.session.commit()
        flash("Proje eklendi", "success")
        return redirect(url_for("manage_projects"))
    projects = Project.query.order_by(Project.name.asc()).all()
    return render_template("projects.html", projects=projects)


@app.route("/projects/<int:project_id>", methods=["POST"])
@manager_required
def update_project(project_id: int):
    project = Project.query.get_or_404(project_id)
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip() or None
    if not name:
        flash("Proje adı zorunludur", "danger")
        return redirect(url_for("manage_projects"))
    duplicate = Project.query.filter(Project.id != project.id, Project.name == name).first()
    if duplicate:
        flash("Bu isimde başka bir proje bulunuyor", "warning")
        return redirect(url_for("manage_projects"))
    project.name = name
    project.description = description
    record_user_activity("project_update", f"{project.name} projesi güncellendi")
    db.session.commit()
    flash("Proje güncellendi", "success")
    return redirect(url_for("manage_projects"))


@app.route("/products/<int:product_id>/update", methods=["POST"])
@admin_required
def update_product(product_id: int):
    product = Product.query.get_or_404(product_id)
    name = request.form.get("name", "").strip()
    sku = request.form.get("sku", "").strip()
    try:
        reorder_level = int(request.form.get("reorder_level", product.reorder_level) or product.reorder_level)
    except (TypeError, ValueError):
        reorder_level = product.reorder_level
    if not name or not sku:
        flash("Ürün adı ve ürün kodu zorunludur", "danger")
        return redirect(url_for("product_detail", product_id=product.id))
    duplicate = Product.query.filter(
        Product.id != product.id,
        (Product.name == name) | (Product.sku == sku),
    ).first()
    if duplicate:
        if duplicate.name == name:
            flash("Bu isimde başka bir ürün mevcut", "warning")
        else:
            flash("Bu ürün kodu başka bir ürün tarafından kullanılıyor", "warning")
        return redirect(url_for("product_detail", product_id=product.id))
    product.name = name
    product.sku = sku
    product.reorder_level = reorder_level

    image_file = request.files.get("image")
    if image_file and image_file.filename:
        if not allowed_file(image_file.filename):
            flash("Desteklenmeyen dosya formatı", "danger")
            return redirect(url_for("product_detail", product_id=product.id))
        filename = secure_filename(image_file.filename)
        ext = Path(filename).suffix
        unique_name = f"product_{product.id}_{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}" + ext
        save_path = Path(app.config["UPLOAD_FOLDER"]) / unique_name
        image_file.save(save_path)
        if product.image_filename and product.image_filename != unique_name:
            old_path = Path(app.config["UPLOAD_FOLDER"]) / product.image_filename
            if old_path.exists():
                old_path.unlink()
        product.image_filename = unique_name

    record_user_activity("product_update", f"{product.name} ürünü güncellendi")
    db.session.commit()
    flash("Ürün güncellendi", "success")
    return redirect(url_for("product_detail", product_id=product.id))


@app.route("/reports/movements/export")
@manager_required
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
@manager_required
def reports():
    products = Product.query.order_by(Product.name).all()
    stock_status = []
    price_trends = []
    for product in products:
        available = product.available_quantity()
        last_cost = product.last_unit_cost()
        average_cost = product.average_unit_cost()
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


@app.route("/users", methods=["GET", "POST"])
@admin_required
def manage_users():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
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
        user = User(username=username, role=role, manager_id=manager_id)
        user.set_password(password)
        db.session.add(user)
        record_user_activity("user_create", f"{username} kullanıcısı oluşturuldu")
        db.session.commit()
        flash("Kullanıcı oluşturuldu", "success")
        return redirect(url_for("manage_users"))
    users = User.query.order_by(User.username.asc()).all()
    return render_template("users.html", users=users)


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
