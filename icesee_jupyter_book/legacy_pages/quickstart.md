# Quickstart

This page provides the fastest way to begin using ICESEE in the GHUB environment.
It is intentionally minimal: one runnable tutorial, a few key concepts, and clear next steps.

---

## 1. Run the first end-to-end example

The recommended entry point is the Lorenz-96 tutorial notebook, which demonstrates a full
forecast → analysis data assimilation cycle in a lightweight setting.

```{button-link} icesee_jupyter_notebooks/run_lorenz96_da.html
:color: success
:expand:
Run the Lorenz-96 Tutorial
```

---

## 2. What this tutorial demonstrates

The Lorenz-96 example illustrates the core ICESEE workflow:

- ensemble initialization  
- model forecast propagation  
- synthetic observation generation  
- EnKF-style analysis update  
- diagnostic evaluation (error and spread)

These same steps carry over to ice-sheet applications, where the model component is replaced
by a flowline solver or a full ice-sheet model.

---

## 3. Suggested path through the book

After completing Lorenz-96, continue with:

```{button-link} icesee_workflow.html
:color: primary
:expand:
ICESEE Workflow Overview
```

```{button-link} user_manual.html
:color: info
:expand:
GHUB User Manual
```

---

## 4. Moving beyond toy models

ICESEE is designed to scale from idealized systems to ice-sheet simulations.
For advanced execution environments:

```{button-link} running_with_containers.html
:color: secondary
:expand:
Running with Containers
```

```{button-link} icesee_hpc_coupling.html
:color: secondary
:expand:
ICESEE-HPC Coupling
```
