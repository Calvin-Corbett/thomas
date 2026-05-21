"""
Minimax game tree search with alpha-beta pruning.

Implements game tree search for turn-based games with alpha-beta pruning,
transposition tables, iterative deepening, and move ordering heuristics.
"""

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from thomas.marketplace.game_ai._types import Blackboard

logger = logging.getLogger(__name__)


@dataclass
class GameNode:
    """Represents a game state in the search tree."""

    state: Blackboard
    moves: list[Any] = field(default_factory=list)
    is_maximizing: bool = True
    depth: int = 0
    hash_value: int | None = None

    def make_move(self, move: Any) -> "GameNode":
        """Apply move to create new node.

        Args:
            move: Move to apply

        Returns:
            New GameNode with move applied
        """
        # This would be implemented by the evaluator
        return GameNode(state=self.state.copy(), depth=self.depth + 1, is_maximizing=not self.is_maximizing)


class MinimaxEvaluator(ABC):
    """Abstract evaluator for game states."""

    @abstractmethod
    def evaluate(self, node: GameNode) -> float:
        """Evaluate a terminal game state.

        Args:
            node: GameNode to evaluate

        Returns:
            Score for the position (higher is better for maximizer)
        """
        pass

    @abstractmethod
    def get_moves(self, node: GameNode) -> list[Any]:
        """Get legal moves for position.

        Args:
            node: GameNode to get moves for

        Returns:
            List of legal moves
        """
        pass

    @abstractmethod
    def apply_move(self, node: GameNode, move: Any) -> GameNode:
        """Apply move to create new node.

        Args:
            node: Current node
            move: Move to apply

        Returns:
            New GameNode with move applied
        """
        pass

    @abstractmethod
    def is_terminal(self, node: GameNode) -> bool:
        """Check if node is terminal (game over).

        Args:
            node: Node to check

        Returns:
            True if node is terminal
        """
        pass

    @abstractmethod
    def order_moves(self, node: GameNode, moves: list[Any]) -> list[Any]:
        """Order moves for better pruning (killer moves, history heuristic).

        Args:
            node: Current node
            moves: Legal moves to order

        Returns:
            Ordered list of moves
        """
        pass


class MinimaxSearcher:
    """Minimax search with alpha-beta pruning and transposition tables."""

    def __init__(self, evaluator: MinimaxEvaluator, max_depth: int = 4, enable_logging: bool = False) -> None:
        """Initialize minimax searcher.

        Args:
            evaluator: Evaluator for game states
            max_depth: Maximum search depth
            enable_logging: Enable debug logging
        """
        self.evaluator = evaluator
        self.max_depth = max_depth
        self._transposition_table: dict[int, tuple[float, int]] = {}
        self._nodes_evaluated = 0
        self._nodes_pruned = 0
        self._history_heuristic: dict[str, int] = {}
        self._time_limit = float("inf")
        self._start_time = 0.0

        if enable_logging:
            logger.setLevel(logging.DEBUG)
            handler = logging.StreamHandler()
            handler.setLevel(logging.DEBUG)
            logger.addHandler(handler)

    def search(self, node: GameNode, depth: int = None) -> tuple[float, Any]:
        """Find best move using minimax with alpha-beta pruning.

        Args:
            node: Root node to search from
            depth: Search depth (uses max_depth if None)

        Returns:
            Tuple of (score, best_move)
        """
        if depth is None:
            depth = self.max_depth

        self._nodes_evaluated = 0
        self._nodes_pruned = 0
        self._start_time = time.time()

        best_score = float("-inf")
        best_move = None

        moves = self.evaluator.order_moves(node, self.evaluator.get_moves(node))

        for move in moves:
            new_node = self.evaluator.apply_move(node, move)
            score = self._minimax(new_node, depth - 1, float("-inf"), float("inf"), False)

            if score > best_score:
                best_score = score
                best_move = move

        logger.debug(f"Search complete: score={best_score}, nodes={self._nodes_evaluated}, pruned={self._nodes_pruned}")

        return best_score, best_move

    def iterative_deepening(self, node: GameNode, time_limit: float = 1.0) -> tuple[float, Any]:
        """Iterative deepening search with time limit.

        Args:
            node: Root node
            time_limit: Time limit in seconds

        Returns:
            Tuple of (score, best_move)
        """
        self._time_limit = time.time() + time_limit
        best_score = 0.0
        best_move = None

        for depth in range(1, self.max_depth + 1):
            if time.time() > self._time_limit:
                break

            try:
                score, move = self.search(node, depth)
                best_score = score
                best_move = move
                logger.debug(f"ID depth {depth}: score={score}")
            except TimeoutError:
                break

        return best_score, best_move

    def _minimax(self, node: GameNode, depth: int, alpha: float, beta: float, maximizing: bool) -> float:
        """Minimax with alpha-beta pruning.

        Args:
            node: Current node
            depth: Remaining search depth
            alpha: Alpha value for pruning
            beta: Beta value for pruning
            maximizing: True if maximizing player

        Returns:
            Score of position
        """
        # Check time limit
        if time.time() > self._time_limit:
            raise TimeoutError("Time limit exceeded")

        # Check transposition table
        if node.hash_value and node.hash_value in self._transposition_table:
            cached_score, cached_depth = self._transposition_table[node.hash_value]
            if cached_depth >= depth:
                return cached_score

        # Terminal node or max depth reached
        if depth == 0 or self.evaluator.is_terminal(node):
            score = self.evaluator.evaluate(node)
            self._nodes_evaluated += 1
            return score

        moves = self.evaluator.order_moves(node, self.evaluator.get_moves(node))

        if maximizing:
            max_eval = float("-inf")

            for move in moves:
                new_node = self.evaluator.apply_move(node, move)
                eval_score = self._minimax(new_node, depth - 1, alpha, beta, False)

                max_eval = max(max_eval, eval_score)
                alpha = max(alpha, eval_score)

                if beta <= alpha:
                    self._nodes_pruned += len(moves) - moves.index(move) - 1
                    break

            # Store in transposition table
            if node.hash_value:
                self._transposition_table[node.hash_value] = (max_eval, depth)

            return max_eval
        else:
            min_eval = float("inf")

            for move in moves:
                new_node = self.evaluator.apply_move(node, move)
                eval_score = self._minimax(new_node, depth - 1, alpha, beta, True)

                min_eval = min(min_eval, eval_score)
                beta = min(beta, eval_score)

                if beta <= alpha:
                    self._nodes_pruned += len(moves) - moves.index(move) - 1
                    break

            # Store in transposition table
            if node.hash_value:
                self._transposition_table[node.hash_value] = (min_eval, depth)

            return min_eval

    def clear_transposition_table(self) -> None:
        """Clear the transposition table cache."""
        self._transposition_table.clear()

    def get_stats(self) -> dict[str, int]:
        """Get search statistics.

        Returns:
            Dictionary with search stats
        """
        return {
            "nodes_evaluated": self._nodes_evaluated,
            "nodes_pruned": self._nodes_pruned,
            "tt_size": len(self._transposition_table),
        }


class SimpleMinimaxEvaluator(MinimaxEvaluator):
    """Simple evaluator for demonstration purposes."""

    def __init__(
        self,
        eval_func: Callable[[GameNode], float],
        moves_func: Callable[[GameNode], list[Any]],
        apply_move_func: Callable[[GameNode, Any], GameNode],
        terminal_func: Callable[[GameNode], bool],
    ) -> None:
        """Initialize with custom functions.

        Args:
            eval_func: Evaluation function
            moves_func: Get legal moves function
            apply_move_func: Apply move function
            terminal_func: Check terminal function
        """
        self._eval_func = eval_func
        self._moves_func = moves_func
        self._apply_move_func = apply_move_func
        self._terminal_func = terminal_func

    def evaluate(self, node: GameNode) -> float:
        """Evaluate position."""
        return self._eval_func(node)

    def get_moves(self, node: GameNode) -> list[Any]:
        """Get legal moves."""
        return self._moves_func(node)

    def apply_move(self, node: GameNode, move: Any) -> GameNode:
        """Apply move."""
        return self._apply_move_func(node, move)

    def is_terminal(self, node: GameNode) -> bool:
        """Check if terminal."""
        return self._terminal_func(node)

    def order_moves(self, node: GameNode, moves: list[Any]) -> list[Any]:
        """Order moves (simple: just return as-is)."""
        return moves
