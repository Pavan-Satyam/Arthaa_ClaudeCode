"""Registry output validation rejects degenerate factors (constant/zero/inf/NaN)."""

import numpy as np
import pandas as pd
import pytest

from arthaai.factors.registry import Registry, RegistryError

_PANEL = {"close": pd.DataFrame({"A": [1.0, 2.0, 3.0], "B": [4.0, 5.0, 6.0]})}


def test_accepts_varying_output():
    out = pd.DataFrame({"A": [0.1, -0.2, 0.3], "B": [1.0, 0.5, -1.0]})
    assert Registry._validate_output("ok", out, _PANEL).shape == (3, 2)


def test_rejects_all_zero_output():
    out = pd.DataFrame({"A": [0.0, 0.0, 0.0], "B": [0.0, 0.0, 0.0]})
    with pytest.raises(RegistryError, match="constant"):
        Registry._validate_output("zero", out, _PANEL)


def test_rejects_constant_nonzero_output():
    out = pd.DataFrame({"A": [2.0, 2.0, 2.0], "B": [2.0, 2.0, 2.0]})
    with pytest.raises(RegistryError, match="constant"):
        Registry._validate_output("const", out, _PANEL)


def test_rejects_shape_mismatch():
    out = pd.DataFrame({"A": [1.0, 2.0]})
    with pytest.raises(RegistryError, match="shape"):
        Registry._validate_output("shape", out, _PANEL)


def test_rejects_inf():
    out = pd.DataFrame({"A": [1.0, np.inf, 2.0], "B": [1.0, 2.0, 3.0]})
    with pytest.raises(RegistryError, match="inf"):
        Registry._validate_output("inf", out, _PANEL)
