---
id: payment
parent: app
kind: component
contract:
  provides:
    - "authorize(amount): PaymentResult"
  error_behavior:
    - "Declined card -> { ok: false }, no exception."
code: ["src/payment/*.ts"]
status: specd
---

# Payment
Authorizes a charge.
