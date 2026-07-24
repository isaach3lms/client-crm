import os
import secrets
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, redirect, url_for, request, flash, abort
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash

from models import db, User, Client, Project, Invite, Deal, Prospect, ChatMessage

STATUS_CHOICES = ["Not Started", "In Progress", "On Hold", "Completed"]
STAGE_CHOICES = ["Lead", "Proposal", "Won", "Lost"]
PROSPECT_STATUS_CHOICES = ["New", "Contacted", "Interested", "Not Interested", "Converted"]
PROSPECT_TYPE_CHOICES = ["Church", "Person"]


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")

    db_url = os.environ.get("DATABASE_URL", "sqlite:///local.db")
    # Render provides postgres:// but SQLAlchemy needs postgresql://
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    login_manager = LoginManager()
    login_manager.login_view = "login"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    def _run_startup_migrations():
        """Adds the is_admin column to a pre-existing users table (older deployments
        of this app) without touching any existing rows, then makes sure at least
        one admin exists by promoting the earliest-created user."""
        from sqlalchemy import inspect, text

        inspector = inspect(db.engine)
        columns = [c["name"] for c in inspector.get_columns("users")]

        if "is_admin" not in columns:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT FALSE"))

        if not User.query.filter_by(is_admin=True).first():
            earliest_user = User.query.order_by(User.id).first()
            if earliest_user:
                earliest_user.is_admin = True
                db.session.commit()

    with app.app_context():
        db.create_all()
        _run_startup_migrations()

    def admin_required(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated or not current_user.is_admin:
                abort(403)
            return f(*args, **kwargs)
        return wrapper

    def _abort_404():
        abort(404)

    # ---------- Auth ----------
    @app.route("/register", methods=["GET", "POST"])
    def register():
        # First-ever user becomes admin with no invite needed (bootstrap).
        is_first_user = User.query.count() == 0
        token = request.args.get("token") or request.form.get("token", "")
        invite = None

        if not is_first_user:
            invite = Invite.query.filter_by(token=token, used=False).first() if token else None
            if not invite:
                flash("This registration link is invalid or has already been used. Ask an admin for a new invite.", "error")
                return redirect(url_for("login"))

        if request.method == "POST":
            username = request.form["username"].strip()
            email = request.form["email"].strip()
            password = request.form["password"]

            if User.query.filter_by(username=username).first():
                flash("That username is already taken.", "error")
                return redirect(url_for("register", token=token))

            user = User(
                username=username,
                email=email,
                password_hash=generate_password_hash(password),
                is_admin=is_first_user,
            )
            db.session.add(user)

            if invite:
                invite.used = True

            db.session.commit()
            flash("Account created. You can log in now.", "success")
            return redirect(url_for("login"))

        return render_template("register.html", token=token, is_first_user=is_first_user)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form["username"].strip()
            password = request.form["password"]
            user = User.query.filter_by(username=username).first()
            if user and check_password_hash(user.password_hash, password):
                login_user(user)
                return redirect(url_for("dashboard"))
            flash("Invalid username or password.", "error")
        no_users_yet = User.query.count() == 0
        return render_template("login.html", no_users_yet=no_users_yet)

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("login"))

    # ---------- Dashboard ----------
    @app.route("/")
    @login_required
    def dashboard():
        client_count = Client.query.count()
        prospect_count = Prospect.query.filter(Prospect.status != "Converted").count()
        project_count = Project.query.count()
        recent_projects = Project.query.order_by(Project.created_at.desc()).limit(5).all()

        open_deals = Deal.query.filter(Deal.stage.in_(["Lead", "Proposal"])).all()
        pipeline_value = sum((d.value or 0) for d in open_deals)
        won_deals_count = Deal.query.filter_by(stage="Won").count()

        return render_template(
            "dashboard.html",
            client_count=client_count,
            prospect_count=prospect_count,
            project_count=project_count,
            recent_projects=recent_projects,
            open_deals_count=len(open_deals),
            pipeline_value=pipeline_value,
            won_deals_count=won_deals_count,
        )

    # ---------- Clients ----------
    @app.route("/clients")
    @login_required
    def clients():
        all_clients = Client.query.order_by(Client.name).all()
        return render_template("clients.html", clients=all_clients)

    @app.route("/clients/new", methods=["GET", "POST"])
    @login_required
    def new_client():
        if request.method == "POST":
            client = Client(
                name=request.form["name"].strip(),
                contact_name=request.form.get("contact_name", "").strip(),
                contact_email=request.form.get("contact_email", "").strip(),
                contact_phone=request.form.get("contact_phone", "").strip(),
                notes=request.form.get("notes", "").strip(),
            )
            db.session.add(client)
            db.session.commit()
            flash("Client added.", "success")
            return redirect(url_for("clients"))
        return render_template("client_form.html", client=None)

    @app.route("/clients/<int:client_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_client(client_id):
        client = db.session.get(Client, client_id) or _abort_404()
        if request.method == "POST":
            client.name = request.form["name"].strip()
            client.contact_name = request.form.get("contact_name", "").strip()
            client.contact_email = request.form.get("contact_email", "").strip()
            client.contact_phone = request.form.get("contact_phone", "").strip()
            client.notes = request.form.get("notes", "").strip()
            db.session.commit()
            flash("Client updated.", "success")
            return redirect(url_for("clients"))
        return render_template("client_form.html", client=client)

    @app.route("/clients/<int:client_id>/delete", methods=["POST"])
    @login_required
    def delete_client(client_id):
        client = db.session.get(Client, client_id) or _abort_404()
        db.session.delete(client)
        db.session.commit()
        flash("Client deleted.", "success")
        return redirect(url_for("clients"))

    # ---------- Projects ----------
    @app.route("/projects")
    @login_required
    def projects():
        all_projects = Project.query.order_by(Project.created_at.desc()).all()
        return render_template("projects.html", projects=all_projects)

    @app.route("/projects/new", methods=["GET", "POST"])
    @login_required
    def new_project():
        clients_list = Client.query.order_by(Client.name).all()
        users_list = User.query.order_by(User.username).all()
        if request.method == "POST":
            due_date = request.form.get("due_date") or None
            project = Project(
                name=request.form["name"].strip(),
                client_id=int(request.form["client_id"]),
                assigned_to_id=int(request.form["assigned_to_id"]) if request.form.get("assigned_to_id") else None,
                status=request.form.get("status", STATUS_CHOICES[0]),
                description=request.form.get("description", "").strip(),
                due_date=datetime.strptime(due_date, "%Y-%m-%d") if due_date else None,
            )
            db.session.add(project)
            db.session.commit()
            flash("Project added.", "success")
            return redirect(url_for("projects"))
        return render_template(
            "project_form.html",
            project=None,
            clients=clients_list,
            users=users_list,
            statuses=STATUS_CHOICES,
        )

    @app.route("/projects/<int:project_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_project(project_id):
        project = db.session.get(Project, project_id) or _abort_404()
        clients_list = Client.query.order_by(Client.name).all()
        users_list = User.query.order_by(User.username).all()
        if request.method == "POST":
            due_date = request.form.get("due_date") or None
            project.name = request.form["name"].strip()
            project.client_id = int(request.form["client_id"])
            project.assigned_to_id = int(request.form["assigned_to_id"]) if request.form.get("assigned_to_id") else None
            project.status = request.form.get("status", STATUS_CHOICES[0])
            project.description = request.form.get("description", "").strip()
            project.due_date = datetime.strptime(due_date, "%Y-%m-%d") if due_date else None
            db.session.commit()
            flash("Project updated.", "success")
            return redirect(url_for("projects"))
        return render_template(
            "project_form.html",
            project=project,
            clients=clients_list,
            users=users_list,
            statuses=STATUS_CHOICES,
        )

    @app.route("/projects/<int:project_id>/delete", methods=["POST"])
    @login_required
    def delete_project(project_id):
        project = db.session.get(Project, project_id) or _abort_404()
        db.session.delete(project)
        db.session.commit()
        flash("Project deleted.", "success")
        return redirect(url_for("projects"))

    # ---------- Prospects ----------
    @app.route("/prospects")
    @login_required
    def prospects():
        all_prospects = Prospect.query.order_by(Prospect.created_at.desc()).all()
        return render_template("prospects.html", prospects=all_prospects)

    @app.route("/prospects/new", methods=["GET", "POST"])
    @login_required
    def new_prospect():
        users_list = User.query.order_by(User.username).all()
        if request.method == "POST":
            prospect = Prospect(
                name=request.form["name"].strip(),
                prospect_type=request.form.get("prospect_type", PROSPECT_TYPE_CHOICES[0]),
                contact_name=request.form.get("contact_name", "").strip(),
                contact_email=request.form.get("contact_email", "").strip(),
                contact_phone=request.form.get("contact_phone", "").strip(),
                status=request.form.get("status", PROSPECT_STATUS_CHOICES[0]),
                notes=request.form.get("notes", "").strip(),
                assigned_to_id=int(request.form["assigned_to_id"]) if request.form.get("assigned_to_id") else None,
            )
            db.session.add(prospect)
            db.session.commit()
            flash("Prospect added.", "success")
            return redirect(url_for("prospects"))
        return render_template(
            "prospect_form.html", prospect=None, users=users_list,
            statuses=PROSPECT_STATUS_CHOICES, types=PROSPECT_TYPE_CHOICES,
        )

    @app.route("/prospects/<int:prospect_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_prospect(prospect_id):
        prospect = db.session.get(Prospect, prospect_id) or _abort_404()
        users_list = User.query.order_by(User.username).all()
        if request.method == "POST":
            prospect.name = request.form["name"].strip()
            prospect.prospect_type = request.form.get("prospect_type", PROSPECT_TYPE_CHOICES[0])
            prospect.contact_name = request.form.get("contact_name", "").strip()
            prospect.contact_email = request.form.get("contact_email", "").strip()
            prospect.contact_phone = request.form.get("contact_phone", "").strip()
            prospect.status = request.form.get("status", PROSPECT_STATUS_CHOICES[0])
            prospect.notes = request.form.get("notes", "").strip()
            prospect.assigned_to_id = int(request.form["assigned_to_id"]) if request.form.get("assigned_to_id") else None
            db.session.commit()
            flash("Prospect updated.", "success")
            return redirect(url_for("prospects"))
        return render_template(
            "prospect_form.html", prospect=prospect, users=users_list,
            statuses=PROSPECT_STATUS_CHOICES, types=PROSPECT_TYPE_CHOICES,
        )

    @app.route("/prospects/<int:prospect_id>/delete", methods=["POST"])
    @login_required
    def delete_prospect(prospect_id):
        prospect = db.session.get(Prospect, prospect_id) or _abort_404()
        db.session.delete(prospect)
        db.session.commit()
        flash("Prospect deleted.", "success")
        return redirect(url_for("prospects"))

    @app.route("/prospects/<int:prospect_id>/convert", methods=["POST"])
    @login_required
    def convert_prospect(prospect_id):
        prospect = db.session.get(Prospect, prospect_id) or _abort_404()
        if prospect.converted_client_id:
            flash(f"{prospect.name} was already converted.", "error")
            return redirect(url_for("prospects"))

        client = Client(
            name=prospect.name,
            contact_name=prospect.contact_name,
            contact_email=prospect.contact_email,
            contact_phone=prospect.contact_phone,
            notes=prospect.notes,
        )
        db.session.add(client)
        db.session.flush()  # assigns client.id before we reference it

        prospect.status = "Converted"
        prospect.converted_client_id = client.id
        db.session.commit()

        flash(f"{prospect.name} converted to a client.", "success")
        return redirect(url_for("edit_client", client_id=client.id))

    # ---------- Deals (Sales pipeline) ----------
    @app.route("/deals")
    @login_required
    def deals():
        all_deals = Deal.query.order_by(Deal.created_at.desc()).all()
        grouped = {stage: [] for stage in STAGE_CHOICES}
        for d in all_deals:
            grouped.setdefault(d.stage, []).append(d)
        return render_template("deals.html", grouped=grouped, stages=STAGE_CHOICES)

    @app.route("/deals/new", methods=["GET", "POST"])
    @login_required
    def new_deal():
        clients_list = Client.query.order_by(Client.name).all()
        users_list = User.query.order_by(User.username).all()
        if request.method == "POST":
            close_date = request.form.get("expected_close_date") or None
            deal = Deal(
                name=request.form["name"].strip(),
                client_id=int(request.form["client_id"]),
                stage=request.form.get("stage", STAGE_CHOICES[0]),
                value=float(request.form.get("value") or 0),
                owner_id=int(request.form["owner_id"]) if request.form.get("owner_id") else None,
                notes=request.form.get("notes", "").strip(),
                expected_close_date=datetime.strptime(close_date, "%Y-%m-%d").date() if close_date else None,
            )
            db.session.add(deal)
            db.session.commit()
            flash("Deal added.", "success")
            return redirect(url_for("deals"))
        return render_template(
            "deal_form.html", deal=None, clients=clients_list, users=users_list, stages=STAGE_CHOICES
        )

    @app.route("/deals/<int:deal_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_deal(deal_id):
        deal = db.session.get(Deal, deal_id) or _abort_404()
        clients_list = Client.query.order_by(Client.name).all()
        users_list = User.query.order_by(User.username).all()
        if request.method == "POST":
            close_date = request.form.get("expected_close_date") or None
            deal.name = request.form["name"].strip()
            deal.client_id = int(request.form["client_id"])
            deal.stage = request.form.get("stage", STAGE_CHOICES[0])
            deal.value = float(request.form.get("value") or 0)
            deal.owner_id = int(request.form["owner_id"]) if request.form.get("owner_id") else None
            deal.notes = request.form.get("notes", "").strip()
            deal.expected_close_date = datetime.strptime(close_date, "%Y-%m-%d").date() if close_date else None
            db.session.commit()
            flash("Deal updated.", "success")
            return redirect(url_for("deals"))
        return render_template(
            "deal_form.html", deal=deal, clients=clients_list, users=users_list, stages=STAGE_CHOICES
        )

    @app.route("/deals/<int:deal_id>/delete", methods=["POST"])
    @login_required
    def delete_deal(deal_id):
        deal = db.session.get(Deal, deal_id) or _abort_404()
        db.session.delete(deal)
        db.session.commit()
        flash("Deal deleted.", "success")
        return redirect(url_for("deals"))

    # ---------- Admin: invites & users ----------
    @app.route("/admin/invites", methods=["GET", "POST"])
    @login_required
    @admin_required
    def admin_invites():
        if request.method == "POST":
            email = request.form.get("email", "").strip()
            token = secrets.token_urlsafe(16)
            invite = Invite(email=email, token=token, invited_by_id=current_user.id)
            db.session.add(invite)
            db.session.commit()
            flash("Invite created. Copy the link below and send it to them.", "success")
            return redirect(url_for("admin_invites"))
        pending = Invite.query.filter_by(used=False).order_by(Invite.created_at.desc()).all()
        used = Invite.query.filter_by(used=True).order_by(Invite.created_at.desc()).all()
        return render_template("admin_invites.html", pending=pending, used=used)

    @app.route("/admin/invites/<int:invite_id>/revoke", methods=["POST"])
    @login_required
    @admin_required
    def revoke_invite(invite_id):
        invite = db.session.get(Invite, invite_id) or _abort_404()
        db.session.delete(invite)
        db.session.commit()
        flash("Invite revoked.", "success")
        return redirect(url_for("admin_invites"))

    @app.route("/admin/users")
    @login_required
    @admin_required
    def admin_users():
        all_users = User.query.order_by(User.username).all()
        return render_template("admin_users.html", users=all_users)

    @app.route("/admin/users/<int:user_id>/edit", methods=["GET", "POST"])
    @login_required
    @admin_required
    def admin_edit_user(user_id):
        user = db.session.get(User, user_id) or _abort_404()
        if request.method == "POST":
            new_username = request.form["username"].strip()
            existing = User.query.filter(User.username == new_username, User.id != user.id).first()
            if existing:
                flash("That username is already taken.", "error")
                return redirect(url_for("admin_edit_user", user_id=user.id))

            user.username = new_username
            user.email = request.form["email"].strip()

            new_password = request.form.get("new_password", "")
            if new_password:
                user.password_hash = generate_password_hash(new_password)

            db.session.commit()
            flash(f"Updated {user.username}.", "success")
            return redirect(url_for("admin_users"))
        return render_template("admin_edit_user.html", user=user)

    @app.route("/admin/users/<int:user_id>/toggle-admin", methods=["POST"])
    @login_required
    @admin_required
    def toggle_admin(user_id):
        user = db.session.get(User, user_id) or _abort_404()
        if user.id == current_user.id:
            flash("You can't change your own admin status.", "error")
            return redirect(url_for("admin_users"))
        user.is_admin = not user.is_admin
        db.session.commit()
        flash(f"Updated admin status for {user.username}.", "success")
        return redirect(url_for("admin_users"))

    # ---------- Profile ----------
    @app.route("/profile", methods=["GET", "POST"])
    @login_required
    def profile():
        if request.method == "POST":
            new_username = request.form["username"].strip()
            new_email = request.form["email"].strip()
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")

            existing = User.query.filter(User.username == new_username, User.id != current_user.id).first()
            if existing:
                flash("That username is already taken.", "error")
                return redirect(url_for("profile"))

            current_user.username = new_username
            current_user.email = new_email

            if new_password:
                if not check_password_hash(current_user.password_hash, current_password):
                    flash("Current password is incorrect, so your password wasn't changed. Other changes were saved.", "error")
                    db.session.commit()
                    return redirect(url_for("profile"))
                current_user.password_hash = generate_password_hash(new_password)

            db.session.commit()
            flash("Profile updated.", "success")
            return redirect(url_for("profile"))

        return render_template("profile.html")

    # ---------- Chat ----------
    @app.route("/chat")
    @login_required
    def chat():
        recent = ChatMessage.query.order_by(ChatMessage.created_at.asc()).limit(100).all()
        return render_template("chat.html", messages=recent)

    @app.route("/chat/messages")
    @login_required
    def chat_messages():
        since_id = request.args.get("since_id", type=int, default=0)
        msgs = ChatMessage.query.filter(ChatMessage.id > since_id).order_by(ChatMessage.created_at.asc()).limit(200).all()
        return {
            "messages": [
                {
                    "id": m.id,
                    "username": m.user.username if m.user else "Deleted user",
                    "body": m.body,
                    "created_at": m.created_at.strftime("%b %d, %I:%M %p"),
                    "is_own": m.user_id == current_user.id,
                }
                for m in msgs
            ]
        }

    @app.route("/chat/send", methods=["POST"])
    @login_required
    def chat_send():
        if request.is_json:
            body = (request.json or {}).get("body", "")
        else:
            body = request.form.get("body", "")
        body = (body or "").strip()
        if not body:
            return {"error": "Message can't be empty."}, 400
        msg = ChatMessage(body=body, user_id=current_user.id)
        db.session.add(msg)
        db.session.commit()
        return {
            "id": msg.id,
            "username": current_user.username,
            "body": msg.body,
            "created_at": msg.created_at.strftime("%b %d, %I:%M %p"),
            "is_own": True,
        }

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
