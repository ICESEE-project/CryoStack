"""ISSM postprocessing: turn ``md.results`` into a transport-neutral result package.

Runs inside MATLAB on whatever resource executed the solve (Remote / Container /
Cloud -- the script knows nothing about any of them). Its single job:

    md.results  ->  outputs/{metadata.json, mesh/mesh.h5, fields/<Sol>/<Field>.h5,
                             model/md_final.mat, figures/}

``metadata.json`` describes what *actually* exists in ``md.results`` (never what
was expected). One unusual field never aborts the export: struct / cell /
object / unsupported-shape fields are recorded under ``skipped`` and the rest
still export. Deterministic plotting is NOT done here -- that is Commit 5.

The Python reader for this package is
:mod:`cryostack_src.models.issm.results` -- it needs neither MATLAB nor ISSM.
"""
from __future__ import annotations

_MATLAB = r"""
% =====================================================================
% CryoStack ISSM neutral result export  (auto-generated -- do not edit)
% =====================================================================
disp('[cryostack] exporting neutral result package ...');

if ~exist('ICESEE_RUN_DIR', 'var') || isempty(ICESEE_RUN_DIR)
    ICESEE_RUN_DIR = pwd;
end
cs_outdir  = fullfile(ICESEE_RUN_DIR, 'outputs');
cs_meshdir = fullfile(cs_outdir, 'mesh');
cs_flddir  = fullfile(cs_outdir, 'fields');
cs_moddir  = fullfile(cs_outdir, 'model');
cs_figdir  = fullfile(cs_outdir, 'figures');
for cs_d = {cs_outdir, cs_meshdir, cs_flddir, cs_moddir, cs_figdir}
    if ~exist(cs_d{1}, 'dir'); mkdir(cs_d{1}); end
end

cs_meta = struct();
cs_meta.schema  = 'cryostack.issm.results';
cs_meta.version = 1;
cs_meta.model   = 'issm';
cs_meta.created = datestr(now, 'yyyy-mm-ddTHH:MM:SS');
cs_meta.status  = 'ok';
cs_meta.solutions = {};

if ~exist('md', 'var')
    cs_meta.status = 'no-model';
    cs_write_metadata(cs_outdir, cs_meta);
    disp('[cryostack][WARN] md does not exist -- nothing to export.');
    return;
end

% -------- md_final.mat (full scientific reproducibility) --------------
try
    save(fullfile(cs_moddir, 'md_final.mat'), 'md', '-v7.3');
    disp(['[cryostack]   model: ' fullfile(cs_moddir, 'md_final.mat')]);
catch cs_ME
    disp(['[cryostack][WARN] could not save md_final.mat: ' cs_ME.message]);
end

% -------- mesh (once) ------------------------------------------------
cs_nv = double(md.mesh.numberofvertices);
cs_ne = double(md.mesh.numberofelements);
cs_E  = md.mesh.elements;
cs_ncols = size(cs_E, 2);
try
    cs_dim = double(md.mesh.dimension());
catch
    if isprop(md.mesh, 'z') && isnumeric(md.mesh.z) && numel(md.mesh.z) == cs_nv
        cs_dim = 3;
    else
        cs_dim = 2;
    end
end
cs_has_z = (isprop(md.mesh, 'z') && isnumeric(md.mesh.z) && numel(md.mesh.z) == cs_nv);

cs_meshfile = fullfile(cs_meshdir, 'mesh.h5');
if exist(cs_meshfile, 'file'); delete(cs_meshfile); end
h5create(cs_meshfile, '/x', cs_nv); h5write(cs_meshfile, '/x', double(md.mesh.x(:)));
h5create(cs_meshfile, '/y', cs_nv); h5write(cs_meshfile, '/y', double(md.mesh.y(:)));
if cs_has_z
    h5create(cs_meshfile, '/z', cs_nv); h5write(cs_meshfile, '/z', double(md.mesh.z(:)));
end
h5create(cs_meshfile, '/elements', [cs_ncols cs_ne], 'Datatype', 'int64');
h5write(cs_meshfile, '/elements', int64(cs_E.'));

cs_meta.mesh = struct('path', 'mesh/mesh.h5', ...
    'numberofvertices', cs_nv, 'numberofelements', cs_ne, ...
    'dimension', cs_dim, 'element_columns', cs_ncols, ...
    'connectivity_indexing', '1-based', 'has_z', cs_has_z);

% -------- solutions ------------------------------------------------
if ~isstruct(md.results) || isempty(fieldnames(md.results))
    cs_meta.status = 'no-results';
    cs_write_metadata(cs_outdir, cs_meta);
    disp('[cryostack][WARN] md.results is empty -- metadata written, no fields.');
    return;
end

cs_MARKERS = {'SolutionType', 'errlog', 'outlog', 'step', 'time'};
cs_sol_names = fieldnames(md.results);

for cs_si = 1:numel(cs_sol_names)
    cs_sname = cs_sol_names{cs_si};
    S = md.results.(cs_sname);
    if ~isstruct(S); continue; end
    cs_nsteps = numel(S);

    cs_sol = struct();
    cs_sol.name = cs_sname;
    cs_sol.transient = (cs_nsteps > 1);
    cs_sol.timesteps = cs_nsteps;
    cs_sol.time = [];
    cs_sol.step = [];
    if all(arrayfun(@(e) isfield(e, 'time') && isnumeric(e.time) && isscalar(e.time), S))
        cs_sol.time = arrayfun(@(e) double(e.time), S);
    end
    if all(arrayfun(@(e) isfield(e, 'step') && isnumeric(e.step) && isscalar(e.step), S))
        cs_sol.step = arrayfun(@(e) double(e.step), S);
    end

    cs_solfld = fullfile(cs_flddir, cs_sname);
    if ~exist(cs_solfld, 'dir'); mkdir(cs_solfld); end
    if cs_sol.transient
        cs_tf = fullfile(cs_solfld, 'time.h5');
        if exist(cs_tf, 'file'); delete(cs_tf); end
        if ~isempty(cs_sol.time)
            h5create(cs_tf, '/time', cs_nsteps); h5write(cs_tf, '/time', double(cs_sol.time(:)));
        end
        if ~isempty(cs_sol.step)
            h5create(cs_tf, '/step', cs_nsteps); h5write(cs_tf, '/step', double(cs_sol.step(:)));
        end
    end

    cs_all = {};
    for cs_k = 1:cs_nsteps
        cs_all = union(cs_all, fieldnames(S(cs_k)));
    end
    cs_all = setdiff(cs_all, cs_MARKERS);

    cs_fields  = {};
    cs_skipped = {};

    for cs_fi = 1:numel(cs_all)
        cs_fld = cs_all{cs_fi};
        try
            cs_loc = 'unknown'; cs_nlen = 0; cs_dtype = 'float64';
            cs_avail = false(1, cs_nsteps);
            cs_bad = '';
            for cs_k = 1:cs_nsteps
                if ~isfield(S(cs_k), cs_fld); continue; end
                v = S(cs_k).(cs_fld);
                if isstruct(v)
                    cs_bad = 'struct-valued field is not supported'; break;
                elseif iscell(v)
                    cs_bad = 'cell-valued field is not supported'; break;
                elseif ischar(v) || isstring(v)
                    cs_bad = 'string field is metadata, not a scientific array'; break;
                elseif isobject(v) && ~islogical(v)
                    cs_bad = 'object-valued field is not supported'; break;
                elseif ~isnumeric(v) && ~islogical(v)
                    cs_bad = ['unsupported type: ' class(v)]; break;
                end
                if strcmp(cs_dtype, 'float64')
                    cs_dtype = cs_matlab_dtype(v);
                end
                if isscalar(v)
                    if ~(isnan(double(v)) || double(v) == -9999)
                        if strcmp(cs_loc, 'unknown'); cs_loc = 'scalar'; end
                        cs_avail(cs_k) = true;
                    end
                elseif numel(v) == cs_nv
                    cs_loc = 'nodal'; cs_nlen = cs_nv; cs_avail(cs_k) = true;
                elseif numel(v) == cs_ne
                    cs_loc = 'elemental'; cs_nlen = cs_ne; cs_avail(cs_k) = true;
                else
                    if strcmp(cs_loc, 'unknown') || strcmp(cs_loc, 'scalar')
                        cs_loc = 'other'; cs_nlen = numel(v);
                    elseif cs_nlen ~= numel(v)
                        cs_bad = 'inconsistent shape across timesteps'; break;
                    end
                    cs_avail(cs_k) = true;
                end
            end

            if ~isempty(cs_bad)
                cs_skipped{end+1} = struct('name', cs_fld, 'reason', cs_bad, ...
                    'kind', cs_field_kind(S, cs_fld, cs_nsteps)); %#ok<AGROW>
                continue;
            end
            if strcmp(cs_loc, 'unknown') || ~any(cs_avail)
                cs_skipped{end+1} = struct('name', cs_fld, ...
                    'reason', 'no usable numeric data at any timestep', 'kind', 'empty'); %#ok<AGROW>
                continue;
            end

            cs_rel = ['fields/' cs_sname '/' cs_fld '.h5'];
            cs_fpath = fullfile(cs_outdir, cs_rel);

            if strcmp(cs_loc, 'scalar')
                if cs_sol.transient
                    cs_col = nan(cs_nsteps, 1);
                    for cs_k = 1:cs_nsteps
                        if cs_avail(cs_k); cs_col(cs_k) = double(S(cs_k).(cs_fld)); end
                    end
                    cs_write_vector(cs_fpath, cs_col);
                    cs_shp = cs_nsteps;
                else
                    cs_write_vector(cs_fpath, double(S(1).(cs_fld)));
                    cs_shp = 1;
                end
            else
                if cs_nlen == 0; cs_nlen = cs_nv; end
                if cs_sol.transient
                    cs_M = nan(cs_nsteps, cs_nlen);
                    for cs_k = 1:cs_nsteps
                        if cs_avail(cs_k)
                            vv = double(S(cs_k).(cs_fld));
                            cs_M(cs_k, 1:numel(vv)) = vv(:).';
                        end
                    end
                    cs_write_matrix(cs_fpath, cs_M);
                    cs_shp = [cs_nsteps cs_nlen];
                else
                    cs_write_vector(cs_fpath, double(S(1).(cs_fld)));
                    cs_shp = cs_nlen;
                end
            end

            % 'units' is intentionally NOT emitted -- ISSM result structs carry
            % no unit metadata and CryoStack does not fabricate it.
            cs_entry = struct('name', cs_fld, 'location', cs_loc, 'shape', cs_shp, ...
                'dtype', cs_dtype, 'path', cs_rel);
            if cs_sol.transient
                cs_entry.available_timesteps = find(cs_avail) - 1;
            end
            cs_fields{end+1} = cs_entry; %#ok<AGROW>

        catch cs_ME
            cs_skipped{end+1} = struct('name', cs_fld, ...
                'reason', ['export error: ' cs_ME.message], 'kind', 'error'); %#ok<AGROW>
        end
    end

    cs_sol.fields  = cs_fields;
    cs_sol.skipped = cs_skipped;
    cs_meta.solutions{end+1} = cs_sol; %#ok<AGROW>
    disp(['[cryostack]   ' cs_sname ': ' num2str(numel(cs_fields)) ' field(s), ' ...
          num2str(numel(cs_skipped)) ' skipped']);
end

cs_write_metadata(cs_outdir, cs_meta);
disp('[cryostack] neutral result package written.');

% ---------------------------------------------------------------------
function cs_write_vector(fpath, v)
    if exist(fpath, 'file'); delete(fpath); end
    v = double(v(:));
    h5create(fpath, '/values', numel(v));
    h5write(fpath, '/values', v);
end

function cs_write_matrix(fpath, M)
    if exist(fpath, 'file'); delete(fpath); end
    M = double(M);
    h5create(fpath, '/values', [size(M, 2) size(M, 1)]);
    h5write(fpath, '/values', M.');
end

function s = cs_matlab_dtype(v)
    switch class(v)
        case 'double';  s = 'float64';
        case 'single';  s = 'float32';
        case 'logical'; s = 'bool';
        otherwise;      s = class(v);
    end
end

function k = cs_field_kind(S, fld, nsteps)
    k = 'unknown';
    for i = 1:nsteps
        if isfield(S(i), fld)
            v = S(i).(fld);
            if isstruct(v); k = 'struct';
            elseif iscell(v); k = 'cell';
            elseif ischar(v) || isstring(v); k = 'char';
            elseif isobject(v); k = 'object';
            else; k = class(v); end
            return;
        end
    end
end

function cs_write_metadata(outdir, meta)
    try
        txt = jsonencode(meta);
    catch
        txt = '{"schema":"cryostack.issm.results","version":1,"status":"encode-error","solutions":[]}';
    end
    fid = fopen(fullfile(outdir, 'metadata.json'), 'w');
    fwrite(fid, txt, 'char');
    fclose(fid);
end
"""


def build_postprocess() -> str:
    """The MATLAB script CryoStack appends after ``run('runme.m')``."""
    return _MATLAB
