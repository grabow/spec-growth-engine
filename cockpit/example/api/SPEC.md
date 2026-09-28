---
id: api
parent: app
kind: container
contract:
  provides:
    - "HTTP API for product search and checkout"
design:
  children: [api.checkout, api.payment]
status: specd
---

# API container
Exposes the HTTP surface. Decomposes into checkout and payment components.
