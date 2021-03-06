# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Copyright 2015-2018 by Exopy Authors, see AUTHORS for more details.
#
# Distributed under the terms of the BSD license.
#
# The full license is in the file LICENCE, distributed with this software.
# -----------------------------------------------------------------------------
"""Plugin handling all measurement related functions.

"""
import logging
import os
from functools import partial

from atom.api import Typed, Str, List, ForwardTyped, Enum, Bool, Dict

from ..utils.plugin_tools import (HasPreferencesPlugin, ExtensionsCollector,
                                  make_extension_validator)
from .engines.api import Engine
from .monitors.api import Monitor
from .hooks.api import PreExecutionHook, PostExecutionHook
from .editors.api import Editor
from .processor import MeasurementProcessor
from .container import MeasurementContainer

logger = logging.getLogger(__name__)

ENGINES_POINT = 'exopy.measurement.engines'

MONITORS_POINT = 'exopy.measurement.monitors'

PRE_HOOK_POINT = 'exopy.measurement.pre-execution'

POST_HOOK_POINT = 'exopy.measurement.post-execution'

EDITORS_POINT = 'exopy.measurement.editors'


def _workspace():
    from .workspace.workspace import MeasurementSpace
    return MeasurementSpace


class TaskRuntimeContext():
    """A context manager used to give temporary access to a task runtime
    (e.g. driver) to a task.

    """
    def __init__(self, dependencies, task):
        self.dependencies = dependencies
        self.task = task

    def __enter__(self):
        res, msg, errors = self.dependencies.collect_task_runtimes(self.task)
        if res:
            self.task.root.run_time = self.dependencies.get_runtime_dependencies('main')
        else:
            logger.error(msg)
            logger.error(errors)
        return res, msg, errors

    def __exit__(self, type, value, traceback):
        self.task.root.run_time = {}
        self.dependencies.release_runtimes()
        self.dependencies.reset()


class MeasurementPlugin(HasPreferencesPlugin):
    """The measurement plugin is reponsible for managing all measurement
    related extensions and handling measurement execution.

    """
    #: Reference to the workspace if any.
    workspace = ForwardTyped(_workspace)

    #: Reference to the last directory from/in which a measurement was
    #: loaded/saved
    path = Str().tag(pref=True)

    #: Currently edited measurements.
    edited_measurements = Typed(MeasurementContainer, ())

    #: Currently enqueued measurements.
    enqueued_measurements = Typed(MeasurementContainer, ())

    #: Measurement processor responsible for measurement execution.
    processor = Typed(MeasurementProcessor)

    #: List of currently available engines.
    engines = List()

    #: Currently selected engine represented by its id.
    selected_engine = Str().tag(pref=True)

    #: What to do of the engine when there is no more measurement to perform.
    engine_policy = Enum('stop', 'sleep').tag(pref=True)

    #: List of currently available pre-execution hooks.
    pre_hooks = List()

    #: Default pre-execution hooks to use for new measurements.
    default_pre_hooks = List().tag(pref=True)

    #: List of currently available monitors.
    monitors = List()

    #: Default monitors to use for new measurements.
    default_monitors = List(default=['exopy.text_monitor']).tag(pref=True)

    #: Always show monitors on measurement startup.
    auto_show_monitors = Bool(True).tag(pref=True)

    #: List of currently available post-execution hooks.
    post_hooks = List()

    #: Default post-execution hooks to use for new measurements.
    default_post_hooks = List().tag(pref=True)

    #: List of currently available editors.
    editors = List()

    # TODO add the possibility to deactivate some editors.

    def start(self):
        """Start the plugin lifecycle by collecting all contributions.

        """
        core = self.workbench.get_plugin('enaml.workbench.core')
        core.invoke_command('exopy.app.errors.enter_error_gathering')

        checker = make_extension_validator(Engine, ('new',))
        self._engines = ExtensionsCollector(workbench=self.workbench,
                                            point=ENGINES_POINT,
                                            ext_class=Engine,
                                            validate_ext=checker)
        self._engines.start()

        checker = make_extension_validator(Editor, ('new', 'is_meant_for'))
        self._editors = ExtensionsCollector(workbench=self.workbench,
                                            point=EDITORS_POINT,
                                            ext_class=Editor,
                                            validate_ext=checker)
        self._editors.start()

        checker = make_extension_validator(PreExecutionHook, ('new',))
        self._pre_hooks = ExtensionsCollector(workbench=self.workbench,
                                              point=PRE_HOOK_POINT,
                                              ext_class=PreExecutionHook,
                                              validate_ext=checker)
        self._pre_hooks.start()

        checker = make_extension_validator(Monitor, ('new',))
        self._monitors = ExtensionsCollector(workbench=self.workbench,
                                             point=MONITORS_POINT,
                                             ext_class=Monitor,
                                             validate_ext=checker)
        self._monitors.start()

        checker = make_extension_validator(PostExecutionHook, ('new',))
        self._post_hooks = ExtensionsCollector(workbench=self.workbench,
                                               point=POST_HOOK_POINT,
                                               ext_class=PostExecutionHook,
                                               validate_ext=checker)
        self._post_hooks.start()

        for contrib in ('engines', 'editors', 'pre_hooks', 'monitors',
                        'post_hooks'):
            self._update_contribs(contrib, None)

        # This call is delayed till there to avoid loading the preferences
        # before discovering the contributions (would be an issue for engine).
        super(MeasurementPlugin, self).start()

        state = core.invoke_command('exopy.app.states.get',
                                    {'state_id': 'exopy.app.directory'})

        m_dir = os.path.join(state.app_directory, 'measurement')
        # Create measurement subfolder if it does not exist.
        if not os.path.isdir(m_dir):
            os.mkdir(m_dir)

        s_dir = os.path.join(m_dir, 'saved_measurements')
        # Create saved_measurements subfolder if it does not exist.
        if not os.path.isdir(s_dir):
            os.mkdir(s_dir)

        if not os.path.isdir(self.path):
            self.path = s_dir

        cmd = 'exopy.app.errors.signal'
        for contrib in ('pre_hooks', 'monitors', 'post_hooks'):
            default = getattr(self, 'default_'+contrib)
            avai_default = [d for d in default
                            if d in getattr(self, contrib)]
            if default != avai_default:
                msg = 'The following {} have not been found : {}'
                missing = set(default) - set(avai_default)
                core.invoke_command(cmd, dict(kind='error',
                                              message=msg.format(contrib,
                                                                 missing)))
                setattr(self, 'default_'+contrib, avai_default)

        for contrib in ('engines', 'editors', 'pre_hooks', 'monitors',
                        'post_hooks'):
            getattr(self, '_'+contrib).observe('contributions',
                                               partial(self._update_contribs,
                                                       contrib))

        core.invoke_command('exopy.app.errors.exit_error_gathering')

    def stop(self):
        """Stop the plugin and remove all observers.

        """
        # Close the monitors window.
        if self.processor.monitors_window:
            self.processor.monitors_window.hide()
            self.processor.monitors_window.close()
            self.processor.monitors_window = None

        for contrib in ('engines', 'editors', 'pre_hooks', 'monitors',
                        'post_hooks'):
            getattr(self, '_'+contrib).stop()

    def get_declarations(self, kind, ids):
        """Get the declarations of engines/editors/tools.

        If an id does not correspond to a known declarations it will be omitted
        from the return value, but no error will be raised. This is because the
        user can easily know which declarations exist by looking at the
        appropriate member of the plugin.

        Parameters
        ----------
        kind : {'engine', 'editor', 'pre-hook', 'monitor', 'post-hook'}
            Kind of object to create.

        ids : list
            Ids of the declarations to return.

        Returns
        -------
        declarations : dict
            Declarations stored in a dict by id.

        """
        kinds = ('engine', 'editor', 'pre-hook', 'monitor', 'post-hook')
        if kind not in kinds:
            msg = 'Expected kind must be one of {}, not {}.'
            raise ValueError(msg.format(kinds, kind))

        decls = getattr(self, '_'+kind.replace('-', '_')+'s').contributions
        return {k: v for k, v in decls.items() if k in ids}

    def create(self, kind, id, default=True):
        """Create a new instance of an engine/editor/tool.

        Parameters
        ----------
        kind : {'engine', 'editor', 'pre-hook', 'monitor', 'post-hook'}
            Kind of object to create.

        id : unicode
            Id of the object to create.

        default : bool, optional
            Whether to use default parameters or not when creating the object.

        Returns
        -------
        obj : BaseEngine|BaseMeasurementTool|BaseEditor
            New instance of the requested object.

        Raises
        ------
        ValueError :
            Raised if the provided kind or id in incorrect.

        """
        kinds = ('engine', 'editor', 'pre-hook', 'monitor', 'post-hook')
        if kind not in kinds:
            msg = 'Expected kind must be one of {}, not {}.'
            raise ValueError(msg.format(kinds, kind))

        decls = getattr(self, '_'+kind.replace('-', '_')+'s').contributions
        if id not in decls:
            raise ValueError('Unknown {} : {}'.format(kind, id))

        return decls[id].new(self.workbench, default)

    def find_next_measurement(self):
        """Find the next runnable measurement in the queue.

        Returns
        -------
        measurement : Measurement|None
            First valid measurement in the queue or None if there is no
            available measurement.

        """
        enqueued_measurements = self.enqueued_measurements.measurements
        i = 0
        measurement = None
        # Look for a measurement not being currently edited. (Can happen if the
        # user is editing the second measurement when the first measurement
        # ends).
        while i < len(enqueued_measurements):
            measurement = enqueued_measurements[i]
            if measurement.status != 'READY':
                i += 1
                measurement = None
            else:
                break

        return measurement

    def get_task_runtime(self, measurement, task):
        """Give temporary access to a task runtime

        Parameters
        ----------
        measurement: Measurement
            Measurement used to analyse and collect runtime
        task: Task:
            Task whose dependencies are going to be analysed
            and collected. Must be part of the measurement.

        Returns
        -------
        runtime: TaskRuntimeContext
            A context manager that acquires and releases the task
            dependencies.

        """
        return TaskRuntimeContext(measurement.dependencies, task)

    # =========================================================================
    # --- Private API ---------------------------------------------------------
    # =========================================================================

    #: Collector of engines.
    _engines = Typed(ExtensionsCollector)

    #: Collector of editors.
    _editors = Typed(ExtensionsCollector)

    #: Collector of pre-execution hooks.
    _pre_hooks = Typed(ExtensionsCollector)

    #: Collectorsof monitors.
    _monitors = Typed(ExtensionsCollector)

    #: Collector of post-execution hooks.
    _post_hooks = Typed(ExtensionsCollector)

    #: Workspace state infos kept to preserve layout.
    _workspace_state = Dict()

    def _post_setattr_selected_engine(self, old, new):
        """Ensures that the selected engine is informed when it is selected and
        deselected.

        This is always called before notifying the workspace of the change.

        """
        # Destroy old instance if any.
        self.processor.engine = None

        if old in self.engines:
            engine = self._engines.contributions[old]
            engine.react_to_unselection(self.workbench)
        if new and new in self.engines:
            engine = self._engines.contributions[new]
            engine.react_to_selection(self.workbench)

    def _update_contribs(self, name, change):
        """Update the list of available contributions (editors, engines, tools)
        when they change.

        """
        setattr(self, name, list(getattr(self, '_'+name).contributions))

    def _default_processor(self):
        """Create a MeasurementProcessor with a reference to the plugin.

        """
        return MeasurementProcessor(plugin=self)
