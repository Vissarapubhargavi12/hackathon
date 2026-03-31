# 🛒 Distributed E-Commerce Order Engine

A robust, menu-driven CLI application simulating a real-world e-commerce backend — built for the Hackathon Technical Assessment.

---

## 📌 Project Overview

This project simulates the backend engine of platforms like Amazon, Flipkart, and Meesho. It handles concurrent users, inventory conflicts, payment failures, rollbacks, order lifecycle management, fraud detection, and more — all in a clean Python CLI.

---

## ✅ Features Implemented (All 20 Tasks)

| # | Task | Description |
|---|------|-------------|
| 1 | Product Management | Add products, prevent duplicate IDs, update/view stock |
| 2 | Multi-User Cart System | Separate carts per user, add/remove/update items |
| 3 | Real-Time Stock Reservation | Reserve on add-to-cart, release on remove |
| 4 | Concurrency Simulation | Threading + logical locking to prevent overselling |
| 5 | Order Placement Engine | Atomic cart → order conversion (all or nothing) |
| 6 | Payment Simulation | 70% success rate, random failures |
| 7 | Transaction Rollback | Full rollback on payment failure, stock restored |
| 8 | Order State Machine | CREATED → PENDING_PAYMENT → PAID → SHIPPED → DELIVERED / FAILED / CANCELLED |
| 9 | Discount & Coupon Engine | Auto 10% on >₹1000, bulk 5%, SAVE10 & FLAT200 coupons |
| 10 | Inventory Alert System | Low stock warnings, block purchase if stock = 0 |
| 11 | Order Management | View all, filter by status, search by ID |
| 12 | Order Cancellation Engine | Cancel order + restore stock, block double-cancel |
| 13 | Return & Refund System | Partial return, update stock and order total |
| 14 | Event-Driven System | Event queue with ORDER_CREATED, PAYMENT_SUCCESS, INVENTORY_UPDATED |
| 15 | Inventory Reservation Expiry | Auto-release reserved stock after timeout |
| 16 | Audit Logging System | Immutable timestamped logs for every action |
| 17 | Fraud Detection System | Flag users for 3+ orders/minute or high-value orders |
| 18 | Failure Injection System | Toggle failure mode to force payment failures |
| 19 | Idempotency Handling | Prevent duplicate orders via idempotency keys |
| 20 | Microservice Simulation | Loosely coupled ProductService, CartService, OrderService, PaymentService |

---

## 🏗️ Design Approach

- **No external libraries** — pure Python 3.10+ using only `threading`, `uuid`, `datetime`, `random`, `enum`
- **In-memory data stores** — `dict` structures simulate a database
- **Logical locking** — `threading.Lock` per product prevents race conditions
- **Event-driven architecture** — decorator-based event handlers simulate a message queue
- **Atomic order placement** — all steps succeed or full rollback occurs
- **Microservice pattern** — `ProductService`, `CartService`, `OrderService`, `PaymentService` operate independently

---

## 📐 Assumptions

1. Data is in-memory only (no persistent database). Each run starts fresh with seed data.
2. "Concurrency" is simulated using Python threads with a `Barrier` to ensure simultaneous execution.
3. Payment has a 70% success rate by default; 100% failure when failure mode is enabled.
4. Reservation expiry is set to 5 minutes (configurable via `RESERVATION_EXPIRY_SECONDS`).
5. Low stock threshold is 5 units (configurable via `LOW_STOCK_THRESHOLD`).
6. Returns are only allowed on `DELIVERED` orders.
7. Fraud detection uses in-memory timestamps; resets on restart.

---

## 🚀 How to Run

### Requirements
- Python 3.10 or higher (uses `str | None` union type syntax)
- No pip installs needed

### Run the CLI
```bash
python ecommerce_order_engine.py
```

### Quick Demo Flow
```
1. Add a product        → Choice 1
2. View products        → Choice 2
3. Add to cart          → Choice 3
4. Apply coupon         → Choice 6 (try SAVE10 or FLAT200)
5. Place order          → Choice 7
6. View orders          → Choice 9
7. Cancel order         → Choice 8
8. Test concurrency     → Choice 12
9. View audit logs      → Choice 13
10. Toggle failure mode → Choice 14
```

---

## 📁 Project Structure

```
ecommerce_order_engine.py   ← Single-file implementation (all 20 tasks)
README.md                   ← This file
```

---

## 🧪 Sample Test Scenarios

**Scenario 1 — Happy Path:**
Add product → Add to cart → Place order → Advance to SHIPPED → DELIVERED → Return product

**Scenario 2 — Payment Failure Rollback:**
Enable failure mode (Choice 14) → Place order → Watch rollback restore stock

**Scenario 3 — Concurrency:**
Add a product with stock=5 → Choice 12 (3 users, 3 qty each) → Only one user succeeds

**Scenario 4 — Coupon + Discount Stack:**
Add items worth >₹1000 → Apply SAVE10 → Place order → See compounded discount

---

## 👨‍💻 Author

Hackathon Submission — Distributed E-Commerce Order Engine  
Repository: `<BHARGAVI>_Ecommerce_Order_Engine_Hackathon`
