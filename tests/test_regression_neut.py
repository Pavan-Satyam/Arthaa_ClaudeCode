"""`regression_neut` correctness (cross-sectional residual orthogonal to the exposure)."""

import numpy as np
import pandas as pd

from arthaai.factors.base import regression_neut


def test_residual_is_not_all_zero():
    x = pd.DataFrame({"A": [1.0], "B": [2.0], "C": [3.0]})
    y = pd.DataFrame({"A": [1.0], "B": [2.0], "C": [4.0]})
    resid = regression_neut(y, x)
    assert not np.allclose(resid.to_numpy(dtype=float), 0.0)


def test_residual_orthogonal_to_exposure_and_zero_mean_per_row():
    x = pd.DataFrame({"A": [1.0, 5.0], "B": [2.0, 3.0], "C": [3.0, 1.0]})
    y = pd.DataFrame({"A": [1.0, 9.0], "B": [2.0, 4.0], "C": [4.0, 2.0]})
    resid = regression_neut(y, x)
    for i in range(len(x)):
        assert abs((x.iloc[i] * resid.iloc[i]).sum()) < 1e-9  # orthogonal to x
        assert abs(resid.iloc[i].sum()) < 1e-9  # orthogonal to the constant


def test_perfect_linear_relationship_is_fully_removed():
    x = pd.DataFrame({"A": [1.0], "B": [2.0], "C": [3.0]})
    y = 2.0 * x - 1.0  # exactly linear in x
    resid = regression_neut(y, x)
    assert np.allclose(resid.to_numpy(dtype=float), 0.0, atol=1e-9)


def test_zero_variance_exposure_yields_nan():
    x = pd.DataFrame({"A": [2.0], "B": [2.0], "C": [2.0]})
    y = pd.DataFrame({"A": [1.0], "B": [2.0], "C": [3.0]})
    resid = regression_neut(y, x)
    assert np.isnan(resid.to_numpy(dtype=float)).all()
