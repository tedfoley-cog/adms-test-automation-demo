"""Shared pytest configuration for the grid-control service tests."""

from __future__ import annotations


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "requirement(id): requirement or defect id the test verifies"
    )
