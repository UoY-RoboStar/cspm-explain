"""Python 3 ctypes wrapper around fdr_bridge.so.

Usage
-----
    from fdr_py import FdrSession

    with FdrSession("examples/Zxoyx.csp") as sess:
        for a in sess.assertions():
            a.execute()
            if not a.passed():
                for ce in a.counterexamples():
                    if ce.is_property():
                        beh = ce.property_behaviour()
                        print("trace len:", beh.trace_len())
                        print("machine name:", sess.machine_name_for(beh))

                        dc = ce.debug_context()
                        dc.initialise()
                        for root in dc.root_behaviours():
                            # reveal_taus_in_trace replaces τ with actual hidden event
                            revealed = dc.reveal_taus_in_trace(root)
                            for i, ev in enumerate(revealed):
                                print(f"  step {i}: {sess.uncompile_event(ev)!r}")
                            for child in dc.children(root):
                                print("  child machine:", sess.machine_name_for(child))
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path

# Resolve bridge .so relative to this file.
_SO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fdr_bridge.so")
_lib = ctypes.CDLL(_SO)

# ---------------------------------------------------------------------------
# Prototype declarations
# ---------------------------------------------------------------------------

_lib.fdr_library_init.restype  = None
_lib.fdr_library_exit.restype  = None
_lib.fdr_has_valid_license.restype = ctypes.c_int
_lib.fdr_version.restype       = None
_lib.fdr_version.argtypes      = [ctypes.c_char_p, ctypes.c_size_t]

_lib.fdr_set_option.restype    = None
_lib.fdr_set_option.argtypes   = [ctypes.c_char_p, ctypes.c_char_p]
_lib.fdr_get_option.restype    = None
_lib.fdr_get_option.argtypes   = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t]

_lib.fdr_session_new.restype   = ctypes.c_void_p
_lib.fdr_session_free.restype  = None
_lib.fdr_session_free.argtypes = [ctypes.c_void_p]
_lib.fdr_session_load_file.restype  = ctypes.c_int
_lib.fdr_session_load_file.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t]
_lib.fdr_session_assertion_count.restype  = ctypes.c_int
_lib.fdr_session_assertion_count.argtypes = [ctypes.c_void_p]
_lib.fdr_session_assertion.restype  = ctypes.c_void_p
_lib.fdr_session_assertion.argtypes = [ctypes.c_void_p, ctypes.c_int]
_lib.fdr_session_uncompile_event.restype  = None
_lib.fdr_session_uncompile_event.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_char_p, ctypes.c_size_t]
_lib.fdr_session_machine_name_for_behaviour.restype  = None
_lib.fdr_session_machine_name_for_behaviour.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]

_lib.fdr_assertion_free.restype     = None
_lib.fdr_assertion_free.argtypes    = [ctypes.c_void_p]
_lib.fdr_assertion_execute.restype  = ctypes.c_int
_lib.fdr_assertion_execute.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
_lib.fdr_assertion_passed.restype   = ctypes.c_int
_lib.fdr_assertion_passed.argtypes  = [ctypes.c_void_p]
_lib.fdr_assertion_to_string.restype  = None
_lib.fdr_assertion_to_string.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
_lib.fdr_assertion_counterexample_count.restype  = ctypes.c_int
_lib.fdr_assertion_counterexample_count.argtypes = [ctypes.c_void_p]
_lib.fdr_assertion_counterexample.restype  = ctypes.c_void_p
_lib.fdr_assertion_counterexample.argtypes = [ctypes.c_void_p, ctypes.c_int]

_lib.fdr_ce_free.restype      = None
_lib.fdr_ce_free.argtypes     = [ctypes.c_void_p]
_lib.fdr_ce_is_property.restype  = ctypes.c_int
_lib.fdr_ce_is_property.argtypes = [ctypes.c_void_p]
_lib.fdr_ce_property_behaviour.restype  = ctypes.c_void_p
_lib.fdr_ce_property_behaviour.argtypes = [ctypes.c_void_p]

_lib.fdr_behaviour_free.restype        = None
_lib.fdr_behaviour_free.argtypes       = [ctypes.c_void_p]
_lib.fdr_behaviour_trace_len.restype   = ctypes.c_int
_lib.fdr_behaviour_trace_len.argtypes  = [ctypes.c_void_p]
_lib.fdr_behaviour_trace_event.restype  = ctypes.c_uint
_lib.fdr_behaviour_trace_event.argtypes = [ctypes.c_void_p, ctypes.c_int]

_lib.fdr_debug_context_new.restype   = ctypes.c_void_p
_lib.fdr_debug_context_new.argtypes  = [ctypes.c_void_p, ctypes.c_int]
_lib.fdr_debug_context_free.restype  = None
_lib.fdr_debug_context_free.argtypes = [ctypes.c_void_p]
_lib.fdr_debug_context_initialise.restype  = ctypes.c_int
_lib.fdr_debug_context_initialise.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
_lib.fdr_debug_context_root_behaviour_count.restype  = ctypes.c_int
_lib.fdr_debug_context_root_behaviour_count.argtypes = [ctypes.c_void_p]
_lib.fdr_debug_context_root_behaviour.restype  = ctypes.c_void_p
_lib.fdr_debug_context_root_behaviour.argtypes = [ctypes.c_void_p, ctypes.c_int]
_lib.fdr_debug_context_children_count.restype  = ctypes.c_int
_lib.fdr_debug_context_children_count.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_lib.fdr_debug_context_child.restype  = ctypes.c_void_p
_lib.fdr_debug_context_child.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
_lib.fdr_debug_context_reveal_tau.restype  = ctypes.c_void_p
_lib.fdr_debug_context_reveal_tau.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
_lib.fdr_debug_context_reveal_taus_in_trace.restype  = ctypes.POINTER(ctypes.c_uint)
_lib.fdr_debug_context_reveal_taus_in_trace.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
_lib.fdr_free_events.restype  = None
_lib.fdr_free_events.argtypes = [ctypes.POINTER(ctypes.c_uint)]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INVALID_EVENT = 0
TAU           = 1

# ---------------------------------------------------------------------------
# Initialise library (call once at import time)
# ---------------------------------------------------------------------------

_lib.fdr_library_init()

def library_exit():
    """Teardown libfdr. Call at program exit if needed."""
    _lib.fdr_library_exit()

def has_valid_license() -> bool:
    return _lib.fdr_has_valid_license() != 0

def version() -> str:
    buf = ctypes.create_string_buffer(256)
    _lib.fdr_version(buf, 256)
    return buf.value.decode()

def set_option(name: str, value: str):
    _lib.fdr_set_option(name.encode(), value.encode())

def get_option(name: str) -> str:
    buf = ctypes.create_string_buffer(256)
    _lib.fdr_get_option(name.encode(), buf, 256)
    return buf.value.decode()

# ---------------------------------------------------------------------------
# Behaviour
# ---------------------------------------------------------------------------

class Behaviour:
    def __init__(self, handle: int, session: "FdrSession"):
        self._h = handle
        self._session = session

    def __del__(self):
        if self._h:
            _lib.fdr_behaviour_free(self._h)
            self._h = 0

    def trace_len(self) -> int:
        return _lib.fdr_behaviour_trace_len(self._h)

    def trace(self) -> list[int]:
        n = self.trace_len()
        return [_lib.fdr_behaviour_trace_event(self._h, i) for i in range(n)]

    def machine_name(self) -> str:
        buf = ctypes.create_string_buffer(512)
        _lib.fdr_session_machine_name_for_behaviour(self._session._h, self._h, buf, 512)
        return buf.value.decode()


# ---------------------------------------------------------------------------
# DebugContext
# ---------------------------------------------------------------------------

class DebugContext:
    def __init__(self, handle: int, session: "FdrSession"):
        self._h = handle
        self._session = session

    def __del__(self):
        if self._h:
            _lib.fdr_debug_context_free(self._h)
            self._h = 0

    def initialise(self):
        buf = ctypes.create_string_buffer(1024)
        rc = _lib.fdr_debug_context_initialise(self._h, buf, 1024)
        if rc != 0:
            raise RuntimeError(f"DebugContext.initialise failed: {buf.value.decode()}")

    def root_behaviours(self) -> list[Behaviour]:
        n = _lib.fdr_debug_context_root_behaviour_count(self._h)
        result = []
        for i in range(n):
            h = _lib.fdr_debug_context_root_behaviour(self._h, i)
            if h:
                result.append(Behaviour(h, self._session))
        return result

    def children(self, beh: Behaviour) -> list[Behaviour]:
        n = _lib.fdr_debug_context_children_count(self._h, beh._h)
        result = []
        for i in range(n):
            h = _lib.fdr_debug_context_child(self._h, beh._h, i)
            if h:
                result.append(Behaviour(h, self._session))
        return result

    def reveal_tau(self, beh: Behaviour, index: int) -> Behaviour | None:
        h = _lib.fdr_debug_context_reveal_tau(self._h, beh._h, index)
        if not h:
            return None
        return Behaviour(h, self._session)

    def reveal_taus_in_trace(self, beh: Behaviour) -> list[int]:
        count = ctypes.c_int(0)
        arr = _lib.fdr_debug_context_reveal_taus_in_trace(self._h, beh._h, ctypes.byref(count))
        if not arr:
            return []
        result = [arr[i] for i in range(count.value)]
        _lib.fdr_free_events(arr)
        return result


# ---------------------------------------------------------------------------
# Counterexample
# ---------------------------------------------------------------------------

class Counterexample:
    def __init__(self, handle: int, session: "FdrSession"):
        self._h = handle
        self._session = session

    def __del__(self):
        if self._h:
            _lib.fdr_ce_free(self._h)
            self._h = 0

    def is_property(self) -> bool:
        return _lib.fdr_ce_is_property(self._h) != 0

    def property_behaviour(self) -> Behaviour | None:
        h = _lib.fdr_ce_property_behaviour(self._h)
        if not h:
            return None
        return Behaviour(h, self._session)

    def debug_context(self, elide_uninteresting: bool = True) -> DebugContext:
        h = _lib.fdr_debug_context_new(self._h, 1 if elide_uninteresting else 0)
        if not h:
            raise RuntimeError("Could not create DebugContext — CE is not a PropertyCounterexample?")
        return DebugContext(h, self._session)


# ---------------------------------------------------------------------------
# Assertion
# ---------------------------------------------------------------------------

class FdrAssertion:
    def __init__(self, handle: int, session: "FdrSession"):
        self._h = handle
        self._session = session

    def __del__(self):
        if self._h:
            _lib.fdr_assertion_free(self._h)
            self._h = 0

    def execute(self):
        buf = ctypes.create_string_buffer(1024)
        rc = _lib.fdr_assertion_execute(self._h, buf, 1024)
        if rc != 0:
            raise RuntimeError(f"Assertion.execute failed: {buf.value.decode()}")

    def passed(self) -> bool:
        return _lib.fdr_assertion_passed(self._h) != 0

    def to_string(self) -> str:
        buf = ctypes.create_string_buffer(512)
        _lib.fdr_assertion_to_string(self._h, buf, 512)
        return buf.value.decode()

    def counterexamples(self) -> list[Counterexample]:
        n = _lib.fdr_assertion_counterexample_count(self._h)
        result = []
        for i in range(n):
            h = _lib.fdr_assertion_counterexample(self._h, i)
            if h:
                result.append(Counterexample(h, self._session))
        return result


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

class FdrSession:
    def __init__(self, csp_file: str | None = None):
        self._h = _lib.fdr_session_new()
        if csp_file:
            self.load(csp_file)

    def __del__(self):
        if self._h:
            _lib.fdr_session_free(self._h)
            self._h = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if self._h:
            _lib.fdr_session_free(self._h)
            self._h = 0

    def load(self, path: str):
        buf = ctypes.create_string_buffer(2048)
        rc = _lib.fdr_session_load_file(self._h, path.encode(), buf, 2048)
        if rc != 0:
            raise RuntimeError(f"Session.load_file failed: {buf.value.decode()}")

    def assertions(self) -> list[FdrAssertion]:
        n = _lib.fdr_session_assertion_count(self._h)
        return [
            FdrAssertion(_lib.fdr_session_assertion(self._h, i), self)
            for i in range(n)
        ]

    def uncompile_event(self, event: int) -> str:
        buf = ctypes.create_string_buffer(512)
        _lib.fdr_session_uncompile_event(self._h, event, buf, 512)
        return buf.value.decode()

    def machine_name_for(self, beh: Behaviour) -> str:
        buf = ctypes.create_string_buffer(512)
        _lib.fdr_session_machine_name_for_behaviour(self._h, beh._h, buf, 512)
        return buf.value.decode()
