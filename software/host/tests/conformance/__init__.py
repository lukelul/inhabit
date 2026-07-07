"""Conformance test harness — every registered plugin must pass its abstract suite.

Auto-discovers all plugins from each Registry. A new plugin passes the harness
automatically if it obeys the contract — no test edits needed.

Extension points covered:
  - RobotAdapter (host/adapters)
  - CanTransport (host/transport)
  - Exporter (host/export)
  - SensorSource (host/sensors)
  - EventDetector (host/events)
  - EpisodeSink (host/logger/sinks)
"""
