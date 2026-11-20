"""Readable coordinate ticks for spatial result maps; values stay unchanged."""


def format_map_axes(ax):
    from matplotlib.ticker import MaxNLocator, ScalarFormatter
    for axis in (ax.xaxis, ax.yaxis):
        formatter = ScalarFormatter(useMathText=True, useOffset=False)
        formatter.set_scientific(True)
        formatter.set_powerlimits((-3, 4))
        axis.set_major_formatter(formatter)
        axis.set_major_locator(MaxNLocator(nbins=5, min_n_ticks=3))
