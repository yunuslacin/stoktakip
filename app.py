import os
from datetime import datetime
from functools import wraps

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint, func
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, "stoktakip.db")

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DATABASE_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = "change-me"

db = SQLAlchemy(app)


class ActivityLog(db.Model):
    __tablename__ = "activity_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    action = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    details = db.Column(db.Text)


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="user")
    manager_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    manager = db.relationship("User", remote_side=[id])
    activities = db.relationship("ActivityLog", backref="user")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class Supplier(db.Model):
    __tablename__ = "suppliers"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    contact_info = db.Column(db.String(255))


class Warehouse(db.Model):
    __tablename__ = "warehouses"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)


class Project(db.Model):
    __tablename__ = "projects"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)


class Product(db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    sku = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.Text)
    low_stock_threshold = db.Column(db.Integer, default=0)

    inventory_lots = db.relationship("InventoryLot", backref="product")

    def current_quantity(self) -> int:
        return sum(lot.quantity_remaining for lot in self.inventory_lots)


class InventoryLot(db.Model):
    __tablename__ = "inventory_lots"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"))
    warehouse_id = db.Column(db.Integer, db.ForeignKey("warehouses.id"))
    invoice_number = db.Column(db.String(120))
    quantity_received = db.Column(db.Integer, nullable=False)
    quantity_remaining = db.Column(db.Integer, nullable=False)
    unit_cost = db.Column(db.Float, nullable=False)
    received_at = db.Column(db.DateTime, default=datetime.utcnow)

    supplier = db.relationship("Supplier")
    warehouse = db.relationship("Warehouse")

    __table_args__ = (
        CheckConstraint("quantity_received >= 0"),
        CheckConstraint("quantity_remaining >= 0"),
    )


class StockMovement(db.Model):
    __tablename__ = "stock_movements"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    lot_id = db.Column(db.Integer, db.ForeignKey("inventory_lots.id"))
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"))
    warehouse_id = db.Column(db.Integer, db.ForeignKey("warehouses.id"))
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"))
    movement_type = db.Column(db.String(20), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_cost = db.Column(db.Float)
    total_cost = db.Column(db.Float)
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    product = db.relationship("Product")
    user = db.relationship("User")
    lot = db.relationship("InventoryLot")
    project = db.relationship("Project")
    warehouse = db.relationship("Warehouse")
    supplier = db.relationship("Supplier")


class StockRequest(db.Model):
    __tablename__ = "stock_requests"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    requester_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"))
    quantity = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default="pending")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    decided_at = db.Column(db.DateTime)
    approver_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    note = db.Column(db.Text)

    product = db.relationship("Product")
    requester = db.relationship("User", foreign_keys=[requester_id])
    approver = db.relationship("User", foreign_keys=[approver_id])
    project = db.relationship("Project")


class PurchaseOrder(db.Model):
    __tablename__ = "purchase_orders"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default="pending")
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"))
    requester_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product = db.relationship("Product")
    supplier = db.relationship("Supplier")
    requester = db.relationship("User")


@app.before_request
def load_logged_in_user():
    user_id = session.get("user_id")
    if user_id is None:
        g.user = None
    else:
        g.user = User.query.get(user_id)


def login_required(role=None):
    def decorator(view):
        @wraps(view)
        def wrapped_view(**kwargs):
            if g.user is None:
                return redirect(url_for("login"))
            if role == "admin" and not g.user.is_admin:
                abort(403)
            return view(**kwargs)

        return wrapped_view

    return decorator


def log_activity(action: str, details: str = ""):
    if g.user is None:
        return
    log = ActivityLog(user_id=g.user.id, action=action, details=details)
    db.session.add(log)
    db.session.commit()


@app.cli.command("init-db")
def init_db_command():
    db.create_all()
    if not User.query.filter_by(username="admin").first():
        admin = User(username="admin", role="admin")
        admin.set_password("admin")
        db.session.add(admin)
        db.session.commit()
        print("Created default admin user (admin/admin)")
    print("Database initialized")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        user = User.query.filter(func.lower(User.username) == username.lower()).first()
        if user and user.check_password(password):
            session.clear()
            session["user_id"] = user.id
            g.user = user
            log_activity("login")
            return redirect(url_for("dashboard"))
        flash("Geçersiz kullanıcı adı veya şifre", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required()
def logout():
    log_activity("logout")
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required()
def dashboard():
    products = Product.query.all()
    low_stock_products = [p for p in products if p.current_quantity() <= p.low_stock_threshold]
    recent_movements = StockMovement.query.order_by(StockMovement.created_at.desc()).limit(10).all()
    pending_requests = StockRequest.query.filter_by(status="pending").count()
    return render_template(
        "dashboard.html",
        products=products,
        low_stock_products=low_stock_products,
        recent_movements=recent_movements,
        pending_requests=pending_requests,
    )


@app.route("/products")
@login_required()
def list_products():
    products = Product.query.all()
    return render_template("products.html", products=products)


@app.route("/products/new", methods=["GET", "POST"])
@login_required("admin")
def create_product():
    if request.method == "POST":
        product = Product(
            name=request.form["name"],
            sku=request.form["sku"],
            description=request.form.get("description"),
            low_stock_threshold=int(request.form.get("low_stock_threshold", 0)),
        )
        db.session.add(product)
        db.session.commit()
        log_activity("create_product", f"Product {product.name}")
        return redirect(url_for("list_products"))
    return render_template("product_form.html")


@app.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@login_required("admin")
def edit_product(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == "POST":
        product.name = request.form["name"]
        product.sku = request.form["sku"]
        product.description = request.form.get("description")
        product.low_stock_threshold = int(request.form.get("low_stock_threshold", 0))
        db.session.commit()
        log_activity("edit_product", f"Product {product.name}")
        return redirect(url_for("list_products"))
    return render_template("product_form.html", product=product)


def fifo_deplete(product: Product, quantity: int, project_id=None, note="", request_ref=None):
    remaining = quantity
    lots = (
        InventoryLot.query.filter_by(product_id=product.id)
        .filter(InventoryLot.quantity_remaining > 0)
        .order_by(InventoryLot.received_at.asc())
        .all()
    )
    total_taken = 0
    for lot in lots:
        if remaining <= 0:
            break
        taken = min(lot.quantity_remaining, remaining)
        lot.quantity_remaining -= taken
        movement = StockMovement(
            product_id=product.id,
            user_id=g.user.id if g.user else None,
            lot_id=lot.id,
            project_id=project_id,
            warehouse_id=lot.warehouse_id,
            supplier_id=lot.supplier_id,
            movement_type="OUT",
            quantity=taken,
            unit_cost=lot.unit_cost,
            total_cost=taken * lot.unit_cost,
            note=note,
        )
        db.session.add(movement)
        remaining -= taken
        total_taken += taken
    if remaining > 0:
        raise ValueError("Yeterli stok yok")
    return total_taken


@app.route("/inventory/in", methods=["GET", "POST"])
@login_required()
def stock_in():
    products = Product.query.all()
    suppliers = Supplier.query.all()
    warehouses = Warehouse.query.all()
    if request.method == "POST":
        product_id = int(request.form["product_id"])
        quantity = int(request.form["quantity"])
        unit_cost = float(request.form["unit_cost"])
        supplier_id = request.form.get("supplier_id") or None
        warehouse_id = request.form.get("warehouse_id") or None
        invoice_number = request.form.get("invoice_number") or None
        lot = InventoryLot(
            product_id=product_id,
            quantity_received=quantity,
            quantity_remaining=quantity,
            unit_cost=unit_cost,
            supplier_id=int(supplier_id) if supplier_id else None,
            warehouse_id=int(warehouse_id) if warehouse_id else None,
            invoice_number=invoice_number,
        )
        db.session.add(lot)
        db.session.flush()
        movement = StockMovement(
            product_id=product_id,
            user_id=g.user.id,
            lot_id=lot.id,
            warehouse_id=lot.warehouse_id,
            supplier_id=lot.supplier_id,
            movement_type="IN",
            quantity=quantity,
            unit_cost=unit_cost,
            total_cost=quantity * unit_cost,
            note=f"Fatura: {invoice_number}" if invoice_number else None,
        )
        db.session.add(movement)
        db.session.commit()
        log_activity("stock_in", f"Product {lot.product.name} - quantity {quantity}")
        flash("Stok girişi başarılı", "success")
        return redirect(url_for("stock_in"))
    return render_template(
        "stock_in.html",
        products=products,
        suppliers=suppliers,
        warehouses=warehouses,
    )


@app.route("/inventory/out", methods=["GET", "POST"])
@login_required()
def stock_out():
    products = Product.query.all()
    projects = Project.query.all()
    if request.method == "POST":
        product_id = int(request.form["product_id"])
        quantity = int(request.form["quantity"])
        project_id = int(request.form.get("project_id")) if request.form.get("project_id") else None
        product = Product.query.get_or_404(product_id)
        try:
            fifo_deplete(product, quantity, project_id=project_id, note=request.form.get("note"))
            db.session.commit()
            log_activity("stock_out", f"Product {product.name} - quantity {quantity}")
            flash("Stok çıkışı başarılı", "success")
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
        return redirect(url_for("stock_out"))
    return render_template("stock_out.html", products=products, projects=projects)


@app.route("/inventory/adjust", methods=["GET", "POST"])
@login_required()
def stock_adjust():
    products = Product.query.all()
    if request.method == "POST":
        product_id = int(request.form["product_id"])
        quantity = int(request.form["quantity"])
        reason = request.form.get("reason")
        product = Product.query.get_or_404(product_id)
        note = f"Düzeltme: {reason}"
        if quantity > 0:
            lot = InventoryLot(
                product_id=product_id,
                quantity_received=quantity,
                quantity_remaining=quantity,
                unit_cost=float(request.form.get("unit_cost", 0) or 0),
            )
            db.session.add(lot)
            db.session.flush()
            movement = StockMovement(
                product_id=product_id,
                user_id=g.user.id,
                lot_id=lot.id,
                movement_type="ADJUST",
                quantity=quantity,
                unit_cost=lot.unit_cost,
                total_cost=quantity * lot.unit_cost,
                note=note,
            )
            db.session.add(movement)
        else:
            try:
                fifo_deplete(product, abs(quantity), note=note)
            except ValueError as exc:
                db.session.rollback()
                flash(str(exc), "danger")
                return redirect(url_for("stock_adjust"))
        db.session.commit()
        log_activity("stock_adjust", f"Product {product.name} - quantity {quantity}")
        flash("Stok düzeltmesi kaydedildi", "success")
        return redirect(url_for("stock_adjust"))
    return render_template("stock_adjust.html", products=products)


@app.route("/requests", methods=["GET", "POST"])
@login_required()
def manage_requests():
    products = Product.query.all()
    projects = Project.query.all()
    if request.method == "POST":
        product_id = int(request.form["product_id"])
        quantity = int(request.form["quantity"])
        project_id = int(request.form.get("project_id")) if request.form.get("project_id") else None
        note = request.form.get("note")
        stock_request = StockRequest(
            product_id=product_id,
            requester_id=g.user.id,
            project_id=project_id,
            quantity=quantity,
            note=note,
        )
        db.session.add(stock_request)
        db.session.commit()
        log_activity("create_request", f"Request {stock_request.id}")
        flash("Talep oluşturuldu", "success")
        return redirect(url_for("manage_requests"))
    if g.user.is_admin:
        requests_qs = StockRequest.query.order_by(StockRequest.created_at.desc()).all()
    else:
        requests_qs = StockRequest.query.filter(
            (StockRequest.requester_id == g.user.id)
            | (StockRequest.requester.has(manager_id=g.user.id))
        ).order_by(StockRequest.created_at.desc()).all()
    return render_template("requests.html", requests=requests_qs, products=products, projects=projects)


@app.route("/requests/<int:request_id>/approve", methods=["POST"])
@login_required()
def approve_request(request_id):
    stock_request = StockRequest.query.get_or_404(request_id)
    if not (g.user.is_admin or stock_request.requester.manager_id == g.user.id):
        abort(403)
    if stock_request.status != "pending":
        flash("Talep güncel durumda değil", "warning")
        return redirect(url_for("manage_requests"))
    product = stock_request.product
    try:
        fifo_deplete(product, stock_request.quantity, project_id=stock_request.project_id, note="Talep karşılama")
        stock_request.status = "approved"
        stock_request.decided_at = datetime.utcnow()
        stock_request.approver_id = g.user.id
        db.session.commit()
        log_activity("stock_out", f"Product {product.name} - quantity {stock_request.quantity}")
        log_activity("approve_request", f"Request {stock_request.id}")
        flash("Talep onaylandı", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("manage_requests"))


@app.route("/requests/<int:request_id>/reject", methods=["POST"])
@login_required()
def reject_request(request_id):
    stock_request = StockRequest.query.get_or_404(request_id)
    if not (g.user.is_admin or stock_request.requester.manager_id == g.user.id):
        abort(403)
    if stock_request.status != "pending":
        flash("Talep güncel durumda değil", "warning")
        return redirect(url_for("manage_requests"))
    stock_request.status = "rejected"
    stock_request.decided_at = datetime.utcnow()
    stock_request.approver_id = g.user.id
    db.session.commit()
    log_activity("reject_request", f"Request {stock_request.id}")
    flash("Talep reddedildi", "info")
    return redirect(url_for("manage_requests"))


@app.route("/orders", methods=["GET", "POST"])
@login_required("admin")
def manage_orders():
    products = Product.query.all()
    suppliers = Supplier.query.all()
    orders = PurchaseOrder.query.order_by(PurchaseOrder.created_at.desc()).all()
    if request.method == "POST":
        order = PurchaseOrder(
            product_id=int(request.form["product_id"]),
            quantity=int(request.form["quantity"]),
            supplier_id=int(request.form.get("supplier_id")) if request.form.get("supplier_id") else None,
            status=request.form.get("status", "pending"),
            requester_id=g.user.id,
        )
        db.session.add(order)
        db.session.commit()
        log_activity("create_order", f"Order {order.id}")
        flash("Sipariş oluşturuldu", "success")
        return redirect(url_for("manage_orders"))
    return render_template("orders.html", orders=orders, products=products, suppliers=suppliers)


@app.route("/orders/<int:order_id>/status", methods=["POST"])
@login_required("admin")
def update_order_status(order_id):
    order = PurchaseOrder.query.get_or_404(order_id)
    order.status = request.form["status"]
    db.session.commit()
    log_activity("update_order_status", f"Order {order.id} -> {order.status}")
    flash("Sipariş durumu güncellendi", "info")
    return redirect(url_for("manage_orders"))


@app.route("/references", methods=["GET", "POST"])
@login_required("admin")
def manage_references():
    suppliers = Supplier.query.order_by(Supplier.name).all()
    warehouses = Warehouse.query.order_by(Warehouse.name).all()
    projects = Project.query.order_by(Project.name).all()
    if request.method == "POST":
        entity = request.form["entity"]
        name = request.form["name"].strip()
        if entity == "supplier":
            supplier = Supplier(name=name, contact_info=request.form.get("contact_info"))
            db.session.add(supplier)
            db.session.commit()
            log_activity("create_supplier", supplier.name)
            flash("Tedarikçi eklendi", "success")
        elif entity == "warehouse":
            warehouse = Warehouse(name=name)
            db.session.add(warehouse)
            db.session.commit()
            log_activity("create_warehouse", warehouse.name)
            flash("Depo eklendi", "success")
        elif entity == "project":
            project = Project(name=name, description=request.form.get("description"))
            db.session.add(project)
            db.session.commit()
            log_activity("create_project", project.name)
            flash("Proje eklendi", "success")
        return redirect(url_for("manage_references"))
    return render_template(
        "references.html",
        suppliers=suppliers,
        warehouses=warehouses,
        projects=projects,
    )


@app.route("/reports/inventory")
@login_required()
def inventory_report():
    products = Product.query.all()
    return render_template("report_inventory.html", products=products)


@app.route("/reports/movements")
@login_required()
def movement_report():
    movements = StockMovement.query.order_by(StockMovement.created_at.desc()).limit(200).all()
    return render_template("report_movements.html", movements=movements)


@app.route("/reports/prices")
@login_required()
def price_report():
    price_data = (
        db.session.query(
            Product.name.label("product_name"),
            InventoryLot.unit_cost,
            InventoryLot.received_at,
        )
        .join(Product, InventoryLot.product_id == Product.id)
        .order_by(Product.name, InventoryLot.received_at)
        .all()
    )
    return render_template("report_prices.html", price_data=price_data)


@app.route("/users", methods=["GET", "POST"])
@login_required("admin")
def manage_users():
    users = User.query.all()
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        role = request.form.get("role", "user")
        manager_id = request.form.get("manager_id") or None
        user = User(username=username, role=role, manager_id=int(manager_id) if manager_id else None)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        log_activity("create_user", f"User {username}")
        flash("Kullanıcı oluşturuldu", "success")
        return redirect(url_for("manage_users"))
    return render_template("users.html", users=users)


@app.route("/users/<int:user_id>/reset", methods=["POST"])
@login_required("admin")
def reset_password(user_id):
    user = User.query.get_or_404(user_id)
    new_password = request.form["new_password"]
    user.set_password(new_password)
    db.session.commit()
    log_activity("reset_password", f"User {user.username}")
    flash("Şifre güncellendi", "success")
    return redirect(url_for("manage_users"))


@app.route("/activity")
@login_required("admin")
def activity_log():
    logs = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).limit(200).all()
    return render_template("activity_log.html", logs=logs)


@app.context_processor
def inject_helpers():
    def format_datetime(dt):
        if not dt:
            return "-"
        return dt.strftime("%d.%m.%Y %H:%M")

    return dict(format_datetime=format_datetime)


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
