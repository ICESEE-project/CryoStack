# ICESEE on GHUB

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**ICESEE-GHUB** is an interactive **Jupyter Book** environment that brings the ICESEE (Ice-sheet Coupled Ensemble Simulator and Estimator) framework to the cloud through GHUB. This tool enables users to explore ensemble data assimilation workflows, run lightweight examples, and understand the ICESEE framework without requiring a full HPC setup.

## 🎯 What is ICESEE?

ICESEE supports ensemble data assimilation workflows (e.g., EnKF-style methods) with an emphasis on:

- **Modular structure** — Reuse the same DA logic across different models
- **Model coupling** — Integrate external codes/workflows while keeping the assimilation engine consistent  
- **Scalability** — Execute on HPC and cloud-style environments, including GHUB

For detailed implementation and broader documentation, see the [ICESEE Wiki](https://github.com/ICESEE-project/ICESEE/wiki).

## ✨ Key Features

- 📚 **Interactive Jupyter Book** format with comprehensive documentation
- 🚀 **Runnable tutorials** including the Lorenz-96 data assimilation demo
- 🔗 **Cloud-ready deployment** through GHUB infrastructure
- 📊 **Ensemble data assimilation** workflows (EnKF-style methods)
- 🧩 **Modular design** for coupling with ice-sheet models (ISSM, Icepack, flowline solvers)
- 💻 **No HPC required** for lightweight examples

## 📋 Prerequisites

- Access to GHUB (https://theghub.org)
- For local development:
  - Python 3.8+
  - Anaconda or Miniconda
  - Jupyter Book
  - Git with submodule support

## 🚀 Quick Start

### On GHUB

1. Navigate to the ICESEE tool on GHUB
2. Launch the tool
3. The Jupyter Book will open automatically
4. Start with the **Lorenz-96 tutorial** for a complete end-to-end example

### Local Installation

```bash
# Clone the repository with submodules
git clone --recursive https://github.com/ICESEE-project/ICESEE-GHUB.git
cd ICESEE-GHUB

# If you already cloned without --recursive, initialize submodules
git submodule update --init --recursive

# Build the Jupyter Book
cd src
make install
```

## 📖 Documentation

This repository provides comprehensive documentation through a Jupyter Book, including:

- **[Quickstart Guide](icesee_jupyter_book/quickstart.md)** — Fastest way to get started
- **[User Manual](icesee_jupyter_book/user_manual.md)** — Practical usage notes
- **[ICESEE Workflow](icesee_jupyter_book/icesee_workflow.md)** — Conceptual overview of the DA cycle
- **[Tutorial Notebooks](icesee_jupyter_book/icesee_jupyter_notebooks/)** — Interactive examples including:
  - Lorenz-96 data assimilation demo (runnable in GHUB)
  - Flowline model coupling
  - ISSM and Icepack integration examples
- **[HPC Coupling Guide](icesee_jupyter_book/icesee_hpc_coupling.md)** — Advanced deployment patterns
- **[Container Usage](icesee_jupyter_book/running_with_containers.md)** — Docker/Singularity workflows

For upstream ICESEE documentation: [ICESEE Wiki](https://github.com/ICESEE-project/ICESEE/wiki)

## 🗂️ Project Structure

```
ICESEE-GHUB/
├── icesee_jupyter_book/     # Jupyter Book source files
│   ├── icesee_jupyter_notebooks/  # Tutorial notebooks
│   ├── _config.yml          # Book configuration
│   ├── _toc.yml            # Table of contents
│   └── *.md                # Documentation pages
├── external/
│   └── ICESEE/             # ICESEE core (git submodule)
├── bin/                    # Scripts for launching the book
├── middleware/             # GHUB integration scripts
├── src/                    # Build system
│   ├── Makefile           # Build commands
│   └── readme.txt         # Build instructions
├── LICENSE                 # MIT License
└── README.md              # This file
```

## 🔧 Building the Book Locally

```bash
# Navigate to the source directory
cd src

# Install and build
make install

# View the built book (opens on localhost:8080)
cd ../icesee_jupyter_book/_build/html
python -m http.server 8080
```

## 🔗 ICESEE Core Integration

This repository integrates with the main ICESEE codebase:

- **Core source**: [ICESEE](https://github.com/ICESEE-project/ICESEE)  
- **Integration method**: Git submodule in `external/ICESEE/`
- **Version pinning**: Tracks the `main` branch for reproducibility (recommended: pin by tag for releases)

## 🤝 Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

**Copyright (c) 2026 ICESEE, Brian Kyanjo, Alexander Robel**

## 📚 Citation

If you use ICESEE in your research, please cite:

```bibtex
@software{icesee2026,
  author = {Kyanjo, Brian and Robel, Alexander},
  title = {ICESEE: Ice-sheet Coupled Ensemble Simulator and Estimator},
  year = {2026},
  url = {https://github.com/ICESEE-project/ICESEE}
}
```

## 💬 Support

- **Issues**: [GitHub Issues](https://github.com/ICESEE-project/ICESEE-GHUB/issues)
- **Documentation**: [ICESEE Wiki](https://github.com/ICESEE-project/ICESEE/wiki)
- **GHUB Support**: https://theghub.org/support

## 🙏 Acknowledgments

This work builds upon the ICESEE framework and leverages GHUB infrastructure for cloud-based scientific computing.

---

**Maintained by**: Brian Kyanjo  
**Project**: ICESEE (Ice-sheet Coupled Ensemble Simulator and Estimator)
