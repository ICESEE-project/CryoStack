# Running with Containers

Some ICESEE workflows depend on external modeling stacks (e.g., ISSM, Icepack, Firedrake)
that are not available in lightweight GHUB sessions. Containers provide a reproducible way
to run these environments consistently across systems.

---

## Why containers?

Containers are useful when you need:

- consistent versions of scientific dependencies  
- reproducible builds across machines and clusters  
- integration with complex external solvers  
- portability between local development and HPC execution  

They provide a practical bridge between GHUB tutorials and full research deployments.

---

## Typical ICESEE container workflow

A common pattern is:

1. Build or pull a container image with required model toolchains  
2. Mount an ICESEE run directory into the container  
3. Execute ensemble forecasts and assimilation cycles inside the container  
4. Write outputs to shared volumes for post-processing  

This keeps the assimilation workflow consistent while isolating heavy dependencies.

---

## Recommended practice

- Keep GHUB notebooks lightweight and instructional  
- Use containers for solver-heavy couplings (ISSM/Icepack)  
- Treat container images as part of the reproducible workflow  

---

## Upstream references

Container and deployment notes are maintained in the ICESEE Wiki:

- https://github.com/ICESEE-project/ICESEE/wiki

---

```{button-link} user_manual.html
:color: secondary
:expand:
Back to User Manual
```

```{button-link} index.html
:color: secondary
:expand:
Back to Home
```
