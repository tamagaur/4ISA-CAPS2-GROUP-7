"""
tests/test_analytics_config.py — Tests for analytics.config.load_analytics_params.

Story 55: service level (Z-score) and LP weights must come from
config/analytics_params.yaml, not a hardcoded formula constant.
"""

from pathlib import Path

import pytest
import yaml

from analytics.config import MissingConfigError, load_analytics_params


def _write_params(tmp_path: Path, contents: dict) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "analytics_params.yaml").write_text(yaml.dump(contents), encoding="utf-8")
    return config_dir


def test_loads_real_config_file():
    """The real config/analytics_params.yaml (repo default) parses cleanly
    and matches the values previously hardcoded in analytics.optimization.lp."""
    load_analytics_params.cache_clear()
    params = load_analytics_params()
    assert params.z_score == pytest.approx(1.28)
    assert (params.w1, params.w2, params.w3) == pytest.approx((0.45, 0.35, 0.20))


def test_missing_file_raises_clear_error(tmp_path):
    load_analytics_params.cache_clear()
    with pytest.raises(MissingConfigError, match="not found"):
        load_analytics_params(config_dir=tmp_path / "config")


def test_missing_key_raises_clear_error(tmp_path):
    config_dir = _write_params(tmp_path, {"service_level": {"z_score": 1.28}})
    load_analytics_params.cache_clear()
    with pytest.raises(MissingConfigError, match="missing a required key"):
        load_analytics_params(config_dir=config_dir)


def test_weights_not_summing_to_one_raises(tmp_path):
    config_dir = _write_params(
        tmp_path,
        {
            "service_level": {"z_score": 1.28},
            "lp_weights": {"w1": 0.5, "w2": 0.5, "w3": 0.5},
        },
    )
    load_analytics_params.cache_clear()
    with pytest.raises(MissingConfigError, match="must sum to 1.00"):
        load_analytics_params(config_dir=config_dir)


def test_custom_service_level_is_honored(tmp_path):
    """A different Z-score (e.g. 95% service level) actually changes the
    loaded value — proving it's configurable, not just re-reading 1.28."""
    config_dir = _write_params(
        tmp_path,
        {
            "service_level": {"z_score": 1.645},
            "lp_weights": {"w1": 0.45, "w2": 0.35, "w3": 0.20},
        },
    )
    load_analytics_params.cache_clear()
    params = load_analytics_params(config_dir=config_dir)
    assert params.z_score == pytest.approx(1.645)

    load_analytics_params.cache_clear()
