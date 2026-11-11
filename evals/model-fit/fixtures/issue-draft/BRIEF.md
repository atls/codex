# Profile Comparison Task Brief

Write a short private draft for one issue in English. Do not publish it, design a new architecture, or add requirements. Include a title, a concise description, and verifiable acceptance criteria.

Established solution:

- Search only local snapshots from two sources; make no network requests
- Support an exact phrase query and an optional source filter
- Include the source identifier and matching excerpt with each result
- Remove documents from the results after their snapshot is replaced
- Return results in a deterministic order when relevance is tied
- Return an explicit error for an empty query
- Keep user interface work out of scope
