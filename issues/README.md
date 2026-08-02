# Local issue tracker (wayfinder)

This folder is the tracker. One issue per file, `NNNN-slug.md`; numbers are stable ids.

- Frontmatter: `status: open | closed`, `type: research | grilling | prototype | task`,
  `labels`, `assignee` (an open unassigned ticket is unclaimed; assign yourself before working it),
  `blocked_by: [NNNN, ...]` (native blocking convention).
- The map is [0001-map.md](0001-map.md) (`wayfinder:map`). Open tickets are its children.
- A ticket is on the **frontier** when open, unassigned, and every `blocked_by` issue is closed.
- Resolve = append `## Resolution` to the ticket, set `status: closed`, add one line to the
  map's Decisions-so-far. One ticket per session (research tickets excepted).
