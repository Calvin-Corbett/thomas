"""
DFA construction from NFA using subset construction.

Implements epsilon closure computation and Hopcroft's minimization algorithm.
"""

from __future__ import annotations

from .nfa import NFA, NFAState


class DFAState:
    """Represents a state in the DFA."""

    _counter = 0

    def __init__(self, nfa_states: set[NFAState]) -> None:
        """Initialize DFA state from set of NFA states."""
        self.state_id = DFAState._counter
        DFAState._counter += 1

        self.nfa_states = nfa_states
        self.is_accepting = False  # Will be set based on whether NFA end state is included
        self.transitions: dict[str, DFAState] = {}

    def __hash__(self) -> int:
        """Hash based on NFA states."""
        return hash(frozenset(s.state_id for s in self.nfa_states))

    def __eq__(self, other: object) -> bool:
        """Equality based on NFA states."""
        if not isinstance(other, DFAState):
            return False
        return self.nfa_states == other.nfa_states

    def __repr__(self) -> str:
        """Return string representation."""
        return f"DFAState({self.state_id}, {len(self.nfa_states)} NFA states)"


class DFA:
    """Deterministic finite automaton."""

    def __init__(self, start: DFAState, end_state_id: int) -> None:
        """Initialize DFA."""
        self.start = start
        self.end_state_id = end_state_id
        self.states: dict[frozenset[int], DFAState] = {}

    def all_states(self) -> set[DFAState]:
        """Get all reachable states."""
        states = set()
        stack = [self.start]

        while stack:
            state = stack.pop()
            if state not in states:
                states.add(state)
                stack.extend(state.transitions.values())

        return states


class SubsetConstructor:
    """Builds DFA from NFA using subset construction."""

    def __init__(self, nfa: NFA) -> None:
        """Initialize constructor."""
        self.nfa = nfa
        self.nfa_end_state_id = nfa.end.state_id

    def construct(self) -> DFA:
        """Construct DFA from NFA."""
        # Start with epsilon closure of NFA start state
        start_closure = self._epsilon_closure({self.nfa.start})
        start_dfa_state = DFAState(start_closure)
        start_dfa_state.is_accepting = self.nfa.end in start_closure

        # Queue of DFA states to process
        unprocessed = [start_dfa_state]
        processed: dict[frozenset[int], DFAState] = {}
        processed[frozenset(s.state_id for s in start_closure)] = start_dfa_state

        while unprocessed:
            dfa_state = unprocessed.pop(0)

            # Find all possible symbols from this DFA state
            symbols = self._get_symbols(dfa_state.nfa_states)

            for symbol in symbols:
                # Move on symbol
                next_nfa_states = self._move(dfa_state.nfa_states, symbol)
                # Epsilon closure
                next_closure = self._epsilon_closure(next_nfa_states)

                if not next_closure:
                    continue

                closure_id = frozenset(s.state_id for s in next_closure)

                # Check if we've seen this state
                if closure_id not in processed:
                    next_dfa_state = DFAState(next_closure)
                    next_dfa_state.is_accepting = self.nfa.end in next_closure
                    processed[closure_id] = next_dfa_state
                    unprocessed.append(next_dfa_state)
                else:
                    next_dfa_state = processed[closure_id]

                dfa_state.transitions[symbol] = next_dfa_state

        dfa = DFA(start_dfa_state, self.nfa_end_state_id)
        dfa.states = processed
        return dfa

    def _epsilon_closure(self, states: set[NFAState]) -> set[NFAState]:
        """Compute epsilon closure of a set of NFA states."""
        closure = set()
        stack = list(states)

        while stack:
            state = stack.pop()
            if state not in closure:
                closure.add(state)
                # Add epsilon transitions
                if None in state.transitions:
                    for next_state in state.transitions[None]:
                        if next_state not in closure:
                            stack.append(next_state)

        return closure

    def _move(self, states: set[NFAState], symbol: str) -> set[NFAState]:
        """Move on symbol from set of states."""
        result = set()

        for state in states:
            if symbol in state.transitions:
                result.update(state.transitions[symbol])
            # Handle "any character" transitions
            elif "." in state.transitions and symbol != "\n":
                result.update(state.transitions["."])

        return result

    def _get_symbols(self, states: set[NFAState]) -> set[str]:
        """Get all possible symbols from states."""
        symbols = set()

        for state in states:
            for symbol in state.transitions:
                if symbol is not None:
                    symbols.add(symbol)

        return symbols


class DFAMinimizer:
    """Minimizes DFA using Hopcroft's algorithm."""

    def __init__(self, dfa: DFA) -> None:
        """Initialize minimizer."""
        self.dfa = dfa
        self.states = dfa.all_states()

    def minimize(self) -> DFA:
        """Minimize DFA using Hopcroft's algorithm."""
        if not self.states:
            return self.dfa

        # Initial partition: accepting and non-accepting states
        accepting = {s for s in self.states if s.is_accepting}
        non_accepting = {s for s in self.states if not s.is_accepting}

        partitions: list[set[DFAState]] = []
        if accepting:
            partitions.append(accepting)
        if non_accepting:
            partitions.append(non_accepting)

        # Refine partitions
        changed = True
        while changed:
            changed = False
            new_partitions: list[set[DFAState]] = []

            for partition in partitions:
                subpartitions = self._split_partition(partition, partitions)
                if len(subpartitions) > 1:
                    changed = True
                new_partitions.extend(subpartitions)

            partitions = new_partitions

        # Rebuild DFA from minimized partitions
        return self._rebuild_dfa(partitions)

    def _split_partition(self, partition: set[DFAState], partitions: list[set[DFAState]]) -> list[set[DFAState]]:
        """Split a partition based on distinguishability."""
        # Get all symbols used in transitions
        symbols = set()
        for state in partition:
            symbols.update(state.transitions.keys())

        if not symbols:
            return [partition]

        # Group states by their transition targets
        groups: dict[tuple, set[DFAState]] = {}

        for state in partition:
            key_parts = []
            for symbol in sorted(symbols):
                target = state.transitions.get(symbol)
                # Find which partition the target belongs to
                partition_idx = -1
                if target is not None:
                    for i, p in enumerate(partitions):
                        if target in p:
                            partition_idx = i
                            break
                key_parts.append(partition_idx)

            key = tuple(key_parts)
            if key not in groups:
                groups[key] = set()
            groups[key].add(state)

        return list(groups.values())

    def _rebuild_dfa(self, partitions: list[set[DFAState]]) -> DFA:
        """Rebuild DFA from minimized partitions."""
        # Find partition containing original start state
        start_partition_idx = -1
        for i, partition in enumerate(partitions):
            if self.dfa.start in partition:
                start_partition_idx = i
                break

        # Create mapping from old state to new state
        state_map: dict[DFAState, DFAState] = {}
        new_start = None

        for i, partition in enumerate(partitions):
            # Use first state in partition as representative
            rep_state = next(iter(partition))
            new_state = DFAState(rep_state.nfa_states)
            new_state.is_accepting = rep_state.is_accepting

            for old_state in partition:
                state_map[old_state] = new_state

            if i == start_partition_idx:
                new_start = new_state

        # Add transitions
        for old_state, new_state in state_map.items():
            for symbol, target in old_state.transitions.items():
                if target in state_map:
                    new_target = state_map[target]
                    new_state.transitions[symbol] = new_target

        new_dfa = DFA(new_start, self.dfa.end_state_id)
        new_dfa.states = {frozenset(s.nfa_states): state_map[s] for s in self.states}
        return new_dfa


def construct_dfa(nfa: NFA) -> DFA:
    """Construct DFA from NFA using subset construction."""
    constructor = SubsetConstructor(nfa)
    return constructor.construct()


def minimize_dfa(dfa: DFA) -> DFA:
    """Minimize DFA using Hopcroft's algorithm."""
    minimizer = DFAMinimizer(dfa)
    return minimizer.minimize()
