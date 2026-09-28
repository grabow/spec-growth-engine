---
id: checkout
parent: app
kind: component
contract:
  provides:
    - "createOrder(cart): Order"
  acceptance_criteria:
    - "An order is created only after payment is authorized."
design:
  approach: "Authorize payment, then build the order."
depends_on: [payment]
code: ["src/checkout/*.ts"]
status: specd
---

# Checkout
Depends on payment. (It also imports util/log WITHOUT declaring it -> drift.)
