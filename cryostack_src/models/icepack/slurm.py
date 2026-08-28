def build_slurm_script(*, header: str, body: str) -> str:
    return header + "\n" + body + "\n"


def build_container_fragment(*, example_dir, sif_path, target):
    return f'''apptainer exec -B "{example_dir}":/workspace/example "{sif_path}" with-icepack bash -lc 'cd /workspace/example && python "{target}"' '''
