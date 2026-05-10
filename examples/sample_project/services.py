"""Sample services module — calls into models and utils."""

from .models import User, Order
from .utils import validate_email, format_price, log_operation


class UserService:
    """Service for user-related operations."""

    def create_user(self, username: str, email: str) -> User:
        if not validate_email(email):
            raise ValueError(f"Invalid email: {email}")
        user = User(id=0, username=username, email=email)
        log_operation("create_user", username)
        return user

    def deactivate_user(self, user: User) -> None:
        user.deactivate()
        log_operation("deactivate_user", user.username)

    def change_email(self, user: User, new_email: str) -> bool:
        if not validate_email(new_email):
            return False
        result = user.update_email(new_email)
        if result:
            log_operation("change_email", user.username)
        return result


class OrderService:
    """Service for order-related operations."""

    def __init__(self, user_service: UserService) -> None:
        self.user_service = user_service

    def create_order(self, user: User, product: str, qty: int, price: float) -> Order:
        order = Order(id=0, user_id=user.id, product_name=product,
                       quantity=qty, price=price)
        total = order.total()
        formatted = format_price(total)
        log_operation("create_order", f"{product} x{qty} = {formatted}")
        return order

    def apply_bulk_discount(self, orders: list[Order], percentage: float) -> float:
        total_savings = 0.0
        for order in orders:
            original = order.total()
            discounted = order.apply_discount(percentage)
            total_savings += (original - discounted)
        log_operation("bulk_discount", f"Saved {format_price(total_savings)}")
        return total_savings

    def get_orders_for_user(self, user: User, all_orders: list[Order]) -> list[Order]:
        return [o for o in all_orders if o.user_id == user.id]
