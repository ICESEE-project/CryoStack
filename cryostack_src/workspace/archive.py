"""Extract regular result files without SMB-incompatible metadata operations."""
from pathlib import Path
import shutil


def archive_size(archive, destination, *, max_files=50000):
    root=Path(destination).resolve()
    members=archive.getmembers()
    if len(members)>max_files: raise ValueError("Too many files in result archive")
    total=0
    for member in members:
        target=(root/member.name).resolve()
        if not target.is_relative_to(root) or member.name.startswith("/"):
            raise ValueError("Result archive path escapes the workspace")
        if not (member.isfile() or member.isdir()):
            raise ValueError("Result archives may contain only regular files and directories")
        if member.size<0: raise ValueError("Invalid result archive size")
        if member.isfile(): total+=member.size
    return total


def extract_contents(archive,destination):
    archive_size(archive,destination)  # Preflight every member before any write.
    root=Path(destination).resolve()
    for member in archive.getmembers():
        target=root/member.name
        if member.isdir(): target.mkdir(parents=True,exist_ok=True)
        else:
            target.parent.mkdir(parents=True,exist_ok=True)
            with archive.extractfile(member) as source,target.open("wb") as output:
                shutil.copyfileobj(source,output,length=1024*1024)
