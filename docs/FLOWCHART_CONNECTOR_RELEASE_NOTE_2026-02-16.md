# Release Note: Flowchart Connector Modes

Date: 2026-02-16

## Summary

Studio flowcharts now support explicit connector behavior modes on each edge:

- `solid`: trigger + context
- `dotted`: pull-only context dependency

This enables fan-out triggers and shared context fan-in without forcing execution on every dependency edge.

## What changed

- Edge payloads include `edge_mode` (`solid` or `dotted`).
- Editor shows connector mode in the edge inspector.
- Canvas rendering uses line style semantics:
  - solid line for `solid`
  - dotted line for `dotted`
- Runtime scheduling:
  - only solid edges enqueue downstream execution
  - dotted edges contribute pullable context only
- Run history metadata distinguishes trigger edges from pulled dotted context.

## Migration note

- Existing edges default to `solid`.
- No manual migration is required for existing flowcharts.
- Existing graphs retain prior behavior until users explicitly set edges to `dotted`.

## Compatibility notes

- Decision route matching uses `condition_key` on solid edges only.
- Source->target pairs cannot mix `solid` and `dotted`.
- Dotted sources are optional and do not block execution when no successful output exists yet.
