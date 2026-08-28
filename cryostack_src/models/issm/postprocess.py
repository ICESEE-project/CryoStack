def build_postprocess() -> str:
    return r"""
disp('[ICESEE-GUI] Running ISSM postprocess...');

if ~exist('ICESEE_RUN_DIR', 'var') || isempty(ICESEE_RUN_DIR)
    ICESEE_RUN_DIR = pwd;
end

figdir   = fullfile(ICESEE_RUN_DIR, 'outputs', 'figures');
modeldir = fullfile(ICESEE_RUN_DIR, 'outputs', 'model');

if ~exist(figdir, 'dir'); mkdir(figdir); end
if ~exist(modeldir, 'dir'); mkdir(modeldir); end

if ~exist('md', 'var')
    disp('[ICESEE-GUI][WARN] Variable md does not exist. Nothing to postprocess.');
    return;
end

try
    save(fullfile(modeldir, 'md_final.mat'), 'md', '-v7.3');
    disp(['[ICESEE-GUI] Saved model: ' fullfile(modeldir, 'md_final.mat')]);
catch ME
    disp(['[ICESEE-GUI][WARN] Could not save md_final.mat: ' ME.message]);
end

try
    results = md.results;
catch ME
    disp(['[ICESEE-GUI][WARN] Could not access md.results: ' ME.message]);
    return;
end

if isempty(results)
    disp('[ICESEE-GUI][WARN] md.results is empty. Nothing to plot.');
    return;
end

try
    if isfield(results, 'StressbalanceSolution')
        sol = results.StressbalanceSolution;

        if isfield(sol, 'Vel')
            f = figure('Visible', 'off');
            plotmodel(md, 'data', sol.Vel);
            title('Stressbalance velocity');
            saveas(f, fullfile(figdir, 'stressbalance_velocity.png'));
            close(f);
            disp('[ICESEE-GUI] Saved stressbalance_velocity.png');
        end

        if isfield(sol, 'Pressure')
            f = figure('Visible', 'off');
            plotmodel(md, 'data', sol.Pressure);
            title('Stressbalance pressure');
            saveas(f, fullfile(figdir, 'stressbalance_pressure.png'));
            close(f);
            disp('[ICESEE-GUI] Saved stressbalance_pressure.png');
        end

        return;
    end

    if isfield(results, 'TransientSolution')
        sol = results.TransientSolution;
        last = sol(numel(sol));

        if isfield(last, 'Vel')
            f = figure('Visible', 'off');
            plotmodel(md, 'data', last.Vel);
            title('Final transient velocity');
            saveas(f, fullfile(figdir, 'transient_final_velocity.png'));
            close(f);
            disp('[ICESEE-GUI] Saved transient_final_velocity.png');
        end

        if isfield(last, 'Thickness')
            f = figure('Visible', 'off');
            plotmodel(md, 'data', last.Thickness);
            title('Final transient thickness');
            saveas(f, fullfile(figdir, 'transient_final_thickness.png'));
            close(f);
            disp('[ICESEE-GUI] Saved transient_final_thickness.png');
        end

        if isfield(last, 'Surface')
            f = figure('Visible', 'off');
            plotmodel(md, 'data', last.Surface);
            title('Final transient surface');
            saveas(f, fullfile(figdir, 'transient_final_surface.png'));
            close(f);
            disp('[ICESEE-GUI] Saved transient_final_surface.png');
        end

        return;
    end

    if isfield(results, 'ThermalSolution')
        sol = results.ThermalSolution;

        if isfield(sol, 'Temperature')
            f = figure('Visible', 'off');
            plotmodel(md, 'data', sol.Temperature);
            title('Thermal temperature');
            saveas(f, fullfile(figdir, 'thermal_temperature.png'));
            close(f);
            disp('[ICESEE-GUI] Saved thermal_temperature.png');
        end

        return;
    end

    if isfield(results, 'MasstransportSolution')
        sol = results.MasstransportSolution;

        if isfield(sol, 'Thickness')
            f = figure('Visible', 'off');
            plotmodel(md, 'data', sol.Thickness);
            title('Mass transport thickness');
            saveas(f, fullfile(figdir, 'masstransport_thickness.png'));
            close(f);
            disp('[ICESEE-GUI] Saved masstransport_thickness.png');
        end

        return;
    end

    disp('[ICESEE-GUI][WARN] Solver type not recognized.');
    disp(fieldnames(md.results));

catch ME
    disp(['[ICESEE-GUI][ERROR] Postprocess failed: ' ME.message]);
end
"""
