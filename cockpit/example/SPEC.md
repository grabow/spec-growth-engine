---
id: app
parent: null
kind: system
contract:
  purpose: "Curated product finder."
  external_actors: ["End user"]
  acceptance_criteria: ["Search works end-to-end, locally verified."]
design:
  children: [api, data]
  constraints: "see ARCHITECTURE.md"
status: specd
---

# System context
The app finds curated products. It splits into an api container and a data
container. Global rules live in ARCHITECTURE.md, not here.
