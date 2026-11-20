"""Download S3 result bytes directly to SMB, without timestamp preservation."""
from __future__ import annotations
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from urllib.parse import urlsplit


def _output(result):
    code,out,err=result if isinstance(result,tuple) else (result.returncode,result.stdout,result.stderr)
    if code: raise RuntimeError("Cloud result transfer failed; previous results were retained.")
    return json.loads(out or "{}")


def fetch_s3_contents(run_uri,destination,*,invoke,reserve,max_files=50000):
    uri=urlsplit(run_uri)
    if uri.scheme!="s3" or not uri.netloc or not uri.path.strip("/"):
        raise ValueError("A full S3 run URI is required")
    prefix=uri.path.lstrip("/").rstrip("/")+"/outputs/"
    listing=_output(invoke(["s3api","list-objects-v2","--bucket",uri.netloc,
                           "--prefix",prefix,"--max-items",str(max_files+1),"--output","json"]))
    objects=listing.get("Contents",[])
    if listing.get("NextToken") or len(objects)>max_files:
        raise ValueError("Too many cloud result files")
    files=[];names=set();total=0
    for obj in objects:
        key=obj.get("Key","")
        if not isinstance(key,str) or not key.startswith(prefix): raise ValueError("Unexpected cloud result key")
        relative=key[len(prefix):]
        if not relative or relative.endswith("/"):continue
        path=PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts or "\\" in relative or relative in names:
            raise ValueError("Unsafe cloud result path")
        size=obj.get("Size")
        etag=obj.get("ETag")
        if isinstance(size,bool) or not isinstance(size,int) or size<0 or not isinstance(etag,str) or not etag:
            raise ValueError("Cloud result metadata is incomplete")
        names.add(relative);files.append((key,path,size,etag));total+=size
    # Catch a file that would also be another file's parent before any writes.
    for _,path,_,_ in files:
        if any(str(parent) in names for parent in path.parents if str(parent)!="."):
            raise ValueError("Conflicting cloud result paths")
    destination=Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    with reserve(total):
        with tempfile.TemporaryDirectory(prefix=".cloud-incoming-",dir=destination.parent) as stage:
            stage=Path(stage)
            for key,path,size,etag in files:
                target=stage/path;target.parent.mkdir(parents=True,exist_ok=True)
                _output(invoke(["s3api","get-object","--bucket",uri.netloc,"--key",key,
                                "--if-match",etag,"--output","json",str(target)]))
                if not target.is_file() or target.stat().st_size!=size:
                    raise RuntimeError("Cloud result size changed during transfer")
            # Every transfer has succeeded before the previous cache is replaced.
            # A unique sibling backup also keeps rename failures recoverable.
            previous=stage.parent/(stage.name+"-previous")
            had_previous=destination.exists()
            if had_previous:destination.rename(previous)
            try:
                stage.rename(destination)
            except BaseException:
                if had_previous:previous.rename(destination)
                raise
            finally:
                if previous.exists() and destination.exists():shutil.rmtree(previous)
    return destination
