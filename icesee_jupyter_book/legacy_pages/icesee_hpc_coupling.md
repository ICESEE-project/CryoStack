# ICESEE-HPC Coupling

ICESEE is designed to scale from small tutorial problems to large ensemble simulations
coupled with full ice-sheet models. These applications typically require HPC resources.

---

## When HPC is needed

HPC execution becomes important when:

- ensemble sizes are large  
- model forecasts are expensive (SSA/full-Stokes solvers)  
- workflows require MPI parallelism  
- data volumes require structured storage (HDF5/Zarr)

ICESEE provides the assimilation logic, while HPC resources provide the computational scale.

---

## Coupling to external ice-sheet models

ICESEE supports coupling patterns where:

- ICESEE manages ensemble state and analysis updates  
- an external model (ISSM, Icepack, custom solvers) performs the forecast step  
- restart files or standardized outputs provide the exchange interface  

This keeps the DA engine model-independent.

---

## Parallel execution model

In typical deployments:

- each ensemble member forecast runs as an independent task  
- MPI or job arrays distribute members across compute nodes  
- ICESEE gathers outputs for the analysis step  
- diagnostics and results are written in portable formats  

The GHUB tool provides templates and documentation, while full-scale execution occurs externally.

---

## Further documentation

Detailed coupling notes and run scripts are maintained upstream:

- https://github.com/ICESEE-project/ICESEE/wiki

---

```{button-link} running_with_containers.html
:color: secondary
:expand:
Running with Containers
```
