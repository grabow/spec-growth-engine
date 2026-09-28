---
id: app
parent: null
kind: system
contract:
  purpose: "Tiny checkout demo for Phase-4 drift detection."
design:
  children: [checkout, payment, util]
status: specd
---

# System context
Decomposes into checkout, payment and a shared util component.
