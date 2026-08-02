---
status: closed
type: grilling
labels: [wayfinder:grilling, charter]
---
## Question
Where do the map and tickets live?

## Resolution
Originally a local markdown tracker in-repo. Superseded 2026-08-02 by Ricky's direction:
the tracker is **GitHub Issues** on the public repo. The map is issue #1; local ticket
files were migrated 1:1 (local NNNN → issue #N) and then retired. Blocking is expressed
as "Blocked by #N" lines in issue bodies; frontier = open + unassigned + all blockers closed.
