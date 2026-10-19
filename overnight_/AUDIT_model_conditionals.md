# AUDIT — `if model == "issm"` / `if model == "icepack"` across the platform (PASS 4, task 10)

Every literal model-name branch in non-test code at HEAD `e15b8e3`, categorised
as **CAPABILITY DECISION** (belongs in `ModelCapabilities`), **SCIENTIFIC
DIFFERENCE** (a real difference in the science/tooling — keep explicit), or
**IMPLEMENTATION DEBT** (a dict/adapter method would be cleaner, but behaviour
is correct — defer).

The brief: *replace only capability decisions; preserve scientific differences
explicitly; do not blindly eliminate branches.*

---

## Replaced this pass (CAPABILITY DECISION → registry)

| Location | Was | Now |
|---|---|---|
| `agents/planning_tools.py:132` | `p.model == "issm" and p.backend == "container"` (MATLAB) | `get_model_capabilities(p.model).requires_matlab and p.backend == "container"` |
| `agents/planning_tools.py:233` | `p.model == "issm" and p.backend == "container"` (`matlab_required`) | same |
| `agent_execution/remote_backend.py:_preflight` | `plan.model == "issm"` (MATLAB preflight) | `get_model_capabilities(plan.model).requires_matlab` |

`ModelCapabilities.requires_matlab` is `True` for issm, `False` for icepack, and
import-time consistent with the adapters (`capabilities.py:_verify_against_adapters`).
A future MATLAB-based model now works without touching these sites.

---

## CAPABILITY DECISION — recommended, NOT changed this pass (gateway / cloud risk)

| Location | Branch | Recommendation |
|---|---|---|
| `cloud/preflight.py:58` | `m == "issm" and not matlab_license_configured` | → `get_model_capabilities(m).requires_matlab`. Safe (icepack already blocked by the `SUPPORTED_CLOUD_MODELS` check two lines up) but load-bearing cloud code — change with a dedicated test. |
| `icesheets_gateway.py:2025` | `backend_dd.value == "container" and model_dd.value == "issm" and _matlab_license is None` | → `...requires_matlab...`. Gateway; defer to a reviewed commit. |
| `icesheets_gateway.py:2797` (`_spack_matlab_license`) | `if model != "issm": return None` | → `if not get_model_capabilities(model).requires_matlab: return None`. Gateway; defer. |
| `icesheets_gateway.py:1490-1491` | which config panel to show (`md_config_panel` vs `icepack_config_panel`) | This is "which panel", driven by `capabilities.basic_mode_config` conceptually, but the panels are genuinely model-specific widgets. Low value to abstract; **keep**. |
| `icesheets_gateway.py:1528` / `2790` | placeholder / exec-dir hint text per model | cosmetic; could read `capabilities.entrypoint_kind`. IMPL DEBT, low priority. |

---

## SCIENTIFIC DIFFERENCE — keep explicit (do not touch)

| Location | Why it is a real difference |
|---|---|
| `agents/planning_tools.py:107-117` | ISSM validates against a curated `md.*` spec with solver detection; Icepack against a Basic-mode parameter list. Different validators (`validate_md_config` vs `validate_icepack_config`), different science. |
| `agents/readonly_tools.py:110-117` | ISSM exposes "curated md.* parameters, solver-aware"; Icepack exposes an explicit `BASIC_MODE_PARAMETERS` list. Different config models. |
| `agent_execution/remote_backend.py:_staging_glue` (`419-424`) | ISSM override = a generated `cryostack_md_overrides.m` **file** + an `inject_override_step` transform before the first `solve()`. Icepack override = an exact single-line **text substitution** of a Python literal in the notebook. Fundamentally different injection mechanisms. |
| `models/submission.py` (`442`, `475-494`, `532`, `843`, `880-899`, `938-967`) | ISSM = MATLAB, `runme.m` entrypoint, MATLAB container env, an in-container `srun` shim; Icepack = Python, notebook/`.py` entrypoint, Firedrake, no MATLAB. The branches build genuinely different shell scripts. |
| `models/submission.py:96` (`_matlab_container_env`) | only ISSM+container needs a MATLAB licence env; the function returns `("","")` otherwise. Could key off `requires_matlab` — borderline CAPABILITY — but it is deep in the submit-script builder; **defer** with the gateway cluster. |
| `remote/spack_env.py:111`, `:134` | ISSM readiness = `ISSM_DIR` + `issm.exe` exist; Icepack readiness = `python -c "import firedrake, icepack"`. Different probes for different runtimes. |
| `models/stack/compat.py:115`, `:144` | Icepack is `gated_by="firedrake"` / environment-sensitive; ISSM is compiled/override-none. A real stack-compatibility difference. |
| `core/icesheet_examples.py:176-180` | ISSM examples are directories with `runme.m`; Icepack examples are `.ipynb`/`.py` files. Different discovery globs. Could read `capabilities.entrypoint_kind`; marginal. |
| `icesheets_gateway.py:815` (`issm_md` serializer key) | only ISSM has `md` overrides; the key is absent for Icepack. Serializer contract — do not rename. |
| `icesheets_gateway.py:1246`, `823` | route `set_example` / overrides to the model's own config panel. UI wiring around model-specific panels. |
| `icesheets_gateway.py:2096`, `remote_backend.py:348` | spack variant name `--with-issm` / `--with-icepack`. A spack fact, not a capability. |
| `llm_adapters.py:111` | `RuleBasedAdapter` only maps `ice_temperature` for icepack — because that is Icepack's Basic-mode parameter. Correct scoping. |

---

## IMPLEMENTATION DEBT — noted, deferred

* `models/submission.py` has the pattern `if model == "issm": … elif model ==
  "icepack": …` repeated ~6 times inside one function family
  (`475-494`, `880-899`, `938-967`). A `ModelSubmissionProfile` (entrypoint
  name, interpreter, container env builder, post-process block) resolved once
  would remove the repetition. Substantial refactor of a critical path; do it
  with a live-run regression, not autonomously.
* Placeholder / hint strings in the gateway could come from `ModelCapabilities`
  (`entrypoint_kind`, a new `example_hint` field). Cosmetic.

---

## Net

3 capability decisions moved to the registry (agent layer + the new submit
backend — all covered by tests). 3 more identified in the gateway/cloud,
recommended but deferred as they are load-bearing and warrant a reviewed
commit + a live run. Everything else is a real scientific/tooling difference
and stays an explicit branch — as it should.
