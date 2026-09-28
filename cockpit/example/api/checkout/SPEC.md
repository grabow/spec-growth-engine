---
id: api.checkout
parent: api
kind: component
contract:
  provides:
    - "createOrder(cart): Order"
  invariants:
    - "An order is persisted only after payment is authorized."
  acceptance_criteria:
    - "A confirmed order exists in the database after a successful checkout."
design:
  approach: "Coordinate payment, then persist the order."
depends_on: [api.payment, data]
code: ["api/checkout/**/*.ts"]
status: specd
---

# Checkout
Coordinates a real payment authorization and order persistence.
