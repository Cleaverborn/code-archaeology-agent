"""Sample utilities module — leaf module depended on by services and models."""

import re
from datetime import datetime


def validate_email(email: str) -> bool:
    """Validate email format."""
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


def format_price(amount: float) -> str:
    """Format a price with currency symbol."""
    return f"${amount:,.2f}"


def log_operation(operation: str, detail: str = "") -> None:
    """Log an operation with timestamp."""
    timestamp = datetime.now().isoformat()
    print(f"[{timestamp}] {operation}: {detail}")


def calculate_total_with_tax(subtotal: float, tax_rate: float = 0.08) -> float:
    """Calculate total including tax."""
    return subtotal * (1 + tax_rate)
