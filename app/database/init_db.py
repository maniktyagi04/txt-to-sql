"""Database initialization and seeding module for the Text-to-SQL backend.

Creates physical SQLite database files (analytics.db, support.db, marketing.db)
matching the production-grade schema metadata and populates them with realistic seed data.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from app.utils.logging import get_logger

logger = get_logger(__name__)


def init_databases(database_dir: str | Path = "app/database") -> None:
    """Initialize SQLite database files and seed them if they do not exist."""
    db_path = Path(database_dir)
    db_path.mkdir(parents=True, exist_ok=True)

    # 1. Initialize analytics.db
    analytics_db = db_path / "analytics.db"
    init_analytics_db(analytics_db)

    # 2. Initialize support.db
    support_db = db_path / "support.db"
    init_support_db(support_db)

    # 3. Initialize marketing.db
    marketing_db = db_path / "marketing.db"
    init_marketing_db(marketing_db)

    logger.info("sqlite_databases_initialized", extra={"db_dir": str(db_path)})


def init_analytics_db(db_path: Path) -> None:
    """Create tables and insert seed data for the analytics schema."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Enable write time safety
        cursor.execute("PRAGMA foreign_keys = ON;")

        # Create sales_orders
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sales_orders (
                order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                order_date TEXT NOT NULL,
                region TEXT NOT NULL,
                enterprise_sales_amount REAL NOT NULL,
                discount_amount REAL NOT NULL,
                order_status TEXT NOT NULL
            );
            """
        )

        # Create customers
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS customers (
                customer_id TEXT PRIMARY KEY,
                account_name TEXT NOT NULL,
                industry TEXT NOT NULL,
                segment TEXT NOT NULL,
                country TEXT NOT NULL,
                region TEXT NOT NULL,
                created_at TEXT NOT NULL,
                lifecycle_stage TEXT NOT NULL
            );
            """
        )

        # Create products
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                product_id TEXT PRIMARY KEY,
                sku TEXT NOT NULL UNIQUE,
                product_name TEXT NOT NULL,
                category TEXT NOT NULL,
                subcategory TEXT NOT NULL,
                launch_date TEXT NOT NULL,
                is_active INTEGER NOT NULL CHECK (is_active IN (0, 1))
            );
            """
        )

        # Create calendar
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS calendar (
                date_day TEXT PRIMARY KEY,
                fiscal_year INTEGER NOT NULL,
                fiscal_quarter TEXT NOT NULL,
                fiscal_month TEXT NOT NULL,
                week_start_date TEXT NOT NULL,
                is_holiday INTEGER NOT NULL CHECK (is_holiday IN (0, 1))
            );
            """
        )

        conn.commit()

        # Seed data if tables are empty
        # Seed Customers
        cursor.execute("SELECT COUNT(*) FROM customers;")
        if cursor.fetchone()[0] == 0:
            customers = [
                ("C001", "Acme Enterprise", "Technology", "Enterprise", "USA", "West", "2024-01-15 08:30:00", "Active"),
                ("C002", "Globex Corporation", "Manufacturing", "Enterprise", "Canada", "North", "2023-11-10 11:15:00", "Active"),
                ("C003", "Initech Financial", "Finance", "Mid-Market", "USA", "East", "2024-03-22 09:00:00", "Active"),
                ("C004", "Umbrella Corp", "Healthcare", "Strategic", "UK", "Europe", "2022-05-18 14:00:00", "Churned"),
                ("C005", "Tyrell Nexus", "Robotics", "Strategic", "USA", "West", "2025-02-01 10:45:00", "Active"),
            ]
            cursor.executemany(
                "INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?, ?, ?);",
                customers
            )

        # Seed Products
        cursor.execute("SELECT COUNT(*) FROM products;")
        if cursor.fetchone()[0] == 0:
            products = [
                ("P001", "SKU-CLOUD-SEC", "Cloud Security Suite", "Software", "Security", "2023-06-01", 1),
                ("P002", "SKU-DATA-OPS", "DataOps Automation Engine", "Software", "Data Platform", "2024-01-10", 1),
                ("P003", "SKU-BI-INSIGHT", "Business Intelligence Analytics", "Software", "Analytics", "2022-10-15", 1),
                ("P004", "SKU-LEGACY-ERP", "Enterprise ERP Suite V1", "Software", "ERP", "2018-04-01", 0),
            ]
            cursor.executemany(
                "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?);",
                products
            )

        # Seed Calendar (covering a range around April / May 2026)
        cursor.execute("SELECT COUNT(*) FROM calendar;")
        if cursor.fetchone()[0] == 0:
            calendar_days = [
                ("2026-04-28", 2026, "2026-Q2", "2026-04", "2026-04-27", 0),
                ("2026-04-29", 2026, "2026-Q2", "2026-04", "2026-04-27", 0),
                ("2026-04-30", 2026, "2026-Q2", "2026-04", "2026-04-27", 0),
                ("2026-05-01", 2026, "2026-Q2", "2026-05", "2026-04-27", 0),  # Labor Day/Holiday depending on locale
                ("2026-05-02", 2026, "2026-Q2", "2026-05", "2026-04-27", 0),
                ("2026-05-03", 2026, "2026-Q2", "2026-05", "2026-04-27", 0),
                ("2026-05-04", 2026, "2026-Q2", "2026-05", "2026-05-04", 0),
                ("2026-05-25", 2026, "2026-Q2", "2026-05", "2026-05-25", 1),  # Memorial Day
            ]
            cursor.executemany(
                "INSERT INTO calendar VALUES (?, ?, ?, ?, ?, ?);",
                calendar_days
            )

        # Seed Sales Orders
        cursor.execute("SELECT COUNT(*) FROM sales_orders;")
        if cursor.fetchone()[0] == 0:
            orders = [
                (1, "C001", "P001", "2026-04-28", "West", 15000.0, 1500.0, "Shipped"),
                (2, "C001", "P002", "2026-04-30", "West", 25000.0, 2000.0, "Processing"),
                (3, "C002", "P002", "2026-05-01", "North", 45000.0, 5000.0, "Shipped"),
                (4, "C003", "P003", "2026-05-02", "East", 12000.0, 0.0, "Delivered"),
                (5, "C005", "P001", "2026-05-04", "West", 18000.0, 1800.0, "Processing"),
                (6, "C002", "P001", "2026-05-25", "North", 15000.0, 1000.0, "Cancelled"),
            ]
            cursor.executemany(
                "INSERT INTO sales_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?);",
                orders
            )

        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.error("seed_analytics_db_failed", extra={"error": str(exc)})
        raise
    finally:
        conn.close()


def init_support_db(db_path: Path) -> None:
    """Create tables and insert seed data for the support schema."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Create tickets
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                priority TEXT NOT NULL,
                status TEXT NOT NULL,
                issue_type TEXT NOT NULL,
                first_response_minutes INTEGER,
                resolution_minutes INTEGER,
                csat_score INTEGER
            );
            """
        )

        conn.commit()

        # Seed Tickets
        cursor.execute("SELECT COUNT(*) FROM tickets;")
        if cursor.fetchone()[0] == 0:
            tickets = [
                (101, "C001", "2026-04-20 09:30:00", "2026-04-20 10:45:00", "High", "Resolved", "Technical", 15, 75, 5),
                (102, "C002", "2026-04-25 14:00:00", "2026-04-26 11:30:00", "Medium", "Resolved", "Billing", 45, 1290, 4),
                (103, "C003", "2026-05-01 08:00:00", None, "Critical", "Open", "Technical", 10, None, None),
                (104, "C001", "2026-05-03 11:00:00", "2026-05-03 11:20:00", "Low", "Resolved", "General Inquiry", 20, 20, 5),
                (105, "C004", "2026-05-10 16:30:00", None, "High", "In Progress", "Bug Report", 120, None, None),
            ]
            cursor.executemany(
                "INSERT INTO tickets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                tickets
            )

        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.error("seed_support_db_failed", extra={"error": str(exc)})
        raise
    finally:
        conn.close()


def init_marketing_db(db_path: Path) -> None:
    """Create tables and insert seed data for the marketing schema."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Create campaign_performance
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS campaign_performance (
                campaign_id TEXT PRIMARY KEY,
                campaign_name TEXT NOT NULL,
                channel TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                impressions INTEGER NOT NULL,
                clicks INTEGER NOT NULL,
                spend REAL NOT NULL,
                leads INTEGER NOT NULL,
                conversions INTEGER NOT NULL
            );
            """
        )

        conn.commit()

        # Seed Campaign Performance
        cursor.execute("SELECT COUNT(*) FROM campaign_performance;")
        if cursor.fetchone()[0] == 0:
            campaigns = [
                ("CMP01", "Spring Cloud Drive", "Google Ads", "2026-03-01", "2026-04-30", 500000, 25000, 12500.0, 1200, 320),
                ("CMP02", "Enterprise Tech Event", "LinkedIn", "2026-04-15", "2026-05-15", 150000, 4500, 8000.0, 450, 95),
                ("CMP03", "Data Summit Sponsorship", "Direct", "2026-05-01", "2026-05-05", 80000, 1200, 15000.0, 350, 120),
                ("CMP04", "Security Best Practices Webinar", "Email", "2026-05-10", "2026-05-20", 25000, 1800, 500.0, 600, 150),
            ]
            cursor.executemany(
                "INSERT INTO campaign_performance VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                campaigns
            )

        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.error("seed_marketing_db_failed", extra={"error": str(exc)})
        raise
    finally:
        conn.close()
