"""
Distributed E-Commerce Order Engine
Hackathon Project - All 20 Tasks Implemented
"""

import uuid
import random
import threading
import time
from datetime import datetime, timedelta
from collections import defaultdict
from enum import Enum


# ─────────────────────────────────────────────
#  ENUMS & CONSTANTS
# ─────────────────────────────────────────────

class OrderStatus(Enum):
    CREATED = "CREATED"
    PENDING_PAYMENT = "PENDING_PAYMENT"
    PAID = "PAID"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

VALID_TRANSITIONS = {
    OrderStatus.CREATED: [OrderStatus.PENDING_PAYMENT, OrderStatus.CANCELLED],
    OrderStatus.PENDING_PAYMENT: [OrderStatus.PAID, OrderStatus.FAILED, OrderStatus.CANCELLED],
    OrderStatus.PAID: [OrderStatus.SHIPPED, OrderStatus.CANCELLED],
    OrderStatus.SHIPPED: [OrderStatus.DELIVERED],
    OrderStatus.DELIVERED: [],
    OrderStatus.FAILED: [],
    OrderStatus.CANCELLED: [],
}

COUPONS = {
    "SAVE10": {"type": "percent", "value": 10},
    "FLAT200": {"type": "flat", "value": 200},
}

LOW_STOCK_THRESHOLD = 5
RESERVATION_EXPIRY_SECONDS = 300  # 5 minutes


# ─────────────────────────────────────────────
#  AUDIT LOG (Task 16)
# ─────────────────────────────────────────────

audit_logs = []

def log(message: str):
    entry = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    audit_logs.append(entry)
    print(f"  📋 LOG: {message}")


# ─────────────────────────────────────────────
#  EVENT QUEUE (Task 14)
# ─────────────────────────────────────────────

event_queue = []
event_handlers = defaultdict(list)

def emit_event(event_type: str, data: dict):
    event = {"type": event_type, "data": data, "time": datetime.now()}
    event_queue.append(event)
    log(f"EVENT: {event_type} -> {data}")
    for handler in event_handlers[event_type]:
        try:
            handler(data)
        except Exception as e:
            print(f"  ⚠️  Event handler error for {event_type}: {e}")
            break  # Failure stops next events (Task 14 rule)

def on_event(event_type: str):
    def decorator(fn):
        event_handlers[event_type].append(fn)
        return fn
    return decorator


# ─────────────────────────────────────────────
#  DATA STORES
# ─────────────────────────────────────────────

products = {}       # product_id -> product dict
carts = {}          # user_id -> {product_id: quantity}
orders = {}         # order_id -> order dict
reservations = {}   # reservation_id -> {product_id, qty, user_id, expires_at}
flagged_users = {}  # user_id -> reason
idempotency_keys = set()  # Task 19

# Locks for concurrency (Task 4)
product_locks = defaultdict(threading.Lock)
stock_lock = threading.Lock()


# ─────────────────────────────────────────────
#  TASK 1: PRODUCT MANAGEMENT
# ─────────────────────────────────────────────

def add_product(product_id: str, name: str, price: float, stock: int) -> bool:
    if product_id in products:
        print(f"  ❌ Product ID '{product_id}' already exists.")
        return False
    if stock < 0:
        print("  ❌ Stock cannot be negative.")
        return False
    products[product_id] = {
        "id": product_id,
        "name": name,
        "price": price,
        "stock": stock,
        "reserved": 0,
    }
    log(f"Product '{product_id}' ({name}) added with stock={stock}")
    emit_event("PRODUCT_ADDED", {"product_id": product_id, "stock": stock})
    print(f"  ✅ Product '{name}' added successfully.")
    return True

def view_products():
    if not products:
        print("  ℹ️  No products available.")
        return
    print(f"\n  {'ID':<12} {'Name':<20} {'Price':>10} {'Stock':>8} {'Reserved':>10}")
    print("  " + "-" * 65)
    for p in products.values():
        available = p["stock"] - p["reserved"]
        print(f"  {p['id']:<12} {p['name']:<20} ₹{p['price']:>9.2f} {available:>8} {p['reserved']:>10}")


# ─────────────────────────────────────────────
#  TASK 3: REAL-TIME STOCK RESERVATION
# ─────────────────────────────────────────────

def reserve_stock(product_id: str, qty: int, user_id: str) -> str | None:
    with product_locks[product_id]:
        p = products.get(product_id)
        if not p:
            return None
        available = p["stock"] - p["reserved"]
        if qty > available:
            return None
        p["reserved"] += qty
        res_id = str(uuid.uuid4())[:8]
        reservations[res_id] = {
            "product_id": product_id,
            "qty": qty,
            "user_id": user_id,
            "expires_at": datetime.now() + timedelta(seconds=RESERVATION_EXPIRY_SECONDS),
        }
        log(f"Stock reserved: {qty}x '{product_id}' for user '{user_id}' (res={res_id})")
        return res_id

def release_reservation(res_id: str):
    res = reservations.pop(res_id, None)
    if res:
        p = products.get(res["product_id"])
        if p:
            p["reserved"] = max(0, p["reserved"] - res["qty"])
        log(f"Reservation {res_id} released.")


# ─────────────────────────────────────────────
#  TASK 15: INVENTORY RESERVATION EXPIRY
# ─────────────────────────────────────────────

def expire_reservations():
    now = datetime.now()
    expired = [rid for rid, r in reservations.items() if r["expires_at"] < now]
    for rid in expired:
        print(f"  ⏰ Reservation {rid} expired, releasing stock.")
        log(f"Reservation {rid} expired and auto-released.")
        release_reservation(rid)


# ─────────────────────────────────────────────
#  TASK 2: MULTI-USER CART SYSTEM
# ─────────────────────────────────────────────

def add_to_cart(user_id: str, product_id: str, qty: int):
    expire_reservations()
    p = products.get(product_id)
    if not p:
        print(f"  ❌ Product '{product_id}' not found.")
        return
    if p["stock"] == 0:
        print(f"  ❌ '{p['name']}' is out of stock.")
        return

    cart = carts.setdefault(user_id, {})
    already_in_cart = cart.get(product_id, 0)
    total_wanted = already_in_cart + qty
    available = p["stock"] - p["reserved"]

    if qty > available:
        print(f"  ❌ Only {available} units available for '{p['name']}'.")
        return

    res_id = reserve_stock(product_id, qty, user_id)
    if not res_id:
        print(f"  ❌ Could not reserve stock for '{p['name']}'.")
        return

    cart[product_id] = cart.get(product_id, 0) + qty
    # Store reservation id per cart item (simplified: last reservation)
    cart[f"_res_{product_id}"] = res_id
    log(f"USER '{user_id}' added {qty}x '{product_id}' to cart.")
    print(f"  ✅ Added {qty}x '{p['name']}' to cart of '{user_id}'.")

def remove_from_cart(user_id: str, product_id: str):
    cart = carts.get(user_id, {})
    if product_id not in cart:
        print(f"  ❌ '{product_id}' not in cart.")
        return
    qty = cart.pop(product_id)
    res_id = cart.pop(f"_res_{product_id}", None)
    if res_id:
        release_reservation(res_id)
    log(f"USER '{user_id}' removed '{product_id}' from cart.")
    print(f"  ✅ Removed '{product_id}' from cart.")

def view_cart(user_id: str):
    cart = carts.get(user_id, {})
    items = {k: v for k, v in cart.items() if not k.startswith("_res_")}
    if not items:
        print(f"  🛒 Cart of '{user_id}' is empty.")
        return
    total = 0
    print(f"\n  Cart for '{user_id}':")
    print(f"  {'Product':<15} {'Qty':>5} {'Unit Price':>12} {'Subtotal':>12}")
    print("  " + "-" * 48)
    for pid, qty in items.items():
        p = products.get(pid)
        if p:
            sub = p["price"] * qty
            total += sub
            print(f"  {p['name']:<15} {qty:>5} ₹{p['price']:>11.2f} ₹{sub:>11.2f}")
    print(f"  {'':35} {'Total:':>8} ₹{total:.2f}")


# ─────────────────────────────────────────────
#  TASK 9: DISCOUNT & COUPON ENGINE
# ─────────────────────────────────────────────

def apply_coupon_to_cart(user_id: str, code: str):
    cart = carts.get(user_id, {})
    items = {k: v for k, v in cart.items() if not k.startswith("_res_")}
    if not items:
        print("  ❌ Cart is empty.")
        return
    coupon = COUPONS.get(code.upper())
    if not coupon:
        print(f"  ❌ Invalid coupon code '{code}'.")
        return
    # Store coupon in cart meta
    cart["_coupon"] = code.upper()
    print(f"  ✅ Coupon '{code.upper()}' applied.")
    log(f"USER '{user_id}' applied coupon '{code.upper()}'.")

def calculate_total(user_id: str) -> float:
    cart = carts.get(user_id, {})
    items = {k: v for k, v in cart.items() if not k.startswith("_res_") and k != "_coupon"}
    total = sum(products[pid]["price"] * qty for pid, qty in items.items() if pid in products)

    # Auto discount: total > 1000 → 10%
    if total > 1000:
        total *= 0.90
        print(f"  🏷️  Auto 10% discount applied (total > ₹1000).")

    # Quantity discount: >3 of same product → extra 5%
    for pid, qty in items.items():
        if qty > 3:
            total -= products[pid]["price"] * qty * 0.05
            print(f"  🏷️  Extra 5% discount on '{pid}' (qty > 3).")

    # Coupon
    coupon_code = cart.get("_coupon")
    if coupon_code and coupon_code in COUPONS:
        c = COUPONS[coupon_code]
        if c["type"] == "percent":
            total *= (1 - c["value"] / 100)
        elif c["type"] == "flat":
            total -= c["value"]
        total = max(0, total)

    return round(total, 2)


# ─────────────────────────────────────────────
#  TASK 5: ORDER PLACEMENT ENGINE (Atomic)
#  TASK 6: PAYMENT SIMULATION
#  TASK 7: TRANSACTION ROLLBACK
# ─────────────────────────────────────────────

failure_mode = {"enabled": False}

def simulate_payment() -> bool:
    if failure_mode["enabled"]:
        return False
    return random.random() > 0.3  # 70% success

def place_order(user_id: str, idempotency_key: str = None) -> str | None:
    # Task 19: Idempotency
    if idempotency_key:
        if idempotency_key in idempotency_keys:
            print("  ⚠️  Duplicate order request detected. Ignoring.")
            return None
        idempotency_keys.add(idempotency_key)

    expire_reservations()
    cart = carts.get(user_id, {})
    items = {k: v for k, v in cart.items() if not k.startswith("_res_") and k != "_coupon"}

    if not items:
        print("  ❌ Cart is empty. Cannot place order.")
        return None

    # Step 1: Validate cart
    for pid, qty in items.items():
        p = products.get(pid)
        if not p:
            print(f"  ❌ Product '{pid}' no longer exists.")
            return None
        if p["stock"] < qty:
            print(f"  ❌ Insufficient stock for '{pid}'.")
            return None

    # Step 2: Calculate total
    total = calculate_total(user_id)
    print(f"  💰 Order total: ₹{total:.2f}")

    # Step 3: Lock stock (deduct)
    locked = []
    for pid, qty in items.items():
        with product_locks[pid]:
            p = products[pid]
            if p["stock"] < qty:
                # Rollback locked
                for lpid, lqty in locked:
                    products[lpid]["stock"] += lqty
                print(f"  ❌ Stock conflict on '{pid}'. Rolling back.")
                return None
            p["stock"] -= qty
            p["reserved"] = max(0, p["reserved"] - qty)
            locked.append((pid, qty))
        log(f"Stock locked: {qty}x '{pid}'")

    # Step 4: Create order
    order_id = "ORD-" + str(uuid.uuid4())[:8].upper()
    order = {
        "id": order_id,
        "user_id": user_id,
        "items": dict(items),
        "total": total,
        "status": OrderStatus.CREATED,
        "created_at": datetime.now(),
        "events": [],
    }
    orders[order_id] = order
    log(f"ORDER '{order_id}' created for user '{user_id}'.")
    emit_event("ORDER_CREATED", {"order_id": order_id, "user_id": user_id})

    # Transition: CREATED → PENDING_PAYMENT
    transition_order(order_id, OrderStatus.PENDING_PAYMENT)

    # Step 5 (Task 6): Simulate payment
    print("  💳 Processing payment...")
    time.sleep(0.5)
    payment_success = simulate_payment()

    if payment_success:
        transition_order(order_id, OrderStatus.PAID)
        emit_event("PAYMENT_SUCCESS", {"order_id": order_id})
        emit_event("INVENTORY_UPDATED", {"items": items})

        # Step 5: Clear cart
        carts[user_id] = {}
        log(f"Cart cleared for user '{user_id}' after order '{order_id}'.")

        # Task 17: Fraud Detection
        check_fraud(user_id, total)

        print(f"  ✅ Order '{order_id}' placed successfully! Status: PAID")
        return order_id
    else:
        # Task 7: Rollback
        print("  ❌ Payment failed! Rolling back transaction...")
        for pid, qty in locked:
            products[pid]["stock"] += qty
            log(f"Stock restored: {qty}x '{pid}' (payment failure rollback)")

        transition_order(order_id, OrderStatus.FAILED)
        del orders[order_id]
        log(f"ORDER '{order_id}' deleted due to payment failure.")
        emit_event("PAYMENT_FAILED", {"order_id": order_id})
        print("  🔄 Rollback complete. Stock restored.")
        return None


# ─────────────────────────────────────────────
#  TASK 8: ORDER STATE MACHINE
# ─────────────────────────────────────────────

def transition_order(order_id: str, new_status: OrderStatus) -> bool:
    order = orders.get(order_id)
    if not order:
        print(f"  ❌ Order '{order_id}' not found.")
        return False
    current = order["status"]
    if new_status not in VALID_TRANSITIONS[current]:
        print(f"  ❌ Invalid transition: {current.value} → {new_status.value}")
        return False
    order["status"] = new_status
    order["events"].append({"status": new_status.value, "time": datetime.now()})
    log(f"ORDER '{order_id}' transitioned: {current.value} → {new_status.value}")
    return True


# ─────────────────────────────────────────────
#  TASK 10: INVENTORY ALERT SYSTEM
# ─────────────────────────────────────────────

def low_stock_alert():
    print("\n  📦 Low Stock Alerts:")
    found = False
    for p in products.values():
        available = p["stock"] - p["reserved"]
        if available <= LOW_STOCK_THRESHOLD:
            status = "OUT OF STOCK" if available == 0 else f"LOW ({available} left)"
            print(f"  ⚠️  {p['name']} [{p['id']}]: {status}")
            found = True
    if not found:
        print("  ✅ All products have sufficient stock.")


# ─────────────────────────────────────────────
#  TASK 11: ORDER MANAGEMENT
# ─────────────────────────────────────────────

def view_orders(filter_status: str = None, search_id: str = None):
    filtered = list(orders.values())
    if search_id:
        filtered = [o for o in filtered if o["id"] == search_id]
    if filter_status:
        try:
            s = OrderStatus(filter_status.upper())
            filtered = [o for o in filtered if o["status"] == s]
        except ValueError:
            print(f"  ❌ Unknown status '{filter_status}'.")
            return
    if not filtered:
        print("  ℹ️  No orders found.")
        return
    print(f"\n  {'Order ID':<15} {'User':<12} {'Total':>10} {'Status':<18} {'Created'}")
    print("  " + "-" * 75)
    for o in filtered:
        print(f"  {o['id']:<15} {o['user_id']:<12} ₹{o['total']:>9.2f} {o['status'].value:<18} {o['created_at'].strftime('%H:%M:%S')}")


# ─────────────────────────────────────────────
#  TASK 12: ORDER CANCELLATION ENGINE
# ─────────────────────────────────────────────

def cancel_order(order_id: str):
    order = orders.get(order_id)
    if not order:
        print(f"  ❌ Order '{order_id}' not found.")
        return
    if order["status"] == OrderStatus.CANCELLED:
        print("  ❌ Order is already cancelled.")
        return
    if not transition_order(order_id, OrderStatus.CANCELLED):
        return
    # Restore stock
    for pid, qty in order["items"].items():
        if pid in products:
            products[pid]["stock"] += qty
            log(f"Stock restored: {qty}x '{pid}' (order cancellation)")
    emit_event("ORDER_CANCELLED", {"order_id": order_id})
    print(f"  ✅ Order '{order_id}' cancelled and stock restored.")


# ─────────────────────────────────────────────
#  TASK 13: RETURN & REFUND SYSTEM
# ─────────────────────────────────────────────

def return_product(order_id: str, product_id: str, qty: int):
    order = orders.get(order_id)
    if not order:
        print(f"  ❌ Order '{order_id}' not found.")
        return
    if order["status"] != OrderStatus.DELIVERED:
        print("  ❌ Can only return delivered orders.")
        return
    ordered_qty = order["items"].get(product_id, 0)
    if qty > ordered_qty:
        print(f"  ❌ Cannot return more than ordered ({ordered_qty}).")
        return

    # Partial return: update stock and order total
    p = products.get(product_id)
    if p:
        products[product_id]["stock"] += qty
        refund = p["price"] * qty
        order["total"] = max(0, order["total"] - refund)
        order["items"][product_id] -= qty
        if order["items"][product_id] == 0:
            del order["items"][product_id]
        log(f"Return: {qty}x '{product_id}' from order '{order_id}'. Refund: ₹{refund:.2f}")
        emit_event("PRODUCT_RETURNED", {"order_id": order_id, "product_id": product_id, "qty": qty})
        print(f"  ✅ Returned {qty}x '{p['name']}'. Refund: ₹{refund:.2f}")


# ─────────────────────────────────────────────
#  TASK 4: CONCURRENCY SIMULATION
# ─────────────────────────────────────────────

def simulate_concurrent_users(product_id: str, num_users: int = 3, qty_each: int = 3):
    print(f"\n  🔀 Simulating {num_users} concurrent users trying to buy {qty_each}x '{product_id}'...")
    p = products.get(product_id)
    if not p:
        print("  ❌ Product not found.")
        return

    results = {}
    barrier = threading.Barrier(num_users)

    def try_add_to_cart(user_id):
        barrier.wait()  # All start simultaneously
        user_cart = f"concurrent_user_{user_id}"
        res = reserve_stock(product_id, qty_each, user_cart)
        results[user_id] = "✅ SUCCESS" if res else "❌ FAILED (out of stock)"
        if res:
            carts[user_cart] = {product_id: qty_each, f"_res_{product_id}": res}

    threads = [threading.Thread(target=try_add_to_cart, args=(i,)) for i in range(num_users)]
    for t in threads: t.start()
    for t in threads: t.join()

    print(f"\n  Results (stock was {p['stock'] + p['reserved']}):")
    for uid, result in sorted(results.items()):
        print(f"    User {uid}: {result}")
    print(f"  Remaining available: {p['stock'] - p['reserved']}")


# ─────────────────────────────────────────────
#  TASK 16: VIEW AUDIT LOGS
# ─────────────────────────────────────────────

def view_logs(limit: int = 20):
    print(f"\n  📋 Audit Log (last {limit} entries):")
    for entry in audit_logs[-limit:]:
        print(f"    {entry}")


# ─────────────────────────────────────────────
#  TASK 17: FRAUD DETECTION SYSTEM
# ─────────────────────────────────────────────

user_order_times = defaultdict(list)

def check_fraud(user_id: str, order_total: float):
    now = datetime.now()
    user_order_times[user_id].append(now)
    # Keep only last minute
    user_order_times[user_id] = [t for t in user_order_times[user_id] if (now - t).seconds < 60]

    if len(user_order_times[user_id]) >= 3:
        flagged_users[user_id] = "3+ orders in 1 minute"
        print(f"  🚨 FRAUD ALERT: User '{user_id}' flagged — too many orders in 1 minute.")
        log(f"FRAUD: User '{user_id}' flagged for rapid ordering.")

    if order_total > 50000:
        flagged_users[user_id] = "High-value suspicious order"
        print(f"  🚨 FRAUD ALERT: User '{user_id}' flagged — high-value order ₹{order_total:.2f}.")
        log(f"FRAUD: User '{user_id}' flagged for high-value order.")


# ─────────────────────────────────────────────
#  TASK 18: FAILURE INJECTION SYSTEM
# ─────────────────────────────────────────────

def trigger_failure_mode(enable: bool):
    failure_mode["enabled"] = enable
    state = "ENABLED" if enable else "DISABLED"
    print(f"  ⚡ Failure mode {state}. {'All payments will fail!' if enable else 'Normal operation resumed.'}")
    log(f"Failure mode {state}.")


# ─────────────────────────────────────────────
#  TASK 20: MICROSERVICE SIMULATION
# ─────────────────────────────────────────────

class ProductService:
    @staticmethod
    def add(pid, name, price, stock): return add_product(pid, name, price, stock)
    @staticmethod
    def view(): return view_products()
    @staticmethod
    def low_stock(): return low_stock_alert()

class CartService:
    @staticmethod
    def add(user, pid, qty): return add_to_cart(user, pid, qty)
    @staticmethod
    def remove(user, pid): return remove_from_cart(user, pid)
    @staticmethod
    def view(user): return view_cart(user)
    @staticmethod
    def coupon(user, code): return apply_coupon_to_cart(user, code)

class OrderService:
    @staticmethod
    def place(user, ikey=None): return place_order(user, ikey)
    @staticmethod
    def cancel(oid): return cancel_order(oid)
    @staticmethod
    def view(fs=None, sid=None): return view_orders(fs, sid)
    @staticmethod
    def ret(oid, pid, qty): return return_product(oid, pid, qty)
    @staticmethod
    def transition(oid, status): return transition_order(oid, status)

class PaymentService:
    @staticmethod
    def simulate(): return simulate_payment()
    @staticmethod
    def failure_mode(en): return trigger_failure_mode(en)

# Instantiate services (loose coupling)
product_svc = ProductService()
cart_svc = CartService()
order_svc = OrderService()
payment_svc = PaymentService()


# ─────────────────────────────────────────────
#  SEED DATA
# ─────────────────────────────────────────────

def seed_data():
    add_product("P001", "Laptop", 45000.0, 10)
    add_product("P002", "Phone", 15000.0, 20)
    add_product("P003", "Headphones", 2500.0, 5)
    add_product("P004", "Mouse", 800.0, 3)
    add_product("P005", "Keyboard", 1200.0, 0)
    print("  ✅ Sample products loaded.\n")


# ─────────────────────────────────────────────
#  CLI MENU
# ─────────────────────────────────────────────

def get_input(prompt, cast=str, default=None):
    try:
        val = input(f"  → {prompt}: ").strip()
        if not val and default is not None:
            return default
        return cast(val)
    except (ValueError, EOFError):
        print("  ❌ Invalid input.")
        return default

def print_menu():
    print("""
╔══════════════════════════════════════════════╗
║     🛒  E-Commerce Order Engine CLI          ║
╠══════════════════════════════════════════════╣
║  1.  Add Product          2.  View Products  ║
║  3.  Add to Cart          4.  Remove from    ║
║                               Cart           ║
║  5.  View Cart            6.  Apply Coupon   ║
║  7.  Place Order          8.  Cancel Order   ║
║  9.  View Orders         10.  Low Stock Alert║
║ 11.  Return Product      12.  Simulate       ║
║                               Concurrent     ║
║ 13.  View Logs           14.  Toggle Failure ║
║                               Mode           ║
║ 15.  Advance Order State  0.  Exit           ║
╚══════════════════════════════════════════════╝""")

def main():
    print("\n🚀 Distributed E-Commerce Order Engine Starting...\n")
    seed_data()

    while True:
        print_menu()
        choice = get_input("Enter choice", int, -1)

        if choice == 1:
            pid = get_input("Product ID")
            name = get_input("Product Name")
            price = get_input("Price", float)
            stock = get_input("Stock", int)
            if all([pid, name, price is not None, stock is not None]):
                product_svc.add(pid, name, price, stock)

        elif choice == 2:
            product_svc.view()

        elif choice == 3:
            user = get_input("User ID", default="user1")
            pid = get_input("Product ID")
            qty = get_input("Quantity", int, 1)
            cart_svc.add(user, pid, qty)

        elif choice == 4:
            user = get_input("User ID", default="user1")
            pid = get_input("Product ID")
            cart_svc.remove(user, pid)

        elif choice == 5:
            user = get_input("User ID", default="user1")
            cart_svc.view(user)

        elif choice == 6:
            user = get_input("User ID", default="user1")
            print("  Available coupons: SAVE10 (10% off), FLAT200 (₹200 off)")
            code = get_input("Coupon Code")
            cart_svc.coupon(user, code)

        elif choice == 7:
            user = get_input("User ID", default="user1")
            ikey = get_input("Idempotency Key (press Enter to skip)", default=None)
            order_svc.place(user, ikey if ikey else None)

        elif choice == 8:
            oid = get_input("Order ID")
            order_svc.cancel(oid)

        elif choice == 9:
            print("  Filter by status? (CREATED/PAID/SHIPPED/DELIVERED/CANCELLED/FAILED or Enter to skip)")
            fs = get_input("Status filter", default=None)
            sid = get_input("Search by Order ID (or Enter to skip)", default=None)
            order_svc.view(fs if fs else None, sid if sid else None)

        elif choice == 10:
            low_stock_alert()

        elif choice == 11:
            oid = get_input("Order ID")
            pid = get_input("Product ID")
            qty = get_input("Return Quantity", int, 1)
            order_svc.ret(oid, pid, qty)

        elif choice == 12:
            pid = get_input("Product ID to test concurrency")
            num = get_input("Number of concurrent users", int, 3)
            qty = get_input("Quantity each user wants", int, 3)
            simulate_concurrent_users(pid, num, qty)

        elif choice == 13:
            limit = get_input("How many last log entries to show", int, 30)
            view_logs(limit)

        elif choice == 14:
            current = failure_mode["enabled"]
            action = "disable" if current else "enable"
            confirm = get_input(f"Failure mode is {'ON' if current else 'OFF'}. Type 'yes' to {action}")
            if confirm.lower() == "yes":
                payment_svc.failure_mode(not current)

        elif choice == 15:
            oid = get_input("Order ID")
            print("  States: PENDING_PAYMENT / PAID / SHIPPED / DELIVERED / FAILED / CANCELLED")
            status_str = get_input("New Status").upper()
            try:
                new_status = OrderStatus(status_str)
                order_svc.transition(oid, new_status)
            except ValueError:
                print(f"  ❌ Unknown status '{status_str}'.")

        elif choice == 0:
            print("\n  👋 Exiting E-Commerce Order Engine. Goodbye!\n")
            break

        else:
            print("  ❌ Invalid option. Please choose from the menu.")

        input("\n  Press Enter to continue...")


if __name__ == "__main__":
    main()
