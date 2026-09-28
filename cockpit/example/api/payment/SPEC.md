---
id: api.payment
parent: api
kind: component
contract:
  provides:
    - "authorize(amount): PaymentResult"
  error_behavior:
    - "Declined card -> PaymentResult.declined, no exception."
status: specd
---

# Payment
Authorizes a charge against the payment provider.
