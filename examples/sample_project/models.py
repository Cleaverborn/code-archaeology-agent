"""Sample models module — demonstrates the system's dependency tracing."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class User:
    """A user model with basic fields."""
    id: int
    username: str
    email: str
    is_active: bool = True

    def deactivate(self) -> None:
        self.is_active = False

    def update_email(self, new_email: str) -> bool:
        if "@" not in new_email:
            return False
        self.email = new_email
        return True


@dataclass
class Order:
    """An order linked to a user."""
    id: int
    user_id: int
    product_name: str
    quantity: int
    price: float

    def total(self) -> float:
        return self.quantity * self.price

    def apply_discount(self, percentage: float) -> float:
        discount = self.total() * (percentage / 100)
        return self.total() - discount
