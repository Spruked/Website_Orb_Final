# Website ORB Final Merge

This folder is the merged Website ORB build assembled from the local ORB packages in `E:\merge and compile lab for orb template`.

Active cognition is TPC only. HLSF and EGF are copied into the active backend as TPC field components. Older CALI/Renova cognition sources are preserved under `_source_orbs` for provenance but are not imported by the active request path.

## Runtime Shape

1. `tools/compile_site_world.py` runs at build time and writes `compiled_orb/site_world.json`.
2. The backend loads `site_world.json` and `pointer_plot_map.json` once at startup.
3. Route changes use a dictionary lookup against the precompiled route SKG record.
4. Visitor questions use intent matching plus the resident route record.
5. Pointer guidance resolves against the live DOM before any point/ping action. Unresolved targets stay voice-only.
6. TPC runtime maps each request through resident site facts, HLSF adjacency, and EGF telemetry when the local EGF dependencies are available.

## Main Folders

- `compiled_orb/` - resident site intelligence, pointer map, tool cache, and generated site world.
- `backend/` - FastAPI runtime, TPC-only cognition, HLSF, EGF, doctrine gate, pointer index, and DockStation adapter boundary.
- `frontend/` - embeddable Website ORB component, ORB visual, pointer runtime, and Dock bridge.
- `tools/` - build-time compiler and package validator.
- `tests/` - focused static/runtime tests for route lookup, pointer index, and guiderails.
- `architecture/` and `docs/` - review notes and install boundaries.
- `vendor/TPC_Triple_Predicate_Cubed/` - copied local TPC package from `R:\TPC_Triple_Predicate_Cubed`.
- `docs/reference/Triple_Predicate_Cubed.docx.pdf` - supplied TPC reference PDF.

## Review Commands

```bash
cd "E:\merge and compile lab for orb template\website_orb_final"
python tools/compile_site_world.py
python tools/validate_package.py
python -m py_compile backend/*.py backend/runtime/*.py backend/cognition/*.py backend/cognition/hlsf_geometry/*.py backend/cognition/Epistemic_Gravity_Field/*.py backend/pointer/*.py backend/dock_adapter/*.py tools/*.py tests/*.py
```
