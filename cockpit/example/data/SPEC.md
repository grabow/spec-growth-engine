---
id: data
parent: app
kind: container
contract:
  provides:
    - "Persistent product and order data"
  invariants:
    - "The database is the single source of product data."
design:
  approach: "PostgreSQL."
status: specd
---

# Data container
Owns persistence. The single source of truth for product and order data.
