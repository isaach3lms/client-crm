import os
from datetime import datetime
from flask import Flask, render_template, redirect, url_for, request, flash
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash

from models import db, User, Client, Project

STATUS_CHOICES = ["Not Started", "In Progress", "On Hold", "Completed"]


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

    with app.app_context():
        db.create_all()

    # ---------- Auth ----------
    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            username = request.form["username"].strip()
            email = request.form["email"].strip()
            password = request.form["password"]

            if User.query.filter_by(username=username).first():
                flash("That username is already taken.", "error")
                return redirect(url_for("register"))

            user = User(
                username=username,
                email=email,
                password_hash=generate_password_hash(password),
            )
            db.session.add(user)
            db.session.commit()
            flash("Account created. You can log in now.", "success")
            return redirect(url_for("login"))
        return render_template("register.html")

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
        return render_template("login.html")

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
        project_count = Project.query.count()
        recent_projects = Project.query.order_by(Project.created_at.desc()).limit(5).all()
        return render_template(
            "dashboard.html",
            client_count=client_count,
            project_count=project_count,
            recent_projects=recent_projects,
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

    def _abort_404():
        from flask import abort
        abort(404)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
