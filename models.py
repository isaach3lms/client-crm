from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    projects = db.relationship("Project", back_populates="assigned_to", foreign_keys="Project.assigned_to_id")


class Invite(db.Model):
    __tablename__ = "invites"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(200))
    token = db.Column(db.String(64), unique=True, nullable=False)
    used = db.Column(db.Boolean, default=False, nullable=False)
    invited_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    invited_by = db.relationship("User", foreign_keys=[invited_by_id])
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Prospect(db.Model):
    __tablename__ = "prospects"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    prospect_type = db.Column(db.String(20), default="Church")  # "Person" or "Church"
    contact_name = db.Column(db.String(200))
    contact_email = db.Column(db.String(200))
    contact_phone = db.Column(db.String(50))
    status = db.Column(db.String(30), default="New", nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    assigned_to_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    assigned_to = db.relationship("User", foreign_keys=[assigned_to_id])

    converted_client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=True)
    converted_client = db.relationship("Client", foreign_keys=[converted_client_id])


class Deal(db.Model):
    __tablename__ = "deals"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    stage = db.Column(db.String(30), default="Lead", nullable=False)
    value = db.Column(db.Numeric(12, 2), default=0)
    expected_close_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)
    client = db.relationship("Client", back_populates="deals")

    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    owner = db.relationship("User", foreign_keys=[owner_id])


class LedgerEntry(db.Model):
    __tablename__ = "ledger_entries"

    id = db.Column(db.Integer, primary_key=True)
    entry_type = db.Column(db.String(10), nullable=False)  # "Income" or "Expense"
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    category = db.Column(db.String(100))
    description = db.Column(db.Text)
    entry_date = db.Column(db.Date, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_by = db.relationship("User", foreign_keys=[created_by_id])
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Client(db.Model):
    __tablename__ = "clients"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    contact_name = db.Column(db.String(200))
    contact_email = db.Column(db.String(200))
    contact_phone = db.Column(db.String(50))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    projects = db.relationship("Project", back_populates="client", cascade="all, delete-orphan")
    deals = db.relationship("Deal", back_populates="client", cascade="all, delete-orphan")


class Project(db.Model):
    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(50), default="Not Started")
    description = db.Column(db.Text)
    due_date = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)
    client = db.relationship("Client", back_populates="projects")

    assigned_to_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    assigned_to = db.relationship("User", back_populates="projects", foreign_keys=[assigned_to_id])
