#!/usr/bin/env python
"""
hilosim.py -- simulated regular and anomalous diffusion processes in 
stroboscopic highly inclined laminated optical sheet (HiLo) geometries.

Generally, this means that a diffusion process in 3D space is only
observable (1) at regular frame intervals and (2) across a finite range
of positions in *z*. Additionally, the 3D trajectory is projected onto
the 2D plane of the camera.

This module has methods to simulate trajectories acquired in HiLo 
geometry.

"""
import os
import numpy as np 
import pandas as pd 

from strobemodels.simulate.simutils import tracks_to_dataframe
from strobemodels.simulate.fbm import FractionalBrownianMotion3D
from strobemodels.simulate.levy import LevyFlight3D

# Available diffusion simulators
DIFFUSION_MODELS = {
    "brownian": FractionalBrownianMotion3D,
    "fbm": FractionalBrownianMotion3D,
    "levy": LevyFlight3D
}

def strobe_infinite_plane(model_obj, n_tracks, dz=0.7, loc_error=0.0, exclude_outside=True, 
    return_dataframe=True):
    """
    Simulate 3D trajectories with photoactivation in a HiLo geometry. Molecules
    are photoactivated with uniform probability in the axial column. Their displacements
    in the XY plane are observed, and the molecules are lost as soon as their z position
    lies outside of the interval (-dz/2, dz/2) during one frame interval.

    args
    ----
        model_obj       :   either a FractionalBrownianMotion3D or LevyFlight3D object,
                            the simulator
        n_tracks        :   int, the number of trajectories to simulate
        dz              :   float, thickness of the observation slice in um
        loc_error       :   float, standard deviation of normally distributed 1D
                            localization error in um
        exclude_outside :   bool, exclude localizations that lie outside of the detectable
                            z interval (-dz/2, dz/2). If False, the whole trajectories
                            are returned.
        return_dataframe:   bool, format results as a pandas.DataFrame rather than a 
                            numpy.ndarray

    returns
    -------
        if return_dataframe:
            pandas.DataFrame with columns ["trajectory", "frame", "z0", "y0", "x0"]
        else:
            3D np.ndarray with shape (n_tracks, track_len, 3), the 3D positions

    """
    # Simulate some 3D trajectories
    tracks = model_obj(n_tracks)

    # Add a random starting position in z
    tracks[:,:,0] = tracks[:,:,0] + np.random.uniform(-hz, hz, size=n_tracks)

    # Exclude molecules outside of the slice from observation by setting their
    # values to NaN
    if exclude_outside:
        outside = np.zeros(n_tracks, dtype=np.bool)
        for t in range(track_len+1):

            # If a molecule is observed outside the slice once, it is lost for 
            # all subsequent frame intervals
            outside = np.logical_or(outside, np.abs(tracks[t,:,0])>hz)
            for d in range(3):
                tracks[t,:,d][outside] = np.nan 

    # Add localization error, if desired
    if loc_error != 0.0:
        tracks = tracks + np.random.normal(scale=loc_error, size=tracks.shape)

    # Format as a pandas.DataFrame, if desired
    if return_dataframe:
        return tracks_to_dataframe(tracks, kill_nan=True)
    else:
        return tracks 

def strobe_one_state_infinite_plane(model, n_tracks, track_len=10, dz=0.7, loc_error=0.0,
    exclude_outside=True, return_dataframe=False, **model_kwargs):
    """
    Simulate a single diffusing state in a HiLo geometry.

    args
    ----
        model           :   str, one of the models in DIFFUSION_MODELS
        n_tracks        :   int, the number of trajectories to simulate
        dz              :   float, the thickness of the observation slice
        loc_error       :   float, localization error 
        exclude_outside :   bool, remove positions that fall outside the focal 
                            depth 
        return_dataframe:   bool, format results as a pandas.DataFrame
        model_kwargs    :   for generating the diffusion model 

    returns
    -------
        if return_dataframe:
            pandas.DataFrame with columns ["trajectory", "frame", "z0", "y0", "x0"]
        else:
            3D np.ndarray with shape (n_tracks, track_len, 3), the 3D positions

    """
    model_obj = DIFFUSION_MODELS[model](dt=dt, track_len=track_len, **model_kwargs)
    return strobe_infinite_plane(model_obj, n_tracks, dz=dz, loc_error=loc_error,
        exclude_outside=exclude_outside, return_dataframe=return_dataframe)
    
def strobe_two_state_infinite_plane(model_0, model_1, n_tracks, f0=0.0, track_len=10,
    dz=0.7, loc_error=0.0, exclude_outside=True, return_dataframe=False, 
    model_0_kwargs={}, model_1_kwargs={}):
    """
    Simulate two diffusing states in a HiLo geometry.

    args
    ----
        model_0         :   str, one of the models in DIFFUSION_MODELS
        model_1         :   str, one of the models in DIFFUSION_MODELS
        n_tracks        :   int, the number of trajectories to simulate
        f0              :   float, the number of trajectories in the first
                            diffusing state
        track_len       :   int, the trajectory length 
        dz              :   float, thickness of the HiLo focal depth in um
        loc_error       :   float, 1D normal localization error in um
        exclude_outside :   bool, remove positions that fall outside the 
                            focal depth 
        return_dataframe:   bool, format result as a pandas.DataFrame
        model_0_kwargs  :   dict, model parameters for state 0
        model_1_kwargs  :   dict, model parameters for state 1

    returns
    -------
        if return_dataframe:
            pandas.DataFrame with columns ["trajectory", "frame", "z0", "y0", "x0"]
        else:
            3D np.ndarray with shape (n_tracks, track_len, 3), the 3D positions

    """
    # Number of trajectories in each state
    N0 = np.random.binomial(n_tracks, f0)
    N1 = n_tracks - N0 

    # Generate simulators for each state
    model_obj_0 = DIFFUSION_MODELS[model_0](dt=dt, track_len=track_len, **model_0_kwargs)
    model_obj_1 = DIFFUSION_MODELS[model_1](dt=dt, track_len=track_len, **model_1_kwargs)

    # Run the simulations
    tracks_0 = strobe_infinite_plane(model_obj_0, N0, dz=dz, loc_error=loc_error,
        exclude_outside=exclude_outside, return_dataframe=return_dataframe)
    tracks_1 = strobe_infinite_plane(model_obj_1, N1, dz=dz, loc_error=loc_error,
        exclude_outside=exclude_outside, return_dataframe=return_dataframe)

    # Concatenate trajectories from both states
    if isinstance(tracks_0, pd.DataFrame):
        tracks = pd.concat([tracks_0, tracks_1], axis=0, sort=True)
    else:
        tracks = np.concatenate([tracks_0, tracks_1], axis=0)

    return tracks 







