#!/usr/bin/env python
"""
core.py -- core fitting routines and user-facing functions

"""
import os

# Numeric 
import numpy as np 

# Least-squares fitting
from scipy.optimize import curve_fit 

# Dataframes
import pandas as pd 

# Plotting
import matplotlib.pyplot as plt 

# Package utilities
from .utils import (
    normalize_pmf,
    generate_support,
    rad_disp_histogram_2d,
    bounds_center,
    coarsen_histogram
)
from .models import (
    CDF_MODELS,
    PDF_MODELS,
    MODEL_PARS,
    MODEL_N_PARS,
    MODEL_PAR_BOUNDS,
    MODEL_GUESS
)
from .plot import (
    plot_jump_length_pmf,
    plot_jump_length_cdf 
)

def fit_model_cdf(tracks, model="one_state_brownian", n_frames=4, frame_interval=0.01,
    pixel_size_um=0.16, bounds=None, guess=None, plot=False, show_plot=True, save_png=None, 
    weight_timesteps=False, weight_short_disps=False, max_jump=5.0, **model_kwargs):
    """
    Fit a set of trajectories to a diffusion model, returning the fit parameters.

    args
    ----
        tracks              :   pandas.DataFrame, trajectories
        model               :   str, the diffusion model to fit
        n_frames            :   int, the maximum number of frame intervals to consider
                                when modeling displacements
        frame_interval      :   float, time between frames in seconds
        pixel_size_um       :   float, size of pixels in um
        bounds              :   2-tuple of 1D ndarray, the lower and upper bounds on 
                                the parameter estimates
        guess               :   1D ndarray or list of 1D ndarray, the guess vectors 
                                from which to seed the iterative fitting algorithm
        plot                :   bool, make a plot of the fits
        show_plot           :   bool, show the plot of the fits to user, if *show_plot*.
                                If False, then the plot is saved if *save_png* and otherwise
                                discarded.
        save_png            :   str, path to save the plot to. If *None*, the plot is 
                                not saved.
        weight_timesteps    :   bool, weight fits in each frame interval by the number
                                of displacements in that frame interval
        weight_short_disps  :   bool, weight fits 
        max_jump            :   float, the maximum displacement to consider in um
        model_kwargs        :   special arguments accepted by model function

    returns
    -------
        (
            dict, the final fit parameters;
            1D ndarray, the edges of each spatial bin in um;
            2D ndarray, the data CDF indexed by (time, jump length);
            2D ndarray, the data PMF indexed by (time, jump length);
            2D ndarray, the model CDF indexed by (time, jump length);
            2D ndarray, the model PMF indexed by (time, jump length)
        )

    """
    # Compile jump lengths
    bin_size = 0.001  # um 
    H, bin_edges = rad_disp_histogram_2d(tracks, n_frames=n_frames, bin_size=bin_size,
        pixel_size_um=pixel_size_um, max_jump=max_jump, first_only=True)
    n_bins = bin_edges.shape[0] - 1

    # Catch pathological input: if there are no recorded displacements, then return
    # NaNs for all parameter estimates
    if H[0,:].sum() == 0:
        return {k: np.nan for k in MODEL_PARS[model]}, None, None, None, None, None 

    # Reduce the number of timepoints, if there are no displacements in the later bins
    t = 0
    while (t<n_frames) and (H[t,:].sum() > 0):
        t += 1
    n_frames = t 
    H = H[:t, :]

    # Normalize to probability mass function
    pmfs = normalize_pmf(H)

    # Accumulate to get the approximate CDF 
    cdfs = np.cumsum(pmfs, axis=1)
    cdfs_ravel = cdfs.ravel()

    # Generate the set of (r, dt) tuples, the independent variables in the fitting problem
    rt_tuples = generate_support(bin_edges, n_frames, frame_interval)

    # Define the model functions to be fit
    kwargs = {
        "frame_interval": frame_interval,
        **model_kwargs 
    }
    model_cdf = lambda *args: CDF_MODELS[model](*args, **kwargs)
    model_pmf = lambda *args: PDF_MODELS[model](*args, **kwargs)

    # Initial parameter guess. If this is not specified, use the default
    if isinstance(guess, np.ndarray):
        assert len(guess) == MODEL_N_PARS[model], "Size of guess vector does not " \
            "match the number of fit parameters for model %s" % model 
        guess = [guess]
    elif isinstance(guess, list):
        assert all([len(g) == MODEL_N_PARS[model] for g in guess]), "Size of guess " \
            "vectors do not match the number of fit parameters for model %s" % model 
    else:
        guess = [MODEL_GUESS[model]]

    # Bounds for the fit parameters
    if bounds is None:
        bounds = MODEL_PAR_BOUNDS[model]

    # Check that the parameter guesses are valid for this choice of bounds
    def in_bounds(gu):
        return all([(g >= bounds[0][i]) and (g <= bounds[1][i]) for i, g in enumerate(gu)])
    guess = [gu for gu in guess if in_bounds(gu)]

    # If no guesses remain, choose the center of the bounds
    if len(guess) == 0:
        guess = [bounds_center(bounds)]

    # If any of the parameters are completely constrained, make sure that the upper
    # bound is strictly greater than the lower bound to avoid scipy.optimize errors
    for j in range(len(bounds[0])):
        if bounds[1][j] - bounds[0][j] == 0.0:
            bounds[1][j] += 1.0e-10

    # If weighting by the number of observations in each frame interval, set the 
    # variance on the CDFs in each bin to be inversely proportional to the number of 
    # observations (jumps) in the corresponding frame interval
    if weight_timesteps:
        sigma = np.zeros(rt_tuples.shape[0], dtype=np.float64)
        frame_times = np.unique(rt_tuples[:,1])
        for t, frame_time in enumerate(frame_times):
            sigma[rt_tuples[:,1] == frame_time] = np.sqrt(1.0 / H[t,:].sum())
        sigma /= sigma.max() 
    else:
        sigma = None 

    # Optionally, bias the fit toward the shorter end of the jump length distribution
    if weight_short_disps:
        if sigma is None:
            sigma = np.ones(rt_tuples.shape[0], dtype=np.float64)
            sigma[rt_tuples[:,0]<=0.5] = 0.25
        else:
            sigma[rt_tuples[:,0]<=0.5] = sigma[rt_tuples[:,0]<=0.5] * 0.25

    # For each initial parameter guess, seed a LS fit and the guess with the lowest
    # sum squared deviation at the end
    ss = np.inf 
    result = None 
    for i, g in enumerate(guess):
        try:
            popt, pcov = curve_fit(model_cdf, rt_tuples, cdfs_ravel,
                bounds=bounds, p0=g, sigma=sigma)
            dev = ((cdfs_ravel - model_cdf(rt_tuples, *popt))**2).sum()
            if dev < ss:
                result = popt 
                ss = dev 
        except RuntimeError:   # does not converge
            continue

    # If result is still None, terminate with NaNs as the fit parameters
    if result is None:
        print("Optimal fit parameters not found")
        fit_pars = {s: np.nan for s in MODEL_PARS[model]}
        return fit_pars, bin_edges, cdfs, pmfs, np.zeros(cdfs.shape), np.zeros(pmfs.shape)

    # Evaluate the model CDF/PMF at the final parameter estimate. The PMF is
    # approximated by evaluating the PDF at the center of each spatial bin, then 
    # multiplying by the bin size 
    model_cdf_eval = model_cdf(rt_tuples, *popt).reshape(H.shape)
    rt_tuples[:,0] -= bin_size * 0.5
    model_pmf_eval = model_pmf(rt_tuples, *popt).reshape(H.shape) * bin_size 

    # Show the result graphically, if desired
    if plot:

        # Coarsen the histogram for the purpose of visualization
        pmf_coarse, bin_edges_coarse = coarsen_histogram(pmfs, bin_edges, 20)

        # If the user wants to the save the plot, create names for the output PMF and CDF
        # plots
        if not save_png is None:
            out_png_pmf = "{}_pmf.png".format(os.path.splitext(save_png)[0])
            out_png_cdf = "{}_cdf.png".format(os.path.splitext(save_png)[0])
        else:
            out_png_pmf = out_png_cdf = None 

        # Plot the PMF
        fig, axes = plot_jump_length_pmf(bin_edges_coarse, pmf_coarse, model_pmfs=model_pmf_eval,
            model_bin_edges=bin_edges, frame_interval=frame_interval, max_jump=2.0,
            cmap="gray", figsize_mod=1.0, out_png=out_png_pmf)

        # Plot the CDF
        fig, axes = plot_jump_length_cdf(bin_edges, cdfs, model_cdfs=model_cdf_eval,
            model_bin_edges=None, frame_interval=frame_interval, max_jump=5.0, cmap="gray",
            figsize_mod=1.0, out_png=out_png_cdf, fontsize=8)

        # Show to user
        if show_plot:
            plt.show()
        plt.close("all")

    # Format output
    fit_pars = {s: v for s, v in zip(MODEL_PARS[model], popt)}
    return fit_pars, bin_edges, cdfs, pmfs, model_cdf_eval, model_pmf_eval 


