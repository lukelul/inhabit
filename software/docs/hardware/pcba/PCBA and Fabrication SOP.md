# PCBA and Fabrication SOP

## Overview

This SOP covers ordering PCBs and PCBA (assembled boards) for the Inhabit Rev-A smart joint sensor node. The Altium project lives in a separate hardware repo; this documents the process and gotchas.

---

## Gerber Generation

- [ ] Open Altium project, run DRC (Design Rule Check) -- no errors
- [ ] Generate Gerbers: File -> Fabrication Outputs -> Gerber Files
- [ ] Include all copper layers, silkscreen, solder mask, paste mask
- [ ] Generate NC Drill file: File -> Fabrication Outputs -> NC Drill Files
- [ ] Verify Gerber output in a viewer (e.g., KiCad Gerber Viewer, gerbv, or fab house online viewer)

---

## BOM (Bill of Materials)

- [ ] Export BOM from Altium with: Designator, Quantity, Value, Package, Manufacturer, MPN
- [ ] Map parts to JLCPCB/LCSC part numbers (or PCBWay part library)
- [ ] Flag parts NOT available at the fab house -- source separately
- [ ] STM32C011 dev module is intentionally **excluded** from PCBA (hand-soldered)

---

## CPL / Pick-and-Place File

- [ ] Generate pick-and-place / centroid file from Altium
- [ ] Columns: Designator, Mid X, Mid Y, Rotation, Layer (Top/Bottom)
- [ ] Verify coordinate origin matches the fab house expectation
- [ ] Cross-check CPL against BOM (every BOM part on PCBA should have a CPL entry)

---

## PCBA Side Selection

- [ ] Identify which components go on top vs bottom
- [ ] WARNING: Bottom-side PCBA component orientation is **UNVERIFIED** -- double-check from schematic and 3D view
- [ ] If both-sides PCBA: confirm fab house supports two-pass assembly
- [ ] Cost: single-side PCBA is significantly cheaper; evaluate if all critical components fit on one side

---

## Parts Intentionally Excluded from PCBA

| Part | Reason | Assembly Method |
|------|--------|-----------------|
| STM32C011 dev module | Different footprint than bare chip; hand-soldered for Rev-A | Solder by hand after PCBA |
| Pin headers / connectors (TBD) | May not be in fab house library | Solder by hand |

---

## How to Verify Orientations

- [ ] Cross-check 3D view in Altium with PCBA orientation rendering from fab house
- [ ] Verify IC pin 1 markers match between schematic, footprint, and physical part
- [ ] For MCP2515: verify SOIC-18 orientation (pin 1 notch)
- [ ] For SN65HVD230: verify SOIC-8 orientation
- [ ] For TVS (SM24CANB-02HTG): verify polarity marking

---

## Fab House Notes

### JLCPCB
- Upload Gerbers as ZIP
- Upload BOM and CPL in their template format
- Select "Economic PCBA" for prototype runs
- Choose SMT assembly side (top/bottom/both)
- Review part placement in their online viewer before confirming
- Standard PCBA lead time: ~7-10 business days + shipping

### PCBWay
- Upload Gerbers; they quote PCB separately from PCBA
- BOM format: flexible, but include MPN
- CPL format: their template or standard centroid
- Turnkey vs consigned: turnkey (they source parts) is easier for prototypes

---

## Common Failure Modes

| Failure | Prevention |
|---------|------------|
| Wrong component rotation | Verify in fab house 3D viewer before ordering |
| Missing component (not in stock) | Check stock before ordering; pre-order if long lead time |
| Wrong footprint (pad mismatch) | Compare Altium footprint with actual part datasheet |
| Solder bridges on fine-pitch | Use solder paste stencil; reflow temperature profile correct |
| Wrong layer assignment | Verify Gerber layer mapping in fab house upload |
| Drill holes misaligned | Verify NC drill file origin matches Gerber origin |

---

## How to Respond to Fab Engineering Questions

Common fab house questions and answers:

| Question | Answer |
|----------|--------|
| "Are slots plated or non-plated?" | Check Altium design; if for connectors, likely non-plated. If via/pad, plated. |
| "Tooling holes -- can we add them?" | Yes, add in board corners, keep clear of components/traces |
| "Which side is top for assembly?" | Top side has silkscreen markings and component reference designators |
| "V-score or tab-route for panelization?" | Prefer tab-route for small boards; V-score for rectangular arrays |
| "Confirm board thickness" | Standard 1.6mm unless otherwise specified in design |

---

## PCBA Remarks (what to put in the order notes)

```
- STM32 dev module (U_STM32) is NOT assembled -- do not place.
- [List any other hand-assembled parts]
- Both-sides assembly required [if applicable].
- Please confirm component orientations before production.
- 120-ohm CAN bus termination resistor: [included/not included on board].
```

---

## Pre-Order Checklist

- [ ] DRC clean
- [ ] Gerbers generated and verified in viewer
- [ ] BOM complete with MPN and stock verified
- [ ] CPL file generated and cross-checked
- [ ] Excluded parts clearly marked
- [ ] Component orientations verified (especially bottom-side)
- [ ] Board outline correct
- [ ] Drill file correct
- [ ] Silkscreen readable
- [ ] Fab house order configured correctly (layers, thickness, finish, PCBA sides)

## Post-Order Review Checklist

- [ ] Review fab house confirmation/preview renders
- [ ] Verify component placement matches Altium layout
- [ ] Confirm excluded parts are NOT in their assembly plan
- [ ] Save order confirmation and tracking
- [ ] Plan hand-assembly of excluded parts upon arrival

## Production File Checklist

- [ ] Gerber ZIP
- [ ] NC Drill file
- [ ] BOM (fab house format)
- [ ] CPL / centroid file (fab house format)
- [ ] Assembly drawing (PDF from Altium)
- [ ] Schematic PDF (for reference during engineering questions)
