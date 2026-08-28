def build_slurm_script(*, header: str, body: str) -> str:
    return header + "\n" + body + "\n"


def build_container_fragment(*, example_dir, exec_dir, sif_path, target):
    return f'''apptainer exec -B "{example_dir}":/opt/ISSM/examples,"{exec_dir}":/opt/ISSM/execution "{sif_path}" with-issm matlab -nodesktop -nosplash -r "cd('/opt/ISSM/examples'); run('{target}'); exit"'''
