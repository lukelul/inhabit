# docs/ -- Inhabit Obsidian Technical Documentation Vault

This directory is an Obsidian-compatible knowledge system for the Inhabit project.
Open it in Obsidian (or any Markdown reader) as a vault.

## Structure

```
docs/
  00-start/         Onboarding, first-day guide
  architecture/     System architecture, data flow, module boundaries
  hardware/         Rev-A hardware stack, PCB, PCBA
    bringup/        Board bring-up SOPs
    pcba/           PCB fabrication and assembly SOPs
  firmware/         STM32 firmware architecture and SOPs
  host/             Host software (Python, ROS 2) architecture
  data/             PVT data pipeline, ML-ready export
  ml/               ML training data notes (TBD)
  teleop/           Universal Teleop Kernel thesis
  last-centimeter/  Last-centimeter contact data thesis
  agents/           Agent operating model (Claude, Codex, CodeRabbit)
  sop/              Standard operating procedures
    development/    Autonomous dev workflow
    hardware/       Bench testing
    firmware/       Firmware dev and validation
    software/       Verification (pytest, ruff, mypy, C tests)
    review/         PR review and merge
    release/        Release, handoff, ultracode
  decisions/        Architecture Decision Records (ADR)
  maps/             Obsidian visual maps with wikilinks + Mermaid
  templates/        Reusable note templates
  checklists/       Step-by-step checklists
  risks/            Risk register
  glossary/         Term definitions
  benchmarks/       Benchmark execution plan
```

## Entry Point

Start at `../00-Inhabit Home.md` (the Obsidian home note).

## Conventions

- **[[wikilinks]]** for internal navigation
- **Mermaid** diagrams for data flow and architecture
- **TBD** marks uncertain or unimplemented details
- Frozen contracts are never modified from docs
- Source file paths are relative to the repo root
