from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Behaviour:
    machine_name: str
    type: str
    acceptance: list[int]
    trace: list[int]
    states: Optional[list[str]]
    child_behaviours: list[Behaviour]

    @classmethod
    def from_dict(cls, d: dict) -> Behaviour:
        return cls(
            machine_name=d.get("machine_name", "(anonymous)"),
            type=d["type"],
            acceptance=d.get("acceptance", []),
            trace=d.get("trace", []),
            states=d.get("states"),
            child_behaviours=[Behaviour.from_dict(c) for c in d.get("child_behaviours", [])],
        )


@dataclass
class Counterexample:
    type: str
    implementation_behaviour: Behaviour

    @classmethod
    def from_dict(cls, d: dict) -> Counterexample:
        return cls(
            type=d["type"],
            implementation_behaviour=Behaviour.from_dict(d["implementation_behaviour"]),
        )


@dataclass
class AssertionResult:
    assertion_string: str
    result: int  # 0 = fail, 1 = pass
    visited_states: int
    visited_transitions: int
    visited_plys: int
    counterexamples: list[Counterexample]
    errors: list[str]

    @classmethod
    def from_dict(cls, d: dict) -> AssertionResult:
        return cls(
            assertion_string=d["assertion_string"],
            result=d["result"],
            visited_states=d.get("visited_states", 0),
            visited_transitions=d.get("visited_transitions", 0),
            visited_plys=d.get("visited_plys", 0),
            counterexamples=[Counterexample.from_dict(c) for c in d.get("counterexamples", [])],
            errors=d.get("errors", []),
        )


@dataclass
class FdrOutput:
    results: list[AssertionResult]
    event_map: dict[str, str]
    file_name: str
    errors: list[str]
    warnings: list[str]

    @classmethod
    def from_dict(cls, d: dict) -> FdrOutput:
        return cls(
            results=[AssertionResult.from_dict(r) for r in d.get("results", [])],
            event_map=d.get("event_map", {}),
            file_name=d.get("file_name", ""),
            errors=d.get("errors", []),
            warnings=d.get("warnings", []),
        )
