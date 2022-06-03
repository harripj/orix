# -*- coding: utf-8 -*-
# Copyright 2018-2022 the orix developers
#
# This file is part of orix.
#
# orix is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# orix is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with orix.  If not, see <http://www.gnu.org/licenses/>.

from typing import Optional, Tuple, Union

import numpy as np
from scipy.ndimage import gaussian_filter

from orix.projections.stereographic import StereographicProjection
from orix.quaternion import Symmetry
from orix.vector import Vector3d


def pole_density_function(
    *args: Union[np.ndarray, Vector3d],
    resolution: float = 1,
    sigma: float = 5,
    hemisphere: Optional[str] = None,
    symmetry: Optional[Symmetry] = None,
    log: bool = False,
    mrd: bool = True
) -> Tuple[np.ma.MaskedArray, Tuple[np.ndarray, np.ndarray]]:
    """Compute the Pole Density Function (PDF) of vectors in the
    stereographic projection.
    If `symmetry` is defined then the PDF is folded back into the point
    group fundamental sector and accumulated.
    Parameters
    ----------
    args
        Vector(s), or azimuth and polar angles of the vectors, the
        latter passed as two separate arguments.
    resolution
        The angular resolution of the sampling grid in degrees.
        Default value is 1.
    sigma
        The angular resolution of the applied broadening in degrees.
        Default value is 5.
    hemisphere
        Which hemisphere(s) to plot the vectors on, defaults to
        None, which means "upper". Options are "upper" and "lower".
    symmetry
        If provided the PDF is calculated within the fundamental sector
        of the point group symmetry, otherwise the PDF is calculated
        on `hemisphere`. Default is None.
    log
        If True the log(PDF) is calculated. Default is True.
    mrd
        If True the returned PDF is in units of Multiples of Random
        Distribution (MRD), otherwise the units are bin counts. Default
        is True.
    Returns
    -------
    hist
        The computed histogram, shape is (N, M).
    x, y
        Tuple of coordinate grids for the bin edges of `hist`. The units
        of `x` and `y` are cartesian coordinates on the stereographic
        projection plane and the shape of both `x` and `y` is
        (N + 1, M + 1).
    See Also
    --------
    orix.plot.InversePoleFigurePlot.pole_density_function
    orix.plot.StereographicPlot.pole_density_function
    orix.vector.Vector3d.pole_density_function
    """

    from orix.sampling.S2_sampling import _sample_S2_equal_area_coordinates

    if hemisphere is None:
        hemisphere = "upper"
    hemisphere = hemisphere.lower()

    poles = {"upper": -1, "lower": 1}
    sp = StereographicProjection(poles[hemisphere])

    if len(args) == 1:
        v = args[0]
        if not isinstance(v, Vector3d):
            raise TypeError(
                "If one argument is passed it must be an instance of "
                + "`orix.vector.Vector3d`."
            )
    elif len(args) == 2:
        # azimuth and polar angles
        v = Vector3d.from_polar(*args)
    else:
        raise ValueError(
            "Accepts only one (Vector3d) or two (azimuth, polar) input arguments."
        )

    if symmetry is not None:
        v = v.in_fundamental_sector(symmetry)

    azimuth, polar, _ = v.to_polar()
    # np.histogram2d expects 1d arrays
    azimuth, polar = np.ravel(azimuth), np.ravel(polar)
    if not azimuth.size:
        raise ValueError("Azimuth and polar have 0 size.")

    # Generate angular mesh on S2.
    # To help with aliasing after reprojection into FS in IPF case,
    # the initial sampling is performed at half the angular resolution
    azimuth_coords, polar_coords = _sample_S2_equal_area_coordinates(
        resolution if symmetry is None else resolution / 2,
        hemisphere=hemisphere,
        azimuth_endpoint=True,
    )
    azimuth_grid, polar_grid = np.meshgrid(azimuth_coords, polar_coords, indexing="ij")
    # generate histogram in angular space
    hist, *_ = np.histogram2d(
        azimuth, polar, bins=(azimuth_coords, polar_coords), density=False
    )

    # "wrap" along azimuthal axis, "reflect" along polar axis
    mode = ("wrap", "reflect")
    # apply broadening in angular space
    hist = gaussian_filter(hist, sigma / resolution, mode=mode)

    # in the case of IPF, accumulate all values outside FS back into
    # correct bin in FS
    if symmetry is not None:
        # compute histogram bin centers in azimuth and polar coords
        azimuth_center_grid, polar_center_grid = np.meshgrid(
            azimuth_coords[:-1] + np.ediff1d(azimuth_coords) / 2,
            polar_coords[:-1] + np.ediff1d(polar_coords) / 2,
            indexing="ij",
        )
        v_center_grid = Vector3d.from_polar(
            azimuth=azimuth_center_grid, polar=polar_center_grid
        ).unit
        # fold back in into FS
        v_center_grid_fs = v_center_grid.in_fundamental_sector(symmetry)
        azimuth_center_fs, polar_center_fs, _ = v_center_grid_fs.to_polar()
        azimuth_center_fs = azimuth_center_fs.ravel()
        polar_center_fs = polar_center_fs.ravel()

        # generate coorinates with proper resolution. When `symmetry`
        # was defined, the initial grid was calculated with resolution
        # `resolution / 2`
        azimuth_coords_res2, polar_coords_res2 = _sample_S2_equal_area_coordinates(
            resolution,
            hemisphere=hemisphere,
            azimuth_endpoint=True,
        )
        azimuth_res2_grid, polar_res2_grid = np.meshgrid(
            azimuth_coords_res2, polar_coords_res2, indexing="ij"
        )
        v_res2_grid = Vector3d.from_polar(
            azimuth=azimuth_res2_grid, polar=polar_res2_grid
        )

        # calculate histogram bin for vectors folded back into FS
        i = np.digitize(azimuth_center_fs, azimuth_coords_res2[1:-1])
        j = np.digitize(polar_center_fs, polar_coords_res2[1:-1])
        # recompute histogram
        temp = np.zeros((azimuth_coords_res2.size - 1, polar_coords_res2.size - 1))
        # add hist data to new histogram by buffering
        np.add.at(temp, (i, j), hist.ravel())

        # get new histogram bins centers to compute histogram mask
        azimuth_center_res2_grid, polar_center_res2_grid = np.meshgrid(
            azimuth_coords_res2[:-1] + np.ediff1d(azimuth_coords_res2) / 2,
            polar_coords_res2[:-1] + np.ediff1d(polar_coords_res2) / 2,
            indexing="ij",
        )
        v_center_res2_grid = Vector3d.from_polar(
            azimuth=azimuth_center_res2_grid, polar=polar_center_res2_grid
        ).unit

        # compute histogram data array as masked array
        hist = np.ma.array(
            temp, mask=~(v_center_res2_grid <= symmetry.fundamental_sector)
        )
        # calculate bin vertices
        x, y = sp.vector2xy(v_res2_grid)
        x, y = x.reshape(v_res2_grid.shape), y.reshape(v_res2_grid.shape)
    else:
        # all points valid in stereographic projection
        hist = np.ma.array(hist, mask=np.zeros_like(hist, dtype=bool))
        # calculate bin vertices
        v_grid = Vector3d.from_polar(azimuth=azimuth_grid, polar=polar_grid).unit
        x, y = sp.vector2xy(v_grid)
        x, y = x.reshape(v_grid.shape), y.reshape(v_grid.shape)

    # Normalize by the average number of counts per cell on the
    # unit sphere to calculate in terms of Multiples of Random
    # Distribution (MRD). See :cite:`rohrer2004distribution`.
    # as `hist` is a masked array, only valid (unmasked) values are
    # used in this computation
    if mrd:
        hist = hist / hist.mean()

    if log:
        # +1 to avoid taking the log of 0
        hist = np.log(hist + 1)

    return hist, (x, y)
