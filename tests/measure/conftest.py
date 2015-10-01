# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Copyright 2015 by Ecpy Authors, see AUTHORS for more details.
#
# Distributed under the terms of the BSD license.
#
# The full license is in the file LICENCE, distributed with this software.
# -----------------------------------------------------------------------------
"""Fixture for testing the measure plugin.

"""
from __future__ import (division, unicode_literals, print_function,
                        absolute_import)

import pytest
from pprint import pformat

import enaml
from enaml.workbench.api import Workbench

with enaml.imports():
    from enaml.workbench.core.core_manifest import CoreManifest

    from ecpy.app.app_manifest import AppManifest
    from ecpy.app.preferences.manifest import PreferencesManifest
    from ecpy.app.dependencies.manifest import DependenciesManifest
    from ecpy.app.errors.manifest import ErrorsManifest
    from ecpy.app.errors.plugin import ErrorsPlugin
    from ecpy.measure.manifest import MeasureManifest


@pytest.fixture
def measure_workbench(monkeypatch, app_dir):
    """Setup the workbench in such a way that the task manager can be tested.

    """
    def exit_err(self):
        if self._delayed:
            raise Exception('Unexpected exceptions occured :\n' +
                            pformat(self._delayed))

    monkeypatch.setattr(ErrorsPlugin, 'exit_error_gathering', exit_err)
    workbench = Workbench()
    workbench.register(CoreManifest())
    workbench.register(AppManifest())
    workbench.register(PreferencesManifest())
    workbench.register(ErrorsManifest())
    workbench.register(DependenciesManifest())
    workbench.register(MeasureManifest())

    return workbench
